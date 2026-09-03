"""Unit tests for the home dashboard's JSON:API document.

Asserted off the pure renderer rather than through a request, the way
``to_upcoming_tasks_response`` is, so the document's shape is pinned without a
database or a client.

The shape follows the specification deliberately in three places, and each is
tested here because later phases inherit it:

- **A degraded section is part of ``data``, not ``errors``.** The specification
  forbids ``data`` and ``errors`` in the same document, so "three sections and a
  failure in the fourth" has no representation as an error document — it is a
  successful response whose fourth section says it is unavailable.
- **The anchor travels in ``meta``**, which is where information about how the
  answer was computed belongs, matching the upcoming-tasks listing's window.
- **The resource carries a ``self`` link**, as the specification recommends.
"""

import datetime
from typing import Any

import pytest

from app.api.home_dashboard.schemas import (
    HOME_DASHBOARD_RESOURCE_TYPE,
    DashboardSectionSchema,
    SummarySectionSchema,
    to_home_dashboard_response,
)
from app.core.dashboard.models.sections import (
    AgendaDay,
    AgendaEntry,
    AgendaParticipant,
    AgendaSectionData,
    AgendaTag,
    DashboardSection,
    DashboardSummaryState,
    HomeDashboard,
    SummarySectionData,
    TasksSectionData,
    UpcomingDatesSectionData,
)

pytestmark = pytest.mark.unit

USER_ID = "test-user-123"
ANCHOR = datetime.date(2026, 7, 31)
TOMORROW = ANCHOR + datetime.timedelta(days=1)
BASE_URL = "http://testserver"

GENERATED_SUMMARY = SummarySectionData(
    state=DashboardSummaryState.GENERATED,
    summary_text="A long day of climbing and two good conversations.",
    journal_count=4,
    event_count=2,
    contact_count=3,
    mood_average=7.5,
)

# The sections Phases 11 and 13 have yet to fill. Named rather than repeated so
# a phase filling one has a single place to stop excluding it.
STILL_EMPTY = ("tasks", "upcoming_dates")

NINE_AM = datetime.datetime(2026, 7, 31, 9, tzinfo=datetime.UTC)

COFFEE = AgendaEntry(
    journal_id=42,
    title="Coffee with Sam",
    is_all_day=False,
    starts_at=NINE_AM,
    ends_at=NINE_AM + datetime.timedelta(hours=1),
    start_time=datetime.time(9, 0),
    end_time=datetime.time(10, 0),
    timezone="Australia/Sydney",
    location="The good place",
    calendar_color="#336699",
    tags=(AgendaTag(id="tag-1", name="social", color="#ff0000"),),
    participants=(AgendaParticipant(contact_id=7, name="Sam Taylor"),),
)


def agenda(
    *entries: AgendaEntry, tomorrow: tuple[AgendaEntry, ...] = ()
) -> AgendaSectionData:
    """An agenda payload as the service builds one: today, and tomorrow's day."""
    return AgendaSectionData(
        entries=entries, tomorrow=AgendaDay(date=TOMORROW, entries=tomorrow)
    )


def dashboard(**overrides: object) -> HomeDashboard:
    """A dashboard with every section ready, as the service builds one."""
    sections: dict[str, object] = {
        "summary": DashboardSection.ready(GENERATED_SUMMARY),
        "agenda": DashboardSection.ready(agenda()),
        "tasks": DashboardSection.ready(TasksSectionData()),
        "upcoming_dates": DashboardSection.ready(UpcomingDatesSectionData()),
    }
    sections.update(overrides)
    return HomeDashboard(
        user_id=USER_ID,
        anchor_date=ANCHOR,
        timezone="Australia/Sydney",
        **sections,  # type: ignore[arg-type]
    )


class TestTheSingletonResource:
    def test_is_keyed_by_the_user_it_belongs_to(self) -> None:
        """No dashboard row exists, so the user's id is the resource's id."""
        response = to_home_dashboard_response(dashboard())

        assert response.data.type == HOME_DASHBOARD_RESOURCE_TYPE == "home-dashboards"
        assert response.data.id == USER_ID

    def test_carries_an_absolute_self_link(self) -> None:
        response = to_home_dashboard_response(dashboard(), BASE_URL)

        assert response.data.links is not None
        assert response.data.links.self == f"{BASE_URL}/api/home-dashboard"


