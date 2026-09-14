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
from core_shared.models.history import Provenance
from core_shared.models.journals.event_state import EventState
from core_shared.models.tasks import TaskStatus
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.settings.models import UserSettings
from app.core.tasks.models.events import contact_field_name
from tests.integration.core.integrations.journal_sync_seeding import (
    MASTER_ID,
    build_processor,
    create_calendar,
    sync_event,
)
from tests.integration.mcp.http_helpers import (
    extract_mcp_json_payload,
    sessionless_mcp_headers,
    sessionless_mcp_request,
)
from tests.integration.tasks.task_seeding import (
    COUNT_CONTACT_LINKS,
    COUNT_CONTACT_LINKS_FOR_TASK,
    COUNT_INTERMEDIATE_JOURNALS,
    COUNT_TASKS,
    FIXED_PAST_INSTANT,
    OTHER_USER_ID,
    USER_ID,
    backdate_updated_at,
    count,
    create_contact,
    create_journal,
    create_task,
    intermediate_journal_ids,
    link_contact,
    link_intermediate_journal,
    linked_contact_ids,
    mark_journal_as_event,
    stored_anchors,
    stored_status,
    stored_text,
    stored_updated_at,
    task_events,
    task_exists,
)


async def _raw_call(client: Any, tool: str, arguments: dict[str, Any]) -> Any:
    return await client.post(
        "/mcp-server/mcp",
        json=sessionless_mcp_request(
            "tools/call", {"name": tool, "arguments": arguments}
        ),
        headers=sessionless_mcp_headers("tools/call", tool),
    )


async def _raw_tool_call(client: Any, arguments: dict[str, Any]) -> Any:
    return await _raw_call(client, "create_task", arguments)


async def _create_task(client: Any, **arguments: Any) -> dict[str, Any]:
    response = await _raw_tool_call(client, arguments)
    assert response.status_code == 200
    return extract_mcp_json_payload(response.text)


async def _set_task_status(client: Any, **arguments: Any) -> dict[str, Any]:
    response = await _raw_call(client, "set_task_status", arguments)
    assert response.status_code == 200
    return extract_mcp_json_payload(response.text)


async def _update_task_text(client: Any, **arguments: Any) -> dict[str, Any]:
    response = await _raw_call(client, "update_task_text", arguments)
    assert response.status_code == 200
    return extract_mcp_json_payload(response.text)


