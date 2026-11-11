---
name: raats-dynamic-trading
category: trading
description: RAATS live trading - batch discovery and analysis, Discord batch approval into FinalInvestPool, Main Agent balance gate, per-trade margin/SL/TP proposal with a second Discord approval, asynchronous entry timer, MT5 execution, adaptive SL/TP, multi-region macro-event blocking and end-of-day summary
trigger: "run RAATS live", "run dynamic trading session" or "run RAATS trading"
version: "2.0.0"
---

# RAATS Dynamic Trading Skill

RAATS has **two separate Discord approvals**, each with a different job:

| Stage | Module | Question to the human | Result |
|-------|--------|-----------------------|--------|
| 1. Batch approval | `trading_loop_dynamic.py` | "May these candidates enter `FinalInvestPool`?" | Approved tickers enter the pool |
| 2. Trade approval | `live_agents.py` (Main Agent) | "May this one trade be executed with this margin, size, SL and TP?" | Only an approved trade becomes an MT5 order |

> **First Discord approval controls what enters `FinalInvestPool`. Second Discord approval controls what becomes a live MT5 trade.**
> Batch approval never authorises execution. The asynchronous entry timer starts only after the second approval.

## Entry point

```powershell
python -m src.agents.live_agents
```

`live_agents.py` starts the Main Agent and the batch pipeline (`trading_loop_dynamic.py`). The trading loop alone no longer trades: it discovers, analyses and asks for batch approval.

## Workflow

### Stage 1 - batches (`trading_loop_dynamic.py`)

A **batch** is one pass of three threaded subagents (discovery -> news and scoring -> analysis):

1. **Discovery** finds candidates (day-gainers plus commodities and currencies), drops what the broker cannot trade and what the **ticker memory** objects to (tickers you rejected or that just lost), then ranks the rest.
2. **Scoring** scores news and sentiment (Ollama model, `RAATS_SENTIMENT_MODEL`).
3. **Analysis** runs the macro check, the RGR gate, the LLM analysts and risk validation; HOLD tickers are replaced from the waiting list.
4. The suitable candidates go to Discord for **batch approval**. The message lists the tickers and the options only: **no balance and no shortfall are shown here**.
5. Only approved tickers enter `FinalInvestPool`. A batch does not need 10 candidates; one approved ticker is enough.
6. The loop keeps processing batches while the pool has capacity and no global block exists. It pauses only when 10 positions are open and the pool holds 10.

Batch 1 is the first run of the day (gainers 1-40, commodities/currencies ranks 1-5), batch 2 continues (41-80, ranks 6-10), batch 3+ take the next unused gainers (the cursor is read from the persisted history).

**Batch naming and the daily reset:** ids look like `batch1_2026_11_08`. The counter restarts at **1 every day**, is recovered from the history after a restart on the same day (batch 4 -> batch 5), and starts at 1 on the next day. Rejected and blocked batches are never recovered: the next batch is fresh.

### Stage 2 - trades (`live_agents.py`)

When approved candidates arrive in the pool the **Main Agent** takes over. It is the only holder of the MT5 write authority; no other agent can open, change or close a position.

**Step 1 - balance gate (once, on the first approved batch)**

- Reads the real MT5 balance (3 attempts, `RAATS_BALANCE_READ_RETRIES` / `RAATS_BALANCE_RETRY_SEC`).
- Balance >= `RAATS_MIN_BALANCE` (default $20): trading may start.
- Balance below the minimum **or MetaTrader 5 not accessible**: **one** Discord message, then **both `live_agents.py` and batch discovery stop** (see "Minimum-balance gate").

**Step 2 - proposal.** For each candidate, one at a time, the Main Agent reads MT5 and calculates the available balance and free margin, the required margin, the position size (lots), the entry, the Stop Loss, the Take Profit, the risk amount and the risk-to-reward ratio.

**Step 3 - trade approval (Discord).** One message per trade, **APPROVE** or **REJECT**:

```
RAATS - Trade Execution Approval
Awaiting approval
Request: `d604cfb2`
Ticker: NKE - BUY LONG

Account balance   $10,000.00
Available margin  $10,000.00
Required margin   $5,000.00
Position size     129.5672 units
Entry price       $38.5900
Stop Loss         $35.8800
Take Profit       $46.7201
Risk amount       $351.13
Risk-to-Reward    1:3.0
```

