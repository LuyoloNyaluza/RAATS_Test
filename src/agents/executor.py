import logging
from typing import Optional

from src.risk.risk_manager import RiskManager
from src.utils.async_timer import wait_for_entry

logger = logging.getLogger("raats.agents.executor")

_DEFAULT_RISK_MANAGER = RiskManager()


def execute_trade(state: dict) -> dict:
    risk_manager: RiskManager = state.get("risk_manager") or _DEFAULT_RISK_MANAGER

    ticker = state.get("ticker", "UNKNOWN")
    signal = state.get("signal", "HOLD")
    market_data = state.get("market_data", {})
    price = market_data.get("close")
    atr = market_data.get("atr")
    closes = market_data.get("closes")
    portfolio_value = state.get("portfolio_value", 10_000)
    is_top_five = state.get("is_top_five", False)

    state["llm_signal"] = signal
    state["executed"] = False
    state["executed_price"] = None
    state["position_size"] = 0.0
    state["stop_loss"] = None
    state["take_profit"] = None
    state["risk_reason"] = None
    state["gradient"] = None
    state["gradient_norm"] = None

    if price is None:
        state["risk_reason"] = "No close price in market_data"
        return state

    m = m_norm = None
    if atr and atr > 0 and closes:
        try:
            m, m_norm = risk_manager.resolve_gradient(closes, atr)
            state["gradient"] = m
            state["gradient_norm"] = m_norm
        except ValueError as exc:
            state["risk_reason"] = f"Gradient unavailable: {exc}"
            return state

    if ticker in risk_manager.positions:
        step = risk_manager.update_stepping_stop(ticker, price)
        state["stepping_update"] = step

        exit_reason = risk_manager.check_exit(ticker, price)
        if exit_reason:
            record = risk_manager.close_position(ticker, price, reason=exit_reason)
            state["closed_trade"] = record
            state["risk_reason"] = f"Position closed: {exit_reason}"
            state["executed"] = True
            state["executed_price"] = price
            logger.info("%s closed via %s, pnl=%.2f", ticker, exit_reason, record["pnl"])
            return state

        position = risk_manager.positions[ticker]
        state["stop_loss"] = position.stop_loss
        state["take_profit"] = position.take_profit
        state["position_size"] = position.size
        state["direction"] = "LONG" if position.direction == 1 else "SHORT"
        state["risk_reason"] = "Position already open; holding and trailing stop"
        return state

    if atr is None or atr <= 0:
        state["risk_reason"] = (
            "Missing/invalid ATR - cannot compute volatility-adjusted risk unit"
        )
        return state

    if not closes:
        state["risk_reason"] = (
            "No recent closes in market_data - cannot derive gradient direction"
        )
        return state

    approved, size, direction, reason = risk_manager.validate_trade(
        ticker=ticker,
        signal=signal,
        current_price=price,
        portfolio_value=portfolio_value,
        atr=atr,
        m_norm=m_norm,
        is_top_five=is_top_five,
    )

    state["risk_reason"] = reason

    if not approved:
        logger.info("Trade rejected for %s: %s", ticker, reason)
        return state

    simulate_delay = state.get("simulate_entry_delay", True)
    entry_delay = wait_for_entry(simulate=simulate_delay)
    state["entry_delay_sec"] = entry_delay.seconds
    state["entry_delay_simulated"] = entry_delay.simulated

    position = risk_manager.open_position(
        ticker=ticker,
        direction=direction,
        entry_price=price,
        size=size,
        atr=atr,
        m=m or 0.0,
        m_norm=m_norm or 0.0,
    )

    state["executed"] = True
    state["executed_price"] = price
    state["position_size"] = position.size
    state["direction"] = "LONG" if direction == 1 else "SHORT"
    state["stop_loss"] = position.stop_loss
    state["take_profit"] = position.take_profit
    state["risk_unit"] = position.risk_unit
    state["gradient_factor"] = position.gradient_factor

    logger.info(
        "%s opened %s size=%.4f @ %.2f SL=%.2f TP=%.2f (m_norm=%+.3f gf=%.3f)",
        ticker, state["direction"], size, price,
        position.stop_loss, position.take_profit,
        position.entry_gradient_norm, position.gradient_factor,
    )
    return state