"""Unit tests for the ``renew_calendar_webhooks`` ARQ task.

Google Calendar watch channels expire after their TTL (7 days), after which
push notifications silently stop arriving. This task re-registers channels
before they lapse by enqueueing a ``setup_calendar_webhook`` job per calendar.

The query that decides *which* calendars are due depends on real SQL across
three tables and is covered by
``tests/integration/test_webhook_renewal_integration.py``; it is patched out
here so these tests cover the fan-out and its failure handling.
"""

import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from core_shared.testing import make_arq_ctx, make_mock_redis

sys.path.insert(0, "/core_shared")


def make_due_calendar(
    user_id: str = "user-1",
    google_account_email: str = "test@example.com",
    google_calendar_id: str = "cal-1",
) -> Any:
    """Build a CalendarWatchRenewal row describing a calendar due for renewal."""
    from worker import CalendarWatchRenewal

    return CalendarWatchRenewal(
        user_id=user_id,
        google_account_email=google_account_email,
        google_calendar_id=google_calendar_id,
    )


class TestRenewCalendarWebhooks:
    """Tests for the ``renew_calendar_webhooks`` ARQ task."""

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
        redis = make_mock_redis()
        job = MagicMock()
        job.job_id = "job-123"
        redis.enqueue_job = AsyncMock(return_value=job)
        return redis

    @pytest.fixture
    def mock_ctx(
        self, mock_session_factory: MagicMock, mock_redis: AsyncMock
    ) -> dict[str, Any]:
        return make_arq_ctx(session_factory=mock_session_factory, redis=mock_redis)

    @pytest.mark.asyncio
    async def test_enqueues_setup_task_per_due_calendar(
        self, mock_ctx: dict, mock_redis: AsyncMock
    ) -> None:
        """Each calendar due for renewal gets its own setup_calendar_webhook job."""
        from worker import renew_calendar_webhooks

        due = [
            make_due_calendar("user-1", "a@example.com", "cal-1"),
            make_due_calendar("user-2", "b@example.com", "cal-2"),
        ]

        with (
            patch("worker.settings") as mock_settings,
            patch(
                "worker._select_calendars_due_for_renewal",
                new=AsyncMock(return_value=due),
            ),
        ):
            mock_settings.webhook_base_url = "https://example.com"
            mock_settings.webhook_renewal_threshold_hours = 48

            result = await renew_calendar_webhooks(mock_ctx)

        assert result["status"] == "success"
        assert mock_redis.enqueue_job.call_count == 2

        first_call = mock_redis.enqueue_job.call_args_list[0]
        assert first_call.args[0] == "setup_calendar_webhook"
        assert first_call.args[1] == "a@example.com"
        assert first_call.args[2] == "user-1"
        assert first_call.args[3] == "cal-1"

        second_call = mock_redis.enqueue_job.call_args_list[1]
        assert second_call.args[1] == "b@example.com"
        assert second_call.args[3] == "cal-2"

    @pytest.mark.asyncio
    async def test_skips_when_webhook_base_url_unset(
        self, mock_ctx: dict, mock_redis: AsyncMock
    ) -> None:
        """Without a webhook URL there is nothing to renew channels for."""
        from worker import renew_calendar_webhooks

        with patch("worker.settings") as mock_settings:
            mock_settings.webhook_base_url = ""

            result = await renew_calendar_webhooks(mock_ctx)

        assert result["status"] == "skipped"
        mock_redis.enqueue_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_continues_after_enqueue_failure(
        self, mock_ctx: dict, mock_redis: AsyncMock
    ) -> None:
        """One calendar failing to enqueue must not strand the others."""
        from worker import renew_calendar_webhooks

        due = [
            make_due_calendar("user-1", "a@example.com", "cal-1"),
            make_due_calendar("user-2", "b@example.com", "cal-2"),
            make_due_calendar("user-3", "c@example.com", "cal-3"),
        ]

        job = MagicMock()
        job.job_id = "job-ok"
        mock_redis.enqueue_job = AsyncMock(
            side_effect=[job, RuntimeError("redis down"), job]
        )

        with (
            patch("worker.settings") as mock_settings,
            patch(
                "worker._select_calendars_due_for_renewal",
                new=AsyncMock(return_value=due),
            ),
        ):
            mock_settings.webhook_base_url = "https://example.com"
            mock_settings.webhook_renewal_threshold_hours = 48

            result = await renew_calendar_webhooks(mock_ctx)

        assert mock_redis.enqueue_job.call_count == 3
        assert result["jobs_enqueued"] == 2
        assert len(result["errors"]) == 1

    @pytest.mark.asyncio
    async def test_returns_summary_counts(
        self, mock_ctx: dict, mock_redis: AsyncMock
    ) -> None:
        """The result summarises what the run found and dispatched."""
        from worker import renew_calendar_webhooks

        due = [make_due_calendar()]

        with (
            patch("worker.settings") as mock_settings,
            patch(
                "worker._select_calendars_due_for_renewal",
                new=AsyncMock(return_value=due),
            ),
        ):
            mock_settings.webhook_base_url = "https://example.com"
            mock_settings.webhook_renewal_threshold_hours = 48

            result = await renew_calendar_webhooks(mock_ctx)

        assert result["status"] == "success"
        assert result["calendars_due"] == 1
        assert result["jobs_enqueued"] == 1
        assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_handles_no_calendars_due(
        self, mock_ctx: dict, mock_redis: AsyncMock
    ) -> None:
        """A run with nothing due is a success, not an error."""
        from worker import renew_calendar_webhooks

        with (
            patch("worker.settings") as mock_settings,
            patch(
                "worker._select_calendars_due_for_renewal",
                new=AsyncMock(return_value=[]),
            ),
        ):
            mock_settings.webhook_base_url = "https://example.com"
            mock_settings.webhook_renewal_threshold_hours = 48

            result = await renew_calendar_webhooks(mock_ctx)

        assert result["status"] == "success"
        assert result["calendars_due"] == 0
        mock_redis.enqueue_job.assert_not_called()