The header also says **PAPER MODE** (simulated balance, no order goes to MT5) or **DRY RUN** (real MT5 figures, live orders disabled) when that applies, and warns when a small account trades the minimum lot at N times the size RAATS wanted. Anything other than APPROVE (REJECT, TIMEOUT, error, no Discord) means the trade is **not** executed.

**Step 4 - execution, only after APPROVE**

1. The asynchronous entry timer starts (`wait_for_entry`).
2. After the interval everything is revalidated: stop request, macro window, balance (>= minimum, readable), free margin, price. A material change (entry drift over `RAATS_REPROPOSE_DRIFT_R` R, size change over 2%, margin up over 10%) means a **new proposal and a new approval** (at most `RAATS_MAX_REPROPOSALS`).
3. `order_check()` validates the order with the broker, then `order_send()` places it. A rejected check never sends an order.
4. The fill is confirmed (partial fills are reported) and the trade is recorded.
5. The Main Agent moves to the next eligible candidate and repeats Steps 2-4.

A **rejected** trade is not executed. `RAATS_TRADE_REJECT_POLICY=skip` (default) moves on; `retry` keeps it in the pool and proposes it again after `RAATS_TRADE_REJECT_RETRY_SEC`.

**Step 5 - monitor.** Open positions are monitored every `RAATS_MONITOR_SEC` seconds. SL/TP are adapted as the risk-to-reward rises; closed trades record their PnL.

## Implementation rules

- Batch approval is not trade approval.
- Trade approval is individual: every candidate gets its own margin, size, SL and TP proposal.
- No timer before approval.
- Revalidate before execution; recalculate and ask again if the proposal changed materially.
- One global balance block stops both modules.
- Only the Main Agent executes. `_submit` refuses any order without that trade's own APPROVE.

## Configuration

### Discord

| Variable | Description |
|----------|-------------|
| `DISCORD_BOT_TOKEN` | Bot token (treat like a password; reset it in the Developer Portal if it leaks) |
| `DISCORD_CHANNEL_ID` | Channel the bot posts in |
| `DISCORD_APPROVER_ID` | Your Discord user id; reactions from anyone else are ignored |

If any is missing nothing is posted and approvals can be given by hand (below). Approvals time out after 10 minutes (`DiscordNotifier(approval_timeout_minutes=...)`); a timeout is never an approval.

### Trading mode

| Variable | Description | Default |
|----------|-------------|---------|
| `RAATS_USE_MT5` | `1`/`true`/`yes` force MT5 mode, `0`/`false`/`no` force paper (simulated 10,000). **Unset = auto**: MT5 mode when the terminal answers with a balance | auto |
| `RAATS_LIVE_TRADING` | Orders are only **sent** when `1`; otherwise MT5 mode is a dry run (real figures, no order) | off |
| `RAATS_MT5_MAGIC` / `RAATS_MT5_DEVIATION` | Magic number (RAATS only touches its own positions) / allowed slippage | `77010` / `20` |
| `RAATS_MT5_SYMBOL_MAP` | JSON symbol overrides, e.g. `{"CL=F": "USOIL"}` | `{}` |
| `RAATS_REQUIRE_APPROVAL` | Ask for the batch approval on Discord | on in the live pipeline |

### Balance and sizing

| Variable | Description | Default |
|----------|-------------|---------|
| `RAATS_MIN_BALANCE` | Minimum MT5 balance. `0` keeps paper-trading while unfunded | `20` |
| `RAATS_BALANCE_READ_RETRIES` / `RAATS_BALANCE_RETRY_SEC` | Attempts / seconds between attempts when MT5 gives no balance | `3` / `2` |
| `RAATS_SMALL_ACCOUNT_BALANCE` | Below this, a size under the broker minimum trades the **minimum lot** (above it the trade waits) | `200` |
| `RAATS_MAX_MIN_LOT_OVERSIZE` | Cap on how many times RAATS's own size the minimum lot may be (`0` = no cap) | `0` |
| `RAATS_MARGIN_RESERVE_PCT` | Free margin kept back | `0` |
| `RAATS_MAX_SPREAD_FRAC_OF_RISK` | Skip when the spread exceeds this fraction of the risk | `0.5` |
| `RAATS_TP_HEADROOM_RR` | Take-profit headroom in R | `1.0` |

### Flow control

