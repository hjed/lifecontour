"""Integration tests for the ``create_task`` MCP tool against real PostgreSQL.

The whole rejection matrix is asserted here as well as against the endpoint,
deliberately. A shared service is not evidence that both callers reach it: a
tool can validate too little, swallow an error into a generic "internal error"
that an AI client cannot act on, or open a transaction the service already owns.
What this file proves is that an AI client gets the *same answers* as an HTTP
one, in a form it can do something about.

The timezone pair is dated rather than clocked, for the reason the endpoint
tests give: ``now`` is deliberately unreachable from a tool call, so the
assertion is on the journal's rendered date — a pure function of its start and
the user's timezone — with two zones 25 hours apart, whose local dates therefore
differ at every instant.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.settings.models import UserSettings
from tests.integration.mcp.http_helpers import (
    extract_mcp_json_payload,
    initialize_mcp_session,
    mcp_headers,
)
from tests.integration.tasks.task_seeding import (
    OTHER_USER_ID,
    USER_ID,
    count,
    create_contact,
    create_journal,
)

_COUNT_TASKS = "SELECT COUNT(*) FROM tasks WHERE user_id = :user_id"
_COUNT_CONTACT_LINKS = "SELECT COUNT(*) FROM task_contacts"

# See the endpoint tests: 02:00 on the 2nd in Kiritimati, 01:00 on the 1st in
# Midway, and long past in both.
FIXED_PAST_INSTANT = datetime(2020, 1, 1, 12, 0, tzinfo=UTC)


async def _raw_tool_call(client: Any, session_id: str, arguments: dict[str, Any]):
    return await client.post(
        "/mcp-server/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "create_task", "arguments": arguments},
        },
        headers=mcp_headers(session_id),
    )


async def _create_task(
    client: Any, session_id: str, **arguments: Any
) -> dict[str, Any]:
    response = await _raw_tool_call(client, session_id, arguments)
    assert response.status_code == 200
    return extract_mcp_json_payload(response.text)


@pytest_asyncio.fixture
async def journal_repository(
    async_connection: AsyncConnection,
) -> SqlJournalRepository:
    return SqlJournalRepository(async_connection)


@pytest_asyncio.fixture
async def user_settings_repository(
    async_connection: AsyncConnection,
) -> SqlUserSettingsRepository:
    return SqlUserSettingsRepository(async_connection)


@pytest_asyncio.fixture
async def anchors(journal_repository: SqlJournalRepository) -> tuple[int, int]:
    """A creating journal and a future-dated due journal, as ``(creating, due)``."""
    creating_id = await create_journal(journal_repository, title="Where it arose")
    due_id = await create_journal(
        journal_repository, title="Where it matters", days_offset=7
    )
    return creating_id, due_id


@pytest.mark.integration
class TestCreateTaskTool:
    """The happy paths through the tool."""

    async def test_creates_a_task_anchored_to_both_journals(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        anchors: tuple[int, int],
    ):
        creating_id, due_id = anchors

        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            payload = await _create_task(
                client,
                session_id,
                creating_journal_id=creating_id,
                due_journal_id=due_id,
                text="print the permit",
            )

        assert "error" not in payload
        assert payload["text"] == "print the permit"
        assert payload["creating_journal_id"] == creating_id
        assert payload["due_journal_id"] == due_id
        assert payload["status"] == "not_done"
        assert int(payload["id"]) > 0
        assert await count(clean_database, _COUNT_TASKS, {"user_id": USER_ID}) == 1

    async def test_accepts_the_same_journal_as_both_anchors(
        self,
        authenticated_lifespan_client,
        journal_repository: SqlJournalRepository,
    ):
        journal_id = await create_journal(
            journal_repository, title="Next week's trip", days_offset=7
        )

        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            payload = await _create_task(
                client,
                session_id,
                creating_journal_id=journal_id,
                due_journal_id=journal_id,
                text="pack the ropes",
            )

        assert "error" not in payload
        assert payload["creating_journal_id"] == journal_id
        assert payload["due_journal_id"] == journal_id

    async def test_links_the_requested_contacts(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        anchors: tuple[int, int],
    ):
        creating_id, due_id = anchors
        first = await create_contact(clean_database, first_name="Sarah")
        second = await create_contact(clean_database, first_name="Tom")

        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            payload = await _create_task(
                client,
                session_id,
                creating_journal_id=creating_id,
                due_journal_id=due_id,
                text="split the gear",
                contact_ids=[first, second],
            )

        assert "error" not in payload
        assert await count(clean_database, _COUNT_CONTACT_LINKS, {}) == 2


@pytest.mark.integration
class TestUnreachableAnchors:
    """The same 404-shaped rejection the endpoint gives, in a form a model can use."""

    async def test_an_absent_due_journal_names_the_due_anchor(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        anchors: tuple[int, int],
    ):
        creating_id, _ = anchors

        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            payload = await _create_task(
                client,
                session_id,
                creating_journal_id=creating_id,
                due_journal_id=999_999,
                text="print the permit",
            )

        assert payload["error"] == "Not found"
        assert "due journal (ID 999999)" in payload["message"]
        assert "exist and belong to you" in payload["message"]
        assert await count(clean_database, _COUNT_TASKS, {"user_id": USER_ID}) == 0

    async def test_another_users_due_journal_reads_as_an_absent_one(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        anchors: tuple[int, int],
    ):
        """Indistinguishability holds for an AI client too."""
        creating_id, _ = anchors
        foreign_id = await create_journal(
            journal_repository,
            title="Somebody else's trip",
            days_offset=7,
            user_id=OTHER_USER_ID,
        )

        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            foreign = await _create_task(
                client,
                session_id,
                creating_journal_id=creating_id,
                due_journal_id=foreign_id,
                text="print the permit",
            )
            absent = await _create_task(
                client,
                session_id,
                creating_journal_id=creating_id,
                due_journal_id=999_999,
                text="print the permit",
            )

        assert foreign["error"] == absent["error"]
        assert foreign["message"].replace(str(foreign_id), "X") == absent[
            "message"
        ].replace("999999", "X")
        assert await count(clean_database, _COUNT_TASKS, {"user_id": USER_ID}) == 0

    async def test_another_users_creating_journal_is_rejected(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        anchors: tuple[int, int],
    ):
        _, due_id = anchors
        foreign_id = await create_journal(
            journal_repository, title="Somebody else's day", user_id=OTHER_USER_ID
        )

        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            payload = await _create_task(
                client,
                session_id,
                creating_journal_id=foreign_id,
                due_journal_id=due_id,
                text="print the permit",
            )

        assert payload["error"] == "Not found"
        assert f"creating journal (ID {foreign_id})" in payload["message"]
        assert await count(clean_database, _COUNT_TASKS, {"user_id": USER_ID}) == 0


@pytest.mark.integration
class TestTheFutureDatedRuleReachesTheTool:
    """Invariant 4, and whose timezone decides it."""

    async def test_a_past_due_journal_is_rejected_with_both_dates(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        anchors: tuple[int, int],
    ):
        creating_id, _ = anchors
        past_id = await create_journal(
            journal_repository, title="Last week", days_offset=-7
        )

        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            payload = await _create_task(
                client,
                session_id,
                creating_journal_id=creating_id,
                due_journal_id=past_id,
                text="too late",
            )

        assert payload["error"] == "Task error"
        assert "not after today" in payload["message"]
        assert "must be a journal dated in the future" in payload["message"]
        assert await count(clean_database, _COUNT_TASKS, {"user_id": USER_ID}) == 0

    @pytest.mark.parametrize(
        ("timezone", "expected_date"),
        [
            ("Pacific/Kiritimati", "2020-01-02"),
            ("Pacific/Midway", "2020-01-01"),
        ],
    )
    async def test_the_journals_date_is_rendered_in_the_users_timezone(
        self,
        authenticated_lifespan_client,
        journal_repository: SqlJournalRepository,
        user_settings_repository: SqlUserSettingsRepository,
        anchors: tuple[int, int],
        timezone: str,
        expected_date: str,
    ):
        creating_id, _ = anchors
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone=timezone)
        )
        past_id = await create_journal(
            journal_repository, title="New Year 2020", start=FIXED_PAST_INSTANT
        )

        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            payload = await _create_task(
                client,
                session_id,
                creating_journal_id=creating_id,
                due_journal_id=past_id,
                text="too late",
            )

        assert f"is dated {expected_date}" in payload["message"]


@pytest.mark.integration
class TestRejectedArguments:
    """What the tool will not accept."""

    async def test_an_unknown_contact_is_rejected_and_nothing_is_written(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        anchors: tuple[int, int],
    ):
        creating_id, due_id = anchors

        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            payload = await _create_task(
                client,
                session_id,
                creating_journal_id=creating_id,
                due_journal_id=due_id,
                text="split the gear",
                contact_ids=[999_999],
            )

        assert payload["error"] == "Contact not found"
        assert await count(clean_database, _COUNT_TASKS, {"user_id": USER_ID}) == 0
        assert await count(clean_database, _COUNT_CONTACT_LINKS, {}) == 0

    async def test_empty_text_is_rejected(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        anchors: tuple[int, int],
    ):
        creating_id, due_id = anchors

        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            payload = await _create_task(
                client,
                session_id,
                creating_journal_id=creating_id,
                due_journal_id=due_id,
                text="   ",
            )

        assert "text" in payload["message"]
        assert await count(clean_database, _COUNT_TASKS, {"user_id": USER_ID}) == 0

    async def test_a_call_carrying_now_is_rejected_by_the_tool_schema(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        anchors: tuple[int, int],
    ):
        """Invariant 4 is not opt-out for an AI client either.

        The tool declares no ``now``, so the transport rejects the argument
        before the service is ever reached — no task is created against a
        pretend clock.
        """
        creating_id, due_id = anchors

        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            response = await _raw_tool_call(
                client,
                session_id,
                {
                    "creating_journal_id": creating_id,
                    "due_journal_id": due_id,
                    "text": "cheat the clock",
                    "now": "2020-01-01T00:00:00+00:00",
                },
            )

        # Asserted on the rejection *reason*, not merely on "now" appearing in
        # the body: a body echo would contain the argument either way, so only
        # the unexpected-keyword error tells a rejection from an acceptance.
        assert '"isError":true' in response.text
        assert "unexpected_keyword_argument" in response.text
        assert await count(clean_database, _COUNT_TASKS, {"user_id": USER_ID}) == 0
