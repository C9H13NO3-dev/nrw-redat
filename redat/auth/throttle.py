"""In-memory login throttle: 5 failures per (client IP, username) within 10 minutes → 60 s lock."""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional


class LoginThrottle:
    def __init__(self, max_failures: int = 5, window_s: int = 600, lock_s: int = 60, clock: Callable[[], float] = time.monotonic):
        self.max_failures, self.window_s, self.lock_s, self._clock = max_failures, window_s, lock_s, clock
        self._failures: dict[tuple, list[float]] = {}
        self._locked_until: dict[tuple, float] = {}
        self._lock = threading.Lock()

    def check(self, key: tuple) -> Optional[int]:
        """Seconds the key stays locked, or None when a login attempt may proceed."""
        with self._lock:
            until = self._locked_until.get(key)
            if until is None:
                return None
            remaining = until - self._clock()
            if remaining <= 0:
                del self._locked_until[key]
                self._failures.pop(key, None)
                return None
            return max(1, int(round(remaining)))

    def failure(self, key: tuple) -> None:
        now = self._clock()
        with self._lock:
            hits = [t for t in self._failures.get(key, []) if now - t < self.window_s] + [now]
            self._failures[key] = hits
            if len(hits) >= self.max_failures:
                self._locked_until[key] = now + self.lock_s
                self._failures[key] = []

    def success(self, key: tuple) -> None:
        with self._lock:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)


login_throttle = LoginThrottle()
