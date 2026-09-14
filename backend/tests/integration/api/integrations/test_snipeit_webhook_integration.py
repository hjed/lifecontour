"""
Integration tests for the Snipe-IT webhook endpoint.

Snipe-IT's "General" webhook posts Slack-format messages. Its settings-page
test message is sent without a ``Content-Type`` header, while real
notifications are sent as ``application/json``.
"""

import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from uuid import uuid4

import pytest
import pytest_asyncio
from core_shared.stream_client import StreamClient, StreamEvent
from httpx import AsyncClient
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from app.api.integrations.snipeit_webhook_payload import MAX_WEBHOOK_ATTACHMENTS
from app.infrastructure.config import Settings

WEBHOOK_URL = "/api/integrations/snipeit/webhook"
WEBHOOK_EVENT_TYPE = "snipeit.webhook_received"
CHECKOUT_TEXT = ":arrow_up: :computer: Asset Checkout Notification"

# The body Snipe-IT v8.3.1 sends from "Test Webhook", verbatim from the logs.
TEST_MESSAGE_BODY = (
    b'{"channel":"#NA","text":"Oh hai! It looks like your General Webhook '
    b'integration with Snipe-IT is working!","username":"journal",'
    b'"icon_emoji":":heart:"}'
)

ReadWebhookEvents = Callable[[], Awaitable[list[StreamEvent]]]


def _notification_body(title_link: str) -> bytes:
    """Build a Snipe-IT Slack-format checkout notification."""
    return json.dumps(
        {
            "text": CHECKOUT_TEXT,
            "username": "journal",
            "channel": "#NA",
            "attachments": [
                {
                    "title": "Tent",
                    "title_link": title_link,
                    "fields": [
                        {"title": "Checked out to", "value": "Me", "short": True}
                    ],
                    "text": "",
                }
            ],
        }
    ).encode()


@pytest_asyncio.fixture
async def read_webhook_events(
    test_settings: Settings,
) -> AsyncGenerator[ReadWebhookEvents]:
    """
    Read the webhook events published after this fixture was set up.

    The consumer group starts at ``$`` so events published by earlier tests are
    never replayed, which keeps "nothing published" assertions meaningful.
    """
    redis_client = Redis.from_url(test_settings.redis_url, decode_responses=False)
    stream_client = StreamClient(redis_client)
    group_name = f"test-group-{uuid4()}"
    await stream_client.ensure_consumer_group(
        test_settings.stream_name, group_name, start_id="$"
    )

    async def read() -> list[StreamEvent]:
        events = await stream_client.read_events(
            stream_name=test_settings.stream_name,
            group_name=group_name,
            consumer_name="test-consumer",
            count=100,
            block_ms=100,
        )
        return [event for event in events if event.event_type == WEBHOOK_EVENT_TYPE]

    try:
        yield read
    finally:
        try:
            await redis_client.xgroup_destroy(test_settings.stream_name, group_name)
        except ResponseError:
            pass
        await redis_client.aclose()


@pytest.mark.asyncio
async def test_test_message_without_content_type_is_accepted(
    authenticated_client: AsyncClient,
    read_webhook_events: ReadWebhookEvents,
) -> None:
    """Snipe-IT's header-less test message is acknowledged without publishing."""
    response = await authenticated_client.post(WEBHOOK_URL, content=TEST_MESSAGE_BODY)

    assert response.status_code == 200
    assert await read_webhook_events() == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({"Content-Type": "application/json"}, id="application-json"),
        pytest.param({}, id="no-content-type"),
        pytest.param({"Content-Type": "text/plain"}, id="text-plain"),
    ],
)
async def test_asset_notification_publishes_asset_event(
    authenticated_client: AsyncClient,
    read_webhook_events: ReadWebhookEvents,
    headers: dict[str, str],
) -> None:
    """An asset notification publishes its asset whatever the Content-Type."""
    response = await authenticated_client.post(
        WEBHOOK_URL,
        content=_notification_body("https://snipe.example/hardware/42"),
        headers=headers,
    )

    assert response.status_code == 200
    events = await read_webhook_events()
    assert [event.event_data for event in events] == [
        {"action": CHECKOUT_TEXT, "item": {"id": 42}}
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "title_link",
    [
        pytest.param("https://snipe.example/accessories/5", id="accessory"),
        pytest.param("http://[/hardware/5", id="unparseable-link"),
    ],
)
async def test_non_asset_notification_publishes_nothing(
    authenticated_client: AsyncClient,
    read_webhook_events: ReadWebhookEvents,
    title_link: str,
) -> None:
    """A notification linking no parseable asset is acknowledged without publishing."""
    response = await authenticated_client.post(
        WEBHOOK_URL,
        content=_notification_body(title_link),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert await read_webhook_events() == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b"not json", id="invalid-json"),
        pytest.param(b"[1, 2]", id="json-array"),
        pytest.param(b'{"attachments": "nope"}', id="invalid-attachments"),
        pytest.param(
            json.dumps(
                {
                    "text": CHECKOUT_TEXT,
                    "attachments": [
                        {"title_link": f"https://snipe.example/hardware/{asset_id}"}
                        for asset_id in range(1, MAX_WEBHOOK_ATTACHMENTS + 2)
                    ],
                }
            ).encode(),
            id="too-many-attachments",
        ),
    ],
)
async def test_malformed_body_is_rejected(
    authenticated_client: AsyncClient,
    read_webhook_events: ReadWebhookEvents,
    body: bytes,
) -> None:
    """A body that is not a Snipe-IT notification is rejected with 400."""
    response = await authenticated_client.post(WEBHOOK_URL, content=body)

    assert response.status_code == 400
    assert await read_webhook_events() == []
