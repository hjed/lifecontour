"""Integration tests for ``GET /api/task-lists/{list_id}/history``.

The list counterpart of ``test_task_history_endpoints.py``: ordering, shape,
pagination and refusals, plus the two things a list's history must do that a
journal's need not — answer empty (not 404) before projection has caught up,
and stay readable by its owner, and only its owner, once the list row is gone.

Rows are seeded through ``SqlFieldHistoryRepository`` exactly as the projection
writes them, which isolates the read from the async projection; the path from a
real list write is covered in
``tests/integration/infrastructure/events/test_task_list_history_projection_e2e.py``.
"""

import json
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.history.adapters.sql.field_history_repository import (
    SqlFieldHistoryRepository,
)
from app.core.history.services.history_service import HistoryService
from app.core.tasks.adapters.sql.task_list_repository import SqlTaskListRepository
from app.core.tasks.adapters.sql.task_repository import SqlTaskRepository
from app.core.tasks.services.task_list_service import TaskListService
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.events.outbox_repository import OutboxEvent
from tests.integration.tasks.task_seeding import (
    ARCHIVED_AT_EXAMPLE,
    OTHER_USER_ID,
    delete_task_list_row,
    seed_task_list,
    seed_task_list_history,
)

pytestmark = pytest.mark.integration

NEWEST_FIRST = ["archived_at", "archived_at", "icon", "name", "__created__"]
FOREIGN_NAME = "Their Secret Plans"
LIST_ARCHIVED_AT = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


async def _own_list(conn: AsyncConnection, *, with_history: bool = True) -> int:
    seeded = await seed_task_list(conn, "Packing")
    assert seeded.id is not None
    if with_history:
        await seed_task_list_history(conn, seeded.id)
    return seeded.id


async def _foreign_list(conn: AsyncConnection, *, with_history: bool) -> int:
    seeded = await seed_task_list(conn, FOREIGN_NAME, user_id=OTHER_USER_ID)
    assert seeded.id is not None
    if with_history:
        await seed_task_list_history(conn, seeded.id, user_id=OTHER_USER_ID)
    return seeded.id


def _fields(response: Response) -> list[str]:
    return [e["attributes"]["field_name"] for e in response.json()["data"]]


def _assert_not_found(response: Response) -> None:
    assert response.status_code == 404, response.text
    assert response.json()["errors"][0]["code"] == "TASK_LIST_NOT_FOUND"
    assert FOREIGN_NAME not in response.text
    assert "Packing" not in response.text


