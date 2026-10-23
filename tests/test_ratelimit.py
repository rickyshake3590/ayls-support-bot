from bot.ratelimit import SlidingWindowLimiter


def test_blocks_after_limit_within_window() -> None:
    now = [0.0]
    limiter = SlidingWindowLimiter(limit=3, window=60, clock=lambda: now[0])
    assert [limiter.allow(1) for _ in range(4)] == [True, True, True, False]


def test_window_slides_and_allows_again() -> None:
    now = [0.0]
    limiter = SlidingWindowLimiter(limit=2, window=60, clock=lambda: now[0])
    assert limiter.allow(1) and limiter.allow(1)
    assert not limiter.allow(1)
    now[0] = 60.0
    assert limiter.allow(1)


def test_limits_are_per_chat() -> None:
    limiter = SlidingWindowLimiter(limit=1, window=60, clock=lambda: 0.0)
    assert limiter.allow(1)
    assert not limiter.allow(1)
    assert limiter.allow(2)