| Variable | Description | Default |
|----------|-------------|---------|
| `RAATS_MAX_POSITIONS` / `RAATS_POOL_TARGET` | Open-position limit / pool size that pauses discovery | `10` / `10` |
| `RAATS_APPROVAL_JOIN_SEC` | How long a trade approval is awaited before monitoring continues in the background | `0.2` |
| `RAATS_REPROPOSE_DRIFT_R` / `RAATS_MAX_REPROPOSALS` | Material-change threshold / re-asks per trade | `0.25` / `3` |
| `RAATS_TRADE_REJECT_POLICY` / `RAATS_TRADE_REJECT_RETRY_SEC` | `skip` or `retry` / delay before a retry | `skip` / `3600` |
| `RAATS_DEFER_RETRY_SEC` | Retry delay for a trade that cannot be paid for yet | `60` |
| `RAATS_MONITOR_SEC` | Position monitoring interval | `30` |
| `RAATS_CANDIDATE_TTL_MIN` | Minutes a pool candidate may wait **before its trade approval is requested**; older ones are dropped (`candidate_expired`). `0` = kept until used | `0` |
| `RAATS_STATE_FILE` | Where the pool is saved so a restart can pick it up | `data/state/live_discovery.json` |
| `RAATS_RESTORE_MAX_AGE_MIN` | On start, a saved candidate is restored **only if it was saved today and its analysis is younger than this**; older analysis is discarded, never reused | `30` |
| `RAATS_BLOCKED_BATCH_PAUSE_SEC` | Wait after a batch **fails with an error**, before the next batch (not used for insufficient funds, which stops everything) | `900` |
| `RAATS_REJECTED_BATCH_PAUSE_SEC` | Wait after you **reject a batch** before the next one (`0` = start the next batch at once) | `0` |
| `RAATS_MACRO_RETRY_SEC` | Wait after a **macro-event window** blocks a batch, then try a fresh batch | `600` |
| `RAATS_RUNNER_POLL_SEC` | How often the batch loop checks for a stop request or free pool space while waiting | `2` |
| `RAATS_STOP_FILE` | Create this file to stop the agents | `data/STOP` |
| `RAATS_HISTORY_DAYS` | Daily history kept in the indicator cache | `180` |
| `RAATS_MEMORY_DIR` | Folder for the summary JSONL | `data/summaries` |
| `RAATS_DISCORD_SUMMARY` | Post the end-of-day summary to Discord | off |
| `RAATS_MACRO_API_KEY` | TradingEconomics key; if set, the API is used **before** the static file | unset |
| `RAATS_SENTIMENT_MODEL` | Ollama model that scores news | `qwen2.5:3b` |

## Minimum-balance gate

Runs in the Main Agent when the **first approved batch** reaches the pool, not before discovery and not inside the batch approval (which never shows a balance).

If the balance is below the minimum, **or cannot be read** (MetaTrader 5 not accessible - an unverified balance is never sufficient), Discord gets **one** message and nothing else:

```
ACCOUNT BALANCE INSUFFICIENT

No trades were opened.

Balance: $0.74

Minimum required: $20.00

Short by: $19.26

Please deposit at least $19.26.

Blocked tickers: TEM.
```

With MT5 unreachable the balance line reads `unavailable (MetaTrader 5 is not accessible)` and asks you to make sure MetaTrader 5 is running and logged in.

Then, on the first run: the **global block** is set (`GLOBAL_STATE`), both `live_agents.py` and batch discovery stop (a batch still waiting for Discord is cancelled), the batches involved are recorded `INSUFFICIENT_FUNDS`, the saved pool is discarded, and a `status: BLOCKED` record goes to `data/summaries/sessions_YYYY-MM.jsonl` (`blocked_reason` `insufficient_balance` or `mt5_unavailable`) and a line to `data/approvals/insufficient_funds_<Mon>_to_<Sun>.jsonl`.

Before every order is sent the minimum is checked again, so a balance that fell during the entry timer defers the trade.

## Broker symbol list (first guardrail)

RAATS only works with tickers the broker actually offers. `src/data/broker_symbols.py` reads the broker's own symbol list once (`mt5.symbols_get()`, through the locked order-layer session, never shutting MT5 down) and saves it to `data/broker/symbols_<server>.json`.