class TestTheAnchorInMeta:
    def test_names_the_day_and_zone_the_sections_were_read_for(self) -> None:
        response = to_home_dashboard_response(dashboard())

        assert response.meta.anchor.date == ANCHOR
        assert response.meta.anchor.timezone == "Australia/Sydney"

    def test_is_present_however_little_the_sections_hold(self) -> None:
        """A client renders "Today, 31 July" whatever else it does or does not."""
        document = to_home_dashboard_response(dashboard()).model_dump(mode="json")

        assert document["meta"]["anchor"] == {
            "date": "2026-07-31",
            "timezone": "Australia/Sydney",
        }

    def test_does_not_sit_in_attributes(self) -> None:
        """How the answer was computed is meta, not a field of the resource."""
        document = to_home_dashboard_response(dashboard()).model_dump(mode="json")

        assert "anchor" not in document["data"]["attributes"]
        assert "timezone" not in document["data"]["attributes"]


class TestTheFourSections:
    def test_all_four_are_declared_in_attributes(self) -> None:
        document = to_home_dashboard_response(dashboard()).model_dump(mode="json")

        assert set(document["data"]["attributes"]) == {
            "summary",
            "agenda",
            "tasks",
            "upcoming_dates",
        }

    def test_a_ready_section_carries_a_payload_object(self) -> None:
        """Present whether or not the phase that fills it has landed yet.

        The two unfilled sections serialise as ``{}`` — "ready and holding
        nothing", which is a real answer rather than an absence — while the
        summary and the agenda carry the fields their phases gave them.
        """
        document = to_home_dashboard_response(dashboard()).model_dump(mode="json")

        for name, section in document["data"]["attributes"].items():
            assert section["status"] == "ready", name
            assert section["data"] is not None, name
        for name in STILL_EMPTY:
            assert document["data"]["attributes"][name]["data"] == {}, name

    def test_an_unavailable_section_carries_null_data(self) -> None:
        document = to_home_dashboard_response(
            dashboard(agenda=DashboardSection.unavailable())
        ).model_dump(mode="json")

        assert document["data"]["attributes"]["agenda"] == {
            "status": "unavailable",
            "data": None,
        }

    def test_the_other_sections_are_unaffected(self) -> None:
        document = to_home_dashboard_response(
            dashboard(agenda=DashboardSection.unavailable())
        ).model_dump(mode="json")

        for name in ("summary", "tasks", "upcoming_dates"):
            assert document["data"]["attributes"][name]["status"] == "ready", name


class TestADegradedDocumentIsStillASuccessfulOne:
    def test_a_failed_section_never_becomes_a_top_level_errors_member(self) -> None:
        """``data`` and ``errors`` may not coexist, so the failure lives in data."""
        document = to_home_dashboard_response(
            dashboard(
                summary=DashboardSection.unavailable(),
                tasks=DashboardSection.unavailable(),
            )
        ).model_dump(mode="json")

        assert set(document) == {"data", "meta"}
        assert "errors" not in document
        assert document["data"]["attributes"]["summary"]["status"] == "unavailable"

    def test_every_section_can_be_unavailable_at_once(self) -> None:
        """Even then the document is a dashboard, with its anchor, not an error."""
        document = to_home_dashboard_response(
            dashboard(
                summary=DashboardSection.unavailable(),
                agenda=DashboardSection.unavailable(),
                tasks=DashboardSection.unavailable(),
                upcoming_dates=DashboardSection.unavailable(),
            )
        ).model_dump(mode="json")

        statuses = {
            section["status"] for section in document["data"]["attributes"].values()
        }
        assert statuses == {"unavailable"}
        assert document["meta"]["anchor"]["date"] == "2026-07-31"


