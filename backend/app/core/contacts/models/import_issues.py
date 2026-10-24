"""What an integration import left out of a contact, for the user to review."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

# A skipped address; the only kind so far (#1820).
SKIPPED_ADDRESS: Literal["skipped_address"] = "skipped_address"


@dataclass(frozen=True)
class ContactImportIssue:
    """One thing an import skipped: ``payload`` is what it left out."""

    id: int
    contact_id: int
    contact_name: str
    integration_source: str
    kind: str
    reason: str
    payload: dict[str, Any]
    status: str
    created_at: datetime
