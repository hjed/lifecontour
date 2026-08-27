"""Integration tests for the home dashboard's agenda section.

Exercises ``GET /api/home-dashboard``'s agenda against real journals, real
``journal_calendar_info`` rows, real tag assignments and real contact
relationships, because a query that reads correctly against a mock can still be
asking about the wrong day, joining the wrong rows, or fanning out.

Four things are asserted here that no unit test can reach:

- **What is on the agenda at all** — an event journal overlapping the user's local
  day, and nothing else: not a journal without calendar info, not one on another
  day, and never another user's.
- **Which day that is.** Two users twenty-five hours apart are never on the same
  date, so a UTC-anchored implementation cannot satisfy both readings.
- **The nested reads are not N+1.** Tags and participants are many-per-journal and
  the obvious implementation loops; the statement count says whether this one
  does, and a functional assertion never would.
- **A cancelled event is flagged, not dropped**, so the payload can never present
  one as still happening.

A test cannot freeze the clock through HTTP, so journals are seeded relative to
an instant read inside the test and the windows are chosen wide enough that a
midnight crossing mid-test cannot turn a correct answer into a failure — the same
bracketing ``test_home_dashboard_api.py`` uses.
"""

import datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.settings.models import UserSettings
from tests.integration.statement_recorder import recorded_statements

URL = "/api/home-dashboard"
USER_ID = "test-user-123"
OTHER_USER_ID = "test-user-456"

# A large positive offset, so one local day spans two UTC dates.
FAR_EAST = "Pacific/Kiritimati"  # UTC+14
# A large negative offset — the side of UTC an all-day event read by instant
# lands on the wrong day for.
FAR_WEST = "Pacific/Niue"  # UTC-11


def agenda_of(response: Any) -> dict[str, Any]:
    section: dict[str, Any] = response.json()["data"]["attributes"]["agenda"]
    return section


def entries_of(response: Any) -> list[dict[str, Any]]:
    section = agenda_of(response)
    assert section["status"] == "ready", section
    entries: list[dict[str, Any]] = section["data"]["entries"]
    return entries


