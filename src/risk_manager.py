
import math
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, List, Sequence

import numpy as np


def compute_atr(highs: Sequence[float], lows: Sequence[float],
                closes: Sequence[float], period: int = 14) -> float:
    """Average True Range over `period` bars."""
    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("highs, lows and closes must be the same length")
    if len(closes) < period + 1:
        raise ValueError(
            f"Need at least {period + 1} bars to compute ATR({period}), got {len(closes)}"
        )

    true_ranges = []
    for i in range(1, len(closes)):
        prev_close = closes[i - 1]
        true_ranges.append(max(
            highs[i] - lows[i],
            abs(highs[i] - prev_close),
            abs(lows[i] - prev_close),
        ))
    return sum(true_ranges[-period:]) / period


def compute_gradient(closes: Sequence[float], lookback: int = 10) -> float:
    """Slope m of a least-squares line through the last `lookback` closes."""
    values = np.asarray(closes, dtype=float)
    if len(values) < lookback:
        raise ValueError(f"Need at least {lookback} closes, got {len(values)}")
    window = values[-lookback:]
    x = np.arange(len(window), dtype=float)
    slope, _intercept = np.polyfit(x, window, 1)
    return float(slope)


def normalize_gradient(m: float, lookback: int, atr: float) -> float:
    """m_norm = (m * lookback) / ATR - dimensionless, ATR-relative."""
    if atr <= 0:
        raise ValueError("ATR must be positive to normalize the gradient")
    return (m * lookback) / atr


def direction_from_gradient(m_norm: float, deadband: float = 0.3) -> int:
    """D purely from gradient sign: +1 BUY (m_norm positive), -1 SELL
    (m_norm negative), 0 = no clear direction (within deadband)."""
    if abs(m_norm) < deadband:
        return 0
    return 1 if m_norm > 0 else -1


def gradient_factor(
    m_norm: float,
    k: float = 0.25,
    f_min: float = 0.75,
    f_max: float = 2.0,
    widen_with_trend: bool = True,
) -> float:
    """Dimensionless multiplier applied to risk_unit, clamped to [f_min, f_max]."""
    magnitude = abs(m_norm)
    if widen_with_trend:
        factor = 1.0 + (k * magnitude)
    else:
        factor = 1.0 / (1.0 + (k * magnitude))
    return float(min(max(factor, f_min), f_max))


@dataclass
class Position:
    ticker: str
    direction: int
    entry_price: float
    size: float
    risk_unit: float
    stop_loss: float
    take_profit: float
    entry_gradient: float = 0.0
    entry_gradient_norm: float = 0.0
    gradient_factor: float = 1.0
    locked_rr: Optional[float] = None
    max_rr_seen: float = 0.0

    def current_gain(self, current_price: float) -> float:
        return (current_price - self.entry_price) * self.direction

    def current_rr(self, current_price: float) -> float:
        if self.risk_unit == 0:
            return 0.0
        return self.current_gain(current_price) / self.risk_unit

    def unrealized_pnl(self, current_price: float) -> float:
        return self.current_gain(current_price) * self.size


