import time
import yfinance as yf
from src.trade_engine import TradeEngine
from src.utils import calculate_atr  # Your ATR helper from Week 1

def main():
        # Initialize engine (adjust parameters per your risk tolerance)
        engine = TradeEngine(
            max_open_trades=10,
            atr_period=14,
            atr_multiplier=1.2,  # Fine-tune sensitivity
            rgr_exit_threshold=0.0,  # Exit when RGR < 0
            rgr_exit_consecutive=3
        )

        # Your capital (update dynamically from your portfolio)
        current_capital = 10000.0  # Example: $10k account

        # Main execution loop (runs continuously during market hours)
        while True:  # Replace with your actual market hours check
            try:
                # 1. FETCH LATEST MARKET TICK (e.g., 1-minute data)
                # Replace with your actual data source (WebSocket, API, etc.)
                ticker = "AAPL"
                data = yf.download(ticker, period="1d", interval="1m")
                latest_tick = data.iloc[-1].to_dict()
                latest_tick['timestamp'] = data.index[-1]

                # 2. GET TRADING SIGNAL FROM YOUR LLM STRATEGIST
                # Replace with your actual LLM/RAG/prompt engineering output
                trading_signal = {
                    'direction': 'BUY' if some_condition else 'SELL',
                    'strength': 0.8  # 0-1 confidence score from your model
                    # Add any other signal metadata your strategy uses
                }

                # 3. PROCESS THE TICK THROUGH RAATS ENGINE
                closed_trades = engine.process_market_tick(
                    tick_data=latest_tick,
                    current_capital=current_capital,
                    trading_signal=trading_signal
                )

                # 4. HANDLE CLOSED TRADES (e.g., log, notify, update capital)
                for trade in closed_trades:
                    print(f"TRADE CLOSED: ID={trade['trade_id']}, Reason={trade['reason']}, P&L={trade['pnl']:.2f}")
                    # Update current_capital based on P&L (if live trading)
                    # current_capital += trade['pnl']

                # 5. SLEEP UNTIL NEXT TICK (adjust interval to your data frequency)
                time.sleep(60)  # For 1-minute data - adjust as needed

            except Exception as e:
                print(f"Error in main loop: {e}")
                time.sleep(10)  # Brief pause on error

if name == "main":
        main()



