"""Completeness guard for journal type-data history coverage (ITER12-002 Phase 2).

Every editable journal type's type-data fields must be **deliberately accounted
for** in `JournalWriteService._TYPE_DATA_TRACKED_FIELDS` — either tracked (so the
field's changes appear in journal history) or explicitly excluded with a reason.
These tests fail the moment a new `JournalType` is added, or a new field is added
to any type-data model, without a coverage decision being recorded here — so
"any new fields on all journal types" can never silently drop out of history.
"""

import dataclasses

from core_shared.models.journals import (
    AbseilingData,
    BushwalkingData,
    CalendarInfo,
    CanoeingData,
    CanyoningData,
    CavingData,
    ClimbingData,
    CrossCountrySkiingData,
    DivingData,
    DownhillSkiingData,
    FitnessData,
    GearMaintenanceData,
    GearUsageData,
    JoggingData,
    JournalType,
    KayakingData,
    MoodData,
    OutdoorActivityData,
    OutdoorPlanningData,
    OutdoorTrainingData,
    PlanData,
    SnorkellingData,
    TravelData,
)

from app.core.journal.services.journal_write_service import _TYPE_DATA_TRACKED_FIELDS

# Keys present on every type-data model that are structural, not content.
_STRUCTURAL_FIELDS = {"id", "journal_id", "created_at", "updated_at"}

# Single source of truth for this test: every JournalType -> its single-row
# type-data model, or None when the type has no such model (NOTE has no type
# data; PHOTO_ALBUM is Immich-synced via external_references, not a dataclass).
_TYPE_DATA_MODELS: dict[JournalType, type | None] = {
    JournalType.NOTE: None,
    JournalType.EVENT: CalendarInfo,
    JournalType.MOOD_RATING: MoodData,
    JournalType.PLAN: PlanData,
    JournalType.TRAVEL: TravelData,
    JournalType.PHOTO_ALBUM: None,
    JournalType.FITNESS: FitnessData,
    JournalType.OUTDOOR_ACTIVITY: OutdoorActivityData,
    JournalType.BUSHWALKING: BushwalkingData,
    JournalType.JOGGING: JoggingData,
    JournalType.ABSEILING_TRIP: AbseilingData,
    JournalType.CANYONING: CanyoningData,
    JournalType.CLIMBING: ClimbingData,
    JournalType.KAYAKING: KayakingData,
    JournalType.CROSS_COUNTRY_SKIING: CrossCountrySkiingData,
    JournalType.CAVING: CavingData,
    JournalType.CANOEING: CanoeingData,
    JournalType.SNORKELLING: SnorkellingData,
    JournalType.DIVING: DivingData,
    JournalType.DOWNHILL_SKIING: DownhillSkiingData,
    JournalType.OUTDOOR_PLANNING: OutdoorPlanningData,
    JournalType.OUTDOOR_TRAINING: OutdoorTrainingData,
    JournalType.GEAR_MAINTENANCE: GearMaintenanceData,
    JournalType.GEAR_USAGE: GearUsageData,
}

# Content fields that exist on a model but are intentionally NOT tracked, each
# with the reason. Keeping the reason here is the "coverage decision" record.
_EXCLUDED_FIELDS: dict[JournalType, dict[str, str]] = {
    JournalType.EVENT: {
        "event_start_date": (
            "denormalised from the base journal event_date_range, which is "
            "tracked as a base field; not edited via the type-data API"
        ),
        "event_end_date": (
            "denormalised from the base journal event_date_range, which is "
            "tracked as a base field; not edited via the type-data API"
        ),
    },
    # Nested child collections; their per-row history is integration/create
    # managed and is captured separately under ITER12-002 Phase 4.
    JournalType.PLAN: {"documents": "nested child collection (Phase 4)"},
    JournalType.TRAVEL: {
        "flights": "nested child collection (Phase 4)",
        "accommodations": "nested child collection (Phase 4)",
        "transportation": "nested child collection (Phase 4)",
    },
    # GEAR_USAGE has no update_type_data path (driven by checkout/checkin flows);
    # its history is out of scope for the type-data projection.
    JournalType.GEAR_USAGE: {
        "gear_item_id": "no type-data edit path (checkout/checkin flow)",
        "checkout_date": "no type-data edit path (checkout/checkin flow)",
        "checkin_date": "no type-data edit path (checkout/checkin flow)",
    },
}


def _content_fields(model: type) -> set[str]:
    return {f.name for f in dataclasses.fields(model)} - _STRUCTURAL_FIELDS


def test_every_journal_type_is_classified() -> None:
    """Adding a new JournalType must force a coverage decision in this test."""
    assert set(JournalType) == set(_TYPE_DATA_MODELS), (
        "Every JournalType must be mapped to a type-data model (or None). "
        f"Unclassified: {set(JournalType) - set(_TYPE_DATA_MODELS)}"
    )


def test_every_type_data_field_is_tracked_or_excluded() -> None:
    """No type-data field may be silently absent from history coverage."""
    for jtype, model in _TYPE_DATA_MODELS.items():
        if model is None:
            continue
        content = _content_fields(model)
        tracked = set(_TYPE_DATA_TRACKED_FIELDS.get(jtype, ()))
        excluded = set(_EXCLUDED_FIELDS.get(jtype, {}))

        uncovered = content - tracked - excluded
        assert not uncovered, (
            f"{jtype.value}: type-data field(s) {sorted(uncovered)} are neither "
            f"tracked for history nor excluded with a reason. Add them to "
            f"_TYPE_DATA_TRACKED_FIELDS or _EXCLUDED_FIELDS."
        )


def test_tracked_fields_are_real_model_fields() -> None:
    """A tracked field that does not exist on the model is a registry bug."""
    for jtype, tracked in _TYPE_DATA_TRACKED_FIELDS.items():
        model = _TYPE_DATA_MODELS[jtype]
        assert model is not None, f"{jtype.value} tracks fields but has no model"
        content = _content_fields(model)
        unknown = set(tracked) - content
        assert not unknown, (
            f"{jtype.value}: tracked field(s) {sorted(unknown)} are not on "
            f"{model.__name__}; remove them or fix the name."
        )


def test_tracked_and_excluded_do_not_overlap() -> None:
    for jtype, excluded in _EXCLUDED_FIELDS.items():
        tracked = set(_TYPE_DATA_TRACKED_FIELDS.get(jtype, ()))
        overlap = tracked & set(excluded)
        assert not overlap, (
            f"{jtype.value}: {sorted(overlap)} both tracked and excluded"
        )
