"""Integration tests for the home dashboard's tasks section.

Exercises ``GET /api/home-dashboard``'s third section against real tasks, real
journal anchors and a real ``journal_calendar_info`` row, because a section that
is correct against a double can still be asking the database about the wrong
week, fanning out per task, or quietly showing a commitment that was called off.

The section adds no query of its own — it reuses the upcoming-window listing,
whose own edges are pinned with a frozen clock in
``tests/integration/tasks/test_task_upcoming_listing_integration.py``. So what
is asserted here is what only this surface can show:

- **The row a card draws arrives whole** — the text, the due journal, how far
  away it is and who is on it — through the endpoint rather than the renderer.
- **The section windows on the day the page is anchored on**, whatever zone the
  user is in, so the tasks and the dates beside them cannot be about different
  weeks.
- **The exclusions survive the reuse.** Done, cancelled and lapsed tasks are
  absent here while the same task is still on its journal, which is the pair the
  specification actually promises: hidden, not lost.
- **One page load costs the same whatever is due**, which no answer can show.

A test cannot freeze the clock through HTTP, so tasks are seeded relative to an
instant read inside the test — the bracketing the agenda and upcoming-dates
suites use. Membership cases sit mid-window, where a midnight crossing cannot
change the answer. **Three cases are unavoidably clock-relative**: a task due
today, one due on the window's last day, and one due the day after it. All three
flip if UTC's date turns over between seeding the journal and the request, so
each calls ``guard_no_rollover`` first — the anchor is compared against the day
the fixture was built for, and a crossing fails *there*, naming itself, instead
of surfacing as an inexplicable off-by-one in the assertion under test. The
window's own edges are pinned against a frozen clock where one can be injected,
in ``tests/integration/tasks/test_task_upcoming_listing_integration.py``.

**The cancelled due journal is written as a ``journal_calendar_info`` row**
rather than driven through the calendar sync processor. That seam — a real
cancellation leaving the state the lapse rule looks for — is what
``tests/integration/tasks/test_journal_cancellation_lapse_integration.py``
exists for, across all three production paths that write it; re-driving the
processor from a dashboard test would assert somebody else's seam a third time.
What this file needs from the fixture is a task the exclusion must drop.
"""

import datetime
from typing import Any

import pytest
from core_shared.models.journals.event_state import EventState
from core_shared.models.tasks import TaskStatus
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.settings.models import UserSettings
from tests.integration.statement_recorder import recorded_statements
from tests.integration.tasks.task_seeding import (
    OTHER_USER_ID,
    USER_ID,
    create_contact,
    create_journal,
    create_task,
    link_contact,
    mark_journal_as_event,
)

URL = "/api/home-dashboard"

# A large positive offset, so one local day spans two UTC dates.
FAR_EAST = "Pacific/Kiritimati"  # UTC+14

pytestmark = pytest.mark.asyncio


def section_of(response: Any) -> dict[str, Any]:
    """The tasks section's envelope."""
    assert response.status_code == 200
    section: dict[str, Any] = response.json()["data"]["attributes"]["tasks"]
    return section


def rows_of(response: Any) -> list[dict[str, Any]]:
    """The rows in the section, in the order they were sent."""
    section = section_of(response)
    assert section["status"] == "ready", section
    return list(section["data"]["tasks"])


def anchor_of(response: Any) -> datetime.date:
    """The day the whole page was read for, as the server resolved it."""
    return datetime.date.fromisoformat(response.json()["meta"]["anchor"]["date"])


async def due_journal(
    journal_repository: SqlJournalRepository,
    *,
    days_offset: int,
    title: str = "Permit meeting",
) -> int:
    """A journal to be due in, placed relative to the real clock."""
    return await create_journal(
        journal_repository, title=title, days_offset=days_offset
    )


def guard_no_rollover(response: Any, seeded_for: datetime.date) -> None:
    """Fail here, rather than in the assertion, if UTC's date turned over.

    The three edge cases in this file seed a journal at ``now + N days`` and
    then assert an exact ``days_away``. If midnight passes between the two, the
    journal keeps the date it was given while the anchor moves on, and the
    expected number is off by one — through no fault of the code. The test user
    has no stored timezone, so the anchor is UTC's today and this comparison is
    exact.
    """
    assert anchor_of(response) == seeded_for, (
        "UTC's date rolled over mid-test; the fixture was seeded for "
        f"{seeded_for} and the page anchored on {anchor_of(response)}"
    )


