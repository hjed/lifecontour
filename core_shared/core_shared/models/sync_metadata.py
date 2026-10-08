"""
Sync metadata SQLAlchemy model.

Tracks synchronization state between external systems and internal entities.
Used to implement idempotent sync operations and track sync history.
"""

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from core_shared.models.base import Base


class SyncStatus(Enum):
    """Status of synchronization operation."""

    SUCCESS = "success"
    FAILED = "failed"
    IN_PROGRESS = "in_progress"
    PENDING = "pending"
    CONFLICT = "conflict"


class SyncMetadata(Base):
    """
    Tracks synchronization state between external systems and internal entities.

    Used to implement idempotent sync operations and track sync history.
    This model supports:
    1. Per-integration sync state tracking
    2. Error logging and debugging
    3. Sync scheduling and coordination
    4. Version-based change detection
    """

    __tablename__ = "sync_metadata"

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Core sync tracking fields
    internal_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="ID of the internal entity being synced (Integer)",
    )
    internal_uuid: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        comment="ID of the internal entity being synced (UUID)",
    )
    integration_source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Name of the integration source (e.g., 'google', 'immich')",
    )
    external_id: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="External system's ID for this entity"
    )
    # Owner of the linked entity. A link is keyed by
    # (user_id, integration_source, external_id) through
    # ``uq_sync_metadata_user_source_external``: two users may each link the
    # same external id, and every lookup, update and delete takes the owner.
    user_id: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Owner of the linked entity",
    )

    # Sync state tracking
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Timestamp of the last successful sync",
    )
    version_hash: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="Hash/ETag for change detection"
    )
    sync_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Current sync status: 'success', 'failed', 'in_progress', 'pending'",
    )

    # Consolidated integration-link metadata (canonical link store).
    # Absorbs the fields previously held only by ``external_references`` so that
    # ``sync_metadata`` can become the single source of truth for entity links.
    reference_data: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Additional link metadata as JSON (e.g. album display fields)",
    )
    internal_entity_type: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="Internal entity type (e.g. 'contact', 'journal', 'gear_item')",
    )
    external_entity_type: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="External entity type (e.g. 'person', 'album', 'activity')",
    )

    # Error handling and retry logic
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Error message from the last failed sync"
    )
    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
        comment="Number of retry attempts for failed syncs",
    )

    # Audit timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        comment="When this sync metadata record was created",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
        comment="When this sync metadata record was last updated",
    )

    def __repr__(self) -> str:
        return (
            f"<SyncMetadata(id={self.id}, "
            f"integration_source='{self.integration_source}', "
            f"external_id='{self.external_id}', "
            f"sync_status='{self.sync_status}')>"
        )
