"""Integration tests for the journal list's ``tasks_due_count`` attribute.

The service is pinned in ``tests/integration/tasks/``; what only exists out here
is whether ``GET /api/journals`` actually **carries** the signal, and what the
page costs once a listing's own enrichment is running around it.

**The statement assertion is scoped to the ``tasks`` table on purpose.** The
endpoint has per-row reads that predate this phase — type data, calendar info,
contact names — so a total statement count would grow with the page whatever
this phase did, and asserting on it would be measuring somebody else's work. The
criterion is that *this* signal costs one query for the whole page, so that is
what is counted: statements against ``tasks``, at two page sizes, expected to be
one at both.

Rows are seeded directly rather than created through the API, for the reason
``task_seeding`` documents: half the cases here need a journal a task can no
longer be created against — one already in the past, or a cancelled event — and
the write path exists precisely to refuse those.
"""

from typing import Any

import pytest
import pytest_asyncio
from core_shared.models.journals.event_state import EventState
from core_shared.models.tasks import TaskStatus
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from tests.integration.contact_seeding import seed_contact
from tests.integration.statement_recorder import recorded_statements
from tests.integration.tasks.task_seeding import (
    USER_ID,
    create_journal,
    create_task,
    mark_journal_as_event,
)

# Wide enough that every seeded journal is on one page, so a missing row is a
# missing attribute rather than an artefact of pagination.
_WHOLE_PAGE = "/api/journals?limit=100"


async def seed_due_journal(
    async_connection: AsyncConnection,
    journal_repository: SqlJournalRepository,
    *,
    title: str,
    days_offset: int = 7,
    tasks: int = 1,
    status: TaskStatus = TaskStatus.NOT_DONE,
    event_state: EventState | None = None,
) -> int:
    """A journal with ``tasks`` tasks due in it, and its own creating journal."""
    creating_id = await create_journal(
        journal_repository, title=f"{title} — where it arose", days_offset=-14
    )
    due_id = await create_journal(
        journal_repository, title=title, days_offset=days_offset
    )
    if event_state is not None:
        await mark_journal_as_event(async_connection, due_id, event_state=event_state)
    for index in range(tasks):
        await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text=f"{title} commitment {index}",
            status=status,
            user_id=USER_ID,
        )
    return due_id


def counts_by_journal_id(payload: dict[str, Any]) -> dict[int, int | None]:
    """Every listed journal's ``tasks_due_count``, keyed by id.

    Read for the whole page rather than for one row, so a test can assert what a
    journal reports *and* that its neighbours were unaffected.
    """
    return {
        int(resource["id"]): resource["attributes"]["tasks_due_count"]
        for resource in payload["data"]
    }


def tasks_statements(statements: list[str]) -> list[str]:
    """The recorded statements that read the ``tasks`` table.

    ``FROM tasks`` matches only that table: the two link tables are
    ``task_intermediate_journals`` and ``task_contacts``, neither of which is
    ``tasks``.
    """
    return [
        statement
        for statement in statements
        if "FROM tasks" in " ".join(statement.split())
    ]


