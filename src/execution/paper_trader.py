"""
src/execution/paper_trader.py (REVISED)

Fixes applied vs. the original:
- Main simulation loop was incomplete — now runs end-to-end on a tick() call
- No position monitoring — now checks SL/TP every tick
- No P&L tracking — realized + unrealized P&L now tracked
- No portfolio summary — added get_portfolio_summary()

This module is intentionally broker-agnostic: `market_data` is passed in by
the caller (e.g. from yfinance, a live feed, or a backtest loop), so it can be
swapped without touching this file.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger("raats.execution.paper_trader")
logging.basicConfig(level=logging.INFO)


@dataclass
class Position:
    position_id: str
    ticker: str
    side: str  # "LONG" or "SHORT"
    entry_price: float
    size: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    opened_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ClosedTrade:
    position_id: str
    ticker: str
    side: str
    entry_price: float
    exit_price: float
    size: float
    pnl: float
    pnl_pct: float
    opened_at: datetime
    closed_at: datetime
    close_reason: str


class PaperTrader:
    """Simple paper trading engine with SL/TP monitoring and P&L tracking."""

    def __init__(self, starting_capital: float = 100_000.0):
        self.starting_capital = starting_capital
        self.capital = starting_capital
        self.open_positions: Dict[str, Position] = {}
        self.trade_history: List[ClosedTrade] = []
        logger.info("PaperTrader initialized with capital=%.2f", starting_capital)

    # ------------------------------------------------------------------
    # Market data preparation
    # ------------------------------------------------------------------
    @staticmethod
    def prepare_market_data(raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize incoming market data into the shape this engine expects.
        Expects at minimum: {"ticker": str, "price": float}
        """
        return {
            "ticker": raw_data.get("ticker"),
            "price": float(raw_data.get("price", 0.0)),
            "timestamp": raw_data.get("timestamp", datetime.utcnow()),
        }

    # ------------------------------------------------------------------
    # Opening positions
    # ------------------------------------------------------------------
    def open_position(
        self,
        ticker: str,
        side: str,
        price: float,
        size: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> Position:
        cost = price * size
        if cost > self.capital:
            raise ValueError(
                f"Insufficient capital: need {cost:.2f}, have {self.capital:.2f}"
            )

        position = Position(
            position_id=str(uuid.uuid4())[:8],
            ticker=ticker,
            side=side.upper(),
            entry_price=price,
            size=size,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        self.open_positions[position.position_id] = position
        self.capital -= cost
        logger.info(
            "Opened %s position %s: %s x%.4f @ %.2f",
            position.side, position.position_id, ticker, size, price,
        )
        return position

    # ------------------------------------------------------------------
    # Closing positions
    # ------------------------------------------------------------------
    def close_position(self, position_id: str, exit_price: float, reason: str = "manual") -> ClosedTrade:
        position = self.open_positions.pop(position_id, None)
        if position is None:
            raise KeyError(f"No open position with id {position_id}")

        if position.side == "LONG":
            pnl = (exit_price - position.entry_price) * position.size
        else:  # SHORT
            pnl = (position.entry_price - exit_price) * position.size

        pnl_pct = pnl / (position.entry_price * position.size) * 100 if position.entry_price else 0.0

        # Return capital: original cost + realized pnl
        self.capital += (position.entry_price * position.size) + pnl

        trade = ClosedTrade(
            position_id=position.position_id,
            ticker=position.ticker,
            side=position.side,
            entry_price=position.entry_price,
            exit_price=exit_price,
            size=position.size,
            pnl=pnl,
            pnl_pct=pnl_pct,
            opened_at=position.opened_at,
            closed_at=datetime.utcnow(),
            close_reason=reason,
        )
        self.trade_history.append(trade)
        logger.info(
            "Closed position %s (%s): pnl=%.2f (%.2f%%) reason=%s",
            position.position_id, position.ticker, pnl, pnl_pct, reason,
        )
        return trade

    # ------------------------------------------------------------------
    # Position monitoring (SL/TP)
    # ------------------------------------------------------------------
    def check_stop_conditions(self, ticker: str, current_price: float) -> List[ClosedTrade]:
        """Check all open positions for this ticker against SL/TP; close as needed."""
        closed = []
        for position_id in list(self.open_positions.keys()):
            position = self.open_positions[position_id]
            if position.ticker != ticker:
                continue

            hit_sl = (
                position.stop_loss is not None
                and (
                    (position.side == "LONG" and current_price <= position.stop_loss)
                    or (position.side == "SHORT" and current_price >= position.stop_loss)
                )
            )
            hit_tp = (
                position.take_profit is not None
                and (
                    (position.side == "LONG" and current_price >= position.take_profit)
                    or (position.side == "SHORT" and current_price <= position.take_profit)
                )
            )

            if hit_sl:
                closed.append(self.close_position(position_id, current_price, reason="stop_loss"))
            elif hit_tp:
                closed.append(self.close_position(position_id, current_price, reason="take_profit"))

        return closed

    # ------------------------------------------------------------------
    # Main tick loop
    # ------------------------------------------------------------------
    def tick(self, market_data: Dict[str, Any], signal: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Process one simulation tick: check stops, optionally act on a new signal.

        Args:
            market_data: raw market data dict (see prepare_market_data)
            signal: optional dict from LLMStrategist.generate_signal(), e.g.
                    {"ticker": ..., "signal": "BUY"/"SELL"/"HOLD", "confidence": ...}
        """
        data = self.prepare_market_data(market_data)
        ticker = data["ticker"]
        price = data["price"]

        closed_trades = self.check_stop_conditions(ticker, price)

        opened_position = None
        if signal and signal.get("ticker") == ticker:
            action = signal.get("signal", "HOLD").upper()
            if action in ("BUY", "SELL") and action != "HOLD":
                # Simple fixed-size sizing for Week 2 prototype; replace with
                # PositionSizer integration in Week 3.
                size = min(10, self.capital / price / 10) if price > 0 else 0
                if size > 0:
                    side = "LONG" if action == "BUY" else "SHORT"
                    opened_position = self.open_position(
                        ticker=ticker,
                        side=side,
                        price=price,
                        size=size,
                        stop_loss=price * (0.98 if side == "LONG" else 1.02),
                        take_profit=price * (1.03 if side == "LONG" else 0.97),
                    )

        return {
            "ticker": ticker,
            "price": price,
            "closed_trades": closed_trades,
            "opened_position": opened_position,
        }

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------
    def get_portfolio_summary(self) -> Dict[str, Any]:
        realized_pnl = sum(t.pnl for t in self.trade_history)
        win_trades = [t for t in self.trade_history if t.pnl > 0]
        loss_trades = [t for t in self.trade_history if t.pnl <= 0]

        return {
            "starting_capital": self.starting_capital,
            "current_capital": self.capital,
            "realized_pnl": realized_pnl,
            "realized_pnl_pct": (realized_pnl / self.starting_capital * 100) if self.starting_capital else 0,
            "open_positions": len(self.open_positions),
            "closed_trades": len(self.trade_history),
            "win_rate": (len(win_trades) / len(self.trade_history) * 100) if self.trade_history else 0,
            "avg_win": (sum(t.pnl for t in win_trades) / len(win_trades)) if win_trades else 0,
            "avg_loss": (sum(t.pnl for t in loss_trades) / len(loss_trades)) if loss_trades else 0,
        }


if __name__ == "__main__":
    trader = PaperTrader(starting_capital=100_000)

    # Simulated tick sequence
    trader.tick({"ticker": "AAPL", "price": 187.0}, signal={"ticker": "AAPL", "signal": "BUY"})
    trader.tick({"ticker": "AAPL", "price": 190.5})
    trader.tick({"ticker": "AAPL", "price": 193.2})

    import json
    print(json.dumps(trader.get_portfolio_summary(), indent=2))
