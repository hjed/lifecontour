"""Unit tests for the pure series-merge planner and its field policies."""

import datetime
import uuid
from zoneinfo import ZoneInfo

import pytest
from core_shared.models.journals import (
    CalendarInfo,
    EventDateRange,
    Journal,
    JournalValidationError,
)

from app.core.journal.models.series_merge import (
    DayOutcome,
    SeriesDayOutcomeKind,
    SeriesFieldPolicy,
    SeriesMember,
    SeriesMergeField,
    SeriesMergePair,
    SeriesMergePolicies,
    overrides_for_pair,
    plan_series_merge,
)

SYDNEY = ZoneInfo("Australia/Sydney")
UTC = ZoneInfo("UTC")
CALENDAR_A = uuid.UUID("00000000-0000-0000-0000-00000000000a")
CALENDAR_B = uuid.UUID("00000000-0000-0000-0000-00000000000b")


def _member(
    journal_id: int,
    start: datetime.datetime,
    *,
    title: str = "Weekly sync",
    content: str = "",
    end: datetime.datetime | None = None,
    calendar_id: uuid.UUID | None = CALENDAR_A,
    location: str | None = None,
    description: str | None = None,
    start_time: datetime.time | None = None,
    end_time: datetime.time | None = None,
    timezone: str | None = None,
    is_all_day: bool = False,
) -> SeriesMember:
    journal = Journal(
        id=journal_id,
        user_id="user-1",
        title=title,
        content=content,
        event_date_range=EventDateRange(start=start, end=end or start),
    )
    calendar_info = (
        CalendarInfo(
            calendar_id=calendar_id,
            journal_id=journal_id,
            location=location,
            description=description,
            start_time=start_time,
            end_time=end_time,
            timezone=timezone,
            is_all_day=is_all_day,
            validate=False,
        )
        if calendar_id is not None
        else None
    )
    return SeriesMember(journal=journal, calendar_info=calendar_info)


def _at(day: int, hour: int = 0, month: int = 8) -> datetime.datetime:
    return datetime.datetime(2026, month, day, hour, tzinfo=UTC)


def _only(days: tuple[DayOutcome, ...]) -> DayOutcome:
    assert len(days) == 1
    return days[0]


