"""SQL implementation of CalendarInfoRepository."""

from typing import Any
from uuid import UUID

from core_shared.models import (
    ExternalEventLinkSyncCapability,
    ExternalEventLinkSyncStatus,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.calendar_info import CalendarInfo
from app.core.journal.models.repositories import CalendarInfoRepository


def project_calendar_info_to_linked_calendar(
    calendar_info: CalendarInfo,
    calendar_id: UUID,
) -> CalendarInfo:
    """Project legacy calendar info onto a linked calendar ID."""
    return CalendarInfo(
        journal_id=calendar_info.journal_id,
        calendar_id=calendar_id,
        start_time=calendar_info.start_time,
        end_time=calendar_info.end_time,
        is_all_day=calendar_info.is_all_day,
        location=calendar_info.location,
        sync_invitees=calendar_info.sync_invitees,
        created_at=calendar_info.created_at,
        updated_at=calendar_info.updated_at,
    )


class SqlCalendarInfoRepository(CalendarInfoRepository):
    """SQL implementation of CalendarInfoRepository using SQLAlchemy Core."""

    def __init__(self, connection: AsyncConnection):
        """Initialize repository with database connection."""
        self.conn = connection

    def _row_to_calendar_info(self, row: Any) -> CalendarInfo:
        """Convert a database row to a CalendarInfo entity."""
        return CalendarInfo(
            journal_id=row.journal_id,
            calendar_id=row.calendar_id,
            start_time=row.start_time,
            end_time=row.end_time,
            is_all_day=row.is_all_day,
            location=row.location,
            sync_invitees=row.sync_invitees,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def find_by_journal_id(self, journal_id: int) -> CalendarInfo | None:
        """Find calendar info by journal ID."""
        query = text(
            """
            SELECT journal_id, calendar_id, start_time, end_time,
                   is_all_day, location, sync_invitees,
                   created_at, updated_at
            FROM journal_calendar_info
            WHERE journal_id = :journal_id
            """
        )
        result = await self.conn.execute(query, {"journal_id": journal_id})
        row = result.fetchone()

        if not row:
            return None

        return self._row_to_calendar_info(row)

    async def save(self, calendar_info: CalendarInfo) -> CalendarInfo:
        """Save calendar info (insert or update)."""
        # Check if row exists
        existing = await self.find_by_journal_id(calendar_info.journal_id)
        if existing is None:
            saved = await self._insert(calendar_info)
        else:
            saved = await self._update(calendar_info)
            if existing.calendar_id != calendar_info.calendar_id:
                await self._delete_external_event_link(
                    calendar_info.journal_id,
                    existing.calendar_id,
                )

        await self._ensure_external_event_link(saved)
        return saved

    async def _insert(self, calendar_info: CalendarInfo) -> CalendarInfo:
        """Insert new calendar info."""
        query = text(
            """
            INSERT INTO journal_calendar_info (
                journal_id, calendar_id, start_time, end_time,
                is_all_day, location, sync_invitees
            )
            VALUES (
                :journal_id, :calendar_id, :start_time, :end_time,
                :is_all_day, :location, :sync_invitees
            )
            RETURNING journal_id, calendar_id, start_time, end_time,
                      is_all_day, location, sync_invitees,
                      created_at, updated_at
            """
        )
        result = await self.conn.execute(
            query,
            {
                "journal_id": calendar_info.journal_id,
                "calendar_id": str(calendar_info.calendar_id),
                "start_time": calendar_info.start_time,
                "end_time": calendar_info.end_time,
                "is_all_day": calendar_info.is_all_day,
                "location": calendar_info.location,
                "sync_invitees": calendar_info.sync_invitees,
            },
        )
        row = result.fetchone()
        return self._row_to_calendar_info(row)

    async def _update(self, calendar_info: CalendarInfo) -> CalendarInfo:
        """Update existing calendar info."""
        query = text(
            """
            UPDATE journal_calendar_info
            SET calendar_id = :calendar_id,
                start_time = :start_time,
                end_time = :end_time,
                is_all_day = :is_all_day,
                location = :location,
                sync_invitees = :sync_invitees,
                updated_at = now()
            WHERE journal_id = :journal_id
            RETURNING journal_id, calendar_id, start_time, end_time,
                      is_all_day, location, sync_invitees,
                      created_at, updated_at
            """
        )
        result = await self.conn.execute(
            query,
            {
                "journal_id": calendar_info.journal_id,
                "calendar_id": str(calendar_info.calendar_id),
                "start_time": calendar_info.start_time,
                "end_time": calendar_info.end_time,
                "is_all_day": calendar_info.is_all_day,
                "location": calendar_info.location,
                "sync_invitees": calendar_info.sync_invitees,
            },
        )
        row = result.fetchone()
        return self._row_to_calendar_info(row)

    async def delete(self, journal_id: int) -> None:
        """Delete calendar info by journal ID."""
        await self.conn.execute(
            text(
                "DELETE FROM journal_external_event_links WHERE journal_id = :journal_id"
            ),
            {"journal_id": journal_id},
        )
        query = text("DELETE FROM journal_calendar_info WHERE journal_id = :journal_id")
        await self.conn.execute(query, {"journal_id": journal_id})

    async def get_by_calendar_id(self, calendar_id: UUID) -> list[CalendarInfo]:
        """Get all calendar info entries for a calendar."""
        primary_query = text(
            """
            SELECT journal_id, calendar_id, start_time, end_time,
                   is_all_day, location, sync_invitees,
                   created_at, updated_at
            FROM journal_calendar_info
            WHERE calendar_id = :calendar_id
            ORDER BY journal_id ASC
            """
        )
        primary_result = await self.conn.execute(
            primary_query, {"calendar_id": str(calendar_id)}
        )
        primary_events = [
            self._row_to_calendar_info(row) for row in primary_result.fetchall()
        ]

        linked_query = text(
            """
            SELECT jci.journal_id, jci.calendar_id, jci.start_time, jci.end_time,
                   jci.is_all_day, jci.location, jci.sync_invitees,
                   jci.created_at, jci.updated_at,
                   jeel.calendar_id AS linked_calendar_id
            FROM journal_external_event_links jeel
            INNER JOIN journal_calendar_info jci ON jci.journal_id = jeel.journal_id
            WHERE jeel.calendar_id = :calendar_id
              AND jci.calendar_id <> jeel.calendar_id
            ORDER BY jci.journal_id ASC
            """
        )
        linked_result = await self.conn.execute(
            linked_query, {"calendar_id": str(calendar_id)}
        )
        linked_events = [
            project_calendar_info_to_linked_calendar(
                self._row_to_calendar_info(row),
                row.linked_calendar_id,
            )
            for row in linked_result.fetchall()
        ]

        return sorted([*primary_events, *linked_events], key=lambda ci: ci.journal_id)

    async def _ensure_external_event_link(self, calendar_info: CalendarInfo) -> None:
        """Ensure the compatibility link row exists for legacy EVENT storage."""
        await self.conn.execute(
            text(
                """
                INSERT INTO journal_external_event_links (
                    journal_id,
                    calendar_id,
                    external_event_id,
                    external_version,
                    sync_capability,
                    sync_status
                )
                VALUES (
                    :journal_id,
                    :calendar_id,
                    NULL,
                    NULL,
                    :sync_capability,
                    :sync_status
                )
                ON CONFLICT (journal_id, calendar_id)
                DO NOTHING
                """
            ),
            {
                "journal_id": calendar_info.journal_id,
                "calendar_id": str(calendar_info.calendar_id),
                "sync_capability": ExternalEventLinkSyncCapability.OUTBOUND.value,
                "sync_status": ExternalEventLinkSyncStatus.PENDING.value,
            },
        )

    async def _delete_external_event_link(
        self, journal_id: int, calendar_id: UUID
    ) -> None:
        """Delete a specific compatibility link row."""
        await self.conn.execute(
            text(
                """
                DELETE FROM journal_external_event_links
                WHERE journal_id = :journal_id AND calendar_id = :calendar_id
                """
            ),
            {"journal_id": journal_id, "calendar_id": str(calendar_id)},
        )