class EventSeeder:
    """Seeds EVENT journals — the only kind the agenda shows.

    A journal has the EVENT type exactly when a ``journal_calendar_info`` row
    exists for it, so that row is what makes a seeded journal an agenda entry,
    and a journal seeded without one is this suite's negative case.

    Local-day placement is done here rather than in each test: the caller says
    "midday in this zone, ``day_offset`` days from now" and the seeder turns it
    into the UTC instant the column stores. Midday rather than an edge so a
    midnight crossing while the test runs cannot move the journal off the day it
    was seeded onto.
    """

    def __init__(self, connection: AsyncConnection) -> None:
        self.connection = connection
        self._calendar_id: UUID | None = None

    async def calendar(self) -> UUID:
        """One calendar for the whole test, created on first use."""
        if self._calendar_id is None:
            result = await self.connection.execute(
                text(
                    """
                    INSERT INTO calendars (user_id, name, color)
                    VALUES (:user_id, 'Seeded', '#336699')
                    RETURNING id
                    """
                ),
                {"user_id": USER_ID},
            )
            self._calendar_id = UUID(str(result.scalar()))
        return self._calendar_id

    async def event(
        self,
        *,
        title: str = "An event",
        user_id: str = USER_ID,
        timezone: str = "UTC",
        day_offset: int = 0,
        hour: int = 12,
        duration_hours: int = 1,
        ends_days_later: int = 0,
        all_day: bool = False,
        location: str | None = None,
        event_state: str = "confirmed",
        with_calendar_info: bool = True,
    ) -> int:
        """One journal, optionally with the calendar info that makes it an event."""
        tz = ZoneInfo(timezone)
        local_day = datetime.datetime.now(tz).date() + datetime.timedelta(
            days=day_offset
        )
        start = datetime.datetime.combine(local_day, datetime.time(hour), tz)
        end = start + datetime.timedelta(hours=duration_hours, days=ends_days_later)

        result = await self.connection.execute(
            text(
                """
                INSERT INTO journals
                    (user_id, title, content,
                     event_date_range_start, event_date_range_end)
                VALUES (:user_id, :title, '', :start, :end)
                RETURNING id
                """
            ),
            {"user_id": user_id, "title": title, "start": start, "end": end},
        )
        journal_id = int(result.scalar_one())

        if with_calendar_info:
            await self.connection.execute(
                text(
                    """
                    INSERT INTO journal_calendar_info
                        (journal_id, calendar_id, start_time, end_time,
                         is_all_day, location, timezone, event_state)
                    VALUES (:journal_id, :calendar_id, :start_time, :end_time,
                            :all_day, :location, :timezone, :event_state)
                    """
                ),
                {
                    "journal_id": journal_id,
                    "calendar_id": await self.calendar(),
                    "start_time": None if all_day else start.time(),
                    "end_time": None if all_day else end.time(),
                    "all_day": all_day,
                    "location": location,
                    "timezone": timezone,
                    "event_state": event_state,
                },
            )
        return journal_id

    async def all_day_on(
        self, day: datetime.date, *, title: str, written_in: str | None = None
    ) -> int:
        """An all-day journal for ``day``, in one of the two storage conventions.

        ``written_in=None`` is the **Google** convention: both bounds at midnight
        UTC and no event timezone, which is what ``_parse_all_day_date`` writes
        for a date-only event. Passing a zone is the **app** convention: midnight
        in that zone, with the zone recorded — which is what the create form plus
        ``EventTypeEditor`` produce.
        """
        zone = ZoneInfo(written_in) if written_in else datetime.UTC
        midnight = datetime.datetime.combine(day, datetime.time.min, zone)

        result = await self.connection.execute(
            text(
                """
                INSERT INTO journals
                    (user_id, title, content,
                     event_date_range_start, event_date_range_end)
                VALUES (:user_id, :title, '', :start, :end)
                RETURNING id
                """
            ),
            {"user_id": USER_ID, "title": title, "start": midnight, "end": midnight},
        )
        journal_id = int(result.scalar_one())
        await self.connection.execute(
            text(
                """
                INSERT INTO journal_calendar_info
                    (journal_id, calendar_id, is_all_day, timezone, event_state)
                VALUES (:journal_id, :calendar_id, true, :timezone, 'confirmed')
                """
            ),
            {
                "journal_id": journal_id,
                "calendar_id": await self.calendar(),
                "timezone": written_in,
            },
        )
        return journal_id

    async def tag(self, journal_id: int, name: str, colour: str = "#ff0000") -> UUID:
        """A freshly created tag, assigned to a journal."""
        result = await self.connection.execute(
            text(
                """
                INSERT INTO journal_tags (name, color) VALUES (:name, :colour)
                RETURNING id
                """
            ),
            {"name": name, "colour": colour},
        )
        tag_id = UUID(str(result.scalar()))
        await self.connection.execute(
            text(
                """
                INSERT INTO journal_tag_assignments (journal_id, tag_id)
                VALUES (:journal_id, :tag_id)
                """
            ),
            {"journal_id": journal_id, "tag_id": tag_id},
        )
        return tag_id

    async def link_existing_contact(
        self, journal_id: int, contact_id: int, *, relationship_type: str
    ) -> None:
        """A second relationship row for a contact already on the journal."""
        await self.connection.execute(
            text(
                """
                INSERT INTO journal_contact_relationships
                    (journal_id, contact_id, relationship_type)
                VALUES (:journal_id, :contact_id, :relationship_type)
                """
            ),
            {
                "journal_id": journal_id,
                "contact_id": contact_id,
                "relationship_type": relationship_type,
            },
        )

    async def participant(
        self,
        journal_id: int,
        first_name: str,
        last_name: str | None = None,
        relationship_type: str = "PARTICIPANT",
    ) -> int:
        result = await self.connection.execute(
            text(
                """
                INSERT INTO contacts (first_name, last_name)
                VALUES (:first_name, :last_name) RETURNING id
                """
            ),
            {"first_name": first_name, "last_name": last_name},
        )
        contact_id = int(result.scalar_one())
        await self.connection.execute(
            text(
                """
                INSERT INTO journal_contact_relationships
                    (journal_id, contact_id, relationship_type)
                VALUES (:journal_id, :contact_id, :relationship_type)
                """
            ),
            {
                "journal_id": journal_id,
                "contact_id": contact_id,
                "relationship_type": relationship_type,
            },
        )
        return contact_id


