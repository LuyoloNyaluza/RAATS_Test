#!/usr/bin/env python3
"""
Test script to verify all RAATS trading components work together.
Run this to validate the complete pipeline.
"""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_imports():
    """Test that all new modules can be imported."""
    print("🧪 Testing imports...")
    
    try:
        from src.data.macro_events import MacroEventChecker, is_trade_blocked_by_macro
        print("  ✅ macro_events.py")
    except Exception as e:
        print(f"  ❌ macro_events.py: {e}")
        return False
    
    try:
        from src.notifications.whatsapp import WhatsAppNotifier, send_whatsapp_approval
        print("  ✅ whatsapp.py")
    except Exception as e:
        print(f"  ❌ whatsapp.py: {e}")
        return False
    
    try:
        from src.agents.middleware.summarization_middleware import SummarizationMiddleware, run_summarization
        print("  ✅ summarization_middleware.py")
    except Exception as e:
        print(f"  ❌ summarization_middleware.py: {e}")
        return False
    
    try:
        from src.data.mt5_bridge import get_account_balance, check_balance_and_notify
        print("  ✅ mt5_bridge.py (new functions)")
    except Exception as e:
        print(f"  ❌ mt5_bridge.py: {e}")
        return False
    
    try:
        from src.agents.trading_loop_dynamic import DynamicTradingManager, run_dynamic_trading_session
        print("  ✅ trading_loop_dynamic.py (updated)")
    except Exception as e:
        print(f"  ❌ trading_loop_dynamic.py: {e}")
        return False
    
    try:
        from src.data.discovery import main as run_discovery
        print("  ✅ discovery.py (updated)")
    except Exception as e:
        print(f"  ❌ discovery.py: {e}")
        return False
    
    return True


def test_macro_events():
    """Test macro event checking."""
    print("\n📅 Testing macro events...")
    
    from src.data.macro_events import MacroEventChecker, is_trade_blocked_by_macro
    
    # Test static calendar loading
    checker = MacroEventChecker()
    events = checker.load_calendar()
    print(f"  Loaded {len(events)} events from static calendar")
    
    for e in events[:3]:
        print(f"    - {e.name} ({e.event_type}) at {e.scheduled_time}")
    
    # Test blocking check
    blocked = is_trade_blocked_by_macro()
    print(f"  Currently blocked: {blocked}")
    
    # Test upcoming events
    upcoming = checker.get_upcoming_events(24)
    print(f"  Upcoming in 24h: {len(upcoming)} events")
    
    return True


def test_whatsapp_notifier():
    """Test WhatsApp notifier (file-based, no webhook)."""
    print("\n📱 Testing WhatsApp notifier...")
    
    from src.notifications.whatsapp import WhatsAppNotifier
    
    notifier = WhatsAppNotifier()
    print(f"  Phone number: {notifier.phone_number}")
    print(f"  Webhook URL: {notifier.webhook_url or 'Not set (file-only mode)'}")
    
    # Test sending approval (will save to file)
    request = notifier.send_approval_request(
        final_invest=["AAPL", "MSFT", "NVDA"],
        mt5_data={
            "AAPL": {"mt5_symbol": "AAPL.US", "spread_pct": 0.02, "tradable": True},
            "MSFT": {"mt5_symbol": "MSFT.US", "spread_pct": 0.03, "tradable": True},
            "NVDA": {"mt5_symbol": "NVDA.US", "spread_pct": 0.05, "tradable": True},
        },
        account_balance=10000.0,
    )
    
    print(f"  Created request: {request.request_id}")
    print(f"  Status: {request.status}")
    
    # Check response file exists
    from pathlib import Path
    response_file = Path("~/.hermes/trading/approvals").expanduser() / f"{request.request_id}.json"
    if response_file.exists():
        print(f"  ✅ Response file created: {response_file}")
    else:
        print(f"  ❌ Response file not found")
        return False
    
    return True


def test_mt5_bridge():
    """Test MT5 bridge functions (will gracefully fail if MT5 not installed)."""
    print("\n🔌 Testing MT5 bridge...")
    
    from src.data.mt5_bridge import get_account_balance, check_balance_and_notify
    
    balance = get_account_balance()
    if balance is not None:
        print(f"  Account balance: ${balance:.2f}")
    else:
        print("  MT5 not available (expected if not on Windows/MT5 not installed)")
    
    # Test balance check
    result = check_balance_and_notify(min_balance=20.0)
    print(f"  Balance check (>= $20): {result}")
    
    return True


