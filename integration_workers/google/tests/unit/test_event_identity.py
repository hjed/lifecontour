"""Unit tests for the cross-calendar event identity token.

The token is the one place that knows how Google identifies a single
real-world event across several calendars. Everything downstream treats it
as an opaque string, so these tests are the whole specification of the
scheme: equal tokens for copies of the same event, distinct tokens for
things that only look alike.
"""

from calendar_models import GoogleEvent, GoogleEventStartEnd
from event_identity import build_event_identity


def _event(**overrides: object) -> GoogleEvent:
    """A confirmed single event, overridable field by field."""
    data: dict[str, object] = {
        "id": "evt-1",
        "summary": "Team Meeting",
        "status": "confirmed",
        "iCalUID": "abc123@google.com",
    }
    data.update(overrides)
    return GoogleEvent(**data)  # type: ignore[arg-type]


class TestSingleEvents:
    """A one-off event is identified by its iCalUID alone."""

    def test_token_is_built_from_the_ical_uid(self) -> None:
        assert build_event_identity(_event()) == "google:abc123@google.com:"

    def test_the_same_event_in_two_calendars_shares_one_token(self) -> None:
        # Google hands each attendee's calendar its own event id, but the
        # iCalUID is what makes them the same meeting. This is the case the
        # whole feature exists for.
        work_copy = _event(id="evt-work-1")
        personal_copy = _event(id="evt-personal-9")

        assert build_event_identity(work_copy) == build_event_identity(personal_copy)

    def test_different_events_get_different_tokens(self) -> None:
        assert build_event_identity(_event(iCalUID="one@google.com")) != (
            build_event_identity(_event(iCalUID="two@google.com"))
        )

    def test_no_ical_uid_yields_no_token(self) -> None:
        # Better to fall back to the existing per-calendar behaviour than to
        # invent an identity that could collide with a real one.
        assert build_event_identity(_event(iCalUID=None)) is None

    def test_blank_ical_uid_yields_no_token(self) -> None:
        assert build_event_identity(_event(iCalUID="   ")) is None


class TestRecurringInstances:
    """Every instance of a series shares the series' iCalUID.

    So the uid alone would collapse a weekly meeting into a single journal.
    The instance's originalStartTime is what separates them.
    """

    def test_instances_of_one_series_get_different_tokens(self) -> None:
        week_one = _event(
            id="series-1_20260320T100000Z",
            recurringEventId="series-1",
            originalStartTime=GoogleEventStartEnd(dateTime="2026-03-20T10:00:00Z"),  # type: ignore[call-arg]
        )
        week_two = _event(
            id="series-1_20260327T100000Z",
            recurringEventId="series-1",
            originalStartTime=GoogleEventStartEnd(dateTime="2026-03-27T10:00:00Z"),  # type: ignore[call-arg]
        )

        assert build_event_identity(week_one) != build_event_identity(week_two)

    def test_one_instance_in_two_calendars_shares_a_token(self) -> None:
        work_copy = _event(
            id="series-work_20260320T100000Z",
            recurringEventId="series-work",
            originalStartTime=GoogleEventStartEnd(dateTime="2026-03-20T10:00:00Z"),  # type: ignore[call-arg]
        )
        personal_copy = _event(
            id="series-personal_20260320T100000Z",
            recurringEventId="series-personal",
            originalStartTime=GoogleEventStartEnd(dateTime="2026-03-20T10:00:00Z"),  # type: ignore[call-arg]
        )

        assert build_event_identity(work_copy) == build_event_identity(personal_copy)

    def test_an_instance_differs_from_a_single_event_with_the_same_uid(self) -> None:
        single = _event()
        instance = _event(
            originalStartTime=GoogleEventStartEnd(dateTime="2026-03-20T10:00:00Z"),  # type: ignore[call-arg]
        )

        assert build_event_identity(single) != build_event_identity(instance)