- **Discovery:** when the 40 equities are chosen from Yahoo's 250 candidates (day gainers, then most-active, reserve and emergency top-ups), a ticker the broker does not list is **never pulled in**: it is not ranked, scored or analysed, and the next candidate takes its place. The console prints `Broker filter: N ticker(s) not offered by the broker...`. Commodities and currencies are checked against the same list in the MT5 filter after ranking.
- **Naming styles:** matches `AAPL`, `AAPL.US`, `TSLA_i` and prefix styles such as `#GFS`, using the project's own symbol map and `RAATS_MT5_SYMBOL_MAP` first. Only FULL-trading (long and short) symbols count; a share ticker is never matched to a Forex/Metals/Index symbol. `mt5_bridge.resolve_mt5_symbol` falls back to the list too, and a "not offered" answer is remembered for 10 minutes, no longer forever.
- **Cache and fail-open:** refreshed when older than `RAATS_BROKER_CATALOG_HOURS` (24); if MT5 is unreachable the newest cached file is used; with no MT5 and no cache there is no filtering (a warning is printed), never a crash. A new account or broker needs nothing: the file is per server.
- **One MT5 decision:** the MT5 filter in `discovery.py` now asks the same `mt5_enabled()` as the trading loop. Before, it read `RAATS_USE_MT5` itself, so with the variable unset (auto mode) the loop ran on the real account but the filter was silently skipped and an untradable ticker such as ORKA got through.
- **Live agents (second guardrail):** if a ticker is still not found on MT5 when a trade is prepared, it is reported to the **ticker memory** (`not_tradable`) and not proposed for `RAATS_MEMORY_UNTRADABLE_DAYS` (30); MT5 trading restricted on the symbol is remembered for 7 days. It is recorded **only when the terminal answered**, so an MT5 outage is never remembered as "not offered".

See what your broker offers (run once, MT5 open and logged in):

```powershell
python -m src.data.broker_symbols                 # refresh and summarise
python -m src.data.broker_symbols ORKA AAPL NKE   # how each ticker resolves
```

| Variable | Description | Default |
|----------|-------------|---------|
| `RAATS_BROKER_FILTER` | `0` switches the broker list off (paper mode, `RAATS_USE_MT5=0`, does too) | on |
| `RAATS_BROKER_CATALOG_HOURS` | Cache age before a refresh from MT5 | `24` |
| `RAATS_BROKER_DIR` | Folder for the cache | `data/broker` |

## Macro events

Entries are blocked **window_minutes before and after** every MEDIUM or HIGH event (30 minutes by default). The check runs per ticker before a trade is proposed and again after the entry timer.

