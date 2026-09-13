def execute_trade(state: dict) -> dict:
    signal = state["signal"]
    market_data = state["market_data"]
    price = market_data["close"]
    # Simulate execution at close price (slippage zero for simplicity)
    executed_price = price
    state["executed_price"] = executed_price
    # In a real system, we would update position, PnL, etc.
    return state