async def _delete_task(client: Any, **arguments: Any) -> dict[str, Any]:
    response = await _raw_call(client, "delete_task", arguments)
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
            payload = await _create_task(
                client,
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
            payload = await _create_task(
                client,
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
            payload = await _create_task(
                client,
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
            payload = await _create_task(
                client,
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
            foreign = await _create_task(
                client,
                creating_journal_id=creating_id,
                due_journal_id=foreign_id,
                text="print the permit",
            )
            absent = await _create_task(
                client,
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
            payload = await _create_task(
                client,
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
            payload = await _create_task(
                client,
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
            payload = await _create_task(
                client,
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
            payload = await _create_task(
                client,
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
            payload = await _create_task(
                client,
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
            response = await _raw_tool_call(
                client,
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
            payload = await _set_task_status(client, task_id=task_id, status=target)

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
            payload = await _set_task_status(
                client, task_id=task_id, status="cancelled"
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
            payload = await _set_task_status(
                client, task_id=task_id, status="cancelled"
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
            payload = await _set_task_status(client, task_id=task_id, status=target)

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
            foreign = await _set_task_status(
                client, task_id=foreign_task, status="done"
            )
            absent = await _set_task_status(client, task_id=999_999, status="done")

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
            response = await _raw_call(
                client,
                "set_task_status",
                {"task_id": task_id, "status": "in_progress"},
            )

        assert '"isError":true' in response.text
        assert await stored_status(clean_database, task_id) == "not_done"


async def _link_contact(client: Any, **arguments: Any) -> dict[str, Any]:
    response = await _raw_call(client, "link_task_to_contact", arguments)
    assert response.status_code == 200
    return extract_mcp_json_payload(response.text)


async def _unlink_contact(client: Any, **arguments: Any) -> dict[str, Any]:
    response = await _raw_call(client, "unlink_task_from_contact", arguments)
    assert response.status_code == 200
    return extract_mcp_json_payload(response.text)


@pytest.mark.integration
class TestContactLinkTools:
    """The same matrix an HTTP client gets, over ``tools/call``.

    A shared service is no evidence that both callers reach it — Phase 5 found a
    real defect on exactly this seam, where every task rejection reached an AI
    client as "internal error". So the tools are asserted in their own right
    rather than by reference to the endpoint tests.

    The tools answer with ``linked`` (the resulting state) and ``changed``
    (whether a row moved), so an agent can tell a fresh link from a no-op
    without a read tool existing yet.
    """

    async def test_linking_writes_the_row(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        sarah = await create_contact(clean_database, first_name="Sarah")

        async with authenticated_lifespan_client() as client:
            payload = await _link_contact(client, task_id=task_id, contact_id=sarah)

        assert "error" not in payload
        assert payload["linked"] is True
        assert payload["changed"] is True
        assert await linked_contact_ids(clean_database, task_id) == [sarah]

    async def test_linking_again_reports_no_change_and_leaves_one_row(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        sarah = await create_contact(clean_database, first_name="Sarah")

        async with authenticated_lifespan_client() as client:
            first = await _link_contact(client, task_id=task_id, contact_id=sarah)
            second = await _link_contact(client, task_id=task_id, contact_id=sarah)

        assert (first["changed"], second["changed"]) == (True, False)
        assert second["linked"] is True
        assert (
            await count(
                clean_database, COUNT_CONTACT_LINKS_FOR_TASK, {"task_id": task_id}
            )
            == 1
        )

    async def test_unlinking_removes_the_row(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        sarah = await create_contact(clean_database, first_name="Sarah")
        await link_contact(clean_database, task_id=task_id, contact_id=sarah)

        async with authenticated_lifespan_client() as client:
            payload = await _unlink_contact(client, task_id=task_id, contact_id=sarah)

        assert "error" not in payload
        assert payload["linked"] is False
        assert payload["changed"] is True
        assert await linked_contact_ids(clean_database, task_id) == []

    async def test_unlinking_again_reports_no_change(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        sarah = await create_contact(clean_database, first_name="Sarah")
        await link_contact(clean_database, task_id=task_id, contact_id=sarah)

        async with authenticated_lifespan_client() as client:
            first = await _unlink_contact(client, task_id=task_id, contact_id=sarah)
            second = await _unlink_contact(client, task_id=task_id, contact_id=sarah)

        assert (first["changed"], second["changed"]) == (True, False)
        assert second["linked"] is False

    @pytest.mark.parametrize("status", list(TaskStatus))
    async def test_links_are_editable_in_every_status(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
        status: TaskStatus,
    ):
        """Cancelled included — the one status ``set_task_status`` will not leave."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=status,
        )
        sarah = await create_contact(clean_database, first_name="Sarah")

        async with authenticated_lifespan_client() as client:
            linked = await _link_contact(client, task_id=task_id, contact_id=sarah)
            unlinked = await _unlink_contact(client, task_id=task_id, contact_id=sarah)

        assert linked["linked"] is True
        assert unlinked["linked"] is False
        assert await stored_status(clean_database, task_id) == status.value

    async def test_no_journal_link_is_created(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """A contact link is not a journal link, whatever the tool is called."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        sarah = await create_contact(clean_database, first_name="Sarah")

        async with authenticated_lifespan_client() as client:
            await _link_contact(client, task_id=task_id, contact_id=sarah)

        assert await count(clean_database, COUNT_INTERMEDIATE_JOURNALS, {}) == 0


@pytest.mark.integration
class TestContactLinkToolRejections:
    """Every refusal reaches an agent as something it can act on."""

    async def test_an_unknown_contact_is_reported_as_not_found(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """Not as an internal error, which an agent can do nothing with.

        The contacts domain's own branch of the shared handler answers this, so
        it comes back as *"Contact not found"* rather than the task domain's
        bare *"Not found"* — which is the more useful answer: the task is fine,
        the contact is the problem, and the message says which id.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )

        async with authenticated_lifespan_client() as client:
            payload = await _link_contact(client, task_id=task_id, contact_id=999_999)

        assert payload["error"] == "Contact not found"
        assert "999999" in payload["message"]
        assert await linked_contact_ids(clean_database, task_id) == []

    async def test_another_users_task_is_indistinguishable_from_an_absent_one(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
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
        sarah = await create_contact(clean_database, first_name="Sarah")

        async with authenticated_lifespan_client() as client:
            foreign = await _link_contact(
                client, task_id=foreign_task, contact_id=sarah
            )
            absent = await _link_contact(client, task_id=999_999, contact_id=sarah)

        assert foreign["error"] == absent["error"] == "Not found"
        assert foreign["message"].replace(str(foreign_task), "X") == absent[
            "message"
        ].replace("999999", "X")
        assert await linked_contact_ids(clean_database, foreign_task) == []

    async def test_unlinking_another_users_task_leaves_its_link_in_place(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
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
        sarah = await create_contact(clean_database, first_name="Sarah")
        await link_contact(clean_database, task_id=foreign_task, contact_id=sarah)

        async with authenticated_lifespan_client() as client:
            payload = await _unlink_contact(
                client, task_id=foreign_task, contact_id=sarah
            )

        assert payload["error"] == "Not found"
        assert await linked_contact_ids(clean_database, foreign_task) == [sarah]

    @pytest.mark.parametrize("unwanted", ["relationship_type", "role", "status"])
    async def test_a_call_carrying_relationship_data_is_refused_by_the_transport(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
        unwanted: str,
    ):
        """The schema offers no such parameter, so the call never reaches the service.

        Asserted on the *rejection*, not on the argument's absence from a
        response body — a request echo would satisfy that either way.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        sarah = await create_contact(clean_database, first_name="Sarah")

        async with authenticated_lifespan_client() as client:
            response = await _raw_call(
                client,
                "link_task_to_contact",
                {
                    "task_id": task_id,
                    "contact_id": sarah,
                    unwanted: "PARTICIPANT",
                },
            )

        assert '"isError":true' in response.text
        assert await linked_contact_ids(clean_database, task_id) == []


@pytest.mark.integration
class TestIdsOutsideTheColumnsRange:
    """The transport refuses an id no row could have, before the service runs.

    The same defect the endpoint tests describe: an out-of-range id used to
    reach the driver and come back as an internal error, which is the least
    actionable answer an agent can get. The bound is in the generated schema, so
    the call is refused rather than attempted.
    """

    async def test_a_task_id_beyond_int32_is_refused(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ):
        sarah = await create_contact(clean_database, first_name="Sarah")

        async with authenticated_lifespan_client() as client:
            response = await _raw_call(
                client,
                "link_task_to_contact",
                {"task_id": 2_147_483_648, "contact_id": sarah},
            )

        assert '"isError":true' in response.text

    async def test_a_contact_id_beyond_int32_is_refused(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )

        async with authenticated_lifespan_client() as client:
            response = await _raw_call(
                client,
                "unlink_task_from_contact",
                {"task_id": task_id, "contact_id": 2_147_483_648},
            )

        assert '"isError":true' in response.text
        assert await linked_contact_ids(clean_database, task_id) == []


@pytest.mark.integration
class TestUpdateTaskTextTool:
    """Rewording over MCP, asserted against the same rules as the endpoint."""

    @pytest.mark.parametrize("status", ["not_done", "done", "cancelled"])
    async def test_the_text_is_editable_in_every_status(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
        status: str,
    ):
        """An agent's call changes the same row an HTTP client's would."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus(status),
        )

        async with authenticated_lifespan_client() as client:
            payload = await _update_task_text(client, task_id=task_id, text="reworded")

        assert "error" not in payload
        assert payload["id"] == task_id
        assert payload["text"] == "reworded"
        assert payload["status"] == status
        assert await stored_text(clean_database, task_id) == "reworded"
        assert await stored_status(clean_database, task_id) == status

    async def test_a_lapsed_task_can_still_be_reworded(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """The due journal is not re-read, so its date cannot block a typo fix."""
        past_id = await create_journal(
            journal_repository, title="Last week", days_offset=-7
        )
        task_id = await create_task(
            clean_database, creating_journal_id=past_id, due_journal_id=past_id
        )

        async with authenticated_lifespan_client() as client:
            payload = await _update_task_text(client, task_id=task_id, text="reworded")

        assert "error" not in payload
        assert await stored_text(clean_database, task_id) == "reworded"

    async def test_no_journal_link_is_created(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """Intermediate links are explicit only; an agent's edit infers none."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )

        async with authenticated_lifespan_client() as client:
            payload = await _update_task_text(client, task_id=task_id, text="reworded")

        assert "error" not in payload
        assert await count(clean_database, COUNT_INTERMEDIATE_JOURNALS, {}) == 0

    async def test_blank_text_is_rejected_and_names_the_field(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The same refusal creation gives, so neither surface is the lenient one."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="print the permit",
        )

        async with authenticated_lifespan_client() as client:
            payload = await _update_task_text(client, task_id=task_id, text="   ")

        assert "text" in payload["message"]
        assert await stored_text(clean_database, task_id) == "print the permit"

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
            text="not yours",
            user_id=OTHER_USER_ID,
        )

        async with authenticated_lifespan_client() as client:
            foreign = await _update_task_text(
                client, task_id=foreign_task, text="reworded"
            )
            absent = await _update_task_text(client, task_id=999_999, text="reworded")

        assert foreign["error"] == absent["error"] == "Not found"
        assert foreign["message"].replace(str(foreign_task), "X") == absent[
            "message"
        ].replace("999999", "X")
        assert await stored_text(clean_database, foreign_task) == "not yours"

    async def test_a_call_carrying_a_status_is_rejected_by_the_tool_schema(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """Two tools, two decisions: rewording is not a way to change a status.

        The combined write exists for the ``PATCH`` body that genuinely carries
        both. A model gets one tool per intent, so smuggling a status through
        this one is refused by the transport before the service is reached.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )

        async with authenticated_lifespan_client() as client:
            response = await _raw_call(
                client,
                "update_task_text",
                {"task_id": task_id, "text": "reworded", "status": "done"},
            )

        assert '"isError":true' in response.text
        assert "unexpected_keyword_argument" in response.text
        assert await stored_status(clean_database, task_id) == "not_done"


@pytest.mark.integration
class TestDeleteTaskTool:
    """Deleting over MCP: the exception, and its blast radius.

    The tool exists because an agent that can create a task by mistake must be
    able to undo that mistake — the specification's MCP list omits delete while
    listing everything else, and principle 1 (no meaningful UI-only behaviour)
    settles it the other way. Recorded as open decision 4 in the iteration
    document.
    """

    async def test_deleting_removes_the_row_and_confirms_it(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """A tool must say something, so it says which task is gone."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )

        async with authenticated_lifespan_client() as client:
            payload = await _delete_task(client, task_id=task_id)

        assert "error" not in payload
        assert payload["deleted"] is True
        assert payload["task_id"] == task_id
        assert not await task_exists(clean_database, task_id)

    async def test_the_link_rows_go_and_the_journals_and_contacts_stay(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """The acceptance criterion, through the surface an agent reaches."""
        creating_id, due_id = task_anchors
        mentioned_id = await create_journal(
            journal_repository, title="Where it came up", days_offset=3
        )
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        contact_id = await create_contact(clean_database)
        await link_intermediate_journal(
            clean_database, task_id=task_id, journal_id=mentioned_id
        )
        await link_contact(clean_database, task_id=task_id, contact_id=contact_id)

        async with authenticated_lifespan_client() as client:
            payload = await _delete_task(client, task_id=task_id)

        assert "error" not in payload
        assert await count(clean_database, COUNT_INTERMEDIATE_JOURNALS, {}) == 0
        assert await count(clean_database, COUNT_CONTACT_LINKS, {}) == 0
        for journal_id in (creating_id, due_id, mentioned_id):
            assert await journal_repository.find_by_id(journal_id) is not None
        assert (
            await count(
                clean_database,
                "SELECT COUNT(*) FROM contacts WHERE id = :contact_id",
                {"contact_id": contact_id},
            )
            == 1
        )

    async def test_deleting_twice_is_not_found_the_second_time(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """A success on a task that was not there would mislead a retrying agent."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )

        async with authenticated_lifespan_client() as client:
            first = await _delete_task(client, task_id=task_id)
            second = await _delete_task(client, task_id=task_id)

        assert first["deleted"] is True
        assert second["error"] == "Not found"

    async def test_another_users_task_is_reported_as_not_found_and_survives(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """Indistinguishable — and intact, which a message alone would not show."""
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
            foreign = await _delete_task(client, task_id=foreign_task)
            absent = await _delete_task(client, task_id=999_999)

        assert foreign["error"] == absent["error"] == "Not found"
        assert foreign["message"].replace(str(foreign_task), "X") == absent[
            "message"
        ].replace("999999", "X")
        assert await task_exists(clean_database, foreign_task)

    async def test_other_tasks_are_untouched(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """A sibling sharing both anchors is not collateral damage."""
        creating_id, due_id = task_anchors
        doomed = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        survivor = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="somebody else's problem",
        )

        async with authenticated_lifespan_client() as client:
            payload = await _delete_task(client, task_id=doomed)

        assert "error" not in payload
        assert await count(clean_database, COUNT_TASKS, {"user_id": USER_ID}) == 1
        assert await stored_text(clean_database, survivor) == "somebody else's problem"


@pytest.mark.integration
class TestTheToolsRecordMcpProvenance:
    """A change an assistant made must not look like one the user made.

    This is the distinction the activity-history specification asks for by name,
    and it is the case the user most needs: a task appearing or disappearing
    because an agent did it is only comprehensible if the history says so. The
    service defaults to ``SYSTEM``, so a tool that omitted its provenance would
    pass every other test in this file while quietly mislabelling every change.
    """

    async def test_a_created_task_is_attributed_to_the_assistant(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors

        async with authenticated_lifespan_client() as client:
            payload = await _create_task(
                client,
                creating_journal_id=creating_id,
                due_journal_id=due_id,
                text="print the permit",
            )

        assert "error" not in payload
        (event,) = await task_events(clean_database)
        assert event.event_type == "TaskCreated"
        assert event.payload["source"] == Provenance.MCP.value
        assert event.payload["changed_by"] == "mcp"

    async def test_a_deleted_task_is_attributed_to_the_assistant(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )

        async with authenticated_lifespan_client() as client:
            payload = await _delete_task(client, task_id=task_id)

        assert "error" not in payload
        (event,) = await task_events(clean_database, task_id=task_id)
        assert event.event_type == "TaskDeleted"
        assert event.payload["source"] == Provenance.MCP.value
        assert event.payload["changed_by"] == "mcp"

    async def test_a_reworded_task_is_attributed_to_the_assistant(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="print the permit",
        )

        async with authenticated_lifespan_client() as client:
            payload = await _update_task_text(
                client,
                task_id=task_id,
                text="print the permit and the map",
            )

        assert "error" not in payload
        (event,) = await task_events(clean_database, task_id=task_id)
        assert event.event_type == "TaskUpdated"
        assert event.payload["changed_fields"] == {
            "text": ["print the permit", "print the permit and the map"]
        }
        assert event.payload["source"] == Provenance.MCP.value
        assert event.payload["changed_by"] == "mcp"

    async def test_a_status_change_is_attributed_to_the_assistant(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The tool most worth attributing: an agent closing a commitment.

        ``set_task_status`` publishes nothing itself — it delegates to
        ``update_task`` — so this asserts the provenance survives both hops, from
        the tool through the delegation to the stored row.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )

        async with authenticated_lifespan_client() as client:
            payload = await _set_task_status(client, task_id=task_id, status="done")

        assert "error" not in payload
        (event,) = await task_events(clean_database, task_id=task_id)
        assert event.event_type == "TaskUpdated"
        assert event.payload["changed_fields"] == {"status": ["not_done", "done"]}
        assert event.payload["source"] == Provenance.MCP.value
        assert event.payload["changed_by"] == "mcp"

    async def test_a_retarget_is_attributed_to_the_assistant(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """An agent deferring a commitment on the user's behalf.

        Provenance crosses an extra hop here — the tool calls
        ``retarget_due_journal_with_trail``, not the write that publishes — and
        a wrapper that accepted the pair and forwarded neither would pass every
        other retarget test in this file.
        """
        creating_id, due_id = task_anchors
        later_id = await create_journal(
            journal_repository, title="A fortnight out", days_offset=14
        )
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )

        async with authenticated_lifespan_client() as client:
            payload = await _retarget_task(
                client, task_id=task_id, due_journal_id=later_id
            )

        assert "error" not in payload
        link, event = await task_events(clean_database, task_id=task_id)
        assert event.event_type == "TaskDueJournalRetargeted"
        assert event.payload["changed_fields"] == {"due_journal_id": [due_id, later_id]}
        assert event.payload["source"] == Provenance.MCP.value
        assert event.payload["changed_by"] == "mcp"
        # The retained journal, announced separately and attributed to the same
        # assistant: the derivation is in ``origin``, not in the provenance.
        assert link.event_type == "TaskJournalLinked"
        assert link.payload["journal_id"] == due_id
        assert link.payload["origin"] == "retarget"
        assert link.payload["source"] == Provenance.MCP.value
        assert link.payload["changed_by"] == "mcp"

    async def test_an_agent_reopening_a_done_task_is_recorded_as_the_agent(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """The change this distinction exists for.

        An assistant undoing somebody's completion is exactly the event that is
        only comprehensible if the history says who did it — and the status
        change has to be in the stream at all for the question to arise.
        """
        creating_id, due_id = task_anchors
        later_id = await create_journal(
            journal_repository, title="A fortnight out", days_offset=14
        )
        task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus.DONE,
        )

        async with authenticated_lifespan_client() as client:
            payload = await _retarget_task(
                client,
                task_id=task_id,
                due_journal_id=later_id,
                acknowledge_reopen=True,
            )

        assert "error" not in payload
        _, event = await task_events(clean_database, task_id=task_id)
        assert event.event_type == "TaskDueJournalRetargeted"
        assert event.payload["changed_fields"]["status"] == ["done", "not_done"]
        assert event.payload["source"] == Provenance.MCP.value
        assert event.payload["changed_by"] == "mcp"

    async def test_attaching_a_journal_is_attributed_to_the_assistant(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """A link an agent asked for: ``mcp``, and ``manual`` rather than derived.

        The tool and the retarget publish the same event type, so ``origin`` is
        asserted alongside the provenance — a link filed under the wrong cause
        would otherwise look identical to a correct one.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        mentioned = await create_journal(journal_repository, title="Came up again")

        async with authenticated_lifespan_client() as client:
            payload = await _attach_journal(
                client, task_id=task_id, journal_id=mentioned
            )

        assert "error" not in payload
        (event,) = await task_events(clean_database, task_id=task_id)
        assert event.event_type == "TaskJournalLinked"
        assert event.payload["journal_id"] == mentioned
        assert event.payload["origin"] == "manual"
        assert event.payload["source"] == Provenance.MCP.value
        assert event.payload["changed_by"] == "mcp"

    async def test_detaching_a_journal_is_attributed_to_the_assistant(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        mentioned = await create_journal(journal_repository, title="Came up again")

        async with authenticated_lifespan_client() as client:
            attached = await _attach_journal(
                client, task_id=task_id, journal_id=mentioned
            )
            payload = await _detach_journal(
                client, task_id=task_id, journal_id=mentioned
            )

        assert "error" not in attached
        assert "error" not in payload
        _, event = await task_events(clean_database, task_id=task_id)
        assert event.event_type == "TaskJournalUnlinked"
        assert event.payload["journal_id"] == mentioned
        assert event.payload["source"] == Provenance.MCP.value
        assert event.payload["changed_by"] == "mcp"

    async def test_linking_a_contact_is_attributed_to_the_assistant(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """An assistant putting a person on somebody's task, recorded as theirs.

        Contact membership travels as a ``TaskUpdated`` carrying
        ``changed_fields``, the same type a reword uses, so the key is asserted
        alongside the provenance — a tool that reached the wrong service method
        would publish a ``TaskUpdated`` too.
        """
        creating_id, due_id = task_anchors
        sarah = await create_contact(clean_database, first_name="Sarah")
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )

        async with authenticated_lifespan_client() as client:
            payload = await _link_contact(client, task_id=task_id, contact_id=sarah)

        assert "error" not in payload
        (event,) = await task_events(clean_database, task_id=task_id)
        assert event.event_type == "TaskUpdated"
        assert event.payload["changed_fields"] == {
            contact_field_name(sarah): [None, sarah]
        }
        assert event.payload["source"] == Provenance.MCP.value
        assert event.payload["changed_by"] == "mcp"

    async def test_unlinking_a_contact_is_attributed_to_the_assistant(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The other tool, asserted separately rather than assumed from the first.

        They are different functions making different service calls, and either
        one dropping provenance is a silent success: the contact still moves and
        an event is still published — only the user's history stops being able to
        tell their own edit from an assistant's.
        """
        creating_id, due_id = task_anchors
        sarah = await create_contact(clean_database, first_name="Sarah")
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )

        async with authenticated_lifespan_client() as client:
            linked = await _link_contact(client, task_id=task_id, contact_id=sarah)
            payload = await _unlink_contact(client, task_id=task_id, contact_id=sarah)

        assert "error" not in linked
        assert "error" not in payload
        _, event = await task_events(clean_database, task_id=task_id)
        assert event.event_type == "TaskUpdated"
        assert event.payload["changed_fields"] == {
            contact_field_name(sarah): [sarah, None]
        }
        assert event.payload["source"] == Provenance.MCP.value
        assert event.payload["changed_by"] == "mcp"

    async def test_a_refused_status_change_records_nothing(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """Leaving cancelled is refused, and a refusal is not a change."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus.CANCELLED,
        )

        async with authenticated_lifespan_client() as client:
            payload = await _set_task_status(client, task_id=task_id, status="done")

        assert "error" in payload
        assert await task_events(clean_database, task_id=task_id) == []

    async def test_a_refused_delete_records_nothing(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """An agent asking twice must not write two deletions into the record."""
        creating_id = await create_journal(
            journal_repository, title="Theirs", user_id=OTHER_USER_ID
        )
        due_id = await create_journal(
            journal_repository,
            title="Theirs, later",
            days_offset=7,
            user_id=OTHER_USER_ID,
        )
        foreign_task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            user_id=OTHER_USER_ID,
        )

        async with authenticated_lifespan_client() as client:
            payload = await _delete_task(client, task_id=foreign_task_id)

        assert "error" in payload
        assert await task_events(clean_database) == []


async def _retarget_task(client: Any, **arguments: Any) -> dict[str, Any]:
    response = await _raw_call(client, "retarget_task", arguments)
    assert response.status_code == 200
    return extract_mcp_json_payload(response.text)


@pytest.mark.integration
class TestRetargetTaskTool:
    """The retarget over ``tools/call``: the same answers an HTTP client gets.

    Asserted separately from the endpoint rather than inferred from the shared
    service, for the reason this file exists: a tool can validate too little,
    flatten an actionable refusal into something a model cannot act on, or open
    a transaction the service already owns.

    Trails of more than one journal are compared **sorted**, for the reason the
    endpoint tests give: the port orders by ``created_at``, which ties when
    several links are written inside one fixture transaction, so the tie-break's
    order is an artefact of the fixture rather than a property of the surface.
    """

    @pytest.mark.parametrize("status", list(TaskStatus))
    async def test_a_retarget_lands_the_task_not_done_on_the_new_journal(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
        status: TaskStatus,
    ):
        """*"Retargeting always leaves the task not done"*, per starting status."""
        creating_id, due_id = task_anchors
        later_id = await create_journal(
            journal_repository, title="A fortnight out", days_offset=14
        )
        task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=status,
        )

        async with authenticated_lifespan_client() as client:
            payload = await _retarget_task(
                client,
                task_id=task_id,
                due_journal_id=later_id,
                acknowledge_reopen=True,
            )

        assert "error" not in payload
        assert payload["status"] == "not_done"
        assert payload["due_journal_id"] == later_id
        assert payload["creating_journal_id"] == creating_id
        assert await stored_status(clean_database, task_id) == "not_done"
        assert await stored_anchors(clean_database, task_id) == (creating_id, later_id)

    async def test_the_answer_carries_the_journal_the_task_just_left(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """The trail, in the same call — an agent has no read tool to ask with.

        This is the phase's second criterion on the surface where it matters
        most: there is still no way to read a task back over MCP, so a trail
        left out of this answer would be unreachable rather than merely
        inconvenient.
        """
        creating_id, due_id = task_anchors
        later_id = await create_journal(
            journal_repository, title="A fortnight out", days_offset=14
        )
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )

        async with authenticated_lifespan_client() as client:
            payload = await _retarget_task(
                client, task_id=task_id, due_journal_id=later_id
            )

        assert payload["intermediate_journal_ids"] == [due_id]

    async def test_a_repeatedly_deferred_task_accumulates_its_trail(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """Three hops, two of them returning to a journal already in the trail."""
        creating_id, due_id = task_anchors
        second = await create_journal(
            journal_repository, title="Two weeks out", days_offset=14
        )
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )

        async with authenticated_lifespan_client() as client:
            for target in (second, due_id):
                await _retarget_task(client, task_id=task_id, due_journal_id=target)
            payload = await _retarget_task(
                client, task_id=task_id, due_journal_id=second
            )

        assert sorted(payload["intermediate_journal_ids"]) == sorted([due_id, second])
        assert sorted(await intermediate_journal_ids(clean_database, task_id)) == (
            sorted([due_id, second])
        )

    async def test_a_lapsed_task_is_resurrected_and_keeps_the_passed_journal(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """The journal being left is never judged, so a lapsed task is reachable."""
        creating_id, _ = task_anchors
        passed_id = await create_journal(
            journal_repository, title="Last week", days_offset=-7
        )
        future_id = await create_journal(
            journal_repository, title="Next week", days_offset=7
        )
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=passed_id
        )

        async with authenticated_lifespan_client() as client:
            payload = await _retarget_task(
                client, task_id=task_id, due_journal_id=future_id
            )

        assert payload["due_journal_id"] == future_id
        assert payload["intermediate_journal_ids"] == [passed_id]

    async def test_retargeting_onto_the_current_due_journal_writes_nothing(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """A no-op, needing no acknowledgement even on a *done* task.

        The timestamp is backdated first, without which asserting it has not
        moved could not fail: ``now()`` is the transaction timestamp and the
        fixture runs the whole test in one, so an insert-time default and an
        update-time stamp are the same value. The *done* status is a second,
        independent witness — any path but the no-op would either have refused
        the call for want of an acknowledgement or written *not done* over it.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus.DONE,
        )
        backdated = await backdate_updated_at(clean_database, task_id)

        async with authenticated_lifespan_client() as client:
            payload = await _retarget_task(
                client, task_id=task_id, due_journal_id=due_id
            )

        assert "error" not in payload
        assert payload["status"] == "done"
        assert await stored_status(clean_database, task_id) == "done"
        assert await stored_anchors(clean_database, task_id) == (creating_id, due_id)
        assert await stored_updated_at(clean_database, task_id) == backdated
        assert await count(clean_database, COUNT_INTERMEDIATE_JOURNALS, {}) == 0


@pytest.mark.integration
class TestEveryTaskReturningToolAnswersTheSameShape:
    """One task shape, whichever tool produced it.

    The retarget tests above prove the trail on the *retarget*. This proves the
    other two, and it is asserted here rather than inferred from the shared
    ``_task_to_dict`` for the reason the whole file exists: a shared helper is
    no evidence that both callers pass it the right thing, and a tool that
    dropped the argument would still return a perfectly valid-looking task.
    """

    async def test_a_created_task_reports_an_empty_trail(
        self,
        authenticated_lifespan_client,
        task_anchors: tuple[int, int],
    ):
        """Creation writes no intermediate link, and says so rather than omitting it."""
        creating_id, due_id = task_anchors

        async with authenticated_lifespan_client() as client:
            payload = await _create_task(
                client,
                creating_journal_id=creating_id,
                due_journal_id=due_id,
                text="print the permit",
            )

        assert payload["intermediate_journal_ids"] == []

    async def test_a_status_change_reports_the_trail_the_task_already_had(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """Answering ``[]`` here would be a lie rather than an omission.

        It matters more over MCP than over HTTP: no tool reads a task back, so
        this answer is the only place an agent could learn the trail.
        """
        creating_id, due_id = task_anchors
        passed_id = await create_journal(
            journal_repository, title="Where it used to be due", days_offset=-7
        )
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        await link_intermediate_journal(
            clean_database, task_id=task_id, journal_id=passed_id
        )

        async with authenticated_lifespan_client() as client:
            payload = await _set_task_status(client, task_id=task_id, status="done")

        assert payload["intermediate_journal_ids"] == [passed_id]


@pytest.mark.integration
class TestTheReopenGateReachesAnAgent:
    """An agent must be told *why*, and how to proceed, not merely refused.

    The specification says the product must say a done task is being reopened
    before it happens. Over MCP the model is the one being told, so the message
    has to name the acknowledgement — a refusal a model cannot act on becomes a
    retry loop.
    """

    async def test_an_unacknowledged_reopen_is_refused_with_an_actionable_message(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        later_id = await create_journal(
            journal_repository, title="A fortnight out", days_offset=14
        )
        task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus.DONE,
        )

        async with authenticated_lifespan_client() as client:
            payload = await _retarget_task(
                client, task_id=task_id, due_journal_id=later_id
            )

        assert payload["error"] == "Task error"
        assert "acknowledge" in payload["message"].lower()

    async def test_the_refusal_writes_nothing_at_all(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """Not the status, not the anchor, and not the automatic link."""
        creating_id, due_id = task_anchors
        later_id = await create_journal(
            journal_repository, title="A fortnight out", days_offset=14
        )
        task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus.DONE,
        )

        async with authenticated_lifespan_client() as client:
            await _retarget_task(client, task_id=task_id, due_journal_id=later_id)

        assert await stored_status(clean_database, task_id) == "done"
        assert await stored_anchors(clean_database, task_id) == (creating_id, due_id)
        assert await count(clean_database, COUNT_INTERMEDIATE_JOURNALS, {}) == 0

    async def test_the_same_call_acknowledged_reopens_the_task(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        later_id = await create_journal(
            journal_repository, title="A fortnight out", days_offset=14
        )
        task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus.DONE,
        )

        async with authenticated_lifespan_client() as client:
            payload = await _retarget_task(
                client,
                task_id=task_id,
                due_journal_id=later_id,
                acknowledge_reopen=True,
            )

        assert "error" not in payload
        assert payload["status"] == "not_done"
        assert await stored_status(clean_database, task_id) == "not_done"

    async def test_a_cancelled_task_is_reopened_without_any_acknowledgement(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """This is where ``set_task_status``'s refusal sends a model.

        Gating it would send the model back and forth between two refusals, each
        naming the other.
        """
        creating_id, due_id = task_anchors
        later_id = await create_journal(
            journal_repository, title="A fortnight out", days_offset=14
        )
        task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus.CANCELLED,
        )

        async with authenticated_lifespan_client() as client:
            payload = await _retarget_task(
                client, task_id=task_id, due_journal_id=later_id
            )

        assert "error" not in payload
        assert payload["status"] == "not_done"

    async def test_the_gate_is_checked_after_the_journal_rules(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """A done task onto a *past* journal hears about the journal, not the gate.

        The acknowledgement is a confirmation rather than a validation, so a
        caller is never asked to confirm a request that was never going to
        succeed. Pinned here as well as on the endpoint because the tool could
        reorder it independently: every other test in this file either supplies
        the acknowledgement or names a valid journal, so moving the gate to the
        top of the tool would leave them all green.
        """
        creating_id, due_id = task_anchors
        past_id = await create_journal(
            journal_repository, title="Last week", days_offset=-7
        )
        task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus.DONE,
        )

        async with authenticated_lifespan_client() as client:
            payload = await _retarget_task(
                client, task_id=task_id, due_journal_id=past_id
            )

        assert payload["error"] == "Task error"
        assert "not after today" in payload["message"]
        assert "acknowledge" not in payload["message"].lower()
        assert await stored_status(clean_database, task_id) == "done"


@pytest.mark.integration
class TestTheRetargetToolRevalidatesTheJournalRules:
    """Invariant 4 and ownership, re-run for an AI caller too."""

    @pytest.mark.parametrize("status", list(TaskStatus))
    async def test_a_past_dated_journal_is_refused_with_both_dates(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
        status: TaskStatus,
    ):
        """A model given only "refused" will propose the same journal again."""
        creating_id, due_id = task_anchors
        past_id = await create_journal(
            journal_repository, title="Last week", days_offset=-7
        )
        task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=status,
        )

        async with authenticated_lifespan_client() as client:
            payload = await _retarget_task(
                client,
                task_id=task_id,
                due_journal_id=past_id,
                acknowledge_reopen=True,
            )

        assert payload["error"] == "Task error"
        assert "not after today" in payload["message"]
        assert await stored_anchors(clean_database, task_id) == (creating_id, due_id)
        assert await count(clean_database, COUNT_INTERMEDIATE_JOURNALS, {}) == 0

    async def test_another_users_journal_reads_as_an_absent_one(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """Otherwise the tool becomes a way to probe another user's journals."""
        creating_id, due_id = task_anchors
        foreign_id = await create_journal(
            journal_repository,
            title="Somebody else's trip",
            days_offset=7,
            user_id=OTHER_USER_ID,
        )
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )

        async with authenticated_lifespan_client() as client:
            foreign = await _retarget_task(
                client, task_id=task_id, due_journal_id=foreign_id
            )
            absent = await _retarget_task(
                client, task_id=task_id, due_journal_id=999_999
            )

        assert foreign["error"] == absent["error"] == "Not found"
        assert foreign["message"].replace(str(foreign_id), "X") == absent[
            "message"
        ].replace("999999", "X")
        assert await stored_anchors(clean_database, task_id) == (creating_id, due_id)

    async def test_another_users_task_is_reported_as_not_found(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """And is left exactly where it was."""
        _, due_id = task_anchors
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
            foreign = await _retarget_task(
                client, task_id=foreign_task, due_journal_id=due_id
            )
            absent = await _retarget_task(
                client, task_id=999_999, due_journal_id=due_id
            )

        assert foreign["error"] == absent["error"] == "Not found"
        assert foreign["message"].replace(str(foreign_task), "X") == absent[
            "message"
        ].replace("999999", "X")
        assert await stored_anchors(clean_database, foreign_task) == (
            foreign_journal,
            foreign_journal,
        )


@pytest.mark.integration
class TestRejectedRetargetArguments:
    """What the transport refuses before the service is ever reached."""

    @pytest.mark.parametrize(
        "extra",
        [
            {"now": "2020-01-01T00:00:00+00:00"},
            {"creating_journal_id": 1},
            {"status": "done"},
            {"due_date": "2026-09-01"},
        ],
        ids=["now", "the creating journal", "a status", "a bare date"],
    )
    async def test_an_argument_the_schema_does_not_offer_is_rejected(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
        extra: dict[str, Any],
    ):
        """The schema's absences are enforced by the transport, not merely stated.

        ``now`` is the seam invariant 4 is judged against; the creating journal
        is immutable; a retarget's status is not the caller's to choose; and a
        task is due in a journal rather than on a date.
        """
        creating_id, due_id = task_anchors
        later_id = await create_journal(
            journal_repository, title="A fortnight out", days_offset=14
        )
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )

        async with authenticated_lifespan_client() as client:
            response = await _raw_call(
                client,
                "retarget_task",
                {"task_id": task_id, "due_journal_id": later_id, **extra},
            )

        assert '"isError":true' in response.text
        assert await stored_anchors(clean_database, task_id) == (creating_id, due_id)

    @pytest.mark.parametrize("value", ["true", "yes", 1, "1"], ids=str)
    async def test_a_truthy_non_boolean_acknowledgement_does_not_reopen_a_done_task(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
        value: object,
    ):
        """A model that sends the wrong type must not reopen a completed task.

        The transport coerced every one of these before the parameter became
        ``StrictBool`` — so an agent that sent ``"true"``, which is a plausible
        thing for a model to emit, silently undid a completion. Asserted on the
        stored status rather than only the refusal.
        """
        creating_id, due_id = task_anchors
        later_id = await create_journal(
            journal_repository, title="A fortnight out", days_offset=14
        )
        task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus.DONE,
        )

        async with authenticated_lifespan_client() as client:
            response = await _raw_call(
                client,
                "retarget_task",
                {
                    "task_id": task_id,
                    "due_journal_id": later_id,
                    "acknowledge_reopen": value,
                },
            )

        assert '"isError":true' in response.text
        assert await stored_status(clean_database, task_id) == "done"
        assert await stored_anchors(clean_database, task_id) == (creating_id, due_id)

    @pytest.mark.parametrize("field", ["task_id", "due_journal_id"])
    async def test_an_id_beyond_int32_is_refused_before_the_driver_sees_it(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
        field: str,
    ):
        """Bounded in the schema, so it is a rejection rather than an internal error."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        arguments: dict[str, Any] = {"task_id": task_id, "due_journal_id": due_id}
        arguments[field] = 2_147_483_648

        async with authenticated_lifespan_client() as client:
            response = await _raw_call(client, "retarget_task", arguments)

        assert '"isError":true' in response.text
        assert await stored_anchors(clean_database, task_id) == (creating_id, due_id)


async def _attach_journal(client: Any, **arguments: Any) -> dict[str, Any]:
    response = await _raw_call(client, "attach_intermediate_journal_to_task", arguments)
    assert response.status_code == 200
    return extract_mcp_json_payload(response.text)


async def _detach_journal(client: Any, **arguments: Any) -> dict[str, Any]:
    response = await _raw_call(
        client, "detach_intermediate_journal_from_task", arguments
    )
    assert response.status_code == 200
    return extract_mcp_json_payload(response.text)


@pytest.mark.integration
class TestIntermediateJournalTools:
    """The same matrix an HTTP client gets, over ``tools/call``.

    The tools answer with ``attached`` (the resulting state) and ``changed``
    (whether a row moved), so an agent can tell a fresh link from a no-op without
    a read tool existing yet. That is the one thing the REST 204 withholds.
    """

    async def test_attaching_writes_the_row(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        mentioned = await create_journal(journal_repository, title="Came up again")

        async with authenticated_lifespan_client() as client:
            payload = await _attach_journal(
                client, task_id=task_id, journal_id=mentioned
            )

        assert "error" not in payload
        assert payload["attached"] is True
        assert payload["changed"] is True
        assert await intermediate_journal_ids(clean_database, task_id) == [mentioned]

    async def test_attaching_again_reports_no_change_and_leaves_one_row(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        mentioned = await create_journal(journal_repository, title="Came up again")

        async with authenticated_lifespan_client() as client:
            first = await _attach_journal(client, task_id=task_id, journal_id=mentioned)
            second = await _attach_journal(
                client, task_id=task_id, journal_id=mentioned
            )

        assert (first["changed"], second["changed"]) == (True, False)
        assert second["attached"] is True
        assert await intermediate_journal_ids(clean_database, task_id) == [mentioned]

    async def test_detaching_removes_the_row(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        mentioned = await create_journal(journal_repository, title="Came up again")
        await link_intermediate_journal(
            clean_database, task_id=task_id, journal_id=mentioned
        )

        async with authenticated_lifespan_client() as client:
            payload = await _detach_journal(
                client, task_id=task_id, journal_id=mentioned
            )

        assert payload["attached"] is False
        assert payload["changed"] is True
        assert await intermediate_journal_ids(clean_database, task_id) == []

    async def test_detaching_again_reports_no_change(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        mentioned = await create_journal(journal_repository, title="Came up again")
        await link_intermediate_journal(
            clean_database, task_id=task_id, journal_id=mentioned
        )

        async with authenticated_lifespan_client() as client:
            first = await _detach_journal(client, task_id=task_id, journal_id=mentioned)
            second = await _detach_journal(
                client, task_id=task_id, journal_id=mentioned
            )

        assert (first["changed"], second["changed"]) == (True, False)
        assert second["attached"] is False

    @pytest.mark.parametrize("status", list(TaskStatus))
    async def test_attaching_works_in_any_status(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
        status: TaskStatus,
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=status,
        )
        mentioned = await create_journal(journal_repository, title="Came up again")

        async with authenticated_lifespan_client() as client:
            payload = await _attach_journal(
                client, task_id=task_id, journal_id=mentioned
            )

        assert payload["changed"] is True
        assert await intermediate_journal_ids(clean_database, task_id) == [mentioned]
        assert await stored_status(clean_database, task_id) == status.value

    async def test_no_contact_link_is_written(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        await create_contact(clean_database, first_name="Sarah")
        mentioned = await create_journal(journal_repository, title="Came up again")

        async with authenticated_lifespan_client() as client:
            await _attach_journal(client, task_id=task_id, journal_id=mentioned)

        assert await count(clean_database, COUNT_CONTACT_LINKS, {}) == 0


@pytest.mark.integration
class TestIntermediateJournalToolRejections:
    """Every refusal, in the form an agent can act on.

    The distinction that matters is between the two rejections attaching can
    produce: *pick another journal* and *it is already linked in a stronger
    role*. Both must be more than "an error occurred", and they must not read
    alike.
    """

    @pytest.mark.parametrize("anchor", ["creating", "due"])
    async def test_attaching_an_anchor_journal_names_the_role(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
        anchor: str,
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        journal_id = creating_id if anchor == "creating" else due_id

        async with authenticated_lifespan_client() as client:
            payload = await _attach_journal(
                client, task_id=task_id, journal_id=journal_id
            )

        assert payload["error"] == "Task error"
        assert anchor in payload["message"]
        assert await count(clean_database, COUNT_INTERMEDIATE_JOURNALS, {}) == 0

    @pytest.mark.parametrize("anchor", ["creating", "due"])
    async def test_detaching_an_anchor_journal_names_the_role(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
        anchor: str,
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        journal_id = creating_id if anchor == "creating" else due_id

        async with authenticated_lifespan_client() as client:
            payload = await _detach_journal(
                client, task_id=task_id, journal_id=journal_id
            )

        assert payload["error"] == "Task error"
        assert anchor in payload["message"]

    async def test_an_anchor_refusal_does_not_read_like_a_missing_journal(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The two rejections have different remedies, so they must look different.

        An agent that cannot tell them apart will retry with the same journal, or
        go looking for a journal that is right in front of it.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )

        async with authenticated_lifespan_client() as client:
            anchor = await _attach_journal(client, task_id=task_id, journal_id=due_id)
            missing = await _attach_journal(client, task_id=task_id, journal_id=999_999)

        assert anchor["error"] != missing["error"]
        assert missing["error"] == "Journal not found"

    async def test_an_unknown_journal_is_reported_as_a_journal(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The journal domain's answer, so the message names the journal and its id.

        A task-shaped "Not found" would leave an agent unsure which of the two
        ids it sent was the problem.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )

        async with authenticated_lifespan_client() as client:
            payload = await _attach_journal(client, task_id=task_id, journal_id=999_999)

        assert payload["error"] == "Journal not found"
        assert "999999" in payload["message"]
        assert await count(clean_database, COUNT_INTERMEDIATE_JOURNALS, {}) == 0

    async def test_another_users_journal_is_indistinguishable_from_an_absent_one(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        theirs = await create_journal(
            journal_repository, title="Not yours", user_id=OTHER_USER_ID
        )

        async with authenticated_lifespan_client() as client:
            foreign = await _attach_journal(client, task_id=task_id, journal_id=theirs)
            absent = await _attach_journal(client, task_id=task_id, journal_id=999_999)

        assert foreign["error"] == absent["error"] == "Journal not found"
        assert foreign["message"].replace(str(theirs), "X") == absent[
            "message"
        ].replace("999999", "X")
        assert await count(clean_database, COUNT_INTERMEDIATE_JOURNALS, {}) == 0

    async def test_another_users_task_answers_exactly_as_an_absent_one(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """On both tools, and their link survives."""
        their_journal = await create_journal(
            journal_repository, title="Theirs", user_id=OTHER_USER_ID
        )
        their_task = await create_task(
            clean_database,
            creating_journal_id=their_journal,
            due_journal_id=their_journal,
            user_id=OTHER_USER_ID,
        )
        their_mention = await create_journal(
            journal_repository, title="Their mention", user_id=OTHER_USER_ID
        )
        await link_intermediate_journal(
            clean_database, task_id=their_task, journal_id=their_mention
        )
        mine = await create_journal(journal_repository, title="Mine")

        async with authenticated_lifespan_client() as client:
            foreign_attach = await _attach_journal(
                client, task_id=their_task, journal_id=mine
            )
            absent_attach = await _attach_journal(
                client, task_id=999_999, journal_id=mine
            )
            foreign_detach = await _detach_journal(
                client, task_id=their_task, journal_id=their_mention
            )
            absent_detach = await _detach_journal(
                client, task_id=999_999, journal_id=their_mention
            )

        # Compared with each other rather than each against a constant, which is
        # what the name promises; the id the caller supplied is normalised out as
        # the only legitimate difference.
        assert foreign_attach["error"] == absent_attach["error"] == "Not found"
        assert foreign_attach["message"].replace(str(their_task), "X") == absent_attach[
            "message"
        ].replace("999999", "X")
        assert foreign_detach["error"] == absent_detach["error"] == "Not found"
        assert foreign_detach["message"].replace(str(their_task), "X") == absent_detach[
            "message"
        ].replace("999999", "X")
        assert await intermediate_journal_ids(clean_database, their_task) == [
            their_mention
        ]

    @pytest.mark.parametrize("unwanted", ["role", "relationship_type", "status"])
    async def test_a_role_argument_is_refused_by_the_transport(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
        unwanted: str,
    ):
        """Refused before the service is reached, because the schema has no such field."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        mentioned = await create_journal(journal_repository, title="Came up again")

        async with authenticated_lifespan_client() as client:
            response = await _raw_call(
                client,
                "attach_intermediate_journal_to_task",
                {
                    "task_id": task_id,
                    "journal_id": mentioned,
                    unwanted: "due",
                },
            )

        assert '"isError":true' in response.text
        assert await intermediate_journal_ids(clean_database, task_id) == []

    async def test_a_journal_id_beyond_int32_is_refused(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )

        async with authenticated_lifespan_client() as client:
            response = await _raw_call(
                client,
                "attach_intermediate_journal_to_task",
                {"task_id": task_id, "journal_id": 2_147_483_648},
            )

        assert '"isError":true' in response.text
        assert await intermediate_journal_ids(clean_database, task_id) == []


async def _get_task(client: Any, **arguments: Any) -> dict[str, Any]:
    response = await _raw_call(client, "get_task", arguments)
    assert response.status_code == 200
    return extract_mcp_json_payload(response.text)


async def _list_journal_tasks(client: Any, **arguments: Any) -> dict[str, Any]:
    response = await _raw_call(client, "list_journal_tasks", arguments)
    assert response.status_code == 200
    return extract_mcp_json_payload(response.text)


@pytest.mark.integration
class TestGetTaskTool:
    """The tool the write tools have been compensating for.

    Every task-returning tool carries the journal trail because until now no
    tool read a task back. This one does, and it has to give an agent the same
    answer the endpoint gives a browser — including the lapse, which is the one
    thing an agent cannot derive for itself: it would need the user's timezone
    and the due journal's event state.
    """

    async def test_it_returns_the_task_with_its_journals_and_contacts(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        mention_id = await create_journal(journal_repository, title="Revisited")
        task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="print the permit",
        )
        await link_intermediate_journal(
            clean_database, task_id=task_id, journal_id=mention_id
        )
        contact_id = await create_contact(clean_database, first_name="Sarah")
        await link_contact(clean_database, task_id=task_id, contact_id=contact_id)

        async with authenticated_lifespan_client() as client:
            payload = await _get_task(client, task_id=task_id)

        assert "error" not in payload
        assert payload["text"] == "print the permit"
        assert payload["status"] == "not_done"
        assert payload["creating_journal"]["id"] == creating_id
        assert payload["due_journal"]["id"] == due_id
        assert [ref["id"] for ref in payload["intermediate_journals"]] == [mention_id]
        assert [contact["id"] for contact in payload["contacts"]] == [contact_id]

    async def test_it_keeps_the_trail_the_write_tools_promise(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """``intermediate_journal_ids`` survives beside the resolved journals.

        An agent that learned the shape from ``create_task`` must not have to
        learn a second one to read the same task back.
        """
        creating_id, due_id = task_anchors
        mention_id = await create_journal(journal_repository, title="Revisited")
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        await link_intermediate_journal(
            clean_database, task_id=task_id, journal_id=mention_id
        )

        async with authenticated_lifespan_client() as client:
            payload = await _get_task(client, task_id=task_id)

        assert payload["intermediate_journal_ids"] == [mention_id]
        assert payload["creating_journal_id"] == creating_id
        assert payload["due_journal_id"] == due_id

    async def test_a_journal_ref_carries_a_date_rather_than_an_instant(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        user_settings_repository: SqlUserSettingsRepository,
        task_anchors: tuple[int, int],
    ):
        """Dated in the user's zone, so an agent cannot re-derive it wrongly.

        Kiritimati is +14, so an instant at midday UTC on 1 January 2020 is
        already the 2nd there — a date no UTC reading produces.
        """
        creating_id, _ = task_anchors
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone="Pacific/Kiritimati")
        )
        due_id = await create_journal(
            journal_repository, title="Fixed", start=FIXED_PAST_INSTANT
        )
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )

        async with authenticated_lifespan_client() as client:
            payload = await _get_task(client, task_id=task_id)

        assert payload["due_journal"]["date"] == "2020-01-02"

    async def test_a_cancelled_due_journal_reports_its_own_lapse_reason(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """The distinction an agent needs to choose what to do next.

        "The day went by" suggests retargeting; "the meeting was called off"
        may mean the commitment is moot.
        """
        creating_id, _ = task_anchors
        cancelled_id = await create_journal(
            journal_repository, title="Cancelled meeting", days_offset=7
        )
        await mark_journal_as_event(
            clean_database, cancelled_id, event_state=EventState.CANCELLED
        )
        task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=cancelled_id,
        )

        async with authenticated_lifespan_client() as client:
            payload = await _get_task(client, task_id=task_id)

        assert payload["lapsed"] is True
        assert payload["lapse_reason"] == "due_journal_cancelled"
        assert payload["due_journal"]["cancelled"] is True

    async def test_a_really_cancelled_due_journal_reports_it_over_mcp(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The same answer after a cancellation nothing seeded.

        The test above writes ``journal_calendar_info`` itself, which proves
        this tool *serialises* a cancelled journal correctly and assumes the
        state arrives. Here calendar sync really cancels the instance — the
        deletion it prefers is refused by the anchor guard, exactly as it is in
        production for a task's due journal — so the whole chain is exercised:
        the sync write, the batched cancellation lookup, the rule, and the tool
        payload an agent reads. ITER18-002 Phase 4 owns this half.
        """
        creating_id, _ = task_anchors
        calendar_id = await create_calendar(clean_database, user_id=USER_ID)
        processor = build_processor(clean_database)
        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_mcp_lapse",
                user_id=USER_ID,
                recurring_event_id=MASTER_ID,
            )
        )
        due_id = int(created["journal_id"])
        task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )

        await processor.process_event(
            sync_event(
                "journal_event.cancelled",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_mcp_lapse",
                user_id=USER_ID,
                existing_journal_id=due_id,
                recurring_event_id=MASTER_ID,
            )
        )

        async with authenticated_lifespan_client() as client:
            payload = await _get_task(client, task_id=task_id)

        assert payload["lapsed"] is True
        assert payload["lapse_reason"] == "due_journal_cancelled"
        assert payload["due_journal"]["cancelled"] is True

    async def test_a_passed_due_journal_reports_the_other_reason(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, _ = task_anchors
        passed_id = await create_journal(
            journal_repository, title="Last week", days_offset=-7
        )
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=passed_id
        )

        async with authenticated_lifespan_client() as client:
            payload = await _get_task(client, task_id=task_id)

        assert payload["lapse_reason"] == "date_passed"

    async def test_a_task_that_has_not_lapsed_reports_no_reason(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )

        async with authenticated_lifespan_client() as client:
            payload = await _get_task(client, task_id=task_id)

        assert payload["lapsed"] is False
        assert payload["lapse_reason"] is None

    async def test_another_users_task_and_an_absent_one_answer_identically(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """The tool inherits the endpoint's 404 rather than deciding its own.

        The two answers differ **only in the id the caller supplied**, which is
        what stops a read being used to probe for other users' tasks — the same
        hedge every other task tool carries, asserted the same way.
        """
        theirs_journal = await create_journal(
            journal_repository, title="Theirs", user_id=OTHER_USER_ID
        )
        theirs = await create_task(
            clean_database,
            creating_journal_id=theirs_journal,
            due_journal_id=theirs_journal,
            user_id=OTHER_USER_ID,
        )

        async with authenticated_lifespan_client() as client:
            foreign = await _get_task(client, task_id=theirs)
            absent = await _get_task(client, task_id=999_999)

        assert foreign["error"] == absent["error"] == "Not found"
        assert foreign["message"].replace(str(theirs), "X") == absent[
            "message"
        ].replace("999999", "X")


@pytest.mark.integration
class TestListJournalTasksTool:
    """A journal's tasks, nested under the role each link holds."""

    async def test_it_nests_the_tasks_under_the_three_groups(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The roles are the structure here, unlike the JSON:API envelope.

        An agent asked to list "by link role" wants to read the roles off the
        answer rather than reassemble them from an attribute.
        """
        viewed_id, elsewhere_id = task_anchors
        due_here = await create_task(
            clean_database,
            creating_journal_id=elsewhere_id,
            due_journal_id=viewed_id,
        )
        created_here = await create_task(
            clean_database,
            creating_journal_id=viewed_id,
            due_journal_id=elsewhere_id,
        )
        mentioned_here = await create_task(
            clean_database,
            creating_journal_id=elsewhere_id,
            due_journal_id=elsewhere_id,
        )
        await link_intermediate_journal(
            clean_database, task_id=mentioned_here, journal_id=viewed_id
        )

        async with authenticated_lifespan_client() as client:
            payload = await _list_journal_tasks(client, journal_id=viewed_id)

        assert payload["journal_id"] == viewed_id
        assert [task["id"] for task in payload["groups"]["due"]] == [due_here]
        assert [task["id"] for task in payload["groups"]["created"]] == [created_here]
        assert [task["id"] for task in payload["groups"]["mentioned"]] == [
            mentioned_here
        ]

    async def test_a_task_in_two_roles_appears_in_both_groups(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """No uniqueness rule applies here, so the nesting can repeat it.

        Which is why the tool says so in its description: an agent counting
        rows across the groups would otherwise report a task twice as a bug.
        """
        viewed_id, _ = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=viewed_id, due_journal_id=viewed_id
        )

        async with authenticated_lifespan_client() as client:
            payload = await _list_journal_tasks(client, journal_id=viewed_id)

        assert [task["id"] for task in payload["groups"]["due"]] == [task_id]
        assert [task["id"] for task in payload["groups"]["created"]] == [task_id]
        assert payload["groups"]["due"][0]["link_roles"] == ["due", "created"]

    async def test_each_listed_task_carries_the_full_read_shape(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The same fields ``get_task`` gives, so one reader serves both."""
        viewed_id, due_id = task_anchors
        task_id = await create_task(
            clean_database,
            creating_journal_id=viewed_id,
            due_journal_id=due_id,
            text="return Sarah's book",
        )
        contact_id = await create_contact(clean_database, first_name="Sarah")
        await link_contact(clean_database, task_id=task_id, contact_id=contact_id)

        async with authenticated_lifespan_client() as client:
            payload = await _list_journal_tasks(client, journal_id=viewed_id)

        (task,) = payload["groups"]["created"]
        assert task["text"] == "return Sarah's book"
        assert task["status"] == "not_done"
        assert task["lapsed"] is False
        assert [contact["id"] for contact in task["contacts"]] == [contact_id]
        assert task["due_journal"]["id"] == due_id

    async def test_the_role_filter_returns_only_that_group(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        viewed_id, elsewhere_id = task_anchors
        due_here = await create_task(
            clean_database,
            creating_journal_id=elsewhere_id,
            due_journal_id=viewed_id,
        )
        await create_task(
            clean_database,
            creating_journal_id=viewed_id,
            due_journal_id=elsewhere_id,
        )

        async with authenticated_lifespan_client() as client:
            payload = await _list_journal_tasks(
                client, journal_id=viewed_id, role="due"
            )

        assert [task["id"] for task in payload["groups"]["due"]] == [due_here]
        assert payload["groups"]["created"] == []
        assert payload["groups"]["mentioned"] == []

    async def test_an_unknown_role_is_refused(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """A misspelled filter must not quietly widen to everything."""
        viewed_id, _ = task_anchors

        async with authenticated_lifespan_client() as client:
            response = await _raw_call(
                client,
                "list_journal_tasks",
                {"journal_id": viewed_id, "role": "overdue"},
            )

        assert '"isError":true' in response.text

    async def test_lapsed_and_finished_tasks_are_listed(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """A journal is where a lapsed task is meant to be found again."""
        viewed_id, due_id = task_anchors
        passed_id = await create_journal(
            journal_repository, title="Last week", days_offset=-7
        )
        lapsed = await create_task(
            clean_database, creating_journal_id=viewed_id, due_journal_id=passed_id
        )
        done = await create_task(
            clean_database,
            creating_journal_id=viewed_id,
            due_journal_id=due_id,
            status=TaskStatus.DONE,
        )

        async with authenticated_lifespan_client() as client:
            payload = await _list_journal_tasks(client, journal_id=viewed_id)

        listed = {task["id"]: task for task in payload["groups"]["created"]}
        assert set(listed) == {lapsed, done}
        assert listed[lapsed]["lapsed"] is True
        assert listed[done]["status"] == "done"

    async def test_a_cancelled_due_journal_is_marked_on_the_listed_row(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """The cancellation cause through the batch, not only the single read.

        An agent listing a journal's tasks has to be able to see *why* one
        lapsed without a follow-up ``get_task`` per row.
        """
        viewed_id, _ = task_anchors
        cancelled_id = await create_journal(
            journal_repository, title="Cancelled meeting", days_offset=7
        )
        await mark_journal_as_event(
            clean_database, cancelled_id, event_state=EventState.CANCELLED
        )
        task_id = await create_task(
            clean_database,
            creating_journal_id=viewed_id,
            due_journal_id=cancelled_id,
        )

        async with authenticated_lifespan_client() as client:
            payload = await _list_journal_tasks(client, journal_id=viewed_id)

        (task,) = payload["groups"]["created"]
        assert task["id"] == task_id
        assert task["lapse_reason"] == "due_journal_cancelled"
        assert task["due_journal"]["cancelled"] is True

    async def test_a_journal_with_no_tasks_answers_three_empty_groups(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """An empty journal is a normal answer with the normal shape."""
        viewed_id, _ = task_anchors

        async with authenticated_lifespan_client() as client:
            payload = await _list_journal_tasks(client, journal_id=viewed_id)

        assert payload["groups"] == {"due": [], "created": [], "mentioned": []}

    async def test_another_users_journal_and_an_absent_one_answer_identically(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """The journal domain's own 404, inherited rather than re-decided.

        And indistinguishable from an absent journal, so a listing cannot be
        used to discover which journal ids belong to somebody else.

        The error is the journal domain's *"Journal not found"* rather than the
        task domain's bare *"Not found"*, which is the more useful answer: what
        the caller named wrongly was a journal, and the tasks are not the
        problem. The same distinction the intermediate-journal tools carry.
        """
        theirs = await create_journal(
            journal_repository, title="Theirs", user_id=OTHER_USER_ID
        )

        async with authenticated_lifespan_client() as client:
            foreign = await _list_journal_tasks(client, journal_id=theirs)
            absent = await _list_journal_tasks(client, journal_id=999_999)

        assert foreign["error"] == absent["error"] == "Journal not found"
        assert foreign["message"].replace(str(theirs), "X") == absent[
            "message"
        ].replace("999999", "X")

    async def test_another_users_task_is_never_listed(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        viewed_id, _ = task_anchors
        mine = await create_task(
            clean_database, creating_journal_id=viewed_id, due_journal_id=viewed_id
        )
        theirs_journal = await create_journal(
            journal_repository, title="Theirs", user_id=OTHER_USER_ID
        )
        theirs = await create_task(
            clean_database,
            creating_journal_id=theirs_journal,
            due_journal_id=theirs_journal,
            user_id=OTHER_USER_ID,
        )
        await link_intermediate_journal(
            clean_database, task_id=theirs, journal_id=viewed_id
        )

        async with authenticated_lifespan_client() as client:
            payload = await _list_journal_tasks(client, journal_id=viewed_id)

        assert [task["id"] for task in payload["groups"]["due"]] == [mine]
        assert payload["groups"]["mentioned"] == []

    async def test_rows_are_ordered_soonest_first(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """The same ordering the endpoint promises, so the two agree."""
        viewed_id, _ = task_anchors
        far_id = await create_journal(journal_repository, title="Far", days_offset=30)
        near_id = await create_journal(journal_repository, title="Near", days_offset=2)
        far_task = await create_task(
            clean_database, creating_journal_id=viewed_id, due_journal_id=far_id
        )
        near_task = await create_task(
            clean_database, creating_journal_id=viewed_id, due_journal_id=near_id
        )

        async with authenticated_lifespan_client() as client:
            payload = await _list_journal_tasks(client, journal_id=viewed_id)

        assert [task["id"] for task in payload["groups"]["created"]] == [
            near_task,
            far_task,
        ]


async def _list_upcoming_tasks(client: Any, **arguments: Any) -> dict[str, Any]:
    response = await _raw_call(client, "list_upcoming_tasks", arguments)
    assert response.status_code == 200
    return extract_mcp_json_payload(response.text)


@pytest.mark.integration
class TestListUpcomingTasksTool:
    """The forward window, as an agent asked "what have I got on" sees it.

    The parity claim is the point of this class: an agent must be told the same
    thing the dashboard shows a browser, including — especially — which tasks
    are *missing* and where they went. An agent that reported "nothing due" to a
    user holding three cancelled-meeting commitments would be confidently wrong
    in a way the user could not check.
    """

    async def test_it_returns_the_window_the_total_and_the_tasks(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """The full read shape per row, so no follow-up call is needed."""
        creating_id, _ = task_anchors
        due_id = await create_journal(
            journal_repository, title="Permit Meeting", days_offset=2
        )
        task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="print the permit",
        )
        contact_id = await create_contact(clean_database, first_name="Sarah")
        await link_contact(clean_database, task_id=task_id, contact_id=contact_id)

        async with authenticated_lifespan_client() as client:
            payload = await _list_upcoming_tasks(client)

        assert payload["window"]["days_ahead"] == 7
        assert payload["total"] == 1
        (task,) = payload["tasks"]
        assert task["id"] == task_id
        assert task["text"] == "print the permit"
        assert task["due_journal"]["title"] == "Permit Meeting"
        assert task["due_journal"]["date"] is not None
        assert [contact["display_name"] for contact in task["contacts"]] == ["Sarah"]
        assert task["lapsed"] is False

    async def test_an_explicit_days_ahead_narrows_the_window(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """An agent may ask about today, tomorrow or the fortnight."""
        creating_id, _ = task_anchors
        near_id = await create_journal(journal_repository, title="Near", days_offset=1)
        far_id = await create_journal(journal_repository, title="Far", days_offset=5)
        near_task = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=near_id
        )
        await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=far_id
        )

        async with authenticated_lifespan_client() as client:
            payload = await _list_upcoming_tasks(client, days_ahead=2)

        assert [task["id"] for task in payload["tasks"]] == [near_task]
        assert payload["window"]["days_ahead"] == 2

    async def test_a_task_due_on_the_boundary_day_is_listed(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """Both ends inclusive, for an agent as for a browser."""
        creating_id, boundary_id = task_anchors
        task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=boundary_id,
        )

        async with authenticated_lifespan_client() as client:
            payload = await _list_upcoming_tasks(client)

        assert [task["id"] for task in payload["tasks"]] == [task_id]

    @pytest.mark.parametrize("status", [TaskStatus.DONE, TaskStatus.CANCELLED])
    async def test_a_finished_task_is_not_listed(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
        status: TaskStatus,
    ):
        """What is outstanding, not what exists."""
        creating_id, _ = task_anchors
        due_id = await create_journal(journal_repository, title="Soon", days_offset=2)
        await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=status,
        )

        async with authenticated_lifespan_client() as client:
            payload = await _list_upcoming_tasks(client)

        assert payload["tasks"] == []
        assert payload["total"] == 0

    async def test_a_task_whose_due_journal_was_cancelled_is_not_listed(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """**The fixture that makes the lapsed exclusion non-vacuous.**

        And the pair the tool's own description promises an agent: absent here,
        present with its reason on the journal — which is the answer to "what
        happened to that task", and the reason an agent can say something more
        useful than "it is gone".
        """
        creating_id, _ = task_anchors
        due_id = await create_journal(
            journal_repository, title="Cancelled meeting", days_offset=2
        )
        await mark_journal_as_event(
            clean_database, due_id, event_state=EventState.CANCELLED
        )
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )

        async with authenticated_lifespan_client() as client:
            upcoming = await _list_upcoming_tasks(client)
            on_its_journal = await _list_journal_tasks(client, journal_id=due_id)

        assert upcoming["tasks"] == []
        (listed,) = on_its_journal["groups"]["due"]
        assert listed["id"] == task_id
        assert listed["lapsed"] is True
        assert listed["lapse_reason"] == "due_journal_cancelled"

    async def test_another_users_task_is_never_listed(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """The acting user is the session's, and both users have one due."""
        creating_id, _ = task_anchors
        mine_journal = await create_journal(
            journal_repository, title="Mine", days_offset=2
        )
        mine = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=mine_journal,
        )
        theirs_journal = await create_journal(
            journal_repository, title="Theirs", days_offset=2, user_id=OTHER_USER_ID
        )
        await create_task(
            clean_database,
            creating_journal_id=theirs_journal,
            due_journal_id=theirs_journal,
            user_id=OTHER_USER_ID,
        )

        async with authenticated_lifespan_client() as client:
            payload = await _list_upcoming_tasks(client)

        assert [task["id"] for task in payload["tasks"]] == [mine]

    async def test_rows_are_ordered_soonest_first(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """The same order the endpoint promises, so the two surfaces agree."""
        creating_id, _ = task_anchors
        far_id = await create_journal(journal_repository, title="Friday", days_offset=5)
        near_id = await create_journal(
            journal_repository, title="Tomorrow", days_offset=1
        )
        far_task = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=far_id
        )
        near_task = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=near_id
        )

        async with authenticated_lifespan_client() as client:
            payload = await _list_upcoming_tasks(client)

        assert [task["id"] for task in payload["tasks"]] == [near_task, far_task]

    async def test_an_empty_window_still_names_its_dates(
        self, authenticated_lifespan_client
    ):
        """The answer an agent turns into "nothing due until Tuesday"."""
        async with authenticated_lifespan_client() as client:
            payload = await _list_upcoming_tasks(client)

        assert payload["tasks"] == []
        assert payload["total"] == 0
        assert payload["window"]["start_date"] is not None
        assert payload["window"]["end_date"] is not None

    @pytest.mark.parametrize("days_ahead", [-1, 91])
    async def test_an_out_of_range_window_is_refused(
        self, authenticated_lifespan_client, days_ahead: int
    ):
        """The bound that keeps this from becoming an every-task browser."""
        async with authenticated_lifespan_client() as client:
            response = await _raw_call(
                client, "list_upcoming_tasks", {"days_ahead": days_ahead}
            )

        assert '"isError":true' in response.text


async def _get_task_history(client: Any, **arguments: Any) -> dict[str, Any]:
    response = await _raw_call(client, "get_task_history", arguments)
    assert response.status_code == 200
    return extract_mcp_json_payload(response.text)


async def _seed_history(
    connection: AsyncConnection,
    task_id: int,
    field_name: str,
    *,
    old_value: str | None = None,
    new_value: str | None = None,
    changed_by: str = "ui",
    source: Provenance = Provenance.UI,
    minutes: int = 0,
    user_id: str | None = USER_ID,
) -> None:
    """One task history row, exactly as the projection consumer writes it."""
    from datetime import UTC, datetime, timedelta

    from app.core.history.adapters.sql.field_history_repository import (
        SqlFieldHistoryRepository,
    )
    from app.core.history.models import FieldHistoryEntry

    await SqlFieldHistoryRepository(connection).record_change(
        FieldHistoryEntry(
            entity_type="task",
            entity_id=task_id,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            changed_by=changed_by,
            source=source,
            event_id=f"evt-{task_id}-{field_name}",
            created_at=datetime(2024, 3, 1, 8, 0, tzinfo=UTC)
            + timedelta(minutes=minutes),
            user_id=user_id,
        )
    )


async def _seed_a_life(
    connection: AsyncConnection, task_id: int, *, user_id: str = USER_ID
) -> None:
    """A task's whole history — one row of each shape its six event types make.

    ``user_id`` is the task's **owner**, which is what the projection stamps
    from the event payload; ``changed_by`` is who acted, and the two differ
    whenever an assistant or a sync touches somebody's task.
    """
    for minutes, (field, old, new, source, actor) in enumerate(
        [
            ("__created__", None, "print the permit", Provenance.UI, "ui"),
            ("text", "print the permit", "print two permits", Provenance.MCP, "mcp"),
            ("status", "not_done", "done", Provenance.UI, "ui"),
            ("due_journal_id", "200", "300", Provenance.MCP, "mcp"),
            ("journal:200", None, "200", Provenance.MCP, "mcp"),
            ("contact:7", None, "7", Provenance.SYSTEM, "system"),
        ]
    ):
        await _seed_history(
            connection,
            task_id,
            field,
            old_value=old,
            new_value=new,
            source=source,
            changed_by=actor,
            minutes=minutes,
            user_id=user_id,
        )


@pytest.mark.integration
class TestGetTaskHistoryTool:
    """AI-agent parity for the read surface, asserted at this surface.

    The specification requires that history available in the UI be available
    through MCP, and this iteration has already found a real defect on exactly
    this seam — every task rejection reaching AI clients as "internal error",
    invisible to the service and endpoint tests alike. So the properties are
    re-asserted here rather than inferred from a shared service.
    """

    async def test_a_mixed_history_comes_back_most_recent_first(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        await _seed_a_life(clean_database, task_id)

        async with authenticated_lifespan_client() as client:
            payload = await _get_task_history(client, task_id=task_id)

        assert "error" not in payload
        assert payload["task_id"] == task_id
        assert payload["total_count"] == 6
        assert [entry["field_name"] for entry in payload["entries"]] == [
            "contact:7",
            "journal:200",
            "due_journal_id",
            "status",
            "text",
            "__created__",
        ]

    async def test_every_entry_names_its_provenance_and_its_actor(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The activity-history specification's *provenance is first-class*, in
        the form an agent can actually use: a value per entry, not an icon."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        await _seed_a_life(clean_database, task_id)

        async with authenticated_lifespan_client() as client:
            payload = await _get_task_history(client, task_id=task_id)

        by_field = {entry["field_name"]: entry for entry in payload["entries"]}
        assert by_field["__created__"]["source"] == "ui"
        assert by_field["__created__"]["changed_by"] == "ui"
        assert by_field["text"]["source"] == "mcp"
        assert by_field["contact:7"]["source"] == "system"
        assert all(entry["created_at"] is not None for entry in payload["entries"])
        assert by_field["text"]["old_value"] == "print the permit"
        assert by_field["text"]["new_value"] == "print two permits"

    async def test_it_pages_the_same_ordering_and_keeps_the_total(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        await _seed_a_life(clean_database, task_id)

        async with authenticated_lifespan_client() as client:
            first = await _get_task_history(client, task_id=task_id, page=1, limit=2)
            third = await _get_task_history(client, task_id=task_id, page=3, limit=2)

        assert first["page"] == 1
        assert first["limit"] == 2
        assert first["total_count"] == third["total_count"] == 6
        assert [entry["field_name"] for entry in first["entries"]] == [
            "contact:7",
            "journal:200",
        ]
        assert [entry["field_name"] for entry in third["entries"]] == [
            "text",
            "__created__",
        ]

    async def test_a_task_whose_events_have_not_projected_yet_answers_empty(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """An empty history is an ordinary answer, not a refusal.

        An agent told "not found" for a task it created a second ago would
        report to the user that their task does not exist.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )

        async with authenticated_lifespan_client() as client:
            payload = await _get_task_history(client, task_id=task_id)

        assert "error" not in payload
        assert payload["entries"] == []
        assert payload["total_count"] == 0

    async def test_a_deleted_tasks_history_is_still_readable(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The discriminator, through the tool.

        Note what this asserts about the tool's contract: ``get_task`` reports
        this id as not found while ``get_task_history`` answers, which is a
        difference an agent has to be told about — and the tool's description is.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        await _seed_a_life(clean_database, task_id)
        await _seed_history(clean_database, task_id, "__deleted__", minutes=10)

        async with authenticated_lifespan_client() as client:
            deleted = await _delete_task(client, task_id=task_id)
            payload = await _get_task_history(client, task_id=task_id)
            gone = await _get_task(client, task_id=task_id)

        assert deleted["deleted"] is True
        assert not await task_exists(clean_database, task_id)
        assert gone["error"] == "Not found"
        assert "error" not in payload
        fields = [entry["field_name"] for entry in payload["entries"]]
        assert fields[0] == "__deleted__"
        assert "__created__" in fields

    async def test_another_users_task_is_reported_as_not_found(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """Indistinguishable from an absent one, so a refusal cannot be used to
        discover which task ids exist."""
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
        await _seed_a_life(clean_database, foreign_task, user_id=OTHER_USER_ID)

        async with authenticated_lifespan_client() as client:
            foreign = await _get_task_history(client, task_id=foreign_task)
            absent = await _get_task_history(client, task_id=999_999)

        assert foreign["error"] == absent["error"] == "Not found"
        assert foreign["message"].replace(str(foreign_task), "X") == absent[
            "message"
        ].replace("999999", "X")

    async def test_another_users_deleted_task_is_refused_too(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """The hardest case to get right: no task row exists to scope against,
        so the only thing standing between the two users is the owner on the
        history rows themselves."""
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
        await _seed_history(
            clean_database, foreign_task, "__deleted__", user_id=OTHER_USER_ID
        )
        # Hard-deleted as ``delete_task`` would, but by SQL: the tool is
        # owner-scoped, so this test's user could not perform the deletion it
        # needs to have already happened.
        await clean_database.execute(
            sa_text("DELETE FROM tasks WHERE id = :task_id"), {"task_id": foreign_task}
        )

        async with authenticated_lifespan_client() as client:
            payload = await _get_task_history(client, task_id=foreign_task)

        assert payload["error"] == "Not found"

    async def test_a_page_number_beyond_the_int_range_is_refused(
        self, authenticated_lifespan_client
    ):
        """The bound that keeps an absurd page from reaching SQL as an OFFSET.

        Unbounded, ``(page - 1) * limit`` overflows PostgreSQL's bigint and the
        call comes back as a database error rather than as something an agent
        can act on. Raised by the pull request's automated review.
        """
        async with authenticated_lifespan_client() as client:
            response = await _raw_call(
                client,
                "get_task_history",
                {"task_id": 1, "page": 99999999999999999999999},
            )

        assert '"isError":true' in response.text

    async def test_an_over_large_page_is_refused_by_the_tool_schema(
        self, authenticated_lifespan_client
    ):
        """The cap keeps this from becoming a bulk export, and the schema is
        where an agent finds out rather than by burning a call."""
        async with authenticated_lifespan_client() as client:
            response = await _raw_call(
                client, "get_task_history", {"task_id": 1, "limit": 1000}
            )

        assert '"isError":true' in response.text
