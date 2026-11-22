"""Integration tests: every task write route refuses a task on an archived list.

An archived list is read-only until unarchived, and so are its tasks. Each
write route answers **409** ``TASK_LIST_ARCHIVED`` — the code the list's own
routes already answer — and leaves the task as it was; reads stay open, because
an archived list and its tasks remain viewable. Another user's task is still a
plain 404: the archived state of somebody else's list is not something this
caller may learn.

The rule itself, its lock and the rollback of a refused delete are proved in
``tests/integration/tasks/test_task_service_archived_list_integration.py``; this
file is about what reaches the client. The task is seeded as a row on an
already-archived list, which no product write can produce directly.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from tests.integration.tasks.task_seeding import (
    ARCHIVED_AT,
    OTHER_USER_ID,
    ArchivedListTask,
    create_list_task,
    seed_archived_list_task,
    seed_task_list,
    stored_status,
    task_state,
)

pytestmark = pytest.mark.integration

Seeded = ArchivedListTask


@pytest_asyncio.fixture
async def seeded(
    async_connection: AsyncConnection,
    journal_repository: SqlJournalRepository,
    task_anchors: tuple[int, int],
) -> ArchivedListTask:
    return await seed_archived_list_task(
        async_connection, journal_repository, task_anchors
    )


async def _snapshot(conn: AsyncConnection, s: Seeded) -> tuple[object, ...]:
    return await task_state(conn, s.task_id)


def _assert_archived(response: Response) -> None:
    assert response.status_code == 409
    (error,) = response.json()["errors"]
    assert error["code"] == "TASK_LIST_ARCHIVED"
    assert "unarchive" in str(error["detail"]).lower()


def _task_body(task_id: int, **attributes: object) -> dict[str, object]:
    return {"data": {"type": "tasks", "id": str(task_id), "attributes": attributes}}


class TestEveryWriteRouteAnswers409:
    async def test_patching_the_status(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        seeded: Seeded,
    ) -> None:
        before = await _snapshot(async_connection, seeded)

        response = await authenticated_client.patch(
            f"/api/tasks/{seeded.task_id}",
            json=_task_body(seeded.task_id, status="done"),
        )

        _assert_archived(response)
        assert await _snapshot(async_connection, seeded) == before

    async def test_patching_the_text(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        seeded: Seeded,
    ) -> None:
        before = await _snapshot(async_connection, seeded)

        response = await authenticated_client.patch(
            f"/api/tasks/{seeded.task_id}",
            json=_task_body(seeded.task_id, text="pack the spare head torch"),
        )

        _assert_archived(response)
        assert await _snapshot(async_connection, seeded) == before

    async def test_reordering_even_where_it_already_is(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        seeded: Seeded,
    ) -> None:
        """The task is alone on its list, so the move to the top changes nothing
        — and is refused anyway: read-only means not writable."""
        before = await _snapshot(async_connection, seeded)

        response = await authenticated_client.post(
            f"/api/tasks/{seeded.task_id}/reorder",
            json={
                "data": {"type": "task-reorders", "attributes": {"after_task_id": None}}
            },
        )

        _assert_archived(response)
        assert await _snapshot(async_connection, seeded) == before

    @pytest.mark.parametrize(
        "attributes",
        [{"flagged": True}, {"icon": "tent"}, {"icon": None}],
        ids=["flag", "icon", "clear-icon-it-does-not-have"],
    )
    async def test_patching_the_flag_or_icon(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        seeded: Seeded,
        attributes: dict[str, object],
    ) -> None:
        """Including a no-op: read-only means not writable."""
        before = await _snapshot(async_connection, seeded)

        response = await authenticated_client.patch(
            f"/api/tasks/{seeded.task_id}",
            json=_task_body(seeded.task_id, **attributes),
        )

        _assert_archived(response)
        assert await _snapshot(async_connection, seeded) == before

    async def test_retargeting(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        seeded: Seeded,
    ) -> None:
        before = await _snapshot(async_connection, seeded)

        response = await authenticated_client.post(
            f"/api/tasks/{seeded.task_id}/retarget",
            json={
                "data": {
                    "type": "task-retarget",
                    "attributes": {"due_journal_id": seeded.later_journal_id},
                }
            },
        )

        _assert_archived(response)
        assert await _snapshot(async_connection, seeded) == before

    async def test_deleting(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        seeded: Seeded,
    ) -> None:
        before = await _snapshot(async_connection, seeded)

        response = await authenticated_client.delete(f"/api/tasks/{seeded.task_id}")

        _assert_archived(response)
        assert await _snapshot(async_connection, seeded) == before

    async def test_linking_a_contact(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        seeded: Seeded,
    ) -> None:
        before = await _snapshot(async_connection, seeded)

        response = await authenticated_client.post(
            f"/api/tasks/{seeded.task_id}/relationships/contacts",
            json={"data": {"type": "contacts", "id": str(seeded.unlinked_contact_id)}},
        )

        _assert_archived(response)
        assert await _snapshot(async_connection, seeded) == before

    async def test_unlinking_a_contact(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        seeded: Seeded,
    ) -> None:
        before = await _snapshot(async_connection, seeded)

        response = await authenticated_client.delete(
            f"/api/tasks/{seeded.task_id}/relationships/contacts/{seeded.contact_id}"
        )

        _assert_archived(response)
        assert await _snapshot(async_connection, seeded) == before

    async def test_attaching_an_intermediate_journal(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        seeded: Seeded,
    ) -> None:
        before = await _snapshot(async_connection, seeded)

        response = await authenticated_client.post(
            f"/api/tasks/{seeded.task_id}/relationships/intermediate-journals",
            json={"data": {"type": "journals", "id": str(seeded.unlinked_journal_id)}},
        )

        _assert_archived(response)
        assert await _snapshot(async_connection, seeded) == before

    async def test_detaching_an_intermediate_journal(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        seeded: Seeded,
    ) -> None:
        before = await _snapshot(async_connection, seeded)

        response = await authenticated_client.delete(
            f"/api/tasks/{seeded.task_id}/relationships/intermediate-journals/"
            f"{seeded.intermediate_journal_id}"
        )

        _assert_archived(response)
        assert await _snapshot(async_connection, seeded) == before


class TestReadsAndOwnership:
    async def test_the_task_can_still_be_read(
        self, authenticated_client: AsyncClient, seeded: Seeded
    ) -> None:
        """Archived is read-only, not hidden: the task stays openable."""
        response = await authenticated_client.get(f"/api/tasks/{seeded.task_id}")

        assert response.status_code == 200
        assert response.json()["data"]["id"] == str(seeded.task_id)

    async def test_another_users_task_on_an_archived_list_is_not_found(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        """A 404, not a 409: whose list is archived is not this caller's to learn."""
        theirs_list = await seed_task_list(
            async_connection, "Theirs", user_id=OTHER_USER_ID, archived_at=ARCHIVED_AT
        )
        assert theirs_list.id is not None
        theirs = await create_list_task(
            async_connection, task_list_id=theirs_list.id, user_id=OTHER_USER_ID
        )

        response = await authenticated_client.patch(
            f"/api/tasks/{theirs}", json=_task_body(theirs, status="done")
        )

        assert response.status_code == 404
        (error,) = response.json()["errors"]
        assert error["code"] == "TASK_NOT_FOUND"
        assert await stored_status(async_connection, theirs) == "not_done"
