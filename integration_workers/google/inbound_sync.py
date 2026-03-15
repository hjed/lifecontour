"""Inbound sync helpers for Google Calendar → Journal synchronization.

Pure-logic module containing:
- InboundSyncClassifier: determines what action to take for each inbound event
- InboundFieldMerger: determines which journal fields to update from inbound data
"""

from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol


class InboundSyncAction(StrEnum):
    """Action to take for an inbound Google Calendar event."""

    CREATE_JOURNAL = "create_journal"
    UPDATE_JOURNAL = "update_journal"
    SKIP_UNCHANGED = "skip_unchanged"
    SKIP_ONE_WAY = "skip_one_way"
    SKIP_CANCELLED = "skip_cancelled"


class ExternalEventLinkProtocol(Protocol):
    """Protocol for the external event link fields needed by the classifier."""

    @property
    def external_version(self) -> str | None: ...

    @property
    def sync_capability(self) -> str: ...


class GoogleEventProtocol(Protocol):
    """Protocol for the Google event fields needed by the classifier."""

    @property
    def etag(self) -> str | None: ...

    @property
    def status(self) -> str | None: ...


class InboundSyncClassifier:
    """Determines the sync action for each inbound Google Calendar event.

    Uses ETag comparison and sync_capability checks to decide whether to
    create, update, or skip each event. Conflict detection (e.g. protected
    local edits) is handled at the backend level by InboundFieldMerger,
    not by this classifier.
    """

    def classify_inbound_event(
        self,
        google_event: GoogleEventProtocol,
        existing_link: ExternalEventLinkProtocol | None,
    ) -> InboundSyncAction:
        """Classify what action to take for an inbound event.

        Args:
            google_event: The inbound Google Calendar event
            existing_link: The existing external event link, or None if new

        Returns:
            The action to take for this event
        """
        # Cancelled events are skipped (Phase 3 handles deletion)
        if google_event.status == "cancelled":
            return InboundSyncAction.SKIP_CANCELLED

        # No existing link → new journal
        if existing_link is None:
            return InboundSyncAction.CREATE_JOURNAL

        # One-way guard: outbound-only links reject inbound updates
        if existing_link.sync_capability == "outbound":
            return InboundSyncAction.SKIP_ONE_WAY

        # ETag comparison: unchanged events are skipped
        if (
            existing_link.external_version is not None
            and existing_link.external_version == google_event.etag
        ):
            return InboundSyncAction.SKIP_UNCHANGED

        # Different ETag with bidirectional capability → update
        return InboundSyncAction.UPDATE_JOURNAL


# Fields that always take inbound values regardless of local edits
_ALWAYS_UPDATE_FIELDS = frozenset(
    {
        "event_date_range_start",
        "event_date_range_end",
    }
)

# Fields protected when there are local edits
_PROTECTED_FIELDS = frozenset(
    {
        "title",
        "content",
    }
)


class InboundFieldMerger:
    """Determines which journal fields to update from inbound data.

    Protected field rule: if journal.updated_at > link.last_synced_at,
    the journal was manually edited locally → preserve existing title/content,
    only update time fields from inbound.
    """

    def merge_fields(
        self,
        existing_data: dict[str, Any],
        inbound_data: dict[str, Any],
        journal_updated_at: datetime,
        link_last_synced_at: datetime,
    ) -> dict[str, Any]:
        """Merge inbound data into existing journal data with protection rules.

        Args:
            existing_data: Current journal field values
            inbound_data: New field values from Google Calendar
            journal_updated_at: When the journal was last updated
            link_last_synced_at: When the link was last synced

        Returns:
            Merged data dictionary with protected fields preserved
        """
        has_local_edits = journal_updated_at > link_last_synced_at

        merged = dict(existing_data)

        for key, value in inbound_data.items():
            if key in _ALWAYS_UPDATE_FIELDS:
                # Time fields always take inbound values
                merged[key] = value
            elif has_local_edits and key in _PROTECTED_FIELDS:
                # Protected fields preserved when there are local edits
                pass
            else:
                # All other fields take inbound values
                merged[key] = value

        return merged
