"""Service layer for calendar mutations.

Wraps calendar create/update/delete in explicit units of work so each write is
committed before the HTTP response is sent (issue #945), keeping transaction
ownership in the service layer rather than the controller.

The verify-then-write steps (ownership checks, in-use checks) run on the same
``transaction`` connection as the write, raising domain-level errors that the
controller maps to HTTP responses.
"""

from core_shared.models.journals import (
    Calendar,
    CalendarNotFoundError,
    JournalDomainError,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import CalendarRepository
from app.infrastructure.unit_of_work import transactional


class CalendarPermissionError(JournalDomainError):
    """Raised when a user attempts to modify a calendar they do not own."""

    def __init__(self, message: str):
        super().__init__(message, 403)


class CalendarInUseError(JournalDomainError):
    """Raised when attempting to delete a calendar still used by journals."""

    def __init__(self, message: str, usage_count: int) -> None:
        super().__init__(message, 409)
        self.usage_count = usage_count


class CalendarService:
    """Service for persisting calendars as committed units of work."""

    def __init__(self, calendar_repo: CalendarRepository) -> None:
        self.calendar_repo = calendar_repo

    @transactional
    async def create_calendar(
        self,
        calendar: Calendar,
        transaction: AsyncConnection,
    ) -> Calendar:
        """Persist a new calendar and return the created entity as a committed unit."""
        return await self.calendar_repo.save(calendar)

    @transactional
    async def update_calendar(
        self,
        calendar: Calendar,
        transaction: AsyncConnection,
    ) -> Calendar:
        """Persist changes to an existing calendar as a committed unit.

        The caller is responsible for loading the calendar, applying the
        requested changes, and re-running domain validation before calling this
        method.
        """
        return await self.calendar_repo.save(calendar)

    @transactional
    async def delete_calendar(
        self,
        calendar: Calendar,
        user_id: str,
        transaction: AsyncConnection,
    ) -> None:
        """Delete a calendar after verifying ownership and that it is unused.

        Args:
            calendar: The calendar to delete (already loaded by the caller).
            user_id: The authenticated user, used to verify ownership.
            transaction: Request connection; the write commits before the response.

        Raises:
            CalendarNotFoundError: The calendar has no persisted id.
            CalendarPermissionError: The user does not own the calendar.
            CalendarInUseError: The calendar is still linked to one or more journals.
        """
        # Validate the id up front so an unsaved calendar fails deterministically
        # rather than running the usage-count query with a NULL calendar_id.
        if calendar.id is None:
            raise CalendarNotFoundError("unknown")

        if calendar.user_id != user_id:
            raise CalendarPermissionError(
                "You don't have permission to delete this calendar"
            )

        # Block deletion of calendars still referenced by journals to avoid
        # orphaning calendar links.
        check_query = text(
            """
            SELECT COUNT(*) AS count
            FROM (
                SELECT journal_id
                FROM journal_calendar_info
                WHERE calendar_id = :calendar_id

                UNION

                SELECT journal_id
                FROM journal_external_event_links
                WHERE calendar_id = :calendar_id
            ) AS linked_journals
            """
        )
        result = await transaction.execute(check_query, {"calendar_id": calendar.id})
        row = result.fetchone()
        usage_count: int = row[0] if row else 0

        if usage_count > 0:
            raise CalendarInUseError(
                f"Cannot delete calendar '{calendar.name}' because it is used by "
                f"{usage_count} journal(s). "
                "Remove the calendar from all journals before deleting it.",
                usage_count,
            )

        await self.calendar_repo.delete(calendar.id)
