"""SQL implementation of CalendarInfoRepository."""

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.calendar_info import CalendarInfo
from app.core.journal.models.repositories import CalendarInfoRepository


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
            return await self._insert(calendar_info)
        else:
            return await self._update(calendar_info)

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
        query = text("DELETE FROM journal_calendar_info WHERE journal_id = :journal_id")
        await self.conn.execute(query, {"journal_id": journal_id})

    async def get_by_calendar_id(self, calendar_id: UUID) -> list[CalendarInfo]:
        """Get all calendar info entries for a calendar."""
        query = text(
            """
            SELECT journal_id, calendar_id, start_time, end_time,
                   is_all_day, location, sync_invitees,
                   created_at, updated_at
            FROM journal_calendar_info
            WHERE calendar_id = :calendar_id
            ORDER BY journal_id ASC
            """
        )
        result = await self.conn.execute(query, {"calendar_id": str(calendar_id)})
        return [self._row_to_calendar_info(row) for row in result.fetchall()]
