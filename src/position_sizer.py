class PositionSizer:
        def calculate_position_size(
            self,
            total_capital: float,
            signal_rank: int,  # 1 = best signal, 2 = second best, etc.
            num_top_signals: int = 5  # Top 5 get bonus in mid-range
        ) -> float:
            """
            Implements Section 3.2.3 Tiered Position Sizing
            signal_rank: 1-based index (1 = highest RGR signal)
            """
            # Base allocation for bottom tier (always applies)
            base_allocation = total_capital / 10.0  # Ctotal / 10 per tier

            if total_capital <= 200:
                # Ctotal ≤ $200: Equal split into 10 trades
                return base_allocation

            elif total_capital <= 400:
                # $200 < Ctotal ≤ $400:
                # - Base: $200 split into 10 trades ($20/trade)
                # - Bonus: 50% of (Ctotal - $200) split into TOP 5 trades
                base_trade = 200.0 / 10.0  # $20
                bonus_pool = 0.5 * (total_capital - 200.0)
                bonus_per_top_trade = bonus_pool / num_top_signals

                if signal_rank <= num_top_signals:  # Top 5 signals
                    return base_trade + bonus_per_top_trade
                else:  # Bottom 5 signals
                    return base_trade

            else:  # Ctotal > $400
                # 50% of Ctotal allocated to SINGLE BEST signal
                if signal_rank == 1:  # Best signal gets 50% capital
                    return 0.5 * total_capital
                else:  # All other signals get 0 (per spec)
                    return 0.0
