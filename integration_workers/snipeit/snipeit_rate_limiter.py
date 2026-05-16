"""
Snipe-IT API rate limiter.

Simple request-per-minute rate limiter for Snipe-IT API calls.
Unlike Strava, Snipe-IT doesn't provide rate limit headers, so we
track counts locally and pre-emptively block when the limit is reached.
"""

from __future__ import annotations

import time

import structlog

logger = structlog.get_logger()

# Default: 120 requests per minute (conservative for self-hosted instances)
_DEFAULT_REQUESTS_PER_MINUTE = 120
_WINDOW_SECONDS = 60


class SnipeItRateLimitError(Exception):
    """Raised when a Snipe-IT API request would exceed rate limits.

    Attributes:
        retry_after: Suggested wait time in seconds, or ``None``.
    """

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class SnipeItRateLimiter:
    """Pre-emptive rate limiter for Snipe-IT API.

    Call ``acquire()`` before making a request to verify the request is
    within limits and record it.

    Args:
        requests_per_minute: Maximum requests allowed per minute window.
    """

    def __init__(self, requests_per_minute: int = _DEFAULT_REQUESTS_PER_MINUTE) -> None:
        self._limit = requests_per_minute
        self._count: int = 0
        self._window_start: float = time.monotonic()

    def acquire(self) -> None:
        """Raise ``SnipeItRateLimitError`` if limit exceeded, else record request."""
        self._maybe_reset_window()

        if self._count >= self._limit:
            elapsed = time.monotonic() - self._window_start
            retry_after = _WINDOW_SECONDS - elapsed
            raise SnipeItRateLimitError(
                f"Snipe-IT rate limit reached ({self._limit} requests/minute). "
                f"Retry after {retry_after:.0f}s.",
                retry_after=max(retry_after, 0),
            )

        self._count += 1

    def _maybe_reset_window(self) -> None:
        """Reset the counter if the 60-second window has elapsed."""
        elapsed = time.monotonic() - self._window_start
        if elapsed >= _WINDOW_SECONDS:
            self._count = 0
            self._window_start = time.monotonic()
