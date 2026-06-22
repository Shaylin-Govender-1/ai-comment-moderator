"""A small, dependency-free per-user rate limiter (bonus feature).

A fixed-window counter keyed by ``user_id``. It is deliberately self-contained
so it can be unit-tested without spinning up HTTP, and keyed on the user id from
the request body (which is exactly the "per user" requirement) rather than IP.

For a single-process deployment this is sufficient. A multi-process / multi-node
deployment would back this with Redis instead — the interface would not change.
"""

from __future__ import annotations

import threading
import time

from app.core.errors import RateLimitExceededError

_UNIT_SECONDS = {"second": 1, "minute": 60, "hour": 3600}


def parse_rate(rate: str) -> tuple[int, int]:
    """Parse a rate string like ``"10/minute"`` into ``(limit, window_seconds)``."""
    try:
        count_str, unit = rate.split("/")
        count = int(count_str)
        window = _UNIT_SECONDS[unit.strip().lower().rstrip("s")]
        if count <= 0:
            raise ValueError
        return count, window
    except (ValueError, KeyError) as exc:
        raise ValueError(
            f"Invalid rate '{rate}'. Use '<count>/<second|minute|hour>', e.g. '10/minute'."
        ) from exc


class RateLimiter:
    """Fixed-window rate limiter keyed by an arbitrary string (here: user id)."""

    def __init__(self, rate: str, enabled: bool = True) -> None:
        self.enabled = enabled
        self.limit, self.window = parse_rate(rate)
        self._lock = threading.Lock()
        # key -> (window_start_monotonic, count_in_window)
        self._buckets: dict[str, tuple[float, int]] = {}
        self._last_sweep = 0.0

    def _sweep(self, now: float) -> None:
        """Drop buckets whose window has fully elapsed (called under the lock).

        Without this the dict would grow unbounded as new users appear. Sweeping
        is throttled to at most once per window, so it stays cheap.
        """
        expired = [k for k, (start, _) in self._buckets.items() if now - start >= self.window]
        for k in expired:
            del self._buckets[k]
        self._last_sweep = now

    def check(self, key: str) -> None:
        """Record a hit for ``key``; raise ``RateLimitExceededError`` if over limit."""
        if not self.enabled:
            return

        now = time.monotonic()
        with self._lock:
            if now - self._last_sweep >= self.window:
                self._sweep(now)
            start, count = self._buckets.get(key, (now, 0))
            if now - start >= self.window:
                # Window expired — reset.
                start, count = now, 0

            if count >= self.limit:
                retry_after = int(self.window - (now - start)) + 1
                raise RateLimitExceededError(
                    f"Rate limit of {self.limit} requests per {self.window}s exceeded. "
                    f"Try again in ~{retry_after}s."
                )

            self._buckets[key] = (start, count + 1)

    def reset(self) -> None:
        """Clear all counters (useful in tests)."""
        with self._lock:
            self._buckets.clear()