class TestTheSummarySection:
    """The one section with a payload of its own, as of this phase.

    Two of the wireframe's three declared states live in ``data.state``; the
    third is the envelope's ``unavailable``, which is why there is no
    ``"unavailable"`` member of the state vocabulary to serialise.
    """

    def test_serialises_every_field_the_card_renders(self) -> None:
        document = to_home_dashboard_response(dashboard()).model_dump(mode="json")

        assert document["data"]["attributes"]["summary"] == {
            "status": "ready",
            "data": {
                "state": "generated",
                "summary_text": "A long day of climbing and two good conversations.",
                "journal_count": 4,
                "event_count": 2,
                "contact_count": 3,
                "mood_average": 7.5,
            },
        }

    def test_a_generating_summary_carries_no_prose(self) -> None:
        """W8 replaces the body with one muted line, so there is nothing to send."""
        document = to_home_dashboard_response(
            dashboard(
                summary=DashboardSection.ready(
                    SummarySectionData(
                        state=DashboardSummaryState.GENERATING,
                        journal_count=1,
                    )
                )
            )
        ).model_dump(mode="json")

        payload = document["data"]["attributes"]["summary"]["data"]
        assert payload["state"] == "generating"
        assert payload["summary_text"] is None

    def test_absent_values_serialise_as_null_rather_than_vanishing(self) -> None:
        """A key that disappears reads to a client as a schema change.

        ``mood_average`` is null on any day nobody rated their mood, which is
        most days, so the field has to be reliably present for W10 to decide
        whether to draw its fourth stat.
        """
        document = to_home_dashboard_response(
            dashboard(
                summary=DashboardSection.ready(
                    SummarySectionData(state=DashboardSummaryState.GENERATED)
                )
            )
        ).model_dump(mode="json")

        payload = document["data"]["attributes"]["summary"]["data"]
        assert payload["summary_text"] is None
        assert payload["mood_average"] is None
        assert payload["journal_count"] == 0

    def test_an_unavailable_summary_takes_nothing_else_down(self) -> None:
        """The specification's ruling, now that the section has real content."""
        document = to_home_dashboard_response(
            dashboard(summary=DashboardSection.unavailable())
        ).model_dump(mode="json")

        assert set(document) == {"data", "meta"}
        assert document["data"]["attributes"]["summary"] == {
            "status": "unavailable",
            "data": None,
        }
        for name in STILL_EMPTY:
            assert document["data"]["attributes"][name]["status"] == "ready", name

    def test_the_page_can_still_name_its_day_without_a_summary(self) -> None:
        """W6's Regenerate control persists in the unavailable state.

        It posts to the daily-summary endpoint for a date, and the only date
        left in the document is the anchor — so that is where a client takes it
        from, and it must survive the section it belongs to going missing.
        """
        document = to_home_dashboard_response(
            dashboard(summary=DashboardSection.unavailable())
        ).model_dump(mode="json")

        assert document["meta"]["anchor"]["date"] == "2026-07-31"

    def test_exposes_no_mutation_affordance(self) -> None:
        """Read-only: regeneration stays on the existing daily-summary endpoint."""
        payload = to_home_dashboard_response(dashboard()).model_dump(mode="json")[
            "data"
        ]["attributes"]["summary"]["data"]

        assert set(payload) == {
            "state",
            "summary_text",
            "journal_count",
            "event_count",
            "contact_count",
            "mood_average",
        }


class TestTheStatusIsDocumentedAsItBehaves:
    """The generated schema is the contract a client author actually reads.

    Phase 2 widened *unavailable* from "could not be read" to "has nothing for
    you", and the domain docstrings were updated with it — but the OpenAPI
    description was not, so clients generated from this endpoint were told the
    summary section's ordinary state meant something had gone wrong. Pinned here
    because prose is exactly the part of a schema no other test touches.
    """

    def test_does_not_describe_unavailable_as_a_failure(self) -> None:
        described = (
            DashboardSectionSchema[SummarySectionSchema]
            .model_fields["status"]
            .description
        )

        assert described is not None
        assert "could not be read or because there is nothing to report" in described

    def test_says_a_ready_section_may_still_be_empty(self) -> None:
        """The other half of the pair, and the one W29's empty lines rest on."""
        described = (
            DashboardSectionSchema[SummarySectionSchema]
            .model_fields["status"]
            .description
        )

        assert described is not None
        assert "empty payload is then a real answer" in described


