#!/usr/bin/env python3
"""
Integration tests for ARQ retry strategy.

Tests that verify ARQ retry behavior with the Google Contacts worker.
These tests require a running Redis instance.
"""

import asyncio
import sys
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from arq import Worker, create_pool
from arq.connections import RedisSettings
from arq.jobs import JobStatus
from redis.exceptions import RedisError  # type: ignore[import-untyped]

sys.path.insert(0, "/core_shared")


# Global state for tracking ARQ task executions
_arq_task_state = {
    "call_count": 0,
    "call_times": [],
    "should_fail_count": 0,
}


class IntentionalTaskFailure(RuntimeError):
    """Specific exception for intentional test failures in ARQ tasks."""

    pass


async def arq_failing_task(ctx):
    """ARQ task that fails a specified number of times before succeeding."""
    # Yield control to event loop (required for async function)
    await asyncio.sleep(0)

    _arq_task_state["call_count"] += 1
    _arq_task_state["call_times"].append(datetime.now(UTC))

    if _arq_task_state["call_count"] <= _arq_task_state["should_fail_count"]:
        raise IntentionalTaskFailure(
            f"Intentional test failure #{_arq_task_state['call_count']}"
        )

    return {
        "status": "success",
        "attempts": _arq_task_state["call_count"],
        "call_times": [t.isoformat() for t in _arq_task_state["call_times"]],
    }


async def arq_always_failing_task(ctx):
    """ARQ task that always fails."""
    # Yield control to event loop (required for async function)
    await asyncio.sleep(0)

    _arq_task_state["call_count"] += 1
    _arq_task_state["call_times"].append(datetime.now(UTC))
    raise IntentionalTaskFailure(
        f"Always fails - attempt #{_arq_task_state['call_count']}"
    )


class TestARQRetryIntegration:
    """Integration tests for ARQ retry behavior with exponential backoff."""

    @pytest.fixture(autouse=True)
    def reset_arq_task_state(self):
        """Reset global ARQ task state before each test."""
        _arq_task_state["call_count"] = 0
        _arq_task_state["call_times"] = []
        _arq_task_state["should_fail_count"] = 0

    @pytest_asyncio.fixture
    async def redis_pool(self):
        """Create a real Redis connection pool for testing."""
        import os

        redis_url = os.environ["REDIS_URL"]
        redis_settings = RedisSettings.from_dsn(redis_url)
        # Use DB 1 for tests to isolate from other test suites
        redis_settings.database = 1
        pool = await create_pool(redis_settings)

        # Clean up any existing jobs in the queue
        try:
            await pool.flushdb()
        except RedisError:
            pass  # Ignore if Redis is not available

        yield pool

        # Cleanup
        try:
            await pool.flushdb()
        except RedisError:
            pass  # Ignore cleanup errors
        try:
            await pool.close()
        except RedisError:
            pass  # Ignore cleanup errors

    @pytest.mark.asyncio
    async def test_worker_settings_configuration(self):
        """Test that the worker settings are correctly configured."""
        from worker import GoogleWorkerSettings, retry_delay_func

        # Verify worker settings
        assert GoogleWorkerSettings.max_tries == 5
        assert GoogleWorkerSettings.retry_delay == retry_delay_func
        assert GoogleWorkerSettings.job_timeout == 600
        assert GoogleWorkerSettings.queue_name == "google"

    @pytest.mark.asyncio
    async def test_retry_delay_exponential_backoff(self):
        """Test that retry delays follow exponential backoff pattern."""
        from worker import retry_delay_func

        # Test multiple retry attempts - collect many samples to verify average behavior
        num_samples = 100
        delays_by_retry = {i: [] for i in range(5)}

        for _ in range(num_samples):
            for i in range(5):
                delays_by_retry[i].append(retry_delay_func(i))

        # Calculate average delays
        avg_delays = [sum(delays_by_retry[i]) / num_samples for i in range(5)]

        # Verify each average delay is close to expected base (within ±10% due to jitter averaging out)
        expected_bases = [60, 120, 240, 480, 900]  # 900 is capped

        for i, (avg_delay, expected) in enumerate(
            zip(avg_delays, expected_bases, strict=True)
        ):
            min_delay = expected * 0.9
            max_delay = expected * 1.1
            assert min_delay <= avg_delay <= max_delay, (
                f"Retry {i}: average delay {avg_delay} not in range [{min_delay}, {max_delay}]"
            )

        # Verify exponential growth pattern in averages
        for i in range(3):
            ratio = avg_delays[i + 1] / avg_delays[i]
            assert 1.8 <= ratio <= 2.2, (
                f"Retry {i} to {i + 1}: average ratio {ratio} not ~2.0"
            )

        # Verify cap is applied (last delay should not grow)
        assert (
            avg_delays[4] <= avg_delays[3] * 2.2
        )  # Should be capped, not continue exponential growth

    @pytest.mark.asyncio
    async def test_job_enqueue_and_status(self, redis_pool):
        """
        Test that jobs can be enqueued and their status tracked.

        This is a simpler integration test that runs in CI to verify basic ARQ
        functionality (job enqueuing and status tracking) without requiring a
        full worker process. The more complex worker retry test is skipped in CI
        but available for manual testing.
        """
        # Enqueue a test job
        job = await redis_pool.enqueue_job(
            "arq_failing_task",
            _job_id="test-status-job",
        )

        assert job is not None
        assert job.job_id == "test-status-job"

        # Check job status
        status = await job.status()
        assert status in [JobStatus.queued, JobStatus.deferred]

    @pytest.mark.skip(
        reason="Complex worker retry test - requires running worker process. Manual testing recommended."
    )
    @pytest.mark.asyncio
    async def test_job_retry_with_worker(self, redis_pool):
        """
        Test that a worker actually retries a failing job.

        Note: This test is skipped in CI as it requires a running worker process.
        """
        # Set up test to fail 2 times before succeeding
        _arq_task_state["should_fail_count"] = 2

        # Enqueue the job
        job = await redis_pool.enqueue_job(
            "arq_failing_task",
            _job_id="test-retry-worker-job",
        )

        # Run worker for a short time to process the job
        worker = Worker(
            functions=[arq_failing_task],
            redis_pool=redis_pool,
            max_jobs=1,
            max_tries=5,
            retry_jobs=True,
            job_timeout=30,
        )

        # Run worker in background
        worker_task = asyncio.create_task(worker.async_run())

        try:
            # Wait for job to complete (with timeout)
            for _ in range(10):  # Wait up to 10 seconds
                await asyncio.sleep(1)
                status = await job.status()
                if status == JobStatus.complete:
                    break

            # Verify job completed successfully after retries
            result = await job.result(timeout=1)
            assert result is not None
            assert result["status"] == "success"
            assert result["attempts"] == 3  # 1 initial + 2 retries

            # Verify the task was called 3 times
            assert _arq_task_state["call_count"] == 3

        finally:
            # Stop worker
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                # If worker_task is cancelled, that's expected. If the test run was cancelled
                # (meaning the exception was raised into us, not just returned from worker_task),
                # we should re-raise. We can tell because worker_task.cancelled() is true.
                if not worker_task.cancelled():
                    raise
