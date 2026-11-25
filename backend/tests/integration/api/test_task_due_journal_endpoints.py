"""Integration tests for a task's due journal on ``PATCH /api/tasks/{task_id}``.

Through the REST surface: what reaches the client when a due journal is set,
changed or cleared — on a list task as a plain edit, on a journal-only task as
a retarget — each refusal's status and JSON:API code with nothing written, and
that another user's task or journal reads as an absent one. The rules and the
races are proved against the service in
``tests/integration/tasks/test_task_service_due_journal_integration.py``; this
file is about the surface.
"""

from datetime import date
from typing import Any

import pytest
from core_shared.models.tasks import TaskStatus
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.common.identifiers import INT32_MAX
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from tests.integration.tasks.task_seeding import (
    OTHER_USER_ID,
    create_journal,
    create_list_task,
    create_task,
    intermediate_journal_ids,
    seed_task_list_id,
    task_events,
)

pytestmark = pytest.mark.integration


def _body(task_id: int, **attributes: object) -> dict[str, object]:
    return {"data": {"type": "tasks", "id": str(task_id), "attributes": attributes}}


async def _patch(client: AsyncClient, task_id: int, **attributes: object) -> Response:
    return await client.patch(
        f"/api/tasks/{task_id}", json=_body(task_id, **attributes)
    )


def _error(response: Response) -> dict[str, Any]:
    (error,) = response.json()["errors"]
    first: dict[str, Any] = error
    return first


async def _stored(conn: AsyncConnection, task_id: int) -> Any:
    return (
        await conn.execute(
            text("SELECT due_journal_id, due_date, status FROM tasks WHERE id = :id"),
            {"id": task_id},
        )
    ).one()


async def _journals(repo: SqlJournalRepository) -> tuple[int, int]:
    """Two future journals of the acting user's."""
    first = await create_journal(repo, title="Beach weekend", days_offset=7)
    second = await create_journal(repo, title="Hike", days_offset=14)
    return first, second


async def _assert_untouched(
    conn: AsyncConnection, task_id: int, due_journal_id: int | None
) -> None:
    assert (await _stored(conn, task_id)).due_journal_id == due_journal_id
    assert await intermediate_journal_ids(conn, task_id) == []
    assert await task_events(conn, task_id=task_id) == []


