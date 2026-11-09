"""Ограничение частоты по ключу (IP) в памяти процесса: скользящее окно 60 с."""

import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int) -> bool:
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True

    def reset(self) -> None:
        self._hits.clear()


login_limiter = RateLimiter()
