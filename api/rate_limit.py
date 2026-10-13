"""Fixed-window rate limit for new live generations."""
import threading
import time


class RateLimiter:
    def __init__(self, limit: int = 5, window_seconds: int = 3600, clock=None):
        self.limit = limit
        self.window = window_seconds
        self.clock = clock or time.time
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self.clock()
        with self._lock:
            hits = [stamp for stamp in self._hits.get(key, []) if now - stamp < self.window]
            if len(hits) >= self.limit:
                self._hits[key] = hits
                return False
            hits.append(now)
            self._hits[key] = hits
            return True