class TestAListTask:
    @pytest.mark.parametrize("change", ["set", "changed", "cleared"])
    async def test_answers_200_with_the_journal_and_its_trail(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        change: str,
    ) -> None:
        old_id, new_id = await _journals(journal_repository)
        linked = ["TaskJournalLinked", "TaskUpdated"]
        cases: dict[str, tuple[int | None, int | None, list[str]]] = {
            "set": (None, new_id, ["TaskUpdated"]),
            "changed": (old_id, new_id, linked),
            "cleared": (old_id, None, linked),
        }
        before, sent, published = cases[change]
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, due_journal_id=before
        )

        response = await _patch(authenticated_client, task_id, due_journal_id=sent)

        assert response.status_code == 200
        attributes = response.json()["data"]["attributes"]
        assert attributes["due_journal_id"] == sent
        assert attributes["intermediate_journal_ids"] == (
            [] if before is None else [before]
        )
        assert (await _stored(async_connection, task_id)).due_journal_id == sent
        events = await task_events(async_connection, task_id=task_id)
        assert [e.event_type for e in events] == published
        event = events[-1]
        assert event.payload["changed_fields"] == {"due_journal_id": [before, sent]}
        assert (event.payload["source"], event.payload["changed_by"]) == ("ui", "ui")

    @pytest.mark.parametrize("status", [TaskStatus.DONE, TaskStatus.CANCELLED])
    async def test_a_closed_task_keeps_its_status(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        status: TaskStatus,
    ) -> None:
        old_id, new_id = await _journals(journal_repository)
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(
            async_connection,
            task_list_id=list_id,
            due_journal_id=old_id,
            status=status,
        )

        response = await _patch(authenticated_client, task_id, due_journal_id=new_id)

        assert response.status_code == 200
        assert response.json()["data"]["attributes"]["status"] == status.value
        assert (await _stored(async_connection, task_id)).status == status.value

    async def test_resending_its_journal_is_a_quiet_200(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        journal_id, _ = await _journals(journal_repository)
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, due_journal_id=journal_id
        )

        response = await _patch(
            authenticated_client, task_id, due_journal_id=journal_id
        )

        assert response.status_code == 200
        assert await task_events(async_connection, task_id=task_id) == []

    async def test_a_journal_and_a_flag_are_one_update(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        journal_id, _ = await _journals(journal_repository)
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(async_connection, task_list_id=list_id)

        response = await _patch(
            authenticated_client, task_id, due_journal_id=journal_id, flagged=True
        )

        assert response.status_code == 200
        (event,) = await task_events(async_connection, task_id=task_id)
        assert event.payload["changed_fields"] == {
            "flagged": [False, True],
            "due_journal_id": [None, journal_id],
        }

    async def test_a_status_and_a_journal_are_both_applied(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """A list task's status is its own, so the two do not clash."""
        old_id, new_id = await _journals(journal_repository)
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, due_journal_id=old_id
        )

        response = await _patch(
            authenticated_client, task_id, due_journal_id=new_id, status="done"
        )

        assert response.status_code == 200
        row = await _stored(async_connection, task_id)
        assert (row.due_journal_id, row.status) == (new_id, "done")

    async def test_a_journal_replaces_a_due_date(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        journal_id, _ = await _journals(journal_repository)
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(
            async_connection, task_list_id=list_id, due_date=date(2099, 12, 31)
        )

        response = await _patch(
            authenticated_client, task_id, due_journal_id=journal_id
        )

        assert response.status_code == 200
        attributes = response.json()["data"]["attributes"]
        assert (attributes["due_journal_id"], attributes["due_date"]) == (
            journal_id,
            None,
        )


class TestAJournalOnlyTask:
    async def test_a_new_journal_retargets_it(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ) -> None:
        creating_id, due_id = task_anchors
        new_id = await create_journal(journal_repository, days_offset=21)
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus.CANCELLED,
        )

        response = await _patch(authenticated_client, task_id, due_journal_id=new_id)

        assert response.status_code == 200
        attributes = response.json()["data"]["attributes"]
        assert (attributes["due_journal_id"], attributes["status"]) == (
            new_id,
            "not_done",
        )
        assert attributes["intermediate_journal_ids"] == [due_id]
        assert [
            event.event_type
            for event in await task_events(async_connection, task_id=task_id)
        ] == ["TaskJournalLinked", "TaskDueJournalRetargeted"]

    @pytest.mark.parametrize(
        "acknowledgement",
        [{"acknowledge_reopen": True}, {"status": "not_done"}],
        ids=["acknowledge-reopen", "status-not-done"],
    )
    async def test_a_done_one_is_reopened_when_the_body_asks(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
        acknowledgement: dict[str, object],
    ) -> None:
        creating_id, due_id = task_anchors
        new_id = await create_journal(journal_repository, days_offset=21)
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus.DONE,
        )

        response = await _patch(
            authenticated_client, task_id, due_journal_id=new_id, **acknowledgement
        )

        assert response.status_code == 200
        assert (await _stored(async_connection, task_id)).status == "not_done"

    async def test_a_done_one_without_the_acknowledgement_is_a_409(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ) -> None:
        creating_id, due_id = task_anchors
        new_id = await create_journal(journal_repository, days_offset=21)
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=TaskStatus.DONE,
        )

        response = await _patch(authenticated_client, task_id, due_journal_id=new_id)

        assert response.status_code == 409
        assert _error(response)["code"] == "TASK_REOPEN_NOT_ACKNOWLEDGED"
        assert (await _stored(async_connection, task_id)).status == "done"
        await _assert_untouched(async_connection, task_id, due_id)

    @pytest.mark.parametrize(
        ("attributes", "field"),
        [
            ({"status": "done"}, "status"),
            ({"status": "cancelled"}, "status"),
            ({"due_journal_id": None}, "due_journal_id"),
        ],
        ids=["beside-done", "beside-cancelled", "cleared"],
    )
    async def test_a_body_with_two_answers_is_a_400(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
        attributes: dict[str, object],
        field: str,
    ) -> None:
        creating_id, due_id = task_anchors
        new_id = await create_journal(journal_repository, days_offset=21)
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        body = {"due_journal_id": new_id, **attributes}

        response = await _patch(authenticated_client, task_id, **body)

        assert response.status_code == 400
        error = _error(response)
        assert error["code"] == "TASK_VALIDATION_ERROR"
        assert error["meta"]["field"] == field
        await _assert_untouched(async_connection, task_id, due_id)