@pytest.fixture
def seeder(async_connection: AsyncConnection) -> EventSeeder:
    """The seeder on the test's savepoint connection.

    The same connection the request reads through, injected by
    ``TestDatabaseProvider``, so rows written here are visible to the endpoint
    without a commit and are rolled back with the test.
    """
    return EventSeeder(async_connection)


@pytest.mark.asyncio
class TestWhatReachesTheAgenda:
    async def test_todays_event_journal_arrives_with_everything_the_card_draws(
        self, authenticated_client: AsyncClient, seeder: EventSeeder
    ) -> None:
        journal_id = await seeder.event(
            title="Coffee with Sam", hour=9, location="The good place"
        )
        tag_id = await seeder.tag(journal_id, "social", "#ff0000")
        contact_id = await seeder.participant(journal_id, "Sam", "Taylor")

        entries = entries_of(await authenticated_client.get(URL))

        assert len(entries) == 1
        entry = entries[0]
        assert entry["journal_id"] == journal_id
        assert entry["title"] == "Coffee with Sam"
        assert entry["is_all_day"] is False
        assert entry["start_time"] == "09:00:00"
        assert entry["location"] == "The good place"
        # W17 keys the row's accent bar to this; the seeded calendar's colour.
        assert entry["calendar_color"] == "#336699"
        assert entry["is_cancelled"] is False
        assert entry["tags"] == [
            {"id": str(tag_id), "name": "social", "color": "#ff0000"}
        ]
        assert entry["participants"] == [
            {"contact_id": contact_id, "name": "Sam Taylor"}
        ]

    async def test_the_clock_times_come_back_in_the_events_own_zone(
        self, authenticated_client: AsyncClient, seeder: EventSeeder
    ) -> None:
        """The stored clock values are the event's wall time, and say so.

        Seeded in a zone the reader is not in, so a payload that quietly
        converted the times — or dropped the zone that makes them readable —
        fails here rather than in a card three phases on.
        """
        await seeder.event(title="Kiritimati morning", timezone=FAR_EAST, hour=9)

        entry = entries_of(await authenticated_client.get(URL))[0]

        assert entry["timezone"] == FAR_EAST
        assert entry["start_time"] == "09:00:00"

    async def test_a_journal_with_no_calendar_info_is_not_an_event(
        self, authenticated_client: AsyncClient, seeder: EventSeeder
    ) -> None:
        """The agenda is today's *schedule*, not today's journals.

        A journal has the EVENT type exactly when it has a calendar info row, so
        one without it is a note about the day rather than something on it.
        """
        await seeder.event(title="Just a note", with_calendar_info=False)

        assert entries_of(await authenticated_client.get(URL)) == []

    async def test_a_journal_on_another_day_is_absent(
        self, authenticated_client: AsyncClient, seeder: EventSeeder
    ) -> None:
        await seeder.event(title="Last week", day_offset=-7)
        await seeder.event(title="Next week", day_offset=7)

        assert entries_of(await authenticated_client.get(URL)) == []

    async def test_a_multi_day_journal_overlapping_today_is_present(
        self, authenticated_client: AsyncClient, seeder: EventSeeder
    ) -> None:
        """Overlap, not containment: a trip under way is part of today.

        The window compares against both ends of ``event_date_range``, so an
        event that began two days ago and ends tomorrow is on today's agenda even
        though neither of its ends falls inside the day.
        """
        journal_id = await seeder.event(
            title="Three days on the river", day_offset=-2, ends_days_later=3
        )

        entries = entries_of(await authenticated_client.get(URL))

        assert [entry["journal_id"] for entry in entries] == [journal_id]

    async def test_another_users_event_is_never_returned(
        self, authenticated_client: AsyncClient, seeder: EventSeeder
    ) -> None:
        """Scoped on ``journals.user_id``, which is the only owner in this join."""
        mine = await seeder.event(title="Mine", hour=9)
        await seeder.event(title="Theirs", hour=10, user_id=OTHER_USER_ID)

        entries = entries_of(await authenticated_client.get(URL))

        assert [entry["journal_id"] for entry in entries] == [mine]
        assert "Theirs" not in (await authenticated_client.get(URL)).text


