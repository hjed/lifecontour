"""
Integration domain entities.

Contains entities for tracking synchronization state and external references
between internal entities and external services.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class SyncStatus(Enum):
    """Status of synchronization operation."""

    SUCCESS = "success"
    FAILED = "failed"
    IN_PROGRESS = "in_progress"
    PENDING = "pending"


@dataclass
class SyncMetadata:
    """
    Tracks synchronization state between external systems and internal entities.

    Used to implement idempotent sync operations and track sync history.
    """

    internal_id: int
    integration_source: str
    external_id: str
    last_synced_at: datetime
    version_hash: str
    sync_status: SyncStatus
    id: int | None = None
    error_message: str | None = None
    retry_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate sync metadata properties."""
        if not self.integration_source.strip():
            raise ValueError("Integration source cannot be empty")

        if not self.external_id.strip():
            raise ValueError("External ID cannot be empty")

        if not self.version_hash.strip():
            raise ValueError("Version hash cannot be empty")

        if self.retry_count < 0:
            raise ValueError("Retry count cannot be negative")


@dataclass
class ExternalReference:
    """
    Links internal entities to external resources.

    Provides a way to reference external data without storing copies,
    maintaining links to photos, documents, or other external resources.
    """

    entity_id: int
    entity_type: str
    integration_source: str
    external_id: str
    id: int | None = None
    external_url: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate external reference properties."""
        if not self.entity_type.strip():
            raise ValueError("Entity type cannot be empty")

        if not self.integration_source.strip():
            raise ValueError("Integration source cannot be empty")

        if not self.external_id.strip():
            raise ValueError("External ID cannot be empty")

        # Validate entity_type is one of the known types
        valid_entity_types = {
            "contact",
            "journal_entry",
            "calendar_event",
            "photo",
            "album",
            "activity",
            "transaction",
        }
        if self.entity_type not in valid_entity_types:
            raise ValueError(
                f"Entity type must be one of: {', '.join(valid_entity_types)}"
            )

        # Initialize metadata as empty dict if None
        if self.metadata is None:
            self.metadata = {}
