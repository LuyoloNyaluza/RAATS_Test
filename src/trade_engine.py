import time
import random
from typing import List, Dict, Optional
from .risk_manager import RiskManager
from .position_sizer import PositionSizer
from .stability_filter import MarketStabilityFilter
from .utils import calculate_atr  
from .strategist.rgr_calculator import RGRCalculator

class TradeEngine:
        def init(
            self,
            max_open_trades: int = 10,
            atr_period: int = 14,
            atr_multiplier: float = 1.0,
             rgr_exit_threshold: float = -0.1,  # EXIT WHEN RGR < -0.1 (tune this)
            rgr_exit_consecutive: int = 3,
            # ← ADD THESE NEW PARAMETERS FOR RGR
            benchmark_ticker: str = "SPY",
            volatility_lookback: int = 50,
            k_factor: float = 1.0,
            risk_tolerance: float = 0.02
        ):
            self.max_open_trades = max_open_trades
            self.atr_period = atr_period
            self.atr_multiplier = atr_multiplier
            self.rgr_calculator = RGRCalculator(
            benchmark_ticker=benchmark_ticker,
            volatility_lookback=volatility_lookback,
            k_factor=k_factor,
            risk_tolerance=risk_tolerance
        )
            self.rgr_exit_threshold = rgr_exit_threshold
            self.rgr_exit_consecutive = rgr_exit_consecutive

            self.risk_manager = RiskManager(atr_multiplier)
            self.position_sizer = PositionSizer()
            self.stability_filter = MarketStabilityFilter()

            self.open_trades: List[Dict] = []  # Each trade: {id, risk_manager, entry_time, signal_data}
            self.trade_id_counter = 0
            self.rgr_exit_counters: Dict[int, int] = {}  # Track consecutive RGR < 0 per trade

        def _generate_random_delay(self) -> float:
            """Section 3.3: Randomized timer (15-30 seconds)"""
            return random.uniform(15.0, 30.0)

        def _should_open_new_trade(
            self,
            signal_quality: float,  # 0-1 score from your LLM strategist (higher = better)
            current_capital: float
        ) -> Tuple[bool, Optional[int]]:
            """
            Implements Trade Opening Logic (Section 3.3)
            Returns: (should_open, position_size)
            """
            # 1. Maximum Trades Check
            if len(self.open_trades) >= self.max_open_trades:
                return False, None

            # 2. Pre-Trade Analysis: Market Stability Filter MUST pass
            if not self.stability_filter.is_market_stable():
                return False, None  # Enter observation state per Section 3.4.2

            # 3. (Optional) Use signal_quality to rank opportunities
            # In practice: You'd compare signal_quality against other pending signals
            # For now, assume we're processing the best available signal

            # 4. Calculate position size based on capital and signal rank
            # Here we assume signal_rank=1 (best signal) - adjust based on your ranking logic
            position_size = self.position_sizer.calculate_position_size(
                total_capital=current_capital,
                signal_rank=1  # Replace with actual signal ranking from your LLM
            )

            return position_size > 0, position_size

        def process_market_tick(
            self,
            tick_data: Dict,  # {timestamp, open, high, low, close, volume, bid_ask_spread}
            current_capital: float,
            trading_signal: Optional[Dict] = None  # From your LLM strategist: {direction, strength, etc.}
        ) -> List[Dict]:
            """
            MAIN EXECUTION/MONITORING LOOP
            Call this on every new market tick (e.g., every minute or tick)
            Returns: List of closed trade notifications
            """
            # 1. UPDATE MARKET STABILITY FILTER (Critical for Section 3.4)
            self.stability_filter.update_indicators(
                high=tick_data['high'],
                low=tick_data['low'],
                close=tick_data['close'],
                volume=tick_data['volume'],
                bid_ask_spread=tick_data['bid_ask_spread'],
                atr_14=calculate_atr(
                    tick_data['high'],
                    tick_data['low'],
                    tick_data['close'],
                    period=self.atr_period
                )
            )
            if self.open_trades:  # Only calculate if we have open positions
            # Get latest benchmark price (in practice: fetch from your data pipeline)
            # For demo: Assume you have benchmark_close from your data feed
            # In production: You'd pull this from your market data module
                benchmark_close = get_latest_benchmark_price(self.benchmark_ticker)  # YOU IMPLEMENT THIS

            # Update RGR calculator state for EACH open trade
            for trade in self.open_trades:
                rm = trade['risk_manager']
                # Only update if trade is active and we have entry price
                if rm.is_active and rm.entry_price > 0:
                    self.rgr_calculator.update_market_data(
                        current_price=float(tick_data['close']),
                    current_atr=float(current_atr),  # From your stability filter update
                    benchmark_close=float(benchmark_close)
                    )
            closed_trades = []

            # 2. CONTINUOUS MONITORING OF OPEN TRADES 
            trades_to_close = []
            for trade in self.open_trades:
                rm = trade['risk_manager']
                trade_id = trade['id']
                # Calculate current RGR for this trade
                current_rgr, diagnostics = self.rgr_calculator.calculate_rgr(
                    current_price=float(tick_data['close']),
                    current_atr=float(current_atr),
                    benchmark_close=float(benchmark_close)  # Same as above
                )

                # Check if RGR has fallen below exit threshold
            if current_rgr < self.rgr_exit_threshold:
                self.rgr_exit_counters[trade_id] = self.rgr_exit_counters.get(trade_id, 0) + 1
            else:
                self.rgr_exit_counters[trade_id] = 0  # Reset counter if RGR recovers

            # Trigger exit if RGR stays below threshold for X consecutive ticks
            if self.rgr_exit_counters.get(trade_id, 0) >= self.rgr_exit_consecutive:
                should_close = True
                reason = 'RGR_EXIT'  # Add this to your closure reasons
                
                # Update adaptive SL based on current price
                new_sl, was_updated = rm.update_adaptive_sl(tick_data['close'])

                # Check for closure conditions (SL/TP hit)
                should_close, reason = rm.check_closure_conditions(tick_data['close'])

                # OPTIONAL: Add RGR-based exit logic (your execution/monitoring idea)
                # Calculate RGR here if you have RoR/RPR data from your strategy
                # For brevity: Assume you compute current_rgr elsewhere
                # current_rgr = ...  # Your RGR calculation
                # if current_rgr < self.rgr_exit_threshold:
                #     self.rgr_exit_counters[trade_id] = self.rgr_exit_counters.get(trade_id, 0) + 1
                # else:
                #     self.rgr_exit_counters[trade_id] = 0
                #
                # if self.rgr_exit_counters.get(trade_id, 0) >= self.rgr_exit_consecutive:
                #     should_close = True
                #     reason = 'RGR_EXIT'

                if should_close or reason in ['SL', 'TP']:  # Or 'RGR_EXIT' if implemented
                    trades_to_close.append((trade, reason))

            # 3. SIMULTANEOUS CLOSURE 
            for trade, reason in trades_to_close:
                trade_id = trade['id']
                # Record trade outcome (P&L, duration, etc.) for your performance metrics
                self._record_trade_outcome(trade, tick_data['close'], reason)

                # Remove from open trades
                self.open_trades = [t for t in self.open_trades if t['id'] != trade_id]

                # 4. NEW TRADE TIMER GENERATION (Section 3.3.2)
                # Upon closure, generate new random delay for replacement
                # (This is handled in the opening logic below via _should_open_new_trade)

                closed_trades.append({
                    'trade_id': trade_id,
                    'reason': reason,
                    'exit_price': tick_data['close'],
                    'pnl': self._calculate_pnl(trade, tick_data['close'])
                })

                # Reset RGR exit counter for this trade ID (if reused)
                if trade_id in self.rgr_exit_counters:
                    del self.rgr_exit_counters[trade_id]

            # 5. TRADE OPENING LOGIC (Section 3.3.1) - Only if monitoring shows capacity
            if trading_signal and len(self.open_trades) < self.max_open_trades:
                should_open, position_size = self._should_open_new_trade(
                    signal_quality=trading_signal.get('strength', 0.5),  # Adjust per your signal
                    current_capital=current_capital
                )

                if should_open and position_size > 0:
                    self.trade_id_counter += 1
                    new_trade_id = self.trade_id_counter

                    # Initialize new trade
                    rm = RiskManager(self.atr_multiplier)
                    rm.initialize_trade(
                        entry_price=tick_data['close'],
                        direction=1 if trading_signal['direction'] == 'BUY' else -1,
                        atr=calculate_atr(
                            tick_data['high'],
                            tick_data['low'],
                            tick_data['close'],
                            period=self.atr_period
                        )
                    )

                    self.open_trades.append({
                        'id': new_trade_id,
                        'risk_manager': rm,
                        'entry_time': tick_data['timestamp'],
                        'signal_data': trading_signal,
                        'position_size': position_size
                    })

                    # Generate new random delay for NEXT potential trade
                    # (Actual delay handled in your main loop scheduler)

            return closed_trades

        def _record_trade_outcome(
            self,
            trade: Dict,
            exit_price: float,
            reason: str
        ) -> None:
            """Log trade details for performance metrics (Section 4.1)"""
            rm = trade['risk_manager']
            entry_price = rm.entry_price
            direction = rm.direction
            position_size = trade['position_size']

            # Calculate P&L (simplified - adjust for your instrument)
            if direction == 1:  # Long
                pnl = (exit_price - entry_price) * position_size
            else:  # Short
                pnl = (entry_price - exit_price) * position_size

            # Store in your performance tracker (e.g., write to CSV/database)
            # Example: self.performance_logger.log_trade(...)
            pass  # Implement your actual logging here

        def _calculate_pnl(self, trade: Dict, exit_price: float) -> float:
            rm = trade['risk_manager']
            entry_price = rm.entry_price
            direction = rm.direction
            position_size = trade['position_size']

            if direction == 1:  # Long
                return (exit_price - entry_price) * position_size
            else:  # Short
                return (entry_price - exit_price) * position_size
