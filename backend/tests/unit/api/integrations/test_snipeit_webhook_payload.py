"""Unit tests for translating Snipe-IT webhook notifications into stream events.

Snipe-IT's "General" webhook posts Slack-format messages. Asset notifications
link the asset in ``attachments[].title_link`` (``<base>/hardware/<id>``); the
test message has no attachments at all.
"""

from typing import Any

import pytest
from pydantic import ValidationError

from app.api.integrations.snipeit_webhook_payload import (
    MAX_WEBHOOK_ATTACHMENTS,
    SnipeItSlackWebhookPayload,
    SnipeItWebhookEvent,
    extract_webhook_events,
)

CHECKOUT_TEXT = ":arrow_up: :computer: Asset Checkout Notification"


def _notification(*title_links: str | None) -> SnipeItSlackWebhookPayload:
    """Build a Snipe-IT Slack-format notification with one attachment per link."""
    return SnipeItSlackWebhookPayload.model_validate(
        {
            "text": CHECKOUT_TEXT,
            "username": "journal",
            "channel": "#NA",
            "attachments": [
                {
                    "title": "Tent",
                    "title_link": link,
                    "fields": [{"title": "To", "value": "Me", "short": True}],
                }
                for link in title_links
            ],
        }
    )


def _asset_ids(payload: SnipeItSlackWebhookPayload) -> list[int]:
    """Return the asset ids of the events extracted from ``payload``."""
    return [event.asset_id for event in extract_webhook_events(payload)]


def test_test_message_produces_no_events() -> None:
    """The settings-page test message links no asset, so nothing is published."""
    payload = SnipeItSlackWebhookPayload.model_validate(
        {
            "channel": "#NA",
            "text": "Oh hai! It looks like your General Webhook integration "
            "with Snipe-IT is working!",
            "username": "journal",
            "icon_emoji": ":heart:",
        }
    )

    assert extract_webhook_events(payload) == []


def test_asset_notification_produces_event_for_linked_asset() -> None:
    """An asset link becomes one event carrying the message text as the action."""
    payload = _notification("https://snipe.example/hardware/42")

    assert extract_webhook_events(payload) == [
        SnipeItWebhookEvent(action=CHECKOUT_TEXT, asset_id=42)
    ]


def test_event_data_matches_worker_contract() -> None:
    """Event data has the ``{action, item: {id}}`` shape the worker reads."""
    event = SnipeItWebhookEvent(action=CHECKOUT_TEXT, asset_id=42)

    expected: dict[str, Any] = {"action": CHECKOUT_TEXT, "item": {"id": 42}}
    assert event.to_event_data() == expected


def test_asset_id_extracted_from_subdirectory_install_with_trailing_slash() -> None:
    """Snipe-IT served under a path prefix still yields the asset id."""
    payload = _notification("https://host.example/snipe/hardware/12/")

    assert _asset_ids(payload) == [12]


def test_query_string_and_fragment_are_ignored() -> None:
    """Only the URL path is matched."""
    payload = _notification("https://snipe.example/hardware/12?tab=history#notes")

    assert _asset_ids(payload) == [12]


def test_non_asset_links_produce_no_events() -> None:
    """Accessory, license, component and asset sub-page links are ignored."""
    payload = _notification(
        "https://snipe.example/accessories/5",
        "https://snipe.example/licenses/7",
        "https://snipe.example/components/9",
        "https://snipe.example/hardware/12/checkout",
    )

    assert extract_webhook_events(payload) == []


def test_invalid_asset_ids_produce_no_events() -> None:
    """Zero, oversized and non-ASCII-digit ids are not Snipe-IT asset ids."""
    payload = _notification(
        "https://snipe.example/hardware/0",
        "https://snipe.example/hardware/" + "9" * 5000,
        "https://snipe.example/hardware/٤٢",
    )

    assert extract_webhook_events(payload) == []


def test_attachment_without_link_produces_no_events() -> None:
    """An attachment with no ``title_link`` is ignored."""
    assert extract_webhook_events(_notification(None)) == []


def test_empty_attachments_produce_no_events() -> None:
    """A notification with no attachments publishes nothing."""
    assert extract_webhook_events(_notification()) == []


def test_distinct_assets_produce_one_event_each_in_order() -> None:
    """Each distinct asset gets its own event, in attachment order."""
    payload = _notification(
        "https://snipe.example/hardware/7",
        "https://snipe.example/hardware/3",
    )

    assert _asset_ids(payload) == [7, 3]


def test_repeated_asset_links_produce_one_event() -> None:
    """Links to the same asset are de-duplicated."""
    payload = _notification(
        "https://snipe.example/hardware/42",
        "https://snipe.example/hardware/42/",
    )

    assert extract_webhook_events(payload) == [
        SnipeItWebhookEvent(action=CHECKOUT_TEXT, asset_id=42)
    ]


def test_attachments_up_to_limit_are_accepted() -> None:
    """A notification at the attachment cap still yields one event per asset."""
    links = [
        f"https://snipe.example/hardware/{asset_id}"
        for asset_id in range(1, MAX_WEBHOOK_ATTACHMENTS + 1)
    ]

    assert len(_asset_ids(_notification(*links))) == MAX_WEBHOOK_ATTACHMENTS


def test_attachments_over_limit_are_rejected() -> None:
    """More attachments than Snipe-IT ever sends fails validation."""
    links = [
        f"https://snipe.example/hardware/{asset_id}"
        for asset_id in range(1, MAX_WEBHOOK_ATTACHMENTS + 2)
    ]

    with pytest.raises(ValidationError):
        _notification(*links)


def test_missing_text_defaults_to_empty_action() -> None:
    """A notification without ``text`` still publishes, with an empty action."""
    payload = SnipeItSlackWebhookPayload.model_validate(
        {"attachments": [{"title_link": "https://snipe.example/hardware/3"}]}
    )

    assert extract_webhook_events(payload) == [
        SnipeItWebhookEvent(action="", asset_id=3)
    ]
