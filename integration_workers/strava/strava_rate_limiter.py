"""
Strava API rate limiter.

Tracks request counts against Strava's two-tier rate limits:

- **Short-term:** 100 requests per 15-minute window
- **Daily:** 1000 requests per day

Counts are seeded from Strava response headers (``X-RateLimit-Usage``)
when available, and also tracked locally so the client can pre-emptively
block before the API rejects with 429.
"""

from __future__ import annotations

import time
from collections.abc import Mapping

import structlog

logger = structlog.get_logger()

# Strava default rate limits
_SHORT_LIMIT = 100  # requests per 15 minutes
_DAILY_LIMIT = 1000  # requests per day
_SHORT_WINDOW_SECONDS = 15 * 60  # 15 minutes


class StravaRateLimitError(Exception):
    """Raised when a Strava API request would exceed rate limits.

    Attributes:
        retry_after: Suggested wait time in seconds, or ``None``.
    """

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class StravaRateLimiter:
    """Pre-emptive rate limiter for Strava API v3.

    Call ``check()`` before making a request to verify the request is within
    limits, and ``record_request()`` after each successful dispatch. When
    Strava response headers are available, call ``update_from_headers()``
    to synchronise counts with the server's view.
    """

    def __init__(self) -> None:
        self._short_count: int = 0
        self._daily_count: int = 0
        self._short_window_start: float = time.monotonic()

    def check(self) -> None:
        """Raise ``StravaRateLimitError`` if the next request would exceed limits."""
        self._maybe_reset_short_window()

        if self._short_count >= _SHORT_LIMIT:
            elapsed = time.monotonic() - self._short_window_start
            retry_after = _SHORT_WINDOW_SECONDS - elapsed
            raise StravaRateLimitError(
                f"Strava 15-minute rate limit reached ({_SHORT_LIMIT} requests). "
                f"Retry after {retry_after:.0f}s.",
                retry_after=max(retry_after, 0),
            )

        if self._daily_count >= _DAILY_LIMIT:
            raise StravaRateLimitError(
                f"Strava daily rate limit reached ({_DAILY_LIMIT} requests). "
                "Retry after midnight UTC.",
            )

    def record_request(self) -> None:
        """Record that a request was made."""
        self._maybe_reset_short_window()
        self._short_count += 1
        self._daily_count += 1

    def update_from_headers(self, headers: Mapping[str, str]) -> None:
        """Synchronise counts from Strava response headers.

        Strava returns two comma-separated values:
        - ``X-RateLimit-Limit: {15min_limit},{daily_limit}``
        - ``X-RateLimit-Usage: {15min_usage},{daily_usage}``

        Args:
            headers: HTTP response headers (case-insensitive mapping).
        """
        usage = headers.get("X-RateLimit-Usage")
        if not usage:
            return

        parts = usage.split(",")
        if len(parts) >= 2:
            try:
                self._short_count = int(parts[0].strip())
                self._daily_count = int(parts[1].strip())
                logger.debug(
                    "Updated rate limits from headers",
                    short_count=self._short_count,
                    daily_count=self._daily_count,
                )
            except ValueError:
                logger.warning(
                    "Could not parse X-RateLimit-Usage header",
                    raw_value=usage,
                )

    def _maybe_reset_short_window(self) -> None:
        """Reset the short-term counter if the 15-minute window has elapsed."""
        elapsed = time.monotonic() - self._short_window_start
        if elapsed >= _SHORT_WINDOW_SECONDS:
            self._short_count = 0
            self._short_window_start = time.monotonic()