@pytest.mark.asyncio
class TestWhoCountsAsAParticipant:
    """Both ways of being at an event, and neither way of merely being in it.

    ``PARTICIPANT`` and ``INVITEE`` are the pair the journal's own contact badge
    treats as attendance, and the Google worker writes every synced attendee as
    ``INVITEE`` — so an agenda that took only ``PARTICIPANT`` would show an empty
    avatar stack on exactly the events most users have most of. ``MENTION`` and
    ``ABOUT`` are people the journal is *about*, who were never claimed to be
    there, and showing them as attendees would be a false statement rather than
    an over-inclusive one.
    """

    async def test_an_invitee_is_shown_beside_a_participant(
        self, authenticated_client: AsyncClient, seeder: EventSeeder
    ) -> None:
        journal_id = await seeder.event(title="Team lunch", hour=12)
        await seeder.participant(journal_id, "Sam", "Taylor")
        await seeder.participant(journal_id, "Alex", "Kim", relationship_type="INVITEE")

        entries = entries_of(await authenticated_client.get(URL))

        names = {person["name"] for person in entries[0]["participants"]}
        assert names == {"Sam Taylor", "Alex Kim"}

    async def test_one_contact_holding_both_roles_appears_once(
        self, authenticated_client: AsyncClient, seeder: EventSeeder
    ) -> None:
        """The relationship key is (journal, contact, type), so both can exist.

        A contact merge reaches that state on its own — its own dedupe is per
        relationship type — and without DISTINCT the avatar stack would draw the
        same face twice and inflate its overflow count.
        """
        journal_id = await seeder.event(title="Team lunch", hour=12)
        contact_id = await seeder.participant(journal_id, "Sam", "Taylor")
        await seeder.link_existing_contact(
            journal_id, contact_id, relationship_type="INVITEE"
        )

        entries = entries_of(await authenticated_client.get(URL))

        assert entries[0]["participants"] == [
            {"contact_id": contact_id, "name": "Sam Taylor"}
        ]

    async def test_a_mentioned_contact_is_not_an_attendee(
        self, authenticated_client: AsyncClient, seeder: EventSeeder
    ) -> None:
        journal_id = await seeder.event(title="Team lunch", hour=12)
        await seeder.participant(journal_id, "Sam", "Taylor")
        await seeder.participant(
            journal_id, "Talked", "About", relationship_type="MENTION"
        )

        entries = entries_of(await authenticated_client.get(URL))

        assert [person["name"] for person in entries[0]["participants"]] == [
            "Sam Taylor"
        ]


@pytest.mark.asyncio
class TestTheOrderOnTheWire:
    async def test_all_day_entries_precede_timed_ones_and_timed_ones_ascend(
        self, authenticated_client: AsyncClient, seeder: EventSeeder
    ) -> None:
        """W12 then W13, end to end — seeded deliberately out of order."""
        await seeder.event(title="Dinner", hour=19)
        await seeder.event(title="Standup", hour=9)
        await seeder.event(title="Public holiday", all_day=True, hour=0)
        await seeder.event(title="Lunch", hour=12)

        entries = entries_of(await authenticated_client.get(URL))

        assert [entry["title"] for entry in entries] == [
            "Public holiday",
            "Standup",
            "Lunch",
            "Dinner",
        ]