class TestReadingAListHistory:
    async def test_the_whole_life_reads_back_most_recent_first(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id = await _own_list(async_connection)

        response = await authenticated_client.get(f"/api/task-lists/{list_id}/history")

        assert response.status_code == 200
        assert _fields(response) == NEWEST_FIRST
        archive, unarchive = (
            response.json()["data"][1]["attributes"],
            response.json()["data"][0]["attributes"],
        )
        assert (archive["old_value"], archive["new_value"]) == (
            None,
            ARCHIVED_AT_EXAMPLE,
        )
        assert (unarchive["old_value"], unarchive["new_value"]) == (
            ARCHIVED_AT_EXAMPLE,
            None,
        )

    async def test_each_entry_has_the_shared_shape_provenance_and_actor(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id = await _own_list(async_connection)

        entries = (
            await authenticated_client.get(f"/api/task-lists/{list_id}/history")
        ).json()["data"]

        assert {e["type"] for e in entries} == {"task_list_history"}
        by_field = {e["attributes"]["field_name"]: e["attributes"] for e in entries}
        assert by_field["__created__"]["entity_type"] == "task_list"
        assert by_field["__created__"]["entity_id"] == list_id
        assert (by_field["name"]["source"], by_field["name"]["changed_by"]) == (
            "mcp",
            "mcp",
        )
        assert by_field["icon"]["source"] == "ui"
        assert all(e["attributes"]["created_at"] is not None for e in entries)

    async def test_a_list_whose_events_have_not_projected_reads_empty(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id = await _own_list(async_connection, with_history=False)

        response = await authenticated_client.get(f"/api/task-lists/{list_id}/history")

        assert response.status_code == 200
        assert response.json()["data"] == []
        assert response.json()["meta"]["total_count"] == 0

    async def test_an_archived_lists_history_is_readable(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        """Archiving refuses writes; a read of the record is not one."""
        archived = await seed_task_list(
            async_connection, "Old trip", archived_at=LIST_ARCHIVED_AT
        )
        assert archived.id is not None
        await seed_task_list_history(async_connection, archived.id)

        response = await authenticated_client.get(
            f"/api/task-lists/{archived.id}/history"
        )

        assert response.status_code == 200
        assert _fields(response) == NEWEST_FIRST

    async def test_rows_filed_under_another_type_with_the_same_id_are_left_out(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        """A task and a list can share an integer id; their feeds must not."""
        list_id = await _own_list(async_connection, with_history=False)
        await seed_task_list_history(async_connection, list_id, entity_type="task")
        await seed_task_list_history(async_connection, list_id, entity_type="journal")

        response = await authenticated_client.get(f"/api/task-lists/{list_id}/history")

        assert response.status_code == 200
        assert response.json()["data"] == []


class TestADeletedListStillHasAHistory:
    """Lists will be hard-deleted; ownership rides on the rows for that day."""

    async def test_the_owner_still_reads_it_after_the_row_is_gone(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id = await _own_list(async_connection)
        await delete_task_list_row(async_connection, list_id)

        response = await authenticated_client.get(f"/api/task-lists/{list_id}/history")

        assert response.status_code == 200
        assert _fields(response) == NEWEST_FIRST

    async def test_another_user_is_refused_once_the_row_is_gone(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        foreign_id = await _foreign_list(async_connection, with_history=True)
        await delete_task_list_row(async_connection, foreign_id)

        response = await authenticated_client.get(
            f"/api/task-lists/{foreign_id}/history"
        )

        _assert_not_found(response)


async def _project_list_deletions(conn: AsyncConnection) -> None:
    """Project the outbox's ``TaskListDeleted`` rows as the consumer would.

    The relay and the stream belong to the projection tests; what this file
    asks is what the history read answers once the real delete's row exists.
    """
    rows = await conn.execute(
        text(
            "SELECT id, event_id, event_type, aggregate_id, event_data, "
            "occurred_at, created_at FROM outbox_events "
            "WHERE event_type = 'TaskListDeleted'"
        )
    )
    history = SqlFieldHistoryRepository(conn)
    for row in rows.all():
        event = OutboxEvent(
            id=row.id,
            event_id=row.event_id,
            event_type=row.event_type,
            aggregate_id=row.aggregate_id,
            event_data=json.loads(row.event_data),
            occurred_at=row.occurred_at,
            retry_count=0,
            created_at=row.created_at,
        )
        for entry in HistoryService().project_event(event):
            await history.record_change(entry)


class TestARealDeleteEndsTheListsHistory:
    """The list's own delete, not a stand-in: its ``__deleted__`` line is the
    newest entry, readable by the owner and by nobody else."""

    async def test_the_owner_reads_the_history_ending_in_the_deletion(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id = await _own_list(async_connection)

        deleted = await authenticated_client.delete(f"/api/task-lists/{list_id}")
        await _project_list_deletions(async_connection)
        response = await authenticated_client.get(f"/api/task-lists/{list_id}/history")

        assert deleted.status_code == 204
        assert response.status_code == 200
        assert _fields(response) == ["__deleted__", *NEWEST_FIRST]
        marker = response.json()["data"][0]["attributes"]
        assert (marker["old_value"], marker["new_value"]) == ("Packing", None)
        assert (marker["source"], marker["changed_by"]) == ("ui", "ui")

    async def test_another_user_is_refused_a_deleted_list_history(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        foreign_id = await _foreign_list(async_connection, with_history=True)
        await TaskListService(
            task_list_repo=SqlTaskListRepository(async_connection),
            task_repo=SqlTaskRepository(async_connection),
            event_publisher=OutboxEventPublisher(async_connection),
        ).delete_task_list(
            user_id=OTHER_USER_ID,
            task_list_id=foreign_id,
            transaction=async_connection,
        )
        await _project_list_deletions(async_connection)

        response = await authenticated_client.get(
            f"/api/task-lists/{foreign_id}/history"
        )

        _assert_not_found(response)


class TestHistoryCannotLeakAcrossUsers:
    async def test_a_foreign_list_with_history_answers_as_an_unknown_one(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        """The owner-on-the-rows branch: the other user's rows answer, and refuse."""
        foreign_id = await _foreign_list(async_connection, with_history=True)

        foreign = await authenticated_client.get(
            f"/api/task-lists/{foreign_id}/history"
        )
        unknown = await authenticated_client.get("/api/task-lists/999999/history")

        _assert_not_found(foreign)
        _assert_not_found(unknown)
        assert (
            foreign.json()["errors"][0]["code"] == unknown.json()["errors"][0]["code"]
        )

    async def test_a_foreign_unprojected_list_is_refused_by_the_fallback(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        foreign_id = await _foreign_list(async_connection, with_history=False)

        response = await authenticated_client.get(
            f"/api/task-lists/{foreign_id}/history"
        )

        _assert_not_found(response)


class TestPaginationAndRejections:
    async def test_pages_slice_one_ordering_and_the_total_is_fixed(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id = await _own_list(async_connection)
        url = f"/api/task-lists/{list_id}/history"

        pages = [
            await authenticated_client.get(f"{url}?page={page}&limit=2")
            for page in (1, 2, 3)
        ]

        assert [field for page in pages for field in _fields(page)] == NEWEST_FIRST
        assert {page.json()["meta"]["total_count"] for page in pages} == {5}
        assert pages[0].json()["meta"]["per_page"] == 2
        assert pages[0].json()["links"]["next"].endswith(f"{url}?page=2&limit=2")

    async def test_a_page_past_the_end_is_an_ordinary_empty_answer(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        list_id = await _own_list(async_connection)

        response = await authenticated_client.get(
            f"/api/task-lists/{list_id}/history?page=1000000&limit=100"
        )

        assert response.status_code == 200
        assert response.json()["data"] == []
        assert response.json()["meta"]["total_count"] == 5

    @pytest.mark.parametrize(
        "query",
        ["limit=101", "limit=0", "page=0", "page=99999999999999999999999"],
    )
    async def test_an_out_of_range_page_or_limit_is_400(
        self,
        query: str,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
    ) -> None:
        list_id = await _own_list(async_connection)

        response = await authenticated_client.get(
            f"/api/task-lists/{list_id}/history?{query}"
        )

        assert response.status_code == 400
        assert "errors" in response.json()

    async def test_an_out_of_range_id_is_400(
        self, authenticated_client: AsyncClient
    ) -> None:
        response = await authenticated_client.get(
            "/api/task-lists/999999999999999999999/history"
        )

        assert response.status_code == 400