class TestWhatReachesTheSection:
    async def test_a_task_due_this_week_arrives_with_everything_a_row_draws(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ) -> None:
        """W23, W25, W26 and W27 in one row, and no follow-up request for any."""
        creating_id, _ = task_anchors
        seeded_for = datetime.datetime.now(datetime.UTC).date()
        due_id = await due_journal(
            journal_repository, days_offset=3, title="Monday standup"
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="book the venue",
        )
        contact_id = await create_contact(async_connection, first_name="Ada")
        await link_contact(async_connection, task_id=task_id, contact_id=contact_id)

        response = await authenticated_client.get(URL)
        guard_no_rollover(response, seeded_for)
        [row] = rows_of(response)

        assert row["task_id"] == task_id
        assert row["text"] == "book the venue"
        assert row["due_journal"]["id"] == due_id
        assert row["due_journal"]["title"] == "Monday standup"
        assert (
            row["due_journal"]["date"]
            == (seeded_for + datetime.timedelta(days=3)).isoformat()
        )
        # The seeded offset, not the difference between two fields of the same
        # response — that identity holds under every mutation, including one
        # that computed the number from the wrong day entirely.
        assert row["days_away"] == 3
        assert row["contacts"] == [
            {"contact_id": contact_id, "name": "Ada", "photo_url": None}
        ]

    async def test_a_task_due_today_reports_zero_days_away(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ) -> None:
        """Today is *in* the window, unlike the future-dated write invariant.

        The chip reads ``Today`` off this number, so a section that started the
        window tomorrow would drop exactly the task a dashboard exists for.
        """
        creating_id, _ = task_anchors
        seeded_for = datetime.datetime.now(datetime.UTC).date()
        due_id = await due_journal(journal_repository, days_offset=0, title="Today")
        await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await authenticated_client.get(URL)
        guard_no_rollover(response, seeded_for)
        [row] = rows_of(response)

        assert row["days_away"] == 0
        assert row["due_journal"]["date"] == anchor_of(response).isoformat()

    async def test_a_task_due_on_the_windows_last_day_is_included(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ) -> None:
        """ "Inclusive" is the word an off-by-one gets wrong at this end."""
        creating_id, _ = task_anchors
        seeded_for = datetime.datetime.now(datetime.UTC).date()
        due_id = await due_journal(journal_repository, days_offset=7, title="Next week")
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await authenticated_client.get(URL)
        guard_no_rollover(response, seeded_for)
        [row] = rows_of(response)

        assert row["task_id"] == task_id
        assert row["days_away"] == 7

    async def test_a_task_due_the_day_after_the_window_is_absent(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ) -> None:
        """The far edge from the other side, so both are pinned rather than one."""
        creating_id, _ = task_anchors
        seeded_for = datetime.datetime.now(datetime.UTC).date()
        due_id = await due_journal(journal_repository, days_offset=8, title="Later")
        await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await authenticated_client.get(URL)
        guard_no_rollover(response, seeded_for)

        assert rows_of(response) == []

    @pytest.mark.parametrize("status", [TaskStatus.DONE, TaskStatus.CANCELLED])
    async def test_a_finished_task_is_absent(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
        status: TaskStatus,
    ) -> None:
        """The section shows what is outstanding, in either terminal status.

        Absent here **and** still on its journal, asserted in the same test as
        for the two lapse causes. The criterion asks for the pair rather than
        the absence: a done task the journal had also stopped showing would
        satisfy "not on the dashboard" while losing the record that the
        commitment was ever met.
        """
        creating_id, _ = task_anchors
        due_id = await due_journal(journal_repository, days_offset=3)
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=status,
        )

        dashboard = await authenticated_client.get(URL)
        on_its_journal = await authenticated_client.get(f"/api/journals/{due_id}/tasks")

        assert rows_of(dashboard) == []
        listed = on_its_journal.json()
        assert [resource["id"] for resource in listed["data"]] == [str(task_id)]
        assert listed["data"][0]["attributes"]["status"] == status.value
        assert listed["data"][0]["attributes"]["lapsed"] is False

    async def test_a_task_due_in_a_cancelled_journal_is_absent_but_still_on_it(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ) -> None:
        """**The fixture that makes the lapsed exclusion non-vacuous.**

        Not done, dated inside the window, and absent only because the meeting
        was called off. A date-passed lapse cannot fall inside a *forward*
        window, so without this case the exclusion could be deleted and every
        other test in this file would still pass.

        The same task is asserted still present on its journal in the same test:
        the dashboard hides it, the journal keeps it, and that pair is what the
        specification promises — no overdue list on the page, and nothing lost.
        """
        creating_id, _ = task_anchors
        due_id = await due_journal(
            journal_repository, days_offset=3, title="Cancelled meeting"
        )
        await mark_journal_as_event(
            async_connection, due_id, event_state=EventState.CANCELLED
        )
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        dashboard = await authenticated_client.get(URL)
        on_its_journal = await authenticated_client.get(f"/api/journals/{due_id}/tasks")

        assert rows_of(dashboard) == []
        listed = on_its_journal.json()
        assert [resource["id"] for resource in listed["data"]] == [str(task_id)]
        assert listed["data"][0]["attributes"]["lapsed"] is True
        assert (
            listed["data"][0]["attributes"]["lapse_reason"] == "due_journal_cancelled"
        )

    async def test_a_confirmed_event_journal_hides_nothing(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ) -> None:
        """Only *cancelled* counts, so the exclusion is not "is an event".

        Without this the cancelled fixture above would pass against a rule that
        dropped every event journal's tasks, which is most of them.
        """
        creating_id, _ = task_anchors
        due_id = await due_journal(journal_repository, days_offset=3, title="Meeting")
        await mark_journal_as_event(
            async_connection, due_id, event_state=EventState.CONFIRMED
        )
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        assert [
            row["task_id"] for row in rows_of(await authenticated_client.get(URL))
        ] == [task_id]

    async def test_a_task_whose_due_journal_has_passed_is_absent(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ) -> None:
        """No overdue section, counter or badge anywhere on this page."""
        creating_id, _ = task_anchors
        past_id = await due_journal(
            journal_repository, days_offset=-7, title="Last week"
        )
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=past_id
        )

        dashboard = await authenticated_client.get(URL)
        read_back = await authenticated_client.get(f"/api/tasks/{task_id}")
        on_its_journal = await authenticated_client.get(
            f"/api/journals/{past_id}/tasks"
        )

        assert rows_of(dashboard) == []
        assert read_back.json()["data"]["attributes"]["lapse_reason"] == "date_passed"
        # Still where the user is meant to find and resurrect it.
        listed = on_its_journal.json()
        assert [resource["id"] for resource in listed["data"]] == [str(task_id)]

    async def test_another_users_task_never_reaches_the_section(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ) -> None:
        """The listing crosses journals, so owner scoping is all that separates
        one user's week from another's."""
        creating_id, _ = task_anchors
        theirs = await create_journal(
            journal_repository,
            title="Their meeting",
            days_offset=3,
            user_id=OTHER_USER_ID,
        )
        await create_task(
            async_connection,
            creating_journal_id=theirs,
            due_journal_id=theirs,
            user_id=OTHER_USER_ID,
        )
        mine = await due_journal(journal_repository, days_offset=3, title="My meeting")
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=mine
        )

        rows = rows_of(await authenticated_client.get(URL))

        assert [row["task_id"] for row in rows] == [task_id]


