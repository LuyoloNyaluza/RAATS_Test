import numpy as np
import pandas as pd
from typing import Tuple, List, Optional
import datetime
import time
import random

def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """
        Calculate Average True Range (ATR) over specified period
        Args:
            high, low, close: Price series (pandas Series)
            period: Lookback period for ATR (default: 14)
        Returns:
            ATR series (pandas Series)
        """
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        return atr

def calculate_ror(entry_price: float, current_price: float, position_direction: int = 1) -> float:
        """
        Calculate Rate of Return (RoR) adjusted for position direction
        Args:
            entry_price: Entry price of position
            current_price: Current market price
            position_direction: 1 for Long, -1 for Short
        Returns:
            Direction-adjusted RoR
        """
        price_return = (current_price - entry_price) / entry_price
        return price_return * position_direction

def calculate_rpr(
        benchmark_return: float,
        atr_current: float,
        risk_tolerance: float = 0.02,
        benchmark_volatility: Optional[float] = None
    ) -> float:
        """
        Calculate Required Rate of Return (RPR)
        Args:
            benchmark_return: Recent benchmark return (e.g., SPY 20-day avg)
            atr_current: Current ATR value
            risk_tolerance: Risk penalty multiplier (default: 0.02)
            benchmark_volatility: Optional benchmark volatility for adjustment
        Returns:
            RPR value
        """
        volatility_penalty = atr_current * risk_tolerance
        # Optional: Adjust penalty based on benchmark volatility
        if benchmark_volatility is not None:
            volatility_penalty *= (benchmark_volatility / atr_current) if atr_current > 0 else 1
        return benchmark_return + volatility_penalty

def generate_random_delay(min_seconds: int = 15, max_seconds: int = 30) -> int:
        """
        Generate randomized delay for active signal validation (Section 3.2.2)
        Args:
            min_seconds: Minimum delay (default: 15)
            max_seconds: Maximum delay (default: 30)
        Returns:
            Random delay in seconds
        """
        return random.randint(min_seconds, max_seconds)

def log_trade_event(
        event_type: str,
        trade_id: str,
        symbol: str,
        price: float,
        quantity: float,
        pnl: Optional[float] = None,
        reason: str = ""
    ) -> str:
        """
        Generate standardized trade log entry
        Args:
            event_type: ENTRY, EXIT, ADJUST_SL, etc.
            trade_id: Unique trade identifier
            symbol: Trading symbol
            price: Execution price
            quantity: Position size
            pnl: Profit/Loss (for exits)
            reason: Reason for event (e.g., "SL_HIT", "RGR_EXIT")
        Returns:
            Formatted log string
        """
        timestamp = datetime.datetime.now().isoformat()
        log_entry = (
            f"{timestamp} | {event_type} | "
            f"TradeID:{trade_id} | {symbol} | "
            f"Price:{price:.2f} | Qty:{quantity:.4f}"
        )
        if pnl is not None:
            log_entry += f" | PnL:{pnl:.2f}"
        if reason:
            log_entry += f" | Reason:{reason}"
        return log_entry

def calculate_position_size(
        capital: float,
        signal_strength: float,
        tiered_thresholds: Tuple[float, float] = (200.0, 400.0),
        base_unit: float = 20.0
    ) -> float:
        """
        Calculate position size using tiered allocation (Section 3.2.3)
        Args:
            capital: Available trading capital
            signal_strength: Normalized signal strength (0-1)
            tiered_thresholds: (low_threshold, high_threshold) for capital tiers
            base_unit: Base unit size for positions
        Returns:
            Position size in quote currency
        """
        low_thresh, high_thresh = tiered_thresholds

        if capital <= low_thresh:
            # Tier 1: Split capital into 10 equal parts
            return capital / 10.0
        elif capital <= high_thresh:
            # Tier 2: $20/base for 10 trades + 50% of excess to top 5 signals
            base_allocation = base_unit * 10  # $200 base
            excess = capital - low_thresh
            bonus_pool = excess * 0.5  # 50% of excess for bonus
            # Distribute bonus to top signals (simplified: proportional to strength)
            return base_unit + (bonus_pool * signal_strength / 10.0)
        else:
            # Tier 3: 50% of capital to single best signal
            return capital * 0.5 * signal_strength

def is_market_open() -> bool:
        """
        Simple market hours check (for US equities: 9:30 AM - 4:00 PM EST)
        Note: For production, use proper market calendar
        """
        now = datetime.datetime.now()
        weekday = now.weekday()  # 0=Monday, 4=Friday
        if weekday >= 5:  # Weekend
            return False

        market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
        return market_open <= now <= market_close
