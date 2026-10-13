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

from core_shared.models.history import Provenance
from core_shared.models.journal_external_event_link import (
    ExternalEventLinkSyncStatus,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# History sources that mean a person changed the journal. Everything else is a
# sync or the system acting on its own (a journal merge included).
_USER_PROVENANCES: tuple[str, ...] = (Provenance.UI.value, Provenance.MCP.value)


@dataclass(frozen=True)
class SeriesLinkedJournal:
    """A journal joined with its external event link, for sync decisions."""

    journal_id: int
    user_id: str
    calendar_id: UUID
    external_event_id: str | None
    recurring_event_id: str | None
    link_sync_status: str | None
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
    has_type_data: bool = False
    has_routes: bool = False

    @property
    def is_protected(self) -> bool:
        """Whether any local addition protects the journal from deletion."""
        return (
            self.has_children
            or self.has_tags
            or self.has_manual_contact_relationships
            or self.has_type_data
            or self.has_routes
        )


# Type-data tables whose presence marks user-authored content on a journal.
# journal_calendar_info (EVENT) is sync-managed and deliberately excluded;
# everything else is only ever written by the user (calendar sync never
# creates these rows on an EVENT journal).
_USER_TYPE_DATA_TABLES: tuple[str, ...] = (
    "journal_mood_data",
    "journal_plan_data",
    "journal_travel_data",
    "journal_fitness_data",
    "journal_outdoor_activity_data",
    "journal_bushwalking_data",
    "journal_jogging_data",
    "journal_abseiling_data",
    "journal_canyoning_data",
    "journal_climbing_data",
    "journal_kayaking_data",
    "journal_skiing_data",
    "journal_caving_data",
    "journal_canoeing_data",
    "journal_snorkelling_data",
    "journal_diving_data",
    "journal_downhill_skiing_data",
    "journal_outdoor_planning_data",
    "journal_outdoor_training_data",
    "journal_gear_maintenance_data",
    "journal_gear_usage_data",
)

_TYPE_DATA_EXISTS_SQL = " OR ".join(
    f"EXISTS (SELECT 1 FROM {table} WHERE journal_id = :journal_id)"
    for table in _USER_TYPE_DATA_TABLES
)


_LINKED_JOURNAL_SELECT = """
    SELECT l.journal_id,
           j.user_id,
           l.calendar_id,
           l.external_event_id,
           l.recurring_event_id,
           l.sync_status AS link_sync_status,
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
        calendar_id=row.calendar_id,
        external_event_id=row.external_event_id,
        recurring_event_id=row.recurring_event_id,
        link_sync_status=row.link_sync_status,
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

    async def find_by_journal(
        self, journal_id: int, calendar_id: UUID
    ) -> SeriesLinkedJournal | None:
        """Find the link+journal facts for a journal's link in one calendar."""
        query = text(
            f"""
            {_LINKED_JOURNAL_SELECT}
            WHERE l.journal_id = :journal_id
              AND l.calendar_id = :calendar_id
            """
        )
        result = await self.conn.execute(
            query, {"journal_id": journal_id, "calendar_id": calendar_id}
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
        # The prefix fallback only applies to unbackfilled links (a stored
        # recurring id is authoritative) and only to single-segment suffixes:
        # Google "this and following" splits create a SUCCESSOR master named
        # <oldId>_R<time>, whose instance ids also start with <oldId>_ but
        # carry an extra underscore segment — those belong to a different,
        # still-active series and must not match.
        query = text(
            f"""
            {_LINKED_JOURNAL_SELECT}
            WHERE l.calendar_id = :calendar_id
              AND (l.recurring_event_id = :recurring_event_id
                   OR (l.recurring_event_id IS NULL
                       AND l.external_event_id LIKE :instance_prefix ESCAPE '\\'
                       AND l.external_event_id
                           NOT LIKE :deeper_prefix ESCAPE '\\'))
            """
        )
        result = await self.conn.execute(
            query,
            {
                "calendar_id": calendar_id,
                "recurring_event_id": recurring_event_id,
                "instance_prefix": f"{escaped}\\_%",
                "deeper_prefix": f"{escaped}\\_%\\_%",
            },
        )
        return [_row_to_linked_journal(row) for row in result.fetchall()]

    async def get_deletion_protection_facts(
        self, journal_id: int
    ) -> DeletionProtectionFacts:
        """Check for local additions that protect a journal from deletion.

        INVITEE contact relationships are sync-managed (created from event
        attendees), so only other relationship types count as manual additions.
        Type data (mood, plan, activity data, ...) and GPS routes never bump
        journals.updated_at, so they are checked explicitly here.
        """
        query = text(
            f"""
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
                ) AS has_manual_contact_relationships,
                ({_TYPE_DATA_EXISTS_SQL}) AS has_type_data,
                EXISTS (
                    SELECT 1 FROM routes WHERE journal_id = :journal_id
                ) AS has_routes
            """
        )
        result = await self.conn.execute(query, {"journal_id": journal_id})
        row = result.fetchone()
        if row is None:  # pragma: no cover - EXISTS always returns one row
            return DeletionProtectionFacts(
                has_children=True,
                has_tags=True,
                has_manual_contact_relationships=True,
                has_type_data=True,
                has_routes=True,
            )
        return DeletionProtectionFacts(
            has_children=row.has_children,
            has_tags=row.has_tags,
            has_manual_contact_relationships=row.has_manual_contact_relationships,
            has_type_data=row.has_type_data,
            has_routes=row.has_routes,
        )

    async def lock_recurrence(self, calendar_id: UUID, recurring_event_id: str) -> None:
        """Serialise work on one recurrence's cancellations until commit.

        Take it before writing any of the recurrence's rows. Two cancellations
        of adjacent occurrences processed at once would otherwise each read
        the other as live and both keep their own; and a handler that had
        already row-locked its own link before waiting here could deadlock
        with the holder, which deletes or backfills that link. Re-entrant
        within a transaction, so taking it again later is harmless.
        """
        await self.conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"cancelled_recurrence:{calendar_id}:{recurring_event_id}"},
        )

    async def has_other_live_links(self, journal_id: int, calendar_id: UUID) -> bool:
        """Whether a calendar *other than this one* still holds the event.

        A de-duplicated event is one journal several calendars link to, so one
        calendar dropping it says nothing about the others.
        """
        query = text(
            """
            SELECT 1
            FROM journal_external_event_links
            WHERE journal_id = :journal_id
              AND calendar_id <> :calendar_id
              AND sync_status <> :cancelled
            LIMIT 1
            """
        )
        result = await self.conn.execute(
            query,
            {
                "journal_id": journal_id,
                "calendar_id": calendar_id,
                "cancelled": ExternalEventLinkSyncStatus.CANCELLED.value,
            },
        )
        return result.fetchone() is not None

    async def has_user_history(self, journal_id: int) -> bool:
        """Whether a person has ever changed this journal, in the app or via MCP.

        Read from the journal's change history, whose provenance says who made
        each change. Sync and system writes don't count: a journal merge, for
        one, rewrites ``updated_at`` without anyone adding to the journal.
        """
        query = text(
            """
            SELECT EXISTS (
                SELECT 1 FROM field_history
                WHERE entity_type = 'journal'
                  AND entity_id = :journal_id
                  AND source = ANY(:sources)
            )
            """
        )
        result = await self.conn.execute(
            query,
            {"journal_id": journal_id, "sources": list(_USER_PROVENANCES)},
        )
        return bool(result.scalar())

    async def backfill_recurring_event_id(
        self, calendar_id: UUID, recurring_event_id: str, journal_ids: list[int]
    ) -> None:
        """Record the recurring id on links matched only by their id prefix.

        Links synced before the recurring id was stored are found through the
        prefix fallback; giving them the id lets later cancellations plan them
        by the column alone.
        """
        if not journal_ids:
            return
        query = text(
            """
            UPDATE journal_external_event_links
            SET recurring_event_id = :recurring_event_id
            WHERE calendar_id = :calendar_id
              AND journal_id = ANY(:journal_ids)
              AND recurring_event_id IS NULL
            """
        )
        await self.conn.execute(
            query,
            {
                "calendar_id": calendar_id,
                "recurring_event_id": recurring_event_id,
                "journal_ids": journal_ids,
            },
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
