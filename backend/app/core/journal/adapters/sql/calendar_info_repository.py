"""SQL implementation of CalendarInfoRepository."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from core_shared.models import (
    ExternalEventLinkSyncCapability,
    ExternalEventLinkSyncStatus,
)
from core_shared.models.journals import (
    CalendarInfo,
    CalendarInfoValidationError,
)
from core_shared.models.journals.event_state import EventState
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import CalendarInfoRepository


def project_calendar_info_to_linked_calendar(
    calendar_info: CalendarInfo,
    calendar_id: UUID,
) -> CalendarInfo:
    """Project legacy calendar info onto a linked calendar ID."""
    return CalendarInfo(
        journal_id=calendar_info.journal_id,
        calendar_id=calendar_id,
        description=calendar_info.description,
        start_time=calendar_info.start_time,
        end_time=calendar_info.end_time,
        is_all_day=calendar_info.is_all_day,
        location=calendar_info.location,
        timezone=calendar_info.timezone,
        sync_invitees=calendar_info.sync_invitees,
        private_description=calendar_info.private_description,
        event_state=calendar_info.event_state,
        event_start_date=calendar_info.event_start_date,
        event_end_date=calendar_info.event_end_date,
        created_at=calendar_info.created_at,
        updated_at=calendar_info.updated_at,
    )


class SqlCalendarInfoRepository(CalendarInfoRepository):
    """SQL implementation of CalendarInfoRepository using SQLAlchemy Core."""

    def __init__(self, connection: AsyncConnection):
        """Initialize repository with database connection."""
        self.conn = connection

    def _row_to_calendar_info(
        self,
        row: Any,
        event_start_date: date | None = None,
        event_end_date: date | None = None,
    ) -> CalendarInfo:
        """Convert a database row to a CalendarInfo entity."""
        start_date = event_start_date
        end_date = event_end_date

        tz_str = getattr(row, "timezone", None)

        def _get_local_date(dt: datetime | Any) -> date | None:
            if not dt:
                return None

            # Since SQLAlchemy stores it with timezone context in Postgres (or naive UTC context)
            if not isinstance(dt, datetime):
                # Fallback if it's not a datetime object somehow
                return dt.date()  # type: ignore[no-any-return]

            from datetime import UTC
            from zoneinfo import ZoneInfo

            # Ensure the dt is timezone-aware (assumed UTC if naive from DB)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)

            if not tz_str:
                return dt.date()
            try:
                tz = ZoneInfo(tz_str)
                return dt.astimezone(tz).date()
            except Exception:  # noqa: BLE001
                return dt.date()

        if (
            start_date is None
            and hasattr(row, "event_date_range_start")
            and row.event_date_range_start
        ):
            start_date = _get_local_date(row.event_date_range_start)
        if (
            end_date is None
            and hasattr(row, "event_date_range_end")
            and row.event_date_range_end
        ):
            end_date = _get_local_date(row.event_date_range_end)

        return CalendarInfo(
            journal_id=row.journal_id,
            calendar_id=row.calendar_id,
            description=getattr(row, "description", None),
            start_time=row.start_time,
            end_time=row.end_time,
            is_all_day=row.is_all_day,
            location=row.location,
            timezone=getattr(row, "timezone", None),
            sync_invitees=row.sync_invitees,
            private_description=getattr(row, "private_description", False),
            event_state=EventState(row.event_state),
            event_start_date=start_date,
            event_end_date=end_date,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def find_by_journal_id(self, journal_id: int) -> CalendarInfo | None:
        """Find calendar info by journal ID."""
        query = text(
            """
            SELECT jci.journal_id, jci.calendar_id, jci.description, jci.start_time, jci.end_time,
                   jci.is_all_day, jci.location, jci.timezone, jci.sync_invitees,
                   jci.private_description, jci.event_state,
                   jci.created_at, jci.updated_at,
                   j.event_date_range_start, j.event_date_range_end
            FROM journal_calendar_info jci
            INNER JOIN journals j ON j.id = jci.journal_id
            WHERE jci.journal_id = :journal_id
            """
        )
        result = await self.conn.execute(query, {"journal_id": journal_id})
        row = result.fetchone()

        if not row:
            return None

        return self._row_to_calendar_info(row)

    async def save(self, calendar_info: CalendarInfo) -> CalendarInfo:
        """Save calendar info (insert or update)."""
        if calendar_info.journal_id is None:
            raise CalendarInfoValidationError(
                "journal_id", "journal_id must be set before saving CalendarInfo"
            )

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
                journal_id, calendar_id, description, start_time, end_time,
                is_all_day, location, timezone, sync_invitees,
                private_description, event_state
            )
            VALUES (
                :journal_id, :calendar_id, :description, :start_time, :end_time,
                :is_all_day, :location, :timezone, :sync_invitees,
                :private_description, :event_state
            )
            RETURNING journal_id, calendar_id, description, start_time, end_time,
                      is_all_day, location, timezone, sync_invitees,
                      private_description, event_state,
                      created_at, updated_at
            """
        )
        result = await self.conn.execute(
            query,
            {
                "journal_id": calendar_info.journal_id,
                "calendar_id": str(calendar_info.calendar_id),
                "description": calendar_info.description,
                "start_time": calendar_info.start_time,
                "end_time": calendar_info.end_time,
                "is_all_day": calendar_info.is_all_day,
                "location": calendar_info.location,
                "timezone": calendar_info.timezone,
                "sync_invitees": calendar_info.sync_invitees,
                "private_description": calendar_info.private_description,
                "event_state": calendar_info.event_state.value,
            },
        )
        row = result.fetchone()
        return self._row_to_calendar_info(
            row,
            event_start_date=calendar_info.event_start_date,
            event_end_date=calendar_info.event_end_date,
        )

    async def _update(self, calendar_info: CalendarInfo) -> CalendarInfo:
        """Update existing calendar info."""
        query = text(
            """
            UPDATE journal_calendar_info
            SET calendar_id = :calendar_id,
                description = :description,
                start_time = :start_time,
                end_time = :end_time,
                is_all_day = :is_all_day,
                location = :location,
                timezone = :timezone,
                sync_invitees = :sync_invitees,
                private_description = :private_description,
                event_state = :event_state,
                updated_at = now()
            WHERE journal_id = :journal_id
            RETURNING journal_id, calendar_id, description, start_time, end_time,
                      is_all_day, location, timezone, sync_invitees,
                      private_description, event_state,
                      created_at, updated_at
            """
        )
        result = await self.conn.execute(
            query,
            {
                "journal_id": calendar_info.journal_id,
                "calendar_id": str(calendar_info.calendar_id),
                "description": calendar_info.description,
                "start_time": calendar_info.start_time,
                "end_time": calendar_info.end_time,
                "is_all_day": calendar_info.is_all_day,
                "location": calendar_info.location,
                "timezone": calendar_info.timezone,
                "sync_invitees": calendar_info.sync_invitees,
                "private_description": calendar_info.private_description,
                "event_state": calendar_info.event_state.value,
            },
        )
        row = result.fetchone()
        return self._row_to_calendar_info(
            row,
            event_start_date=calendar_info.event_start_date,
            event_end_date=calendar_info.event_end_date,
        )

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
            SELECT jci.journal_id, jci.calendar_id, jci.description, jci.start_time, jci.end_time,
                   jci.is_all_day, jci.location, jci.timezone, jci.sync_invitees,
                   jci.private_description, jci.event_state,
                   jci.created_at, jci.updated_at,
                   j.event_date_range_start, j.event_date_range_end
            FROM journal_calendar_info jci
            INNER JOIN journals j ON j.id = jci.journal_id
            WHERE jci.calendar_id = :calendar_id
            ORDER BY jci.journal_id ASC
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
            SELECT jci.journal_id, jci.calendar_id, jci.description, jci.start_time, jci.end_time,
                   jci.is_all_day, jci.location, jci.timezone, jci.sync_invitees,
                   jci.private_description, jci.event_state,
                   jci.created_at, jci.updated_at,
                   j.event_date_range_start, j.event_date_range_end,
                   jeel.calendar_id AS linked_calendar_id
            FROM journal_external_event_links jeel
            INNER JOIN journal_calendar_info jci ON jci.journal_id = jeel.journal_id
            INNER JOIN journals j ON j.id = jci.journal_id
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

        def get_sort_key(ci: CalendarInfo) -> int:
            assert ci.journal_id is not None, (
                "CalendarInfo from DB must have a journal_id"
            )
            return ci.journal_id

        return sorted(
            [*primary_events, *linked_events],
            key=get_sort_key,
        )

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
