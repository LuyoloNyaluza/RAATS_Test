 import numpy as np
    import pandas as pd
    from typing import Tuple

    class MarketStabilityFilter:
        def init(
            self,
            adx_threshold: float = 25.0,
            spread_z_threshold: float = 1.5,
            atr_ratio_threshold: float = 1.2,
            gradient_std_threshold: float = 0.002  # Example: 0.2% price change std dev
        ):
            self.adx_threshold = adx_threshold
            self.spread_z_threshold = spread_z_threshold
            self.atr_ratio_threshold = atr_ratio_threshold
            self.gradient_std_threshold = gradient_std_threshold
            self.indicators_history = []  # Store recent values for gradient calc

        def update_indicators(
            self,
            high: float,
            low: float,
            close: float,
            volume: float,
            bid_ask_spread: float,
            atr_14: float
        ) -> None:
            """Call this on every new bar/tick to update filter state"""
            # 1. Trend Reliability: ADX > threshold (simplified - use actual ADX calc in practice)
            # For production: Replace with ta-lib ADX calculation
            trend_reliability = True  # Placeholder - implement real ADX check

            # 2. Spread Stabilization: Current spread vs. historical mean/stdev
            self.indicators_history.append({
                'spread': bid_ask_spread,
                'atr': atr_14,
                'close': close
            })
            # Keep only last 20 periods for stability calc
            if len(self.indicators_history) > 20:
                self.indicators_history.pop(0)

            if len(self.indicators_history) >= 20:
                spreads = [x['spread'] for x in self.indicators_history]
                spread_mean = np.mean(spreads)
                spread_std = np.std(spreads)
                spread_z = (bid_ask_spread - spread_mean) / (spread_std + 1e-9)
                spread_stable = abs(spread_z) < self.spread_z_threshold
            else:
                spread_stable = True  # Not enough data yet - assume stable

            # 3. Volatility Normalization: Current ATR vs. 50-period avg ATR
            atr_values = [x['atr'] for x in self.indicators_history]
            if len(atr_values) >= 10:  # Need minimum for avg
                atr_avg = np.mean(atr_values[-10:])  # Recent 10-period avg
                atr_ratio = atr_14 / (atr_avg + 1e-9)
                vol_normalized = atr_ratio < self.atr_ratio_threshold
            else:
                vol_normalized = True  # Not enough data

            # 4. Gradient Stability: Std dev of recent price changes
            if len(self.indicators_history) >= 5:
                closes = [x['close'] for x in self.indicators_history]
                price_changes = np.diff(closes)
                gradient_std = np.std(price_changes[-5:])  # Last 5 changes
                gradient_stable = gradient_std < self.gradient_std_threshold
            else:
                gradient_stable = True  # Not enough data

            # Store latest evaluation
            self.last_evaluation = {
                'trend_reliable': trend_reliability,
                'spread_stable': spread_stable,
                'vol_normalized': vol_normalized,
                'gradient_stable': gradient_stable,
                'is_stable': trend_reliability and spread_stable and vol_normalized and gradient_stable
            }

        def is_market_stable(self) -> bool:
            """Return True if ALL 4 indicators pass (Section 3.4.1)"""
            if not hasattr(self, 'last_evaluation'):
                return False  # Not initialized yet
            return self.last_evaluation['is_stable']

        def get_stability_score(self) -> float:
            """Optional: Return 0-100 score for dynamic position sizing"""
            if not hasattr(self, 'last_evaluation'):
                return 0.0
            score = (
                (1 if self.last_evaluation['trend_reliable'] else 0) * 25 +
                (1 if self.last_evaluation['spread_stable'] else 0) * 25 +
                (1 if self.last_evaluation['vol_normalized'] else 0) * 25 +
                (1 if self.last_evaluation['gradient_stable'] else 0) * 25
            )
            return score
