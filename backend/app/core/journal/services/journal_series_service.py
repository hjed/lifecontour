"""Service layer for journal series operations.

Wraps series create/update/delete and journal<->series membership in explicit
units of work so each write commits before the response is sent, keeping
transaction ownership in the service layer rather than the controller.
"""

from uuid import UUID

from core_shared.models.journals import (
    JournalNotFoundError,
    JournalSeriesNotFoundError,
    JournalValidationError,
)
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.journal_series import JournalSeries
from app.core.journal.models.repositories import (
    JournalRepository,
    JournalSeriesRepository,
)
from app.infrastructure.unit_of_work import transactional


def parse_series_id(series_id: str) -> UUID:
    """Parse a series id string, mapping malformed input to not-found.

    Shared by the REST controller and MCP tools: a syntactically invalid id
    can't refer to an existing series, so it surfaces as a 404 rather than a
    parse error.
    """
    try:
        return UUID(series_id)
    except ValueError as e:
        raise JournalSeriesNotFoundError(series_id) from e


class JournalSeriesService:
    """Service for persisting journal series as committed units of work."""

    def __init__(
        self,
        series_repo: JournalSeriesRepository,
        journal_repo: JournalRepository,
    ) -> None:
        self.series_repo = series_repo
        self.journal_repo = journal_repo

    async def get_series(self, series_id: UUID, user_id: str) -> JournalSeries:
        """Get a series by ID.

        Raises:
            JournalSeriesNotFoundError: If the series doesn't exist for the user.
        """
        series = await self.series_repo.find_by_id(series_id, user_id)
        if series is None:
            raise JournalSeriesNotFoundError(str(series_id))
        return series

    async def list_series(self, user_id: str) -> list[JournalSeries]:
        """List all series for a user, ordered by name."""
        return await self.series_repo.find_all(user_id)

    async def get_series_for_journal(
        self, journal_id: int, user_id: str
    ) -> list[JournalSeries]:
        """List all series a journal belongs to."""
        return await self.series_repo.get_series_for_journal(journal_id, user_id)

    async def get_member_journal_ids(self, series_id: UUID, user_id: str) -> list[int]:
        """Get member journal IDs for a series the user owns.

        Raises:
            JournalSeriesNotFoundError: If the series doesn't exist for the user.
        """
        await self.get_series(series_id, user_id)
        return await self.series_repo.get_member_journal_ids(series_id)

    @transactional
    async def create_series(
        self,
        series: JournalSeries,
        transaction: AsyncConnection,
    ) -> JournalSeries:
        """Persist a new journal series."""
        return await self.series_repo.save(series)

    @transactional
    async def update_series(
        self,
        series_id: UUID,
        user_id: str,
        name: str,
        description: str | None,
        transaction: AsyncConnection,
    ) -> JournalSeries:
        """Rename/re-describe a series.

        Raises:
            JournalSeriesNotFoundError: If the series doesn't exist for the user.
            JournalValidationError: If the new name is blank or too long.
        """
        series = await self.get_series(series_id, user_id)
        try:
            series.rename(name=name, description=description)
        except ValueError as e:
            raise JournalValidationError("name", str(e)) from e
        return await self.series_repo.save(series)

    @transactional
    async def delete_series(
        self,
        series_id: UUID,
        user_id: str,
        transaction: AsyncConnection,
    ) -> None:
        """Delete a series. Memberships cascade; member journals are untouched.

        Raises:
            JournalSeriesNotFoundError: If the series doesn't exist for the user.
        """
        await self.get_series(series_id, user_id)
        await self.series_repo.delete(series_id, user_id)

    @transactional
    async def add_journal_to_series(
        self,
        series_id: UUID,
        journal_id: int,
        user_id: str,
        transaction: AsyncConnection,
    ) -> None:
        """Add a journal to a series after validating ownership of both.

        Raises:
            JournalSeriesNotFoundError: If the series doesn't exist for the user.
            JournalNotFoundError: If the journal doesn't exist or belongs to
                another user (not distinguished, to avoid leaking existence).
        """
        await self.get_series(series_id, user_id)
        journal = await self.journal_repo.find_by_id(journal_id)
        if journal is None or journal.user_id != user_id:
            raise JournalNotFoundError(journal_id)
        await self.series_repo.add_member(series_id, journal_id)

    @transactional
    async def remove_journal_from_series(
        self,
        series_id: UUID,
        journal_id: int,
        user_id: str,
        transaction: AsyncConnection,
    ) -> None:
        """Remove a journal from a series (idempotent).

        Raises:
            JournalSeriesNotFoundError: If the series doesn't exist for the user.
        """
        await self.get_series(series_id, user_id)
        await self.series_repo.remove_member(series_id, journal_id)