class TestPairingByLocalDate:
    def test_pairs_one_source_and_one_destination_on_the_same_local_day(
        self,
    ) -> None:
        plan = plan_series_merge(
            source_members=[_member(1, _at(3, 9))],
            destination_members=[_member(2, _at(3, 1))],
            tz=UTC,
            policies=SeriesMergePolicies(),
        )

        day = _only(plan.days)
        assert day.kind is SeriesDayOutcomeKind.CANDIDATE
        assert day.date == datetime.date(2026, 8, 3)
        assert plan.candidates == (SeriesMergePair(1, 2),)

    def test_groups_by_the_users_timezone_not_utc(self) -> None:
        # 20:00 UTC on the 2nd is 06:00 on the 3rd in Sydney, the same local
        # day as 01:00 UTC on the 3rd (11:00 Sydney).
        plan = plan_series_merge(
            source_members=[_member(1, _at(2, 20))],
            destination_members=[_member(2, _at(3, 1))],
            tz=SYDNEY,
            policies=SeriesMergePolicies(),
        )

        day = _only(plan.days)
        assert day.kind is SeriesDayOutcomeKind.CANDIDATE
        assert day.date == datetime.date(2026, 8, 3)

    def test_the_same_instants_are_different_days_in_utc(self) -> None:
        plan = plan_series_merge(
            source_members=[_member(1, _at(2, 20))],
            destination_members=[_member(2, _at(3, 1))],
            tz=UTC,
            policies=SeriesMergePolicies(),
        )

        assert [d.kind for d in plan.days] == [
            SeriesDayOutcomeKind.UNPAIRED,
            SeriesDayOutcomeKind.UNPAIRED,
        ]
        assert plan.candidates == ()

    def test_pairs_across_a_daylight_saving_transition_day(self) -> None:
        # Sydney leaves DST at 03:00 on 5 April 2026: the day is 25 hours long.
        # 13:30 UTC on the 4th is 00:30 on the 5th (AEDT, +11); 13:30 UTC on
        # the 5th is 23:30 on the 5th (AEST, +10). Both are the 5th.
        plan = plan_series_merge(
            source_members=[_member(1, _at(4, 13, month=4) + _half_hour())],
            destination_members=[_member(2, _at(5, 13, month=4) + _half_hour())],
            tz=SYDNEY,
            policies=SeriesMergePolicies(),
        )

        day = _only(plan.days)
        assert day.kind is SeriesDayOutcomeKind.CANDIDATE
        assert day.date == datetime.date(2026, 4, 5)

    def test_days_are_ordered_and_unpaired_sides_are_reported(self) -> None:
        plan = plan_series_merge(
            source_members=[_member(1, _at(10)), _member(3, _at(3))],
            destination_members=[_member(2, _at(5))],
            tz=UTC,
            policies=SeriesMergePolicies(),
        )

        assert [(d.date.day, d.kind) for d in plan.days] == [
            (3, SeriesDayOutcomeKind.UNPAIRED),
            (5, SeriesDayOutcomeKind.UNPAIRED),
            (10, SeriesDayOutcomeKind.UNPAIRED),
        ]
        assert plan.days[0].source_journal_ids == (3,)
        assert plan.days[1].destination_journal_ids == (2,)

    def test_a_day_with_two_journals_on_one_side_is_ambiguous(self) -> None:
        plan = plan_series_merge(
            source_members=[_member(1, _at(3, 9)), _member(3, _at(3, 15))],
            destination_members=[_member(2, _at(3, 9))],
            tz=UTC,
            policies=SeriesMergePolicies(),
        )

        day = _only(plan.days)
        assert day.kind is SeriesDayOutcomeKind.AMBIGUOUS
        assert day.source_journal_ids == (1, 3)
        assert day.destination_journal_ids == (2,)
        assert plan.candidates == ()

    def test_a_journal_in_both_series_is_already_shared_and_not_paired(
        self,
    ) -> None:
        shared = _member(1, _at(3))
        plan = plan_series_merge(
            source_members=[shared, _member(3, _at(3))],
            destination_members=[shared, _member(2, _at(3))],
            tz=UTC,
            policies=SeriesMergePolicies(),
        )

        assert [(d.kind, d.source_journal_ids) for d in plan.days] == [
            (SeriesDayOutcomeKind.ALREADY_SHARED, (1,)),
            (SeriesDayOutcomeKind.CANDIDATE, (3,)),
        ]
        assert plan.candidates == (SeriesMergePair(3, 2),)

    def test_same_calendar_pairs_are_candidates(self) -> None:
        plan = plan_series_merge(
            source_members=[_member(1, _at(3), calendar_id=CALENDAR_A)],
            destination_members=[_member(2, _at(3), calendar_id=CALENDAR_A)],
            tz=UTC,
            policies=SeriesMergePolicies(),
        )

        assert plan.candidates == (SeriesMergePair(1, 2),)


