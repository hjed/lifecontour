"""Unit tests for the incomplete outdoor activity evaluator.

Pins the three incompleteness rules and their exemptions:

1. No attributes set — a present subtype row whose own fillable fields are all
   unset (value equals the dataclass default; the models reject blank strings
   at construction, so defaults are the only empty values).
   Fieldless subtypes are exempt, derived from the absence of fillable fields.
2. Missing template — an abseiling row with no ``template_id``.
3. No participants — an outdoor journal with zero participants, unless
   bushwalking is its only subtype; a subtype-less outdoor journal is flagged.
"""

import datetime
from uuid import uuid4

import pytest

from core_shared.models.journals import (
    SUBTYPE_FACTS_FIELDS,
    AbseilingData,
    BushwalkingData,
    CanoeingData,
    CanyoningData,
    CavingData,
    ClimbingData,
    DivingData,
    DownhillSkiingData,
    EventDateRange,
    IncompletenessReason,
    KayakingData,
    OutdoorActivityFacts,
    OutdoorActivitySubtype,
    SnorkellingData,
    evaluate_incompleteness,
    fillable_fields,
)

JOURNAL_ID = 1


def make_facts(**overrides: object) -> OutdoorActivityFacts:
    """Build facts for a journal that matches no rule unless overridden."""
    base: dict[str, object] = {
        "journal_id": JOURNAL_ID,
        "title": "Test trip",
        "event_date_range": EventDateRange(
            start=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
            end=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        ),
        "participant_count": 1,
    }
    base.update(overrides)
    return OutdoorActivityFacts(**base)  # type: ignore[arg-type]


class TestRuleNoAttributes:
    def test_empty_subtype_row_flags_no_attributes(self) -> None:
        facts = make_facts(canoeing_data=CanoeingData(journal_id=JOURNAL_ID))

        result = evaluate_incompleteness(facts)

        assert result is not None
        assert result.reasons == [IncompletenessReason.NO_ATTRIBUTES]
        assert result.journal_id == JOURNAL_ID
        assert result.title == "Test trip"
        assert result.event_date_range == facts.event_date_range
        assert result.subtypes == [OutdoorActivitySubtype.CANOEING]

    def test_subtype_with_attribute_set_not_flagged(self) -> None:
        facts = make_facts(
            canoeing_data=CanoeingData(journal_id=JOURNAL_ID, water_type="river")
        )

        assert evaluate_incompleteness(facts) is None

    @pytest.mark.parametrize(
        ("facts_attr", "model"),
        [
            ("snorkelling_data", SnorkellingData),
            ("diving_data", DivingData),
            ("downhill_skiing_data", DownhillSkiingData),
        ],
    )
    def test_fieldless_subtypes_exempt_from_no_attributes(
        self, facts_attr: str, model: type
    ) -> None:
        facts = make_facts(**{facts_attr: model(journal_id=JOURNAL_ID)})

        assert evaluate_incompleteness(facts) is None

    @pytest.mark.parametrize("model", [SnorkellingData, DivingData, DownhillSkiingData])
    def test_fieldless_exemption_is_derived_not_hardcoded(self, model: type) -> None:
        assert fillable_fields(model) == ()

    def test_canyoning_journal_with_empty_dependency_bushwalking_row_flagged(
        self,
    ) -> None:
        facts = make_facts(
            bushwalking_data=BushwalkingData(journal_id=JOURNAL_ID),
            abseiling_data=AbseilingData(
                journal_id=JOURNAL_ID, template_id=uuid4(), number_of_abseils=3
            ),
            canyoning_data=CanyoningData(journal_id=JOURNAL_ID, french_grade="v3a2IV"),
        )

        result = evaluate_incompleteness(facts)

        assert result is not None
        assert result.reasons == [IncompletenessReason.NO_ATTRIBUTES]

    def test_no_attributes_reason_appears_once_for_multiple_empty_subtypes(
        self,
    ) -> None:
        facts = make_facts(
            bushwalking_data=BushwalkingData(journal_id=JOURNAL_ID),
            abseiling_data=AbseilingData(journal_id=JOURNAL_ID, template_id=uuid4()),
            canyoning_data=CanyoningData(journal_id=JOURNAL_ID),
        )

        result = evaluate_incompleteness(facts)

        assert result is not None
        assert result.reasons.count(IncompletenessReason.NO_ATTRIBUTES) == 1

    def test_climbing_indoor_false_treated_as_unset(self) -> None:
        facts = make_facts(
            climbing_data=ClimbingData(journal_id=JOURNAL_ID, indoor=False)
        )

        result = evaluate_incompleteness(facts)

        assert result is not None
        assert result.reasons == [IncompletenessReason.NO_ATTRIBUTES]

    def test_climbing_indoor_true_counts_as_attribute(self) -> None:
        facts = make_facts(
            climbing_data=ClimbingData(journal_id=JOURNAL_ID, indoor=True)
        )

        assert evaluate_incompleteness(facts) is None

    def test_canyoning_explicit_false_boolean_counts_as_attribute(self) -> None:
        facts = make_facts(
            canyoning_data=CanyoningData(journal_id=JOURNAL_ID, is_vertical=False)
        )

        assert evaluate_incompleteness(facts) is None

    def test_abseil_pitches_count_as_rule1_attributes(self) -> None:
        facts = make_facts(
            abseiling_data=AbseilingData(journal_id=JOURNAL_ID, template_id=uuid4()),
            abseil_pitch_count=2,
        )

        assert evaluate_incompleteness(facts) is None

    def test_template_id_does_not_count_as_rule1_attribute(self) -> None:
        facts = make_facts(
            abseiling_data=AbseilingData(journal_id=JOURNAL_ID, template_id=uuid4()),
        )

        result = evaluate_incompleteness(facts)

        assert result is not None
        assert result.reasons == [IncompletenessReason.NO_ATTRIBUTES]


