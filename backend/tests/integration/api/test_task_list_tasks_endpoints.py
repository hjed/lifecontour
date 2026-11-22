"""Integration tests for reading a list's tasks over REST.

``GET /api/task-lists/{list_id}/tasks`` answers the list's open tasks in the
user's manual order, unpaged; ``GET /api/task-lists/{list_id}/tasks/completed``
answers its done and cancelled tasks most recently closed first, a page at a
time. Both refuse another user's list exactly as a missing one.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from core_shared.models.tasks import TaskIcon, TaskStatus
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.common.identifiers import INT32_MAX
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from tests.integration.tasks.task_seeding import (
    OTHER_USER_ID,
    backdate_closed_at,
    create_contact,
    create_journal,
    create_list_task,
    link_contact,
    seed_task_list_id,
)

pytestmark = pytest.mark.integration

# Long past in every timezone, so overdue whatever the user's zone.
LONG_PAST = date(2000, 1, 1)
CLOSED_BASE = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _open_path(list_id: int | str) -> str:
    return f"/api/task-lists/{list_id}/tasks"


def _completed_path(list_id: int | str) -> str:
    return f"/api/task-lists/{list_id}/tasks/completed"


def _ids(response: Response) -> list[int]:
    return [int(row["id"]) for row in response.json()["data"]]


def _error(response: Response) -> dict[str, Any]:
    (error,) = response.json()["errors"]
    first: dict[str, Any] = error
    return first


async def _closed(
    conn: AsyncConnection,
    list_id: int,
    status: TaskStatus,
    *,
    minutes: int,
    text: str = "closed",
) -> int:
    """A closed task on the list, closed ``minutes`` after a fixed instant."""
    task_id = await create_list_task(
        conn, task_list_id=list_id, status=status, text=text
    )
    await backdate_closed_at(conn, task_id, CLOSED_BASE + timedelta(minutes=minutes))
    return task_id


class TestOpenTasks:
    async def test_answers_the_open_tasks_in_manual_order(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        """Ordered by position, a tie broken by id; closed tasks are absent."""
        list_id = await seed_task_list_id(async_connection)
        third = await create_list_task(
            async_connection, task_list_id=list_id, position=5
        )
        first = await create_list_task(
            async_connection, task_list_id=list_id, position=1
        )
        tied = await create_list_task(
            async_connection, task_list_id=list_id, position=1
        )
        await _closed(async_connection, list_id, TaskStatus.DONE, minutes=1)
        await _closed(async_connection, list_id, TaskStatus.CANCELLED, minutes=2)

        response = await authenticated_client.get(_open_path(list_id))

        assert response.status_code == 200
        assert _ids(response) == [first, tied, third]
        assert response.json()["meta"] == {"total": 3}

    async def test_an_empty_list_answers_no_tasks(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id = await seed_task_list_id(async_connection)

        response = await authenticated_client.get(_open_path(list_id))

        assert response.status_code == 200
        assert response.json() == {"data": [], "meta": {"total": 0}}

    async def test_each_task_carries_the_full_read_shape(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        list_id = await seed_task_list_id(async_connection)
        dated = await create_list_task(
            async_connection,
            task_list_id=list_id,
            due_date=LONG_PAST,
            flagged=True,
            icon=TaskIcon.STAR,
            text="pack the tent",
        )
        contact_id = await create_contact(async_connection, first_name="Sarah")
        await link_contact(async_connection, task_id=dated, contact_id=contact_id)
        trip = await create_journal(
            journal_repository, title="Weekend Trip", days_offset=10
        )
        await create_list_task(
            async_connection, task_list_id=list_id, position=1, due_journal_id=trip
        )

        response = await authenticated_client.get(_open_path(list_id))

        rows = response.json()["data"]
        dated_row = rows[0]["attributes"]
        assert dated_row["text"] == "pack the tent"
        assert dated_row["task_list"] == {
            "id": list_id,
            "name": "Packing",
            "icon": None,
            "archived": False,
        }
        assert dated_row["due_date"] == LONG_PAST.isoformat()
        assert dated_row["flagged"] is True
        assert dated_row["icon"] == "star"
        assert dated_row["overdue"] is True
        assert dated_row["lapsed"] is False
        assert [contact["id"] for contact in dated_row["contacts"]] == [contact_id]
        journal_row = rows[1]["attributes"]
        assert journal_row["due_journal"]["title"] == "Weekend Trip"
        assert journal_row["overdue"] is False
        assert rows[0]["links"]["self"].endswith(f"/api/tasks/{dated}")

    async def test_an_archived_lists_tasks_are_readable_and_marked(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id = await seed_task_list_id(async_connection, archived=True)
        task_id = await create_list_task(async_connection, task_list_id=list_id)

        response = await authenticated_client.get(_open_path(list_id))

        assert response.status_code == 200
        assert _ids(response) == [task_id]
        assert response.json()["data"][0]["attributes"]["task_list"]["archived"]


class TestCompletedTasks:
    async def test_answers_done_and_cancelled_most_recently_closed_first(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id = await seed_task_list_id(async_connection)
        older = await _closed(async_connection, list_id, TaskStatus.DONE, minutes=1)
        newest = await _closed(
            async_connection, list_id, TaskStatus.CANCELLED, minutes=3
        )
        middle = await _closed(async_connection, list_id, TaskStatus.DONE, minutes=2)
        await create_list_task(async_connection, task_list_id=list_id)

        response = await authenticated_client.get(_completed_path(list_id))

        assert response.status_code == 200
        assert _ids(response) == [newest, middle, older]
        statuses = [row["attributes"]["status"] for row in response.json()["data"]]
        assert statuses == ["cancelled", "done", "done"]
        assert response.json()["meta"]["total_count"] == 3

    async def test_pages_through_the_completed_tasks(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id = await seed_task_list_id(async_connection)
        closed = [
            await _closed(async_connection, list_id, TaskStatus.DONE, minutes=minute)
            for minute in range(3)
        ]

        first = await authenticated_client.get(
            _completed_path(list_id), params={"page": 1, "limit": 2}
        )
        second = await authenticated_client.get(
            _completed_path(list_id), params={"page": 2, "limit": 2}
        )

        assert _ids(first) == [closed[2], closed[1]]
        assert _ids(second) == [closed[0]]
        assert first.json()["meta"] == {
            "total_count": 3,
            "page_count": 2,
            "current_page": 1,
            "per_page": 2,
        }
        links = first.json()["links"]
        assert links["next"].endswith(
            f"/api/task-lists/{list_id}/tasks/completed?page=2&limit=2"
        )
        assert links.get("prev") is None
        assert second.json()["links"]["prev"].endswith("page=1&limit=2")
        assert second.json()["links"].get("next") is None

    async def test_a_page_past_the_end_is_empty_and_keeps_the_total(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id = await seed_task_list_id(async_connection)
        await _closed(async_connection, list_id, TaskStatus.DONE, minutes=1)

        response = await authenticated_client.get(
            _completed_path(list_id), params={"page": 5}
        )

        assert response.status_code == 200
        assert response.json()["data"] == []
        assert response.json()["meta"]["total_count"] == 1

    async def test_a_list_with_nothing_completed_answers_an_empty_first_page(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id = await seed_task_list_id(async_connection)
        await create_list_task(async_connection, task_list_id=list_id)

        response = await authenticated_client.get(_completed_path(list_id))

        assert response.status_code == 200
        body = response.json()
        assert body["data"] == []
        assert body["meta"] == {
            "total_count": 0,
            "page_count": 0,
            "current_page": 1,
            "per_page": 20,
        }
        assert body["links"].get("next") is None
        assert body["links"].get("prev") is None

    async def test_an_archived_lists_completed_tasks_are_readable(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id = await seed_task_list_id(async_connection, archived=True)
        done = await _closed(async_connection, list_id, TaskStatus.DONE, minutes=1)

        response = await authenticated_client.get(_completed_path(list_id))

        assert _ids(response) == [done]


class TestRefusals:
    @pytest.mark.parametrize("path", [_open_path, _completed_path])
    @pytest.mark.parametrize("list_id", ["abc", "0", str(INT32_MAX + 1)])
    async def test_a_bad_list_id_is_a_400(
        self, authenticated_client: AsyncClient, path: Any, list_id: str
    ) -> None:
        response = await authenticated_client.get(path(list_id))

        assert response.status_code == 400

    @pytest.mark.parametrize(
        "params",
        [{"page": 0}, {"page": "two"}, {"limit": 0}, {"limit": 101}],
    )
    async def test_a_bad_page_or_limit_is_a_400(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        params: dict[str, Any],
    ) -> None:
        list_id = await seed_task_list_id(async_connection)

        response = await authenticated_client.get(
            _completed_path(list_id), params=params
        )

        assert response.status_code == 400

    @pytest.mark.parametrize("path", [_open_path, _completed_path])
    async def test_an_unknown_list_is_a_404(
        self, authenticated_client: AsyncClient, path: Any
    ) -> None:
        response = await authenticated_client.get(path(999_999))

        assert response.status_code == 404
        assert _error(response)["code"] == "TASK_LIST_NOT_FOUND"


class TestAnotherUsersList:
    @pytest.mark.parametrize("path", [_open_path, _completed_path])
    async def test_reads_exactly_as_a_missing_list_and_leaks_nothing(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        path: Any,
    ) -> None:
        """A real list of theirs with tasks of both kinds answers the 404 an
        unknown id does, naming neither the list nor any task."""
        foreign_list_id = await seed_task_list_id(
            async_connection, user_id=OTHER_USER_ID
        )
        await create_list_task(
            async_connection,
            task_list_id=foreign_list_id,
            user_id=OTHER_USER_ID,
            text="their secret errand",
        )
        await _closed_for(async_connection, foreign_list_id)

        foreign = await authenticated_client.get(path(foreign_list_id))
        absent = await authenticated_client.get(path(999_999))

        assert foreign.status_code == absent.status_code == 404
        assert _error(foreign)["code"] == _error(absent)["code"]
        assert _error(foreign)["detail"] == (
            f"Task list with ID {foreign_list_id} not found"
        )
        assert "secret errand" not in foreign.text
        assert "Packing" not in foreign.text


async def _closed_for(conn: AsyncConnection, list_id: int) -> None:
    """A done task of the other user's on their list."""
    await create_list_task(
        conn,
        task_list_id=list_id,
        user_id=OTHER_USER_ID,
        status=TaskStatus.DONE,
        text="their secret errand, done",
    )
