"""Tests for Snipe-IT rate limiter."""

import time
from unittest.mock import patch

import pytest

from snipeit_rate_limiter import SnipeItRateLimiter, SnipeItRateLimitError


class TestSnipeItRateLimiter:
    """Tests for the SnipeItRateLimiter."""

    def test_allows_requests_within_limit(self) -> None:
        """Requests within the configured limit are allowed."""
        limiter = SnipeItRateLimiter(requests_per_minute=5)
        for _ in range(5):
            limiter.acquire()

    def test_raises_when_limit_exceeded(self) -> None:
        """Exceeding the limit raises SnipeItRateLimitError."""
        limiter = SnipeItRateLimiter(requests_per_minute=3)
        for _ in range(3):
            limiter.acquire()

        with pytest.raises(SnipeItRateLimitError, match="rate limit"):
            limiter.acquire()

    def test_resets_after_window_expires(self) -> None:
        """Counter resets after the 60-second window elapses."""
        limiter = SnipeItRateLimiter(requests_per_minute=2)
        limiter.acquire()
        limiter.acquire()

        # Simulate window expiry by patching monotonic time
        with patch.object(time, "monotonic", return_value=time.monotonic() + 61):
            limiter.acquire()  # Should not raise

    def test_retry_after_value_is_positive(self) -> None:
        """The error includes a positive retry_after value."""
        limiter = SnipeItRateLimiter(requests_per_minute=1)
        limiter.acquire()

        with pytest.raises(SnipeItRateLimitError) as exc_info:
            limiter.acquire()
        assert exc_info.value.retry_after is not None
        assert exc_info.value.retry_after >= 0

    def test_default_limit(self) -> None:
        """Default limit is 120 requests/minute."""
        limiter = SnipeItRateLimiter()
        # Should handle many requests without raising
        for _ in range(120):
            limiter.acquire()

        with pytest.raises(SnipeItRateLimitError):
            limiter.acquire()