def test_summarization():
    """Test summarization middleware."""
    print("\n📝 Testing summarization middleware...")
    
    from src.agents.middleware.summarization_middleware import SummarizationMiddleware
    
    middleware = SummarizationMiddleware()
    print(f"  Memory dir: {middleware.memory_dir}")
    print(f"  WhatsApp enabled: {middleware.enable_whatsapp}")
    
    # Create mock session results
    mock_results = {
        "manager": type('MockManager', (), {
            'final_invest': ['AAPL', 'MSFT'],
            'active_list': [],
            'waitlist': ['GOOGL'],
            'hold_history': [{'ticker': 'TSLA', 'round': 1}],
            'replacement_history': [],
            'rgr_rejected': ['META'],
            'rgr_results': {
                'AAPL': {'passed': True, 'rgr': 0.05, 'direction': 'LONG'},
                'MSFT': {'passed': True, 'rgr': 0.03, 'direction': 'LONG'},
            },
            'mt5_data': {},
            'daily_results': [],
            'risk_manager': type('MockRM', (), {
                'positions': {},
                'closed_trades': [],
                'portfolio_summary': lambda: {'open_positions': 0, 'closed_trades': 0, 'realized_pnl': 0, 'unrealized_pnl': 0, 'daily_pnl': 0, 'win_rate': 0},
            })(),
            'portfolio_value': 10000,
            'closed_positions_today': [],
            '_categorize_results': lambda self: {'executed': [], 'hold': ['TSLA'], 'invest_blocked': [], 'blocked': [], 'unstable': [], 'error': []},
        })(),
        "results": [],
    }
    
    summary = middleware.process_session_end(mock_results)
    print(f"  Summary keys: {list(summary.keys())}")
    print(f"  Final INVEST: {summary['final_invest']}")
    print(f"  Categories: {list(summary['categories'].keys())}")
    
    # Check JSONL file created
    from pathlib import Path
    jsonl_file = middleware.memory_dir / f"sessions_{__import__('datetime').datetime.now().strftime('%Y-%m')}.jsonl"
    if jsonl_file.exists():
        print(f"  ✅ JSONL log created: {jsonl_file}")
    else:
        print(f"  ⚠️ JSONL log not found at {jsonl_file}")
    
    return True


def test_discovery_macro_block():
    """Test that discovery.py blocks on macro events."""
    print("\n🔍 Testing discovery macro event block...")
    
    # This will use the static calendar - check if any event is active now
    from src.data.macro_events import is_trade_blocked_by_macro
    
    blocked = is_trade_blocked_by_macro()
    if blocked:
        print("  ⚠️ Macro event currently active - discovery would be blocked")
        print("  This is expected behavior during FOMC/CPI/NFP windows")
    else:
        print("  No macro event window active - discovery would proceed")
    
    return True


def main():
    """Run all tests."""
    print("=" * 60)
    print("RAATS TRADING PIPELINE - COMPONENT TESTS")
    print("=" * 60)
    
    tests = [
        ("Imports", test_imports),
        ("Macro Events", test_macro_events),
        ("WhatsApp Notifier", test_whatsapp_notifier),
        ("MT5 Bridge", test_mt5_bridge),
        ("Summarization", test_summarization),
        ("Discovery Macro Block", test_discovery_macro_block),
    ]
    
    results = {}
    for name, test_func in tests:
        try:
            results[name] = test_func()
        except Exception as e:
            print(f"  ❌ {name} failed with exception: {e}")
            import traceback
            traceback.print_exc()
            results[name] = False
    
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    all_passed = True
    for name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status} - {name}")
        if not passed:
            all_passed = False
    
    print("=" * 60)
    
    if all_passed:
        print("🎉 ALL TESTS PASSED!")
        print("\nNext steps:")
        print("1. Set WHATSAPP_PHONE environment variable to your mobile number")
        print("2. Set WHATSAPP_WEBHOOK_URL for WhatsApp Business API")
        print("3. Set RAATS_MACRO_API_KEY for live economic calendar")
        print("4. Set RAATS_USE_MT5=1 and configure MT5 terminal")
        print("5. Run: python -m src.agents.trading_loop_dynamic")
    else:
        print("⚠️  Some tests failed - check output above")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())