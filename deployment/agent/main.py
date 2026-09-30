from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
import os
import sys

# Add the project root to sys.path so we can import src.* modules
# Assuming this file is in deployment/agent/main.py
# We need to go up two levels to reach RAATS_Test, then into src
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.join(current_dir, '..', '..')
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from agents.trading_loop_dynamic import run_dynamic_trading_session

app = FastAPI(title="RAATS Agent API")

class TradeResponse(BaseModel):
    status: str
    message: str

@app.get("/")
def read_root():
    return {"message": "RAATS Agent API is running"}

@app.post("/run-trading-session", response_model=TradeResponse)
def run_trading_session(background_tasks: BackgroundTasks):
    def run_session():
        # Run the dynamic trading session with empty ticker_universe to trigger discovery
        # This function will block until the session ends (market close or error)
        run_dynamic_trading_session(ticker_universe=None, use_dynamic_discovery=True)
    background_tasks.add_task(run_session)
    return TradeResponse(status="started", message="Trading session started in background")

@app.get("/status")
def get_status():
    # In a real implementation, we would track the state of background tasks.
    # For now, we return a placeholder.
    return {"status": "idle", "note": "Status tracking not implemented"}