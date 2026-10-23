"""Per-chat sliding-window rate limit. In memory: resets on restart, which is fine for one instance."""

import time
from collections import defaultdict, deque
from collections.abc import Callable

from . import config

WINDOW_SECONDS = 60.0


class SlidingWindowLimiter:
    def __init__(
        self,
        limit: int,
        window: float = WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window
        self._clock = clock
        self._hits: dict[int, deque[float]] = defaultdict(deque)

    def allow(self, chat_id: int) -> bool:
        now = self._clock()
        hits = self._hits[chat_id]
        while hits and now - hits[0] >= self._window:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(now)
        return True


limiter = SlidingWindowLimiter(config.USER_MSGS_PER_MIN)
