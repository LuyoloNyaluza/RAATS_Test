# src/utils/timer.py
import time
from functools import wraps


def node_timer(name: str):   
    def decorator(func):
        """Decorator to time a function and store the elapsed time in the state dictionary."""
        @wraps(func)
        def wrapper(state):
            start = time.perf_counter()
            result_state = func(state)
            elapsed_ms = (time.perf_counter() - start) * 1000
            result_state.setdefault("latencies", {})[name] = round(elapsed_ms, 2)
            return result_state
        return wrapper
    return decorator


def timer(func):
    """General-purpose timing decorator for plain function calls 
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        end = time.perf_counter()
        elapsed_ms = (end - start) * 1000
        return result, elapsed_ms
    return wrapper