"""Merging one journal series into another.

The source series' members all join the destination series, and each local
day with exactly one member on each side may merge that pair into one journal
(the destination's surviving). What pairs up, and what every pair keeps, is
decided by the pure planner in ``app.core.journal.models.series_merge``; this
service loads what the planner needs and, for the merge itself, reuses
``JournalMergeService`` for every pair.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from core_shared.models.journals import (
    JournalSeriesNotFoundError,
    JournalValidationError,
)

from app.core.journal.models.journal_series import JournalSeries
from app.core.journal.models.repositories import (
    CalendarInfoRepository,
    JournalRepository,
    JournalSeriesRepository,
)
from app.core.journal.models.series_merge import (
    DayOutcome,
    SeriesMember,
    SeriesMergePlan,
    SeriesMergePolicies,
    plan_series_merge,
)
from app.core.journal.services.journal_date_resolver import JournalDateResolver


@dataclass(frozen=True)
class SeriesMergeReport:
    """A planned (preview) or performed merge, with the journals it names."""

    source_series: JournalSeries
    destination_series: JournalSeries
    days: tuple[DayOutcome, ...]
    # Every journal a day names, as it was when the plan was made.
    members: Mapping[int, SeriesMember]


class JournalSeriesMergeService:
    """Plans and performs series merges for one user."""

    def __init__(
        self,
        series_repo: JournalSeriesRepository,
        journal_repo: JournalRepository,
        calendar_info_repo: CalendarInfoRepository,
        date_resolver: JournalDateResolver,
    ) -> None:
        self.series_repo = series_repo
        self.journal_repo = journal_repo
        self.calendar_info_repo = calendar_info_repo
        self.date_resolver = date_resolver

    async def preview_merge(
        self,
        destination_series_id: UUID,
        source_series_id: UUID,
        user_id: str,
        policies: SeriesMergePolicies,
    ) -> SeriesMergeReport:
        """What merging the source series into the destination would do.

        Writes nothing.

        Raises:
            JournalValidationError: If the two series are the same.
            JournalSeriesNotFoundError: If either series doesn't exist for the
                user.
        """
        source, destination = await self._load_series(
            destination_series_id, source_series_id, user_id
        )
        plan, members = await self._plan(source, destination, user_id, policies)
        return SeriesMergeReport(
            source_series=source,
            destination_series=destination,
            days=plan.days,
            members=members,
        )

    async def _load_series(
        self, destination_series_id: UUID, source_series_id: UUID, user_id: str
    ) -> tuple[JournalSeries, JournalSeries]:
        if destination_series_id == source_series_id:
            raise JournalValidationError(
                "source_series_id", "A series cannot be merged into itself"
            )
        source = await self.series_repo.find_by_id(source_series_id, user_id)
        if source is None:
            raise JournalSeriesNotFoundError(str(source_series_id))
        destination = await self.series_repo.find_by_id(destination_series_id, user_id)
        if destination is None:
            raise JournalSeriesNotFoundError(str(destination_series_id))
        return source, destination

    async def _plan(
        self,
        source: JournalSeries,
        destination: JournalSeries,
        user_id: str,
        policies: SeriesMergePolicies,
    ) -> tuple[SeriesMergePlan, dict[int, SeriesMember]]:
        source_members = await self._members(source, user_id)
        destination_members = await self._members(destination, user_id)
        plan = plan_series_merge(
            source_members=source_members,
            destination_members=destination_members,
            tz=await self.date_resolver.timezone_for(user_id),
            policies=policies,
        )
        members = {m.journal_id: m for m in [*source_members, *destination_members]}
        return plan, members

    async def _members(self, series: JournalSeries, user_id: str) -> list[SeriesMember]:
        assert series.id is not None
        member_ids = await self.series_repo.get_member_journal_ids(series.id)
        journals = await self.journal_repo.find_by_ids_for_user(user_id, member_ids)
        return [
            SeriesMember(
                journal=journal,
                calendar_info=await self.calendar_info_repo.find_by_journal_id(
                    journal.id
                ),
            )
            for journal in journals
            if journal.id is not None
        ]
