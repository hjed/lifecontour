"""
Shared SQLAlchemy models for integration synchronization.

These models are used by both the main application and integration workers
to track synchronization state and external references.
"""

from core_shared.models.base import Base
from core_shared.models.external_reference import ExternalReference
from core_shared.models.journal_external_event_link import (
    ExternalEventLinkSyncCapability,
    ExternalEventLinkSyncStatus,
    JournalExternalEventLink,
)
from core_shared.models.outbox import OutboxEvent
from core_shared.models.outbox_events import (
    ContactSyncEventData,
    JournalStatusEventData,
    JournalSyncEventData,
    MatchDetectionEventData,
    OutboxEventData,
    SyncCompletedEventData,
    parse_outbox_event_data,
)
from core_shared.models.route import Route
from core_shared.models.sync_job import SyncJob, SyncJobStatus, SyncType
from core_shared.models.sync_metadata import SyncMetadata, SyncStatus

__all__ = [
    "Base",
    "ContactSyncEventData",
    "SyncMetadata",
    "SyncStatus",
    "SyncJob",
    "SyncJobStatus",
    "SyncType",
    "ExternalReference",
    "JournalExternalEventLink",
    "ExternalEventLinkSyncCapability",
    "ExternalEventLinkSyncStatus",
    "JournalStatusEventData",
    "JournalSyncEventData",
    "MatchDetectionEventData",
    "OutboxEvent",
    "OutboxEventData",
    "Route",
    "SyncCompletedEventData",
    "parse_outbox_event_data",
]
