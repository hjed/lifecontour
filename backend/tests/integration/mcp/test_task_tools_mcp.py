"""Integration tests for the task MCP tools against real PostgreSQL.

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

from typing import Any

import pytest
from core_shared.models.tasks import TaskStatus
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
    COUNT_CONTACT_LINKS,
    COUNT_INTERMEDIATE_JOURNALS,
    COUNT_TASKS,
    FIXED_PAST_INSTANT,
    OTHER_USER_ID,
    USER_ID,
    count,
    create_contact,
    create_journal,
    create_task,
    stored_status,
)


async def _raw_call(client: Any, session_id: str, tool: str, arguments: dict[str, Any]):
    return await client.post(
        "/mcp-server/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        },
        headers=mcp_headers(session_id),
    )


async def _raw_tool_call(client: Any, session_id: str, arguments: dict[str, Any]):
    return await _raw_call(client, session_id, "create_task", arguments)


async def _create_task(
    client: Any, session_id: str, **arguments: Any
) -> dict[str, Any]:
    response = await _raw_tool_call(client, session_id, arguments)
    assert response.status_code == 200
    return extract_mcp_json_payload(response.text)


async def _set_task_status(
    client: Any, session_id: str, **arguments: Any
) -> dict[str, Any]:
    response = await _raw_call(client, session_id, "set_task_status", arguments)
    assert response.status_code == 200
    return extract_mcp_json_payload(response.text)


@pytest.mark.integration
class TestCreateTaskTool:
    """The happy paths through the tool."""

    async def test_creates_a_task_anchored_to_both_journals(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors

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
        assert await count(clean_database, COUNT_TASKS, {"user_id": USER_ID}) == 1

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
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
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
        assert await count(clean_database, COUNT_CONTACT_LINKS, {}) == 2


@pytest.mark.integration
class TestUnreachableAnchors:
    """The same 404-shaped rejection the endpoint gives, in a form a model can use."""

    async def test_an_absent_due_journal_names_the_due_anchor(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, _ = task_anchors

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
        assert await count(clean_database, COUNT_TASKS, {"user_id": USER_ID}) == 0

    async def test_another_users_due_journal_reads_as_an_absent_one(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """Indistinguishability holds for an AI client too."""
        creating_id, _ = task_anchors
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
        assert await count(clean_database, COUNT_TASKS, {"user_id": USER_ID}) == 0

    async def test_another_users_creating_journal_is_rejected(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        _, due_id = task_anchors
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
        assert await count(clean_database, COUNT_TASKS, {"user_id": USER_ID}) == 0


@pytest.mark.integration
class TestTheFutureDatedRuleReachesTheTool:
    """Invariant 4, and whose timezone decides it."""

    async def test_a_past_due_journal_is_rejected_with_both_dates(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, _ = task_anchors
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
        assert await count(clean_database, COUNT_TASKS, {"user_id": USER_ID}) == 0

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
        task_anchors: tuple[int, int],
        timezone: str,
        expected_date: str,
    ):
        creating_id, _ = task_anchors
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
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors

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
        assert await count(clean_database, COUNT_TASKS, {"user_id": USER_ID}) == 0
        assert await count(clean_database, COUNT_CONTACT_LINKS, {}) == 0

    async def test_empty_text_is_rejected(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors

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
        assert await count(clean_database, COUNT_TASKS, {"user_id": USER_ID}) == 0

    async def test_a_call_carrying_now_is_rejected_by_the_tool_schema(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """Invariant 4 is not opt-out for an AI client either.

        The tool declares no ``now``, so the transport rejects the argument
        before the service is ever reached — no task is created against a
        pretend clock.
        """
        creating_id, due_id = task_anchors

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
        assert await count(clean_database, COUNT_TASKS, {"user_id": USER_ID}) == 0


@pytest.mark.integration
class TestSetTaskStatusTool:
    """The lifecycle over MCP, asserted against the same matrix as the endpoint."""

    @pytest.mark.parametrize(
        ("current", "target"),
        [
            ("not_done", "done"),
            ("not_done", "cancelled"),
            ("done", "not_done"),
            ("done", "cancelled"),
        ],
    )
    async def test_each_permitted_transition_reaches_the_row(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
        current: str,
        target: str,
    ):
        """An agent's call changes the same row an HTTP client's would.

        The tool opens no transaction of its own — that is a property of the
        code, and the unit of work behind it is asserted against the service in
        ``tests/integration/tasks/``, because the savepoint fixture makes a
        commit unobservable from out here.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus(current),
        )

        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            payload = await _set_task_status(
                client, session_id, task_id=task_id, status=target
            )

        assert "error" not in payload
        assert payload["id"] == task_id
        assert payload["status"] == target
        assert await stored_status(clean_database, task_id) == target

    async def test_no_journal_link_is_created(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """An agent marking a task done attaches it to nothing."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )

        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            payload = await _set_task_status(
                client, session_id, task_id=task_id, status="cancelled"
            )

        assert "error" not in payload
        assert await count(clean_database, COUNT_INTERMEDIATE_JOURNALS, {}) == 0

    async def test_asking_for_the_current_status_is_accepted(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The same no-op the endpoint allows, so neither surface is the odd one.

        A cancelled task in particular: asking for the status it already has is
        not a reopening, and an agent re-sending a call must not be told it did
        something wrong.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus.CANCELLED,
        )

        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            payload = await _set_task_status(
                client, session_id, task_id=task_id, status="cancelled"
            )

        assert "error" not in payload
        assert payload["status"] == "cancelled"
        assert await stored_status(clean_database, task_id) == "cancelled"

    @pytest.mark.parametrize("target", ["not_done", "done"])
    async def test_leaving_cancelled_is_refused_with_an_actionable_message(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
        target: str,
    ):
        """A model told only "refused" will retry; this one is told to retarget."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus.CANCELLED,
        )

        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            payload = await _set_task_status(
                client, session_id, task_id=task_id, status=target
            )

        assert payload["error"] == "Task error"
        assert "retarget" in payload["message"].lower()
        assert await stored_status(clean_database, task_id) == "cancelled"

    async def test_another_users_task_is_reported_as_not_found(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """Indistinguishable from an absent one, and the row does not move."""
        foreign_journal = await create_journal(
            journal_repository,
            title="Somebody else's day",
            days_offset=7,
            user_id=OTHER_USER_ID,
        )
        foreign_task = await create_task(
            clean_database,
            creating_journal_id=foreign_journal,
            due_journal_id=foreign_journal,
            user_id=OTHER_USER_ID,
        )

        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            foreign = await _set_task_status(
                client, session_id, task_id=foreign_task, status="done"
            )
            absent = await _set_task_status(
                client, session_id, task_id=999_999, status="done"
            )

        assert foreign["error"] == absent["error"] == "Not found"
        assert foreign["message"].replace(str(foreign_task), "X") == absent[
            "message"
        ].replace("999999", "X")
        assert await stored_status(clean_database, foreign_task) == "not_done"

    async def test_an_unknown_status_is_rejected_by_the_tool_schema(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The three values are in the schema, so a fourth never reaches the service."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )

        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            response = await _raw_call(
                client,
                session_id,
                "set_task_status",
                {"task_id": task_id, "status": "in_progress"},
            )

        assert '"isError":true' in response.text
        assert await stored_status(clean_database, task_id) == "not_done"
