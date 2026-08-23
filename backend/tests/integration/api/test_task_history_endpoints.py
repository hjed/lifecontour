"""Integration tests for ``GET /api/tasks/{task_id}/history``.

Mirrors ``test_journal_history_endpoints.py`` — empty state, populated entries,
pagination, 404, JSON:API shape, most-recent-first ordering — over the task
surface, and adds the two things a journal cannot be asked:

- **a deleted task's history is still readable.** Tasks are hard-deleted, so
  this endpoint has to answer without the row it would ordinarily authorise
  against. It is the discriminator the phase's design turns on, and the only
  test here whose failure would leave a user's ``__deleted__`` marker permanently
  unreachable.
- **a task whose events have not been projected yet answers empty, not 404.**
  Projection is asynchronous; refusing here would tell somebody their new task
  does not exist.

Rows are seeded through the shared ``SqlFieldHistoryRepository`` — the same rows
the projection consumer writes — so these tests isolate the read from the async
projection. The end-to-end path from a real task write is covered in
``tests/integration/infrastructure/events/test_task_history_projection_e2e.py``.
"""

from datetime import UTC, datetime, timedelta

import pytest
from core_shared.models.history import Provenance
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.history.adapters.sql.field_history_repository import (
    SqlFieldHistoryRepository,
)
from app.core.history.models import FieldHistoryEntry
from tests.integration.tasks.task_seeding import (
    OTHER_USER_ID,
    USER_ID,
    create_task,
)

BASE = datetime(2024, 3, 1, 8, 0, tzinfo=UTC)


async def _seed(
    connection: AsyncConnection,
    task_id: int,
    field_name: str,
    *,
    old_value: str | None = None,
    new_value: str | None = None,
    changed_by: str = "ui",
    source: Provenance = Provenance.UI,
    created_at: datetime = BASE,
    user_id: str | None = USER_ID,
    event_id: str | None = None,
) -> None:
    """Write one task history row exactly as the projection consumer would."""
    repo = SqlFieldHistoryRepository(connection)
    await repo.record_change(
        FieldHistoryEntry(
            entity_type="task",
            entity_id=task_id,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            changed_by=changed_by,
            source=source,
            event_id=event_id or f"evt-{task_id}-{field_name}",
            created_at=created_at,
            user_id=user_id,
        )
    )


