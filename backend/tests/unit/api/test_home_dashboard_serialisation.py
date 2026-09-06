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
from core_shared.models.contacts.entities import ImportantDate
from core_shared.models.contacts.important_date_occurrence import (
    ImportantDateOccurrence,
)
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)
from core_shared.models.date_window import upcoming_window
from core_shared.models.tasks import TaskContactRef, TaskJournalRef

from app.api.home_dashboard.schemas import (
    HOME_DASHBOARD_RESOURCE_TYPE,
    DashboardSectionSchema,
    SummarySectionSchema,
    to_home_dashboard_response,
)
from app.core.contacts.models.importance import ContactImportance
from app.core.contacts.models.upcoming_dates import (
    UpcomingContactDate,
    UpcomingDateContact,
)
from app.core.dashboard.models.sections import (
    AgendaDay,
    AgendaSectionData,
    DashboardSection,
    DashboardSummaryState,
    DashboardTask,
    HomeDashboard,
    SummarySectionData,
    TasksSectionData,
    UpcomingDatesSectionData,
)
from app.core.journal.models.agenda import (
    AgendaEntry,
    AgendaParticipant,
    AgendaTag,
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


NO_SIGNALS = ContactImportance(
    contact_id=7,
    is_favourite=False,
    journal_count_30d=0,
    activity_count_30d=0,
    last_activity_at=None,
)

ADA = UpcomingDateContact(
    id=7, display_name="Ada Lovelace", photo_url="https://example.test/ada.png"
)


def occurrence(
    *,
    date_type: ImportantDateType,
    occurs_on: datetime.date,
    days_away: int,
    years: int | None,
    observed_for_leap_day: bool = False,
    custom_date_type_name: str | None = None,
) -> UpcomingContactDate:
    """One resolved occurrence as the contacts read hands it over."""
    return UpcomingContactDate(
        occurrence=ImportantDateOccurrence(
            important_date=ImportantDate(
                id=1,
                contact_id=7,
                date_type=date_type,
                precision=DatePrecision.DAY_MONTH,
                month=occurs_on.month,
                day=occurs_on.day,
                custom_date_type_id=3 if custom_date_type_name else None,
                custom_date_type_name=custom_date_type_name,
            ),
            occurs_on=occurs_on,
            days_away=days_away,
            years=years,
            observed_for_leap_day=observed_for_leap_day,
        ),
        contact=ADA,
        importance=NO_SIGNALS,
    )


BIRTHDAY = occurrence(
    date_type=ImportantDateType.BIRTHDAY,
    occurs_on=datetime.date(2026, 8, 2),
    days_away=2,
    years=35,
)

SOBRIETY = occurrence(
    date_type=ImportantDateType.CUSTOM,
    occurs_on=datetime.date(2026, 8, 1),
    days_away=1,
    years=None,
    custom_date_type_name="Sobriety",
)

LEAP_BIRTHDAY = occurrence(
    date_type=ImportantDateType.BIRTHDAY,
    occurs_on=datetime.date(2026, 2, 28),
    days_away=4,
    years=None,
    observed_for_leap_day=True,
)


def dates(*rows: UpcomingContactDate) -> UpcomingDatesSectionData:
    """An upcoming-dates payload as the service builds one: a window and rows."""
    return UpcomingDatesSectionData(window=upcoming_window(ANCHOR, 7), dates=rows)


def task_row(
    task_id: int,
    *,
    days_away: int,
    text: str = "book the venue",
    title: str = "Monday standup",
    contacts: tuple[TaskContactRef, ...] = (),
) -> DashboardTask:
    """One row as the tasks projection produces it, ready for the wire."""
    return DashboardTask(
        task_id=task_id,
        text=text,
        due_journal=TaskJournalRef(
            id=900 + task_id,
            title=title,
            date=ANCHOR + datetime.timedelta(days=days_away),
            cancelled=False,
        ),
        days_away=days_away,
        contacts=contacts,
    )


def tasks(*rows: DashboardTask) -> TasksSectionData:
    """A tasks payload as the service builds one: a window and rows."""
    return TasksSectionData(window=upcoming_window(ANCHOR, 7), tasks=rows)


def dashboard(**overrides: object) -> HomeDashboard:
    """A dashboard with every section ready, as the service builds one."""
    sections: dict[str, object] = {
        "summary": DashboardSection.ready(GENERATED_SUMMARY),
        "agenda": DashboardSection.ready(agenda()),
        "tasks": DashboardSection.ready(tasks()),
        "upcoming_dates": DashboardSection.ready(dates()),
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
        """All four sections now carry fields, and none of them added a section.

        The envelope this contract was written around is unchanged: what each
        phase did was fill a payload, so a ready section still means "read, and
        here is what it holds" — including when what it holds is empty.
        """
        document = to_home_dashboard_response(dashboard()).model_dump(mode="json")

        for name, section in document["data"]["attributes"].items():
            assert section["status"] == "ready", name
            assert section["data"] is not None, name
            assert section["data"] != {}, name

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
        for name in ("agenda", "tasks", "upcoming_dates"):
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


class TestTheUpcomingDatesSection:
    """W30–W32: whose date, when, how far away, and what it makes.

    The rows are the contacts domain's ``UpcomingContactDate``, the way the
    agenda's are the journal domain's ``AgendaEntry``. What is asserted here is
    only the wire shape — the ordering and the recurrence were settled before a
    renderer sees them, and a renderer that re-derived either would be a second
    copy of a rule that already has a home.
    """

    @staticmethod
    def section_of(document: dict[str, Any]) -> dict[str, Any]:
        section: dict[str, Any] = document["data"]["attributes"]["upcoming_dates"][
            "data"
        ]
        return section

    def test_a_row_renders_field_for_field(self) -> None:
        document = to_home_dashboard_response(
            dashboard(upcoming_dates=DashboardSection.ready(dates(BIRTHDAY)))
        ).model_dump(mode="json")

        assert self.section_of(document)["dates"] == [
            {
                "contact_id": 7,
                "contact_name": "Ada Lovelace",
                "photo_url": "https://example.test/ada.png",
                "date_type": "birthday",
                "custom_date_type_name": None,
                "occurs_on": "2026-08-02",
                "days_away": 2,
                "years": 35,
                "observed_for_leap_day": False,
            }
        ]

    def test_a_custom_type_carries_the_name_the_user_gave_it(self) -> None:
        """The badge shows what they called it, not the word "custom"."""
        document = to_home_dashboard_response(
            dashboard(upcoming_dates=DashboardSection.ready(dates(SOBRIETY)))
        ).model_dump(mode="json")

        row = self.section_of(document)["dates"][0]
        assert (row["date_type"], row["custom_date_type_name"]) == (
            "custom",
            "Sobriety",
        )

    def test_a_date_with_no_derivable_years_sends_null(self) -> None:
        """W31 degrades the badge to the bare type; the wire says why it must."""
        document = to_home_dashboard_response(
            dashboard(upcoming_dates=DashboardSection.ready(dates(SOBRIETY)))
        ).model_dump(mode="json")

        assert self.section_of(document)["dates"][0]["years"] is None

    def test_a_leap_day_substitution_is_flagged_rather_than_silent(self) -> None:
        document = to_home_dashboard_response(
            dashboard(upcoming_dates=DashboardSection.ready(dates(LEAP_BIRTHDAY)))
        ).model_dump(mode="json")

        row = self.section_of(document)["dates"][0]
        assert (row["occurs_on"], row["observed_for_leap_day"]) == ("2026-02-28", True)

    def test_it_keeps_the_order_the_service_put_the_rows_in(self) -> None:
        document = to_home_dashboard_response(
            dashboard(upcoming_dates=DashboardSection.ready(dates(SOBRIETY, BIRTHDAY)))
        ).model_dump(mode="json")

        assert [row["date_type"] for row in self.section_of(document)["dates"]] == [
            "custom",
            "birthday",
        ]

    def test_the_window_travels_with_the_rows(self) -> None:
        """So a surface labels itself "the next seven days" from the answer it
        was given rather than from the browser's own arithmetic."""
        document = to_home_dashboard_response(
            dashboard(upcoming_dates=DashboardSection.ready(dates(BIRTHDAY)))
        ).model_dump(mode="json")

        assert self.section_of(document)["window"] == {
            "start_date": "2026-07-31",
            "end_date": "2026-08-07",
            "days_ahead": 7,
        }

    def test_the_total_names_the_whole_window(self) -> None:
        """W32's show-more names a count larger than the three rows the card
        renders, so the count is sent rather than left to be derived from a list
        the card has already truncated."""
        document = to_home_dashboard_response(
            dashboard(
                upcoming_dates=DashboardSection.ready(
                    dates(BIRTHDAY, SOBRIETY, LEAP_BIRTHDAY, BIRTHDAY)
                )
            )
        ).model_dump(mode="json")

        assert self.section_of(document)["total"] == 4

    def test_nothing_in_the_window_is_a_ready_empty_list(self) -> None:
        """W29's idiom: one quiet line, not the section being unavailable."""
        document = to_home_dashboard_response(
            dashboard(upcoming_dates=DashboardSection.ready(dates()))
        ).model_dump(mode="json")

        section = document["data"]["attributes"]["upcoming_dates"]
        assert section["status"] == "ready"
        assert section["data"]["dates"] == []
        assert section["data"]["total"] == 0

    def test_an_unavailable_section_is_told_apart_from_an_empty_one(self) -> None:
        document = to_home_dashboard_response(
            dashboard(upcoming_dates=DashboardSection.unavailable())
        ).model_dump(mode="json")

        section = document["data"]["attributes"]["upcoming_dates"]
        assert section["status"] == "unavailable"
        assert section["data"] is None

    def test_the_rest_of_the_page_survives_it(self) -> None:
        document = to_home_dashboard_response(
            dashboard(upcoming_dates=DashboardSection.unavailable())
        ).model_dump(mode="json")

        attributes = document["data"]["attributes"]
        assert attributes["summary"]["status"] == "ready"
        assert attributes["agenda"]["status"] == "ready"

    def test_the_rows_carry_no_ranking_signals(self) -> None:
        """Contact importance decides the order and is not otherwise the user's
        business — the specification requires it stay inferred and unconfigured,
        and a payload that published it would invite a surface to show it."""
        document = to_home_dashboard_response(
            dashboard(upcoming_dates=DashboardSection.ready(dates(BIRTHDAY)))
        ).model_dump(mode="json")

        assert set(self.section_of(document)["dates"][0]) == {
            "contact_id",
            "contact_name",
            "photo_url",
            "date_type",
            "custom_date_type_name",
            "occurs_on",
            "days_away",
            "years",
            "observed_for_leap_day",
        }


class TestTheTasksSection:
    """The section's wire shape: the window, the count, and what a row draws.

    The rows arrive already selected and already ordered, so nothing here is
    about which tasks are due — it is about the row a card can render from and
    the fields that are deliberately **not** in it.
    """

    def payload_of(self, document: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = document["data"]["attributes"]["tasks"]["data"]
        return payload

    def test_the_window_travels_with_the_rows(self) -> None:
        """W28 names a week; the section has to be able to say which one."""
        document = to_home_dashboard_response(dashboard()).model_dump(mode="json")

        assert self.payload_of(document)["window"] == {
            "start_date": "2026-07-31",
            "end_date": "2026-08-07",
            "days_ahead": 7,
        }

    def test_the_window_is_the_same_span_the_dates_beside_it_report(self) -> None:
        """One week two sections agree on, not two that happen to match today."""
        document = to_home_dashboard_response(dashboard()).model_dump(mode="json")

        attributes = document["data"]["attributes"]
        assert (
            self.payload_of(document)["window"]
            == attributes["upcoming_dates"]["data"]["window"]
        )

    def test_the_total_names_the_whole_window_rather_than_a_page(self) -> None:
        """Nothing is capped server-side, so the count equals the rows sent.

        It is named anyway because it is the number the show-more displays, and
        naming it keeps a reader from mistaking it for a pagination total that
        might exceed what arrived.
        """
        document = to_home_dashboard_response(
            dashboard(
                tasks=DashboardSection.ready(
                    tasks(
                        *(task_row(index, days_away=index % 8) for index in range(1, 9))
                    )
                )
            )
        ).model_dump(mode="json")

        payload = self.payload_of(document)
        assert payload["total"] == 8 == len(payload["tasks"])

    def test_a_row_carries_exactly_what_a_row_draws(self) -> None:
        """The key set is pinned, because the omissions are the decision.

        Every row here is not done, not lapsed and due in an uncancelled
        journal — those are the section's entry conditions — so publishing the
        status, the lapse or the due journal's cancelled flag would send a
        constant and invite a surface to branch on it. The creating and
        intermediate journals are material no dashboard row shows.
        """
        document = to_home_dashboard_response(
            dashboard(tasks=DashboardSection.ready(tasks(task_row(12, days_away=1))))
        ).model_dump(mode="json")

        (row,) = self.payload_of(document)["tasks"]
        assert set(row) == {
            "task_id",
            "text",
            "due_journal",
            "days_away",
            "contacts",
        }
        assert set(row["due_journal"]) == {"id", "title", "date"}

    def test_a_row_carries_the_task_and_its_due_journal(self) -> None:
        document = to_home_dashboard_response(
            dashboard(
                tasks=DashboardSection.ready(
                    tasks(
                        task_row(
                            12,
                            days_away=1,
                            text="book the venue",
                            title="Monday standup",
                        )
                    )
                )
            )
        ).model_dump(mode="json")

        (row,) = self.payload_of(document)["tasks"]
        assert row["task_id"] == 12
        assert row["text"] == "book the venue"
        assert row["due_journal"] == {
            "id": 912,
            "title": "Monday standup",
            "date": "2026-08-01",
        }

    def test_a_row_carries_the_days_away_the_chip_is_drawn_from(self) -> None:
        """W25 renders ``Today``/``Tomorrow`` from this rather than from a clock."""
        document = to_home_dashboard_response(
            dashboard(
                tasks=DashboardSection.ready(
                    tasks(task_row(1, days_away=0), task_row(2, days_away=1))
                )
            )
        ).model_dump(mode="json")

        assert [row["days_away"] for row in self.payload_of(document)["tasks"]] == [
            0,
            1,
        ]

    def test_a_rows_contacts_carry_a_name_and_an_avatar(self) -> None:
        """W27 draws an avatar beside a full name, so both are on the wire."""
        document = to_home_dashboard_response(
            dashboard(
                tasks=DashboardSection.ready(
                    tasks(
                        task_row(
                            12,
                            days_away=1,
                            contacts=(
                                TaskContactRef(
                                    id=5,
                                    display_name="Ada Lovelace",
                                    photo_url="/photos/ada.png",
                                ),
                                TaskContactRef(
                                    id=2, display_name="Grace Hopper", photo_url=None
                                ),
                            ),
                        )
                    )
                )
            )
        ).model_dump(mode="json")

        (row,) = self.payload_of(document)["tasks"]
        assert row["contacts"] == [
            {"contact_id": 5, "name": "Ada Lovelace", "photo_url": "/photos/ada.png"},
            {"contact_id": 2, "name": "Grace Hopper", "photo_url": None},
        ]

    def test_a_row_with_nobody_on_it_carries_an_empty_list(self) -> None:
        """W27 renders nothing for zero contacts; null would be a third case."""
        document = to_home_dashboard_response(
            dashboard(tasks=DashboardSection.ready(tasks(task_row(12, days_away=1))))
        ).model_dump(mode="json")

        (row,) = self.payload_of(document)["tasks"]
        assert row["contacts"] == []

    def test_it_keeps_the_order_the_service_put_the_rows_in(self) -> None:
        """Soonest first was decided upstream; the renderer must not re-sort."""
        document = to_home_dashboard_response(
            dashboard(
                tasks=DashboardSection.ready(
                    tasks(
                        task_row(1, days_away=0),
                        task_row(2, days_away=3),
                        task_row(3, days_away=7),
                    )
                )
            )
        ).model_dump(mode="json")

        rows = self.payload_of(document)["tasks"]
        assert [row["task_id"] for row in rows] == [1, 2, 3]

    def test_nothing_due_this_week_is_a_ready_empty_list(self) -> None:
        """W29 reads as a good outcome, and it still needs its window."""
        document = to_home_dashboard_response(dashboard()).model_dump(mode="json")

        section = document["data"]["attributes"]["tasks"]
        assert section["status"] == "ready"
        assert section["data"]["tasks"] == []
        assert section["data"]["total"] == 0
        assert section["data"]["window"]["start_date"] == "2026-07-31"

    def test_an_unavailable_section_is_told_apart_from_an_empty_one(self) -> None:
        document = to_home_dashboard_response(
            dashboard(tasks=DashboardSection.unavailable())
        ).model_dump(mode="json")

        assert document["data"]["attributes"]["tasks"] == {
            "status": "unavailable",
            "data": None,
        }

    def test_the_rest_of_the_page_survives_it(self) -> None:
        document = to_home_dashboard_response(
            dashboard(tasks=DashboardSection.unavailable())
        ).model_dump(mode="json")

        for name in ("summary", "agenda", "upcoming_dates"):
            assert document["data"]["attributes"][name]["status"] == "ready", name
