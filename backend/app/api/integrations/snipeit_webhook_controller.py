"""
Snipe-IT Webhook API controller.

Provides an inbound webhook endpoint for receiving events from a Snipe-IT instance.
Events are published to the Redis Stream for asynchronous processing by the Snipe-IT worker.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import structlog
from core_shared.stream_client import StreamClient
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Response
from pydantic import BaseModel

from app.infrastructure.config import Settings

logger = structlog.get_logger()

router = APIRouter(prefix="/integrations/snipeit", tags=["integrations-snipeit"])


class SnipeItWebhookPayload(BaseModel):
    """
    Validation model for inbound Snipe-IT webhooks.
    Accepts arbitrary payload structure while ensuring it is valid JSON
    with at least some expected fields.
    """

    action: str | None = None
    item: dict[str, Any] | None = None

    model_config = {"extra": "allow"}


@router.post(
    "/webhook",
    include_in_schema=False,
    status_code=200,
)
@inject
async def snipeit_webhook_event(
    payload: SnipeItWebhookPayload,
    stream_client: FromDishka[StreamClient],
    settings: FromDishka[Settings],
) -> Response:
    """
    Receive Snipe-IT webhook events.

    Snipe-IT sends POST requests when assets or maintenance records are created/updated.
    The endpoint responds with HTTP 200 immediately. Events are placed directly onto
    the domain events Redis stream for processing by the Snipe-IT worker.
    """
    try:
        event_id = str(uuid4())
        await stream_client.publish(
            stream_name=settings.stream_name,
            event_id=event_id,
            event_type="snipeit.webhook_received",
            aggregate_id=0,
            event_data=payload.model_dump(),
            occurred_at=datetime.now(UTC).isoformat(),
        )
        logger.info(
            "Published Snipe-IT webhook event to stream",
            event_id=event_id,
            stream=settings.stream_name,
        )
    except Exception:
        logger.error(
            "Failed to publish Snipe-IT webhook event to stream", exc_info=True
        )
        return Response(status_code=500)

    return Response(status_code=200)