class TestTheOrder:
    async def test_the_soonest_deadline_leads(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ) -> None:
        """W22's rule, through the endpoint: soonest first, not insertion order.

        Seeded back to front, so a section handing the rows over in the order
        the statement happened to produce them fails here.
        """
        creating_id, _ = task_anchors
        ids = []
        for offset in (5, 1, 3):
            due_id = await due_journal(
                journal_repository, days_offset=offset, title=f"In {offset} days"
            )
            ids.append(
                (
                    offset,
                    await create_task(
                        async_connection,
                        creating_journal_id=creating_id,
                        due_journal_id=due_id,
                    ),
                )
            )

        rows = rows_of(await authenticated_client.get(URL))

        expected = [task_id for _offset, task_id in sorted(ids)]
        assert [row["task_id"] for row in rows] == expected
        assert [row["days_away"] for row in rows] == [1, 3, 5]


class TestTheSectionsOwnAnswers:
    async def test_nothing_due_this_week_is_ready_and_empty(
        self, authenticated_client: AsyncClient
    ) -> None:
        """W29's idiom — one quiet line — not the section being unavailable."""
        section = section_of(await authenticated_client.get(URL))

        assert section["status"] == "ready"
        assert section["data"]["tasks"] == []
        assert section["data"]["total"] == 0

    async def test_the_total_names_the_whole_window_uncapped(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ) -> None:
        """Eight is more than the card's five, and all eight travel.

        The show-more reveals the remainder from this payload rather than by
        asking again, so a server-side cap would turn one round trip into two.
        """
        creating_id, _ = task_anchors
        for offset in range(8):
            due_id = await due_journal(
                journal_repository, days_offset=offset, title=f"Day {offset}"
            )
            await create_task(
                async_connection,
                creating_journal_id=creating_id,
                due_journal_id=due_id,
            )

        section = section_of(await authenticated_client.get(URL))

        assert section["data"]["total"] == 8
        assert len(section["data"]["tasks"]) == 8

    async def test_the_window_travels_and_starts_on_the_pages_anchor(
        self, authenticated_client: AsyncClient
    ) -> None:
        response = await authenticated_client.get(URL)
        window = section_of(response)["data"]["window"]

        anchor = response.json()["meta"]["anchor"]["date"]
        assert window["start_date"] == anchor
        assert window["days_ahead"] == 7
        assert (
            window["end_date"]
            == (
                datetime.date.fromisoformat(anchor) + datetime.timedelta(days=7)
            ).isoformat()
        )

    async def test_it_covers_the_same_week_as_the_dates_beside_it(
        self, authenticated_client: AsyncClient
    ) -> None:
        """The specification asks the two evidence columns to match, and one
        window object is what makes that structural rather than coincidental."""
        attributes = (await authenticated_client.get(URL)).json()["data"]["attributes"]

        assert (
            attributes["tasks"]["data"]["window"]
            == attributes["upcoming_dates"]["data"]["window"]
        )

    async def test_it_windows_on_the_page_anchor_in_a_far_eastern_zone(
        self,
        authenticated_client: AsyncClient,
        user_settings_repository: SqlUserSettingsRepository,
    ) -> None:
        """Kiritimati is a day ahead of UTC for part of every day.

        Whichever day it is there, the section must be about the same one the
        page is: a section resolving its own zone could disagree with the header
        above it, and this is what makes the zone being handed down observable.
        """
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone=FAR_EAST)
        )

        response = await authenticated_client.get(URL)

        meta = response.json()["meta"]["anchor"]
        assert meta["timezone"] == FAR_EAST
        assert section_of(response)["data"]["window"]["start_date"] == meta["date"]

    async def test_the_utc_control_windows_on_utcs_day(
        self, authenticated_client: AsyncClient
    ) -> None:
        """The control for the case above: with no stored zone the anchor is
        UTC's day, so the Kiritimati assertion is about the zone rather than
        about the window echoing whatever it was given."""
        response = await authenticated_client.get(URL)

        meta = response.json()["meta"]["anchor"]
        assert meta["timezone"] == "UTC"
        assert meta["date"] == datetime.datetime.now(datetime.UTC).date().isoformat()
        assert section_of(response)["data"]["window"]["start_date"] == meta["date"]


