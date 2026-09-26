"""Write-side schemas for journal ``type_data``, one model per journal type.

These are the single source of truth for what a client may send in
``type_data``: the field names, their types, and every constraint the domain
enforces. Two surfaces read them, so neither has to restate a limit:

* ``list_journal_types`` publishes their JSON Schema, which is how an agent
  discovers that ``role`` caps at 100 characters *before* breaching it;
* the MCP tools validate ``type_data`` against them at the tool boundary, so a
  bad value is refused with the field named rather than reaching the column and
  surfacing as an opaque driver error. That wiring lands in the next change of
  this stack; here the models exist and are published.

The REST response schemas in ``app.api.journals.schemas`` deliberately do NOT
build on these. Reading has to be more forgiving than writing — a row holding a
value that predates a vocabulary still has to deserialise — so the two model
sets differ by type, and inheriting one from the other is a Liskov violation
mypy rightly rejects. The numbers stay single-sourced regardless: both sides
read the same constants.

Every bound is imported from :mod:`core_shared.models.journals.constants` and
every closed vocabulary is its ``StrEnum``, so a limit is defined exactly once
and JSON Schema gets a native ``maxLength`` / ``minimum`` / ``enum``. The
entity dataclasses validate the same rules again in ``__post_init__``: these
models guard the boundary, the entities guard the domain, and both read the
same constants.

What these models do **not** hold is any rule that needs a row they cannot
see. A ``type_data`` update is a patch, so a model validating it sees only the
fields the caller sent — never the stored ones. "start_time and end_time must
be given together" and "an all-day event has no times" cannot both be decided
from a patch, and whether an end time earlier than its start is an error or an
event running past midnight depends on the journal's date range, which is not
in ``type_data`` at all. Those live in the entities, which see the merged row,
and they surface as ordinary 400s rather than the opaque failure this work was
about. Where a rule *is* decidable from the payload alone — a timezone
``ZoneInfo`` cannot resolve, an all-day event carrying a time, a check-in
before its check-out — it is enforced here too and named in the field
description, so ``list_journal_types`` still teaches it.

Vocabularies are typed as their enum **here** but stay ``str`` on the read
side, so a legacy row holding an off-vocabulary value still reads back instead
of failing deserialisation.

``extra="forbid"``: a mistyped key is refused, naming the field. It used to be
dropped in silence, which reads to a caller as a write that succeeded.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from typing import Annotated, Any
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from core_shared.models.journals.constants import (
    FRENCH_CANYON_GRADE_PATTERN,
    MAX_ENERGY_LEVEL,
    MAX_FRENCH_GRADE_LENGTH,
    MAX_LOCATION_LENGTH,
    MAX_MOOD_LABEL_LENGTH,
    MAX_MOOD_VALUE,
    MAX_PARTICIPANT_NOTES_LENGTH,
    MAX_PLAN_DOCUMENT_TITLE_LENGTH,
    MAX_PLAN_DOCUMENT_URL_LENGTH,
    MAX_RETIREMENT_REASON_LENGTH,
    MAX_ROLE_LENGTH,
    MAX_STRAVA_ACTIVITY_ID_LENGTH,
    MAX_TIMEZONE_LENGTH,
    MAX_WATER_GAUGE_NAME_LENGTH,
    MAX_WEATHER_CONDITIONS_LENGTH,
    MIN_ENERGY_LEVEL,
    MIN_MOOD_VALUE,
    AnchorLocation,
    AnchorType,
    ClimbingType,
    MaintenanceType,
    PitchType,
    RapidsGrade,
    TrackGrade,
)
from core_shared.models.journals.event_state import EventState
from core_shared.models.journals.journal_types import JournalType
from core_shared.models.journals.outdoor_activity_subtypes import OutdoorActivitySubtype


def _reject_blank(value: str) -> str:
    """A text field the domain requires to be non-blank.

    ``"   "`` clears nothing and means nothing; the entities reject it, so the
    boundary has to as well or the advertised constraints are not the ones
    actually enforced. Use ``null`` to clear a field.
    """
    if not value.strip():
        raise ValueError("must not be blank; use null to clear it")
    return value


NonBlankStr = Annotated[str, AfterValidator(_reject_blank)]


def _resolvable_timezone(value: str) -> str:
    """An IANA name ``ZoneInfo`` can actually resolve.

    ``CalendarInfo`` checks this, and length alone let "Australia/Sidney"
    through a boundary that claims to hold the write constraints. This one is a
    single field, so unlike the cross-field event rules it can live here
    without needing to see the stored row.
    """
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, KeyError, ValueError) as exc:
        raise ValueError(f"is not a known IANA timezone: {value!r}") from exc
    return value


TimezoneStr = Annotated[str, AfterValidator(_resolvable_timezone)]


def _unit(unit: str) -> dict[str, Any]:
    """Carry a field's unit into its JSON Schema.

    JSON Schema has no unit keyword, and a bare ``int`` tells a caller nothing
    about whether a distance is metres or kilometres — the one thing they must
    not have to infer.
    """
    return {"unit": unit}


class TypeDataModel(BaseModel):
    """Base for every type_data write model."""

    model_config = ConfigDict(extra="forbid")


class NoteTypeData(TypeDataModel):
    """NOTE carries no type_data — it is the absence of any typed row."""


class EventTypeData(TypeDataModel):
    """EVENT (calendar_info)."""

    calendar_id: UUID = Field(description="UUID of the calendar to file the event in")
    description: str | None = Field(
        default=None, description="Event description, separate from the journal content"
    )
    start_time: time | None = Field(
        default=None,
        description=(
            "Start time of day, HH:MM or HH:MM:SS, no timezone. On a create, "
            "start_time and end_time must be given together or both omitted. "
            "An end earlier than the start is allowed and means the event runs "
            "past midnight, resolved against the journal's event_date_range"
        ),
    )
    end_time: time | None = Field(
        default=None,
        description=(
            "End time of day, HH:MM or HH:MM:SS, no timezone. See start_time "
            "for the pairing and past-midnight rules"
        ),
    )
    is_all_day: bool | None = Field(
        default=None,
        description=(
            "All-day event. An all-day event holds no times: leave them out "
            "and any stored times are cleared for you"
        ),
    )
    location: str | None = Field(
        default=None, description="Free-text location", max_length=MAX_LOCATION_LENGTH
    )
    timezone: TimezoneStr | None = Field(
        default=None,
        description="IANA timezone name that ZoneInfo can resolve, e.g. 'Australia/Sydney'",
        max_length=MAX_TIMEZONE_LENGTH,
    )
    sync_invitees: bool | None = Field(
        default=None, description="Sync invitees to the external calendar"
    )
    private_description: bool | None = Field(
        default=None,
        description="Keep the description out of the external calendar",
    )
    event_state: EventState | None = Field(
        default=None, description="Participation state (defaults to confirmed)"
    )

    @model_validator(mode="after")
    def _all_day_events_hold_no_times(self) -> EventTypeData:
        """An all-day event carrying a time contradicts itself.

        Only the rules that need no other row are checked here. Whether the
        times are supplied *as a pair* depends on what is already stored, which
        a patch cannot see, and an end earlier than its start is legal — it
        means the event runs past midnight, resolved against the journal's date
        range. CalendarInfo owns both of those, with the dates in hand.
        """
        if self.is_all_day and (self.start_time or self.end_time):
            raise ValueError(
                "an all-day event cannot have start_time or end_time; "
                "omit them and any stored times are cleared"
            )
        return self


class MoodRatingTypeData(TypeDataModel):
    """MOOD_RATING."""

    mood_value: int | None = Field(
        default=None,
        description="Mood on a 1-10 scale",
        ge=MIN_MOOD_VALUE,
        le=MAX_MOOD_VALUE,
        json_schema_extra=_unit("1-10 scale"),
    )
    mood_label: str | None = Field(
        default=None,
        description="Free-text mood label",
        max_length=MAX_MOOD_LABEL_LENGTH,
    )
    energy_level: int | None = Field(
        default=None,
        description="Energy on a 1-10 scale",
        ge=MIN_ENERGY_LEVEL,
        le=MAX_ENERGY_LEVEL,
        json_schema_extra=_unit("1-10 scale"),
    )


class PlanDocumentTypeData(TypeDataModel):
    """One linked document on a PLAN journal."""

    url: NonBlankStr = Field(
        description="Document URL",
        max_length=MAX_PLAN_DOCUMENT_URL_LENGTH,
    )
    title: str | None = Field(
        default=None,
        description="Document title; blank becomes 'Untitled'",
        max_length=MAX_PLAN_DOCUMENT_TITLE_LENGTH,
    )
    description: str | None = Field(default=None, description="Document description")
    order: int | None = Field(
        default=None, description="Display order; defaults to the position in the list"
    )


class PlanTypeData(TypeDataModel):
    """PLAN."""

    documents: list[PlanDocumentTypeData] | None = Field(
        default=None,
        description=(
            "Linked documents. Replaces the whole list: a document whose url is "
            "absent from the payload is deleted, and one whose url matches an "
            "existing document keeps its id so history reads as an edit"
        ),
    )


class TravelTypeData(TypeDataModel):
    """TRAVEL — the row exists, but no field is writable through type_data."""


class FitnessTypeData(TypeDataModel):
    """FITNESS."""

    heart_rate_avg: int | None = Field(
        default=None,
        description="Average heart rate",
        ge=0,
        json_schema_extra=_unit("bpm"),
    )
    heart_rate_max: int | None = Field(
        default=None,
        description="Maximum heart rate",
        ge=0,
        json_schema_extra=_unit("bpm"),
    )
    distance: int | None = Field(
        default=None,
        description="Distance covered, in metres (a 10 km ride is 10000)",
        ge=0,
        json_schema_extra=_unit("m"),
    )
    elevation_gain: int | None = Field(
        default=None,
        description="Total ascent",
        ge=0,
        json_schema_extra=_unit("m"),
    )
    elevation_loss: int | None = Field(
        default=None,
        description="Total descent",
        ge=0,
        json_schema_extra=_unit("m"),
    )
    duration: int | None = Field(
        default=None,
        description="Moving time, in seconds (an hour is 3600)",
        ge=0,
        json_schema_extra=_unit("seconds"),
    )
    calories: int | None = Field(
        default=None,
        description="Energy expended",
        ge=0,
        json_schema_extra=_unit("kcal"),
    )
    strava_activity_id: NonBlankStr | None = Field(
        default=None,
        description="Linked Strava activity id; creates the Strava external link",
        max_length=MAX_STRAVA_ACTIVITY_ID_LENGTH,
    )


class OutdoorActivityTypeData(TypeDataModel):
    """OUTDOOR_ACTIVITY."""

    weather_conditions: NonBlankStr | None = Field(
        default=None,
        description="Weather during the activity, e.g. 'hot and windy'",
        max_length=MAX_WEATHER_CONDITIONS_LENGTH,
    )
    role: NonBlankStr | None = Field(
        default=None,
        description="Your role on the trip, e.g. 'Guide', 'Organiser', 'Course Leader'",
        max_length=MAX_ROLE_LENGTH,
    )
    in_leadership_role: bool | None = Field(
        default=None, description="Whether you led the trip"
    )
    participant_notes: NonBlankStr | None = Field(
        default=None,
        description="Notes about participants not listed via contact relationships",
        max_length=MAX_PARTICIPANT_NOTES_LENGTH,
    )


class BushwalkingTypeData(TypeDataModel):
    """BUSHWALKING."""

    track_grading: TrackGrade | None = Field(
        default=None, description="Australian Walking Track Grading System grade"
    )


class JoggingTypeData(TypeDataModel):
    """JOGGING."""

    pace: int | None = Field(
        default=None,
        description="Pace in seconds per kilometre, e.g. 330 for 5:30/km",
        ge=0,
        json_schema_extra=_unit("seconds per km"),
    )


class AbseilPitchTypeData(TypeDataModel):
    """One pitch on an ABSEILING_TRIP journal."""

    pitch_number: int = Field(description="Sequence number, 1-based", ge=1)
    height: int | None = Field(
        default=None,
        description="Drop height of this pitch",
        ge=0,
        json_schema_extra=_unit("m"),
    )
    anchor_location: AnchorLocation | None = Field(
        default=None, description="Where the anchor sits"
    )
    anchor_type: AnchorType | None = Field(default=None, description="Kind of anchor")
    did_rescue: bool | None = Field(
        default=None, description="Whether you performed a rescue on this pitch"
    )
    did_setup: bool | None = Field(
        default=None, description="Whether you set the anchor up"
    )
    notes: str | None = Field(default=None, description="Short notes for the pitch")
    pitch_type: PitchType | None = Field(
        default=None, description="How the pitch is descended; null means abseil"
    )


class AbseilingTripTypeData(TypeDataModel):
    """ABSEILING_TRIP."""

    template_id: UUID | None = Field(
        default=None,
        description=(
            "Activity template this abseiling-derived journal came from, "
            "preserved when pitches are edited. On create, prefer "
            "create_journal_entry's top-level template_id, which also applies "
            "the template's pitches and type fields"
        ),
    )
    number_of_abseils: int | None = Field(
        default=None, description="Count of abseils", ge=0
    )
    total_length: int | None = Field(
        default=None,
        description="Total abseiled length",
        ge=0,
        json_schema_extra=_unit("m"),
    )
    number_of_setups: int | None = Field(
        default=None, description="Anchors you set up", ge=0
    )
    number_of_rescues: int | None = Field(
        default=None, description="Rescues you performed", ge=0
    )
    pitches: list[AbseilPitchTypeData] | None = Field(
        default=None, description="Pitches, replacing the whole list"
    )


class CanyoningTypeData(TypeDataModel):
    """CANYONING."""

    french_grade: str | None = Field(
        default=None,
        description=(
            "French canyon grade: v[1-7]a[1-7] then optional engagement I-VI "
            "and 1-3 stars, e.g. 'v3a2IV**'"
        ),
        max_length=MAX_FRENCH_GRADE_LENGTH,
        pattern=FRENCH_CANYON_GRADE_PATTERN,
    )
    water_guage_name: str | None = Field(
        default=None,
        description="Name of the water gauge used",
        max_length=MAX_WATER_GAUGE_NAME_LENGTH,
    )
    water_guage_level: int | None = Field(
        default=None, description="Gauge reading at the time of the trip"
    )
    is_vertical: bool | None = Field(
        default=None, description="Primarily vertical canyon"
    )
    is_night_canyon: bool | None = Field(default=None, description="Done at night")
    is_white_water: bool | None = Field(
        default=None, description="Significant white water"
    )


class ClimbingTypeData(TypeDataModel):
    """CLIMBING."""

    climbing_type: ClimbingType | None = Field(
        default=None, description="Climbing discipline"
    )
    grade: int | None = Field(
        default=None, description="Ewbank (Australian) grade", ge=0
    )
    length: int | None = Field(
        default=None,
        description="Route length",
        ge=0,
        json_schema_extra=_unit("m"),
    )
    indoor: bool | None = Field(
        default=None,
        description="Indoor climb; independent of climbing_type",
    )


class KayakingTypeData(TypeDataModel):
    """KAYAKING."""

    water_type: NonBlankStr | None = Field(
        default=None,
        description="Type of water body — free text, e.g. 'river', 'lake', 'sea'",
    )
    is_white_water: bool | None = Field(default=None, description="White-water paddle")
    rapids_grade: RapidsGrade | None = Field(
        default=None, description="International Scale of River Difficulty"
    )


class CrossCountrySkiingTypeData(TypeDataModel):
    """CROSS_COUNTRY_SKIING."""

    snow_conditions: NonBlankStr | None = Field(
        default=None,
        description=(
            "Snow conditions — free text with no fixed vocabulary, e.g. "
            "'fresh powder', 'packed powder', 'spring corn', 'icy', 'slush'"
        ),
    )


class CavingTypeData(TypeDataModel):
    """CAVING."""

    is_vertical: bool | None = Field(default=None, description="Vertical cave (SRT)")
    is_horizontal: bool | None = Field(default=None, description="Horizontal cave")


class CanoeingTypeData(TypeDataModel):
    """CANOEING."""

    water_type: NonBlankStr | None = Field(
        default=None,
        description="Type of water body — free text, e.g. 'river', 'lake', 'sea'",
    )


class SnorkellingTypeData(TypeDataModel):
    """SNORKELLING — presence of the row is the whole record."""


class DivingTypeData(TypeDataModel):
    """DIVING — presence of the row is the whole record."""


class DownhillSkiingTypeData(TypeDataModel):
    """DOWNHILL_SKIING — presence of the row is the whole record."""


class OutdoorPlanningTypeData(TypeDataModel):
    """OUTDOOR_PLANNING."""

    topics: str | None = Field(default=None, description="Meeting topics")
    activity_types: list[OutdoorActivitySubtype] | None = Field(
        default=None, description="Outdoor activity types the meeting relates to"
    )


class OutdoorTrainingTypeData(TypeDataModel):
    """OUTDOOR_TRAINING."""

    focus_areas: list[NonBlankStr] | None = Field(
        default=None,
        description=(
            "Skills trained. Prefer a value from enums.activity_subtypes; "
            "free text is accepted for anything outside that list"
        ),
    )


class GearMaintenanceTypeData(TypeDataModel):
    """GEAR_MAINTENANCE."""

    gear_item_id: UUID = Field(description="UUID of the gear item being maintained")
    maintenance_type: MaintenanceType = Field(description="Kind of maintenance")
    activity_types: list[OutdoorActivitySubtype] | None = Field(
        default=None, description="Activity types the item is used for"
    )
    retirement_reason: NonBlankStr | None = Field(
        default=None,
        description=(
            "Why the item was retired. Required when maintenance_type is "
            f"'{MaintenanceType.RETIRING_GEAR.value}'"
        ),
        max_length=MAX_RETIREMENT_REASON_LENGTH,
    )

    @model_validator(mode="after")
    def _retirement_needs_a_reason(self) -> GearMaintenanceTypeData:
        """The domain refuses to retire an item without saying why.

        Only checked when maintenance_type is actually supplied: on a partial
        update it may be absent, and the stored value is not visible here. The
        entity checks it again against the merged row.
        """
        if (
            self.maintenance_type == MaintenanceType.RETIRING_GEAR
            and not self.retirement_reason
        ):
            raise ValueError(
                "retirement_reason is required when maintenance_type is "
                f"'{MaintenanceType.RETIRING_GEAR.value}'"
            )
        return self


def _refuse_inverted_window(
    checkout: datetime | None, checkin: datetime | None
) -> None:
    """A usage window that ends before it begins, refused where it is named.

    Checked only when the payload carries both ends: a patch setting one of
    them cannot see the stored other, and the entity checks the merged item
    regardless.
    """
    if checkout is None or checkin is None:
        return
    # The entity treats a naive datetime as UTC when comparing against an
    # aware one; match that rather than raising on the mix.
    if (checkout.tzinfo is None) != (checkin.tzinfo is None):
        checkout = checkout.replace(tzinfo=checkout.tzinfo or UTC)
        checkin = checkin.replace(tzinfo=checkin.tzinfo or UTC)
    if checkout > checkin:
        raise ValueError("checkin_date cannot be earlier than checkout_date")


class GearUsageItemTypeData(TypeDataModel):
    """One gear item used on a GEAR_USAGE journal."""

    gear_item_id: UUID = Field(description="UUID of the gear item being used")
    checkout_date: datetime | None = Field(
        default=None,
        description=(
            "ISO datetime the item was checked out; null means the journal's start"
        ),
    )
    checkin_date: datetime | None = Field(
        default=None,
        description=(
            "ISO datetime the item was checked back in; null means the journal's "
            "end. Cannot be earlier than checkout_date"
        ),
    )

    @model_validator(mode="after")
    def _checkin_cannot_precede_checkout(self) -> GearUsageItemTypeData:
        _refuse_inverted_window(self.checkout_date, self.checkin_date)
        return self


_LEGACY_GEAR_USAGE_FIELDS = ("gear_item_id", "checkout_date", "checkin_date")


class GearUsageTypeData(TypeDataModel):
    """GEAR_USAGE: the gear items used on the journal.

    ``items`` is the whole list. The single-item fields are the older shape,
    still accepted: they add or update one item without touching the others.
    """

    items: list[GearUsageItemTypeData] | None = Field(
        default=None,
        description=(
            "Every gear item used, replacing the whole list: items left out are "
            "removed. A gear item may appear once. Do not combine with "
            "gear_item_id/checkout_date/checkin_date"
        ),
    )
    gear_item_id: UUID | None = Field(
        default=None,
        description=(
            "Deprecated single-item form: adds this gear item, or updates its "
            "dates if the journal already lists it; other items are kept"
        ),
    )
    checkout_date: datetime | None = Field(
        default=None,
        description=(
            "Deprecated single-item form: checkout of gear_item_id, or of the "
            "journal's only item when gear_item_id is omitted"
        ),
    )
    checkin_date: datetime | None = Field(
        default=None,
        description=(
            "Deprecated single-item form: check-in of gear_item_id, or of the "
            "journal's only item when gear_item_id is omitted; cannot be earlier "
            "than checkout_date"
        ),
    )

    @model_validator(mode="after")
    def _one_shape_at_a_time(self) -> GearUsageTypeData:
        """Refuse mixing the list with the single-item fields, and bad items.

        The write helper applies the same rules (an update is validated without
        this model's validators), so this is the early, well-named refusal.
        """
        if self.items is not None:
            mixed = [f for f in _LEGACY_GEAR_USAGE_FIELDS if f in self.model_fields_set]
            if mixed:
                raise ValueError(
                    f"items cannot be combined with {', '.join(mixed)}; "
                    "list every gear item in items instead"
                )
            seen: set[UUID] = set()
            for item in self.items:
                if item.gear_item_id in seen:
                    raise ValueError(
                        f"items lists gear item {item.gear_item_id} more than once"
                    )
                seen.add(item.gear_item_id)
        _refuse_inverted_window(self.checkout_date, self.checkin_date)
        return self


# Every JournalType that accepts type_data on a write, and the model that
# defines it. PHOTO_ALBUM is absent on purpose: its data comes from Immich
# album sync and the write paths refuse it outright, so there is no shape for a
# client to send. tests/unit/journal/test_journal_type_coverage.py fails if any
# other type is missing.
TYPE_DATA_MODELS: dict[JournalType, type[TypeDataModel]] = {
    JournalType.NOTE: NoteTypeData,
    JournalType.EVENT: EventTypeData,
    JournalType.MOOD_RATING: MoodRatingTypeData,
    JournalType.PLAN: PlanTypeData,
    JournalType.TRAVEL: TravelTypeData,
    JournalType.FITNESS: FitnessTypeData,
    JournalType.OUTDOOR_ACTIVITY: OutdoorActivityTypeData,
    JournalType.BUSHWALKING: BushwalkingTypeData,
    JournalType.JOGGING: JoggingTypeData,
    JournalType.ABSEILING_TRIP: AbseilingTripTypeData,
    JournalType.CANYONING: CanyoningTypeData,
    JournalType.CLIMBING: ClimbingTypeData,
    JournalType.KAYAKING: KayakingTypeData,
    JournalType.CROSS_COUNTRY_SKIING: CrossCountrySkiingTypeData,
    JournalType.CAVING: CavingTypeData,
    JournalType.CANOEING: CanoeingTypeData,
    JournalType.SNORKELLING: SnorkellingTypeData,
    JournalType.DIVING: DivingTypeData,
    JournalType.DOWNHILL_SKIING: DownhillSkiingTypeData,
    JournalType.OUTDOOR_PLANNING: OutdoorPlanningTypeData,
    JournalType.OUTDOOR_TRAINING: OutdoorTrainingTypeData,
    JournalType.GEAR_MAINTENANCE: GearMaintenanceTypeData,
    JournalType.GEAR_USAGE: GearUsageTypeData,
}

# Types whose type_data is written by an integration rather than a client.
INTEGRATION_MANAGED_TYPES: frozenset[JournalType] = frozenset({JournalType.PHOTO_ALBUM})


def accepted_fields(journal_type: JournalType) -> list[str]:
    """The field names ``journal_type`` accepts, for 'did you mean' messages."""
    model = TYPE_DATA_MODELS.get(journal_type)
    return sorted(model.model_fields) if model is not None else []
