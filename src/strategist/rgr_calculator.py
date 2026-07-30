import numpy as np
import pandas as pd
from typing import Tuple, Optional, Dict

class RGRCalculator:
        """
        Calculates Realized Growth Rate (RGR) - the proprietary adaptive signal
        that drives RAATS' decision-making (Section 3.2).

        Formula: RGR = (RoR - RPR) * (1 + Volatility_Scaling_Factor)
        Where:
          - RoR = (Current Price - Entry Price) / Entry Price (direction-adjusted)
          - RPR = Dynamic hurdle rate (benchmark return + volatility-adjusted risk penalty)
          - Volatility_Scaling_Factor = k / (ATR_current / ATR_avg)
        """

        def init(
            self,
            benchmark_ticker: str = "SPY",  # Default benchmark for equities
            volatility_lookback: int = 50,   # Periods for ATR average
            k_factor: float = 1.0,           # Volatility scaling constant (tune this)
            risk_tolerance: float = 0.02     # Risk penalty multiplier for RPR
        ):
            self.benchmark_ticker = benchmark_ticker
            self.volatility_lookback = volatility_lookback
            self.k_factor = k_factor
            self.risk_tolerance = risk_tolerance

            # State tracking (updated per tick)
            self.entry_price: Optional[float] = None
            self.position_direction: Optional[int] = None  # 1=Long, -1=Short
            self.benchmark_returns: Optional[pd.Series] = None
            self.atr_history: list = []  # Stores recent ATR values for avg calculation

        def initialize_position(
            self,
            entry_price: float,
            direction: int,  # 1 for Long, -1 for Short
            benchmark_data: pd.DataFrame  # OHLCV data for benchmark ticker
        ) -> None:
            """Call when opening a new trade to set entry reference"""
            self.entry_price = float(entry_price)
            self.position_direction = int(direction)

            # Calculate benchmark returns for RPR calculation
            benchmark_close = benchmark_data['Close']
            self.benchmark_returns = benchmark_close.pct_change().dropna()

            # Initialize ATR history
            self.atr_history = []

        def update_market_data(
            self,
            current_price: float,
            current_atr: float,
            benchmark_close: float
        ) -> None:
            """Update internal state with latest market data (call on every tick)"""
            # Track ATR history for volatility scaling
            self.atr_history.append(float(current_atr))
            if len(self.atr_history) > self.volatility_lookback:
                self.atr_history.pop(0)

            # Update benchmark returns with latest price (efficient rolling window)
            if self.benchmark_returns is not None:
                # Convert to list for efficient appending (avoid DataFrame recreation)
                if not hasattr(self, '_benchmark_closes'):
                    self._benchmark_closes = list(benchmark_close)
                else:
                    self._benchmark_closes.append(float(benchmark_close))
                    # Keep only lookback window
                    if len(self._benchmark_closes) > self.volatility_lookback:
                        self._benchmark_closes.pop(0)

        def _get_benchmark_returns(self) -> pd.Series:
            """Efficiently compute returns from stored close prices"""
            if not hasattr(self, '_benchmark_closes') or len(self._benchmark_closes) < 2:
                return pd.Series([0.0])
            closes = np.array(self._benchmark_closes)
            returns = np.diff(closes) / closes[:-1]
            return pd.Series(returns)

        def calculate_rgr(
            self,
            current_price: float,
            current_atr: float,
            benchmark_close: float
        ) -> Tuple[float, Dict]:
            """
            Calculate RGR and return diagnostic info
            Returns: (rgr_value, diagnostics_dict)
            """
            if self.entry_price is None or self.position_direction is None:
                return 0.0, {"error": "Position not initialized"}

            # 1. Calculate RoR (Rate of Return) - direction-adjusted
            price_return = (float(current_price) - self.entry_price) / self.entry_price
            # Adjust for position direction (short positions profit when price falls)
            ror = price_return * float(self.position_direction)

            # 2. Calculate RPR (Required Rate of Return)
            # RPR = Benchmark return over lookback + volatility-adjusted risk penalty
            if self.benchmark_returns is not None and len(self.benchmark_returns) > 0:
                # Use stored benchmark returns for efficiency
                benchmark_return = float(self._get_benchmark_returns().tail(
                    min(20, len(self._benchmark_returns))
                ).mean())
            else:
                benchmark_return = 0.0

            # Volatility penalty: ATR_current * risk_tolerance
            volatility_penalty = float(current_atr) * self.risk_tolerance
            rpr = benchmark_return + volatility_penalty

            # 3. Calculate Volatility_Scaling_Factor
            if len(self.atr_history) >= 10:  # Need minimum for stable average
                atr_avg = np.mean(self.atr_history[-10:])  # Recent 10-period ATR avg
                volatility_ratio = float(current_atr) / (atr_avg + 1e-9)  # Avoid division by zero
                volatility_scaling_factor = self.k_factor / volatility_ratio
            else:
                volatility_scaling_factor = self.k_factor  # Default when insufficient data

            # 4. Calculate RGR
            rgr = (ror - rpr) * (1 + volatility_scaling_factor)

            # Diagnostic info for debugging/tracking
            diagnostics = {
                "ror": float(ror),
                "rpr": float(rpr),
                "volatility_scaling_factor": float(volatility_scaling_factor),
                "atr_current": float(current_atr),
                "atr_avg": float(atr_avg) if len(self.atr_history) >= 10 else None,
                "volatility_ratio": float(volatility_ratio) if len(self.atr_history) >= 10 else None,
                "benchmark_return": float(benchmark_return),
                "volatility_penalty": float(volatility_penalty)
            }

            return float(rgr), dict(diagnostics)  # Return copy to prevent reference issues