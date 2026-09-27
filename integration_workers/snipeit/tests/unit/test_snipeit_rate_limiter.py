"""Tests for Snipe-IT rate limiter."""

import time
from unittest.mock import patch

import pytest

from snipeit_rate_limiter import (
    SnipeItRateLimiter,
    SnipeItRateLimitError,
    rate_limiter_for,
)


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


class TestWaitForSlot:
    """``wait_for_slot`` waits out a full window instead of raising."""

    @pytest.mark.asyncio
    async def test_returns_at_once_while_within_the_limit(self) -> None:
        limiter = SnipeItRateLimiter(requests_per_minute=2)
        with patch("snipeit_rate_limiter.asyncio.sleep") as sleep:
            await limiter.wait_for_slot()
            await limiter.wait_for_slot()
        sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_sleeps_until_the_window_resets_then_counts_the_request(
        self,
    ) -> None:
        clock = [1000.0]
        with patch("snipeit_rate_limiter.time.monotonic", side_effect=lambda: clock[0]):
            limiter = SnipeItRateLimiter(requests_per_minute=1)
            await limiter.wait_for_slot()
            clock[0] += 20

            async def advance(seconds: float) -> None:
                clock[0] += seconds

            with patch(
                "snipeit_rate_limiter.asyncio.sleep", side_effect=advance
            ) as sleep:
                await limiter.wait_for_slot()

            sleep.assert_awaited_once_with(40)
            # The slot it waited for is taken: the next caller waits again.
            with pytest.raises(SnipeItRateLimitError):
                limiter.acquire()


class TestSharedRateLimiter:
    """Every client using one API key on one instance counts against one budget.

    Snipe-IT throttles each API key, so another key on the same instance, e.g.
    another user's, has a budget of its own.
    """

    def test_one_key_on_one_instance_shares_a_limiter(self) -> None:
        first = rate_limiter_for("https://snipe.example.com/", "key-1")
        assert rate_limiter_for("https://snipe.example.com", "key-1") is first

    def test_another_key_on_the_same_instance_has_its_own(self) -> None:
        assert rate_limiter_for("https://snipe.example.com", "key-1") is not (
            rate_limiter_for("https://snipe.example.com", "key-2")
        )

    def test_another_instance_has_its_own(self) -> None:
        assert rate_limiter_for("https://a.example.com", "key-1") is not (
            rate_limiter_for("https://b.example.com", "key-1")
        )

    def test_the_api_key_is_not_kept_in_the_clear(self) -> None:
        from snipeit_rate_limiter import _shared_limiters

        rate_limiter_for("https://snipe.example.com", "secret-api-key")
        assert not any("secret-api-key" in key for key in _shared_limiters)
