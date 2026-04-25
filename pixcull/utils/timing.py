import time
from contextlib import contextmanager
from functools import wraps
from typing import Callable


@contextmanager
def timed(label: str):
    t0 = time.perf_counter()
    yield
    print(f"[{label}] {time.perf_counter() - t0:.3f}s")


def time_it(fn: Callable) -> Callable:
    @wraps(fn)
    def wrapper(*args, **kwargs):
        t0 = time.perf_counter()
        out = fn(*args, **kwargs)
        print(f"[{fn.__name__}] {time.perf_counter() - t0:.3f}s")
        return out
    return wrapper
