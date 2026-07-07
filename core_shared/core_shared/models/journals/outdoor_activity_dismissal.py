"""Domain model for outdoor-activity review dismissals.

A dismissal records that a user has removed an outdoor activity journal from the
incomplete-activities review. It is journal-scoped and reversible, and is stored
separately from the merge ``journal_review_items`` queue (a different concept).
The presence of a dismissal excludes the journal from the review regardless of
which incompleteness rules it matches.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core_shared.models.history import Provenance


@dataclass
class OutdoorActivityDismissal:
    """A user's dismissal of an outdoor activity journal from the review.

    ``provenance`` records where the dismissal came from (the web UI, an AI agent
    via MCP, etc.), following the shared activity-history provenance convention.
    """

    journal_id: int
    user_id: str
    provenance: Provenance
    created_at: datetime | None = None
    updated_at: datetime | None = None
