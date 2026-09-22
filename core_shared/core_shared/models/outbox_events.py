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

from pydantic import AwareDatetime, BaseModel, Field

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
    """Payload for ``journal_event.created`` and ``journal_event.updated`` events.

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
            "'relationship_type' keys, and optionally 'status', 'role', "
            "'display_name' and 'is_self'"
        ),
    )
    recurring_event_id: str | None = Field(
        default=None,
        description=(
            "Recurring master event id when the event is an instance of a "
            "recurring series (drives journal series auto-linking)"
        ),
    )
    external_identity: str | None = Field(
        default=None,
        max_length=512,
        description=(
            "Opaque token, built and understood only by the source "
            "integration, that is equal for every copy of the same "
            "real-world event however many calendars hold it. Consumers "
            "compare it for equality and nothing else: two links sharing a "
            "token for one user are the same thing, so they belong to the "
            "same journal. Null when the source has no such identity."
        ),
    )


class JournalStatusEventData(BaseModel):
    """Lightweight payload for ``journal_event.conflicted`` and ``journal_event.cancelled``.

    These events only need identifying fields — they don't carry
    full journal/calendar data.  Using this model instead of the full
    ``JournalSyncEventData`` avoids hard-failing on payloads that
    legitimately omit ``journal_data`` / ``calendar_info_data``.
    """

    external_event_id: str = Field(description="External system's event identifier")
    calendar_id: str = Field(
        description="Internal calendar UUID (or synthetic UUID for non-calendar sources)"
    )
    existing_journal_id: int | None = Field(
        default=None,
        description="ID of existing journal (required for cancellation)",
    )
    recurring_event_id: str | None = Field(
        default=None,
        description=(
            "Recurring master event id when the cancelled instance belongs to a "
            "recurring series (enables far-future instance deletion)"
        ),
    )
    integration_source: str | None = Field(
        default=None,
        description="Source integration (e.g., 'google'); used for provenance",
    )


class JournalSeriesCancelledEventData(BaseModel):
    """Payload for ``journal_event.series_cancelled``.

    Published by a calendar worker when an entire recurring series is
    cancelled/deleted upstream (a single cancelled event carrying the recurring
    master id). The backend fans out over all journals linked to that series:
    far-future unedited instances are deleted, the rest are marked cancelled.
    """

    integration_source: str = Field(description="Source integration (e.g., 'google')")
    calendar_id: str = Field(description="Internal calendar UUID")
    recurring_event_id: str = Field(
        description="The recurring master event id of the cancelled series"
    )
    sync_timestamp: str = Field(
        description="ISO-8601 timestamp of when the sync occurred"
    )


# ── Immich Album Sync ────────────────────────────────────────────────


class ImmichAlbumSyncEventData(BaseModel):
    """Payload for ``immich_album.created`` and ``immich_album.updated`` events.

    Published by the Immich worker when an album is imported as a
    ``PHOTO_ALBUM`` journal. The backend ``ImmichAlbumOutboxEventProcessor``
    creates/updates the journal and records ``sync_metadata`` /
    ``external_references`` links. Unlike calendar journals, albums use
    ``sync_metadata`` (no calendar or external event link).
    """

    integration_source: str = Field(
        default="immich_album",
        description="Always 'immich_album' for album sync events",
    )
    external_id: str = Field(description="Immich album UUID")
    version_hash: str = Field(description="Hash of album metadata for change detection")
    sync_action: str = Field(description="Type of sync action ('created', 'updated')")
    existing_journal_id: int | None = Field(
        default=None,
        description="ID of the existing journal when updating",
    )
    journal_data: dict[str, Any] = Field(
        description=(
            "Journal fields: 'user_id', 'title', 'content', "
            "'event_date_range_start', 'event_date_range_end' (ISO-8601)"
        )
    )
    album_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Album display + sync metadata: 'album_name', 'description', "
            "'asset_count', 'updated_at', 'thumbnail_asset_id', 'album_url', "
            "'shared_link_url' (public share URL, when the album is shared), and "
            "'people' (list of {'id', 'name'} for the unique Immich people tagged "
            "across the album's photos, resolved to journal participants by the "
            "backend)"
        ),
    )
    sync_timestamp: str = Field(
        description="ISO-8601 timestamp of when the sync occurred"
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
    event_date_range_start: AwareDatetime = Field(
        description="Start datetime for date gating"
    )
    event_date_range_end: AwareDatetime = Field(
        description="End datetime for date gating"
    )
    created_at: str = Field(description="ISO-8601 timestamp of event creation")


# ── Union type and dispatcher ────────────────────────────────────────


OutboxEventData = (
    ContactSyncEventData
    | SyncCompletedEventData
    | JournalSyncEventData
    | JournalStatusEventData
    | JournalSeriesCancelledEventData
    | ImmichAlbumSyncEventData
    | MatchDetectionEventData
)
"""Union of all outbox event payload types."""


# Dispatch map for event_type → payload model.
# Entries use either prefix matching (ending with '.') or exact matching.
_EVENT_TYPE_DISPATCH: list[tuple[str, type[BaseModel]]] = [
    ("contact.", ContactSyncEventData),
    ("sync.completed", SyncCompletedEventData),
    ("journal_event.created", JournalSyncEventData),
    ("journal_event.updated", JournalSyncEventData),
    ("journal_event.conflicted", JournalStatusEventData),
    ("journal_event.series_cancelled", JournalSeriesCancelledEventData),
    ("journal_event.cancelled", JournalStatusEventData),
    ("immich_album.", ImmichAlbumSyncEventData),
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