class TestTheAgendaSection:
    """The agenda on the wire: entries in order, and nothing pre-formatted.

    What the card needs is *data* — a boolean for all-day, a boolean for
    cancelled, names for the avatar stack, a colour beside each tag name — so
    that Phase 7 can render a marker with real text rather than styling alone
    and an avatar with a real ``alt``. A payload of finished strings would take
    those decisions away from the surface that has to make them accessible.
    """

    def test_an_entry_renders_field_for_field(self) -> None:
        document = to_home_dashboard_response(
            dashboard(agenda=DashboardSection.ready(agenda(COFFEE)))
        ).model_dump(mode="json")

        assert document["data"]["attributes"]["agenda"]["data"]["entries"] == [
            {
                "journal_id": 42,
                "title": "Coffee with Sam",
                "is_all_day": False,
                "starts_at": "2026-07-31T09:00:00Z",
                "ends_at": "2026-07-31T10:00:00Z",
                "start_time": "09:00:00",
                "end_time": "10:00:00",
                "timezone": "Australia/Sydney",
                "location": "The good place",
                "calendar_color": "#336699",
                "is_cancelled": False,
                "tags": [{"id": "tag-1", "name": "social", "color": "#ff0000"}],
                "participants": [{"contact_id": 7, "name": "Sam Taylor"}],
            }
        ]

    def test_it_keeps_the_order_the_service_put_the_entries_in(self) -> None:
        """The wire preserves W12/W13; it does not re-sort and cannot re-shuffle."""
        later = AgendaEntry(
            journal_id=43,
            title="Dinner",
            is_all_day=False,
            starts_at=NINE_AM + datetime.timedelta(hours=10),
            ends_at=NINE_AM + datetime.timedelta(hours=12),
        )
        document = to_home_dashboard_response(
            dashboard(agenda=DashboardSection.ready(agenda(COFFEE, later)))
        ).model_dump(mode="json")

        entries = document["data"]["attributes"]["agenda"]["data"]["entries"]
        assert [entry["journal_id"] for entry in entries] == [42, 43]

    def test_an_all_day_entry_carries_no_clock_times(self) -> None:
        """The card draws ``ALL DAY`` in place of a time (W12), so there is none."""
        all_day = AgendaEntry(
            journal_id=44,
            title="Public holiday",
            is_all_day=True,
            starts_at=NINE_AM,
            ends_at=NINE_AM,
        )
        document = to_home_dashboard_response(
            dashboard(agenda=DashboardSection.ready(agenda(all_day)))
        ).model_dump(mode="json")

        entry = document["data"]["attributes"]["agenda"]["data"]["entries"][0]
        assert entry["is_all_day"] is True
        assert entry["start_time"] is None
        assert entry["end_time"] is None

    def test_a_cancelled_entry_says_so(self) -> None:
        """W18: shown, never hidden, and never as if it were still happening."""
        cancelled = AgendaEntry(
            journal_id=45,
            title="Postponed standup",
            is_all_day=False,
            starts_at=NINE_AM,
            ends_at=NINE_AM,
            is_cancelled=True,
        )
        document = to_home_dashboard_response(
            dashboard(agenda=DashboardSection.ready(agenda(cancelled)))
        ).model_dump(mode="json")

        entry = document["data"]["attributes"]["agenda"]["data"]["entries"][0]
        assert entry["is_cancelled"] is True
        assert entry["title"] == "Postponed standup"

    def test_the_clock_times_carry_the_zone_they_are_expressed_in(self) -> None:
        """``09:00`` alone is uninterpretable, so the zone travels beside it.

        The stored clock values are the **event's** wall time, not the reader's —
        migration 0045 derives them ``AT TIME ZONE jci.timezone`` — so a Sydney
        reader's agenda can hold a New York meeting saying nine in the morning
        that sorts into their evening. The journals API sends the same field
        beside the same two values for the same reason.
        """
        document = to_home_dashboard_response(
            dashboard(agenda=DashboardSection.ready(agenda(COFFEE)))
        ).model_dump(mode="json")

        entry = document["data"]["attributes"]["agenda"]["data"]["entries"][0]
        assert entry["timezone"] == "Australia/Sydney"
        assert entry["start_time"] == "09:00:00"

    def test_an_entry_with_nothing_optional_renders_its_absences(self) -> None:
        bare = AgendaEntry(
            journal_id=46,
            title="A quiet event",
            is_all_day=False,
            starts_at=NINE_AM,
            ends_at=NINE_AM,
        )
        document = to_home_dashboard_response(
            dashboard(agenda=DashboardSection.ready(agenda(bare)))
        ).model_dump(mode="json")

        entry = document["data"]["attributes"]["agenda"]["data"]["entries"][0]
        assert entry["location"] is None
        assert entry["timezone"] is None
        assert entry["calendar_color"] is None
        assert entry["tags"] == []
        assert entry["participants"] == []

    def test_an_empty_day_is_ready_with_an_empty_list(self) -> None:
        """Not ``{}`` and not null: the section answered, and the answer is none.

        The card's single quiet line for "nothing scheduled today" is a different
        line from the one it shows when the section could not be read, so the two
        cannot share a representation.
        """
        document = to_home_dashboard_response(dashboard()).model_dump(mode="json")

        assert document["data"]["attributes"]["agenda"] == {
            "status": "ready",
            "data": {
                "entries": [],
                "tomorrow": {"date": "2026-08-01", "entries": []},
            },
        }

    def test_an_unavailable_agenda_carries_null_data(self) -> None:
        document = to_home_dashboard_response(
            dashboard(agenda=DashboardSection.unavailable())
        ).model_dump(mode="json")

        assert document["data"]["attributes"]["agenda"]["data"] is None


