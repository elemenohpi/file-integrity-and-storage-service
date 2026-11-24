# metrics.py -- course staff file, do not modify.
#
# Small, dependency-free helpers for turning raw, timestamped samples into
# the numbers the dashboard and the CSV files show.

import threading
import time


def percentile(values, p):
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def mean(values):
    return sum(values) / len(values) if values else None


class Clock:
    """Simulated clock: sim_ms = real_ms_elapsed * speed, starting at 0 the
    moment the gateway first answers."""

    def __init__(self, speed):
        self.speed = speed
        self._start = None
        self._start_epoch_ms = None
        self._lock = threading.Lock()

    def start(self):
        with self._lock:
            if self._start is None:
                self._start = time.monotonic()
                self._start_epoch_ms = time.time() * 1000.0

    def sim_ms_for_epoch(self, epoch_ms):
        with self._lock:
            if self._start_epoch_ms is None:
                return 0.0
            base = self._start_epoch_ms
        return max(0.0, (epoch_ms - base) * self.speed)

    def started(self):
        with self._lock:
            return self._start is not None

    def sim_ms(self):
        with self._lock:
            if self._start is None:
                return 0.0
            real_elapsed = time.monotonic() - self._start
        return real_elapsed * 1000.0 * self.speed

    def sim_seconds(self):
        return self.sim_ms() / 1000.0

    def real_seconds_for_sim(self, sim_seconds):
        """How many real seconds correspond to a duration of sim_seconds,
        at the current speed -- used to size real timeouts for hostile
        shell commands."""
        return max(0.05, sim_seconds / self.speed)

    def sleep_until_sim_ms(self, target_sim_ms):
        while True:
            now = self.sim_ms()
            remaining_sim_ms = target_sim_ms - now
            if remaining_sim_ms <= 0:
                return
            remaining_real_s = (remaining_sim_ms / 1000.0) / self.speed
            time.sleep(min(remaining_real_s, 1.0))