class TestSkipIfDifferent:
    @pytest.mark.parametrize(
        ("field", "source_kwargs", "destination_kwargs"),
        [
            (SeriesMergeField.TITLE, {"title": "A"}, {"title": "B"}),
            (SeriesMergeField.CONTENT, {"content": "a"}, {"content": "b"}),
            (SeriesMergeField.LOCATION, {"location": "Here"}, {"location": "There"}),
            (
                SeriesMergeField.EVENT_DESCRIPTION,
                {"description": "a"},
                {"description": "b"},
            ),
            (
                SeriesMergeField.TIMING,
                {"start_time": datetime.time(9), "end_time": datetime.time(10)},
                {"start_time": datetime.time(11), "end_time": datetime.time(12)},
            ),
        ],
    )
    def test_skips_the_pair_when_the_field_differs(
        self,
        field: SeriesMergeField,
        source_kwargs: dict[str, object],
        destination_kwargs: dict[str, object],
    ) -> None:
        policies = SeriesMergePolicies.with_policy(
            field, SeriesFieldPolicy.SKIP_IF_DIFFERENT
        )

        plan = plan_series_merge(
            source_members=[_member(1, _at(3), **source_kwargs)],  # type: ignore[arg-type]
            destination_members=[_member(2, _at(3), **destination_kwargs)],  # type: ignore[arg-type]
            tz=UTC,
            policies=policies,
        )

        day = _only(plan.days)
        assert day.kind is SeriesDayOutcomeKind.SKIPPED
        assert day.skip_reason is field
        assert field in day.differing_fields
        assert plan.candidates == ()

    def test_one_empty_side_is_not_a_difference(self) -> None:
        policies = SeriesMergePolicies(
            location=SeriesFieldPolicy.SKIP_IF_DIFFERENT,
            content=SeriesFieldPolicy.SKIP_IF_DIFFERENT,
        )

        plan = plan_series_merge(
            source_members=[_member(1, _at(3), location="Here", content="")],
            destination_members=[_member(2, _at(3), location=None, content="b")],
            tz=UTC,
            policies=policies,
        )

        day = _only(plan.days)
        assert day.kind is SeriesDayOutcomeKind.CANDIDATE
        assert day.differing_fields == ()

    def test_a_non_event_journal_compares_timing_by_date_range_only(
        self,
    ) -> None:
        plan = plan_series_merge(
            source_members=[_member(1, _at(3, 9), calendar_id=None)],
            destination_members=[
                _member(
                    2,
                    _at(3, 9),
                    start_time=datetime.time(9),
                    end_time=datetime.time(10),
                )
            ],
            tz=UTC,
            policies=SeriesMergePolicies(timing=SeriesFieldPolicy.SKIP_IF_DIFFERENT),
        )

        assert _only(plan.days).kind is SeriesDayOutcomeKind.CANDIDATE

    def test_equal_values_are_not_a_difference(self) -> None:
        plan = plan_series_merge(
            source_members=[_member(1, _at(3), title="Same")],
            destination_members=[_member(2, _at(3), title="Same")],
            tz=UTC,
            policies=SeriesMergePolicies(title=SeriesFieldPolicy.SKIP_IF_DIFFERENT),
        )

        assert _only(plan.days).kind is SeriesDayOutcomeKind.CANDIDATE

    def test_differences_under_other_policies_are_reported_but_merge(
        self,
    ) -> None:
        plan = plan_series_merge(
            source_members=[_member(1, _at(3), title="A", location="Here")],
            destination_members=[_member(2, _at(3), title="B", location="There")],
            tz=UTC,
            policies=SeriesMergePolicies(),
        )

        day = _only(plan.days)
        assert day.kind is SeriesDayOutcomeKind.CANDIDATE
        assert day.differing_fields == (
            SeriesMergeField.TITLE,
            SeriesMergeField.LOCATION,
        )


class TestPolicies:
    def test_defaults_keep_destination_and_combine_content(self) -> None:
        policies = SeriesMergePolicies()

        assert policies.title is SeriesFieldPolicy.DESTINATION
        assert policies.content is SeriesFieldPolicy.COMBINE
        assert policies.timing is SeriesFieldPolicy.DESTINATION
        assert policies.location is SeriesFieldPolicy.DESTINATION
        assert policies.event_description is SeriesFieldPolicy.DESTINATION

    @pytest.mark.parametrize(
        "field",
        [f for f in SeriesMergeField if f is not SeriesMergeField.CONTENT],
    )
    def test_combine_is_only_allowed_for_content(self, field: SeriesMergeField) -> None:
        with pytest.raises(JournalValidationError):
            SeriesMergePolicies.with_policy(field, SeriesFieldPolicy.COMBINE)


