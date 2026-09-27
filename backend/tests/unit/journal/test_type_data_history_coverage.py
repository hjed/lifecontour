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
    AbseilPitch,
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
    GearUsageItem,
    JoggingData,
    JournalType,
    KayakingData,
    MoodData,
    OutdoorActivityData,
    OutdoorPlanningData,
    OutdoorTrainingData,
    PlanData,
    PlanDocument,
    SnorkellingData,
    TravelData,
)

from app.core.journal.services.journal_write_service import (
    _TYPE_DATA_COLLECTIONS,
    _TYPE_DATA_TRACKED_FIELDS,
)

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
    # Nested child collection: per-row history is produced via the
    # _TYPE_DATA_COLLECTIONS registry (plan:doc:<id>:<field>), not the single-row
    # tracked registry (ITER12-002 Phase 4).
    JournalType.PLAN: {
        "documents": "per-row history via plan:doc:<id>:<field> (Phase 4)"
    },
    # TRAVEL nested children have no write path yet (the type-data update endpoint
    # rejects TRAVEL and nothing calls save_flight/accommodation/transportation),
    # so there is no write to record. Deferred until TRAVEL nested editing exists.
    JournalType.GEAR_USAGE: {
        "items": "per-row history via gear_usage:item:<gear_item_id>:<field>"
    },
    JournalType.TRAVEL: {
        "flights": "no write path — deferred until TRAVEL nested editing exists",
        "accommodations": "no write path — deferred until TRAVEL nested editing exists",
        "transportation": "no write path — deferred until TRAVEL nested editing exists",
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


# The per-row child model backing each registered nested collection (ITER12-002
# Phase 4). PLAN documents are a field on PlanData; ABSEIL pitches are a separate
# table (AbseilPitch), not a field on AbseilingData.
_COLLECTION_ROW_MODELS: dict[JournalType, type] = {
    JournalType.PLAN: PlanDocument,
    JournalType.ABSEILING_TRIP: AbseilPitch,
    JournalType.GEAR_USAGE: GearUsageItem,
}


def test_collection_per_row_fields_are_real_model_fields() -> None:
    """Every nested-collection per-row tracked field must exist on its row model.

    Guards the Phase 4 ``_TYPE_DATA_COLLECTIONS`` registry the same way
    ``test_tracked_fields_are_real_model_fields`` guards the single-row registry.
    """
    for jtype, specs in _TYPE_DATA_COLLECTIONS.items():
        row_model = _COLLECTION_ROW_MODELS.get(jtype)
        assert row_model is not None, (
            f"{jtype.value} has a collection spec but no row model in this test"
        )
        content = _content_fields(row_model)
        for spec in specs:
            unknown = set(spec.fields) - content
            assert not unknown, (
                f"{jtype.value}: collection '{spec.field_name}' tracks per-row "
                f"field(s) {sorted(unknown)} not on {row_model.__name__}."
            )


def test_collection_field_on_single_row_model_is_excluded() -> None:
    """A collection that is also a field on the single-row model must be excluded.

    Keeps the two registries consistent: PLAN.documents is a field on PlanData, so
    it must be excluded-with-reason from the single-row tracked registry (it is
    covered per-row instead). Separate-table collections (ABSEIL pitches) are not
    single-row fields, so they need no exclusion.
    """
    for jtype, specs in _TYPE_DATA_COLLECTIONS.items():
        model = _TYPE_DATA_MODELS[jtype]
        if model is None:
            continue
        single_row_fields = _content_fields(model)
        excluded = set(_EXCLUDED_FIELDS.get(jtype, {}))
        for spec in specs:
            if spec.field_name in single_row_fields:
                assert spec.field_name in excluded, (
                    f"{jtype.value}: collection '{spec.field_name}' is a field on "
                    f"{model.__name__} but is not excluded-with-reason; the "
                    f"single-row coverage guard would flag it."
                )
