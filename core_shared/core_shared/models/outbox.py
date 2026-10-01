"""
Outbox Event model for transactional outbox pattern.

This model enables reliable event publishing by storing events in the same
database transaction as the business data changes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Column, DateTime, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB

from .base import Base
from .outbox_events import (
    ContactSyncEventData,
    ImmichAlbumSyncEventData,
    JournalSeriesCancelledEventData,
    JournalSyncEventData,
    MatchDetectionEventData,
    SyncCompletedEventData,
)


class OutboxEvent(Base):
    """
    Outbox event for transactional outbox pattern.

    Events are stored in the same transaction as business data changes,
    then processed asynchronously by a separate event publisher.
    """

    __tablename__ = "outbox_events"

    id = Column(Integer, primary_key=True, autoincrement=True, nullable=False)

    event_id = Column(
        String(255),
        nullable=False,
        unique=True,
        default=lambda: str(uuid4()),
        comment="Unique identifier for the event",
    )

    event_type = Column(
        String(100),
        nullable=False,
        comment="Type of event (e.g., 'contact.created', 'sync.completed')",
    )

    aggregate_id = Column(
        Integer,
        nullable=False,
        default=0,
        comment="ID of the entity that changed",
    )

    event_data = Column(
        JSONB, nullable=False, comment="JSON payload with event details"
    )

    occurred_at = Column(
        DateTime(timezone=True),
        server_default=text("now()"),
        default=lambda: datetime.now(UTC),
        nullable=False,
        comment="When the event occurred",
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=text("now()"),
        default=lambda: datetime.now(UTC),
        nullable=False,
        comment="When the event was created",
    )

    relayed_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the event was published to the Redis Stream by the OutboxRelay",
    )

    retry_count = Column(
        Integer,
        server_default=text("0"),
        default=0,
        nullable=False,
        comment="Number of processing attempts",
    )

    def __repr__(self) -> str:
        """String representation of the outbox event."""
        return (
            f"<OutboxEvent(id={self.id}, event_type='{self.event_type}', "
            f"aggregate_id={self.aggregate_id}, relayed_at={self.relayed_at})>"
        )

    @classmethod
    def create_contact_sync_event(
        cls,
        contact_data: dict[str, Any],
        integration_source: str,
        external_id: str,
        sync_type: str = "created",
        etag: str | None = None,
        user_id: str | None = None,
    ) -> OutboxEvent:
        """
        Create an outbox event for contact synchronization.

        Args:
            contact_data: Contact data from external system in our Contacts format
            integration_source: Source integration (e.g., 'google')
            external_id: External system's contact ID
            sync_type: Type of sync operation ('created', 'updated', 'deleted')
            etag: External system's version identifier (e.g., Google ETag)
            user_id: Owner of the synced contact (the integration's user)

        Returns:
            OutboxEvent instance ready to be saved

        Raises:
            pydantic.ValidationError: If the payload is invalid
        """
        payload = ContactSyncEventData(
            integration_source=integration_source,
            external_id=external_id,
            contact_data=contact_data,
            sync_timestamp=datetime.now(UTC).isoformat(),
            sync_type=sync_type,
            etag=etag,
            user_id=user_id,
        )
        return cls(
            event_type=f"contact.{sync_type}",
            event_data=payload.model_dump(),
            aggregate_id=0,
        )

    @classmethod
    def create_sync_completed_event(
        cls, integration_source: str, google_account_email: str, metrics: dict[str, Any]
    ) -> OutboxEvent:
        """
        Create an outbox event for sync completion.

        Args:
            integration_source: Source integration (e.g., 'google')
            google_account_email: Google account that was synced
            metrics: Sync metrics and results

        Returns:
            OutboxEvent instance ready to be saved

        Raises:
            pydantic.ValidationError: If the payload is invalid
        """
        payload = SyncCompletedEventData(
            integration_source=integration_source,
            google_account_email=google_account_email,
            metrics=metrics,
            completed_at=datetime.now(UTC).isoformat(),
        )
        return cls(
            event_type="sync.completed",
            event_data=payload.model_dump(),
            aggregate_id=0,
        )

    @classmethod
    def create_journal_sync_event(
        cls,
        journal_data: dict[str, Any],
        calendar_info_data: dict[str, Any],
        integration_source: str,
        external_event_id: str,
        calendar_id: str,
        sync_action: str,
        etag: str | None = None,
        existing_journal_id: int | None = None,
        contact_relationships: list[dict[str, Any]] | None = None,
        recurring_event_id: str | None = None,
        external_identity: str | None = None,
    ) -> OutboxEvent:
        """
        Create an outbox event for journal calendar event synchronization.

        Args:
            journal_data: Journal data transformed from external event
            calendar_info_data: Calendar info data (times, location, etc.)
            integration_source: Source integration (e.g., 'google')
            external_event_id: External system's event ID
            calendar_id: Internal calendar ID
            sync_action: Type of sync action ('created', 'updated', 'conflicted')
            etag: External system's version identifier (e.g., Google ETag)
            existing_journal_id: ID of existing journal if updating
            contact_relationships: List of contact relationship dicts with
                'email' and 'relationship_type' keys. Generic format supports
                INVITEE, PARTICIPANT, ABOUT, etc. for future integrations.
                Optional 'display_name' and 'is_self' (the account owner)
                feed contact suggestions for emails that match no contact.
            recurring_event_id: Recurring master event id when the event is an
                instance of a recurring series (drives series auto-linking)
            external_identity: Opaque token, meaningful only to the source
                integration, that is equal for every copy of the same
                real-world event however many calendars hold it

        Returns:
            OutboxEvent instance ready to be saved

        Raises:
            pydantic.ValidationError: If the payload is invalid
        """
        payload = JournalSyncEventData(
            integration_source=integration_source,
            external_event_id=external_event_id,
            calendar_id=calendar_id,
            journal_data=journal_data,
            calendar_info_data=calendar_info_data,
            sync_timestamp=datetime.now(UTC).isoformat(),
            sync_action=sync_action,
            etag=etag,
            existing_journal_id=existing_journal_id,
            contact_relationships=contact_relationships or [],
            recurring_event_id=recurring_event_id,
            external_identity=external_identity,
        )
        return cls(
            event_type=f"journal_event.{sync_action}",
            event_data=payload.model_dump(),
            aggregate_id=existing_journal_id or 0,
        )

    @classmethod
    def create_journal_series_cancelled_event(
        cls,
        integration_source: str,
        calendar_id: str,
        recurring_event_id: str,
    ) -> OutboxEvent:
        """
        Create an outbox event for a cancelled/deleted recurring series.

        Emitted when the upstream calendar reports the recurring master event
        as cancelled (whole-series deletion). The backend fans out over all
        journals linked to the series.

        Args:
            integration_source: Source integration (e.g., 'google')
            calendar_id: Internal calendar ID
            recurring_event_id: The recurring master event id of the series

        Returns:
            OutboxEvent instance ready to be saved

        Raises:
            pydantic.ValidationError: If the payload is invalid
        """
        payload = JournalSeriesCancelledEventData(
            integration_source=integration_source,
            calendar_id=calendar_id,
            recurring_event_id=recurring_event_id,
            sync_timestamp=datetime.now(UTC).isoformat(),
        )
        return cls(
            event_type="journal_event.series_cancelled",
            event_data=payload.model_dump(),
            aggregate_id=0,
        )

    @classmethod
    def create_immich_album_sync_event(
        cls,
        external_id: str,
        version_hash: str,
        sync_action: str,
        journal_data: dict[str, Any],
        album_metadata: dict[str, Any],
        integration_source: str = "immich_album",
        existing_journal_id: int | None = None,
    ) -> OutboxEvent:
        """
        Create an outbox event for Immich album synchronization.

        Emitted by the Immich worker when an album is imported as a
        ``PHOTO_ALBUM`` journal. The backend ``ImmichAlbumOutboxEventProcessor``
        creates/updates the journal from the payload.

        Args:
            external_id: Immich album UUID.
            version_hash: Hash of album metadata for change detection.
            sync_action: Type of sync action ('created', 'updated').
            journal_data: Journal fields (user_id, title, content, date range).
            album_metadata: Album display + sync metadata.
            integration_source: Source integration (default 'immich_album').
            existing_journal_id: ID of the existing journal when updating.

        Returns:
            OutboxEvent instance ready to be saved.

        Raises:
            pydantic.ValidationError: If the payload is invalid.
        """
        payload = ImmichAlbumSyncEventData(
            integration_source=integration_source,
            external_id=external_id,
            version_hash=version_hash,
            sync_action=sync_action,
            existing_journal_id=existing_journal_id,
            journal_data=journal_data,
            album_metadata=album_metadata,
            sync_timestamp=datetime.now(UTC).isoformat(),
        )
        return cls(
            event_type=f"immich_album.{sync_action}",
            event_data=payload.model_dump(),
            aggregate_id=existing_journal_id or 0,
        )

    @classmethod
    def create_match_detection_event(
        cls,
        journal_id: int,
        user_id: str,
        journal_title: str,
        journal_content: str,
        event_date_range_start: str | datetime,
        event_date_range_end: str | datetime,
    ) -> OutboxEvent:
        """
        Create an outbox event to trigger match candidate detection.

        This is the Phase 2 event in the two-phase outbox pattern:
        Phase 1 creates the journal + emits this event (same transaction),
        Phase 2 processes this event to detect matches via AI assessment.

        Args:
            journal_id: ID of the newly created journal
            user_id: User who owns the journal
            journal_title: Title for similarity comparison
            journal_content: Content for similarity comparison
            event_date_range_start: ISO start datetime for date gating
            event_date_range_end: ISO end datetime for date gating

        Returns:
            OutboxEvent instance ready to be saved

        Raises:
            pydantic.ValidationError: If the payload is invalid
        """
        payload = MatchDetectionEventData.model_validate(
            {
                "journal_id": journal_id,
                "user_id": user_id,
                "journal_title": journal_title,
                "journal_content": journal_content,
                "event_date_range_start": event_date_range_start,
                "event_date_range_end": event_date_range_end,
                "created_at": datetime.now(UTC).isoformat(),
            }
        )
        return cls(
            event_type="journal_review.detect_matches",
            event_data=payload.model_dump(mode="json"),
            aggregate_id=journal_id,
        )

    def is_failed(self) -> bool:
        """Check if the event has exceeded max retries."""
        return bool(self.retry_count >= 3)

    def can_retry(self) -> bool:
        """Check if the event can be retried."""
        return bool(self.retry_count < 3)
