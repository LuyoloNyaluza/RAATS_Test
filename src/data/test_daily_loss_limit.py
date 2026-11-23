"""Daily loss limit: 20% of the START-OF-DAY balance, net of the day's closed P&L, entries only."""
from src.risk.risk_manager import RiskManager


def _rm(start):
    rm = RiskManager()
    rm.sync_day("2026-11-23", start, 0.0)
    return rm


def test_default_is_20_percent():
    assert abs(RiskManager().max_daily_loss_pct - 0.20) < 1e-9


def test_profit_then_loss_nets_positive_and_keeps_trading():
    rm = _rm(20.0)
    rm.update_daily_pnl(9.0)
    rm.update_daily_pnl(-2.0)
    assert rm.daily_pnl == 7.0 and rm.can_trade_today(27.0)


def test_small_loss_below_limit_still_trades():
    rm = _rm(20.0)
    rm.update_daily_pnl(-2.0)          # 20 -> 18 is -10%, under 20%
    assert rm.can_trade_today(18.0)


def test_limit_uses_start_of_day_not_current_balance():
    rm = _rm(100.0)
    rm.update_daily_pnl(-19.0)
    assert rm.can_trade_today(81.0)    # limit 20.00
    rm.update_daily_pnl(-1.0)          # net -20 reaches the limit
    assert not rm.can_trade_today(80.0)


def test_limit_scales_with_any_balance():
    rm = _rm(500.0)
    rm.update_daily_pnl(-99.0)
    assert rm.can_trade_today(401.0)
    rm.update_daily_pnl(-1.5)
    assert not rm.can_trade_today(399.5)


def test_profit_after_loss_reopens_trading():
    rm = _rm(100.0)
    rm.update_daily_pnl(-25.0)
    assert not rm.can_trade_today(75.0)
    rm.update_daily_pnl(10.0)          # net -15 again under the limit
    assert rm.can_trade_today(85.0)


def test_new_day_resets_and_restart_keeps_realised():
    rm = _rm(100.0)
    rm.update_daily_pnl(-30.0)
    rm.sync_day("2026-11-24", 70.0, 0.0)
    assert rm.daily_pnl == 0.0 and rm.day_start_balance == 70.0 and rm.can_trade_today(70.0)
    fresh = RiskManager()              # restart mid-day: broker says -15 so far, balance 85
    fresh.sync_day("2026-11-24", 85.0 - (-15.0), -15.0)
    assert fresh.day_start_balance == 100.0 and fresh.can_trade_today(85.0)


def test_validate_trade_blocks_with_clear_message_only_when_over_limit():
    rm = _rm(100.0)
    rm.update_daily_pnl(-25.0)
    ok, _, _, why = rm.validate_trade("X", "INVEST", 10.0, 75.0, atr=1.0)
    assert not ok and why.startswith("Daily loss limit reached") and "start-of-day" in why


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in tests:
        try:
            fn(); print(f"PASS  {fn.__name__}")
        except Exception as exc:
            failed += 1; print(f"FAIL  {fn.__name__}: {exc!r}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)
