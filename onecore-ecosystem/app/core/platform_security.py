"""Dependency-free process-local authentication abuse controls.

This is a per-worker safety net, not a distributed quota service. Production
deployments must also enforce rate limits at a trusted ingress or WAF.
"""
from collections import defaultdict, deque
from threading import Lock
from time import monotonic


class LoginRateLimiter:
    def __init__(self, max_attempts: int = 5, window_seconds: int = 60):
        if max_attempts < 1 or window_seconds < 1:
            raise ValueError("Rate limit settings must be positive")
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        now = monotonic()
        with self._lock:
            if len(self._attempts) >= 10000 and key not in self._attempts:
                cutoff = now - self.window_seconds
                for candidate in list(self._attempts):
                    bucket = self._attempts[candidate]
                    while bucket and bucket[0] <= cutoff:
                        bucket.popleft()
                    if not bucket:
                        self._attempts.pop(candidate, None)
                if len(self._attempts) >= 10000:
                    return False
            bucket = self._attempts[key]
            cutoff = now - self.window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self.max_attempts:
                return False
            bucket.append(now)
            return True

    def reset(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)
