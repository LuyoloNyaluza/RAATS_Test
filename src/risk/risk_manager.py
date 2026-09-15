"""
src/risk/risk_manager.py

RAATS Section 3.2: Adaptive Decision-Making Logic and Risk Management.

  3.2.1 Stop Loss / Take Profit at 1:2 RRR, ATR-derived risk distance
  3.2.2 Adaptive bi-directional stepping stop logic
        - Direction D derived from the trading signal's GRADIENT (spec wording)
        - risk_unit scaled by a dimensionless gradient factor
  3.2.3 Tiered position sizing strategy

-----------------------------------------------------------------------------
GRADIENT HANDLING - WHY NOT `m * StopLoss`
-----------------------------------------------------------------------------
The raw gradient m has units of price-per-bar; a stop loss has units of price.
Multiplying them yields price^2/bar, which is not a price. Numerically it also
explodes: with entry 315.32 / SL 303.88, m=1.5 gives m*SL = 455.82, i.e. a
"stop" ABOVE entry on a long (instant trigger); m=-0.8 gives -243.10.

Instead the gradient is normalized to a dimensionless quantity:

    m_norm = (m * lookback) / ATR        # total move over the window, in ATRs

and used two ways:

    D           = sign(m_norm)            when |m_norm| exceeds a deadband
    risk_unit   = ATR * atr_multiplier * gradient_factor(m_norm)

Because every SL/TP/stepping formula is expressed in terms of risk_unit, the
gradient automatically modulates BOTH the initial stop and every subsequent
stepped stop - which is the "m(StopLoss + adaptive value)" behaviour, done in
a dimensionally consistent way. The verified stepping math is unchanged.
-----------------------------------------------------------------------------
"""

import math
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, List, Sequence

import numpy as np


# ---------------------------------------------------------------------------
# ATR
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Gradient
# ---------------------------------------------------------------------------
def compute_gradient(closes: Sequence[float], lookback: int = 10) -> float:
    """Slope m of a least-squares line through the last `lookback` closes.

    Units: price per bar.
    """
    values = np.asarray(closes, dtype=float)
    if len(values) < lookback:
        raise ValueError(f"Need at least {lookback} closes, got {len(values)}")
    window = values[-lookback:]
    x = np.arange(len(window), dtype=float)
    slope, _intercept = np.polyfit(x, window, 1)
    return float(slope)


def normalize_gradient(m: float, lookback: int, atr: float) -> float:
    """Convert price-per-bar slope into a dimensionless ATR-relative measure.

        m_norm = (m * lookback) / ATR

    |m_norm| = 1.0 means the trend covers roughly one ATR over the window.
    """
    if atr <= 0:
        raise ValueError("ATR must be positive to normalize the gradient")
    return (m * lookback) / atr


def direction_from_gradient(m_norm: float, deadband: float = 0.3) -> int:
    """Spec 3.2.2: D determined by the trading signal's gradient.

    Returns +1 (long), -1 (short), or 0 (no clear gradient -> stand aside).
    The deadband stops a flat/choppy market flip-flopping direction.
    """
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
    """Dimensionless multiplier applied to risk_unit.

    widen_with_trend=True  -> steeper trend gives a WIDER stop, so ordinary
                              retracement inside a fast move does not shake the
                              position out. (default)
    widen_with_trend=False -> steeper trend gives a TIGHTER stop, locking gains
                              more aggressively in strong moves.

    Clamped to [f_min, f_max] so an extreme gradient can never produce an
    absurd stop distance.
    """
    magnitude = abs(m_norm)
    if widen_with_trend:
        factor = 1.0 + (k * magnitude)
    else:
        factor = 1.0 / (1.0 + (k * magnitude))
    return float(min(max(factor, f_min), f_max))


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------
@dataclass
class Position:
    ticker: str
    direction: int          # D: +1 long, -1 short
    entry_price: float
    size: float
    risk_unit: float        # ATR * atr_multiplier * gradient_factor
    stop_loss: float
    take_profit: float
    entry_gradient: float = 0.0        # m (price/bar) at entry
    entry_gradient_norm: float = 0.0   # m_norm (dimensionless) at entry
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


