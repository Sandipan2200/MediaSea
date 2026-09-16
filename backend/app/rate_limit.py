"""In-memory sliding-window rate limiter (per-IP, per-endpoint).

Defaults: 20 analyses/min/IP — generous for humans pasting links, tight enough
to make SSRF probing and scraping expensive. Configurable via
MEDIASAVER_RATE_LIMIT_PER_MINUTE. For multi-replica deploys, swap the dict for
Redis; the interface (check() raising SafeFetchError) stays the same.
"""

from __future__ import annotations

import time
from collections import defaultdict

from .fetcher import SafeFetchError
from .schemas import ErrorCode


class RateLimiter:
    def __init__(self, per_minute: int = 20) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str) -> None:
        now = time.monotonic()
        window_start = now - 60.0
        hits = [t for t in self._hits[key] if t > window_start]
        self._hits[key] = hits
        if len(hits) >= self.per_minute:
            raise SafeFetchError(
                ErrorCode.RATE_LIMITED,
                "Too many requests — please wait a few seconds and try again.",
            )
        hits.append(now)