@pytest.mark.asyncio
class TestTheDayBoundary:
    """The window is the user's local day, and UTC's day is a different set.

    **Being twenty-five hours apart is not what separates two zones' days.** A
    +14 zone and a -11 zone are never on the same *date*, but their day windows
    overlap by twenty-three hours, so an event seeded in one is almost always in
    the other too. What actually separates a local day from UTC's is that a local
    day in a large offset spans **two UTC dates**: `Pacific/Kiritimati`'s day
    runs from 10:00 UTC to 10:00 UTC, so its morning and its evening fall on
    either side of a UTC midnight.

    So the discriminator is a pair — one event before that midnight and one
    after, both on the same local day. Whichever UTC date a UTC-anchored
    implementation picked, it could return at most one of them; only a
    locally-anchored one returns both. The pair is seeded on three consecutive
    local days and the assertion is keyed on the anchor the server reports, so a
    midnight crossing mid-test moves the expectation with the answer instead of
    failing a request the endpoint handled correctly.
    """

    NOON = "noon"
    NIGHT = "night"

    async def seed_three_days(self, seeder: EventSeeder) -> None:
        """Two events on each of yesterday, today and tomorrow, in FAR_EAST.

        12:00 local is 22:00 UTC on the previous UTC date; 22:00 local is 08:00
        UTC on the next one. Neither neighbouring day's pair can reach today's
        window: yesterday's night is 08:00 UTC, two hours before this local day
        opens, and tomorrow's noon is 22:00 UTC, twelve hours after it closes.
        """
        for day_offset in (-1, 0, 1):
            local_day = datetime.datetime.now(ZoneInfo(FAR_EAST)).date() + (
                datetime.timedelta(days=day_offset)
            )
            for hour, label in ((12, self.NOON), (22, self.NIGHT)):
                await seeder.event(
                    title=f"{local_day.isoformat()} {label}",
                    timezone=FAR_EAST,
                    day_offset=day_offset,
                    hour=hour,
                )

    async def test_one_local_day_arrives_whole_though_it_spans_two_utc_dates(
        self,
        authenticated_client: AsyncClient,
        user_settings_repository: SqlUserSettingsRepository,
        seeder: EventSeeder,
    ) -> None:
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone=FAR_EAST)
        )
        await self.seed_three_days(seeder)

        response = await authenticated_client.get(URL)

        anchor = response.json()["meta"]["anchor"]["date"]
        assert [entry["title"] for entry in entries_of(response)] == [
            f"{anchor} {self.NOON}",
            f"{anchor} {self.NIGHT}",
        ]

    async def test_the_neighbouring_local_days_stay_off_it(
        self,
        authenticated_client: AsyncClient,
        user_settings_repository: SqlUserSettingsRepository,
        seeder: EventSeeder,
    ) -> None:
        """The two days either side are the near misses, so they are named.

        Distinct from the test above, which pins what the day *contains*: this
        one pins that a window built one UTC date too wide in either direction
        would pick up a neighbour, and says which neighbour it would be.
        """
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone=FAR_EAST)
        )
        await self.seed_three_days(seeder)

        response = await authenticated_client.get(URL)

        anchor = datetime.date.fromisoformat(response.json()["meta"]["anchor"]["date"])
        titles = {entry["title"] for entry in entries_of(response)}
        for neighbour in (
            anchor - datetime.timedelta(days=1),
            anchor + (datetime.timedelta(days=1)),
        ):
            assert f"{neighbour.isoformat()} {self.NOON}" not in titles
            assert f"{neighbour.isoformat()} {self.NIGHT}" not in titles

    async def test_the_anchor_reports_the_zone_the_window_was_built_in(
        self,
        authenticated_client: AsyncClient,
        user_settings_repository: SqlUserSettingsRepository,
        seeder: EventSeeder,
    ) -> None:
        """The page labels itself from ``meta.anchor``, so it must agree.

        Bracketed either side of the request because a local midnight can pass
        while it is in flight, which is not a defect in the answer.
        """
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone=FAR_EAST)
        )
        before = datetime.datetime.now(ZoneInfo(FAR_EAST)).date()
        document = (await authenticated_client.get(URL)).json()
        after = datetime.datetime.now(ZoneInfo(FAR_EAST)).date()

        assert document["meta"]["anchor"]["timezone"] == FAR_EAST
        assert document["meta"]["anchor"]["date"] in {
            before.isoformat(),
            after.isoformat(),
        }


