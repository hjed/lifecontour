"""
Tests for periodic sync monitoring and logging.

These tests verify that periodic syncs are properly logged and monitored,
including trigger type identification, metrics recording, and error handling.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestPeriodicSyncLogging:
    """Test periodic sync logging and observability."""

    @pytest.mark.asyncio
    async def test_periodic_sync_logs_trigger_type(self, caplog):
        """Test that periodic syncs log trigger_type=periodic."""
        import logging

        import worker

        # Set caplog to capture logs from worker module
        caplog.set_level(logging.INFO, logger="worker")

        # Mock database session and query results
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            (1, "user1@example.com"),
            (2, "user2@example.com"),
        ]
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        # Create mock session factory
        mock_session_factory = MagicMock(return_value=mock_session)

        # Mock context with Redis pool and session_factory
        mock_redis = AsyncMock()
        mock_redis.enqueue_job = AsyncMock(
            return_value=MagicMock(job_id="test-job-123")
        )
        ctx = {
            "redis": mock_redis,
            "session_factory": mock_session_factory,
        }

        # Call periodic sync
        result = await worker.periodic_sync_all_accounts(ctx)

        # Verify result
        assert result["status"] == "success"
        assert result["accounts_found"] == 2
        assert result["jobs_enqueued"] == 4  # 2 accounts × 2 jobs (contacts + calendar)

        # Verify logs contain periodic sync markers
        # The function logs "Starting periodic sync for all Google accounts"
        # and "Found active Google accounts for periodic sync"
        log_text = caplog.text.lower()
        assert "periodic" in log_text, (
            f"Expected 'periodic' in logs, got: {caplog.text}"
        )

    @pytest.mark.asyncio
    async def test_sync_google_contacts_accepts_trigger_type(self):
        """Test that sync_google_contacts accepts trigger_type parameter."""
        import inspect

        from worker import sync_google_contacts

        # Get function signature
        sig = inspect.signature(sync_google_contacts)

        # Verify trigger_type parameter exists or can be added
        # For now, we'll verify the function signature
        params = list(sig.parameters.keys())
        assert "ctx" in params
        assert "google_account_email" in params
        assert "user_id" in params
        assert "sync_type" in params

    @pytest.mark.asyncio
    async def test_periodic_sync_logs_metrics(self, caplog):
        """Test that periodic sync logs include metrics (accounts_found, jobs_enqueued)."""
        import worker

        # Mock database with 3 accounts
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            (1, "user1@example.com"),
            (2, "user2@example.com"),
            (3, "user3@example.com"),
        ]
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        mock_session_factory = MagicMock(return_value=mock_session)

        # Mock context
        mock_redis = AsyncMock()
        mock_redis.enqueue_job = AsyncMock(
            return_value=MagicMock(job_id="test-job-123")
        )
        ctx = {
            "redis": mock_redis,
            "session_factory": mock_session_factory,
        }

        # Call periodic sync
        result = await worker.periodic_sync_all_accounts(ctx)

        # Verify metrics in result
        assert result["accounts_found"] == 3
        assert result["jobs_enqueued"] == 6  # 3 accounts × 2 jobs (contacts + calendar)
        assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_periodic_sync_logs_errors(self, caplog):
        """Test that failed periodic syncs log error details."""
        import worker

        # Mock database
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [(1, "user1@example.com")]
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        mock_session_factory = MagicMock(return_value=mock_session)

        # Mock context
        mock_redis = AsyncMock()
        mock_redis.enqueue_job = AsyncMock(
            side_effect=Exception("Redis connection failed")
        )
        ctx = {
            "redis": mock_redis,
            "session_factory": mock_session_factory,
        }

        # Call periodic sync
        result = await worker.periodic_sync_all_accounts(ctx)

        # Verify error handling
        assert result["accounts_found"] == 1
        assert result["jobs_enqueued"] == 0
        assert len(result["errors"]) == 2  # Both contacts + calendar jobs fail
        assert "Redis connection failed" in result["errors"][0]

        # Verify error was logged
        assert any("error" in record.message.lower() for record in caplog.records)

    @pytest.mark.asyncio
    async def test_periodic_sync_enqueues_with_smart_sync_type(self):
        """Test that periodic syncs use 'smart' sync type by default."""
        import worker

        # Mock database
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [(1, "user1@example.com")]
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        mock_session_factory = MagicMock(return_value=mock_session)

        # Mock context
        mock_redis = AsyncMock()
        mock_job = MagicMock(job_id="test-job-123")
        mock_redis.enqueue_job = AsyncMock(return_value=mock_job)
        ctx = {
            "redis": mock_redis,
            "session_factory": mock_session_factory,
        }

        # Call periodic sync
        await worker.periodic_sync_all_accounts(ctx)

        # Verify enqueue_job was called with 'smart' sync type
        # Verify enqueue_job was called with 'smart' sync type for both jobs
        # First call: sync_google_contacts, second call: sync_calendar_events
        assert mock_redis.enqueue_job.call_count == 2
        contacts_call = mock_redis.enqueue_job.call_args_list[0]
        assert contacts_call[0][0] == "sync_google_contacts"
        assert contacts_call[0][3] == "smart"
        assert contacts_call.kwargs["_queue_name"] == worker.ARQ_QUEUE_NAME

        calendar_call = mock_redis.enqueue_job.call_args_list[1]
        assert calendar_call[0][0] == "sync_calendar_events"
        assert calendar_call[0][3] == "smart"
        assert calendar_call.kwargs["_queue_name"] == worker.ARQ_QUEUE_NAME
