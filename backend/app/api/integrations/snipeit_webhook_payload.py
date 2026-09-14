"""
Snipe-IT webhook payload translation.

Snipe-IT's "General" webhook posts Slack-format messages rather than a
structured event: ``{text, username, channel, attachments[]}``. Notifications
about an asset link it in ``attachments[].title_link`` as
``<base>/hardware/<id>``; the settings-page test message has no attachments.

This module turns those messages into the ``snipeit.webhook_received`` event
data the Snipe-IT worker consumes: ``{"action": str, "item": {"id": int}}``.
"""

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict

# Snipe-IT asset ids are positive database ids; the length cap keeps a hostile
# link from reaching int()'s digit limit.
_ASSET_PATH = re.compile(r"/hardware/([1-9][0-9]{0,17})/?$")


class SnipeItSlackAttachment(BaseModel):
    """One Slack attachment in a Snipe-IT notification."""

    model_config = ConfigDict(extra="ignore")

    title_link: str | None = None


class SnipeItSlackWebhookPayload(BaseModel):
    """A Snipe-IT webhook notification in Slack message format."""

    model_config = ConfigDict(extra="ignore")

    text: str = ""
    attachments: list[SnipeItSlackAttachment] = []


@dataclass(frozen=True)
class SnipeItWebhookEvent:
    """An asset change reported by Snipe-IT, ready to publish to the stream."""

    action: str
    asset_id: int

    def to_event_data(self) -> dict[str, Any]:
        """Serialise into the event data read by the Snipe-IT worker."""
        return {"action": self.action, "item": {"id": self.asset_id}}


def _asset_id_from_link(link: str | None) -> int | None:
    """Return the asset id from a Snipe-IT ``/hardware/<id>`` URL, if it is one."""
    if not link:
        return None
    match = _ASSET_PATH.search(urlparse(link).path)
    return int(match.group(1)) if match else None


def extract_webhook_events(
    payload: SnipeItSlackWebhookPayload,
) -> list[SnipeItWebhookEvent]:
    """
    Return one event per distinct asset linked by the notification.

    Messages without an asset link (the test message, or notifications about
    accessories, licenses, components and consumables) yield no events.
    """
    asset_ids = dict.fromkeys(
        asset_id
        for attachment in payload.attachments
        if (asset_id := _asset_id_from_link(attachment.title_link)) is not None
    )
    return [
        SnipeItWebhookEvent(action=payload.text, asset_id=asset_id)
        for asset_id in asset_ids
    ]
