---
name: raats-dynamic-trading
category: trading
description: RAATS dynamic trading pipeline - discovery, macro-event check, MT5 broker filter, RGR gate, iterative analysis with replacements, Discord approval, minimum-balance guard and end-of-day summary
trigger: "run dynamic trading session" or "run RAATS trading"
version: "1.1.0"
---

# RAATS Dynamic Trading Skill

Runs the full RAATS pipeline, in this order:

1. **Discovery** (`discovery.main()`) - day-gainers screener, previous-session returns, optional MT5 broker filter, macro check, then the three arrays: top 50, top 10 (with news), waiting list.
2. **Macro event check** - blocks the session inside a high-impact event window.
3. **Starting balance** - read once from MT5 (only when MT5 is enabled) for the end-of-day summary.
4. **RGR gate** - every ticker must pass `rgr_screen.screen_candidate()` to join the active list (initial top 10 and every waiting-list replacement).
5. **Analysis rounds** - collector, stability, analyst, executor; HOLD tickers are replaced from the waiting list until every active ticker is INVEST or the waiting list is empty. Paper positions are opened during these rounds.
6. **MT5 data for the final INVEST list** - broker symbol, tradable flag, spread (so the approver sees them).
7. **Minimum-balance guard** - blocks the session if the MT5 balance is below `RAATS_MIN_BALANCE` (default $20). Runs whether or not approval is required.
8. **Discord approval** (optional) - you react on the message. Anything other than APPROVE discards this session's paper positions.
9. **Balance re-check** after approval.
10. **Summary** - JSONL summary, standard logger, optional Discord post.

## Quick start (Windows PowerShell)

```powershell
# Discord (required for approval / summary)
$env:DISCORD_BOT_TOKEN   = "..."        # bot token - treat like a password
$env:DISCORD_CHANNEL_ID  = "..."        # channel the bot posts in
$env:DISCORD_APPROVER_ID = "..."        # YOUR Discord user id - the only person who can approve

# Behaviour
$env:RAATS_USE_MT5           = "1"      # MT5 filter in discovery AND symbol lookup + balance guard in the loop
$env:RAATS_REQUIRE_APPROVAL  = "1"      # ask on Discord before finishing the session
$env:RAATS_DISCORD_SUMMARY   = "1"      # post the end-of-day summary to Discord

python -m src.agents.trading_loop_dynamic
```

If you keep these in a `.env` file instead, something in the project must load it (for example `python-dotenv`), and `.env` must be in `.gitignore`. Never commit the bot token; if it is ever pasted or committed, reset it in the Discord Developer Portal.

## Configuration

### Discord

| Variable | Description |
|----------|-------------|
| `DISCORD_BOT_TOKEN` | Bot token from the Developer Portal |
| `DISCORD_CHANNEL_ID` | Channel the bot posts in |
| `DISCORD_APPROVER_ID` | Your Discord user id. Reactions from anyone else (and from the bot) are ignored |

If any of the three is missing, nothing is posted and approvals can still be given by hand (see below).

### Pipeline

| Variable | Description | Default |
|----------|-------------|---------|
| `RAATS_USE_MT5` | Enable the MT5 broker filter in discovery, and `enable_mt5` in the trading loop's entry point | off |
| `RAATS_MT5_SYMBOL_MAP` | JSON overrides for symbol names, e.g. `{"CL=F": "USOIL"}` | `{}` |
| `RAATS_MIN_BALANCE` | Minimum MT5 balance in dollars | `20` |
| `RAATS_REQUIRE_APPROVAL` | Ask for approval on Discord | off |
| `RAATS_DISCORD_SUMMARY` | Post the end-of-day summary to Discord | off |
| `RAATS_MACRO_API_KEY` | TradingEconomics key; without it the static calendar is used | unset |
| `RAATS_MEMORY_DIR` | Folder for the summary JSONL | `data/summaries` |
| `RAATS_SENTIMENT_MODEL` | Ollama model that scores news | `mistral-nemo` |

`RAATS_WHATSAPP_SUMMARY`, `WHATSAPP_PHONE` and `WHATSAPP_WEBHOOK_URL` no longer exist. Delete `whatsapp.py`: it contains a hard-coded phone number.

## Discord setup (about 10 minutes, free, no review process)

The bot only makes outbound calls to Discord, so there is no webhook, public URL or ngrok.

1. discord.com/developers/applications -> **New Application** -> **Bot** -> **Reset Token** and copy it.
2. **OAuth2 -> URL Generator**: scope `bot`; permissions View Channel, Send Messages, Add Reactions, Read Message History. Open the URL and add the bot to a private server you created. No privileged intents are needed.
3. Discord Settings -> Advanced -> **Developer Mode** on. Right-click the channel -> Copy Channel ID; right-click your name -> Copy User ID.
4. Set the three `DISCORD_*` variables.
5. Test (tap the tick on your phone; it should print `APPROVE`):
   ```powershell
   python -c "from src.notifications.discord_notifier import DiscordNotifier as D; print(D().request_approval(['AAPL','MSFT'], None, 10000))"
   ```

