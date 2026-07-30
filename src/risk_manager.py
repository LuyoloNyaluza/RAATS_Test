import numpy as np
from typing import Tuple, Literal

class RiskManager:
        def init(self, atr_multiplier: float = 1.0):
            self.atr_multiplier = atr_multiplier
            self.direction: Literal[1, -1] = 0  # 1=Long, -1=Short
            self.entry_price: float = 0.0
            self.risk_unit: float = 0.0
            self.initial_sl: float = 0.0
            self.initial_tp: float = 0.0
            self.current_sl: float = 0.0
            self.current_tp: float = 0.0
            self.is_active: bool = False

        def initialize_trade(
            self,
            entry_price: float,
            direction: Literal[1, -1],
            atr: float
        ) -> None:
            """Set up initial trade per Section 3.2.1"""
            self.direction = direction
            self.entry_price = entry_price
            self.risk_unit = atr * self.atr_multiplier  # RiskDistance = ATR * multiplier

            # Initial SL/TP per formulas: PSL = Pentry - RiskDistance, PTP = Pentry + 2*RiskDistance
            self.initial_sl = entry_price - (direction * self.risk_unit)
            self.initial_tp = entry_price + (direction * 2 * self.risk_unit)
            self.current_sl = self.initial_sl
            self.current_tp = self.initial_tp
            self.is_active = True

        def update_adaptive_sl(
            self,
            current_price: float
        ) -> Tuple[float, bool]:
            """
            Implements Section 3.2.2 Adaptive Bi-Directional Stepping Stop
            Returns: (new_sl, was_updated)
            """
            if not self.is_active:
                return self.current_sl, False

            # Calculate current risk-reward ratio (currentrr)
            price_diff = current_price - self.entry_price
            current_rrr = abs(price_diff) / self.risk_unit  # currentgain relative to risk_unit

            # Adaptive Stepping Activation (Trigger: currentrr >= 2.0)
            if current_rrr < 2.0:
                return self.current_sl, False  # No trailing yet

            # 1. Calculate Steps: 0.5 RR increments beyond 2.0 trigger
            steps = int((current_rrr - 2.0) // 0.5)  # Floor division

            # 2. Lock in Profit: lockedrr = 1.5 + (steps * 0.5)
            locked_rrr = 1.5 + (steps * 0.5)

            # 3. Update Stop Loss: newsl = Pentry + (Direction * lockedrr * risk_unit)
            new_sl = self.entry_price + (self.direction * locked_rrr * self.risk_unit)

            # 4. Ensure Forward Movement (Critical safeguard)
            if (self.direction == 1 and new_sl > self.current_sl) or \
               (self.direction == -1 and new_sl < self.current_sl):
                self.current_sl = new_sl
                return new_sl, True  # SL updated

            return self.current_sl, False  # SL not updated (would move backward)

        def check_closure_conditions(
            self,
            current_price: float
        ) -> Tuple[bool, Literal['SL', 'TP', 'NONE']]:
            """Check if trade should close (SL/TP hit)"""
            if not self.is_active:
                return False, 'NONE'

            if self.direction == 1:  # Long position
                if current_price <= self.current_sl:
                    return True, 'SL'
                if current_price >= self.current_tp:
                    return True, 'TP'
            else:  # Short position
                if current_price >= self.current_sl:
                    return True, 'SL'
                if current_price <= self.current_tp:
                    return True, 'TP'

            return False, 'NONE'