"""
Unit tests for Strava webhook endpoints and subscription service.

Tests cover the validation handshake (hub.challenge), event payload
parsing for each aspect_type, ARQ task enqueue, and the webhook
subscription lifecycle (subscribe, unsubscribe, verify, force_resubscribe).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.integrations.strava.webhook_service import (
    StravaWebhookError,
    StravaWebhookService,
)

# ---------------------------------------------------------------------------
# StravaWebhookService unit tests
# ---------------------------------------------------------------------------


class TestStravaWebhookServiceSubscribe:
    """Tests for StravaWebhookService.subscribe."""

    @pytest.mark.asyncio
    async def test_subscribe_sends_correct_payload(self) -> None:
        """subscribe() POSTs correct form data to Strava push_subscriptions."""
        service = StravaWebhookService(client_id="test-id", client_secret="test-secret")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": 12345}
        mock_response.raise_for_status = MagicMock()

        with patch(
            "app.core.integrations.strava.webhook_service.httpx.AsyncClient"
        ) as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await service.subscribe(
                callback_url="https://example.com/webhook",
                verify_token="my-verify-token",
            )

        assert result == 12345
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs["data"]["client_id"] == "test-id"
        assert call_kwargs.kwargs["data"]["client_secret"] == "test-secret"
        assert (
            call_kwargs.kwargs["data"]["callback_url"] == "https://example.com/webhook"
        )
        assert call_kwargs.kwargs["data"]["verify_token"] == "my-verify-token"

    @pytest.mark.asyncio
    async def test_subscribe_raises_on_http_error(self) -> None:
        """subscribe() raises StravaWebhookError on HTTP errors."""
        import httpx

        service = StravaWebhookService(client_id="test-id", client_secret="test-secret")

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 409
        mock_response.text = "Subscription already exists"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "409", request=MagicMock(), response=mock_response
        )

        with patch(
            "app.core.integrations.strava.webhook_service.httpx.AsyncClient"
        ) as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with pytest.raises(StravaWebhookError, match="409"):
                await service.subscribe(
                    callback_url="https://example.com/webhook",
                    verify_token="token",
                )


class TestStravaWebhookServiceUnsubscribe:
    """Tests for StravaWebhookService.unsubscribe."""

    @pytest.mark.asyncio
    async def test_unsubscribe_sends_delete(self) -> None:
        """unsubscribe() sends DELETE to Strava push_subscriptions/{id}."""
        service = StravaWebhookService(client_id="test-id", client_secret="test-secret")

        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_response.raise_for_status = MagicMock()

        with patch(
            "app.core.integrations.strava.webhook_service.httpx.AsyncClient"
        ) as mock_cls:
            mock_client = AsyncMock()
            mock_client.delete.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            await service.unsubscribe(subscription_id=12345)

        mock_client.delete.assert_called_once()
        call_args = mock_client.delete.call_args
        assert "12345" in call_args.args[0]
        assert call_args.kwargs["params"]["client_id"] == "test-id"


class TestStravaWebhookServiceVerify:
    """Tests for StravaWebhookService.verify_subscription."""

    @pytest.mark.asyncio
    async def test_verify_returns_id_when_active(self) -> None:
        """verify_subscription() returns subscription ID when one exists."""
        service = StravaWebhookService(client_id="test-id", client_secret="test-secret")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"id": 99, "callback_url": "https://..."}]
        mock_response.raise_for_status = MagicMock()

        with patch(
            "app.core.integrations.strava.webhook_service.httpx.AsyncClient"
        ) as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await service.verify_subscription()

        assert result == 99

    @pytest.mark.asyncio
    async def test_verify_returns_none_when_no_subscription(self) -> None:
        """verify_subscription() returns None when no subscription exists."""
        service = StravaWebhookService(client_id="test-id", client_secret="test-secret")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()

        with patch(
            "app.core.integrations.strava.webhook_service.httpx.AsyncClient"
        ) as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await service.verify_subscription()

        assert result is None


class TestStravaWebhookServiceForceResubscribe:
    """Tests for StravaWebhookService.force_resubscribe."""

    @pytest.mark.asyncio
    async def test_force_resubscribe_deletes_and_creates(self) -> None:
        """force_resubscribe() deletes existing then creates new subscription."""
        service = StravaWebhookService(client_id="test-id", client_secret="test-secret")

        service.unsubscribe = AsyncMock()  # type: ignore[method-assign]
        service.subscribe = AsyncMock(return_value=777)  # type: ignore[method-assign]

        result = await service.force_resubscribe(
            callback_url="https://example.com/webhook",
            verify_token="token",
            existing_subscription_id=123,
        )

        assert result == 777
        service.unsubscribe.assert_called_once_with(123)
        service.subscribe.assert_called_once_with(
            "https://example.com/webhook", "token"
        )

    @pytest.mark.asyncio
    async def test_force_resubscribe_verifies_when_no_id_given(self) -> None:
        """force_resubscribe() calls verify_subscription when no ID provided."""
        service = StravaWebhookService(client_id="test-id", client_secret="test-secret")

        service.verify_subscription = AsyncMock(return_value=456)  # type: ignore[method-assign]
        service.unsubscribe = AsyncMock()  # type: ignore[method-assign]
        service.subscribe = AsyncMock(return_value=789)  # type: ignore[method-assign]

        result = await service.force_resubscribe(
            callback_url="https://example.com/webhook",
            verify_token="token",
        )

        assert result == 789
        service.verify_subscription.assert_called_once()
        service.unsubscribe.assert_called_once_with(456)
