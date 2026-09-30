"""Merging one journal series into another.

The source series' members all join the destination series, and each local
day with exactly one member on each side may merge that pair into one journal
(the destination's surviving). What pairs up, and what every pair keeps, is
decided by the pure planner in ``app.core.journal.models.series_merge``; this
service loads what the planner needs and, for the merge itself, reuses
``JournalMergeService`` for every pair.
"""

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

import structlog
from core_shared.models.history import Provenance
from core_shared.models.journals import (
    JournalSeriesNotFoundError,
    JournalValidationError,
)
from core_shared.models.journals.exceptions import (
    JournalDomainError,
    JournalMergeConflictError,
)
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.journal_series import JournalSeries
from app.core.journal.models.repositories import (
    CalendarInfoRepository,
    JournalRepository,
    JournalSeriesRepository,
)
from app.core.journal.models.series_merge import (
    DayOutcome,
    SeriesDayOutcomeKind,
    SeriesMember,
    SeriesMergePair,
    SeriesMergePlan,
    SeriesMergePolicies,
    overrides_for_pair,
    plan_series_merge,
)
from app.core.journal.services.journal_date_resolver import JournalDateResolver
from app.core.journal.services.journal_merge_service import JournalMergeService
from app.infrastructure.unit_of_work import savepoint, transactional

logger = structlog.get_logger(__name__)


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
        journal_merge_service: JournalMergeService,
    ) -> None:
        self.series_repo = series_repo
        self.journal_repo = journal_repo
        self.calendar_info_repo = calendar_info_repo
        self.date_resolver = date_resolver
        self.journal_merge_service = journal_merge_service

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

    @transactional
    async def merge_series(
        self,
        destination_series_id: UUID,
        source_series_id: UUID,
        user_id: str,
        policies: SeriesMergePolicies,
        pairs: Sequence[SeriesMergePair],
        transaction: AsyncConnection,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> SeriesMergeReport:
        """Merge the source series into the destination series.

        ``pairs`` are the candidates the user confirmed from a preview; any
        other candidate is left unmerged (``excluded``). The plan is made again
        from current data and **every** confirmed pair must still be a
        candidate, or nothing is written: a preview that no longer matches the
        data is not the merge the user agreed to.

        Each pair merges in its own savepoint, so a pair the single-journal
        merge refuses is reported as ``failed`` and the rest carry on. Then
        the source's recurrences are aliased to the destination (locking their
        keys against a concurrent sync), every remaining source member joins
        the destination, and the source series is deleted.

        Raises:
            JournalValidationError: If the two series are the same.
            JournalSeriesNotFoundError: If either series doesn't exist for the
                user.
            JournalMergeConflictError: If a confirmed pair is no longer a
                merge candidate.
        """
        source_series, destination_series = await self._load_series(
            destination_series_id, source_series_id, user_id
        )
        plan, members = await self._plan(
            source_series, destination_series, user_id, policies
        )
        confirmed = set(pairs)
        if stale := confirmed - set(plan.candidates):
            raise JournalMergeConflictError(
                "The series changed since the merge was previewed: "
                f"{len(stale)} confirmed pair(s) can no longer be merged"
            )

        # Ascending source id, so concurrent merges lock journals in one order.
        merged_kinds = {
            pair: await self._merge_pair(
                pair, members, policies, transaction, source, changed_by
            )
            for pair in sorted(confirmed, key=lambda p: p.source_journal_id)
        }
        days = tuple(_performed(day, confirmed, merged_kinds) for day in plan.days)

        assert source_series.id is not None and destination_series.id is not None
        # Alias first: it locks every recurrence key the source answers for,
        # so no sync can add a journal to the source between the move and the
        # delete, where the delete would drop it.
        await self.series_repo.alias_recurrences(source_series, destination_series.id)
        await self.series_repo.move_members(source_series.id, destination_series.id)
        await self.series_repo.delete(source_series.id, user_id)
        logger.info(
            "Journal series merged",
            source_series_id=str(source_series.id),
            destination_series_id=str(destination_series.id),
            merged_pairs=sum(
                kind is SeriesDayOutcomeKind.MERGED for kind in merged_kinds.values()
            ),
        )
        return SeriesMergeReport(
            source_series=source_series,
            destination_series=destination_series,
            days=days,
            members=members,
        )

    async def _merge_pair(
        self,
        pair: SeriesMergePair,
        members: Mapping[int, SeriesMember],
        policies: SeriesMergePolicies,
        transaction: AsyncConnection,
        source: Provenance,
        changed_by: str,
    ) -> SeriesDayOutcomeKind:
        try:
            async with savepoint(transaction):
                await self.journal_merge_service.merge_journals(
                    target_id=pair.destination_journal_id,
                    source_id=pair.source_journal_id,
                    transaction=transaction,
                    overrides=overrides_for_pair(
                        members[pair.source_journal_id],
                        members[pair.destination_journal_id],
                        policies,
                    ),
                    source=source,
                    changed_by=changed_by,
                )
        except JournalDomainError as e:
            logger.warning(
                "Series merge pair failed",
                source_journal_id=pair.source_journal_id,
                destination_journal_id=pair.destination_journal_id,
                error=str(e),
            )
            return SeriesDayOutcomeKind.FAILED
        return SeriesDayOutcomeKind.MERGED

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


def _performed(
    day: DayOutcome,
    confirmed: set[SeriesMergePair],
    merged_kinds: Mapping[SeriesMergePair, SeriesDayOutcomeKind],
) -> DayOutcome:
    """A planned day as the merge left it."""
    if day.kind is not SeriesDayOutcomeKind.CANDIDATE or day.pair is None:
        return day
    if day.pair not in confirmed:
        return dataclasses.replace(day, kind=SeriesDayOutcomeKind.EXCLUDED)
    return dataclasses.replace(day, kind=merged_kinds[day.pair])
