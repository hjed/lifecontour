"""SQL implementation of CalendarRepository."""

from typing import Any
from uuid import UUID

from core_shared.models.journals import Calendar, CalendarNotFoundError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import CalendarRepository


class SqlCalendarRepository(CalendarRepository):
    """SQL implementation of CalendarRepository using SQLAlchemy Core."""

    def __init__(self, connection: AsyncConnection):
        """Initialize repository with database connection."""
        self.conn = connection

    def _row_to_calendar(self, row: Any) -> Calendar:
        """Convert a database row to a Calendar entity."""
        return Calendar(
            id=row.id,
            user_id=row.user_id,
            name=row.name,
            color=row.color,
            description=row.description,
            is_synced_to_google=row.is_synced_to_google,
            google_calendar_id=row.google_calendar_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def find_by_id(self, calendar_id: UUID) -> Calendar | None:
        """Find a calendar by ID."""
        query = text(
            """
            SELECT id, user_id, name, color, description,
                   is_synced_to_google, google_calendar_id,
                   created_at, updated_at
            FROM calendars
            WHERE id = :calendar_id
            """
        )
        result = await self.conn.execute(query, {"calendar_id": str(calendar_id)})
        row = result.fetchone()

        if not row:
            return None

        return self._row_to_calendar(row)

    async def save(self, calendar: Calendar) -> Calendar:
        """Save a calendar (insert or update)."""
        if calendar.id is None:
            return await self._insert(calendar)
        else:
            return await self._update(calendar)

    async def _insert(self, calendar: Calendar) -> Calendar:
        """Insert a new calendar."""
        query = text(
            """
            INSERT INTO calendars (
                user_id, name, color, description,
                is_synced_to_google, google_calendar_id
            )
            VALUES (
                :user_id, :name, :color, :description,
                :is_synced_to_google, :google_calendar_id
            )
            RETURNING id, user_id, name, color, description,
                      is_synced_to_google, google_calendar_id,
                      created_at, updated_at
            """
        )
        result = await self.conn.execute(
            query,
            {
                "user_id": calendar.user_id,
                "name": calendar.name,
                "color": calendar.color,
                "description": calendar.description,
                "is_synced_to_google": calendar.is_synced_to_google,
                "google_calendar_id": calendar.google_calendar_id,
            },
        )
        row = result.fetchone()
        return self._row_to_calendar(row)

    async def _update(self, calendar: Calendar) -> Calendar:
        """Update an existing calendar."""
        query = text(
            """
            UPDATE calendars
            SET user_id = :user_id,
                name = :name,
                color = :color,
                description = :description,
                is_synced_to_google = :is_synced_to_google,
                google_calendar_id = :google_calendar_id,
                updated_at = now()
            WHERE id = :id
            RETURNING id, user_id, name, color, description,
                      is_synced_to_google, google_calendar_id,
                      created_at, updated_at
            """
        )
        result = await self.conn.execute(
            query,
            {
                "id": str(calendar.id),
                "user_id": calendar.user_id,
                "name": calendar.name,
                "color": calendar.color,
                "description": calendar.description,
                "is_synced_to_google": calendar.is_synced_to_google,
                "google_calendar_id": calendar.google_calendar_id,
            },
        )
        row = result.fetchone()

        if not row:
            raise CalendarNotFoundError(str(calendar.id))

        return self._row_to_calendar(row)

    async def delete(self, calendar_id: UUID) -> None:
        """Delete a calendar by ID."""
        query = text("DELETE FROM calendars WHERE id = :calendar_id")
        result = await self.conn.execute(query, {"calendar_id": str(calendar_id)})

        if result.rowcount == 0:
            raise CalendarNotFoundError(str(calendar_id))

    async def get_all(self, user_id: str) -> list[Calendar]:
        """Get all calendars for a user."""
        query = text(
            """
            SELECT id, user_id, name, color, description,
                   is_synced_to_google, google_calendar_id,
                   created_at, updated_at
            FROM calendars
            WHERE user_id = :user_id
            ORDER BY name ASC
            """
        )
        result = await self.conn.execute(query, {"user_id": user_id})
        return [self._row_to_calendar(row) for row in result.fetchall()]

    async def get_synced_calendars(self, user_id: str) -> list[Calendar]:
        """Get all calendars synced to Google Calendar for a user."""
        query = text(
            """
            SELECT id, user_id, name, color, description,
                   is_synced_to_google, google_calendar_id,
                   created_at, updated_at
            FROM calendars
            WHERE user_id = :user_id AND is_synced_to_google = true
            ORDER BY name ASC
            """
        )
        result = await self.conn.execute(query, {"user_id": user_id})
        return [self._row_to_calendar(row) for row in result.fetchall()]