@pytest.mark.asyncio
class TestACancelledEvent:
    async def test_is_returned_flagged_rather_than_omitted(
        self, authenticated_client: AsyncClient, seeder: EventSeeder
    ) -> None:
        """W18: shown, never hidden — and never as if it were still happening.

        Omitting it would be the other reading the specification allows, but the
        payload is not the surface that gets to choose: the flag is what lets the
        card mark it, and a card cannot mark an entry it was never sent.
        """
        journal_id = await seeder.event(
            title="Postponed standup", hour=9, event_state="cancelled"
        )

        entries = entries_of(await authenticated_client.get(URL))

        assert [entry["journal_id"] for entry in entries] == [journal_id]
        assert entries[0]["is_cancelled"] is True

    async def test_a_confirmed_event_beside_it_is_not_flagged(
        self, authenticated_client: AsyncClient, seeder: EventSeeder
    ) -> None:
        """Proof the flag is read from the row rather than defaulted."""
        await seeder.event(title="Postponed", hour=9, event_state="cancelled")
        await seeder.event(title="Going ahead", hour=10)

        flags = {
            entry["title"]: entry["is_cancelled"]
            for entry in entries_of(await authenticated_client.get(URL))
        }

        assert flags == {"Postponed": True, "Going ahead": False}


@pytest.mark.asyncio
class TestTheNestedReadsAreNotAnNPlusOne:
    async def test_eight_events_with_tags_and_participants_cost_what_two_do(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        seeder: EventSeeder,
    ) -> None:
        """The criterion is "one query, not one per journal", so it is counted.

        Functionally an N+1 is invisible — the answer is right either way — so
        only the statement count can tell a single aggregated read from a loop
        over the day's events.
        """
        for index in range(2):
            journal_id = await seeder.event(title=f"Early {index}", hour=8)
            await seeder.tag(journal_id, f"tag-{index}")
            await seeder.participant(journal_id, f"Person{index}")

        with recorded_statements(async_connection) as few:
            await authenticated_client.get(URL)

        for index in range(2, 8):
            journal_id = await seeder.event(title=f"Later {index}", hour=9)
            await seeder.tag(journal_id, f"tag-{index}")
            await seeder.participant(journal_id, f"Person{index}")

        with recorded_statements(async_connection) as many:
            response = await authenticated_client.get(URL)

        assert len(entries_of(response)) == 8
        assert len(many) == len(few)


@pytest.mark.asyncio
class TestADayWithNothingOnIt:
    async def test_is_ready_with_an_empty_list_rather_than_unavailable(
        self, authenticated_client: AsyncClient
    ) -> None:
        """The distinction the card's single quiet line depends on."""
        assert agenda_of(await authenticated_client.get(URL)) == {
            "status": "ready",
            "data": {"entries": []},
        }


@pytest.mark.asyncio
class TestTheAgendaDoesNotWrite:
    async def test_reading_the_dashboard_leaves_the_journal_untouched(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        seeder: EventSeeder,
    ) -> None:
        """A page load must not mutate, and the agenda is the second read to try.

        Asserted on the statements rather than on a timestamp: ``now()`` is the
        transaction's clock and the fixture shares one transaction, so an
        unchanged ``updated_at`` would prove nothing either way.
        """
        await seeder.event(title="Coffee with Sam", hour=9)

        with recorded_statements(async_connection) as statements:
            await authenticated_client.get(URL)

        written = [
            statement
            for statement in statements
            if statement.strip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}
        ]
        assert written == []