## Approval flow

1. The bot posts the final INVEST list with MT5 symbols, spreads and the balance, and adds the reactions: tick = **APPROVE**, cross = **REJECT**, note = **MODIFY**.
2. RAATS checks every 5 seconds for up to 10 minutes.
3. Safety rules: only your reaction counts; if several reactions are present, REJECT beats MODIFY beats APPROVE.
4. **APPROVE** continues the session. **REJECT, MODIFY or TIMEOUT** return early: this session's paper positions are discarded, no summary is written, and the reason is logged to `analysis_errors_*.jsonl` with `stage: "approval"`. MODIFY has no edit step yet, so it is treated as not approved.

The approval timeout is 10 minutes. To change it, edit `_get_notifier()` in `trading_loop_dynamic.py`: `DiscordNotifier(approval_timeout_minutes=30)`.

### Approval log (JSONL)

Every request is stored in one weekly file, named like the other logs:

```
data/approvals/approval_requests_<Monday>_to_<Sunday>.jsonl
e.g. data/approvals/approval_requests_2026-10-26_to_2026-11-01.jsonl
```

The log is **append-only**: a request writes a `PENDING` line when sent and a new line when it is decided; the newest line for a `request_id` is its current state. All lines of a request stay in the file it started in, even if the week changes while it waits.

| Field | Meaning |
|-------|---------|
| `request_id` | 8-character id |
| `timestamp`, `expires_at` | When it was sent / when it times out |
| `final_invest`, `mt5_data`, `account_balance` | What the approver was shown |
| `options` | `["APPROVE","REJECT","MODIFY"]` |
| `status` | `PENDING` -> `COMPLETED` or `TIMEOUT` |
| `user_response` | `APPROVE`, `REJECT`, `MODIFY` or `TIMEOUT` |
| `response_time`, `response_source` | When, and `discord` or `manual` |
| `message_id`, `log_file`, `send_error` | Discord message id, the file this request lives in, any send failure |

### Approving without Discord

The request id is printed when the request is sent.

```powershell
python -m src.notifications.discord_notifier pending
python -m src.notifications.discord_notifier respond <request_id> APPROVE     # or REJECT, MODIFY, 1, 2, 3
```

This appends a line to the same weekly file.

## Macro events

The session is blocked when the current time is within the window (default 30 minutes, 15 for jobless claims) of a MEDIUM or HIGH impact event: FOMC, CPI, NFP, PCE, GDP, ISM, retail sales, jobless claims.

- **Static calendar:** `src/data/macro_calendar.json`, maintained by hand. It is never overwritten.
- **Live calendar:** with `RAATS_MACRO_API_KEY`, downloads are cached in `macro_calendar_api_cache.json` (refreshed every 6 hours) and used if the static file is missing.
- A date that falls on a weekend is reported as a warning when the calendar loads. **Check the current file against federalreserve.gov and bls.gov before relying on it:** it contains events on Saturday 2026-11-07 (FOMC) and 2026-11-14 (retail sales), contains only one jobless-claims entry, and starts on 2026-10-30, so earlier dates cannot be checked.
- Naive times (for example a simulated date) are treated as UTC.
- The window is minutes wide but RAATS runs once a day on daily bars, so the check rarely blocks. A "high-impact release today" rule would suit a daily strategy better.

## MT5

Requirements: Windows, MT5 terminal installed and logged in, `pip install MetaTrader5`.

- Symbols are resolved from Yahoo names (`GC=F` -> `XAUUSD`, equities with suffixes such as `.US`). Override with `RAATS_MT5_SYMBOL_MAP`.
- A symbol is **tradable** only when its trade mode is FULL (RAATS opens longs and shorts). Close-only, long-only and disabled symbols are not.
- Broker coverage of small-cap day-gainers is likely to be low; the discovery filter can drop most of the list.
- If the balance cannot be read, the guard is skipped with a warning and the session continues.
- A low balance sends a Discord alert and appends to `data/approvals/insufficient_funds_<Monday>_to_<Sunday>.jsonl`.
- Do not call MT5 from threaded runs (`run_watchlist_concurrent`).

## Summarization middleware

At the end of an approved session:

1. Appends to `data/summaries/sessions_YYYY-MM.jsonl` (monthly file).
2. Calls the standard `log_session_summary()`.
3. Posts to Discord if `RAATS_DISCORD_SUMMARY` is set.

The summary holds the final INVEST list, open and closed trades, return / Sharpe / drawdown, realized and daily PnL, win rate (from the portfolio summary), RGR rejections, MT5 data, and starting / closing balance. The cross-session memory hook is a placeholder: nothing reads these files back into the agents yet.