class TestTimezoneNormalisation:
    """originalStartTime arrives in each calendar's own timezone.

    Comparing the raw strings would make two copies of one instance look
    like two different instances, so the instant is normalised to UTC.
    """

    def test_the_same_instant_in_two_offsets_yields_one_token(self) -> None:
        sydney = _event(
            originalStartTime=GoogleEventStartEnd(  # type: ignore[call-arg]
                dateTime="2026-03-20T21:00:00+11:00",
                timeZone="Australia/Sydney",
            ),
        )
        utc = _event(
            originalStartTime=GoogleEventStartEnd(dateTime="2026-03-20T10:00:00Z"),  # type: ignore[call-arg]
        )

        assert build_event_identity(sydney) == build_event_identity(utc)

    def test_a_naive_datetime_is_read_in_the_events_timezone(self) -> None:
        naive_sydney = _event(
            originalStartTime=GoogleEventStartEnd(  # type: ignore[call-arg]
                dateTime="2026-03-20T21:00:00",
                timeZone="Australia/Sydney",
            ),
        )
        utc = _event(
            originalStartTime=GoogleEventStartEnd(dateTime="2026-03-20T10:00:00Z"),  # type: ignore[call-arg]
        )

        assert build_event_identity(naive_sydney) == build_event_identity(utc)

    def test_different_instants_stay_distinct(self) -> None:
        earlier = _event(
            originalStartTime=GoogleEventStartEnd(dateTime="2026-03-20T10:00:00Z"),  # type: ignore[call-arg]
        )
        later = _event(
            originalStartTime=GoogleEventStartEnd(dateTime="2026-03-20T11:00:00Z"),  # type: ignore[call-arg]
        )

        assert build_event_identity(earlier) != build_event_identity(later)


class TestAllDayInstances:
    """An all-day instance carries a date, not an instant."""

    def test_an_all_day_instance_is_pinned_to_utc_midnight(self) -> None:
        all_day = _event(
            originalStartTime=GoogleEventStartEnd(date="2026-03-20"),  # type: ignore[call-arg]
        )

        assert build_event_identity(all_day) == (
            "google:abc123@google.com:2026-03-20T00:00:00+00:00"
        )

    def test_the_same_all_day_instance_in_two_calendars_matches(self) -> None:
        work_copy = _event(
            id="series-work_20260320",
            originalStartTime=GoogleEventStartEnd(date="2026-03-20"),  # type: ignore[call-arg]
        )
        personal_copy = _event(
            id="series-personal_20260320",
            originalStartTime=GoogleEventStartEnd(date="2026-03-20"),  # type: ignore[call-arg]
        )

        assert build_event_identity(work_copy) == build_event_identity(personal_copy)

    def test_consecutive_all_day_instances_stay_distinct(self) -> None:
        first = _event(originalStartTime=GoogleEventStartEnd(date="2026-03-20"))  # type: ignore[call-arg]
        second = _event(originalStartTime=GoogleEventStartEnd(date="2026-03-21"))  # type: ignore[call-arg]

        assert build_event_identity(first) != build_event_identity(second)


class TestMalformedInput:
    """A token that cannot be trusted is better withheld than guessed."""

    def test_an_unparseable_original_start_yields_no_token(self) -> None:
        # Falling back to the uid alone would merge every instance of the
        # series into one journal — far worse than leaving this event on the
        # existing per-calendar path.
        broken = _event(
            originalStartTime=GoogleEventStartEnd(dateTime="not-a-datetime"),  # type: ignore[call-arg]
        )

        assert build_event_identity(broken) is None

    def test_an_empty_original_start_is_treated_as_a_single_event(self) -> None:
        # An originalStartTime object with neither field set carries no
        # instance information, so the event is identified by its uid.
        empty = _event(originalStartTime=GoogleEventStartEnd())  # type: ignore[call-arg]

        assert build_event_identity(empty) == "google:abc123@google.com:"


class TestTokenShape:
    """The column is bounded, so the token has to be too."""

    def test_an_oversized_uid_still_produces_a_storable_token(self) -> None:
        long_uid = ("x" * 900) + "@google.com"
        token = build_event_identity(_event(iCalUID=long_uid))

        assert token is not None
        assert len(token) <= 512

    def test_an_oversized_uid_still_matches_itself_across_calendars(self) -> None:
        # Whatever shortening happens must stay a function of the input, or
        # two copies of one event would no longer match.
        long_uid = ("x" * 900) + "@google.com"

        assert build_event_identity(_event(id="a", iCalUID=long_uid)) == (
            build_event_identity(_event(id="b", iCalUID=long_uid))
        )

    def test_two_oversized_uids_stay_distinct(self) -> None:
        assert build_event_identity(_event(iCalUID="y" * 900)) != (
            build_event_identity(_event(iCalUID="z" * 900))
        )

    def test_the_token_names_its_source(self) -> None:
        # Two integrations must never collide on one token.
        token = build_event_identity(_event())

        assert token is not None
        assert token.startswith("google:")
