import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import NewType

SnipeItWebhookToken = NewType("SnipeItWebhookToken", str)
"""Secret in a user's Snipe-IT webhook URL that identifies them as its owner."""


def generate_webhook_token() -> SnipeItWebhookToken:
    """Generate a new random, URL-safe Snipe-IT webhook token."""
    return SnipeItWebhookToken(secrets.token_urlsafe(32))


@dataclass
class SnipeItSettings:
    """Domain model for Snipe-IT integration settings."""

    user_id: str
    base_url: str
    snipeit_user_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
