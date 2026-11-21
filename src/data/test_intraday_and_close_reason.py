"""Tests: intraday ATR, close-reason classification, max_rr_seen recording."""
import types, contextlib
from src.data import mt5_orders as mo
from src.risk.risk_manager import RiskManager


def _fake_mt5(rates=None, deals=None):
    m = types.SimpleNamespace(
        TIMEFRAME_M5=5, TIMEFRAME_D1=1440,
        DEAL_ENTRY_OUT=1, DEAL_REASON_CLIENT=0, DEAL_REASON_MOBILE=1, DEAL_REASON_WEB=2,
        DEAL_REASON_EXPERT=3, DEAL_REASON_SL=4, DEAL_REASON_TP=5, DEAL_REASON_SO=6)
    m.copy_rates_from_pos = lambda sym, tf, pos, n: rates
    m.history_deals_get = lambda position=None: deals
    return m


@contextlib.contextmanager
def _ok_session():
    yield True


def _patch(monkey_mt5):
    mo.mt5 = monkey_mt5
    mo.session = _ok_session
    mo.live_enabled = lambda: True


def test_intraday_atr_constant_range():
    rates = [{"high": 101.0, "low": 100.0, "close": 100.5} for _ in range(40)]
    _patch(_fake_mt5(rates=rates))
    atr = mo.intraday_atr("X", "M5", 14)
    assert atr is not None
    assert abs(atr - 1.0) < 1e-9


def test_intraday_atr_not_enough_bars_returns_none():
    _patch(_fake_mt5(rates=[{"high": 2, "low": 1, "close": 1.5}] * 5))
    assert mo.intraday_atr("X", "M5", 14) is None


def _deal(reason):
    return types.SimpleNamespace(entry=1, reason=reason, price=10.0, profit=1.0, commission=0.0,
                                 swap=0.0, comment="", ticket=9, time=1)


def test_close_reasons():
    for code, want in ((0, "manual_close"), (1, "manual_close"), (2, "manual_close"), (3, "expert_close"),
                       (4, "stop_loss"), (5, "take_profit"), (6, "stop_out"), (99, "external_close")):
        _patch(_fake_mt5(deals=[_deal(code)]))
        info = mo.closed_deal_info(123)
        assert info is not None
        assert info["reason"] == want, (code, info["reason"])
        assert info["detail"]["deal_reason_code"] == code


def test_observe_records_max_rr():
    rm = RiskManager()
    pos = rm.open_position("T", 1, 100.0, 1.0, atr=2.0, m=0.0, m_norm=0.0)
    r1 = rm.observe("T", 100.0 + 1.0 * pos.risk_unit)
    rm.observe("T", 100.0 + 0.2 * pos.risk_unit)
    assert abs(r1 - 1.0) < 1e-9 and abs(pos.max_rr_seen - 1.0) < 1e-9


if __name__ == "__main__":
    # Script-style runner (matches the other tests here): python -m src.data.test_intraday_and_close_reason
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL  {fn.__name__}: {exc!r}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)