@pytest.mark.asyncio
class TestAnAllDayEventLandsOnItsOwnDate:
    """All-day events are matched by date, and instants cannot do that job.

    An all-day event happens on a *date*, but the schema stores only instants and
    the two writers disagree about which instant means that date: the Google
    worker writes midnight **UTC** with no event timezone, while the app writes
    midnight in the browser's zone and records it. Matching by instant therefore
    reads a synced holiday onto the previous day for every user west of UTC —
    which is the case these tests exist to hold shut.

    Each test seeds the same event on three consecutive dates and asserts against
    the anchor the server reports, so a midnight crossing mid-test moves the
    expectation with the answer rather than failing a correct response.
    """

    async def seed_three_dates(
        self, seeder: EventSeeder, timezone: str, *, written_in: str | None
    ) -> None:
        for offset in (-1, 0, 1):
            day = datetime.datetime.now(ZoneInfo(timezone)).date() + (
                datetime.timedelta(days=offset)
            )
            await seeder.all_day_on(
                day, title=f"Holiday {day.isoformat()}", written_in=written_in
            )

    @pytest.mark.parametrize("timezone", [FAR_WEST, FAR_EAST])
    async def test_a_google_written_event_is_read_as_the_date_it_says(
        self,
        authenticated_client: AsyncClient,
        user_settings_repository: SqlUserSettingsRepository,
        seeder: EventSeeder,
        timezone: str,
    ) -> None:
        """Both sides of UTC, because only one of them was ever broken.

        Under instant matching the far-western user got the previous day's
        holiday and never today's, while the far-eastern user was correct — so
        asserting only one side would pass on the bug half the time.
        """
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone=timezone)
        )
        await self.seed_three_dates(seeder, timezone, written_in=None)

        response = await authenticated_client.get(URL)

        anchor = response.json()["meta"]["anchor"]["date"]
        assert [entry["title"] for entry in entries_of(response)] == [
            f"Holiday {anchor}"
        ]

    async def test_an_app_written_event_keeps_working(
        self,
        authenticated_client: AsyncClient,
        user_settings_repository: SqlUserSettingsRepository,
        seeder: EventSeeder,
    ) -> None:
        """The convention that was already correct must stay correct.

        Its instant is local midnight and its zone is recorded, so reading the
        bounds back in that zone returns the same date it was written as.
        """
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone=FAR_WEST)
        )
        await self.seed_three_dates(seeder, FAR_WEST, written_in=FAR_WEST)

        response = await authenticated_client.get(URL)

        anchor = response.json()["meta"]["anchor"]["date"]
        assert [entry["title"] for entry in entries_of(response)] == [
            f"Holiday {anchor}"
        ]

    async def test_a_multi_day_all_day_event_covers_every_date_it_spans(
        self,
        authenticated_client: AsyncClient,
        user_settings_repository: SqlUserSettingsRepository,
        seeder: EventSeeder,
    ) -> None:
        """Date-space overlap, matching what instants do for timed events."""
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone=FAR_WEST)
        )
        today = datetime.datetime.now(ZoneInfo(FAR_WEST)).date()
        journal_id = await seeder.all_day_on(
            today - datetime.timedelta(days=1), title="Long weekend"
        )
        await seeder.connection.execute(
            text(
                """
                UPDATE journals SET event_date_range_end = :end WHERE id = :id
                """
            ),
            {
                "id": journal_id,
                "end": datetime.datetime.combine(
                    today + datetime.timedelta(days=1),
                    datetime.time.min,
                    datetime.UTC,
                ),
            },
        )

        entries = entries_of(await authenticated_client.get(URL))

        assert [entry["journal_id"] for entry in entries] == [journal_id]

    async def test_a_timed_event_is_still_matched_on_instants(
        self,
        authenticated_client: AsyncClient,
        user_settings_repository: SqlUserSettingsRepository,
        seeder: EventSeeder,
    ) -> None:
        """The date rule is for all-day rows only, and must not leak.

        A far-western user's midday is on the *following* UTC date, so a timed
        event matched by its UTC date rather than its instant would vanish.
        """
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone=FAR_WEST)
        )
        journal_id = await seeder.event(
            title="Far-western midday", timezone=FAR_WEST, hour=12
        )

        entries = entries_of(await authenticated_client.get(URL))

        assert [entry["journal_id"] for entry in entries] == [journal_id]
