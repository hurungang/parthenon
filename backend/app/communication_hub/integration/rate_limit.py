"""In-memory per-client rate limiter for the integration gateway.

A simple sliding-window counter keyed by client id. This is sufficient for a
single Communication Hub process; a shared store (Redis) would be required for
horizontal scaling (documented in deployment notes).
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

_WINDOW_SECONDS = {"per_minute": 60, "per_hour": 3600, "per_day": 86400}

_buckets: dict[str, deque[float]] = defaultdict(deque)
_lock = Lock()


def is_rate_limited(key: str, limit: int | None, window: str | None) -> bool:
    """Return True when *key* has exceeded *limit* within *window*."""
    if not limit or not window:
        return False
    seconds = _WINDOW_SECONDS.get(window, 60)
    now = time.time()
    with _lock:
        bucket = _buckets[key]
        cutoff = now - seconds
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            return True
        bucket.append(now)
        return False


def reset() -> None:
    """Clear all counters (test helper)."""
    with _lock:
        _buckets.clear()
