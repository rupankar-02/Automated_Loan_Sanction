import pytest

from core.utils.ratelimit import SlidingWindowLimiter, call_with_backoff


class Clock:
    def __init__(self):
        self.t = 0.0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def test_limiter_allows_burst_then_waits_for_the_window():
    c = Clock()
    lim = SlidingWindowLimiter(10, 60, clock=c.now, sleep=c.sleep)
    for _ in range(10):
        lim.acquire()
    assert c.t == 0                       # 10 requests fit in the window without waiting
    waits = []
    lim.acquire(on_wait=waits.append)     # the 11th must wait for the first to age out
    assert c.t >= 60 and waits and waits[0] == pytest.approx(60)


def test_limiter_window_slides():
    c = Clock()
    lim = SlidingWindowLimiter(2, 10, clock=c.now, sleep=c.sleep)
    lim.acquire(); c.t = 6; lim.acquire()
    lim.acquire()                         # waits only until t=10, not t=16
    assert 10 <= c.t < 11.5


def test_backoff_retries_rate_limits_then_succeeds():
    calls, slept = [], []

    class Err(Exception):
        status_code = 429

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise Err("too many requests")
        return "ok"

    assert call_with_backoff(fn, retries=3, sleep=slept.append) == "ok"
    assert slept == [2.0, 4.0]


def test_backoff_gives_up_and_ignores_other_errors():
    def always():
        raise RuntimeError("429 rate limit")

    with pytest.raises(RuntimeError):
        call_with_backoff(always, retries=2, sleep=lambda s: None)

    calls = []

    def boom():
        calls.append(1)
        raise ValueError("bad request")

    with pytest.raises(ValueError):
        call_with_backoff(boom, retries=3, sleep=lambda s: None)
    assert len(calls) == 1                # non-rate-limit errors are not retried
