"""
Integration tests for the Snipe-IT webhook endpoint.

Snipe-IT's "General" webhook posts Slack-format messages. Its settings-page
test message is sent without a ``Content-Type`` header, while real
notifications are sent as ``application/json``.
"""

import json
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from uuid import uuid4

import pytest
import pytest_asyncio
from core_shared.stream_client import StreamClient, StreamEvent
from httpx import AsyncClient
from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.integrations.snipeit_webhook_payload import MAX_WEBHOOK_ATTACHMENTS
from app.core.integrations.adapters.sql.snipeit_settings_repository import (
    SqlSnipeItSettingsRepository,
)
from app.core.integrations.models.snipeit import (
    SnipeItSettings,
    generate_webhook_token,
)
from app.infrastructure.config import Settings

WEBHOOK_PATH = "/api/integrations/snipeit/webhook"
WEBHOOK_OWNER_ID = "snipeit-webhook-owner"
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
async def webhook_url(async_connection: AsyncConnection) -> str:
    """
    Configure Snipe-IT for ``WEBHOOK_OWNER_ID`` and return their webhook URL path.

    The owner is not the signed-in test user: Snipe-IT sends no session, so the
    token alone must identify whose asset to sync.
    """
    token = generate_webhook_token()
    await SqlSnipeItSettingsRepository(async_connection).save(
        SnipeItSettings(user_id=WEBHOOK_OWNER_ID, base_url="https://snipe.example"),
        new_webhook_token=token,
    )
    return f"{WEBHOOK_PATH}/{token}"


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
    webhook_url: str,
) -> None:
    """Snipe-IT's header-less test message is acknowledged without publishing."""
    response = await authenticated_client.post(webhook_url, content=TEST_MESSAGE_BODY)

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
    webhook_url: str,
    headers: dict[str, str],
) -> None:
    """An asset notification publishes its asset for the URL's owner, whatever the Content-Type."""
    response = await authenticated_client.post(
        webhook_url,
        content=_notification_body("https://snipe.example/hardware/42"),
        headers=headers,
    )

    assert response.status_code == 200
    events = await read_webhook_events()
    assert [event.event_data for event in events] == [
        {"action": CHECKOUT_TEXT, "item": {"id": 42}, "user_id": WEBHOOK_OWNER_ID}
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
    webhook_url: str,
    title_link: str,
) -> None:
    """A notification linking no parseable asset is acknowledged without publishing."""
    response = await authenticated_client.post(
        webhook_url,
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
    webhook_url: str,
    body: bytes,
) -> None:
    """A body that is not a Snipe-IT notification is rejected with 400."""
    response = await authenticated_client.post(webhook_url, content=body)

    assert response.status_code == 400
    assert await read_webhook_events() == []


ASSET_NOTIFICATION = _notification_body("https://snipe.example/hardware/42")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        pytest.param(ASSET_NOTIFICATION, id="asset-notification"),
        pytest.param(b"not json", id="malformed-body"),
    ],
)
async def test_unknown_token_is_not_found(
    authenticated_client: AsyncClient,
    read_webhook_events: ReadWebhookEvents,
    webhook_url: str,
    body: bytes,
) -> None:
    """A token nobody owns gets 404 before the body is read, so nothing is revealed."""
    unknown_url = f"{WEBHOOK_PATH}/{generate_webhook_token()}"
    assert unknown_url != webhook_url

    response = await authenticated_client.post(unknown_url, content=body)
    no_such_route = await authenticated_client.post(
        "/api/integrations/snipeit/no-such-route", content=body
    )

    assert response.status_code == 404
    assert response.json() == no_such_route.json()
    assert await read_webhook_events() == []


@pytest.mark.asyncio
async def test_url_without_token_is_not_found(
    authenticated_client: AsyncClient,
    read_webhook_events: ReadWebhookEvents,
    webhook_url: str,
) -> None:
    """The old tokenless URL no longer accepts notifications."""
    assert webhook_url.startswith(f"{WEBHOOK_PATH}/")

    response = await authenticated_client.post(WEBHOOK_PATH, content=ASSET_NOTIFICATION)

    assert response.status_code == 404
    assert await read_webhook_events() == []


@pytest.mark.asyncio
async def test_rejected_body_does_not_log_the_token(
    authenticated_client: AsyncClient,
    webhook_url: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A malformed delivery to a valid URL is logged without the secret token."""
    token = webhook_url.rsplit("/", 1)[-1]

    with caplog.at_level(logging.DEBUG):
        response = await authenticated_client.post(webhook_url, content=b"not json")

    assert response.status_code == 400
    # The test client's own httpx request log is not the backend's.
    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name.startswith("app.")
    ]
    assert any("/webhook/{webhook_token}" in message for message in messages)
    assert not any(token in message for message in messages)
