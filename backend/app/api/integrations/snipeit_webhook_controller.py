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

from app.api.integrations.snipeit_webhook_payload import (
    SnipeItSlackWebhookPayload,
    extract_webhook_events,
)
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
    "/webhook",
    include_in_schema=False,
    status_code=200,
)
@inject
async def snipeit_webhook_event(
    request: Request,
    stream_client: FromDishka[StreamClient],
    settings: FromDishka[Settings],
) -> Response:
    """
    Receive Snipe-IT webhook notifications.

    Snipe-IT's "General" webhook posts a Slack-format message on asset checkout,
    checkin, acceptance and audit. Each linked asset is published to the domain
    events Redis stream for the Snipe-IT worker to sync; messages that link no
    asset (the settings-page test message, accessories, licenses, ...) are
    acknowledged without publishing.

    This endpoint is unauthenticated — Snipe-IT calls it directly.
    """
    payload = await _parse_payload(request)
    events = extract_webhook_events(payload)
    if not events:
        logger.info(
            "Ignoring Snipe-IT webhook without an asset link",
            reason="no_asset_link",
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
                event_data=event.to_event_data(),
                occurred_at=datetime.now(UTC).isoformat(),
            )
            logger.info(
                "Published Snipe-IT webhook event to stream",
                event_id=event_id,
                asset_id=event.asset_id,
                stream=settings.stream_name,
            )
    except Exception:
        logger.error(
            "Failed to publish Snipe-IT webhook event to stream", exc_info=True
        )
        return Response(status_code=500)

    return Response(status_code=200)
