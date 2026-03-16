"""Unit tests for periodic_sync_all_accounts calendar event scheduling.

Verifies that periodic_sync_all_accounts enqueues both sync_google_contacts
AND sync_calendar_events jobs for each active Google integration.
"""

import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, "/core_shared")


class TestPeriodicSyncCalendar:
    """Tests for calendar event sync scheduling in periodic_sync_all_accounts."""

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        return session

    @pytest.fixture
    def mock_session_factory(self, mock_session: AsyncMock) -> MagicMock:
        factory = MagicMock()
        factory.return_value = mock_session
        return factory

    @pytest.fixture
    def mock_redis(self) -> AsyncMock:
        redis = AsyncMock()
        redis.enqueue_job = AsyncMock()
        return redis

    @pytest.fixture
    def mock_ctx(
        self, mock_session_factory: MagicMock, mock_redis: AsyncMock
    ) -> dict[str, Any]:
        return {
            "session_factory": mock_session_factory,
            "redis": mock_redis,
        }

    @pytest.mark.asyncio
    async def test_enqueues_both_contacts_and_calendar_sync(
        self, mock_ctx: dict, mock_session: AsyncMock, mock_redis: AsyncMock
    ) -> None:
        """Should enqueue both sync_google_contacts AND sync_calendar_events per account."""
        from worker import periodic_sync_all_accounts

        # Use tuple rows — worker accesses row[0] and row[1] via index
        account_row = ("user-1", "test@example.com")
        result = MagicMock()
        result.fetchall.return_value = [account_row]
        mock_session.execute.return_value = result

        # Return a mock job for each enqueue call
        mock_job = MagicMock()
        mock_job.job_id = "job-123"
        mock_redis.enqueue_job.return_value = mock_job

        await periodic_sync_all_accounts(mock_ctx)

        # Should have been called twice: once for contacts, once for calendar
        assert mock_redis.enqueue_job.call_count == 2

        # Verify first call is contacts sync
        contacts_call = mock_redis.enqueue_job.call_args_list[0]
        assert contacts_call[0][0] == "sync_google_contacts"

        # Verify second call is calendar sync
        calendar_call = mock_redis.enqueue_job.call_args_list[1]
        assert calendar_call[0][0] == "sync_calendar_events"

    @pytest.mark.asyncio
    async def test_enqueues_calendar_sync_with_smart_type(
        self, mock_ctx: dict, mock_session: AsyncMock, mock_redis: AsyncMock
    ) -> None:
        """Calendar sync should use 'smart' sync type for periodic syncs."""
        from worker import periodic_sync_all_accounts

        account_row = ("user-1", "test@example.com")
        result = MagicMock()
        result.fetchall.return_value = [account_row]
        mock_session.execute.return_value = result

        mock_job = MagicMock()
        mock_job.job_id = "job-123"
        mock_redis.enqueue_job.return_value = mock_job

        await periodic_sync_all_accounts(mock_ctx)

        # Calendar sync call should use "smart"
        calendar_call = mock_redis.enqueue_job.call_args_list[1]
        assert calendar_call[0][2] == "user-1"  # user_id
        assert calendar_call[0][3] == "smart"  # sync_type

    @pytest.mark.asyncio
    async def test_handles_no_accounts_gracefully(
        self, mock_ctx: dict, mock_session: AsyncMock, mock_redis: AsyncMock
    ) -> None:
        """Should handle no active accounts without errors."""
        from worker import periodic_sync_all_accounts

        result = MagicMock()
        result.fetchall.return_value = []
        mock_session.execute.return_value = result

        result = await periodic_sync_all_accounts(mock_ctx)

        assert result["status"] == "success"
        assert result["accounts_found"] == 0
        assert result["jobs_enqueued"] == 0
        mock_redis.enqueue_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_counts_both_contacts_and_calendar_jobs(
        self, mock_ctx: dict, mock_session: AsyncMock, mock_redis: AsyncMock
    ) -> None:
        """jobs_enqueued should include both contacts and calendar sync jobs."""
        from worker import periodic_sync_all_accounts

        account_row = ("user-1", "test@example.com")
        result = MagicMock()
        result.fetchall.return_value = [account_row]
        mock_session.execute.return_value = result

        mock_job = MagicMock()
        mock_job.job_id = "job-123"
        mock_redis.enqueue_job.return_value = mock_job

        result = await periodic_sync_all_accounts(mock_ctx)

        assert result["jobs_enqueued"] == 2  # contacts + calendar

    @pytest.mark.asyncio
    async def test_calendar_sync_error_doesnt_prevent_next_account(
        self, mock_ctx: dict, mock_session: AsyncMock, mock_redis: AsyncMock
    ) -> None:
        """Calendar sync failure for one account shouldn't block other accounts."""
        from worker import periodic_sync_all_accounts

        account1 = ("user-1", "a@example.com")
        account2 = ("user-2", "b@example.com")
        result = MagicMock()
        result.fetchall.return_value = [account1, account2]
        mock_session.execute.return_value = result

        mock_job = MagicMock()
        mock_job.job_id = "job-123"

        # Contacts succeeds, calendar fails for first account, both succeed for second
        mock_redis.enqueue_job.side_effect = [
            mock_job,  # user-1 contacts
            Exception("Redis timeout"),  # user-1 calendar
            mock_job,  # user-2 contacts
            mock_job,  # user-2 calendar
        ]

        result = await periodic_sync_all_accounts(mock_ctx)

        assert result["status"] == "success"
        assert result["jobs_enqueued"] == 3  # 1+0+1+1
        assert len(result["errors"]) == 1
