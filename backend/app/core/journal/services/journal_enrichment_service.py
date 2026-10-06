"""Everything shown alongside a journal, read once for every surface.

REST and MCP both report a journal with its types, type-specific data,
contacts, tags, series and calendars. This service reads all of it, so the two
give the same answer. Each surface then only renders the result in its own
wire format (REST's JSON:API schemas, MCP's assistant-facing dicts). External
links are read by :class:`JournalExternalLinkService`, for the same reason.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from core_shared.models.journals import JournalType

from app.core.journal.services.journal_type_data_reader import TYPE_DATA_READERS

if TYPE_CHECKING:
    from core_shared.models.journals import (
        AbseilPitch,
        Calendar,
        JournalContactRelationship,
    )

    from app.core.contacts.models.repositories import ContactRepository
    from app.core.journal.adapters.sql.album_sync_read_repository import (
        AlbumSyncReadRepository,
    )
    from app.core.journal.models.journal_series import JournalSeries
    from app.core.journal.models.journal_tag import JournalTag
    from app.core.journal.models.repositories import (
        AbseilingDataRepository,
        AbseilPitchRepository,
        BushwalkingDataRepository,
        CalendarInfoRepository,
        CalendarRepository,
        CanoeingDataRepository,
        CanyoningDataRepository,
        CavingDataRepository,
        ClimbingDataRepository,
        CrossCountrySkiingDataRepository,
        DivingDataRepository,
        DownhillSkiingDataRepository,
        FitnessDataRepository,
        GearMaintenanceDataRepository,
        GearUsageDataRepository,
        JoggingDataRepository,
        JournalContactRelationshipRepository,
        JournalRepository,
        JournalSeriesRepository,
        JournalTagRepository,
        KayakingDataRepository,
        MoodDataRepository,
        OutdoorActivityDataRepository,
        OutdoorPlanningDataRepository,
        OutdoorTrainingDataRepository,
        PlanDataRepository,
        SnorkellingDataRepository,
        TravelDataRepository,
    )


def contact_display_name(
    first_name: str | None, last_name: str | None, contact_id: int
) -> str:
    """A contact's name as a journal or task shows it, skipping missing parts."""
    parts = [part for part in (first_name, last_name) if part]
    return " ".join(parts) if parts else f"Contact {contact_id}"


@dataclass(frozen=True)
class JournalTypeDataRepositories:
    """The repository holding each type's row, named by its ``repo_attr``.

    ``TYPE_DATA_READERS`` finds each type's repository here by attribute name;
    ``tests/unit/journal/test_journal_type_coverage.py`` keeps the two aligned.
    """

    calendar_info_repo: CalendarInfoRepository
    mood_data_repo: MoodDataRepository
    plan_data_repo: PlanDataRepository
    travel_data_repo: TravelDataRepository
    photo_album_data_repo: AlbumSyncReadRepository
    fitness_data_repo: FitnessDataRepository
    outdoor_activity_data_repo: OutdoorActivityDataRepository
    bushwalking_data_repo: BushwalkingDataRepository
    jogging_data_repo: JoggingDataRepository
    abseiling_data_repo: AbseilingDataRepository
    caving_data_repo: CavingDataRepository
    canyoning_data_repo: CanyoningDataRepository
    climbing_data_repo: ClimbingDataRepository
    kayaking_data_repo: KayakingDataRepository
    cross_country_skiing_data_repo: CrossCountrySkiingDataRepository
    canoeing_data_repo: CanoeingDataRepository
    snorkelling_data_repo: SnorkellingDataRepository
    diving_data_repo: DivingDataRepository
    downhill_skiing_data_repo: DownhillSkiingDataRepository
    outdoor_planning_data_repo: OutdoorPlanningDataRepository
    outdoor_training_data_repo: OutdoorTrainingDataRepository
    gear_maintenance_data_repo: GearMaintenanceDataRepository
    gear_usage_data_repo: GearUsageDataRepository
    # Not a type of its own: the pitches of an ABSEILING_TRIP.
    abseil_pitch_repo: AbseilPitchRepository


@dataclass(frozen=True)
class EnrichedContact:
    """A journal's relationship to a contact, with the contact's name."""

    relationship: JournalContactRelationship
    name: str
    first_name: str | None
    last_name: str | None
    photo_url: str | None

    @property
    def contact_id(self) -> int:
        return self.relationship.contact_id


