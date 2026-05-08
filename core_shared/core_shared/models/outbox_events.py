"""
Typed Pydantic models for outbox event payloads.

Each ``event_type`` value has its own model representing the full
``event_data`` JSON payload shape.  These models are used by both
publishers (via ``model_dump()``) and consumers (via ``model_validate()``)
to enforce a well-defined contract at the boundary.

The models live in ``core_shared`` so they are available to both the
backend and integration workers.
"""

from typing import Any

from pydantic import BaseModel, Field

# ── Contact Sync ──────────────────────────────────────────────────────


class ContactSyncEventData(BaseModel):
    """Payload for ``contact.created`` and ``contact.updated`` events.

    Published by integration workers (e.g. Google) when a contact is
    synced from an external system.
    """

    integration_source: str = Field(
        description="Source integration (e.g. 'google', 'strava')"
    )
    external_id: str = Field(description="External system's contact identifier")
    contact_data: dict[str, Any] = Field(
        description="Contact data in the system's canonical format"
    )
    sync_timestamp: str = Field(
        description="ISO-8601 timestamp of when the sync occurred"
    )
    sync_type: str = Field(
        description="Type of sync operation ('created', 'updated', 'deleted')"
    )
    etag: str | None = Field(
        default=None,
        description="External system's version identifier (e.g. Google ETag)",
    )


# ── Sync Completed ───────────────────────────────────────────────────


class SyncCompletedEventData(BaseModel):
    """Payload for ``sync.completed`` events.

    Published by integration workers when a full sync cycle completes.
    """

    integration_source: str = Field(description="Source integration (e.g. 'google')")
    google_account_email: str = Field(description="Google account that was synced")
    metrics: dict[str, Any] = Field(description="Sync metrics and result counts")
    completed_at: str = Field(description="ISO-8601 timestamp of sync completion")


# ── Journal Sync ─────────────────────────────────────────────────────


class JournalSyncEventData(BaseModel):
    """Payload for ``journal_event.*`` events (created/updated/conflicted/cancelled).

    Published by integration workers (Google Calendar, Strava) when a
    journal-relevant external event is synced.
    """

    integration_source: str = Field(
        description="Source integration (e.g. 'google', 'strava')"
    )
    external_event_id: str = Field(description="External system's event identifier")
    calendar_id: str = Field(
        description="Internal calendar UUID (or synthetic UUID for non-calendar sources)"
    )
    journal_data: dict[str, Any] = Field(
        description="Journal data transformed from external event"
    )
    calendar_info_data: dict[str, Any] = Field(
        description="Calendar info (times, location, etc.)"
    )
    sync_timestamp: str = Field(
        description="ISO-8601 timestamp of when the sync occurred"
    )
    sync_action: str = Field(
        description="Type of sync action ('created', 'updated', 'conflicted', 'cancelled')"
    )
    etag: str | None = Field(
        default=None,
        description="External system's version identifier",
    )
    existing_journal_id: int | None = Field(
        default=None,
        description="ID of existing journal if updating",
    )
    contact_relationships: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "List of contact relationship dicts with 'email' and "
            "'relationship_type' keys"
        ),
    )


# ── Match Detection ──────────────────────────────────────────────────


class MatchDetectionEventData(BaseModel):
    """Payload for ``journal_review.detect_matches`` events.

    Published by ``JournalOutboxEventProcessor`` as a Phase 2 event
    after journal creation to trigger AI-assisted match detection.
    """

    journal_id: int = Field(description="ID of the newly created journal")
    user_id: str = Field(description="User who owns the journal")
    journal_title: str = Field(description="Title for similarity comparison")
    journal_content: str = Field(
        default="",
        description="Content for similarity comparison",
    )
    event_date_range_start: str = Field(
        description="ISO-8601 start datetime for date gating"
    )
    event_date_range_end: str = Field(
        description="ISO-8601 end datetime for date gating"
    )
    created_at: str = Field(description="ISO-8601 timestamp of event creation")


# ── Union type and dispatcher ────────────────────────────────────────


OutboxEventData = (
    ContactSyncEventData
    | SyncCompletedEventData
    | JournalSyncEventData
    | MatchDetectionEventData
)
"""Union of all outbox event payload types."""


# Prefix-based dispatch map for event_type → payload model.
# Prefix matches are checked in order; first match wins.
_EVENT_TYPE_DISPATCH: list[tuple[str, type[BaseModel]]] = [
    ("contact.", ContactSyncEventData),
    ("sync.completed", SyncCompletedEventData),
    ("journal_event.", JournalSyncEventData),
    ("journal_review.", MatchDetectionEventData),
]


def parse_outbox_event_data(
    event_type: str,
    event_data: dict[str, Any],
) -> OutboxEventData:
    """Parse raw ``event_data`` dict into the typed Pydantic model.

    Uses prefix matching on ``event_type`` to select the correct model,
    then validates the payload.

    Args:
        event_type: The outbox event type string (e.g. ``'contact.created'``).
        event_data: The raw JSON dict from the outbox event.

    Returns:
        A validated Pydantic model instance.

    Raises:
        ValueError: If ``event_type`` doesn't match any known pattern.
        pydantic.ValidationError: If the payload doesn't match the model.
    """
    for prefix, model_class in _EVENT_TYPE_DISPATCH:
        if event_type.startswith(prefix) or event_type == prefix:
            return model_class.model_validate(event_data)  # type: ignore[return-value]

    raise ValueError(f"Unknown event type: {event_type}")
