"""Sliding-window rate limiter and retry-with-backoff for rate-limited APIs (Sarvam: 10 req/min)."""
import threading
import time
from collections import deque
from typing import Callable


class SlidingWindowLimiter:
    """Thread-safe: at most `max_calls` acquisitions in any `per_seconds` window."""

    def __init__(self, max_calls: int, per_seconds: float = 60.0,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
        self.max_calls, self.per_seconds = max_calls, per_seconds
        self._clock, self._sleep = clock, sleep
        self._stamps: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self, on_wait: Callable[[float], None] | None = None) -> None:
        while True:
            with self._lock:
                now = self._clock()
                while self._stamps and now - self._stamps[0] >= self.per_seconds:
                    self._stamps.popleft()
                if len(self._stamps) < self.max_calls:
                    self._stamps.append(now)
                    return
                wait = self._stamps[0] + self.per_seconds - now
            if on_wait:
                on_wait(wait)
            self._sleep(min(max(wait, 0.05), 1.0))


def is_rate_limited(exc: Exception) -> bool:
    return getattr(exc, "status_code", None) == 429 or "429" in str(exc) or "rate limit" in str(exc).lower()


def call_with_backoff(fn: Callable, retries: int = 3, base: float = 2.0,
                      sleep: Callable[[float], None] = time.sleep,
                      on_wait: Callable[[float], None] | None = None):
    """Retry `fn` on rate-limit errors with exponential backoff (2s, 4s, 8s...). Other errors raise."""
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as e:
            if not is_rate_limited(e) or attempt == retries:
                raise
            delay = base * (2 ** attempt)
            if on_wait:
                on_wait(delay)
            sleep(delay)
