"""Unit tests for webhook re-register schemas and logic.

Tests:
- Webhook re-register response schemas
- Webhook URL response schemas
- TaskQueueService.enqueue_calendar_webhook_setup
- StravaWebhookService integration in force_resubscribe
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.integrations.schemas import (
    WebhookReregisterAttributes,
    WebhookReregisterData,
    WebhookReregisterResponse,
    WebhookUrlAttributes,
    WebhookUrlData,
    WebhookUrlResponse,
)

# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestWebhookReregisterResponse:
    """Tests for WebhookReregisterResponse schema."""

    def test_serializes_correctly(self):
        """Should serialise to JSON API format."""
        response = WebhookReregisterResponse(
            data=WebhookReregisterData(
                attributes=WebhookReregisterAttributes(
                    webhooks_queued=3,
                    message="Queued webhook re-registration for 3 calendar(s)",
                )
            )
        )
        dumped = response.model_dump()

        assert dumped["data"]["type"] == "webhook-reregister"
        assert dumped["data"]["attributes"]["webhooks_queued"] == 3
        assert "3 calendar(s)" in dumped["data"]["attributes"]["message"]

    def test_zero_webhooks_queued(self):
        """Should allow 0 webhooks_queued."""
        response = WebhookReregisterResponse(
            data=WebhookReregisterData(
                attributes=WebhookReregisterAttributes(
                    webhooks_queued=0,
                    message="No synced calendars found",
                )
            )
        )
        dumped = response.model_dump()
        assert dumped["data"]["attributes"]["webhooks_queued"] == 0


class TestWebhookUrlResponse:
    """Tests for WebhookUrlResponse schema."""

    def test_serializes_correctly(self):
        """Should serialise to JSON API format."""
        response = WebhookUrlResponse(
            data=WebhookUrlData(
                attributes=WebhookUrlAttributes(
                    webhook_url="https://example.com/api/integrations/snipeit/webhook",
                    message="Configure this URL in your Snipe-IT instance.",
                )
            )
        )
        dumped = response.model_dump()

        assert dumped["data"]["type"] == "webhook-url"
        assert (
            dumped["data"]["attributes"]["webhook_url"]
            == "https://example.com/api/integrations/snipeit/webhook"
        )

    def test_webhook_url_required(self):
        """Should require webhook_url field."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            WebhookUrlAttributes(message="test")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# TaskQueueService.enqueue_calendar_webhook_setup tests
# ---------------------------------------------------------------------------


class TestEnqueueCalendarWebhookSetup:
    """Tests for TaskQueueService.enqueue_calendar_webhook_setup."""

    @pytest.mark.asyncio
    async def test_enqueues_setup_calendar_webhook_task(self):
        """Should enqueue the setup_calendar_webhook ARQ task."""
        from app.core.integrations.task_queue_service import TaskQueueService

        mock_pool = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "test-job-id"
        mock_pool.enqueue_job = AsyncMock(return_value=mock_job)

        service = TaskQueueService(
            redis_settings=MagicMock(),
            settings=MagicMock(),
            db_manager=MagicMock(),
            redis_pool=mock_pool,
        )

        result = await service.enqueue_calendar_webhook_setup(
            google_account_email="user@gmail.com",
            user_id="user-123",
            google_calendar_id="cal-abc",
        )

        assert result == "test-job-id"
        mock_pool.enqueue_job.assert_called_once()
        call_args = mock_pool.enqueue_job.call_args
        assert call_args.args[0] == "setup_calendar_webhook"
        assert call_args.args[1] == "user@gmail.com"
        assert call_args.args[2] == "user-123"
        assert call_args.args[3] == "cal-abc"

    @pytest.mark.asyncio
    async def test_raises_on_none_job(self):
        """Should raise JobEnqueueError when pool returns None."""
        from app.core.integrations.exceptions import JobEnqueueError
        from app.core.integrations.task_queue_service import TaskQueueService

        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock(return_value=None)

        service = TaskQueueService(
            redis_settings=MagicMock(),
            settings=MagicMock(),
            db_manager=MagicMock(),
            redis_pool=mock_pool,
        )

        with pytest.raises(JobEnqueueError):
            await service.enqueue_calendar_webhook_setup(
                google_account_email="user@gmail.com",
                user_id="user-123",
                google_calendar_id="cal-abc",
            )

    @pytest.mark.asyncio
    async def test_does_not_persist_sync_job(self):
        """Webhook setup should NOT create a sync_jobs database record."""
        from app.core.integrations.task_queue_service import TaskQueueService

        mock_pool = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "test-job-id"
        mock_pool.enqueue_job = AsyncMock(return_value=mock_job)

        mock_db_manager = MagicMock()

        service = TaskQueueService(
            redis_settings=MagicMock(),
            settings=MagicMock(),
            db_manager=mock_db_manager,
            redis_pool=mock_pool,
        )

        await service.enqueue_calendar_webhook_setup(
            google_account_email="user@gmail.com",
            user_id="user-123",
            google_calendar_id="cal-abc",
        )

        # db_manager should not be accessed for webhook setup tasks
        mock_db_manager.get_session.assert_not_called()


# ---------------------------------------------------------------------------
# Strava webhook re-register logic tests
# ---------------------------------------------------------------------------


class TestStravaWebhookReregisterLogic:
    """Tests for the Strava webhook re-register business logic.

    These test the StravaWebhookService.force_resubscribe method which is
    the core logic behind the reregister endpoint.
    """

    @pytest.mark.asyncio
    async def test_force_resubscribe_with_existing_subscription(self):
        """Should delete existing subscription before creating new one."""
        from app.core.integrations.strava.webhook_service import (
            StravaWebhookService,
        )

        service = StravaWebhookService(
            client_id="client-id",
            client_secret="secret",
        )
        service.unsubscribe = AsyncMock()  # type: ignore[method-assign]
        service.subscribe = AsyncMock(return_value=99)  # type: ignore[method-assign]

        result = await service.force_resubscribe(
            callback_url="https://example.com/webhook",
            verify_token="new-token",
            existing_subscription_id=42,
        )

        assert result == 99
        service.unsubscribe.assert_called_once_with(42)
        service.subscribe.assert_called_once_with(
            "https://example.com/webhook", "new-token"
        )

    @pytest.mark.asyncio
    async def test_force_resubscribe_without_existing_subscription(self):
        """Should verify and delete before creating when no ID provided."""
        from app.core.integrations.strava.webhook_service import (
            StravaWebhookService,
        )

        service = StravaWebhookService(
            client_id="client-id",
            client_secret="secret",
        )
        service.verify_subscription = AsyncMock(return_value=None)  # type: ignore[method-assign]
        service.unsubscribe = AsyncMock()  # type: ignore[method-assign]
        service.subscribe = AsyncMock(return_value=100)  # type: ignore[method-assign]

        result = await service.force_resubscribe(
            callback_url="https://example.com/webhook",
            verify_token="new-token",
        )

        assert result == 100
        service.verify_subscription.assert_called_once()
        # No unsubscribe since verify returned None
        service.unsubscribe.assert_not_called()
