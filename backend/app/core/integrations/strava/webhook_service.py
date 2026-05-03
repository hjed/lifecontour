"""
Strava Webhook Service.

Manages Strava push subscription lifecycle: creation, verification,
deletion, and forced resubscription. Communicates with Strava's
``/api/v3/push_subscriptions`` API.
"""

from __future__ import annotations

import httpx
import structlog

logger = structlog.get_logger()

# Strava Push Subscription API endpoint
STRAVA_PUSH_SUBSCRIPTIONS_URL = "https://www.strava.com/api/v3/push_subscriptions"


class StravaWebhookError(Exception):
    """Raised when a Strava webhook operation fails."""


class StravaWebhookService:
    """
    Service for managing Strava push subscriptions (webhooks).

    Handles subscription creation (with verify_token handshake),
    deletion, status verification, and forced resubscription.
    Uses ``httpx`` for HTTP requests to the Strava API.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
    ) -> None:
        """
        Initialize the Strava webhook service.

        Args:
            client_id: Strava OAuth application client ID.
            client_secret: Strava OAuth application client secret.
        """
        self._client_id = client_id
        self._client_secret = client_secret

    async def subscribe(
        self,
        callback_url: str,
        verify_token: str,
    ) -> int:
        """
        Create a new Strava push subscription.

        Sends a POST to Strava's push_subscriptions API. Strava will
        immediately validate the callback by sending a GET with the
        ``hub.verify_token`` — the webhook endpoint must echo the
        ``hub.challenge`` for the subscription to succeed.

        Args:
            callback_url: Public HTTPS URL for webhook callbacks.
            verify_token: Shared secret for handshake validation.

        Returns:
            The Strava subscription ID (int).

        Raises:
            StravaWebhookError: If subscription creation fails.
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    STRAVA_PUSH_SUBSCRIPTIONS_URL,
                    data={
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "callback_url": callback_url,
                        "verify_token": verify_token,
                    },
                )
                response.raise_for_status()
                data = response.json()

            subscription_id = data.get("id")
            if subscription_id is None:
                raise StravaWebhookError(
                    "Strava subscription response missing 'id' field"
                )

            logger.info(
                "Strava webhook subscription created",
                subscription_id=subscription_id,
                callback_url=callback_url,
            )
            return int(subscription_id)

        except httpx.HTTPStatusError as e:
            logger.error(
                "Strava webhook subscription failed",
                status_code=e.response.status_code,
                response_body=e.response.text,
                exc_info=True,
            )
            raise StravaWebhookError(
                f"Strava subscription failed with status {e.response.status_code}: "
                f"{e.response.text}"
            ) from e
        except StravaWebhookError:
            raise
        except Exception as e:
            logger.error(
                "Unexpected error creating Strava webhook subscription",
                error=str(e),
                exc_info=True,
            )
            raise StravaWebhookError(
                f"Failed to create Strava webhook subscription: {e!s}"
            ) from e

    async def unsubscribe(self, subscription_id: int) -> None:
        """
        Delete an existing Strava push subscription.

        Args:
            subscription_id: The subscription ID to delete.

        Raises:
            StravaWebhookError: If deletion fails.
        """
        try:
            url = f"{STRAVA_PUSH_SUBSCRIPTIONS_URL}/{subscription_id}"
            async with httpx.AsyncClient() as client:
                response = await client.delete(
                    url,
                    params={
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                    },
                )
                response.raise_for_status()

            logger.info(
                "Strava webhook subscription deleted",
                subscription_id=subscription_id,
            )

        except httpx.HTTPStatusError as e:
            logger.error(
                "Strava webhook unsubscribe failed",
                subscription_id=subscription_id,
                status_code=e.response.status_code,
                exc_info=True,
            )
            raise StravaWebhookError(
                f"Failed to delete Strava subscription {subscription_id}: "
                f"HTTP {e.response.status_code}"
            ) from e
        except Exception as e:
            logger.error(
                "Unexpected error deleting Strava webhook subscription",
                subscription_id=subscription_id,
                error=str(e),
                exc_info=True,
            )
            raise StravaWebhookError(
                f"Failed to delete Strava subscription: {e!s}"
            ) from e

    async def verify_subscription(self) -> int | None:
        """
        Verify that a push subscription currently exists for this application.

        Calls GET /push_subscriptions to check if a subscription is active.

        Returns:
            The subscription ID if one exists, or None.

        Raises:
            StravaWebhookError: If the verification request fails.
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    STRAVA_PUSH_SUBSCRIPTIONS_URL,
                    params={
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                    },
                )
                response.raise_for_status()
                data = response.json()

            # Strava returns a list of subscriptions (max 1 per app)
            if isinstance(data, list) and len(data) > 0:
                subscription_id = data[0].get("id")
                logger.info(
                    "Strava webhook subscription verified",
                    subscription_id=subscription_id,
                )
                return int(subscription_id) if subscription_id is not None else None

            logger.info("No active Strava webhook subscription found")
            return None

        except httpx.HTTPStatusError as e:
            logger.error(
                "Strava subscription verification failed",
                status_code=e.response.status_code,
                exc_info=True,
            )
            raise StravaWebhookError(
                f"Failed to verify Strava subscription: HTTP {e.response.status_code}"
            ) from e
        except Exception as e:
            logger.error(
                "Unexpected error verifying Strava subscription",
                error=str(e),
                exc_info=True,
            )
            raise StravaWebhookError(
                f"Failed to verify Strava subscription: {e!s}"
            ) from e

    async def force_resubscribe(
        self,
        callback_url: str,
        verify_token: str,
        existing_subscription_id: int | None = None,
    ) -> int:
        """
        Delete existing subscription (if any) and create a new one.

        Args:
            callback_url: Public HTTPS URL for webhook callbacks.
            verify_token: Shared secret for handshake validation.
            existing_subscription_id: Known subscription ID to delete first.
                If None, verifies current subscription before deleting.

        Returns:
            The new subscription ID.

        Raises:
            StravaWebhookError: If resubscription fails.
        """
        # Determine subscription to delete
        sub_id = existing_subscription_id
        if sub_id is None:
            sub_id = await self.verify_subscription()

        # Delete existing subscription if found
        if sub_id is not None:
            try:
                await self.unsubscribe(sub_id)
            except StravaWebhookError:
                logger.warning(
                    "Failed to delete existing subscription during resubscribe, "
                    "proceeding with creation",
                    subscription_id=sub_id,
                )

        # Create new subscription
        new_id = await self.subscribe(callback_url, verify_token)

        logger.info(
            "Strava webhook force-resubscribed",
            old_subscription_id=sub_id,
            new_subscription_id=new_id,
        )
        return new_id
