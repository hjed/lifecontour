from dataclasses import dataclass
from datetime import datetime


@dataclass
class SnipeItSettings:
    """Domain model for Snipe-IT integration settings."""

    user_id: str
    base_url: str
    snipeit_user_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