async def _seed_a_life(
    connection: AsyncConnection, task_id: int, *, user_id: str = USER_ID
) -> None:
    """A task's whole history, one row per thing that happened to it.

    Deliberately mixed: the marker that opens it, a reword, a status move, an
    anchor retarget, an intermediate journal link and a person — one of each
    shape the six event types produce, from three different origins. A read that
    only handles the simple pairs passes a single-row fixture and fails this one.

    ``user_id`` is the **task owner** the projection would stamp on every row,
    not the actor: it comes off the event payload, and every event a task
    publishes belongs to whoever owns the task. Seeding a foreign task's rows
    with the authenticated user's id would hand this test a leak of its own
    making and hide the one it is looking for.
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
        await _seed(
            connection,
            task_id,
            field,
            old_value=old,
            new_value=new,
            source=source,
            changed_by=actor,
            created_at=BASE + timedelta(minutes=minutes),
            user_id=user_id,
        )


@pytest.mark.integration
class TestReadingATaskHistory:
    async def test_a_mixed_history_reads_back_most_recent_first(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """Ordering is the contract; the activity-history specification asks for
        "most-recent-first, regardless of any processing delay"."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        await _seed_a_life(async_connection, task_id)

        response = await authenticated_client.get(f"/api/tasks/{task_id}/history")

        assert response.status_code == 200
        entries = response.json()["data"]
        assert [e["attributes"]["field_name"] for e in entries] == [
            "contact:7",
            "journal:200",
            "due_journal_id",
            "status",
            "text",
            "__created__",
        ]

    async def test_every_entry_names_its_provenance_and_its_actor(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """Both halves, on every row. A feed that shows only the source cannot
        distinguish two people; one that shows only the actor cannot say a change
        came from an assistant rather than the browser."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        await _seed_a_life(async_connection, task_id)

        entries = (
            await authenticated_client.get(f"/api/tasks/{task_id}/history")
        ).json()["data"]

        by_field = {e["attributes"]["field_name"]: e["attributes"] for e in entries}
        assert by_field["__created__"]["source"] == "ui"
        assert by_field["__created__"]["changed_by"] == "ui"
        assert by_field["text"]["source"] == "mcp"
        assert by_field["text"]["changed_by"] == "mcp"
        assert by_field["contact:7"]["source"] == "system"
        assert all(e["attributes"]["created_at"] is not None for e in entries)

    async def test_each_entry_follows_the_shared_json_api_shape(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """The same ``History{Attributes,Resource}`` schemas the journal feed
        uses, so one component can render both. Only the ``type`` differs."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        await _seed(
            async_connection,
            task_id,
            "text",
            old_value="a",
            new_value="b",
        )

        entry = (
            await authenticated_client.get(f"/api/tasks/{task_id}/history")
        ).json()["data"][0]

        assert {"type", "id", "attributes"}.issubset(entry)
        assert entry["type"] == "task_history"
        attrs = entry["attributes"]
        assert attrs["entity_type"] == "task"
        assert attrs["entity_id"] == task_id
        for key in (
            "field_name",
            "old_value",
            "new_value",
            "changed_by",
            "source",
            "created_at",
        ):
            assert key in attrs

    async def test_a_task_whose_events_have_not_projected_yet_reads_empty(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """200 with no entries, never 404.

        The projection consumer runs behind the write, so a task created a
        moment ago is in exactly this state. Refusing would tell the user their
        new task does not exist, and it would keep saying so until a background
        process they cannot see caught up.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await authenticated_client.get(f"/api/tasks/{task_id}/history")

        assert response.status_code == 200
        assert response.json()["data"] == []
        assert response.json()["meta"]["total_count"] == 0


@pytest.mark.integration
class TestADeletedTaskStillHasAHistory:
    """The case the whole design turns on.

    A task is hard-deleted, so every other history read's authorisation — load
    the aggregate, compare ``user_id`` — has nothing to load. Ownership rides on
    the rows instead, which is why they carry ``user_id`` at all.
    """

    async def test_the_owner_still_reads_it_after_the_task_row_is_gone(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        await _seed_a_life(async_connection, task_id)
        await _seed(
            async_connection,
            task_id,
            "__deleted__",
            created_at=BASE + timedelta(minutes=10),
        )

        deleted = await authenticated_client.delete(f"/api/tasks/{task_id}")
        assert deleted.status_code == 204

        response = await authenticated_client.get(f"/api/tasks/{task_id}/history")

        assert response.status_code == 200
        fields = [e["attributes"]["field_name"] for e in response.json()["data"]]
        assert fields[0] == "__deleted__"
        assert "__created__" in fields

    async def test_another_user_is_refused_a_deleted_task_too(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """Once the row is gone there is no other guard.

        The task repository's owner scoping cannot answer for a task that no
        longer exists, so if the rows did not carry an owner the honest choices
        would be to leak or to refuse everybody.
        """
        creating_id, due_id = task_anchors
        other_task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            user_id=OTHER_USER_ID,
        )
        await _seed(
            async_connection,
            other_task_id,
            "__deleted__",
            user_id=OTHER_USER_ID,
        )

        response = await authenticated_client.get(f"/api/tasks/{other_task_id}/history")

        assert response.status_code == 404
        # The domain's own refusal, not FastAPI's "no such route" — otherwise
        # this test passes against an endpoint that was never written.
        assert response.json()["errors"][0]["code"] == "TASK_NOT_FOUND"


@pytest.mark.integration
class TestHistoryCannotLeakAcrossUsers:
    """The ITER12-002 lesson, asserted at this surface rather than inherited."""

    async def test_another_users_live_task_is_404(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        creating_id, due_id = task_anchors
        other_task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            user_id=OTHER_USER_ID,
        )
        await _seed_a_life(async_connection, other_task_id, user_id=OTHER_USER_ID)

        response = await authenticated_client.get(f"/api/tasks/{other_task_id}/history")

        assert response.status_code == 404
        assert response.json()["errors"][0]["code"] == "TASK_NOT_FOUND"

    async def test_a_foreign_task_answers_exactly_what_an_unknown_one_does(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """Otherwise the difference between the two bodies is a probe: an
        attacker learns which ids exist by reading the error."""
        creating_id, due_id = task_anchors
        other_task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            user_id=OTHER_USER_ID,
        )
        await _seed_a_life(async_connection, other_task_id, user_id=OTHER_USER_ID)

        foreign = await authenticated_client.get(f"/api/tasks/{other_task_id}/history")
        unknown = await authenticated_client.get("/api/tasks/999999/history")

        assert foreign.status_code == unknown.status_code == 404
        assert (
            foreign.json()["errors"][0]["code"] == (unknown.json()["errors"][0]["code"])
        )

    async def test_an_unprojected_foreign_task_is_404_as_well(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """The fallback path has its own owner check, and this is it.

        With no history rows the read falls through to the ``tasks`` table; a
        fallback that looked the task up unscoped would hand somebody else's
        history over the moment the projection lagged.
        """
        creating_id, due_id = task_anchors
        other_task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            user_id=OTHER_USER_ID,
        )

        response = await authenticated_client.get(f"/api/tasks/{other_task_id}/history")

        assert response.status_code == 404
        assert response.json()["errors"][0]["code"] == "TASK_NOT_FOUND"


@pytest.mark.integration
class TestPaginationAndRejections:
    async def test_pages_slice_the_same_ordering_and_meta_carries_the_total(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        await _seed_a_life(async_connection, task_id)

        first = await authenticated_client.get(
            f"/api/tasks/{task_id}/history?page=1&limit=2"
        )
        third = await authenticated_client.get(
            f"/api/tasks/{task_id}/history?page=3&limit=2"
        )

        assert first.status_code == 200
        body = first.json()
        assert len(body["data"]) == 2
        assert body["meta"]["current_page"] == 1
        assert body["meta"]["per_page"] == 2
        assert body["meta"]["total_count"] == 6
        assert [e["attributes"]["field_name"] for e in body["data"]] == [
            "contact:7",
            "journal:200",
        ]
        assert [e["attributes"]["field_name"] for e in third.json()["data"]] == [
            "text",
            "__created__",
        ]

    async def test_the_total_does_not_change_with_the_page(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        await _seed_a_life(async_connection, task_id)

        totals = {
            (
                await authenticated_client.get(
                    f"/api/tasks/{task_id}/history?page={page}&limit=2"
                )
            ).json()["meta"]["total_count"]
            for page in (1, 2, 3)
        }

        assert totals == {6}

    async def test_an_unknown_task_is_404(
        self, authenticated_client: AsyncClient
    ) -> None:
        response = await authenticated_client.get("/api/tasks/999999/history")

        assert response.status_code == 404
        assert response.json()["errors"][0]["code"] == "TASK_NOT_FOUND"

    async def test_an_out_of_range_id_is_400(
        self, authenticated_client: AsyncClient
    ) -> None:
        """The same ``DatabaseIdPath`` guard every other task member route uses:
        an id beyond ``INTEGER`` is a bad request, not a database error."""
        response = await authenticated_client.get(
            "/api/tasks/999999999999999999999/history"
        )

        assert response.status_code == 400

    async def test_the_limit_is_capped(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """No page size a client can name turns this into a bulk export.

        400 rather than 422: this API renders every request-validation failure
        through the same JSON:API handler, so an over-large ``limit`` answers
        the way an unknown attribute does.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        response = await authenticated_client.get(
            f"/api/tasks/{task_id}/history?limit=1000"
        )

        assert response.status_code == 400
        assert "errors" in response.json()
