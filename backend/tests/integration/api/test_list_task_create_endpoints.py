"""Integration tests for ``POST /api/task-lists/{list_id}/tasks``.

Creating a task on a list, through the REST surface: what reaches the client on
success, each refusal's status and JSON:API code, and that another user's list
reads as an absent one with nothing written. The rules themselves are proved
against the service in ``tests/integration/tasks/``; this file is about the
surface.
"""

from datetime import date
from typing import Any

import pytest
from core_shared.models.history import Provenance
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.common.identifiers import INT32_MAX
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from tests.integration.tasks.task_seeding import (
    COUNT_TASKS,
    OTHER_USER_ID,
    USER_ID,
    count,
    create_contact,
    create_journal,
    create_list_task,
    linked_contact_ids,
    seed_task_list_id,
    task_events,
)

pytestmark = pytest.mark.integration

# Far enough either side of the real clock that no timezone moves them.
FUTURE = date(2099, 12, 31)
PAST = date(2000, 1, 1)


def _body(**attributes: object) -> dict[str, Any]:
    return {
        "data": {
            "type": "tasks",
            "attributes": {"text": "pack the tent", **attributes},
        }
    }


def _error(response: Response) -> dict[str, Any]:
    (error,) = response.json()["errors"]
    first: dict[str, Any] = error
    return first


async def _create(
    client: AsyncClient, list_id: int | str, **attributes: object
) -> Response:
    return await client.post(
        f"/api/task-lists/{list_id}/tasks", json=_body(**attributes)
    )