- **Global events** (Fed, ECB, US CPI and jobs report) block every ticker.
- **Regional events** (Bank of England, Bank of Canada, China CPI/PMI/GDP/loan-rate fixing, US PCE) block only assets that trade in the currencies they move, through `asset_currencies()` (e.g. `GBPUSD=X` -> GBP and USD, `^FTSE` -> GBP, `NKE` -> USD).
- **Calendar:** `src/data/macro_calendar.json` (next to `macro_events.py`), covering 2026-11-09 to 2027-12-31. Times are UTC with the official local time kept in `local_time`, so daylight saving is handled. Events marked `confirmed: false` are indicative (China's 2027 releases, the monthly loan-rate fixing): check them when the agency publishes its calendar. US PCE/GDP/retail sales/ISM for 2027, and Eurozone, UK and Canadian data releases, are not in the file.
- On first use the calendar is verified; an empty or expiring calendar sends one Discord alert. A failing macro check also alerts (it never silently disables the block) but does not stop trading.
- With `RAATS_MACRO_API_KEY` the API is used first; its events carry no region or currency and therefore block everything.
- Weekend dates are warned about, except China (its statistics bureau publishes on weekends).

## MT5

Requirements: Windows (native Python, not WSL), MT5 terminal installed and logged in, `pip install MetaTrader5`.

- Everything goes through `mt5_orders.py`: one lock, automatic reconnect, **no `mt5.shutdown()`**. Background code must read balances with `mt5_orders.account_balance()`, not `mt5_bridge.get_account_balance()` (which shuts MT5 down after each call).
- Symbols are resolved from Yahoo names (`GC=F` -> `XAUUSD`, equities with broker suffixes). A symbol is tradable only with FULL trade mode.
- Sizing (`mt5_sizing.py`): units -> lots, rounded **down** to the volume step (`volume_min + k * step`), never up. Below the broker minimum a trade is not placeable, except the small-account minimum-lot exception above (its oversize is shown in the approval).
- Margin is checked with `order_calc_margin` against free margin per trade.
- Live orders: `order_check()` first, then `order_send()`; partial fills are reported. Without `RAATS_LIVE_TRADING=1` nothing is sent. **A dry run skips `order_check`, so it can accept trades a live run would reject.**
- Always test on a **demo account** first.

## Data

`collector.py` keeps `data/processed/indicators/<TICKER>_indicators.csv` (about 6 months of daily bars). In live mode a cache older than the previous business day is refreshed automatically; RSI is blank for its first 14 bars (warm-up). Historical simulations (`as_of`) never refresh and never use live news.

## Approval flow and logs

Stage 1 reactions: tick = APPROVE, cross = REJECT, note = MODIFY (MODIFY has no edit step and counts as not approved). Stage 2 offers APPROVE and REJECT only. Only `DISCORD_APPROVER_ID` counts; REJECT beats MODIFY beats APPROVE.

Every request, batch or trade, is one append-only line per state change in `data/approvals/approval_requests_<Mon>_to_<Sun>.jsonl` (fields include `request_id`, `kind` = `batch` or `trade`, `proposal`, `status` `PENDING` -> `COMPLETED`/`TIMEOUT`, `user_response`, `response_source`). Approve without Discord:

```powershell
python -m src.notifications.discord_notifier pending
python -m src.notifications.discord_notifier respond <request_id> APPROVE     # or REJECT
```

## Summaries and memory

`SummarizationMiddleware` appends a record to `data/summaries/sessions_YYYY-MM.jsonl` (shared with the batch history), calls `log_session_summary()` and optionally posts to Discord. It holds the final INVEST list, open and closed positions with levels, RGR rejections, HOLD and replacement history, MT5 data, PnL and win rate, and the start/closing balance (read without shutting MT5 down). `_save_to_hermes_memory()` is still a **placeholder**; the cross-session memory that exists is the ticker memory below.

### Ticker memory (`src/data/ticker_memory.py`)

A short-term, **advisory** memory so RAATS does not propose again what you just rejected or what just lost money. It is an append-only event log, `data/memory/ticker_events.jsonl`, written by the Main Agent:

| Event | Recorded when | Effect |
|-------|---------------|--------|
| `trade_rejected` | you press REJECT on a **trade** approval | ticker not proposed again for `RAATS_MEMORY_REJECT_DAYS` trading days (2) |
| `closed` | a position closes | a **loss** blocks the ticker for `RAATS_MEMORY_LOSS_COOLDOWN_DAYS` trading days (2); a win or flat close does nothing |
| `seen` | a trade for the ticker was **proposed to you** (it passed the balance gate) | none yet (history for a later recurrence flag) |
| `batch_rejected` | the ticker was in a batch you rejected | none: a batch is all-or-nothing, so it says nothing about the ticker |
| `not_tradable` | a ticker is not found on MT5 at trade time (terminal reachable), or its trading is restricted | not proposed for `RAATS_MEMORY_UNTRADABLE_DAYS` (30; 7 for a restriction) |

Rules it follows:

- **Tickers blocked for insufficient funds never ran, so nothing is recorded for them.** Memory events are written only when something actually happens to a ticker: a trade is proposed, you reject it, or it closes.
- It is read in **two places**. (1) The batch pipeline (`trading_loop_dynamic.py`) drops remembered tickers from the ranked table right after discovery and the MT5 filter, **before** the top 10, the news and the LLM scoring, so the next-best tickers move up and no analysis time is spent on them; the skipped tickers are printed with the reason, and the discovery cursor still moves past them. (2) The Main Agent checks again before proposing a trade, as a safety net. If the filter would remove every instrument it is not applied, and a failing memory never stops discovery.
- It only decides whether to **propose** a ticker. A candidate you already approved is never blocked, and it never overrides the balance gate, macro block, risk checks or your approval. The skip is announced on Discord once per ticker.
- A **timeout or an error is never a rejection** and is not recorded as one. With `RAATS_TRADE_REJECT_POLICY=retry` rejections are not recorded either (you asked to be asked again).
- Analysis is always re-run on fresh data; weekends are skipped when counting trading days (market holidays are not known, so a cooldown can end slightly early).
- Events older than `RAATS_MEMORY_KEEP_DAYS` (14) are ignored. `check(..., as_of=...)` only sees events up to that moment, so simulations have no look-ahead.
- Memory never breaks trading: file errors are logged and ignored.

| Variable | Description | Default |
|----------|-------------|---------|
| `RAATS_TICKER_MEMORY` | `0` switches it off | `1` |
| `RAATS_TICKER_MEMORY_FILE` | Event log | `data/memory/ticker_events.jsonl` |
| `RAATS_MEMORY_REJECT_DAYS` | Trading days a rejected trade blocks its ticker | `2` |
| `RAATS_MEMORY_LOSS_COOLDOWN_DAYS` | Trading days after a losing close | `2` |
| `RAATS_MEMORY_UNTRADABLE_DAYS` | Calendar days a ticker the broker does not offer is skipped | `30` |
| `RAATS_MEMORY_KEEP_DAYS` | Calendar days a rejection or loss event stays relevant | `14` |

Deliberately not done: the analysts do not see the memory or the recurrence count (`times_seen`), and the summarization middleware does not write to it (the Main Agent is the only writer, so each event is recorded once).

## Files

```
data/
|-- approvals/approval_requests_<Mon>_to_<Sun>.jsonl     batch + trade approvals
|-- approvals/insufficient_funds_<Mon>_to_<Sun>.jsonl    balance-gate log
|-- summaries/sessions_YYYY-MM.jsonl                     batch history + end-of-day summaries
|-- processed/indicators/<TICKER>_indicators.csv         indicator cache (refreshed daily)
|-- state/live_discovery.json                            persisted pool
|-- memory/ticker_events.jsonl                           ticker memory (rejections, losing closes, sightings, untradable)
|-- broker/symbols_<server>.json                         the broker's own symbol list (cached)
`-- STOP                                                 create to stop the agents
logs/  agent_performance_*, sentiment_analysis_*, analysis_errors_*   (weekly JSONL)
src/data/macro_calendar.json                             calendar (UTC, with local_time)
```

## Testing

```powershell
python test_two_stage_approval.py        # from the project root (paper mode, no MT5 needed)
python test_ticker_memory.py             # ticker memory rules (standard library only)
python test_broker_symbols.py            # broker symbol list (standard library only)
python -c "from src.data import mt5_orders; print(mt5_orders.account_balance())"
python -c "from src.notifications.discord_notifier import DiscordNotifier as D; print(D().send_alert('RAATS test'))"
python -m src.notifications.discord_notifier pending
```

First live run: demo account, `RAATS_LIVE_TRADING=1`, and check the console for `[mt5] ... using the real account`. To test the low-balance path set `RAATS_MIN_BALANCE` above your balance: you should get one alert and both modules should stop.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Approval shows **PAPER MODE** and a $10,000 balance | MT5 mode is off. Leave `RAATS_USE_MT5` unset (auto) or set `1`, and check the terminal is open and logged in |
| Approval shows **DRY RUN** | `RAATS_LIVE_TRADING` is not `1`; no order will be sent |
| "ACCOUNT BALANCE INSUFFICIENT" with `unavailable` | MT5 is not running or not logged in |
| No Discord trade approval arrives | `DiscordNotifier` must have `send_trade_approval_request`; check the three `DISCORD_*` variables |
| "Macro calendar problem" alert | `macro_calendar.json` missing from `src/data/` or expiring |
| "Macro-event check FAILED" alert | Fix the import/calendar error; entries are unprotected until then |
| Trade waits, nothing opens | Macro window, free margin, spread cap or balance revalidation; the reason is logged and alerted |
| An untradable ticker (e.g. ORKA) reaches the pool | Run `python -m src.data.broker_symbols` with MT5 open to build the list; check the console for `[broker] symbol list: N symbols` and `Broker filter:` lines |
| `[broker] MT5 not reachable: using the cached symbol list` | MT5 was closed; the saved list is used, which is fine unless you changed broker |
| Stale indicators | Delete the cache file, or check the refresh warning in the log |

## Known limitations

- Batch approval is all-or-nothing per batch.
- A dry run skips `order_check`.
- China 2027 dates and the loan-rate fixing are unconfirmed; Eurozone/UK/Canadian data releases and 2027 US PCE/GDP/retail sales/ISM are not in the calendar.
- Ticker memory is phase 1 only: rejections and losing closes block a ticker; recurrence is recorded but not yet shown to the analysts.
- Some legacy balance code in `trading_loop_dynamic.py` (`_balance_ok`, sink `read_balance`) is unused.
- These settings are defined but have **no effect** in the current code: `RAATS_BATCH_POOL` (default 50), `RAATS_EXHAUSTED_RETRY_SEC` (default 600) and `RAATS_BATCH_BALANCE_RETRY_SEC` (only used by the unused `_balance_ok`). Setting them changes nothing.
- The calendar is only as accurate as the file you maintain.

## License

Part of RAATS (Research Algorithmic Automated Trading System)
MSc Computer Science, University of Fort Hare