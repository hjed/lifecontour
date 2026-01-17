#!/usr/bin/env python3
"""
Unit tests for retry strategy implementation.

Tests exponential backoff with jitter for ARQ task retries.
"""

import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, "/core_shared")


class TestRetryDelayFunction:
    """Test cases for retry delay calculation with exponential backoff and jitter."""

    def test_retry_delay_first_retry(self):
        """Test retry delay for first retry (retry_count=0)."""
        from worker import retry_delay_func

        # First retry should be around 60 seconds (base delay)
        # With jitter of ±20%, range is 48-72 seconds
        delay = retry_delay_func(0)
        assert 48 <= delay <= 72, f"Expected delay between 48-72s, got {delay}s"

    def test_retry_delay_second_retry(self):
        """Test retry delay for second retry (retry_count=1)."""
        from worker import retry_delay_func

        # Second retry should be around 120 seconds (60 * 2^1)
        # With jitter of ±20%, range is 96-144 seconds
        delay = retry_delay_func(1)
        assert 96 <= delay <= 144, f"Expected delay between 96-144s, got {delay}s"

    def test_retry_delay_third_retry(self):
        """Test retry delay for third retry (retry_count=2)."""
        from worker import retry_delay_func

        # Third retry should be around 240 seconds (60 * 2^2)
        # With jitter of ±20%, range is 192-288 seconds
        delay = retry_delay_func(2)
        assert 192 <= delay <= 288, f"Expected delay between 192-288s, got {delay}s"

    def test_retry_delay_fourth_retry(self):
        """Test retry delay for fourth retry (retry_count=3)."""
        from worker import retry_delay_func

        # Fourth retry should be around 480 seconds (60 * 2^3)
        # With jitter of ±20%, range is 384-576 seconds
        delay = retry_delay_func(3)
        assert 384 <= delay <= 576, f"Expected delay between 384-576s, got {delay}s"

    def test_retry_delay_max_cap(self):
        """Test that retry delay is capped at 900 seconds (15 minutes)."""
        from worker import retry_delay_func

        # Fifth retry would be 960s (60 * 2^4) but should be capped at 900s
        # With jitter, max is 900 * 1.2 = 1080, but cap should apply first
        delay = retry_delay_func(4)
        assert delay <= 900, f"Expected delay capped at 900s, got {delay}s"

        # Even higher retry counts should still be capped
        delay = retry_delay_func(10)
        assert delay <= 900, f"Expected delay capped at 900s, got {delay}s"

    def test_retry_delay_deterministic_with_seed(self):
        """Test that retry delay is deterministic when random seed is set."""
        from worker import retry_delay_func

        # Set random seed for reproducibility
        with patch("random.uniform") as mock_uniform:
            mock_uniform.return_value = 1.0  # No jitter

            delay = retry_delay_func(0)
            assert delay == 60.0, f"Expected 60s with no jitter, got {delay}s"

            delay = retry_delay_func(1)
            assert delay == 120.0, f"Expected 120s with no jitter, got {delay}s"

    def test_retry_delay_jitter_variation(self):
        """Test that jitter produces variation in retry delays."""
        from worker import retry_delay_func

        # Run multiple times and verify we get different values due to jitter
        delays = [retry_delay_func(0) for _ in range(10)]

        # All delays should be in valid range
        assert all(48 <= d <= 72 for d in delays), f"Some delays out of range: {delays}"

        # Should have some variation (not all identical)
        # With 10 samples, very unlikely all are identical with random jitter
        num_unique_delays = len(set(delays))
        assert num_unique_delays > 1, f"Expected variation in delays, got {num_unique_delays} unique values"

    def test_retry_delay_exponential_growth(self):
        """Test that delays grow exponentially."""
        from worker import retry_delay_func

        # Calculate average delays for each retry count (to smooth out jitter)
        avg_delays = []
        for retry_count in range(4):
            delays = [retry_delay_func(retry_count) for _ in range(100)]
            avg_delays.append(sum(delays) / len(delays))

        # Each delay should be approximately double the previous
        for i in range(1, len(avg_delays)):
            ratio = avg_delays[i] / avg_delays[i - 1]
            assert 1.8 <= ratio <= 2.2, (
                f"Expected ~2x growth from retry {i-1} to {i}, "
                f"got {ratio:.2f}x ({avg_delays[i-1]:.1f}s -> {avg_delays[i]:.1f}s)"
            )

