import os
from pathlib import Path
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient

# Force load the .env file located in the exact same folder as this script
env_path = Path(__file__).resolve().parent / ".env"
loaded = load_dotenv(dotenv_path=env_path)

api_key = os.getenv("ALPACA_API_KEY")
secret_key = os.getenv("ALPACA_SECRET_KEY")

print(f"1. Found .env file at {env_path}: {loaded}")
print(f"2. API Key starts with: {api_key[:4] if api_key else 'NONE'}")
print(f"3. Secret Key length: {len(secret_key) if secret_key else 0}")

trading_client = TradingClient(
    api_key=api_key,
    secret_key=secret_key,
    paper=True  # Set to False if you want to use the live trading environment
)

account = trading_client.get_account()
print(f"Account Status: {getattr(account, 'status', 'UNKNOWN')}")
print(f"Buying Power: ${getattr(account, 'buying_power', 'UNKNOWN')}")