@pytest.mark.integration
class TestTheIndicatorOnTheWire:
    """What ``GET /api/journals`` says about each journal's live commitments."""

    @pytest_asyncio.fixture(autouse=True)
    async def _clean(self, clean_database):  # noqa: ARG002
        """Each test owns the whole listing, so it owns the whole database."""

    async def test_a_journal_reports_the_commitments_due_in_it(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """Two tasks due read as two, and the journal beside it is unaffected.

        A count rather than a flag is what makes the second half assertable: the
        quiet journal has to report *zero*, not merely fail to report a badge.
        """
        busy_id = await seed_due_journal(
            async_connection, journal_repository, title="Permit Meeting", tasks=2
        )
        quiet_id = await create_journal(
            journal_repository, title="Nothing due here", days_offset=8
        )

        response = await authenticated_client.get(_WHOLE_PAGE)

        assert response.status_code == 200
        counts = counts_by_journal_id(response.json())
        assert counts[busy_id] == 2
        assert counts[quiet_id] == 0

    async def test_a_journal_the_task_was_created_in_reports_zero(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """The indicator says *due here*, which is one link role of three.

        ``seed_due_journal`` leaves a creating journal on the page for every
        due one, so this is asserted over the same rows every other test here
        already has.
        """
        creating_id = await create_journal(
            journal_repository, title="Monday Planning", days_offset=-14
        )
        due_id = await create_journal(
            journal_repository, title="Permit Meeting", days_offset=7
        )
        await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="print the permit",
        )

        response = await authenticated_client.get(_WHOLE_PAGE)

        counts = counts_by_journal_id(response.json())
        assert counts[creating_id] == 0
        assert counts[due_id] == 1

    async def test_terminal_tasks_do_not_light_the_indicator(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """A journal whose commitments are all settled reports zero."""
        done_id = await seed_due_journal(
            async_connection,
            journal_repository,
            title="All finished",
            status=TaskStatus.DONE,
        )
        cancelled_id = await seed_due_journal(
            async_connection,
            journal_repository,
            title="All called off",
            status=TaskStatus.CANCELLED,
        )

        response = await authenticated_client.get(_WHOLE_PAGE)

        counts = counts_by_journal_id(response.json())
        assert counts[done_id] == 0
        assert counts[cancelled_id] == 0

    async def test_a_past_dated_journal_holding_a_live_task_reports_zero(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """Its tasks have lapsed, and a lapsed task must produce no badge.

        The specification is explicit that lapsing means no overdue section, no
        counter and no badge — the user meets the task on the journal itself,
        not through the listing calling it out.
        """
        lapsed_id = await seed_due_journal(
            async_connection, journal_repository, title="Last week", days_offset=-3
        )
        live_id = await seed_due_journal(
            async_connection, journal_repository, title="Next week", days_offset=7
        )

        response = await authenticated_client.get(_WHOLE_PAGE)

        counts = counts_by_journal_id(response.json())
        assert counts[lapsed_id] == 0
        assert counts[live_id] == 1

    async def test_a_cancelled_event_journal_reports_zero(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """A cancelled meeting a week away lights nothing; a confirmed one does.

        The confirmed event is what makes this non-vacuous: both journals are
        real events, so a lookup treating any event as cancelled would fail
        here and pass without it.
        """
        cancelled_id = await seed_due_journal(
            async_connection,
            journal_repository,
            title="Called off",
            event_state=EventState.CANCELLED,
        )
        confirmed_id = await seed_due_journal(
            async_connection,
            journal_repository,
            title="Still going ahead",
            event_state=EventState.CONFIRMED,
        )

        response = await authenticated_client.get(_WHOLE_PAGE)

        counts = counts_by_journal_id(response.json())
        assert counts[cancelled_id] == 0
        assert counts[confirmed_id] == 1


@pytest.mark.integration
class TestOneQueryForTheWholePage:
    """The criterion this phase exists to satisfy, asserted at the endpoint."""

    @pytest_asyncio.fixture(autouse=True)
    async def _clean(self, clean_database):  # noqa: ARG002
        """Each test owns the whole listing, so it owns the whole database."""

    async def test_the_signal_costs_one_tasks_query_however_long_the_page(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """One statement against ``tasks`` for a two-journal page, and for eight.

        The *doubling* is what makes this an N+1 assertion rather than a magic
        number: a per-row query would answer 2 and then 8, and any fixed
        expectation would have caught only one of the two.
        """
        for index in range(2):
            await seed_due_journal(
                async_connection,
                journal_repository,
                title=f"Small page {index}",
                days_offset=index + 1,
            )

        with recorded_statements(async_connection) as small:
            small_response = await authenticated_client.get(_WHOLE_PAGE)

        for index in range(6):
            await seed_due_journal(
                async_connection,
                journal_repository,
                title=f"Large page {index}",
                days_offset=index + 10,
            )

        with recorded_statements(async_connection) as large:
            large_response = await authenticated_client.get(_WHOLE_PAGE)

        # Four journals on the first page and sixteen on the second: each
        # ``seed_due_journal`` leaves its creating journal on the listing too.
        assert len(small_response.json()["data"]) == 4
        assert len(large_response.json()["data"]) == 16
        assert len(tasks_statements(small)) == 1
        assert len(tasks_statements(large)) == 1

    async def test_a_page_with_nothing_due_still_costs_only_the_one(
        self,
        authenticated_client: AsyncClient,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """The common listing: no journal holds a task, and none is asked about twice.

        The count comes back empty and the follow-up reads are skipped, so the
        ordinary page pays exactly one statement for the whole indicator.
        """
        for index in range(8):
            await create_journal(
                journal_repository, title=f"Quiet {index}", days_offset=index + 1
            )

        with recorded_statements(async_connection) as statements:
            response = await authenticated_client.get(_WHOLE_PAGE)

        assert set(counts_by_journal_id(response.json()).values()) == {0}
        assert len(tasks_statements(statements)) == 1


@pytest.mark.integration
class TestNotComputedIsNotZero:
    """The endpoints that do not run the count must not answer as if they had.

    Only ``list_journals`` reaches ``_build_journal_list_resources``, so every
    other journal payload — search, the detail view, a contact's journals —
    leaves ``tasks_due_count`` alone. The field is therefore **nullable**, and
    that is the whole point: a default of ``0`` would have those payloads state
    that a journal has nothing due in it without anything ever having looked,
    which is a false claim rather than a missing one. Both render as silence on
    a surface, so the distinction exists for the reader of the payload.
    """

    @pytest_asyncio.fixture(autouse=True)
    async def _clean(self, clean_database):  # noqa: ARG002
        """Each test owns the whole listing, so it owns the whole database."""

    async def test_the_list_answers_zero_for_a_journal_with_nothing_due(
        self,
        authenticated_client: AsyncClient,
        journal_repository: SqlJournalRepository,
    ):
        """On the list the count really was computed, so zero is a fact."""
        quiet_id = await create_journal(
            journal_repository, title="Nothing due here", days_offset=8
        )

        response = await authenticated_client.get(_WHOLE_PAGE)

        assert counts_by_journal_id(response.json())[quiet_id] == 0

    async def test_a_contacts_journals_answer_null_rather_than_zero(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """The second caller of the shared helper, and the reason the guard is real.

        ``app/api/contacts/controllers.py`` imports
        ``_build_journal_list_resources`` and calls it **without** the counts, so
        this is not a hypothetical caller the nullable default merely guards
        against — it is a shipped screen. Before the helper stopped collapsing
        "no mapping passed" into "an empty mapping", every row here carried a
        `0`, including for a journal with a live commitment in it.
        """
        due_id = await seed_due_journal(
            async_connection, journal_repository, title="Permit Meeting", tasks=2
        )
        contact_id = await seed_contact(async_connection, first_name="Sarah")
        await async_connection.execute(
            text(
                "INSERT INTO journal_contact_relationships "
                "(journal_id, contact_id, relationship_type) "
                "VALUES (:journal_id, :contact_id, 'PARTICIPANT')"
            ),
            {"journal_id": due_id, "contact_id": contact_id},
        )

        response = await authenticated_client.get(
            f"/api/contacts/{contact_id}/journals"
        )

        assert response.status_code == 200
        rows = {
            int(r["id"]): r["attributes"]["tasks_due_count"]
            for r in response.json()["data"]
        }
        assert rows[due_id] is None

    async def test_the_detail_view_answers_null_rather_than_zero(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """A journal with two tasks genuinely due reads null, not zero.

        The sharpest form of the rule: this journal is **not** clear, so a
        payload answering ``0`` would be affirmatively wrong rather than merely
        uninformative. Null says nobody asked.
        """
        due_id = await seed_due_journal(
            async_connection, journal_repository, title="Permit Meeting", tasks=2
        )

        response = await authenticated_client.get(f"/api/journals/{due_id}")

        assert response.status_code == 200
        assert response.json()["data"]["attributes"]["tasks_due_count"] is None