def _types_from_rows(present: Sequence[JournalType] | set[JournalType]) -> list[str]:
    """Type values in ``TYPE_DATA_READERS`` order; NOTE when there are none."""
    types = [t.value for t in TYPE_DATA_READERS if t in present]
    return types or [JournalType.NOTE.value]


@dataclass(frozen=True)
class JournalEnrichment:
    """What every surface shows alongside a journal.

    ``type_rows`` holds each present type's domain row (the photo album's is
    the album display dict) in ``TYPE_DATA_READERS`` order; NOTE has no row.
    ``calendars`` is every calendar an EVENT lives in, display calendar first,
    and is empty for a journal that is not an event.
    """

    type_rows: Mapping[JournalType, Any]
    contacts: list[EnrichedContact]
    tags: list[JournalTag]
    series: list[JournalSeries]
    calendars: list[Calendar]
    abseil_pitches: list[AbseilPitch] = field(default_factory=list)

    @property
    def types(self) -> list[str]:
        return _types_from_rows(set(self.type_rows))


class JournalEnrichmentService:
    """Reads a journal's enrichment, and the types of many journals at once."""

    def __init__(
        self,
        type_data_repos: JournalTypeDataRepositories,
        journal_repo: JournalRepository,
        contact_relationship_repo: JournalContactRelationshipRepository,
        contact_repo: ContactRepository,
        tag_repo: JournalTagRepository,
        series_repo: JournalSeriesRepository,
        calendar_repo: CalendarRepository,
    ) -> None:
        self.type_data_repos = type_data_repos
        self.journal_repo = journal_repo
        self.contact_relationship_repo = contact_relationship_repo
        self.contact_repo = contact_repo
        self.tag_repo = tag_repo
        self.series_repo = series_repo
        self.calendar_repo = calendar_repo

    async def enrich(self, journal_id: int, user_id: str) -> JournalEnrichment:
        """Everything shown alongside one journal.

        ``user_id`` scopes the series: only the owner's series are reported.
        """
        type_rows = await self._read_type_rows(journal_id)
        abseil_pitches = (
            await self.type_data_repos.abseil_pitch_repo.find_by_journal_id(journal_id)
            if JournalType.ABSEILING_TRIP in type_rows
            else []
        )
        # One event can be held by several calendars — where one calendar
        # invites another the sync records a single journal linked to each —
        # while it is still displayed in exactly one, which leads the list.
        calendars = (
            await self.calendar_repo.find_linked_to_journal(journal_id)
            if JournalType.EVENT in type_rows
            else []
        )
        return JournalEnrichment(
            type_rows=type_rows,
            abseil_pitches=abseil_pitches,
            contacts=await self._read_contacts(journal_id),
            tags=await self.tag_repo.get_tags_for_journal(journal_id),
            series=await self.series_repo.get_series_for_journal(journal_id, user_id),
            calendars=calendars,
        )

    async def types_for(self, journal_ids: Sequence[int]) -> dict[int, list[str]]:
        """Each journal's types, in one query, as :attr:`JournalEnrichment.types`.

        An id that names no journal is omitted.
        """
        rows = await self.journal_repo.get_typed_rows_batch(journal_ids)
        return {
            journal_id: _types_from_rows(present)
            for journal_id, present in rows.items()
        }

    async def _read_type_rows(self, journal_id: int) -> dict[JournalType, Any]:
        type_rows: dict[JournalType, Any] = {}
        for journal_type, reader in TYPE_DATA_READERS.items():
            repo = getattr(self.type_data_repos, reader.repo_attr)
            row = await repo.find_by_journal_id(journal_id)
            if row:
                type_rows[journal_type] = row
        return type_rows

    async def _read_contacts(self, journal_id: int) -> list[EnrichedContact]:
        relationships = await self.contact_relationship_repo.get_by_journal(journal_id)
        if not relationships:
            return []
        names = await self.contact_repo.find_names_by_ids(
            list(dict.fromkeys(rel.contact_id for rel in relationships))
        )
        contacts: list[EnrichedContact] = []
        for rel in relationships:
            # The relationship's foreign key cascades on contact delete, so
            # every contact is found; the fallback keeps the type total.
            first_name, last_name, photo_url = names.get(
                rel.contact_id, (None, None, None)
            )
            contacts.append(
                EnrichedContact(
                    relationship=rel,
                    name=contact_display_name(first_name, last_name, rel.contact_id),
                    first_name=first_name,
                    last_name=last_name,
                    photo_url=photo_url,
                )
            )
        return contacts
