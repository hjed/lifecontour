"""
Integration domain entities.

Contains entities for tracking synchronization state and external references
between internal entities and external services.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


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
