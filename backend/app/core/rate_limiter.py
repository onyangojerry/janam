"""In-memory fixed window rate limiter."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import math
import threading
import time


@dataclass(slots=True)
class _Bucket:
    hits: deque[float] = field(default_factory=deque)


class InMemoryRateLimiter:
    def __init__(self, limit: int, window_seconds: int = 60):
        self._limit = max(1, limit)
        self._window_seconds = max(1, window_seconds)
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def consume(self, key: str) -> bool:
        allowed, _, _ = self.consume_with_info(key)
        return allowed

    def consume_with_info(self, key: str) -> tuple[bool, int, int]:
        now = time.monotonic()
        window_start = now - self._window_seconds

        with self._lock:
            bucket = self._buckets.setdefault(key, _Bucket())

            while bucket.hits and bucket.hits[0] < window_start:
                bucket.hits.popleft()

            if len(bucket.hits) >= self._limit:
                oldest = bucket.hits[0]
                retry_after = max(1, math.ceil(self._window_seconds - (now - oldest)))
                return False, 0, retry_after

            bucket.hits.append(now)
            remaining = max(0, self._limit - len(bucket.hits))
            return True, remaining, self._window_seconds

    @property
    def limit(self) -> int:
        return self._limit