# ---------------------------------------------------------------------------
# Risk Manager
# ---------------------------------------------------------------------------
class RiskManager:
    """RAATS adaptive risk manager with gradient-driven bi-directional stops.

    direction_source:
        "gradient"  - D from price gradient only (spec-literal default)
        "signal"    - D from the LLM signal only (previous behaviour)
        "agreement" - trade only when gradient and LLM signal agree
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
        direction_source: str = "agreement",
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

        if direction_source not in ("gradient", "signal", "agreement"):
            raise ValueError(f"Unknown direction_source: {direction_source}")
        self.direction_source = direction_source

        self.positions: Dict[str, Position] = {}
        self.daily_pnl: float = 0.0
        self.closed_trades: List[dict] = []
        self.conflicts: List[dict] = []   # gradient vs LLM disagreements

    # -- gradient helpers ---------------------------------------------------
    def resolve_gradient(self, closes: Sequence[float], atr: float) -> Tuple[float, float]:
        """Return (m, m_norm) for the configured lookback."""
        m = compute_gradient(closes, self.gradient_lookback)
        m_norm = normalize_gradient(m, self.gradient_lookback, atr)
        return m, m_norm

    def compute_risk_unit(self, atr: float, m_norm: float) -> Tuple[float, float]:
        """Return (risk_unit, gradient_factor)."""
        gf = gradient_factor(
            m_norm,
            k=self.gradient_k,
            f_min=self.gradient_f_min,
            f_max=self.gradient_f_max,
            widen_with_trend=self.widen_with_trend,
        )
        return atr * self.atr_multiplier * gf, gf

    def resolve_direction(self, m_norm: float, signal: str) -> Tuple[int, str]:
        """Return (direction, reason). direction 0 means stand aside."""
        signal = (signal or "").upper()
        grad_dir = direction_from_gradient(m_norm, self.gradient_deadband)
        sig_dir = 1 if signal == "BUY" else -1 if signal == "SELL" else 0

        if self.direction_source == "gradient":
            if grad_dir == 0:
                return 0, (f"Gradient within deadband (|m_norm|={abs(m_norm):.3f} "
                           f"< {self.gradient_deadband}) - no clear direction")
            if sig_dir != 0 and sig_dir != grad_dir:
                self.conflicts.append({"m_norm": m_norm, "signal": signal,
                                       "gradient_dir": grad_dir})
                return grad_dir, (f"Gradient ({'up' if grad_dir > 0 else 'down'}) "
                                  f"overrides LLM signal {signal}")
            return grad_dir, f"Direction from gradient (m_norm={m_norm:+.3f})"

        if self.direction_source == "signal":
            if sig_dir == 0:
                return 0, f"Signal {signal} is not directional"
            return sig_dir, f"Direction from LLM signal ({signal})"

        # agreement
        if grad_dir == 0:
            return 0, f"Gradient within deadband (|m_norm|={abs(m_norm):.3f})"
        if sig_dir == 0:
            return 0, f"Signal {signal} is not directional"
        if sig_dir != grad_dir:
            self.conflicts.append({"m_norm": m_norm, "signal": signal,
                                   "gradient_dir": grad_dir})
            return 0, (f"Conflict: LLM says {signal} but gradient is "
                       f"{'up' if grad_dir > 0 else 'down'} (m_norm={m_norm:+.3f})")
        return sig_dir, f"Gradient and signal agree ({signal}, m_norm={m_norm:+.3f})"

    # -- 3.2.3 Tiered position sizing ---------------------------------------
    def calculate_position_size(self, total_capital: float, is_top_five: bool = False) -> float:
        if total_capital <= 200:
            return total_capital / 10
        if total_capital <= 400:
            base = 200 / 10
            if is_top_five:
                return base + (0.5 * (total_capital - 200) / 5)
            return base
        return 0.5 * total_capital

    # -- 3.2.1 SL / TP on entry ---------------------------------------------
    def compute_initial_levels(self, entry_price: float, direction: int,
                               risk_unit: float) -> Tuple[float, float]:
        stop_loss = entry_price - (direction * risk_unit)
        take_profit = entry_price + (direction * self.rrr * risk_unit)
        return stop_loss, take_profit

    # -- Daily loss circuit breaker -----------------------------------------
    def can_trade_today(self, portfolio_value: float) -> bool:
        if self.daily_pnl >= 0:
            return True
        return abs(self.daily_pnl) <= (portfolio_value * self.max_daily_loss_pct)

    def update_daily_pnl(self, pnl: float) -> None:
        self.daily_pnl += pnl

    def reset_daily(self) -> None:
        self.daily_pnl = 0.0

    # -- Trade validation ---------------------------------------------------
    def validate_trade(
        self,
        ticker: str,
        signal: str,
        current_price: float,
        portfolio_value: float,
        atr: float,
        closes: Optional[Sequence[float]] = None,
        m_norm: Optional[float] = None,
        is_top_five: bool = False,
    ) -> Tuple[bool, float, int, str]:
        """Validate a proposed trade.

        Supply either `closes` (gradient computed internally) or a precomputed
        `m_norm`. Returns (approved, size, direction, reason).
        """
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

    # -- Opening ------------------------------------------------------------
    def open_position(
        self,
        ticker: str,
        direction: int,
        entry_price: float,
        size: float,
        atr: float,
        m: float = 0.0,
        m_norm: float = 0.0,
    ) -> Position:
        risk_unit, gf = self.compute_risk_unit(atr, m_norm)
        stop_loss, take_profit = self.compute_initial_levels(entry_price, direction, risk_unit)

        position = Position(
            ticker=ticker,
            direction=direction,
            entry_price=entry_price,
            size=size,
            risk_unit=risk_unit,
            stop_loss=stop_loss,
            take_profit=take_profit,
            entry_gradient=m,
            entry_gradient_norm=m_norm,
            gradient_factor=gf,
        )
        self.positions[ticker] = position
        return position

    # -- 3.2.2 Adaptive bi-directional stepping stop ------------------------
    def update_stepping_stop(self, ticker: str, current_price: float) -> dict:
        """Verified stepping logic (unchanged).

            steps     = floor((current_rr - 2.0) / 0.5)
            locked_rr = 1.5 + (steps * 0.5)
            new_sl    = P_entry + (D * locked_rr * risk_unit)

        Gradient enters through risk_unit, so stepped stops inherit the
        gradient scaling automatically.
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

    # -- Exit checks --------------------------------------------------------
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

    # -- Reporting ----------------------------------------------------------
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
            "gradient_signal_conflicts": len(self.conflicts),
        }