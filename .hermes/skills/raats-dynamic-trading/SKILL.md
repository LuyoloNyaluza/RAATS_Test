---
name: raats-dynamic-trading
category: trading
description: Full RAATS dynamic trading pipeline with macro events, MT5 filter, WhatsApp approval, and summarization
trigger: "run dynamic trading session" or "run RAATS trading"
version: "1.0.0"
---

# RAATS Dynamic Trading Skill

This skill executes the complete RAATS trading pipeline:
1. **Discovery** - Get top 50 performers, top 10 with news, waiting list
2. **Macro Event Check** - Block trades during FOMC/CPI/NFP windows
3. **MT5 Broker Filter** - Filter by tradable symbols on your broker
4. **RGR Gate Screening** - Risk-adjusted return screening
5. **Dynamic Trading** - Iterative analysis with replacements
6. **WhatsApp Approval** - Human-in-the-loop for final INVEST list
7. **MT5 Balance Check** - Blocks if account < $20
8. **Summarization Middleware** - End-of-day summary to memory/WhatsApp

## Quick Start

```bash
# Set required environment variables
export RAATS_USE_MT5=1                    # Enable MT5 filter
export RAATS_MT5_SYMBOL_MAP='{"CL=F": "USOIL"}'  # Custom symbol mappings
export RAATS_MACRO_API_KEY=your_key       # TradingEconomics API key
export RAATS_REQUIRE_APPROVAL=1           # Enable WhatsApp approval
export WHATSAPP_WEBHOOK_URL=https://...   # WhatsApp Business API webhook
export WHATSAPP_PHONE=+27123456789        # YOUR MOBILE NUMBER HERE
export RAATS_WHATSAPP_SUMMARY=1           # Send EOD summary to WhatsApp

# Run the pipeline
python -m src.agents.trading_loop_dynamic
```

## Configuration

### Required Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `WHATSAPP_PHONE` | **YOUR MOBILE NUMBER** with country code (e.g., +27123456789) | +27123456789 |
| `WHATSAPP_WEBHOOK_URL` | WhatsApp Business API webhook endpoint | Required for approval/summary |
| `RAATS_MACRO_API_KEY` | TradingEconomics or similar API key | Uses static calendar if not set |

### Optional Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `RAATS_USE_MT5` | Enable MT5 broker filter | 0 (off) |
| `RAATS_MT5_SYMBOL_MAP` | JSON symbol overrides | {} |
| `RAATS_REQUIRE_APPROVAL` | Require WhatsApp approval before trades | 0 (off) |
| `RAATS_WHATSAPP_SUMMARY` | Send EOD summary to WhatsApp | 0 (off) |
| `RAATS_MEMORY_DIR` | Directory for session JSONL logs | ~/.hermes/memory/trading_sessions |

## Macro Events

The system blocks trades during high-impact event windows (30 min before/after):
- **FOMC** - Federal Reserve rate decisions
- **CPI** - Consumer Price Index
- **NFP** - Non-Farm Payrolls
- **PCE** - Personal Consumption Expenditures
- **GDP** - Gross Domestic Product
- **ISM** - Manufacturing/Services PMI
- **Retail Sales**
- **Jobless Claims**

### Static Calendar
Update `src/data/macro_calendar.json` quarterly with scheduled events.

### Live Calendar
Set `RAATS_MACRO_API_KEY` for TradingEconomics API (auto-refreshes every 6 hours).

## WhatsApp Integration

### Setting Up Your Mobile Number

**Option 1: Environment Variable (Recommended)**
```bash
export WHATSAPP_PHONE="+27123456789"  # ← REPLACE WITH YOUR NUMBER
```

**Option 2: Edit the Source File**
Edit `src/notifications/whatsapp.py` line 32:
```python
self.phone_number = phone_number or os.environ.get("WHATSAPP_PHONE", "+27123456789")  # ← CHANGE THIS
```

**Option 3: Pass at Runtime**
```python
from src.notifications.whatsapp import WhatsAppNotifier
notifier = WhatsAppNotifier(phone_number="+27123456789")
```

### WhatsApp Business API Setup

1. Get a WhatsApp Business Account
2. Configure webhook URL for incoming messages
3. Set `WHATSAPP_WEBHOOK_URL` to your webhook endpoint
4. The webhook should accept POST with JSON: `{"to": "...", "text": "...", "request_id": "..."}`

### Approval Flow

1. System determines final INVEST list
2. Sends WhatsApp message with:
   - Final INVEST tickers
   - MT5 symbols and spreads
   - Account balance (with warning if < $20)
3. You reply with: `APPROVE`, `REJECT`, or `MODIFY`
4. System waits up to 10 minutes (configurable)
5. On APPROVE: Re-checks balance, executes trades
6. On REJECT/TIMEOUT: Aborts, logs to JSONL

### Response File (Fallback)
If webhook isn't configured, edit the response file:
```
~/.hermes/trading/approvals/{request_id}.json
```
Change `"status": "PENDING"` to `"status": "COMPLETED"` and add `"user_response": "APPROVE"`

## MT5 Integration