class TestRefusals:
    async def test_a_journal_that_is_not_future_is_refused(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        past_id = await create_journal(journal_repository, days_offset=-3)
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(async_connection, task_list_id=list_id)

        response = await _patch(authenticated_client, task_id, due_journal_id=past_id)

        assert response.status_code == 400
        assert _error(response)["code"] == "TASK_DUE_JOURNAL_NOT_FUTURE"
        await _assert_untouched(async_connection, task_id, None)

    async def test_a_date_and_a_journal_together_are_refused(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        journal_id, _ = await _journals(journal_repository)
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(async_connection, task_list_id=list_id)

        response = await _patch(
            authenticated_client,
            task_id,
            due_journal_id=journal_id,
            due_date="2099-12-31",
        )

        assert response.status_code == 400
        error = _error(response)
        assert (error["code"], error["meta"]["field"]) == (
            "TASK_VALIDATION_ERROR",
            "due_date",
        )
        await _assert_untouched(async_connection, task_id, None)

    @pytest.mark.parametrize(
        "attributes",
        [
            {"due_journal_id": "7"},
            {"due_journal_id": 7.5},
            {"due_journal_id": 0},
            {"due_journal_id": INT32_MAX + 1},
            {"due_journal_id": 7, "acknowledge_reopen": "yes"},
        ],
        ids=["string", "float", "zero", "beyond-int32", "non-boolean-ack"],
    )
    async def test_a_malformed_body_is_a_validation_error(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        attributes: dict[str, object],
    ) -> None:
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(async_connection, task_list_id=list_id)

        response = await _patch(authenticated_client, task_id, **attributes)

        assert response.status_code == 400
        assert _error(response)["code"] == "VALIDATION_ERROR"
        await _assert_untouched(async_connection, task_id, None)


class TestAnotherUsersRows:
    async def test_their_journal_reads_as_an_absent_one(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Byte-identical once the ids are stripped, so no journal can be probed."""
        theirs = await create_journal(
            journal_repository, days_offset=7, user_id=OTHER_USER_ID
        )
        list_id = await seed_task_list_id(async_connection)
        task_id = await create_list_task(async_connection, task_list_id=list_id)

        foreign = await _patch(authenticated_client, task_id, due_journal_id=theirs)
        absent = await _patch(authenticated_client, task_id, due_journal_id=999_999)

        assert foreign.status_code == absent.status_code == 404
        foreign_error, absent_error = _error(foreign), _error(absent)
        assert (
            foreign_error["code"]
            == absent_error["code"]
            == ("TASK_ANCHOR_JOURNAL_NOT_FOUND")
        )
        assert foreign_error["meta"] == absent_error["meta"] == {"anchor": "due"}
        assert foreign_error["detail"].replace(str(theirs), "X") == absent_error[
            "detail"
        ].replace("999999", "X")
        await _assert_untouched(async_connection, task_id, None)

    async def test_their_task_reads_as_an_absent_one_and_is_left_alone(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        journal_id, _ = await _journals(journal_repository)
        foreign_list = await seed_task_list_id(async_connection, user_id=OTHER_USER_ID)
        foreign_task = await create_list_task(
            async_connection, task_list_id=foreign_list, user_id=OTHER_USER_ID
        )

        foreign = await _patch(
            authenticated_client, foreign_task, due_journal_id=journal_id
        )
        absent = await _patch(authenticated_client, 999_999, due_journal_id=journal_id)

        assert foreign.status_code == absent.status_code == 404
        assert _error(foreign)["code"] == _error(absent)["code"] == "TASK_NOT_FOUND"
        assert _error(foreign)["detail"].replace(str(foreign_task), "X") == _error(
            absent
        )["detail"].replace("999999", "X")
        await _assert_untouched(async_connection, foreign_task, None)
