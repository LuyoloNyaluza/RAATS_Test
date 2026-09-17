import random
import time
from dataclasses import dataclass


@dataclass
class EntryDelay:
    seconds: float
    simulated: bool


def randomized_entry_delay(low: float = 15.0, high: float = 30.0) -> float:
    """Sample a single randomized delay in [low, high] seconds (spec: 15-30)."""
    if low > high:
        raise ValueError("low must be <= high")
    return random.uniform(low, high)


def wait_for_entry(
    low: float = 15.0,
    high: float = 30.0,
    simulate: bool = True,
) -> EntryDelay:
    """Apply (or simulate) the randomized entry delay before a fill."""
    delay = randomized_entry_delay(low, high)
    if not simulate:
        time.sleep(delay)
    return EntryDelay(seconds=delay, simulated=simulate)