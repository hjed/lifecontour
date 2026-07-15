"""SQL repository for external event link queries used by inbound sync.

Supports the recurring-series cancellation flow: resolving a cancelled
instance's link+journal facts, fanning out over all instances of a recurring
series, and checking whether a journal has local additions that protect it
from sync-driven deletion.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@dataclass(frozen=True)
class SeriesLinkedJournal:
    """A journal joined with its external event link, for sync decisions."""

    journal_id: int
    user_id: str
    external_event_id: str | None
    recurring_event_id: str | None
    link_updated_at: datetime | None
    journal_updated_at: datetime | None
    event_date_range_start: datetime | None
    event_date_range_end: datetime | None


@dataclass(frozen=True)
class DeletionProtectionFacts:
    """Local additions that protect a journal from sync-driven deletion."""

    has_children: bool
    has_tags: bool
    has_manual_contact_relationships: bool


_LINKED_JOURNAL_SELECT = """
    SELECT l.journal_id,
           j.user_id,
           l.external_event_id,
           l.recurring_event_id,
           l.updated_at AS link_updated_at,
           j.updated_at AS journal_updated_at,
           j.event_date_range_start,
           j.event_date_range_end
    FROM journal_external_event_links l
    JOIN journals j ON j.id = l.journal_id
"""


def _row_to_linked_journal(row: Any) -> SeriesLinkedJournal:
    return SeriesLinkedJournal(
        journal_id=row.journal_id,
        user_id=row.user_id,
        external_event_id=row.external_event_id,
        recurring_event_id=row.recurring_event_id,
        link_updated_at=row.link_updated_at,
        journal_updated_at=row.journal_updated_at,
        event_date_range_start=row.event_date_range_start,
        event_date_range_end=row.event_date_range_end,
    )


class SqlJournalEventLinkRepository:
    """SQL queries over journal_external_event_links for inbound sync."""

    def __init__(self, conn: AsyncConnection):
        """Initialize with database connection."""
        self.conn = conn

    async def find_by_external_event(
        self, calendar_id: UUID, external_event_id: str
    ) -> SeriesLinkedJournal | None:
        """Find the link+journal facts for one external event."""
        query = text(
            f"""
            {_LINKED_JOURNAL_SELECT}
            WHERE l.calendar_id = :calendar_id
              AND l.external_event_id = :external_event_id
            """
        )
        result = await self.conn.execute(
            query,
            {"calendar_id": calendar_id, "external_event_id": external_event_id},
        )
        row = result.fetchone()
        return _row_to_linked_journal(row) if row else None

    async def find_journals_for_series(
        self, calendar_id: UUID, recurring_event_id: str
    ) -> list[SeriesLinkedJournal]:
        """Find all journals linked to a recurring series on a calendar.

        Matches the backfilled ``recurring_event_id`` column, plus an
        ``external_event_id`` prefix fallback (Google instance ids are
        ``<masterId>_<YYYYMMDDTHHMMSSZ>``) so whole-series deletion still works
        for links synced before the recurring id was recorded.
        """
        escaped = (
            recurring_event_id.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        query = text(
            f"""
            {_LINKED_JOURNAL_SELECT}
            WHERE l.calendar_id = :calendar_id
              AND (l.recurring_event_id = :recurring_event_id
                   OR l.external_event_id LIKE :instance_prefix ESCAPE '\\')
            """
        )
        result = await self.conn.execute(
            query,
            {
                "calendar_id": calendar_id,
                "recurring_event_id": recurring_event_id,
                "instance_prefix": f"{escaped}\\_%",
            },
        )
        return [_row_to_linked_journal(row) for row in result.fetchall()]

    async def get_deletion_protection_facts(
        self, journal_id: int
    ) -> DeletionProtectionFacts:
        """Check for local additions that protect a journal from deletion.

        INVITEE contact relationships are sync-managed (created from event
        attendees), so only other relationship types count as manual additions.
        """
        query = text(
            """
            SELECT
                EXISTS (
                    SELECT 1 FROM journals WHERE parent_id = :journal_id
                ) AS has_children,
                EXISTS (
                    SELECT 1 FROM journal_tag_assignments
                    WHERE journal_id = :journal_id
                ) AS has_tags,
                EXISTS (
                    SELECT 1 FROM journal_contact_relationships
                    WHERE journal_id = :journal_id
                      AND relationship_type != 'INVITEE'
                ) AS has_manual_contact_relationships
            """
        )
        result = await self.conn.execute(query, {"journal_id": journal_id})
        row = result.fetchone()
        if row is None:  # pragma: no cover - EXISTS always returns one row
            return DeletionProtectionFacts(
                has_children=True,
                has_tags=True,
                has_manual_contact_relationships=True,
            )
        return DeletionProtectionFacts(
            has_children=row.has_children,
            has_tags=row.has_tags,
            has_manual_contact_relationships=row.has_manual_contact_relationships,
        )

    async def delete_links_for_journal(self, journal_id: int) -> None:
        """Remove all external event links for a journal.

        Called before a sync-driven journal deletion so the JournalDeleted
        event carries no external identifiers — the upstream event is already
        gone, so no outbound deletion should be attempted.
        """
        query = text(
            """
            DELETE FROM journal_external_event_links
            WHERE journal_id = :journal_id
            """
        )
        await self.conn.execute(query, {"journal_id": journal_id})
