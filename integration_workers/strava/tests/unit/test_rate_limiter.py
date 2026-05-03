"""
Unit tests for Strava rate limiter.

Validates enforcement of Strava's 100 requests / 15 minutes and
1000 requests / day rate limits, as well as header-based limit tracking.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from strava_rate_limiter import StravaRateLimiter, StravaRateLimitError


class TestRateLimiterAllowsRequests:
    """Requests within limits are allowed."""

    def test_allows_first_request(self) -> None:
        """The first request is always allowed."""
        limiter = StravaRateLimiter()
        limiter.check()  # Should not raise

    def test_allows_requests_within_short_limit(self) -> None:
        """Requests within the 15-minute limit (100) are allowed."""
        limiter = StravaRateLimiter()
        for _ in range(99):
            limiter.record_request()
        limiter.check()  # 100th request — should still be allowed


class TestRateLimiterBlocks:
    """Requests exceeding limits are blocked."""

    def test_blocks_when_short_limit_exceeded(self) -> None:
        """Raises StravaRateLimitError after 100 requests in 15 minutes."""
        limiter = StravaRateLimiter()
        for _ in range(100):
            limiter.record_request()

        with pytest.raises(StravaRateLimitError, match="15-minute"):
            limiter.check()

    def test_blocks_when_daily_limit_exceeded(self) -> None:
        """Raises StravaRateLimitError after 1000 requests in a day."""
        limiter = StravaRateLimiter()
        limiter._daily_count = 1000

        with pytest.raises(StravaRateLimitError, match="daily"):
            limiter.check()


class TestRateLimiterHeaderUpdates:
    """Limits updated from Strava response headers."""

    def test_updates_from_response_headers(self) -> None:
        """update_from_headers parses X-RateLimit-Limit and X-RateLimit-Usage."""
        limiter = StravaRateLimiter()
        headers = {
            "X-RateLimit-Limit": "100,1000",
            "X-RateLimit-Usage": "42,567",
        }
        limiter.update_from_headers(headers)

        assert limiter._short_count == 42
        assert limiter._daily_count == 567

    def test_handles_missing_headers_gracefully(self) -> None:
        """Missing rate limit headers do not raise."""
        limiter = StravaRateLimiter()
        limiter.update_from_headers({})
        # Should not raise; counts remain at 0
        limiter.check()


class TestRateLimiterReset:
    """Window-based reset behaviour."""

    def test_short_window_resets_after_15_minutes(self) -> None:
        """Short-term count resets after 15 minutes have elapsed."""
        limiter = StravaRateLimiter()
        for _ in range(100):
            limiter.record_request()

        # Simulate 16 minutes passing
        with patch.object(time, "monotonic", return_value=time.monotonic() + 16 * 60):
            limiter.check()  # Should not raise after reset

    def test_daily_window_resets_after_utc_midnight(self) -> None:
        """Daily count resets when the UTC date changes."""
        limiter = StravaRateLimiter()
        limiter._daily_count = 1000

        # Advance the stored date so the next check sees a new day
        limiter._daily_window_date -= 1

        limiter.check()  # Should not raise — daily count was reset
        assert limiter._daily_count == 0