class TestPoliciesFromMapping:
    def test_named_fields_are_set_and_the_rest_keep_defaults(self) -> None:
        policies = SeriesMergePolicies.from_mapping({"title": "source"})

        assert policies == SeriesMergePolicies(title=SeriesFieldPolicy.SOURCE)

    def test_none_is_the_defaults(self) -> None:
        assert SeriesMergePolicies.from_mapping(None) == SeriesMergePolicies()

    @pytest.mark.parametrize(
        "raw", [{"colour": "source"}, {"title": "whichever"}, {"title": "combine"}]
    )
    def test_unknown_or_invalid_input_is_a_validation_error(
        self, raw: dict[str, str]
    ) -> None:
        with pytest.raises(JournalValidationError):
            SeriesMergePolicies.from_mapping(raw)


class TestOverridesForPair:
    def test_destination_policy_pins_the_destination_values(self) -> None:
        source = _member(1, _at(3, 9), title="Source", location="Here")
        destination = _member(2, _at(3, 11), title="Dest", location="There")

        overrides = overrides_for_pair(source, destination, SeriesMergePolicies())

        assert overrides["title"] == "Dest"
        assert overrides["event_date_range"] == {
            "start": _at(3, 11).isoformat(),
            "end": _at(3, 11).isoformat(),
        }
        assert overrides["type_data"]["event"]["location"] == "There"
        assert "content" not in overrides

    def test_source_policy_takes_the_source_values(self) -> None:
        source = _member(
            1,
            _at(3, 9),
            title="Source",
            content="source notes",
            description="source desc",
            start_time=datetime.time(19, 30),
            end_time=datetime.time(20, 30),
            timezone="Australia/Sydney",
        )
        destination = _member(
            2, _at(3, 11), title="Dest", content="dest notes", description="d"
        )
        policies = SeriesMergePolicies(
            title=SeriesFieldPolicy.SOURCE,
            content=SeriesFieldPolicy.SOURCE,
            timing=SeriesFieldPolicy.SOURCE,
            event_description=SeriesFieldPolicy.SOURCE,
        )

        overrides = overrides_for_pair(source, destination, policies)

        assert overrides["title"] == "Source"
        assert overrides["content"] == "source notes"
        assert overrides["event_date_range"]["start"] == _at(3, 9).isoformat()
        assert overrides["type_data"]["event"] == {
            "start_time": "19:30:00",
            "end_time": "20:30:00",
            "timezone": "Australia/Sydney",
            "is_all_day": False,
            "description": "source desc",
        }

    def test_an_empty_preferred_value_is_filled_from_the_other_side(self) -> None:
        source = _member(1, _at(3), location="Here", description="a")
        destination = _member(2, _at(3), location=None, description=None)

        overrides = overrides_for_pair(source, destination, SeriesMergePolicies())

        assert overrides["type_data"]["event"]["location"] == "Here"
        assert overrides["type_data"]["event"]["description"] == "a"

    def test_both_empty_emits_no_override(self) -> None:
        source = _member(1, _at(3))
        destination = _member(2, _at(3))

        overrides = overrides_for_pair(source, destination, SeriesMergePolicies())

        assert "location" not in overrides["type_data"]["event"]
        assert "description" not in overrides["type_data"]["event"]

    def test_destination_content_policy_pins_the_destination_content(
        self,
    ) -> None:
        source = _member(1, _at(3), content="a")
        destination = _member(2, _at(3), content="b")
        policies = SeriesMergePolicies(content=SeriesFieldPolicy.DESTINATION)

        overrides = overrides_for_pair(source, destination, policies)

        assert overrides["content"] == "b"

    def test_timing_without_calendar_info_overrides_only_the_date_range(
        self,
    ) -> None:
        source = _member(1, _at(3, 9), calendar_id=None)
        destination = _member(2, _at(3, 11), calendar_id=None)
        policies = SeriesMergePolicies(timing=SeriesFieldPolicy.SOURCE)

        overrides = overrides_for_pair(source, destination, policies)

        assert overrides["event_date_range"]["start"] == _at(3, 9).isoformat()
        assert "type_data" not in overrides


def _half_hour() -> datetime.timedelta:
    return datetime.timedelta(minutes=30)