class RiskManager:
    """RAATS adaptive risk manager.

    Direction logic (finalized): the LLM signal is an INVEST/HOLD filter,
    not a direction-picker. HOLD -> no trade, regardless of gradient.
    BUY or SELL (either) -> "invest" is confirmed; the GRADIENT's sign then
    picks the actual direction (positive -> BUY, negative -> SELL).
    """

    def __init__(
        self,
        atr_multiplier: float = 1.5,
        rrr: float = 2.0,
        step_trigger_rr: float = 2.0,
        step_size_rr: float = 0.5,
        base_locked_rr: float = 1.5,
        max_daily_loss_pct: float = 0.05,
        gradient_lookback: int = 10,
        gradient_deadband: float = 0.3,
        gradient_k: float = 0.25,
        gradient_f_min: float = 0.75,
        gradient_f_max: float = 2.0,
        widen_with_trend: bool = True,
    ):
        self.atr_multiplier = atr_multiplier
        self.rrr = rrr
        self.step_trigger_rr = step_trigger_rr
        self.step_size_rr = step_size_rr
        self.base_locked_rr = base_locked_rr
        self.max_daily_loss_pct = max_daily_loss_pct

        self.gradient_lookback = gradient_lookback
        self.gradient_deadband = gradient_deadband
        self.gradient_k = gradient_k
        self.gradient_f_min = gradient_f_min
        self.gradient_f_max = gradient_f_max
        self.widen_with_trend = widen_with_trend

        self.positions: Dict[str, Position] = {}
        self.daily_pnl: float = 0.0
        self.closed_trades: List[dict] = []

    def resolve_gradient(self, closes: Sequence[float], atr: float) -> Tuple[float, float]:
        m = compute_gradient(closes, self.gradient_lookback)
        m_norm = normalize_gradient(m, self.gradient_lookback, atr)
        return m, m_norm

    def compute_risk_unit(self, atr: float, m_norm: float) -> Tuple[float, float]:
        gf = gradient_factor(
            m_norm, k=self.gradient_k, f_min=self.gradient_f_min,
            f_max=self.gradient_f_max, widen_with_trend=self.widen_with_trend,
        )
        return atr * self.atr_multiplier * gf, gf

    def resolve_direction(self, m_norm: float, signal: str) -> Tuple[int, str]:
        """LLM = invest/hold filter (signal is "INVEST" or "HOLD").
        Gradient = direction, when investing.

        Returns (direction, reason). direction 0 means stand aside.
        """
        signal = (signal or "").upper()

        if signal != "INVEST":
            return 0, f"LLM signal is {signal or 'empty'} - no trade considered"

        grad_dir = direction_from_gradient(m_norm, self.gradient_deadband)
        if grad_dir == 0:
            return 0, (f"LLM confirmed an opportunity (INVEST), but gradient has no "
                       f"clear direction (|m_norm|={abs(m_norm):.3f} < {self.gradient_deadband})")

        chosen = "BUY" if grad_dir == 1 else "SELL"
        return grad_dir, (f"LLM confirmed an opportunity (INVEST); gradient "
                          f"(m_norm={m_norm:+.3f}) sets direction to {chosen}")

    def calculate_position_size(self, total_capital: float, is_top_five: bool = False) -> float:
        if total_capital <= 200:
            return total_capital / 10
        if total_capital <= 400:
            base = 200 / 10
            if is_top_five:
                return base + (0.5 * (total_capital - 200) / 5)
            return base
        return 0.5 * total_capital

    def compute_initial_levels(self, entry_price: float, direction: int,
                               risk_unit: float) -> Tuple[float, float]:
        """BUY (D=+1): SL below entry, TP above. SELL (D=-1): SL above, TP below."""
        stop_loss = entry_price - (direction * risk_unit)
        take_profit = entry_price + (direction * self.rrr * risk_unit)
        return stop_loss, take_profit

    def can_trade_today(self, portfolio_value: float) -> bool:
        if self.daily_pnl >= 0:
            return True
        return abs(self.daily_pnl) <= (portfolio_value * self.max_daily_loss_pct)

    def update_daily_pnl(self, pnl: float) -> None:
        self.daily_pnl += pnl

    def reset_daily(self) -> None:
        self.daily_pnl = 0.0

    def validate_trade(
        self, ticker: str, signal: str, current_price: float, portfolio_value: float,
        atr: float, closes: Optional[Sequence[float]] = None,
        m_norm: Optional[float] = None, is_top_five: bool = False,
    ) -> Tuple[bool, float, int, str]:
        if not self.can_trade_today(portfolio_value):
            return False, 0.0, 0, (
                f"Daily loss limit reached (pnl={self.daily_pnl:.2f}, "
                f"limit={portfolio_value * self.max_daily_loss_pct:.2f})"
            )

        if atr is None or atr <= 0:
            return False, 0.0, 0, "Invalid ATR - cannot size risk"
        if current_price <= 0:
            return False, 0.0, 0, "Invalid price"

        if m_norm is None:
            if closes is None:
                return False, 0.0, 0, "Need closes or m_norm to derive gradient"
            try:
                _m, m_norm = self.resolve_gradient(closes, atr)
            except ValueError as exc:
                return False, 0.0, 0, f"Gradient unavailable: {exc}"

        direction, reason = self.resolve_direction(m_norm, signal)
        if direction == 0:
            return False, 0.0, 0, reason

        existing = self.positions.get(ticker)
        if existing is not None:
            if existing.direction == direction:
                return False, 0.0, 0, f"Already {'long' if direction == 1 else 'short'} {ticker}"
            return False, 0.0, 0, f"Opposing position open on {ticker}; close before reversing"

        capital_per_trade = self.calculate_position_size(portfolio_value, is_top_five)
        size = capital_per_trade / current_price
        if size <= 0:
            return False, 0.0, 0, "Position size resolves to zero"

        return True, size, direction, reason

    def open_position(
        self, ticker: str, direction: int, entry_price: float, size: float,
        atr: float, m: float = 0.0, m_norm: float = 0.0,
    ) -> Position:
        risk_unit, gf = self.compute_risk_unit(atr, m_norm)
        stop_loss, take_profit = self.compute_initial_levels(entry_price, direction, risk_unit)

        position = Position(
            ticker=ticker, direction=direction, entry_price=entry_price, size=size,
            risk_unit=risk_unit, stop_loss=stop_loss, take_profit=take_profit,
            entry_gradient=m, entry_gradient_norm=m_norm, gradient_factor=gf,
        )
        self.positions[ticker] = position
        return position

    def update_stepping_stop(self, ticker: str, current_price: float) -> dict:
        """
            steps     = floor((current_rr - 2.0) / 0.5)
            locked_rr = 1.5 + (steps * 0.5)
            new_sl    = P_entry + (D * locked_rr * risk_unit)
        """
        position = self.positions.get(ticker)
        if position is None:
            return {"updated": False, "reason": "no open position"}

        current_rr = position.current_rr(current_price)
        position.max_rr_seen = max(position.max_rr_seen, current_rr)

        if current_rr < self.step_trigger_rr:
            return {"updated": False,
                    "reason": f"current_rr {current_rr:.3f} below trigger {self.step_trigger_rr}",
                    "current_rr": current_rr, "stop_loss": position.stop_loss}

        steps = math.floor((current_rr - self.step_trigger_rr) / self.step_size_rr)
        locked_rr = self.base_locked_rr + (steps * self.step_size_rr)
        new_sl = position.entry_price + (position.direction * locked_rr * position.risk_unit)

        improves = (new_sl > position.stop_loss if position.direction == 1
                    else new_sl < position.stop_loss)
        if not improves:
            return {"updated": False, "reason": "new_sl would move backwards; retained",
                    "current_rr": current_rr, "stop_loss": position.stop_loss}

        old_sl = position.stop_loss
        position.stop_loss = new_sl
        position.locked_rr = locked_rr

        return {"updated": True, "current_rr": current_rr, "steps": steps,
                "locked_rr": locked_rr, "old_stop_loss": old_sl, "stop_loss": new_sl}

    def check_exit(self, ticker: str, current_price: float) -> Optional[str]:
        position = self.positions.get(ticker)
        if position is None:
            return None
        if position.direction == 1:
            if current_price <= position.stop_loss:
                return "stop_loss"
            if current_price >= position.take_profit:
                return "take_profit"
        else:
            if current_price >= position.stop_loss:
                return "stop_loss"
            if current_price <= position.take_profit:
                return "take_profit"
        return None

    def close_position(self, ticker: str, exit_price: float, reason: str = "manual") -> dict:
        position = self.positions.pop(ticker, None)
        if position is None:
            raise KeyError(f"No open position for {ticker}")

        pnl = position.current_gain(exit_price) * position.size
        self.update_daily_pnl(pnl)

        record = {
            "ticker": ticker,
            "direction": "LONG" if position.direction == 1 else "SHORT",
            "entry_price": position.entry_price,
            "exit_price": exit_price,
            "size": position.size,
            "risk_unit": position.risk_unit,
            "entry_gradient": position.entry_gradient,
            "entry_gradient_norm": position.entry_gradient_norm,
            "gradient_factor": position.gradient_factor,
            "final_stop_loss": position.stop_loss,
            "locked_rr": position.locked_rr,
            "max_rr_seen": position.max_rr_seen,
            "pnl": pnl,
            "reason": reason,
        }
        self.closed_trades.append(record)
        return record

    def portfolio_summary(self, prices: Optional[Dict[str, float]] = None) -> dict:
        prices = prices or {}
        unrealized = sum(p.unrealized_pnl(prices[t])
                         for t, p in self.positions.items() if t in prices)
        realized = sum(t["pnl"] for t in self.closed_trades)
        wins = [t for t in self.closed_trades if t["pnl"] > 0]
        return {
            "open_positions": len(self.positions),
            "closed_trades": len(self.closed_trades),
            "realized_pnl": realized,
            "unrealized_pnl": unrealized,
            "daily_pnl": self.daily_pnl,
            "win_rate": (len(wins) / len(self.closed_trades) * 100) if self.closed_trades else 0.0,
        }