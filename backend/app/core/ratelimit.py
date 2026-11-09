"""Ограничение частоты по ключу (IP, пользователь, чат) в памяти процесса: скользящее окно 60 с."""

import time
from collections import deque

WINDOW = 60.0
# Раз в столько вызовов удаляются ключи без попаданий в окне: иначе словарь растёт
# без ограничений (ключ — произвольный IP или chat_id, который задаёт клиент).
_SWEEP_EVERY = 1024


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._calls = 0

    def allow(self, key: str, limit: int) -> bool:
        now = time.monotonic()
        self._calls += 1
        if self._calls >= _SWEEP_EVERY:
            self._sweep(now)
        q = self._hits.setdefault(key, deque())
        while q and now - q[0] > WINDOW:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True

    def _sweep(self, now: float) -> None:
        self._calls = 0
        stale = [k for k, q in self._hits.items() if not q or now - q[-1] > WINDOW]
        for k in stale:
            del self._hits[k]

    def reset(self) -> None:
        self._hits.clear()
        self._calls = 0


login_limiter = RateLimiter()