## Files created

```
data/
|-- approvals/
|   |-- approval_requests_<Mon>_to_<Sun>.jsonl      approval log (append-only)
|   `-- insufficient_funds_<Mon>_to_<Sun>.jsonl     balance-guard log
`-- summaries/
    `-- sessions_YYYY-MM.jsonl                      end-of-day summaries
logs/
|-- agent_performance_<Mon>_to_<Sun>.jsonl
|-- sentiment_analysis_<Mon>_to_<Sun>.jsonl
`-- analysis_errors_<Mon>_to_<Sun>.jsonl            includes stage "approval" entries
src/data/
|-- macro_calendar.json                             hand-maintained
`-- macro_calendar_api_cache.json                   API downloads
```

## Usage in code

```python
from src.agents.trading_loop_dynamic import run_dynamic_trading_session
from src.data.discovery import main as run_discovery

top_50, top_10, waiting_list = run_discovery()

session = run_dynamic_trading_session(
    top_50_performing=top_50,
    top_10=top_10,
    waiting_list=waiting_list,
    portfolio_value=10_000,
    enable_rgr_gate=True,     # default True
    rgr_threshold=0.0,        # default 0.0
    enable_mt5=True,          # default False; the entry point sets it from RAATS_USE_MT5
)

print(session["final_invest"])
print(session["open_trades"])
```

## Testing

```powershell
# Macro events
python -c "from src.data.macro_events import is_trade_blocked_by_macro; print(is_trade_blocked_by_macro())"

# MT5 balance
python -c "from src.data.mt5_bridge import get_account_balance; print(get_account_balance())"

# Discord alert and approval
python -c "from src.notifications.discord_notifier import DiscordNotifier as D; print(D().send_alert('RAATS test'))"
python -c "from src.notifications.discord_notifier import DiscordNotifier as D; print(D().request_approval(['AAPL','MSFT'], None, 10000))"

# Waiting requests / answer by hand
python -m src.notifications.discord_notifier pending
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Discord not configured" | Set all three `DISCORD_*` variables; approve by hand with the `respond` command meanwhile |
| Discord send fails with 403 | The bot lacks permission in that channel: View Channel, Send Messages, Add Reactions, Read Message History |
| Reactions are ignored | `DISCORD_APPROVER_ID` must be your own user id (Developer Mode -> Copy User ID), not the bot's |
| "Approval timeout" | You have 10 minutes; see the approval flow section to change it |
| "MT5 package not installed" | `pip install MetaTrader5` (Windows only) |
| MT5 step does nothing | Set `RAATS_USE_MT5=1`; the loop's MT5 lookup and balance guard need it as well as the discovery filter |
| "MT5 balance unavailable - guard NOT applied" | Terminal not open / not logged in; the session continues without the guard |
| "macro calendar has N event(s) on a weekend" | Fix those dates in `macro_calendar.json` |
| No macro blocking at all | Calendar missing or has no event near now; check the file and its dates |
| Insufficient balance | Fund the account above `RAATS_MIN_BALANCE`; see `insufficient_funds_*.jsonl` |

## Architecture

```
discovery.py (main)
    |-- get_tickers_from_gainers_feed() -> get_previous_session_returns()
    |-- apply_mt5_filter()            (RAATS_USE_MT5)      -> mt5_bridge.py
    |-- is_trade_blocked_by_macro()                        -> macro_events.py
    `-- build_ticker_arrays() -> top 50 / top 10 + news / waiting list
            |
            v
trading_loop_dynamic.py (run_dynamic_trading_session)
    |-- macro check, starting balance
    |-- DynamicTradingManager
    |     |-- RGR gate on the initial list and every replacement   -> rgr_screen.py
    |     |-- analysis rounds + HOLD replacement (LangGraph: collector -> stability -> analyst -> executor)
    |     |-- MT5 data for the final INVEST list                   -> mt5_bridge.py
    |     |-- minimum-balance guard                                -> mt5_bridge.py -> Discord alert
    |     |-- Discord approval (APPROVE continues, otherwise positions are discarded)
    |     |                                                        -> discord_notifier.py -> approval_requests_*.jsonl
    |     |-- balance re-check
    |     `-- SummarizationMiddleware -> sessions_YYYY-MM.jsonl, log_session_summary, Discord
```

## Known limitations

- Paper positions are opened during the analysis rounds, before you are asked. A rejection discards them. When real MT5 order placement is added, orders must be sent only after approval.
- Nothing is sent to the broker today.
- MODIFY is recorded but has no edit step.
- The memory hook in the summarization middleware is a placeholder.
- The macro calendar is only as accurate as the file you maintain.

## License

Part of RAATS (Research Algorithmic Automated Trading System)
MSc Computer Science, University of Fort Hare
