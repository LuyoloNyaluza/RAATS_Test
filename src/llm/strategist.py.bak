from src.strategist.rgr_calculator import RGRCalculator

class LLMStrategist:
        def init(self):
            self.active_rgr_calculators: dict = {}  # trade_id -> RGRCalculator
            # ... [your existing init] ...

        def generate_signal(
            self,
            market_data: dict,  # {price, atr, volume, etc.}
            open_trades: list,  # From your trade engine
            signal = {
                'direction': 'BUY' or 'SELL',  # Your existing logic
                'strength': 0.0-1.0,           # Your existing confidence score
                # ← ADD THESE NEW FIELDS:
                'rgr': 0.0,
                'rgr_diagnostics': {}
            }

            # ... [other inputs] ...
        ) -> dict:
            # ... [your existing signal generation logic (direction, strength)] ...

            # ← ADD: CALCULATE AND ATTACH RGR TO SIGNAL
            signal = {
                'direction': 'BUY' or 'SELL',
                'strength': 0.0-1.0,  # Your existing confidence score
                'rgr': 0.0,           # ← NEW: The RGR value
                'rgr_diagnostics': {} # ← NEW: Optional detailed breakdown
            }

            # Update RGR for all active positions
            for trade in open_trades:
                trade_id = trade['id']
                if trade_id not in self.active_rgr_calculators:
                    # Initialize RGR calculator when position opens
                    self.active_rgr_calculators[trade_id] = RGRCalculator(
                        benchmark_ticker="SPY",  # Match your trade engine's setting
                        volatility_lookback=50,
                        k_factor=1.0,
                        risk_tolerance=0.02
                    )
                    # Initialize with entry price (you'll need to get this from trade data)
                    entry_price = get_entry_price_from_trade(trade)  # YOU IMPLEMENT THIS
                    direction = 1 if trade['direction'] == 'BUY' else -1
                    # You'll need benchmark data here too - simplify for demo:
                    benchmark_data = get_recent_benchmark_data("SPY", 50)  # YOU IMPLEMENT THIS
                    self.active_rgr_calculators[trade_id].initialize_position(
                        entry_price=entry_price,
                        direction=direction,
                        benchmark_data=benchmark_data
                    )

                # Update and calculate RGR
                self.active_rgr_calculators[trade_id].update_market_data(
                    current_price=market_data['close'],
                    current_atr=market_data['atr'],
                    benchmark_close=get_latest_benchmark_price("SPY")  # YOU IMPLEMENT THIS
                )
                current_rgr, diagnostics = self.active_rgr_calculators[trade_id].calculate_rgr(
                    current_price=market_data['close'],
                    current_atr=market_data['atr'],
                    benchmark_close=get_latest_benchmark_price("SPY")
                )

                # Attach RGR to the signal (if this is the signal for THIS trade)
                # In practice: You'd attach RGR to the signal generating THIS trade
                if trade_id == current_trade_being_signaled:  # YOUR LOGIC HERE
                    signal['rgr'] = current_rgr
                    signal['rgr_diagnostics'] = diagnostics

            return signal
