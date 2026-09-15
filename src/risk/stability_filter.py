
from dataclasses import dataclass, field
from typing import Dict, Any, Optional

import numpy as np
import pandas as pd


@dataclass
class StabilityConfig:
    trend_fast: int = 5
    trend_slow: int = 20
    trend_lookback: int = 10
    trend_min_consistency: float = 0.7

    spread_recent_window: int = 5
    spread_baseline_window: int = 30
    spread_max_ratio: float = 1.3

    atr_recent_window: int = 3
    atr_baseline_window: int = 30
    atr_max_ratio: float = 1.4

    gradient_window: int = 10
    gradient_max_sign_flips: int = 6
    gradient_max_zscore: float = 2.5

    require_all: bool = True


@dataclass
class StabilityResult:
    stable: bool
    status: str
    indicators: Dict[str, Any] = field(default_factory=dict)
    failed: list = field(default_factory=list)

    def __str__(self) -> str:
        if self.stable:
            return "Stable"
        return f"Unstable (failed: {', '.join(self.failed)})"


class MarketStabilityFilter:
    def __init__(self, config: Optional[StabilityConfig] = None):
        self.config = config or StabilityConfig()

    def _trend_reliability(self, df: pd.DataFrame) -> Dict[str, Any]:
        c = self.config
        close = df["Close"]

        fast = close.rolling(c.trend_fast).mean()
        slow = close.rolling(c.trend_slow).mean()
        diff = (fast - slow).dropna()

        if len(diff) < c.trend_lookback:
            return {"passed": False, "reason": "insufficient history for trend check",
                    "consistency": None}

        window = diff.iloc[-c.trend_lookback:]
        current_sign = np.sign(window.iloc[-1])
        if current_sign == 0:
            consistency = 0.0
        else:
            consistency = float((np.sign(window) == current_sign).sum() / len(window))

        passed = consistency >= c.trend_min_consistency
        return {
            "passed": passed, "consistency": round(consistency, 3),
            "threshold": c.trend_min_consistency,
            "direction": "up" if current_sign > 0 else "down" if current_sign < 0 else "flat",
        }

    def _spread_stabilization(self, df: pd.DataFrame) -> Dict[str, Any]:
        c = self.config
        if not {"High", "Low", "Close"}.issubset(df.columns):
            return {"passed": False, "reason": "High/Low/Close required", "is_proxy": True}

        rng = ((df["High"] - df["Low"]) / df["Close"]).dropna()
        if len(rng) < c.spread_baseline_window:
            return {"passed": False, "reason": "insufficient history for spread check",
                    "is_proxy": True}

        recent = float(rng.iloc[-c.spread_recent_window:].mean())
        baseline = float(rng.iloc[-c.spread_baseline_window:].median())

        if baseline == 0:
            return {"passed": False, "reason": "zero baseline range", "is_proxy": True}

        ratio = recent / baseline
        return {
            "passed": ratio <= c.spread_max_ratio, "recent_range": round(recent, 5),
            "baseline_range": round(baseline, 5), "ratio": round(ratio, 3),
            "threshold": c.spread_max_ratio, "is_proxy": True,
            "proxy_note": "intrabar range used; no bid/ask data in daily OHLCV",
        }

    def _volatility_normalization(self, df: pd.DataFrame, atr_col: str) -> Dict[str, Any]:
        c = self.config
        if atr_col not in df.columns:
            return {"passed": False, "reason": f"ATR column '{atr_col}' not found"}

        atr = df[atr_col].dropna()
        if len(atr) < c.atr_baseline_window:
            return {"passed": False, "reason": "insufficient history for ATR check"}

        recent = float(atr.iloc[-c.atr_recent_window:].mean())
        baseline = float(atr.iloc[-c.atr_baseline_window:].median())

        if baseline == 0:
            return {"passed": False, "reason": "zero baseline ATR"}

        ratio = recent / baseline
        return {
            "passed": ratio <= c.atr_max_ratio, "recent_atr": round(recent, 4),
            "baseline_atr": round(baseline, 4), "ratio": round(ratio, 3),
            "threshold": c.atr_max_ratio,
        }

    def _gradient_stability(self, df: pd.DataFrame) -> Dict[str, Any]:
        c = self.config
        close = df["Close"]
        gradient = close.diff().dropna()

        if len(gradient) < c.gradient_window + 1:
            return {"passed": False, "reason": "insufficient history for gradient check"}

        window = gradient.iloc[-c.gradient_window:]
        signs = np.sign(window.values)
        sign_flips = int((signs[1:] != signs[:-1]).sum())

        std = float(window.std())
        mean = float(window.mean())
        latest = float(window.iloc[-1])
        zscore = abs((latest - mean) / std) if std > 0 else 0.0

        flips_ok = sign_flips <= c.gradient_max_sign_flips
        spike_ok = zscore <= c.gradient_max_zscore

        return {
            "passed": flips_ok and spike_ok, "sign_flips": sign_flips,
            "max_sign_flips": c.gradient_max_sign_flips, "latest_zscore": round(zscore, 3),
            "max_zscore": c.gradient_max_zscore, "flips_ok": flips_ok, "spike_ok": spike_ok,
        }

    def assess(self, df: pd.DataFrame, atr_col: str = "ATRr_14") -> StabilityResult:
        indicators = {
            "trend_reliability": self._trend_reliability(df),
            "spread_stabilization": self._spread_stabilization(df),
            "volatility_normalization": self._volatility_normalization(df, atr_col),
            "gradient_stability": self._gradient_stability(df),
        }

        failed = [name for name, res in indicators.items() if not res.get("passed")]

        if self.config.require_all:
            stable = len(failed) == 0
        else:
            stable = len(failed) < 2

        return StabilityResult(
            stable=stable, status="Stable" if stable else "Unstable",
            indicators=indicators, failed=failed,
        )

    def is_safe_to_trade(self, df: pd.DataFrame, atr_col: str = "ATRr_14") -> bool:
        return self.assess(df, atr_col).stable