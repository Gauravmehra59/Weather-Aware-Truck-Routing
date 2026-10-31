"""Keep request rates within the public servers' usage policies (1 request/second)."""

import threading
import time


class RateLimiter:
    def __init__(self, min_interval_s):
        self.min_interval_s = min_interval_s
        self._last = float('-inf')
        self._lock = threading.Lock()

    def wait(self):
        """Block until at least `min_interval_s` has passed since the previous call."""
        with self._lock:
            delay = self._last + self.min_interval_s - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()