class TestTomorrowOnTheWire:
    """Tomorrow rides beside today, as a day: its date and its entries.

    Open decision 5 put tomorrow in the payload rather than behind a second
    request, and **W20** renders it "in exactly the same form" as today — so it
    is serialised through the same entry renderer, and the tests here are about
    the shape around it: the date the disclosure labels itself with, the order
    the service settled, and nothing derived alongside.
    """

    def tomorrow_of(self, document: dict[str, Any]) -> dict[str, Any]:
        tomorrow: dict[str, Any] = document["data"]["attributes"]["agenda"]["data"][
            "tomorrow"
        ]
        return tomorrow

    def test_carries_the_date_and_the_entries(self) -> None:
        document = to_home_dashboard_response(
            dashboard(agenda=DashboardSection.ready(agenda(tomorrow=(COFFEE,))))
        ).model_dump(mode="json")

        tomorrow = self.tomorrow_of(document)
        assert tomorrow["date"] == "2026-08-01"
        assert [entry["journal_id"] for entry in tomorrow["entries"]] == [42]

    def test_an_entry_renders_in_exactly_the_form_todays_does(self) -> None:
        """W20, on the wire: one renderer, so the two days cannot drift apart."""
        document = to_home_dashboard_response(
            dashboard(agenda=DashboardSection.ready(agenda(COFFEE, tomorrow=(COFFEE,))))
        ).model_dump(mode="json")

        today = document["data"]["attributes"]["agenda"]["data"]["entries"][0]
        assert self.tomorrow_of(document)["entries"][0] == today

    def test_keeps_the_order_the_service_put_the_entries_in(self) -> None:
        later = AgendaEntry(
            journal_id=43,
            title="Dinner",
            is_all_day=False,
            starts_at=NINE_AM + datetime.timedelta(hours=10),
            ends_at=NINE_AM + datetime.timedelta(hours=12),
        )
        document = to_home_dashboard_response(
            dashboard(agenda=DashboardSection.ready(agenda(tomorrow=(COFFEE, later))))
        ).model_dump(mode="json")

        entries = self.tomorrow_of(document)["entries"]
        assert [entry["journal_id"] for entry in entries] == [42, 43]

    def test_a_cancelled_entry_tomorrow_says_so(self) -> None:
        """W18 applies to tomorrow's rows exactly as to today's."""
        cancelled = AgendaEntry(
            journal_id=45,
            title="Postponed standup",
            is_all_day=False,
            starts_at=NINE_AM,
            ends_at=NINE_AM,
            is_cancelled=True,
        )
        document = to_home_dashboard_response(
            dashboard(agenda=DashboardSection.ready(agenda(tomorrow=(cancelled,))))
        ).model_dump(mode="json")

        entry = self.tomorrow_of(document)["entries"][0]
        assert entry["is_cancelled"] is True
        assert entry["title"] == "Postponed standup"

    def test_nothing_tomorrow_is_a_dated_empty_list(self) -> None:
        """The disclosure still renders, with a zero count and its date label."""
        document = to_home_dashboard_response(dashboard()).model_dump(mode="json")

        assert self.tomorrow_of(document) == {"date": "2026-08-01", "entries": []}

    def test_carries_no_count_beside_the_list(self) -> None:
        """W19's count is ``entries.length``: tomorrow is not capped, so a count
        on the wire would be derivable data that can drift from its list.
        """
        document = to_home_dashboard_response(
            dashboard(agenda=DashboardSection.ready(agenda(tomorrow=(COFFEE,))))
        ).model_dump(mode="json")

        assert set(self.tomorrow_of(document)) == {"date", "entries"}

    def test_is_always_present_on_a_ready_agenda(self) -> None:
        """Absent tomorrow would read as "nothing tomorrow"; it must not be able to."""
        document = to_home_dashboard_response(
            dashboard(agenda=DashboardSection.ready(agenda(COFFEE)))
        ).model_dump(mode="json")

        assert "tomorrow" in document["data"]["attributes"]["agenda"]["data"]
