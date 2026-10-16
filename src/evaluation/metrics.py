# File: src/evaluation/metrics.py
import numpy as np
import pandas as pd

def compute_sharpe(returns, risk_free=0.0, periods=252):
    """Annualized Sharpe ratio"""
    excess = returns - risk_free/periods
    return np.sqrt(periods) * excess.mean() / excess.std()

def compute_max_drawdown(equity_curve):
    """Max drawdown from equity curve"""
    roll_max = equity_curve.expanding().max()
    drawdown = (equity_curve - roll_max) / roll_max
    return drawdown.min()

def compute_win_rate(trades):
    """Win rate from list of trade profits"""
    wins = [t for t in trades if t > 0]
    return len(wins) / len(trades) if trades else 0

# Add more as needed