"""
Snipe-IT Webhook API controller.

Provides an inbound webhook endpoint for receiving events from a Snipe-IT instance.
Events are published to the Redis Stream for asynchronous processing by the Snipe-IT worker.
"""

import json
from datetime import UTC, datetime
from uuid import uuid4

import structlog
from core_shared.stream_client import StreamClient
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.integrations.snipeit_webhook_payload import (
    SnipeItSlackWebhookPayload,
    extract_webhook_events,
)
from app.core.integrations.adapters.sql.snipeit_settings_repository import (
    SqlSnipeItSettingsRepository,
)
from app.core.integrations.models.snipeit import SnipeItWebhookToken
from app.infrastructure.config import Settings

logger = structlog.get_logger()

router = APIRouter(prefix="/integrations/snipeit", tags=["integrations-snipeit"])


async def _parse_payload(request: Request) -> SnipeItSlackWebhookPayload:
    """
    Parse the request body as a Snipe-IT notification, ignoring ``Content-Type``.

    Snipe-IT's settings-page test message is sent without a ``Content-Type``
    header, so FastAPI's body parsing would hand over raw bytes.
    """
    try:
        return SnipeItSlackWebhookPayload.model_validate(
            json.loads(await request.body())
        )
    except (ValueError, ValidationError) as exc:
        raise HTTPException(
            status_code=400, detail="Invalid Snipe-IT webhook payload"
        ) from exc


@router.post(
    "/webhook/{webhook_token}",
    include_in_schema=False,
    status_code=200,
)
@inject
async def snipeit_webhook_event(
    webhook_token: str,
    request: Request,
    stream_client: FromDishka[StreamClient],
    settings: FromDishka[Settings],
    settings_repository: FromDishka[SqlSnipeItSettingsRepository],
) -> Response:
    """
    Receive Snipe-IT webhook notifications.

    Snipe-IT's "General" webhook posts a Slack-format message on asset checkout,
    checkin, acceptance and audit. Each linked asset is published to the domain
    events Redis stream for the Snipe-IT worker to sync; messages that link no
    asset (the settings-page test message, accessories, licenses, ...) are
    acknowledged without publishing.

    Snipe-IT webhooks carry no signature, so the secret token in the URL is the
    authentication: it identifies the user whose Snipe-IT the asset is synced
    from. An unknown token gets 404 before the body is read, so the endpoint's
    existence is not revealed.
    """
    user_id = await settings_repository.get_user_id_by_webhook_token(
        SnipeItWebhookToken(webhook_token)
    )
    if user_id is None:
        # Starlette's exception, not FastAPI's: it is what routing raises for a
        # path that does not exist, so the response is indistinguishable.
        raise StarletteHTTPException(status_code=404)

    payload = await _parse_payload(request)
    events = extract_webhook_events(payload)
    if not events:
        logger.info(
            "Ignoring Snipe-IT webhook without an asset link",
            reason="no_asset_link",
            user_id=user_id,
            attachment_count=len(payload.attachments),
        )
        return Response(status_code=200)

    # A failure part-way leaves earlier events published; a retried delivery
    # only re-syncs those assets, which is idempotent.
    try:
        for event in events:
            event_id = str(uuid4())
            await stream_client.publish(
                stream_name=settings.stream_name,
                event_id=event_id,
                event_type="snipeit.webhook_received",
                aggregate_id=0,
                event_data=event.to_event_data(user_id),
                occurred_at=datetime.now(UTC).isoformat(),
            )
            logger.info(
                "Published Snipe-IT webhook event to stream",
                event_id=event_id,
                asset_id=event.asset_id,
                user_id=user_id,
                stream=settings.stream_name,
            )
    except Exception:
        logger.error(
            "Failed to publish Snipe-IT webhook event to stream", exc_info=True
        )
        return Response(status_code=500)

    return Response(status_code=200)
