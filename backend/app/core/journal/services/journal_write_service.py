"""Composite write service for journals.

Owns the multi-write orchestration that a single journal create/update request
performs (the journal row, its types, the per-type data rows, contact
relationships and the type-data updates). Each public method is decorated with
:func:`app.infrastructure.unit_of_work.transactional` so the *whole* composite
operation commits as ONE unit of work before the HTTP response is sent
(issue #945).

Because ``@transactional`` / ``unit_of_work`` are re-entrant, the underlying
service write methods (``JournalService``, ``JournalContactService``) may also
be decorated: when called from inside a composite method they join the outer
unit of work and only the outermost commit fires, so a mid-request failure
rolls the entire journal write back atomically.

Per-item batch operations (contact-relationship bulk processing) use
:func:`app.infrastructure.unit_of_work.savepoint` so one bad item rolls back
just its SAVEPOINT and the loop continues.
"""

from collections.abc import Callable, Sequence
from typing import Any, NamedTuple

import structlog
from core_shared.models.history import Provenance
from core_shared.models.journals import (
    Journal,
    JournalContactRelationship,
    JournalContactRelationshipType,
    JournalType,
    JournalValidationError,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.album_sync_read_repository import (
    AlbumSyncReadRepository,
)
from app.core.journal.models.journal_tag import JournalTag
from app.core.journal.models.repositories import (
    AbseilingDataRepository,
    AbseilPitchRepository,
    BushwalkingDataRepository,
    CalendarInfoRepository,
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
from app.core.journal.services import journal_type_data_helpers as helpers
from app.core.journal.services.journal_contact_service import JournalContactService
from app.core.journal.services.journal_service import JournalService
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.unit_of_work import savepoint, transactional

logger = structlog.get_logger()


def to_history_value(value: Any) -> Any:
    """Coerce a type-data field value to a JSON-safe scalar for history/events.

    ``changed_fields`` travels through the outbox and Redis as JSON, so non-JSON
    types on the type-data rows (enums, UUIDs, dates/times) must be reduced to a
    primitive. Scalars and ``None`` pass through unchanged; enums use their value;
    anything date/time-like is ISO-formatted; everything else is stringified.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    enum_value = getattr(value, "value", None)
    if enum_value is not None and not callable(enum_value):
        return to_history_value(enum_value)
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    return str(value)


def diff_tracked_fields(
    before: Any, after: Any, fields: tuple[str, ...]
) -> dict[str, tuple[Any, Any]]:
    """Diff ``fields`` between two type-data rows into ``{field: (old, new)}`` pairs.

    Either row may be ``None`` (e.g. a row created during the update), in which
    case its side of every field is ``None``. Only fields that actually changed
    are returned, so an update that changes nothing yields ``{}`` (no history).
    """
    changed: dict[str, tuple[Any, Any]] = {}
    for field in fields:
        old = getattr(before, field, None) if before is not None else None
        new = getattr(after, field, None) if after is not None else None
        if old != new:
            changed[field] = (to_history_value(old), to_history_value(new))
    return changed


def diff_collection_rows(
    before_rows: Sequence[Any],
    after_rows: Sequence[Any],
    *,
    key: Callable[[Any], str],
    prefix: str,
    fields: tuple[str, ...],
) -> dict[str, tuple[Any, Any]]:
    """Per-row diff of a nested child collection into prefixed history pairs.

    Each row is identified by a stable natural ``key`` (e.g. a document id or a
    pitch number) so edits to the same logical row read as field changes rather
    than churn. For every changed field of every row the result carries a
    ``{prefix}:{key}:{field} -> (old, new)`` pair, mirroring the route/gear
    ``route:<id>:<field>`` projection convention:

    - a row only in ``after``  -> ``(None, new)`` pairs (created)
    - a row only in ``before`` -> ``(old, None)`` pairs (deleted)
    - a row in both            -> ``(old, new)`` pairs for changed fields only

    Rows whose tracked fields are all unchanged contribute nothing, so a no-op
    update yields ``{}`` (no history). Short surrogate keys keep the qualified
    ``field_name`` within the history column's length.
    """
    before_by = {key(r): r for r in before_rows}
    after_by = {key(r): r for r in after_rows}
    changed: dict[str, tuple[Any, Any]] = {}
    for row_key in sorted(before_by.keys() | after_by.keys()):
        before_row = before_by.get(row_key)
        after_row = after_by.get(row_key)
        for field in fields:
            old = getattr(before_row, field, None) if before_row is not None else None
            new = getattr(after_row, field, None) if after_row is not None else None
            if old != new:
                changed[f"{prefix}:{row_key}:{field}"] = (
                    to_history_value(old),
                    to_history_value(new),
                )
    return changed


# Tracked fields per editable single-row type, used to compute type-data history.
# Every editable journal type with an `update_*_type_data` helper is registered
# here so its type-data edits appear in history. The field names are kept exactly
# in sync with the type-data dataclasses by
# `tests/unit/journal/test_type_data_history_coverage.py`, which fails if a new
# type or field is added without a coverage decision (tracked or excluded). Types
# that are intentionally excluded (and why): PLAN/TRAVEL hold nested child
# collections and PHOTO_ALBUM is Immich-synced (integration/Phase 4); SNORKELLING/
# DIVING/DOWNHILL_SKIING validate existence only (no editable fields); NOTE has no
# type data.
_TYPE_DATA_TRACKED_FIELDS: dict[JournalType, tuple[str, ...]] = {
    JournalType.EVENT: (
        "calendar_id",
        "is_all_day",
        "start_time",
        "end_time",
        "location",
        "timezone",
        "description",
        "sync_invitees",
        "private_description",
        "event_state",
    ),
    JournalType.MOOD_RATING: ("mood_value", "mood_label", "energy_level"),
    JournalType.FITNESS: (
        "heart_rate_avg",
        "heart_rate_max",
        "distance",
        "elevation_gain",
        "elevation_loss",
        "duration",
        "calories",
        "strava_activity_id",
    ),
    JournalType.OUTDOOR_ACTIVITY: (
        "weather_conditions",
        "role",
        "in_leadership_role",
        "participant_notes",
    ),
    JournalType.BUSHWALKING: ("track_grading",),
    JournalType.JOGGING: ("pace",),
    # Abseiling tracks its trip-level scalars; per-pitch (AbseilPitch) history is
    # a nested collection deferred to Phase 4.
    JournalType.ABSEILING_TRIP: (
        # Consolidated template reference for all abseiling-derived journals
        # (ITER16-001); tracked here since it is co-located with the pitch data.
        "template_id",
        "number_of_abseils",
        "total_length",
        "number_of_setups",
        "number_of_rescues",
    ),
    JournalType.CANYONING: (
        "french_grade",
        "water_guage_name",
        "water_guage_level",
        "is_vertical",
        "is_night_canyon",
        "is_white_water",
    ),
    JournalType.CAVING: ("is_vertical", "is_horizontal"),
    JournalType.CANOEING: ("water_type",),
    JournalType.CLIMBING: (
        "climbing_type",
        "grade",
        "length",
        "indoor",
    ),
    JournalType.KAYAKING: ("water_type", "is_white_water", "rapids_grade"),
    JournalType.CROSS_COUNTRY_SKIING: ("snow_conditions",),
    JournalType.OUTDOOR_PLANNING: ("topics", "activity_types"),
    JournalType.OUTDOOR_TRAINING: ("focus_areas",),
    JournalType.GEAR_MAINTENANCE: (
        "gear_item_id",
        "maintenance_type",
        "activity_types",
        "retirement_reason",
    ),
    JournalType.GEAR_USAGE: (
        "gear_item_id",
        "checkout_date",
        "checkin_date",
    ),
}


class _CollectionSpec(NamedTuple):
    """How a nested child collection of a journal type is diffed into history.

    ``field_name`` is the collection attribute on the type-data model (kept in
    sync with the model by ``test_type_data_history_coverage.py``); ``prefix`` +
    a short, stable per-row ``key`` form the ``{prefix}:{key}:{field}`` history
    field names (mirroring the route/gear convention); ``fields`` are the per-row
    fields tracked for history.
    """

    field_name: str
    prefix: str
    key: Callable[[Any], str]
    fields: tuple[str, ...]


# Nested child collections whose per-row changes are projected into journal
# history (ITER12-002 Phase 4). Each collection is snapshotted before/after the
# type-data update and diffed by ``diff_collection_rows``. TRAVEL's collections
# are intentionally absent: they have no write path yet (deferred).
_TYPE_DATA_COLLECTIONS: dict[JournalType, tuple[_CollectionSpec, ...]] = {
    JournalType.PLAN: (
        _CollectionSpec(
            field_name="documents",
            prefix="plan:doc",
            key=lambda d: str(d.id),
            fields=("url", "title", "description", "order"),
        ),
    ),
    JournalType.ABSEILING_TRIP: (
        _CollectionSpec(
            field_name="pitches",
            prefix="abseil:pitch",
            key=lambda p: str(p.pitch_number),
            fields=(
                "height",
                "anchor_location",
                "anchor_type",
                "did_rescue",
                "did_setup",
                "notes",
            ),
        ),
    ),
}


class JournalWriteService:
    """Service orchestrating composite journal writes as a single unit of work."""

    def __init__(
        self,
        journal_service: JournalService,
        journal_contact_service: JournalContactService,
        calendar_info_repo: CalendarInfoRepository,
        photo_album_data_repo: AlbumSyncReadRepository,
        mood_data_repo: MoodDataRepository,
        plan_data_repo: PlanDataRepository,
        travel_data_repo: TravelDataRepository,
        fitness_data_repo: FitnessDataRepository,
        outdoor_activity_data_repo: OutdoorActivityDataRepository,
        bushwalking_data_repo: BushwalkingDataRepository,
        jogging_data_repo: JoggingDataRepository,
        abseiling_data_repo: AbseilingDataRepository,
        abseil_pitch_repo: AbseilPitchRepository,
        canyoning_data_repo: CanyoningDataRepository,
        caving_data_repo: CavingDataRepository,
        canoeing_data_repo: CanoeingDataRepository,
        climbing_data_repo: ClimbingDataRepository,
        kayaking_data_repo: KayakingDataRepository,
        skiing_data_repo: CrossCountrySkiingDataRepository,
        snorkelling_data_repo: SnorkellingDataRepository,
        diving_data_repo: DivingDataRepository,
        downhill_skiing_data_repo: DownhillSkiingDataRepository,
        outdoor_planning_data_repo: OutdoorPlanningDataRepository,
        outdoor_training_data_repo: OutdoorTrainingDataRepository,
        gear_maintenance_data_repo: GearMaintenanceDataRepository,
        gear_usage_data_repo: GearUsageDataRepository,
        tag_repo: JournalTagRepository,
        event_publisher: OutboxEventPublisher,
    ) -> None:
        self.journal_service = journal_service
        self.journal_contact_service = journal_contact_service
        self.calendar_info_repo = calendar_info_repo
        self.photo_album_data_repo = photo_album_data_repo
        self.mood_data_repo = mood_data_repo
        self.plan_data_repo = plan_data_repo
        self.travel_data_repo = travel_data_repo
        self.fitness_data_repo = fitness_data_repo
        self.outdoor_activity_data_repo = outdoor_activity_data_repo
        self.bushwalking_data_repo = bushwalking_data_repo
        self.jogging_data_repo = jogging_data_repo
        self.abseiling_data_repo = abseiling_data_repo
        self.abseil_pitch_repo = abseil_pitch_repo
        self.canyoning_data_repo = canyoning_data_repo
        self.caving_data_repo = caving_data_repo
        self.canoeing_data_repo = canoeing_data_repo
        self.climbing_data_repo = climbing_data_repo
        self.kayaking_data_repo = kayaking_data_repo
        self.skiing_data_repo = skiing_data_repo
        self.snorkelling_data_repo = snorkelling_data_repo
        self.diving_data_repo = diving_data_repo
        self.downhill_skiing_data_repo = downhill_skiing_data_repo
        self.outdoor_planning_data_repo = outdoor_planning_data_repo
        self.outdoor_training_data_repo = outdoor_training_data_repo
        self.gear_maintenance_data_repo = gear_maintenance_data_repo
        self.gear_usage_data_repo = gear_usage_data_repo
        self.tag_repo = tag_repo
        self.event_publisher = event_publisher

    # ------------------------------------------------------------------ #
    # Composite write operations                                          #
    # ------------------------------------------------------------------ #

    @transactional
    async def create_journal(
        self,
        journal: Journal,
        types: list[str] | None,
        type_data: dict[str, Any] | None,
        relationships: list[dict[str, Any]] | None,
        transaction: AsyncConnection,
        *,
        tags: list[str] | None = None,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
    ) -> Journal:
        """Create a journal with its types, type-data, contacts and tags.

        The entire operation runs inside a single unit of work, so a failure in
        any step rolls back the whole journal. ``tags`` is keyword-only and
        defaults to ``None`` so existing positional callers (REST, which manages
        tags via separate endpoints) are unaffected.
        """
        created_journal = await self.journal_service.create_journal(
            journal, transaction, changed_by=changed_by, source=source
        )

        if created_journal.id is None:
            raise JournalValidationError(
                "id", "Journal ID is required after save operation"
            )
        journal_id = created_journal.id

        if types:
            await self._process_journal_types(
                journal_id, types, transaction, changed_by=changed_by, source=source
            )

        if type_data:
            await self._process_journal_type_data(journal_id, type_data, transaction)

        if relationships:
            await self._process_journal_contact_relationships(
                journal_id, relationships, transaction
            )

        if tags:
            await self._process_journal_tags(journal_id, tags, transaction)

        return created_journal

    @transactional
    async def update_journal(
        self,
        journal: Journal,
        transaction: AsyncConnection,
        *,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
    ) -> Journal:
        """Update a journal's core fields as a committed unit of work.

        ``changed_fields`` are computed inside :class:`JournalService` by diffing
        the persisted journal against ``journal``; callers pass the merged journal.
        """
        return await self.journal_service.update_journal(
            journal,
            transaction,
            changed_by=changed_by,
            source=source,
        )

    @transactional
    async def update_journal_composite(
        self,
        journal: Journal,
        transaction: AsyncConnection,
        *,
        types: list[str] | None = None,
        type_data: dict[str, Any] | None = None,
        relationships: list[dict[str, Any]] | None = None,
        tags: list[str] | None = None,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
    ) -> Journal:
        """Update a journal's core fields and optionally replace its associations.

        Tri-state per association: ``None`` leaves it untouched, while any list
        (including ``[]``) REPLACES the current set. This is the composite behind
        the MCP ``update_journal_entry`` tool; REST uses the thinner
        :meth:`update_journal`. The whole operation is one unit of work.
        """
        updated = await self.journal_service.update_journal(
            journal, transaction, changed_by=changed_by, source=source
        )
        if updated.id is None:
            raise JournalValidationError("id", "Journal ID is required after update")
        journal_id = updated.id

        if types is not None:
            await self._replace_journal_types(
                journal_id,
                types,
                type_data,
                transaction,
                changed_by=changed_by,
                source=source,
            )
        elif type_data is not None:
            # Editing type-data on an existing journal (no type change): route each
            # type through update_type_data so the edit produces field-level history
            # with the caller's provenance — MCP parity with the REST PUT
            # /types/{type}/data path — including EVENT calendar sync and PLAN/ABSEIL
            # per-row history (ITER12-002 Phase 4).
            for type_name, attrs in type_data.items():
                try:
                    jtype = JournalType[type_name.upper()]
                except KeyError as exc:
                    raise JournalValidationError(
                        "type_data", f"Unknown journal type: {type_name}"
                    ) from exc
                await self.update_type_data(
                    journal_id,
                    jtype,
                    attrs,
                    transaction,
                    changed_by=changed_by,
                    source=source,
                )

        if relationships is not None:
            await self._replace_contact_relationships(
                journal_id, relationships, transaction
            )

        if tags is not None:
            await self._replace_journal_tags(journal_id, tags, transaction)

        return updated

    @transactional
    async def delete_journal(
        self,
        journal_id: int,
        transaction: AsyncConnection,
        *,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
    ) -> None:
        """Delete a journal as a committed unit of work."""
        await self.journal_service.delete_journal(
            journal_id, transaction, changed_by=changed_by, source=source
        )

    @transactional
    async def add_type(
        self,
        journal_id: int,
        journal_type: JournalType,
        type_data: dict[str, Any] | None,
        transaction: AsyncConnection,
        *,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
    ) -> list[JournalType]:
        """Add a type (with dependencies), its default rows, and optional data."""
        added_types = await self.journal_service.add_type_to_journal(
            journal_id,
            journal_type,
            transaction,
            changed_by=changed_by,
            source=source,
        )

        for added_type in added_types:
            await self._create_type_specific_data(added_type, journal_id)

        if type_data:
            wrapped_type_data = {journal_type.value: type_data}
            await self._process_journal_type_data(
                journal_id, wrapped_type_data, transaction
            )

        return added_types

    @transactional
    async def remove_type(
        self,
        journal_id: int,
        journal_type: JournalType,
        transaction: AsyncConnection,
        *,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
    ) -> None:
        """Remove a type and delete its type-specific data row."""
        await self.journal_service.remove_type_from_journal(
            journal_id,
            journal_type,
            transaction,
            changed_by=changed_by,
            source=source,
        )
        await self._delete_type_specific_data(journal_type, journal_id)

    @transactional
    async def update_type_data(
        self,
        journal_id: int,
        journal_type: JournalType,
        attrs: dict[str, Any],
        transaction: AsyncConnection,
        *,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
    ) -> None:
        """Update the type-specific data for a single existing journal type.

        Snapshots the tracked fields of the type-data row before and after the
        update, diffs them into ``{field: (old, new)}`` pairs, and publishes a
        single ``JournalUpdated`` event so the change is projected into journal
        history. EVENT additionally always carries the ``calendar_info`` marker so
        the Google Calendar outbound worker re-syncs (the history projection skips
        the non-pair marker and records only the real field diffs).
        """
        from app.core.journal.models.events import JournalUpdated

        repo = self._type_data_repo(journal_type)
        tracked = _TYPE_DATA_TRACKED_FIELDS.get(journal_type, ())
        before = (
            await repo.find_by_journal_id(journal_id)
            if repo is not None and tracked
            else None
        )
        # Snapshot nested child collections (PLAN documents, ABSEIL pitches) before
        # the update so per-row changes can be diffed into history (Phase 4).
        collections = _TYPE_DATA_COLLECTIONS.get(journal_type, ())
        before_collections = {
            spec.field_name: await self._load_collection_rows(
                journal_type, spec.field_name, journal_id
            )
            for spec in collections
        }

        await self._apply_type_data_update(journal_id, journal_type, attrs)

        after = (
            await repo.find_by_journal_id(journal_id)
            if repo is not None and tracked
            else None
        )
        changed_fields: dict[str, Any] = diff_tracked_fields(before, after, tracked)

        for spec in collections:
            after_rows = await self._load_collection_rows(
                journal_type, spec.field_name, journal_id
            )
            changed_fields.update(
                diff_collection_rows(
                    before_collections[spec.field_name],
                    after_rows,
                    key=spec.key,
                    prefix=spec.prefix,
                    fields=spec.fields,
                )
            )

        if journal_type == JournalType.EVENT:
            # The marker (a non-pair signal) triggers calendar sync regardless of
            # whether any tracked field changed; the projection ignores it.
            changed_fields = {**changed_fields, "calendar_info": True}

        if changed_fields:
            event = JournalUpdated(
                journal_id=journal_id,
                changed_fields=changed_fields,
                source=source,
                changed_by=changed_by,
                transaction=transaction,
            )
            await self.event_publisher.publish(event)

    def _type_data_repo(self, journal_type: JournalType) -> Any:
        """Return the single-row repo whose tracked fields back ``journal_type``."""
        return {
            JournalType.EVENT: self.calendar_info_repo,
            JournalType.MOOD_RATING: self.mood_data_repo,
            JournalType.FITNESS: self.fitness_data_repo,
            JournalType.OUTDOOR_ACTIVITY: self.outdoor_activity_data_repo,
            JournalType.BUSHWALKING: self.bushwalking_data_repo,
            JournalType.JOGGING: self.jogging_data_repo,
            JournalType.ABSEILING_TRIP: self.abseiling_data_repo,
            JournalType.CANYONING: self.canyoning_data_repo,
            JournalType.CAVING: self.caving_data_repo,
            JournalType.CANOEING: self.canoeing_data_repo,
            JournalType.CLIMBING: self.climbing_data_repo,
            JournalType.KAYAKING: self.kayaking_data_repo,
            JournalType.CROSS_COUNTRY_SKIING: self.skiing_data_repo,
            JournalType.OUTDOOR_PLANNING: self.outdoor_planning_data_repo,
            JournalType.OUTDOOR_TRAINING: self.outdoor_training_data_repo,
            JournalType.GEAR_MAINTENANCE: self.gear_maintenance_data_repo,
            JournalType.GEAR_USAGE: self.gear_usage_data_repo,
        }.get(journal_type)

    async def _load_collection_rows(
        self, journal_type: JournalType, field_name: str, journal_id: int
    ) -> list[Any]:
        """Load the rows of a nested child collection for history diffing."""
        if journal_type == JournalType.PLAN and field_name == "documents":
            return list(await self.plan_data_repo.get_documents(journal_id))
        if journal_type == JournalType.ABSEILING_TRIP and field_name == "pitches":
            return list(await self.abseil_pitch_repo.find_by_journal_id(journal_id))
        return []

    async def _apply_type_data_update(
        self,
        journal_id: int,
        journal_type: JournalType,
        attrs: dict[str, Any],
    ) -> None:
        """Dispatch the type-specific data write (no event publishing)."""
        journal_type_str = journal_type.value

        if journal_type == JournalType.EVENT:
            await helpers.update_event_type_data(
                journal_id, journal_type_str, attrs, self.calendar_info_repo
            )
        elif journal_type == JournalType.MOOD_RATING:
            await helpers.update_mood_type_data(
                journal_id, journal_type_str, attrs, self.mood_data_repo
            )
        elif journal_type == JournalType.PHOTO_ALBUM:
            # PHOTO_ALBUM data is managed by Immich album sync and cannot be
            # edited through this API.
            raise JournalValidationError(
                "journal_type",
                "PHOTO_ALBUM data is managed by Immich sync and cannot be edited",
            )
        elif journal_type == JournalType.FITNESS:
            await helpers.update_fitness_type_data(
                journal_id, journal_type_str, attrs, self.fitness_data_repo
            )
        elif journal_type == JournalType.OUTDOOR_ACTIVITY:
            await helpers.update_outdoor_activity_type_data(
                journal_id, journal_type_str, attrs, self.outdoor_activity_data_repo
            )
        elif journal_type == JournalType.BUSHWALKING:
            await helpers.update_bushwalking_type_data(
                journal_id, journal_type_str, attrs, self.bushwalking_data_repo
            )
        elif journal_type == JournalType.JOGGING:
            await helpers.update_jogging_type_data(
                journal_id, journal_type_str, attrs, self.jogging_data_repo
            )
        elif journal_type == JournalType.ABSEILING_TRIP:
            await helpers.update_abseiling_type_data(
                journal_id,
                journal_type_str,
                attrs,
                self.abseiling_data_repo,
                self.abseil_pitch_repo,
            )
        elif journal_type == JournalType.CANYONING:
            await helpers.update_canyoning_type_data(
                journal_id, journal_type_str, attrs, self.canyoning_data_repo
            )
        elif journal_type == JournalType.CAVING:
            await helpers.update_caving_type_data(
                journal_id, journal_type_str, attrs, self.caving_data_repo
            )
        elif journal_type == JournalType.CANOEING:
            await helpers.update_canoeing_type_data(
                journal_id, journal_type_str, attrs, self.canoeing_data_repo
            )
        elif journal_type == JournalType.CLIMBING:
            await helpers.update_climbing_type_data(
                journal_id, journal_type_str, attrs, self.climbing_data_repo
            )
        elif journal_type == JournalType.KAYAKING:
            await helpers.update_kayaking_type_data(
                journal_id, journal_type_str, attrs, self.kayaking_data_repo
            )
        elif journal_type == JournalType.CROSS_COUNTRY_SKIING:
            await helpers.update_cross_country_skiing_type_data(
                journal_id, journal_type_str, attrs, self.skiing_data_repo
            )
        elif journal_type == JournalType.SNORKELLING:
            if not await self.snorkelling_data_repo.find_by_journal_id(journal_id):
                raise JournalValidationError(
                    "journal_type", f"Journal does not have type {journal_type_str}"
                )
        elif journal_type == JournalType.DIVING:
            if not await self.diving_data_repo.find_by_journal_id(journal_id):
                raise JournalValidationError(
                    "journal_type", f"Journal does not have type {journal_type_str}"
                )
        elif journal_type == JournalType.DOWNHILL_SKIING:
            if not await self.downhill_skiing_data_repo.find_by_journal_id(journal_id):
                raise JournalValidationError(
                    "journal_type", f"Journal does not have type {journal_type_str}"
                )
        elif journal_type == JournalType.OUTDOOR_PLANNING:
            await helpers.update_outdoor_planning_type_data(
                journal_id, journal_type_str, attrs, self.outdoor_planning_data_repo
            )
        elif journal_type == JournalType.OUTDOOR_TRAINING:
            await helpers.update_outdoor_training_type_data(
                journal_id, attrs, self.outdoor_training_data_repo
            )
        elif journal_type == JournalType.GEAR_MAINTENANCE:
            await helpers.update_gear_maintenance_type_data(
                journal_id, journal_type_str, attrs, self.gear_maintenance_data_repo
            )
        elif journal_type == JournalType.GEAR_USAGE:
            await helpers.update_gear_usage_type_data(
                journal_id, journal_type_str, attrs, self.gear_usage_data_repo
            )
        elif journal_type == JournalType.PLAN:
            await helpers.update_plan_type_data(journal_id, attrs, self.plan_data_repo)
        elif journal_type == JournalType.TRAVEL:
            # TRAVEL nested children (flights/accommodations/transportation) have
            # no write path yet, so editing them is unsupported (and produces no
            # history). Deferred until TRAVEL nested editing is implemented.
            raise JournalValidationError(
                "journal_type",
                "Updating TRAVEL type data is not yet supported. "
                "Please use the full journal update endpoint instead.",
            )
        else:
            # NOTE type has no type-specific data
            raise JournalValidationError(
                "journal_type",
                f"Type {journal_type_str} has no type-specific data to update",
            )

    @transactional
    async def add_contact_to_journal(
        self,
        relationship: JournalContactRelationship,
        transaction: AsyncConnection,
    ) -> JournalContactRelationship:
        """Add a single contact relationship to a journal."""
        return await self.journal_contact_service.add_contact_to_journal(
            relationship, transaction=transaction
        )

    @transactional
    async def remove_contact_from_journal(
        self,
        journal_id: int,
        contact_id: int,
        relationship_type: JournalContactRelationshipType,
        transaction: AsyncConnection,
    ) -> None:
        """Remove a single contact relationship from a journal."""
        await self.journal_contact_service.remove_contact_from_journal(
            journal_id, contact_id, relationship_type, transaction=transaction
        )

    # ------------------------------------------------------------------ #
    # Private orchestration helpers                                       #
    # ------------------------------------------------------------------ #

    async def _process_journal_types(
        self,
        journal_id: int,
        types: list[str],
        transaction: AsyncConnection,
        *,
        changed_by: str,
        source: Provenance,
    ) -> None:
        """Add the requested types (and dependencies) plus their default rows.

        Invalid type strings are skipped, mirroring the original controller.
        """
        for type_str in types:
            try:
                journal_type = helpers.parse_journal_type(type_str)

                # Returns all types added, including auto-resolved dependencies
                added_types = await self.journal_service.add_type_to_journal(
                    journal_id,
                    journal_type,
                    transaction,
                    changed_by=changed_by,
                    source=source,
                )

                # Create type-specific data rows for ALL added types (including
                # dependencies)
                for added_type in added_types:
                    await self._create_type_specific_data(added_type, journal_id)
            except ValueError, KeyError:
                # Invalid type, skip
                pass

    async def _process_journal_type_data(
        self,
        journal_id: int,
        type_data: dict[str, Any],
        transaction: AsyncConnection,
    ) -> None:
        """Process and save type-specific data supplied with a create request.

        ``type_data`` keys are case-insensitive.
        """
        # Normalize type_data keys to lowercase for case-insensitive matching
        normalized_type_data = {k.lower(): v for k, v in type_data.items()}

        # Process EVENT type data
        if "event" in normalized_type_data:
            from datetime import time as dt_time
            from uuid import UUID

            from core_shared.models.journals import (
                CalendarInfo,
                event_date_in_timezone,
            )

            event_data = normalized_type_data["event"]

            # CalendarInfo stores clock-only times; anchor them to the journal's
            # event date range so cross-midnight events (e.g. 23:00→01:00) pass
            # the start<=end validation instead of being wrongly rejected.
            journal = await self.journal_service.journal_repo.find_by_id(journal_id)
            event_timezone = event_data.get("timezone")
            event_start_date = (
                event_date_in_timezone(journal.event_date_range.start, event_timezone)
                if journal is not None
                else None
            )
            event_end_date = (
                event_date_in_timezone(journal.event_date_range.end, event_timezone)
                if journal is not None
                else None
            )

            try:

                def _parse_time_str(time_str: str) -> dt_time:
                    """Parse HH:MM or HH:MM:SS time strings from HTML time inputs."""
                    parts = time_str.split(":")
                    if len(parts) == 2:  # noqa: PLR2004
                        hours, minutes = map(int, parts)
                        seconds = 0
                    elif len(parts) == 3:  # noqa: PLR2004
                        hours, minutes, seconds = map(int, parts)
                    else:
                        raise ValueError(f"Invalid time format: {time_str!r}")
                    return dt_time(hours, minutes, seconds)

                # Convert string times to time objects if provided
                start_time = None
                if event_data.get("start_time"):
                    start_time = _parse_time_str(event_data["start_time"])

                end_time = None
                if event_data.get("end_time"):
                    end_time = _parse_time_str(event_data["end_time"])

                calendar_info = CalendarInfo(
                    journal_id=journal_id,
                    calendar_id=UUID(event_data["calendar_id"]),
                    description=event_data.get("description"),
                    start_time=start_time,
                    end_time=end_time,
                    is_all_day=event_data.get("is_all_day", False),
                    location=event_data.get("location"),
                    timezone=event_data.get("timezone"),
                    sync_invitees=event_data.get("sync_invitees", False),
                    private_description=event_data.get("private_description", False),
                    event_start_date=event_start_date,
                    event_end_date=event_end_date,
                )
                await self.calendar_info_repo.save(calendar_info)

                # Publish JournalUpdated event so Google Calendar worker can sync
                from app.core.journal.models.events import JournalUpdated

                calendar_sync_event = JournalUpdated(
                    journal_id=journal_id,
                    changed_fields={"calendar_info": True},
                    transaction=transaction,
                )
                await self.event_publisher.publish(calendar_sync_event)
            except (ValueError, KeyError) as exc:
                from fastapi import HTTPException

                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid EVENT type_data: {exc}",
                ) from exc

        # PHOTO_ALBUM type data is integration-managed (Immich album sync) and is
        # not writable through this API. Fail fast rather than silently dropping
        # the payload so callers don't believe a write succeeded.
        if "photo_album" in normalized_type_data:
            raise JournalValidationError(
                "photo_album",
                "PHOTO_ALBUM data is managed by Immich sync and cannot be set",
            )

        # Process PLAN type data (shared with the update path so create and edit
        # apply identical document coercion + replace semantics).
        if "plan" in normalized_type_data:
            await helpers.update_plan_type_data(
                journal_id, normalized_type_data["plan"], self.plan_data_repo
            )

        # Process TRAVEL type data
        if "travel" in normalized_type_data:
            from core_shared.models.journals import TravelData

            # Payload for travel currently empty in UI, but create data if valid
            travel_data = await self.travel_data_repo.find_by_journal_id(journal_id)
            if not travel_data:
                travel_data = TravelData(journal_id=journal_id)
            await self.travel_data_repo.save(travel_data)

        # Process MOOD_RATING type data
        if "mood_rating" in normalized_type_data:
            from core_shared.models.journals import MoodData

            mood_payload = normalized_type_data["mood_rating"]
            mood_data = await self.mood_data_repo.find_by_journal_id(journal_id)
            if mood_data is None:
                mood_data = MoodData(journal_id=journal_id)

            mood_value_raw = mood_payload.get("mood_value")
            energy_level_raw = mood_payload.get("energy_level")

            if mood_value_raw is not None:
                try:
                    mood_data.mood_value = int(mood_value_raw)
                except (TypeError, ValueError) as exc:
                    from fastapi import HTTPException

                    raise HTTPException(
                        status_code=400,
                        detail="mood_value must be an integer",
                    ) from exc
            if energy_level_raw is not None:
                try:
                    mood_data.energy_level = int(energy_level_raw)
                except (TypeError, ValueError) as exc:
                    from fastapi import HTTPException

                    raise HTTPException(
                        status_code=400,
                        detail="energy_level must be an integer",
                    ) from exc
            mood_data.mood_label = (
                mood_payload.get("mood_label") or mood_data.mood_label
            )

            await self.mood_data_repo.save(mood_data)

        # Process FITNESS type data
        if "fitness" in normalized_type_data:
            from core_shared.models.journals import FitnessData

            fitness_payload = normalized_type_data["fitness"]
            fitness_data = await self.fitness_data_repo.find_by_journal_id(journal_id)
            if fitness_data is None:
                fitness_data = FitnessData(journal_id=journal_id)

            numeric_fields = (
                "distance",
                "duration",
                "heart_rate_avg",
                "heart_rate_max",
                "elevation_gain",
                "elevation_loss",
                "calories",
            )
            for field in numeric_fields:
                if field in fitness_payload:
                    value = fitness_payload[field]
                    if value is None:
                        setattr(fitness_data, field, None)
                    else:
                        try:
                            setattr(fitness_data, field, int(value))
                        except (TypeError, ValueError) as exc:
                            from fastapi import HTTPException

                            raise HTTPException(
                                status_code=400,
                                detail=f"{field} must be an integer",
                            ) from exc

            if "strava_activity_id" in fitness_payload:
                fitness_data.strava_activity_id = fitness_payload["strava_activity_id"]

            await self.fitness_data_repo.save(fitness_data)

        # Process OUTDOOR_ACTIVITY type data
        if "outdoor_activity" in normalized_type_data:
            from core_shared.models.journals import OutdoorActivityData

            outdoor_payload = normalized_type_data["outdoor_activity"]
            outdoor_data = await self.outdoor_activity_data_repo.find_by_journal_id(
                journal_id
            )
            if outdoor_data is None:
                outdoor_data = OutdoorActivityData(journal_id=journal_id)

            if "weather_conditions" in outdoor_payload:
                outdoor_data.weather_conditions = outdoor_payload["weather_conditions"]
            if "role" in outdoor_payload:
                outdoor_data.role = outdoor_payload["role"]
            if "in_leadership_role" in outdoor_payload:
                outdoor_data.in_leadership_role = outdoor_payload["in_leadership_role"]
            if "participant_notes" in outdoor_payload:
                outdoor_data.participant_notes = outdoor_payload["participant_notes"]

            await self.outdoor_activity_data_repo.save(outdoor_data)

        # Process BUSHWALKING type data
        if "bushwalking" in normalized_type_data:
            from core_shared.models.journals import BushwalkingData

            bushwalking_payload = normalized_type_data["bushwalking"]
            bushwalking_data = await self.bushwalking_data_repo.find_by_journal_id(
                journal_id
            )
            if bushwalking_data is None:
                bushwalking_data = BushwalkingData(journal_id=journal_id)

            if "track_grading" in bushwalking_payload:
                bushwalking_data.track_grading = bushwalking_payload["track_grading"]

            await self.bushwalking_data_repo.save(bushwalking_data)

        # Process JOGGING type data
        if "jogging" in normalized_type_data:
            from core_shared.models.journals import JoggingData

            jogging_payload = normalized_type_data["jogging"]
            jogging_data = await self.jogging_data_repo.find_by_journal_id(journal_id)
            if jogging_data is None:
                jogging_data = JoggingData(journal_id=journal_id)

            if "pace" in jogging_payload:
                pace_raw = jogging_payload["pace"]
                if pace_raw is None:
                    jogging_data.pace = None
                else:
                    try:
                        jogging_data.pace = int(pace_raw)
                    except (TypeError, ValueError) as exc:
                        from fastapi import HTTPException

                        raise HTTPException(
                            status_code=400,
                            detail="pace must be an integer (seconds per km)",
                        ) from exc

            await self.jogging_data_repo.save(jogging_data)

        # Process ABSEILING_TRIP type data
        if "abseiling_trip" in normalized_type_data:
            await helpers.update_abseiling_type_data(
                journal_id,
                "ABSEILING_TRIP",
                normalized_type_data["abseiling_trip"],
                self.abseiling_data_repo,
                self.abseil_pitch_repo,
            )

        # Process CANYONING type data
        if "canyoning" in normalized_type_data:
            await helpers.update_canyoning_type_data(
                journal_id,
                "CANYONING",
                normalized_type_data["canyoning"],
                self.canyoning_data_repo,
            )

        # Process CAVING type data
        if "caving" in normalized_type_data:
            await helpers.update_caving_type_data(
                journal_id,
                "CAVING",
                normalized_type_data["caving"],
                self.caving_data_repo,
            )

        # Process CANOEING type data
        if "canoeing" in normalized_type_data:
            await helpers.update_canoeing_type_data(
                journal_id,
                "CANOEING",
                normalized_type_data["canoeing"],
                self.canoeing_data_repo,
            )

        # Process CLIMBING type data
        if "climbing" in normalized_type_data:
            await helpers.update_climbing_type_data(
                journal_id,
                "CLIMBING",
                normalized_type_data["climbing"],
                self.climbing_data_repo,
            )

        # Process KAYAKING type data
        if "kayaking" in normalized_type_data:
            await helpers.update_kayaking_type_data(
                journal_id,
                "KAYAKING",
                normalized_type_data["kayaking"],
                self.kayaking_data_repo,
            )

        # Process CROSS_COUNTRY_SKIING type data
        if "cross_country_skiing" in normalized_type_data:
            await helpers.update_cross_country_skiing_type_data(
                journal_id,
                "CROSS_COUNTRY_SKIING",
                normalized_type_data["cross_country_skiing"],
                self.skiing_data_repo,
            )

        # Process OUTDOOR_PLANNING type data
        if "outdoor_planning" in normalized_type_data:
            await helpers.update_outdoor_planning_type_data(
                journal_id,
                "OUTDOOR_PLANNING",
                normalized_type_data["outdoor_planning"],
                self.outdoor_planning_data_repo,
            )

        # Process OUTDOOR_TRAINING type data
        if "outdoor_training" in normalized_type_data:
            await helpers.update_outdoor_training_type_data(
                journal_id,
                normalized_type_data["outdoor_training"],
                self.outdoor_training_data_repo,
            )

        # Process GEAR_MAINTENANCE type data
        if "gear_maintenance" in normalized_type_data:
            await helpers.update_gear_maintenance_type_data(
                journal_id,
                "GEAR_MAINTENANCE",
                normalized_type_data["gear_maintenance"],
                self.gear_maintenance_data_repo,
            )

        # Process GEAR_USAGE type data
        if "gear_usage" in normalized_type_data:
            await helpers.update_gear_usage_type_data(
                journal_id,
                "GEAR_USAGE",
                normalized_type_data["gear_usage"],
                self.gear_usage_data_repo,
            )

    async def _process_journal_contact_relationships(
        self,
        journal_id: int,
        contacts_data: list[dict[str, Any]],
        transaction: AsyncConnection,
    ) -> None:
        """Create contact relationships for a journal, skipping invalid items.

        Each relationship is wrapped in a SAVEPOINT so a missing contact or a
        unique-constraint violation rolls back only that item, not the whole
        composite write.
        """
        for contact_data in contacts_data:
            try:
                # Extract contact_id and relationship_type from attributes
                # contact_data is a dict from JSON, not a Pydantic model
                if "attributes" in contact_data:
                    attrs = contact_data["attributes"]
                    contact_id = int(attrs["contact_id"])
                    relationship_type = JournalContactRelationshipType[
                        attrs["relationship_type"]
                    ]

                    # Parse status and role if present
                    from core_shared.models.journals.attendee_status import (
                        AttendeeStatus,
                    )
                    from core_shared.models.journals.contact_event_role import (
                        ContactEventRole,
                    )

                    status, role = None, None
                    status_raw = attrs.get("status")
                    if isinstance(status_raw, str):
                        try:
                            status = AttendeeStatus[status_raw.upper()]
                        except KeyError:
                            logger.warning(
                                "Invalid AttendeeStatus",
                                status=status_raw,
                                journal_id=journal_id,
                                contact_id=contact_id,
                            )

                    role_raw = attrs.get("role")
                    if isinstance(role_raw, str):
                        try:
                            role = ContactEventRole[role_raw.upper()]
                        except KeyError:
                            logger.warning(
                                "Invalid ContactEventRole",
                                role=role_raw,
                                journal_id=journal_id,
                                contact_id=contact_id,
                            )

                    # Create the relationship using a SAVEPOINT to prevent
                    # aborting the unit of work if a contact is missing or a
                    # unique constraint is violated.
                    relationship = JournalContactRelationship(
                        journal_id=journal_id,
                        contact_id=contact_id,
                        relationship_type=relationship_type,
                        status=status,
                        role=role,
                    )
                    try:
                        async with savepoint(transaction):
                            await self.journal_contact_service.add_contact_to_journal(
                                relationship, transaction=transaction
                            )
                    except IntegrityError:
                        # Log error and ignore; the savepoint handles the rollback
                        logger.warning(
                            "Invalid journal contact relationship ignored",
                            journal_id=journal_id,
                            contact_id=contact_id,
                        )

            except ValueError, KeyError, AttributeError, TypeError:
                # Invalid contact relationship payload, skip
                pass

    async def _process_journal_tags(
        self,
        journal_id: int,
        tags: list[str],
        transaction: AsyncConnection,
    ) -> None:
        """Find-or-create each tag by name and assign it to the journal.

        Each tag is wrapped in a SAVEPOINT so a failure (e.g. a duplicate-name
        race on insert) rolls back just that statement and leaves the surrounding
        transaction usable — the error then propagates cleanly rather than
        poisoning the whole composite unit of work. The error is NOT swallowed:
        a failing tag still aborts the composite write. Tag lookup is
        case-insensitive (``tag_repo.find_by_name``); a missing tag is created
        with the default grey colour, mirroring the previous MCP tool behaviour.
        """
        for tag_name in tags:
            async with savepoint(transaction):
                tag = await self.tag_repo.find_by_name(tag_name)
                if tag is None:
                    tag = await self.tag_repo.save(
                        JournalTag(id=None, name=tag_name, color="#808080")
                    )
                if tag.id is not None:
                    await self.tag_repo.assign_tag(journal_id, tag.id)

    # Tables whose presence marks a journal type, used to detect current types
    # for replace-all updates. Must cover every type that
    # ``_create_type_specific_data`` / ``_delete_type_specific_data`` can
    # add/remove, otherwise a replace-all update would fail to detect (and so
    # leave behind) a dropped type. PHOTO_ALBUM is intentionally omitted: it is
    # Immich-synced and must not be removed/created through this write path.
    def _type_presence_repos(self) -> list[tuple[JournalType, Any]]:
        return [
            (JournalType.EVENT, self.calendar_info_repo),
            (JournalType.MOOD_RATING, self.mood_data_repo),
            (JournalType.PLAN, self.plan_data_repo),
            (JournalType.TRAVEL, self.travel_data_repo),
            (JournalType.FITNESS, self.fitness_data_repo),
            (JournalType.OUTDOOR_ACTIVITY, self.outdoor_activity_data_repo),
            (JournalType.BUSHWALKING, self.bushwalking_data_repo),
            (JournalType.JOGGING, self.jogging_data_repo),
            (JournalType.ABSEILING_TRIP, self.abseiling_data_repo),
            (JournalType.CAVING, self.caving_data_repo),
            (JournalType.CANYONING, self.canyoning_data_repo),
            (JournalType.CANOEING, self.canoeing_data_repo),
            (JournalType.CLIMBING, self.climbing_data_repo),
            (JournalType.KAYAKING, self.kayaking_data_repo),
            (JournalType.CROSS_COUNTRY_SKIING, self.skiing_data_repo),
            (JournalType.SNORKELLING, self.snorkelling_data_repo),
            (JournalType.DIVING, self.diving_data_repo),
            (JournalType.DOWNHILL_SKIING, self.downhill_skiing_data_repo),
            (JournalType.OUTDOOR_PLANNING, self.outdoor_planning_data_repo),
            (JournalType.OUTDOOR_TRAINING, self.outdoor_training_data_repo),
            (JournalType.GEAR_MAINTENANCE, self.gear_maintenance_data_repo),
            (JournalType.GEAR_USAGE, self.gear_usage_data_repo),
        ]

    async def _get_current_types(self, journal_id: int) -> set[JournalType]:
        """Detect a journal's current types by which type-data rows exist.

        Type membership is represented by the presence of a type-specific data
        row (there is no dedicated types table).
        """
        current: set[JournalType] = set()
        for journal_type, repo in self._type_presence_repos():
            if await repo.find_by_journal_id(journal_id) is not None:
                current.add(journal_type)
        return current

    async def _replace_journal_types(
        self,
        journal_id: int,
        types: list[str],
        type_data: dict[str, Any] | None,
        transaction: AsyncConnection,
        *,
        changed_by: str,
        source: Provenance,
    ) -> None:
        """Replace the journal's types with ``types`` (replace-all semantics).

        Types present but no longer desired are removed (their type-data row
        deleted); newly desired types are added (with auto-resolved dependencies)
        and given default rows; finally any supplied ``type_data`` is applied.

        An unparseable type string raises rather than being skipped: silently
        dropping it from ``desired`` would make ``current - desired`` remove
        (and delete the data of) more types than the client intended. Callers
        validate upfront, so this is a defensive guard against an incomplete set.
        """
        desired: set[JournalType] = set()
        for type_str in types:
            try:
                desired.add(helpers.parse_journal_type(type_str))
            except (ValueError, KeyError) as exc:
                raise JournalValidationError(
                    "types", f"Invalid journal type: {type_str}"
                ) from exc

        current = await self._get_current_types(journal_id)

        # GEAR_* types cannot be created with a default row, so adding one without
        # accompanying type_data would silently no-op. Fail fast with a clear error
        # (mirrors the create tool's upfront validation).
        normalized_type_data = {k.lower(): v for k, v in (type_data or {}).items()}
        for journal_type in desired - current:
            if journal_type in (
                JournalType.GEAR_MAINTENANCE,
                JournalType.GEAR_USAGE,
            ) and not normalized_type_data.get(journal_type.value):
                raise JournalValidationError(
                    journal_type.value,
                    f"Type {journal_type.value.upper()} requires corresponding "
                    "non-empty type_data when added",
                )

        for journal_type in current - desired:
            await self.journal_service.remove_type_from_journal(
                journal_id,
                journal_type,
                transaction,
                changed_by=changed_by,
                source=source,
            )
            await self._delete_type_specific_data(journal_type, journal_id)

        for journal_type in desired - current:
            added_types = await self.journal_service.add_type_to_journal(
                journal_id,
                journal_type,
                transaction,
                changed_by=changed_by,
                source=source,
            )
            for added_type in added_types:
                await self._create_type_specific_data(added_type, journal_id)

        # Only apply type-data for types that remain after the replace. A stray
        # key for a type not in `types` would otherwise recreate that type's row
        # and defeat the replace-all semantics.
        desired_values = {jt.value for jt in desired}
        scoped_type_data = {
            key: value
            for key, value in normalized_type_data.items()
            if key in desired_values
        }
        if scoped_type_data:
            await self._process_journal_type_data(
                journal_id, scoped_type_data, transaction
            )

    async def _replace_contact_relationships(
        self,
        journal_id: int,
        relationships: list[dict[str, Any]],
        transaction: AsyncConnection,
    ) -> None:
        """Remove all existing contact relationships, then add the provided set."""
        repo = self.journal_contact_service.contact_relationship_repo
        existing = await repo.get_by_journal(journal_id)
        for rel in existing:
            await self.journal_contact_service.remove_contact_from_journal(
                rel.journal_id if rel.journal_id is not None else journal_id,
                rel.contact_id,
                rel.relationship_type,
                transaction=transaction,
            )
        await self._process_journal_contact_relationships(
            journal_id, relationships, transaction
        )

    async def _replace_journal_tags(
        self,
        journal_id: int,
        tags: list[str],
        transaction: AsyncConnection,
    ) -> None:
        """Remove all existing tag assignments, then find-or-create + assign ``tags``."""
        existing = await self.tag_repo.get_tags_for_journal(journal_id)
        for tag in existing:
            if tag.id is not None:
                await self.tag_repo.remove_tag(journal_id, tag.id)
        await self._process_journal_tags(journal_id, tags, transaction)

    async def _create_type_specific_data(
        self, journal_type: JournalType, journal_id: int
    ) -> None:
        """Create the default type-specific data row for a journal type."""
        await helpers.create_type_specific_data(
            journal_type,
            journal_id,
            self.mood_data_repo,
            self.plan_data_repo,
            self.travel_data_repo,
            self.fitness_data_repo,
            self.outdoor_activity_data_repo,
            self.bushwalking_data_repo,
            self.jogging_data_repo,
            self.abseiling_data_repo,
            self.abseil_pitch_repo,
            self.canyoning_data_repo,
            self.caving_data_repo,
            self.canoeing_data_repo,
            self.climbing_data_repo,
            self.kayaking_data_repo,
            self.skiing_data_repo,
            self.snorkelling_data_repo,
            self.diving_data_repo,
            self.downhill_skiing_data_repo,
            self.outdoor_planning_data_repo,
            self.outdoor_training_data_repo,
            self.gear_maintenance_data_repo,
            self.gear_usage_data_repo,
        )

    async def _delete_type_specific_data(
        self, journal_type: JournalType, journal_id: int
    ) -> None:
        """Delete the type-specific data row for a journal type."""
        if journal_type == JournalType.EVENT:
            # EVENT has no row in the generic helper; its presence marker is the
            # journal_calendar_info row, so it must be removed here for the type
            # to actually be gone (e.g. on a replace-all update that drops EVENT).
            await self.calendar_info_repo.delete(journal_id)
            return
        await helpers.delete_type_specific_data(
            journal_type,
            journal_id,
            self.mood_data_repo,
            self.plan_data_repo,
            self.travel_data_repo,
            self.photo_album_data_repo,
            self.fitness_data_repo,
            self.outdoor_activity_data_repo,
            self.bushwalking_data_repo,
            self.jogging_data_repo,
            self.abseiling_data_repo,
            self.abseil_pitch_repo,
            self.canyoning_data_repo,
            self.caving_data_repo,
            self.canoeing_data_repo,
            self.climbing_data_repo,
            self.kayaking_data_repo,
            self.skiing_data_repo,
            self.snorkelling_data_repo,
            self.diving_data_repo,
            self.downhill_skiing_data_repo,
            self.outdoor_planning_data_repo,
            self.outdoor_training_data_repo,
            self.gear_maintenance_data_repo,
            self.gear_usage_data_repo,
        )