class TestRuleMissingTemplate:
    def test_missing_template_flagged_for_plain_abseiling_trip(self) -> None:
        facts = make_facts(
            abseiling_data=AbseilingData(journal_id=JOURNAL_ID, number_of_abseils=3),
            abseil_pitch_count=3,
        )

        result = evaluate_incompleteness(facts)

        assert result is not None
        assert result.reasons == [IncompletenessReason.MISSING_TEMPLATE]

    @pytest.mark.parametrize(
        ("facts_attr", "subtype_data"),
        [
            (
                "canyoning_data",
                CanyoningData(journal_id=JOURNAL_ID, french_grade="v3a2IV"),
            ),
            (
                "climbing_data",
                ClimbingData(journal_id=JOURNAL_ID, climbing_type="sport"),
            ),
            ("caving_data", CavingData(journal_id=JOURNAL_ID, is_vertical=True)),
        ],
    )
    def test_missing_template_flagged_for_each_abseiling_derived_type(
        self, facts_attr: str, subtype_data: object
    ) -> None:
        facts = make_facts(
            abseiling_data=AbseilingData(journal_id=JOURNAL_ID, number_of_abseils=1),
            **{facts_attr: subtype_data},
        )

        result = evaluate_incompleteness(facts)

        assert result is not None
        assert result.reasons == [IncompletenessReason.MISSING_TEMPLATE]

    def test_template_set_not_flagged_for_missing_template(self) -> None:
        facts = make_facts(
            abseiling_data=AbseilingData(
                journal_id=JOURNAL_ID, template_id=uuid4(), number_of_abseils=1
            ),
        )

        assert evaluate_incompleteness(facts) is None


class TestRuleNoParticipants:
    def test_no_participants_flagged_for_non_bushwalking_subtype(self) -> None:
        facts = make_facts(
            kayaking_data=KayakingData(journal_id=JOURNAL_ID, water_type="river"),
            participant_count=0,
        )

        result = evaluate_incompleteness(facts)

        assert result is not None
        assert result.reasons == [IncompletenessReason.NO_PARTICIPANTS]

    def test_bushwalking_only_journal_exempt_from_no_participants(self) -> None:
        facts = make_facts(
            bushwalking_data=BushwalkingData(
                journal_id=JOURNAL_ID, track_grading="Grade 3"
            ),
            participant_count=0,
        )

        assert evaluate_incompleteness(facts) is None

    def test_canyoning_with_bushwalking_dependency_row_not_exempt_from_no_participants(
        self,
    ) -> None:
        facts = make_facts(
            bushwalking_data=BushwalkingData(
                journal_id=JOURNAL_ID, track_grading="Grade 3"
            ),
            abseiling_data=AbseilingData(
                journal_id=JOURNAL_ID, template_id=uuid4(), number_of_abseils=1
            ),
            canyoning_data=CanyoningData(journal_id=JOURNAL_ID, french_grade="v3a2IV"),
            participant_count=0,
        )

        result = evaluate_incompleteness(facts)

        assert result is not None
        assert result.reasons == [IncompletenessReason.NO_PARTICIPANTS]

    def test_outdoor_training_counts_for_rule3_but_not_rule1(self) -> None:
        flagged = make_facts(has_outdoor_training=True, participant_count=0)
        satisfied = make_facts(has_outdoor_training=True, participant_count=1)

        result = evaluate_incompleteness(flagged)

        assert result is not None
        assert result.reasons == [IncompletenessReason.NO_PARTICIPANTS]
        assert result.subtypes == [OutdoorActivitySubtype.OUTDOOR_TRAINING]
        assert evaluate_incompleteness(satisfied) is None


class TestCombined:
    def test_plain_outdoor_activity_without_subtypes_flagged_for_no_participants(
        self,
    ) -> None:
        """A subtype-less outdoor journal is still a non-bushwalking activity."""
        flagged = make_facts(participant_count=0)
        satisfied = make_facts(participant_count=1)

        result = evaluate_incompleteness(flagged)

        assert result is not None
        assert result.reasons == [IncompletenessReason.NO_PARTICIPANTS]
        assert result.subtypes == []
        assert evaluate_incompleteness(satisfied) is None

    def test_all_three_reasons_combined(self) -> None:
        facts = make_facts(
            bushwalking_data=BushwalkingData(journal_id=JOURNAL_ID),
            abseiling_data=AbseilingData(journal_id=JOURNAL_ID),
            canyoning_data=CanyoningData(journal_id=JOURNAL_ID),
            participant_count=0,
        )

        result = evaluate_incompleteness(facts)

        assert result is not None
        assert result.reasons == [
            IncompletenessReason.NO_ATTRIBUTES,
            IncompletenessReason.MISSING_TEMPLATE,
            IncompletenessReason.NO_PARTICIPANTS,
        ]
        assert result.subtypes == [
            OutdoorActivitySubtype.BUSHWALKING,
            OutdoorActivitySubtype.ABSEILING_TRIP,
            OutdoorActivitySubtype.CANYONING,
        ]


class TestRegistry:
    def test_registry_covers_every_outdoor_subtype_except_training(self) -> None:
        assert set(SUBTYPE_FACTS_FIELDS) == set(OutdoorActivitySubtype) - {
            OutdoorActivitySubtype.OUTDOOR_TRAINING
        }
