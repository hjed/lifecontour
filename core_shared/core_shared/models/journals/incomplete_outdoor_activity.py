"""Read-model contracts and pure rules for the incomplete outdoor activities review.

The incomplete review is a projection over existing tables — no new journal
state. A repository gathers per-journal :class:`OutdoorActivityFacts` and
:func:`evaluate_incompleteness` applies the three product rules:

1. **No attributes set** — a present subtype row whose own type-specific fields
   are all unset. A field is unset when its value equals the dataclass default
   (so ``ClimbingData.indoor`` — ``False`` by default — counts as unset at
   ``False``, while an explicit ``CanyoningData.is_vertical = False`` — default
   ``None`` — counts as set). Subtypes with no fillable fields are exempt —
   the exemption is derived from the model's fields, never a hard-coded list. Abseil pitches count as abseiling
   attributes; ``template_id`` does not (rule 2 owns it). Dependency-added
   subtype rows (e.g. the bushwalking row on a canyoning journal) are evaluated
   like any other — types are detected purely by row presence.
2. **Missing template** — an abseiling row (present on every abseiling-derived
   journal via type dependencies) with no consolidated ``template_id``.
3. **No participants** — an outdoor journal with zero PARTICIPANT contacts,
   unless bushwalking is its only subtype (solo hikes are expected). A
   subtype-less OUTDOOR_ACTIVITY journal is still an outdoor activity other
   than bushwalking, so it is flagged (product decision, 2026-07-07).

A journal matching no rule yields ``None`` and never appears in the review.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .abseiling_data import AbseilingData
from .bushwalking_data import BushwalkingData
from .canoeing_data import CanoeingData
from .canyoning_data import CanyoningData
from .caving_data import CavingData
from .climbing_data import ClimbingData
from .cross_country_skiing_data import CrossCountrySkiingData
from .diving_data import DivingData
from .downhill_skiing_data import DownhillSkiingData
from .kayaking_data import KayakingData
from .outdoor_activity_subtypes import OutdoorActivitySubtype
from .snorkelling_data import SnorkellingData
from .value_objects import EventDateRange


class IncompletenessReason(StrEnum):
    """Why an outdoor activity journal is flagged as incomplete."""

    NO_ATTRIBUTES = "no_attributes"
    MISSING_TEMPLATE = "missing_template"
    NO_PARTICIPANTS = "no_participants"


@dataclass
class OutdoorActivityFacts:
    """Per-journal facts the incompleteness rules are evaluated against.

    One instance per outdoor journal (a journal with an
    ``journal_outdoor_activity_data`` row), carrying each present subtype's
    data row, an OUTDOOR_TRAINING presence flag (excluded from rule 1 by the
    spec, but an outdoor subtype for rule 3), and the participant/pitch counts.
    """

    journal_id: int
    title: str
    event_date_range: EventDateRange
    bushwalking_data: BushwalkingData | None = None
    abseiling_data: AbseilingData | None = None
    canyoning_data: CanyoningData | None = None
    climbing_data: ClimbingData | None = None
    kayaking_data: KayakingData | None = None
    cross_country_skiing_data: CrossCountrySkiingData | None = None
    caving_data: CavingData | None = None
    canoeing_data: CanoeingData | None = None
    snorkelling_data: SnorkellingData | None = None
    diving_data: DivingData | None = None
    downhill_skiing_data: DownhillSkiingData | None = None
    has_outdoor_training: bool = False
    participant_count: int = 0
    abseil_pitch_count: int = 0


@dataclass
class IncompleteOutdoorActivity:
    """An outdoor journal flagged by the incomplete review, with its reasons.

    ``dismissed`` is review state, not a rule outcome: evaluation always leaves
    it ``False`` and the service marks it when listing dismissed entries.
    """

    journal_id: int
    title: str
    event_date_range: EventDateRange
    subtypes: list[OutdoorActivitySubtype]
    reasons: list[IncompletenessReason]
    dismissed: bool = False


# Maps each rule-1-relevant outdoor subtype to its facts attribute and data
# model. OUTDOOR_TRAINING is deliberately absent: the spec scopes rule 1 to the
# core outdoor subtypes, so training journals carry only a presence flag.
SUBTYPE_FACTS_FIELDS: dict[OutdoorActivitySubtype, tuple[str, type[Any]]] = {
    OutdoorActivitySubtype.BUSHWALKING: ("bushwalking_data", BushwalkingData),
    OutdoorActivitySubtype.ABSEILING_TRIP: ("abseiling_data", AbseilingData),
    OutdoorActivitySubtype.CANYONING: ("canyoning_data", CanyoningData),
    OutdoorActivitySubtype.CLIMBING: ("climbing_data", ClimbingData),
    OutdoorActivitySubtype.KAYAKING: ("kayaking_data", KayakingData),
    OutdoorActivitySubtype.CROSS_COUNTRY_SKIING: (
        "cross_country_skiing_data",
        CrossCountrySkiingData,
    ),
    OutdoorActivitySubtype.CAVING: ("caving_data", CavingData),
    OutdoorActivitySubtype.CANOEING: ("canoeing_data", CanoeingData),
    OutdoorActivitySubtype.SNORKELLING: ("snorkelling_data", SnorkellingData),
    OutdoorActivitySubtype.DIVING: ("diving_data", DivingData),
    OutdoorActivitySubtype.DOWNHILL_SKIING: (
        "downhill_skiing_data",
        DownhillSkiingData,
    ),
}

# Fields that are not user-fillable attributes: keys/timestamps, and the
# template reference (rule 2's concern, not an attribute).
_NON_ATTRIBUTE_FIELDS = frozenset(
    {"journal_id", "template_id", "created_at", "updated_at"}
)


def fillable_fields(model: type[Any]) -> tuple[dataclasses.Field[Any], ...]:
    """The user-fillable attribute fields of a subtype data model.

    Derived from the dataclass definition, so a subtype gaining or losing a
    column automatically flows into rule 1 and the fieldless exemption.
    """
    return tuple(
        f for f in dataclasses.fields(model) if f.name not in _NON_ATTRIBUTE_FIELDS
    )


def _is_unset(value: object, field_def: dataclasses.Field[Any]) -> bool:
    """A field is unset when it equals its dataclass default.

    The subtype models reject blank strings at construction, so defaults are
    the only "empty" values a hydrated data row can carry.
    """
    return value == field_def.default


def _has_no_attributes(
    subtype: OutdoorActivitySubtype, data: object, abseil_pitch_count: int
) -> bool:
    fields = fillable_fields(type(data))
    if not fields:
        # Fieldless subtypes could never satisfy the rule — exempt.
        return False
    if subtype is OutdoorActivitySubtype.ABSEILING_TRIP and abseil_pitch_count > 0:
        return False
    return all(_is_unset(getattr(data, f.name), f) for f in fields)


def evaluate_incompleteness(
    facts: OutdoorActivityFacts,
) -> IncompleteOutdoorActivity | None:
    """Apply the three incompleteness rules; ``None`` when nothing matches."""
    present: list[tuple[OutdoorActivitySubtype, object]] = [
        (subtype, data)
        for subtype, (facts_attr, _model) in SUBTYPE_FACTS_FIELDS.items()
        if (data := getattr(facts, facts_attr)) is not None
    ]
    subtypes = [subtype for subtype, _data in present]
    if facts.has_outdoor_training:
        subtypes.append(OutdoorActivitySubtype.OUTDOOR_TRAINING)

    reasons: list[IncompletenessReason] = []
    if any(
        _has_no_attributes(subtype, data, facts.abseil_pitch_count)
        for subtype, data in present
    ):
        reasons.append(IncompletenessReason.NO_ATTRIBUTES)
    if facts.abseiling_data is not None and facts.abseiling_data.template_id is None:
        reasons.append(IncompletenessReason.MISSING_TEMPLATE)
    bushwalking_only = set(subtypes) == {OutdoorActivitySubtype.BUSHWALKING}
    if facts.participant_count == 0 and not bushwalking_only:
        reasons.append(IncompletenessReason.NO_PARTICIPANTS)

    if not reasons:
        return None
    return IncompleteOutdoorActivity(
        journal_id=facts.journal_id,
        title=facts.title,
        event_date_range=facts.event_date_range,
        subtypes=subtypes,
        reasons=reasons,
    )