### Requirements
- Windows with MetaTrader 5 terminal installed
- Logged into your broker account
- `pip install MetaTrader5`

### Symbol Mapping
Override broker-specific symbols via `RAATS_MT5_SYMBOL_MAP`:
```json
{
  "CL=F": "USOIL",
  "GC=F": "XAUUSD",
  "EURUSD=X": "EURUSD"
}
```

### Balance Check
- Fetches account balance via `mt5.account_info()`
- Blocks trades if balance < $20
- Sends WhatsApp alert and logs to `insufficient_balance.jsonl`

## Summarization Middleware

Runs at end of every session:
1. **JSONL Log** - `~/.hermes/memory/trading_sessions/sessions_YYYY-MM.jsonl`
2. **Hermes Memory** - Key facts saved for cross-session recall
3. **WhatsApp** - Optional summary to your phone
4. **Standard Logger** - Existing `log_session_summary()` call

### Session Summary Includes
- Final INVEST list
- Open/closed trades
- PnL metrics (realized, daily, win rate)
- RGR rejections
- MT5 data (symbols, spreads)
- Portfolio summary

## Files Created

```
~/.hermes/
├── memory/trading_sessions/
│   └── sessions_2026-10.jsonl      # Session history
├── trading/
│   ├── approvals/
│   │   └── {request_id}.json       # Approval requests/responses
│   └── insufficient_balance.jsonl  # Balance alerts
```

## Usage in Code

```python
from src.agents.trading_loop_dynamic import run_dynamic_trading_session
from src.data.discovery import main as run_discovery

# Step 1: Run discovery
top_50, top_10, waiting_list = run_discovery()

# Step 2: Run dynamic trading (with all features)
session = run_dynamic_trading_session(
    top_50_performing=top_50,
    top_10=top_10,
    waiting_list=waiting_list,
    portfolio_value=10_000,
    enable_rgr_gate=True,
    rgr_threshold=0.0,
    enable_mt5=True,
)

# Access results
print(f"Final INVEST: {session['final_invest']}")
print(f"Open trades: {session['open_trades']}")
print(f"Metrics: {session.get('metrics', {})}")
```

## Testing

```bash
# Test macro events
python -c "from src.data.macro_events import is_trade_blocked_by_macro; print(is_trade_blocked_by_macro())"

# Test MT5 balance
python -c "from src.data.mt5_bridge import get_account_balance; print(get_account_balance())"

# Test WhatsApp (without webhook - saves to file)
python -c "from src.notifications.whatsapp import WhatsAppNotifier; n=WhatsAppNotifier(); n.send_approval_request(['AAPL','MSFT'], {}, 10000)"

# Test summarization
python -c "from src.agents.middleware.summarization_middleware import SummarizationMiddleware; m=SummarizationMiddleware(); print('Ready')"
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "MT5 package not installed" | `pip install MetaTrader5` (Windows only) |
| "No macro calendar" | Update `macro_calendar.json` or set `RAATS_MACRO_API_KEY` |
| "WhatsApp webhook failed" | Check `WHATSAPP_WEBHOOK_URL` and webhook accepts POST JSON |
| "Approval timeout" | Increase timeout in `WhatsAppNotifier(approval_timeout_minutes=15)` |
| "Insufficient balance" | Fund MT5 account > $20, check `insufficient_balance.jsonl` |

## Architecture

```
discovery.py (main)
    │
    ├─► get_tickers_from_gainers_feed()
    ├─► build_market_universe()
    ├─► get_previous_session_returns()
    ├─► apply_mt5_filter() ──────► mt5_bridge.py
    ├─► is_trade_blocked_by_macro() ──► macro_events.py
    └─► build_ticker_arrays()
            │
            ▼
trading_loop_dynamic.py (run_dynamic_trading_session)
    │
    ├─► MacroEventChecker (blocks FOMC/CPI/NFP)
    ├─► DynamicTradingManager
    │   ├─► _screen_initial_active_list() ──► rgr_screen.py
    │   ├─► _get_replacements() (with RGR gate)
    │   ├─► run_trading_session()
    │   │   ├─► WhatsApp approval interrupt
    │   │   ├─► MT5 balance check
    │   │   └─► enrich_final_invest() ──► mt5_bridge.py
    │   └─► SummarizationMiddleware
    │       ├─► JSONL log
    │       ├─► Hermes memory
    │       └─► WhatsApp summary
    └─► LangGraph trading loop (collector→stability→analyst→executor)
```

## Customization

### Change Macro Event Window
```python
from src.data.macro_events import MacroEventChecker
checker = MacroEventChecker(default_window_minutes=60)  # 1 hour window
```

### Change Balance Threshold
```python
from src.data.mt5_bridge import check_balance_and_notify
check_balance_and_notify(min_balance=50.0)  # $50 minimum
```

### Change Approval Timeout
```python
from src.notifications.whatsapp import WhatsAppNotifier
notifier = WhatsAppNotifier(approval_timeout_minutes=30)  # 30 minutes
```

## License

Part of RAATS (Research Algorithmic Automated Trading System)
MSc Computer Science, University of Fort Hare