class TestCreatingATaskOnAList:
    async def test_answers_201_with_the_task_on_the_list(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id = await seed_task_list_id(async_connection)

        response = await _create(authenticated_client, list_id, due_date="2099-12-31")

        assert response.status_code == 201
        data = response.json()["data"]
        assert data["type"] == "tasks"
        attributes = data["attributes"]
        assert attributes["text"] == "pack the tent"
        assert attributes["status"] == "not_done"
        assert attributes["task_list_id"] == list_id
        assert attributes["due_date"] == "2099-12-31"
        assert attributes["creating_journal_id"] is None
        assert attributes["due_journal_id"] is None
        assert attributes["intermediate_journal_ids"] == []
        assert data["links"]["self"].endswith(f"/api/tasks/{data['id']}")

    async def test_an_undated_task_has_no_due_date(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id = await seed_task_list_id(async_connection)

        response = await _create(authenticated_client, list_id)

        assert response.status_code == 201
        assert response.json()["data"]["attributes"]["due_date"] is None

    async def test_joins_the_bottom_of_the_list(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id = await seed_task_list_id(async_connection)
        await create_list_task(async_connection, task_list_id=list_id, position=0)

        response = await _create(authenticated_client, list_id)

        assert response.status_code == 201
        task_id = int(response.json()["data"]["id"])
        read = await authenticated_client.get(f"/api/tasks/{task_id}")
        assert read.status_code == 200
        assert read.json()["data"]["attributes"]["task_list_id"] == list_id

    async def test_links_the_named_contacts(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id = await seed_task_list_id(async_connection)
        contact_id = await create_contact(async_connection)

        response = await _create(
            authenticated_client, list_id, contact_ids=[contact_id]
        )

        assert response.status_code == 201
        task_id = int(response.json()["data"]["id"])
        assert await linked_contact_ids(async_connection, task_id) == [contact_id]

    async def test_the_create_is_attributed_to_the_ui(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id = await seed_task_list_id(async_connection)

        response = await _create(authenticated_client, list_id)

        assert response.status_code == 201
        (event,) = await task_events(async_connection)
        assert event.event_type == "TaskCreated"
        assert event.payload["task_list_id"] == list_id
        assert event.payload["source"] == Provenance.UI.value
        assert event.payload["changed_by"] == "ui"


class TestRefusals:
    async def test_a_past_due_date_is_refused_naming_both_days(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id = await seed_task_list_id(async_connection)

        response = await _create(
            authenticated_client, list_id, due_date=PAST.isoformat()
        )

        assert response.status_code == 400
        error = _error(response)
        assert error["code"] == "TASK_DUE_DATE_IN_PAST"
        assert PAST.isoformat() in error["detail"]
        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 0

    @pytest.mark.parametrize(
        "attributes",
        [
            pytest.param({"creating_journal_id": 1}, id="a creating journal"),
            pytest.param({"position": 0}, id="a position"),
            pytest.param({"task_list_id": 1}, id="a list in the body"),
            pytest.param({"due_date": 20991231}, id="a numeric due date"),
            pytest.param({"due_date": "31/12/2099"}, id="a malformed due date"),
        ],
    )
    async def test_a_body_this_create_does_not_take_is_a_validation_error(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        attributes: dict[str, object],
    ) -> None:
        list_id = await seed_task_list_id(async_connection)

        response = await _create(authenticated_client, list_id, **attributes)

        assert response.status_code == 400
        assert _error(response)["code"] == "VALIDATION_ERROR"
        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 0

    async def test_another_resource_type_is_a_validation_error(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id = await seed_task_list_id(async_connection)
        body = _body()
        body["data"]["type"] = "task-lists"

        response = await authenticated_client.post(
            f"/api/task-lists/{list_id}/tasks", json=body
        )

        assert response.status_code == 400
        assert _error(response)["code"] == "VALIDATION_ERROR"

    async def test_blank_text_names_the_field(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id = await seed_task_list_id(async_connection)

        response = await authenticated_client.post(
            f"/api/task-lists/{list_id}/tasks",
            json={"data": {"type": "tasks", "attributes": {"text": "   "}}},
        )

        assert response.status_code == 400
        error = _error(response)
        assert error["code"] == "TASK_VALIDATION_ERROR"
        assert error["meta"] == {"field": "text"}

    @pytest.mark.parametrize("list_id", ["0", str(INT32_MAX + 1), "abc"])
    async def test_an_out_of_range_list_id_is_a_bad_request(
        self, authenticated_client: AsyncClient, list_id: str
    ) -> None:
        response = await _create(authenticated_client, list_id)

        assert response.status_code == 400

    async def test_an_unknown_list_is_not_found(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        response = await _create(authenticated_client, 999_999)

        assert response.status_code == 404
        assert _error(response)["code"] == "TASK_LIST_NOT_FOUND"
        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 0

    async def test_an_unknown_contact_is_not_found(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id = await seed_task_list_id(async_connection)

        response = await _create(authenticated_client, list_id, contact_ids=[999_999])

        assert response.status_code == 404
        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 0

    async def test_an_archived_list_is_a_conflict_naming_the_way_out(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id = await seed_task_list_id(async_connection, archived=True)

        response = await _create(authenticated_client, list_id)

        assert response.status_code == 409
        error = _error(response)
        assert error["code"] == "TASK_LIST_ARCHIVED"
        assert "unarchive" in error["detail"].lower()
        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 0
        assert await task_events(async_connection) == []


class TestCreatingDueInAJournal:
    async def test_answers_201_with_the_task_due_in_the_journal(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        list_id = await seed_task_list_id(async_connection)
        journal_id = await create_journal(journal_repository, days_offset=5)

        response = await _create(
            authenticated_client, list_id, due_journal_id=journal_id
        )

        assert response.status_code == 201
        attributes = response.json()["data"]["attributes"]
        assert attributes["task_list_id"] == list_id
        assert attributes["due_journal_id"] == journal_id
        assert attributes["creating_journal_id"] is None
        assert attributes["due_date"] is None
        task_id = int(response.json()["data"]["id"])
        (event,) = await task_events(async_connection, task_id=task_id)
        assert event.payload["due_journal_id"] == journal_id
        assert event.payload["source"] == Provenance.UI.value

    async def test_a_journal_that_is_not_in_the_future_is_refused_naming_both_days(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        list_id = await seed_task_list_id(async_connection)
        journal_id = await create_journal(journal_repository, days_offset=-2)

        response = await _create(
            authenticated_client, list_id, due_journal_id=journal_id
        )

        assert response.status_code == 400
        error = _error(response)
        assert error["code"] == "TASK_DUE_JOURNAL_NOT_FUTURE"
        assert "today" in error["detail"].lower()
        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 0
        assert await task_events(async_connection) == []

    async def test_a_due_date_beside_it_is_refused_naming_the_date(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        list_id = await seed_task_list_id(async_connection)
        journal_id = await create_journal(journal_repository, days_offset=5)

        response = await _create(
            authenticated_client,
            list_id,
            due_date=FUTURE.isoformat(),
            due_journal_id=journal_id,
        )

        assert response.status_code == 400
        error = _error(response)
        assert error["code"] == "TASK_VALIDATION_ERROR"
        assert error["meta"] == {"field": "due_date"}
        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 0

    async def test_an_unknown_journal_is_not_found_as_the_due_anchor(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id = await seed_task_list_id(async_connection)

        response = await _create(authenticated_client, list_id, due_journal_id=999_999)

        assert response.status_code == 404
        error = _error(response)
        assert error["code"] == "TASK_ANCHOR_JOURNAL_NOT_FOUND"
        assert error["meta"] == {"anchor": "due"}
        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 0

    @pytest.mark.parametrize("journal_id", [0, INT32_MAX + 1, "abc"], ids=repr)
    async def test_an_out_of_range_journal_id_is_a_validation_error(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_id: object,
    ) -> None:
        list_id = await seed_task_list_id(async_connection)

        response = await _create(
            authenticated_client, list_id, due_journal_id=journal_id
        )

        assert response.status_code == 400
        assert _error(response)["code"] == "VALIDATION_ERROR"

    async def test_an_archived_list_is_reported_before_a_past_journal(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        list_id = await seed_task_list_id(async_connection, archived=True)
        journal_id = await create_journal(journal_repository, days_offset=-2)

        response = await _create(
            authenticated_client, list_id, due_journal_id=journal_id
        )

        assert response.status_code == 409
        assert _error(response)["code"] == "TASK_LIST_ARCHIVED"


def _retarget_body(due_journal_id: int, **attributes: object) -> dict[str, object]:
    return {
        "data": {
            "type": "task-retarget",
            "attributes": {"due_journal_id": due_journal_id, **attributes},
        }
    }


class TestRetargetingAListTaskNotDueInAJournal:
    """A list task with no due journal is given one; a due date is replaced."""

    @pytest.mark.parametrize(
        "attributes", [{}, {"due_date": "2099-12-31"}], ids=["undated", "due-date"]
    )
    async def test_gains_the_journal(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        attributes: dict[str, object],
    ) -> None:
        list_id = await seed_task_list_id(async_connection)
        later_id = await create_journal(journal_repository, days_offset=9)
        created = await _create(authenticated_client, list_id, **attributes)
        task_id = int(created.json()["data"]["id"])

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/retarget", json=_retarget_body(later_id)
        )

        assert response.status_code == 200
        moved = response.json()["data"]["attributes"]
        assert (moved["due_journal_id"], moved["due_date"], moved["status"]) == (
            later_id,
            None,
            "not_done",
        )
        assert moved["intermediate_journal_ids"] == []


class TestRetargetingAClosedListTaskDueInAJournal:
    """A list task's due journal is a plain date: a closed one moves and stays closed."""

    @pytest.mark.parametrize("status", ["done", "cancelled"])
    @pytest.mark.parametrize("acknowledge_reopen", [False, True])
    async def test_moves_and_keeps_its_status(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        status: str,
        acknowledge_reopen: bool,
    ) -> None:
        list_id = await seed_task_list_id(async_connection)
        due_id = await create_journal(journal_repository, days_offset=5)
        later_id = await create_journal(journal_repository, days_offset=9)
        created = await _create(authenticated_client, list_id, due_journal_id=due_id)
        task_id = int(created.json()["data"]["id"])
        closed = await authenticated_client.patch(
            f"/api/tasks/{task_id}",
            json={
                "data": {
                    "type": "tasks",
                    "id": str(task_id),
                    "attributes": {"status": status},
                }
            },
        )
        assert closed.status_code == 200

        response = await authenticated_client.post(
            f"/api/tasks/{task_id}/retarget",
            json=_retarget_body(later_id, acknowledge_reopen=acknowledge_reopen),
        )

        assert response.status_code == 200
        moved = response.json()["data"]["attributes"]
        assert (moved["status"], moved["due_journal_id"]) == (status, later_id)
        assert moved["intermediate_journal_ids"] == [due_id]
        last = (await task_events(async_connection, task_id=task_id))[-1]
        assert last.event_type == "TaskUpdated"
        assert last.payload["changed_fields"] == {"due_journal_id": [due_id, later_id]}


class TestAnotherUsersJournal:
    async def test_reads_as_an_absent_one_and_nothing_is_written(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Byte-identical to a journal that does not exist, so nothing is probed."""
        list_id = await seed_task_list_id(async_connection)
        foreign_journal_id = await create_journal(
            journal_repository, days_offset=5, user_id=OTHER_USER_ID
        )
        absent_journal_id = foreign_journal_id + 1_000_000

        foreign = await _create(
            authenticated_client, list_id, due_journal_id=foreign_journal_id
        )
        absent = await _create(
            authenticated_client, list_id, due_journal_id=absent_journal_id
        )

        assert foreign.status_code == absent.status_code == 404
        assert _error(foreign)["code"] == _error(absent)["code"]
        assert _error(foreign)["meta"] == _error(absent)["meta"] == {"anchor": "due"}
        assert _error(foreign)["detail"] == _error(absent)["detail"].replace(
            str(absent_journal_id), str(foreign_journal_id)
        )
        for owner in (USER_ID, OTHER_USER_ID):
            assert await count(async_connection, COUNT_TASKS, {"user_id": owner}) == 0
        assert await task_events(async_connection) == []


class TestAnotherUsersList:
    async def test_reads_as_an_absent_one_and_nothing_is_written(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        foreign_list_id = await seed_task_list_id(
            async_connection, user_id=OTHER_USER_ID
        )

        foreign = await _create(authenticated_client, foreign_list_id)
        absent = await _create(authenticated_client, 999_999)

        assert foreign.status_code == absent.status_code == 404
        assert (
            _error(foreign)["code"] == _error(absent)["code"] == "TASK_LIST_NOT_FOUND"
        )
        assert _error(foreign)["detail"] == (
            f"Task list with ID {foreign_list_id} not found"
        )
        for owner in (USER_ID, OTHER_USER_ID):
            assert await count(async_connection, COUNT_TASKS, {"user_id": owner}) == 0
        assert await task_events(async_connection) == []