class TestTheRoundTrips:
    async def test_the_whole_page_reads_user_settings_exactly_once(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ) -> None:
        """Four sections, one zone, one row read.

        The tasks section is handed the zone the page already resolved rather
        than resolving its own — and this is the only level the difference is
        visible at, because a unit test's read service is a double and makes no
        settings call of its own. Two reads of ``user_settings`` in one request
        are two statements under READ COMMITTED: a zone changed between them
        leaves this section windowed in the new zone beneath a header dated in
        the old one.
        """
        creating_id, _ = task_anchors
        due_id = await due_journal(journal_repository, days_offset=3)
        await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        with recorded_statements(async_connection) as statements:
            response = await authenticated_client.get(URL)

        assert len(rows_of(response)) == 1
        settings_reads = [
            statement
            for statement in statements
            if "user_settings" in statement
            and statement.lstrip().upper().startswith("SELECT")
        ]
        assert len(settings_reads) == 1, settings_reads

    async def test_the_section_costs_the_same_however_many_tasks_are_due(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ) -> None:
        """An N+1 here is a per-task round trip on every page load.

        Every task carries a contact, because the contact lookup is the read
        most likely to fan out. The count is of the whole request, so it is
        asserted as a difference: six tasks must cost exactly what one costs.
        """
        creating_id, _ = task_anchors

        async def seed(index: int) -> None:
            due_id = await due_journal(
                journal_repository, days_offset=index % 7, title=f"Day {index}"
            )
            task_id = await create_task(
                async_connection,
                creating_journal_id=creating_id,
                due_journal_id=due_id,
                text=f"task {index}",
            )
            contact_id = await create_contact(
                async_connection, first_name=f"Contact{index}"
            )
            await link_contact(async_connection, task_id=task_id, contact_id=contact_id)

        await seed(1)
        with recorded_statements(async_connection) as one_task:
            await authenticated_client.get(URL)

        for index in range(2, 7):
            await seed(index)
        with recorded_statements(async_connection) as six_tasks:
            response = await authenticated_client.get(URL)

        assert len(rows_of(response)) == 6
        assert len(six_tasks) == len(one_task)
