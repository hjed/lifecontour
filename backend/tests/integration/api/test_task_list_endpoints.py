"""Integration tests for the task list endpoints: create, read, list, update, move,
archive, unarchive and delete.

The rules themselves (bottom placement, owner scoping, the event) are proven
against ``TaskListService`` and ``TaskListReadService`` in
``tests/integration/tasks/test_task_list_service_integration.py``. These tests
hold the REST surface to its own promises: the JSON:API shapes, the status code
and error code of each refusal, the provenance it records, and that another
user's list is answered exactly as a missing one.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from core_shared.models.tasks import MAX_TASK_LIST_NAME_LENGTH, TaskIcon, TaskStatus
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.common.identifiers import INT32_MAX
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.infrastructure.config import Settings
from app.main import create_app
from tests.integration.tasks.task_seeding import (
    OTHER_USER_ID,
    USER_ID,
    count,
    create_journal,
    create_list_task,
    seed_task_list,
    task_exists,
    task_list_events,
)

pytestmark = pytest.mark.integration

ARCHIVED_AT = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
ARCHIVED_EARLIER = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
ARCHIVED_LATER = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
_COUNT_LISTS = "SELECT COUNT(*) FROM task_lists WHERE user_id = :user_id"


def _body(**attributes: object) -> dict[str, object]:
    return {"data": {"type": "task-lists", "attributes": attributes}}


def _error(response_json: dict[str, object]) -> dict[str, object]:
    errors = response_json["errors"]
    assert isinstance(errors, list)
    assert len(errors) == 1
    first: dict[str, object] = errors[0]
    return first


def _names(response_json: dict[str, object]) -> list[str]:
    data = response_json["data"]
    assert isinstance(data, list)
    return [resource["attributes"]["name"] for resource in data]


class TestCreateTaskListEndpoint:
    async def test_creates_a_list_and_answers_with_the_resource(
        self, authenticated_client: AsyncClient
    ) -> None:
        response = await authenticated_client.post(
            "/api/task-lists", json=_body(name="Packing", icon="luggage")
        )

        assert response.status_code == 201
        data = response.json()["data"]
        assert data["type"] == "task-lists"
        list_id = int(data["id"])
        assert list_id > 0
        assert data["attributes"] == {
            "name": "Packing",
            "icon": "luggage",
            "position": 0,
            "archived": False,
            "archived_at": None,
            "associated_journal_id": None,
            "created_at": data["attributes"]["created_at"],
            "updated_at": data["attributes"]["updated_at"],
        }
        assert data["attributes"]["created_at"] is not None
        assert data["links"]["self"].endswith(f"/api/task-lists/{list_id}")
        assert data["links"]["self"].startswith("http")

    async def test_the_icon_is_optional(
        self, authenticated_client: AsyncClient
    ) -> None:
        response = await authenticated_client.post(
            "/api/task-lists", json=_body(name="Errands")
        )

        assert response.status_code == 201
        assert response.json()["data"]["attributes"]["icon"] is None

    async def test_the_created_event_is_attributed_to_the_browser(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        response = await authenticated_client.post(
            "/api/task-lists", json=_body(name="Packing")
        )
        list_id = int(response.json()["data"]["id"])

        (event,) = await task_list_events(async_connection, task_list_id=list_id)
        assert event.event_type == "TaskListCreated"
        assert event.payload["user_id"] == USER_ID
        assert (event.payload["source"], event.payload["changed_by"]) == ("ui", "ui")

    @pytest.mark.parametrize("name", ["", "   ", "x" * (MAX_TASK_LIST_NAME_LENGTH + 1)])
    async def test_a_blank_or_too_long_name_is_refused_naming_the_field(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        name: str,
    ) -> None:
        response = await authenticated_client.post(
            "/api/task-lists", json=_body(name=name)
        )

        assert response.status_code == 400
        error = _error(response.json())
        assert error["code"] == "TASK_VALIDATION_ERROR"
        assert error["meta"] == {"field": "name"}
        assert await count(async_connection, _COUNT_LISTS, {"user_id": USER_ID}) == 0
        assert await task_list_events(async_connection) == []

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param(_body(name="Packing", icon="not-an-icon"), id="unknown-icon"),
            pytest.param(_body(icon="luggage"), id="missing-name"),
            pytest.param(_body(name="Packing", position=3), id="unknown-attribute"),
            pytest.param(
                {"data": {"type": "tasks", "attributes": {"name": "Packing"}}},
                id="another-resource-type",
            ),
            pytest.param(
                {"data": {"type": "task-lists", "attributes": {"name": "P"}}, "x": 1},
                id="unknown-envelope-member",
            ),
        ],
    )
    async def test_a_malformed_body_is_refused_and_nothing_is_written(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        body: dict[str, object],
    ) -> None:
        response = await authenticated_client.post("/api/task-lists", json=body)

        assert response.status_code == 400
        assert response.json()["errors"][0]["code"] == "VALIDATION_ERROR"
        assert await count(async_connection, _COUNT_LISTS, {"user_id": USER_ID}) == 0


class TestGetTaskListEndpoint:
    async def test_reads_one_owned_list(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(
            async_connection, "Groceries", icon=TaskIcon.SHOPPING_CART
        )

        response = await authenticated_client.get(f"/api/task-lists/{seeded.id}")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["type"] == "task-lists"
        assert data["id"] == str(seeded.id)
        assert data["attributes"]["name"] == "Groceries"
        assert data["attributes"]["icon"] == "shopping-cart"
        assert data["links"]["self"].endswith(f"/api/task-lists/{seeded.id}")

    async def test_an_archived_list_reads_as_archived(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(
            async_connection, "Old trip", archived_at=ARCHIVED_AT
        )

        response = await authenticated_client.get(f"/api/task-lists/{seeded.id}")

        attributes = response.json()["data"]["attributes"]
        assert attributes["archived"] is True
        assert datetime.fromisoformat(attributes["archived_at"]) == ARCHIVED_AT

    async def test_another_users_list_is_indistinguishable_from_a_missing_one(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        foreign = await seed_task_list(
            async_connection, "Theirs", user_id=OTHER_USER_ID
        )
        missing_id = INT32_MAX

        foreign_response = await authenticated_client.get(
            f"/api/task-lists/{foreign.id}"
        )
        missing_response = await authenticated_client.get(
            f"/api/task-lists/{missing_id}"
        )

        assert foreign_response.status_code == missing_response.status_code == 404
        foreign_error = _error(foreign_response.json())
        missing_error = _error(missing_response.json())
        assert foreign_error["code"] == missing_error["code"] == "TASK_LIST_NOT_FOUND"
        # The same words a missing id gets: nothing says the list exists.
        assert foreign_error["detail"] == f"Task list with ID {foreign.id} not found"
        assert "Theirs" not in foreign_response.text

    @pytest.mark.parametrize("list_id", ["0", str(INT32_MAX + 1), "abc"])
    async def test_an_out_of_range_id_is_a_bad_request(
        self, authenticated_client: AsyncClient, list_id: str
    ) -> None:
        response = await authenticated_client.get(f"/api/task-lists/{list_id}")

        assert response.status_code == 400


def _patch_body(list_id: object, **attributes: object) -> dict[str, object]:
    return {
        "data": {"type": "task-lists", "id": str(list_id), "attributes": attributes}
    }


async def _row(conn: AsyncConnection, list_id: int) -> dict[str, Any]:
    row = (
        await conn.execute(
            text("SELECT * FROM task_lists WHERE id = :id"), {"id": list_id}
        )
    ).one()
    return dict(row._mapping)


class TestUpdateTaskListEndpoint:
    async def test_renames_a_list_and_answers_with_the_resource(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(
            async_connection, "Packing", icon=TaskIcon.LUGGAGE
        )

        response = await authenticated_client.patch(
            f"/api/task-lists/{seeded.id}",
            json=_patch_body(seeded.id, name="Trip packing"),
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert (data["type"], data["id"]) == ("task-lists", str(seeded.id))
        # An absent icon is left alone.
        assert (data["attributes"]["name"], data["attributes"]["icon"]) == (
            "Trip packing",
            "luggage",
        )
        assert data["links"]["self"].endswith(f"/api/task-lists/{seeded.id}")

    async def test_sets_the_icon_and_keeps_the_name(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(async_connection, "Packing")

        response = await authenticated_client.patch(
            f"/api/task-lists/{seeded.id}",
            json=_patch_body(seeded.id, icon="shopping-cart"),
        )

        assert response.status_code == 200
        attributes = response.json()["data"]["attributes"]
        assert (attributes["name"], attributes["icon"]) == ("Packing", "shopping-cart")

    async def test_a_null_icon_clears_it(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(
            async_connection, "Packing", icon=TaskIcon.LUGGAGE
        )
        assert seeded.id is not None

        response = await authenticated_client.patch(
            f"/api/task-lists/{seeded.id}", json=_patch_body(seeded.id, icon=None)
        )

        assert response.status_code == 200
        assert response.json()["data"]["attributes"]["icon"] is None
        assert (await _row(async_connection, seeded.id))["icon"] is None

    async def test_name_and_icon_together_are_one_event_attributed_to_the_browser(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(async_connection, "Packing")

        response = await authenticated_client.patch(
            f"/api/task-lists/{seeded.id}",
            json=_patch_body(seeded.id, name="Trip", icon="luggage"),
        )

        assert response.status_code == 200
        (event,) = await task_list_events(async_connection, task_list_id=seeded.id)
        assert event.event_type == "TaskListUpdated"
        assert event.payload["changed_fields"] == {
            "name": ["Packing", "Trip"],
            "icon": [None, "luggage"],
        }
        assert (event.payload["source"], event.payload["changed_by"]) == ("ui", "ui")

    @pytest.mark.parametrize("name", ["", "   ", "x" * (MAX_TASK_LIST_NAME_LENGTH + 1)])
    async def test_a_blank_or_too_long_name_is_refused_naming_the_field(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        name: str,
    ) -> None:
        seeded = await seed_task_list(async_connection, "Packing")
        assert seeded.id is not None
        before = await _row(async_connection, seeded.id)

        response = await authenticated_client.patch(
            f"/api/task-lists/{seeded.id}", json=_patch_body(seeded.id, name=name)
        )

        assert response.status_code == 400
        error = _error(response.json())
        assert error["code"] == "TASK_VALIDATION_ERROR"
        assert error["meta"] == {"field": "name"}
        assert await _row(async_connection, seeded.id) == before
        assert await task_list_events(async_connection) == []

    async def test_a_body_id_that_disagrees_with_the_path_is_refused(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(async_connection, "Packing")
        other = await seed_task_list(async_connection, "Errands")
        assert seeded.id is not None and other.id is not None
        before = await _row(async_connection, other.id)

        response = await authenticated_client.patch(
            f"/api/task-lists/{seeded.id}", json=_patch_body(other.id, name="Trip")
        )

        assert response.status_code == 400
        error = _error(response.json())
        assert error["code"] == "TASK_VALIDATION_ERROR"
        assert error["meta"] == {"field": "id"}
        assert (await _row(async_connection, seeded.id))["name"] == "Packing"
        assert await _row(async_connection, other.id) == before
        assert await task_list_events(async_connection) == []

    @pytest.mark.parametrize(
        "attributes",
        [
            pytest.param({}, id="names-no-change"),
            pytest.param({"name": None}, id="null-name"),
            pytest.param({"icon": "not-an-icon"}, id="unknown-icon"),
            pytest.param({"position": 3}, id="position"),
            pytest.param({"archived_at": None}, id="archived-at"),
        ],
    )
    async def test_a_malformed_attribute_set_is_refused_and_nothing_is_written(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        attributes: dict[str, object],
    ) -> None:
        seeded = await seed_task_list(
            async_connection, "Packing", icon=TaskIcon.LUGGAGE
        )
        assert seeded.id is not None
        before = await _row(async_connection, seeded.id)

        response = await authenticated_client.patch(
            f"/api/task-lists/{seeded.id}", json=_patch_body(seeded.id, **attributes)
        )

        assert response.status_code == 400
        assert response.json()["errors"][0]["code"] == "VALIDATION_ERROR"
        assert await _row(async_connection, seeded.id) == before
        assert await task_list_events(async_connection) == []

    async def test_another_resource_type_or_a_missing_id_is_refused(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(async_connection, "Packing")

        wrong_type = await authenticated_client.patch(
            f"/api/task-lists/{seeded.id}",
            json={
                "data": {
                    "type": "tasks",
                    "id": str(seeded.id),
                    "attributes": {"name": "Trip"},
                }
            },
        )
        no_id = await authenticated_client.patch(
            f"/api/task-lists/{seeded.id}", json=_body(name="Trip")
        )

        assert wrong_type.status_code == 400
        assert no_id.status_code == 400
        assert await task_list_events(async_connection) == []

    async def test_a_missing_list_is_not_found(
        self, authenticated_client: AsyncClient
    ) -> None:
        response = await authenticated_client.patch(
            f"/api/task-lists/{INT32_MAX}", json=_patch_body(INT32_MAX, name="Trip")
        )

        assert response.status_code == 404
        error = _error(response.json())
        assert error["code"] == "TASK_LIST_NOT_FOUND"
        assert error["detail"] == f"Task list with ID {INT32_MAX} not found"

    @pytest.mark.parametrize("list_id", ["0", str(INT32_MAX + 1), "abc"])
    async def test_an_out_of_range_id_is_a_bad_request(
        self, authenticated_client: AsyncClient, list_id: str
    ) -> None:
        response = await authenticated_client.patch(
            f"/api/task-lists/{list_id}", json=_patch_body(list_id, name="Trip")
        )

        assert response.status_code == 400

    async def test_an_archived_list_refuses_a_patch_with_a_conflict(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        archived = await seed_task_list(
            async_connection, "Old trip", archived_at=ARCHIVED_AT
        )
        before = await _row(async_connection, archived.id or 0)

        response = await authenticated_client.patch(
            f"/api/task-lists/{archived.id}",
            json=_patch_body(archived.id, name="Renamed"),
        )

        assert response.status_code == 409
        error = _error(response.json())
        assert error["code"] == "TASK_LIST_ARCHIVED"
        assert "unarchive" in str(error["detail"])
        assert await _row(async_connection, archived.id or 0) == before
        assert await task_list_events(async_connection) == []


async def _journal(conn: AsyncConnection, *, user_id: str = USER_ID) -> int:
    return await create_journal(
        SqlJournalRepository(conn), title="Trip", days_offset=7, user_id=user_id
    )


class TestAssociateTaskListEndpoint:
    """``associated_journal_id`` on ``PATCH /api/task-lists/{list_id}``.

    The service rule is proven in ``test_task_list_service_integration.py``;
    here, the REST shape of each answer and refusal.
    """

    async def test_associates_changes_and_removes_and_each_read_carries_it(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        first = await _journal(async_connection)
        second = await _journal(async_connection)
        seeded = await seed_task_list(async_connection, "Packing")

        answered = []
        for journal_id in (first, second, None):
            response = await authenticated_client.patch(
                f"/api/task-lists/{seeded.id}",
                json=_patch_body(seeded.id, associated_journal_id=journal_id),
            )
            assert response.status_code == 200
            answered.append(
                response.json()["data"]["attributes"]["associated_journal_id"]
            )

        assert answered == [first, second, None]
        events = await task_list_events(async_connection, task_list_id=seeded.id)
        assert [event.payload["changed_fields"] for event in events] == [
            {"associated_journal_id": [None, first]},
            {"associated_journal_id": [first, second]},
            {"associated_journal_id": [second, None]},
        ]
        assert {(e.payload["source"], e.payload["changed_by"]) for e in events} == {
            ("ui", "ui")
        }

    async def test_the_read_and_the_listing_carry_the_journal(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        journal_id = await _journal(async_connection)
        seeded = await seed_task_list(
            async_connection, "Packing", associated_journal_id=journal_id
        )

        read = await authenticated_client.get(f"/api/task-lists/{seeded.id}")
        listing = await authenticated_client.get("/api/task-lists")

        assert read.json()["data"]["attributes"]["associated_journal_id"] == journal_id
        assert [
            resource["attributes"]["associated_journal_id"]
            for resource in listing.json()["data"]
        ] == [journal_id]

    async def test_another_users_journal_is_answered_as_a_missing_one(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        theirs = await _journal(async_connection, user_id=OTHER_USER_ID)
        seeded = await seed_task_list(async_connection, "Packing")
        assert seeded.id is not None
        missing = theirs + 1_000_000

        foreign = await authenticated_client.patch(
            f"/api/task-lists/{seeded.id}",
            json=_patch_body(seeded.id, associated_journal_id=theirs),
        )
        unknown = await authenticated_client.patch(
            f"/api/task-lists/{seeded.id}",
            json=_patch_body(seeded.id, associated_journal_id=missing),
        )

        assert (foreign.status_code, unknown.status_code) == (404, 404)
        foreign_error, unknown_error = _error(foreign.json()), _error(unknown.json())
        assert foreign_error["code"] == "TASK_LIST_JOURNAL_NOT_FOUND"
        assert foreign_error["meta"] == {"field": "associated_journal_id"}
        assert foreign_error["detail"] == str(unknown_error["detail"]).replace(
            str(missing), str(theirs)
        )
        assert (await _row(async_connection, seeded.id))[
            "associated_journal_id"
        ] is None
        assert await task_list_events(async_connection) == []

    async def test_an_archived_list_refuses_an_association_with_a_conflict(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        journal_id = await _journal(async_connection)
        archived = await seed_task_list(
            async_connection, "Old trip", archived_at=ARCHIVED_AT
        )

        response = await authenticated_client.patch(
            f"/api/task-lists/{archived.id}",
            json=_patch_body(archived.id, associated_journal_id=journal_id),
        )

        assert response.status_code == 409
        assert _error(response.json())["code"] == "TASK_LIST_ARCHIVED"

    @pytest.mark.parametrize("journal_id", ["12", 0, True], ids=repr)
    async def test_a_journal_id_that_is_not_a_positive_integer_is_refused(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        journal_id: object,
    ) -> None:
        seeded = await seed_task_list(async_connection, "Packing")

        response = await authenticated_client.patch(
            f"/api/task-lists/{seeded.id}",
            json=_patch_body(seeded.id, associated_journal_id=journal_id),
        )

        assert response.status_code == 400
        assert await task_list_events(async_connection) == []


class TestArchiveTaskListEndpoint:
    """``POST /api/task-lists/{list_id}/archive``: no body, answers the list."""

    async def test_archives_the_list_and_answers_with_the_resource(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(
            async_connection, "Packing", icon=TaskIcon.LUGGAGE
        )

        response = await authenticated_client.post(
            f"/api/task-lists/{seeded.id}/archive"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert (data["type"], data["id"]) == ("task-lists", str(seeded.id))
        attributes = data["attributes"]
        assert attributes["archived"] is True
        assert attributes["archived_at"] is not None
        assert (attributes["name"], attributes["icon"], attributes["position"]) == (
            "Packing",
            "luggage",
            seeded.position,
        )
        assert data["links"]["self"].endswith(f"/api/task-lists/{seeded.id}")

    async def test_the_event_is_attributed_to_the_browser(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(async_connection, "Packing")

        response = await authenticated_client.post(
            f"/api/task-lists/{seeded.id}/archive"
        )

        archived_at = response.json()["data"]["attributes"]["archived_at"]
        (event,) = await task_list_events(async_connection)
        assert event.event_type == "TaskListUpdated"
        (old, new) = event.payload["changed_fields"]["archived_at"]
        assert old is None
        assert datetime.fromisoformat(new) == datetime.fromisoformat(archived_at)
        assert (event.payload["source"], event.payload["changed_by"]) == ("ui", "ui")

    async def test_archiving_an_archived_list_answers_it_unchanged(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(
            async_connection, "Old trip", archived_at=ARCHIVED_AT
        )

        response = await authenticated_client.post(
            f"/api/task-lists/{seeded.id}/archive"
        )

        assert response.status_code == 200
        attributes = response.json()["data"]["attributes"]
        assert datetime.fromisoformat(attributes["archived_at"]) == ARCHIVED_AT
        assert await task_list_events(async_connection) == []

    async def test_a_missing_list_is_not_found(
        self, authenticated_client: AsyncClient
    ) -> None:
        response = await authenticated_client.post(
            f"/api/task-lists/{INT32_MAX}/archive"
        )

        assert response.status_code == 404
        assert _error(response.json())["code"] == "TASK_LIST_NOT_FOUND"

    @pytest.mark.parametrize("list_id", ["0", str(INT32_MAX + 1), "abc"])
    async def test_an_out_of_range_id_is_a_bad_request(
        self, authenticated_client: AsyncClient, list_id: str
    ) -> None:
        response = await authenticated_client.post(f"/api/task-lists/{list_id}/archive")

        assert response.status_code == 400
        assert _error(response.json())["code"] == "VALIDATION_ERROR"


class TestDeleteTaskListEndpoint:
    """``DELETE /api/task-lists/{list_id}``: no body, answers 204."""

    async def test_deletes_the_list_and_answers_no_content(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(async_connection, "Packing")

        response = await authenticated_client.delete(f"/api/task-lists/{seeded.id}")

        assert response.status_code == 204
        assert response.content == b""
        read = await authenticated_client.get(f"/api/task-lists/{seeded.id}")
        assert read.status_code == 404

    async def test_tasks_go_with_it_except_those_holding_both_journals(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        seeded = await seed_task_list(async_connection, "Packing")
        assert seeded.id is not None
        creating_id, due_id = task_anchors
        deleted = await create_list_task(async_connection, task_list_id=seeded.id)
        kept = await create_list_task(
            async_connection,
            task_list_id=seeded.id,
            position=1,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
        )

        response = await authenticated_client.delete(f"/api/task-lists/{seeded.id}")

        assert response.status_code == 204
        assert not await task_exists(async_connection, deleted)
        kept_read = await authenticated_client.get(f"/api/tasks/{kept}")
        assert kept_read.status_code == 200
        attributes = kept_read.json()["data"]["attributes"]
        assert (attributes["task_list_id"], attributes["task_list"]) == (None, None)

    async def test_the_event_is_attributed_to_the_browser(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(async_connection, "Packing")

        await authenticated_client.delete(f"/api/task-lists/{seeded.id}")

        (event,) = await task_list_events(async_connection)
        assert event.event_type == "TaskListDeleted"
        assert (event.payload["source"], event.payload["changed_by"]) == ("ui", "ui")

    async def test_deleting_it_again_is_not_found(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(async_connection, "Packing")
        await authenticated_client.delete(f"/api/task-lists/{seeded.id}")

        response = await authenticated_client.delete(f"/api/task-lists/{seeded.id}")

        assert response.status_code == 404
        assert _error(response.json())["code"] == "TASK_LIST_NOT_FOUND"

    async def test_an_archived_list_is_refused_as_a_conflict(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(
            async_connection, "Old trip", archived_at=ARCHIVED_AT
        )

        response = await authenticated_client.delete(f"/api/task-lists/{seeded.id}")

        assert response.status_code == 409
        assert _error(response.json())["code"] == "TASK_LIST_ARCHIVED"
        assert await count(async_connection, _COUNT_LISTS, {"user_id": USER_ID}) == 1
        assert await task_list_events(async_connection) == []

    async def test_another_users_list_is_not_found_and_survives(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        theirs = await seed_task_list(async_connection, "Theirs", user_id=OTHER_USER_ID)

        response = await authenticated_client.delete(f"/api/task-lists/{theirs.id}")

        assert response.status_code == 404
        assert _error(response.json())["code"] == "TASK_LIST_NOT_FOUND"
        assert (
            await count(async_connection, _COUNT_LISTS, {"user_id": OTHER_USER_ID}) == 1
        )

    @pytest.mark.parametrize("list_id", ["0", str(INT32_MAX + 1), "abc"])
    async def test_an_out_of_range_id_is_a_bad_request(
        self, authenticated_client: AsyncClient, list_id: str
    ) -> None:
        response = await authenticated_client.delete(f"/api/task-lists/{list_id}")

        assert response.status_code == 400
        assert _error(response.json())["code"] == "VALIDATION_ERROR"


class TestUnarchiveTaskListEndpoint:
    """``POST /api/task-lists/{list_id}/unarchive``: no body, answers the list."""

    async def test_unarchives_the_list_and_it_is_active_and_writable_again(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        await seed_task_list(async_connection, "First")
        seeded = await seed_task_list(
            async_connection, "Old trip", archived_at=ARCHIVED_AT
        )
        await seed_task_list(async_connection, "Last")

        response = await authenticated_client.post(
            f"/api/task-lists/{seeded.id}/unarchive"
        )

        assert response.status_code == 200
        attributes = response.json()["data"]["attributes"]
        assert (attributes["archived"], attributes["archived_at"]) == (False, None)
        listed = await authenticated_client.get("/api/task-lists")
        assert _names(listed.json()) == ["First", "Old trip", "Last"]
        renamed = await authenticated_client.patch(
            f"/api/task-lists/{seeded.id}", json=_patch_body(seeded.id, name="Trip")
        )
        assert renamed.status_code == 200

    async def test_the_event_is_attributed_to_the_browser(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(
            async_connection, "Old trip", archived_at=ARCHIVED_AT
        )

        await authenticated_client.post(f"/api/task-lists/{seeded.id}/unarchive")

        (event,) = await task_list_events(async_connection)
        assert event.payload["changed_fields"] == {
            "archived_at": [ARCHIVED_AT.isoformat(), None]
        }
        assert (event.payload["source"], event.payload["changed_by"]) == ("ui", "ui")

    async def test_unarchiving_an_active_list_answers_it_unchanged(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        seeded = await seed_task_list(async_connection, "Packing")

        response = await authenticated_client.post(
            f"/api/task-lists/{seeded.id}/unarchive"
        )

        assert response.status_code == 200
        assert response.json()["data"]["attributes"]["archived"] is False
        assert await task_list_events(async_connection) == []

    async def test_a_missing_list_is_not_found(
        self, authenticated_client: AsyncClient
    ) -> None:
        response = await authenticated_client.post(
            f"/api/task-lists/{INT32_MAX}/unarchive"
        )

        assert response.status_code == 404
        assert _error(response.json())["code"] == "TASK_LIST_NOT_FOUND"

    @pytest.mark.parametrize("list_id", ["0", str(INT32_MAX + 1), "abc"])
    async def test_an_out_of_range_id_is_a_bad_request(
        self, authenticated_client: AsyncClient, list_id: str
    ) -> None:
        response = await authenticated_client.post(
            f"/api/task-lists/{list_id}/unarchive"
        )

        assert response.status_code == 400
        assert _error(response.json())["code"] == "VALIDATION_ERROR"


class TestListTaskListsEndpoint:
    async def test_lists_active_lists_in_order_by_default(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        await seed_task_list(async_connection, "First")
        await seed_task_list(async_connection, "Archived", archived_at=ARCHIVED_AT)
        await seed_task_list(async_connection, "Second")

        response = await authenticated_client.get("/api/task-lists")

        assert response.status_code == 200
        assert _names(response.json()) == ["First", "Second"]
        assert response.json()["data"][0]["type"] == "task-lists"

    @pytest.mark.parametrize(
        ("archived", "expected"),
        [
            ("active", ["First", "Second"]),
            ("archived", ["Archived"]),
            ("all", ["First", "Archived", "Second"]),
        ],
    )
    async def test_the_archived_filter_selects_by_archived_state(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        archived: str,
        expected: list[str],
    ) -> None:
        await seed_task_list(async_connection, "First")
        await seed_task_list(async_connection, "Archived", archived_at=ARCHIVED_AT)
        await seed_task_list(async_connection, "Second")

        response = await authenticated_client.get(
            "/api/task-lists", params={"archived": archived}
        )

        assert response.status_code == 200
        assert _names(response.json()) == expected

    async def test_no_lists_is_an_empty_collection(
        self, authenticated_client: AsyncClient
    ) -> None:
        response = await authenticated_client.get("/api/task-lists")

        assert response.status_code == 200
        assert response.json()["data"] == []

    async def test_an_unknown_filter_is_a_bad_request(
        self, authenticated_client: AsyncClient
    ) -> None:
        response = await authenticated_client.get(
            "/api/task-lists", params={"archived": "yes"}
        )

        assert response.status_code == 400

    @pytest.mark.parametrize("archived", ["active", "archived", "all"])
    async def test_another_users_lists_are_never_listed(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        archived: str,
    ) -> None:
        await seed_task_list(async_connection, "Mine")
        await seed_task_list(async_connection, "Theirs", user_id=OTHER_USER_ID)
        await seed_task_list(
            async_connection,
            "Theirs archived",
            user_id=OTHER_USER_ID,
            archived_at=ARCHIVED_AT,
        )

        response = await authenticated_client.get(
            "/api/task-lists", params={"archived": archived}
        )

        assert "Theirs" not in _names(response.json())
        assert "Theirs archived" not in _names(response.json())


class TestListTaskListsByNameInPages:
    """The archived page's listing: a name filter, and pages with a total.

    The filter and paging rules are the repository's and are proven there;
    these hold the REST surface to its shape, its refusals and its owner.
    """

    async def test_a_filtered_page_answers_the_slice_with_pagination(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        for name, archived_at in (
            ("Pack 1", ARCHIVED_EARLIER),
            ("Pack 2", ARCHIVED_AT),
            ("Groceries", ARCHIVED_AT),
            ("Pack 3", ARCHIVED_LATER),
        ):
            await seed_task_list(async_connection, name, archived_at=archived_at)

        response = await authenticated_client.get(
            "/api/task-lists",
            params={"archived": "archived", "name": "PACK", "page": 2, "limit": 2},
        )

        assert response.status_code == 200
        body = response.json()
        assert _names(body) == ["Pack 1"]
        assert body["meta"] == {
            "total_count": 3,
            "page_count": 2,
            "current_page": 2,
            "per_page": 2,
        }
        assert body["links"]["prev"].endswith(
            "/api/task-lists?page=1&limit=2&archived=archived&name=PACK"
        )
        assert body["links"]["next"] is None

    async def test_an_unpaged_listing_carries_no_pagination(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        await seed_task_list(async_connection, "Packing")

        response = await authenticated_client.get(
            "/api/task-lists", params={"name": "pack"}
        )

        assert response.status_code == 200
        assert set(response.json()) == {"data"}

    @pytest.mark.parametrize(
        "params",
        [
            pytest.param({"page": 0}, id="page-zero"),
            pytest.param({"page": INT32_MAX + 1}, id="page-past-int32"),
            pytest.param({"limit": 0}, id="limit-zero"),
            pytest.param({"limit": 101}, id="limit-over-100"),
            pytest.param({"page": "two"}, id="page-not-a-number"),
        ],
    )
    async def test_an_out_of_range_page_or_limit_is_a_bad_request(
        self, authenticated_client: AsyncClient, params: dict[str, int | str]
    ) -> None:
        response = await authenticated_client.get("/api/task-lists", params=params)

        assert response.status_code == 400

    @pytest.mark.parametrize(
        "name",
        [
            pytest.param("   ", id="blank"),
            pytest.param("n" * (MAX_TASK_LIST_NAME_LENGTH + 1), id="too-long"),
        ],
    )
    async def test_a_blank_or_too_long_name_filter_is_refused_naming_the_field(
        self, authenticated_client: AsyncClient, name: str
    ) -> None:
        response = await authenticated_client.get(
            "/api/task-lists", params={"archived": "archived", "name": name}
        )

        assert response.status_code == 400
        error = _error(response.json())
        assert error["code"] == "TASK_VALIDATION_ERROR"
        assert error["meta"] == {"field": "name"}

    async def test_another_users_matching_lists_are_neither_listed_nor_counted(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        await seed_task_list(async_connection, "Pack mine", archived_at=ARCHIVED_AT)
        await seed_task_list(
            async_connection,
            "Pack theirs",
            user_id=OTHER_USER_ID,
            archived_at=ARCHIVED_AT,
        )

        response = await authenticated_client.get(
            "/api/task-lists",
            params={"archived": "archived", "name": "pack", "limit": 20},
        )

        assert _names(response.json()) == ["Pack mine"]
        assert response.json()["meta"]["total_count"] == 1


_COUNT_OUTBOX = "SELECT COUNT(*) FROM outbox_events"


def _move(index: object) -> dict[str, object]:
    return {"data": {"type": "task-list-moves", "attributes": {"index": index}}}


def _ids(response_json: dict[str, object]) -> list[int]:
    data = response_json["data"]
    assert isinstance(data, list)
    return [int(resource["id"]) for resource in data]


async def _seed_ids(connection: AsyncConnection, *names: str) -> list[int]:
    seeded = [await seed_task_list(connection, name) for name in names]
    return [each.id for each in seeded if each.id is not None]


class TestMoveTaskListEndpoint:
    async def test_moves_the_list_and_answers_the_active_lists_in_order(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        a, b, c = await _seed_ids(async_connection, "A", "B", "C")

        response = await authenticated_client.post(
            f"/api/task-lists/{a}/move", json=_move(2)
        )

        assert response.status_code == 200
        body = response.json()
        assert _ids(body) == [b, c, a]
        assert [r["attributes"]["position"] for r in body["data"]] == [0, 1, 2]
        assert all(r["type"] == "task-lists" for r in body["data"])
        assert body["data"][2]["links"]["self"].endswith(f"/api/task-lists/{a}")

        listing = await authenticated_client.get("/api/task-lists")
        assert _ids(listing.json()) == [b, c, a]

    async def test_archived_lists_are_left_out_of_the_answer(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        a = (await seed_task_list(async_connection, "A")).id
        await seed_task_list(async_connection, "Old trip", archived_at=ARCHIVED_AT)
        (b,) = await _seed_ids(async_connection, "B")

        response = await authenticated_client.post(
            f"/api/task-lists/{b}/move", json=_move(0)
        )

        assert _ids(response.json()) == [b, a]
        assert "Old trip" not in _names(response.json())

    async def test_an_index_past_the_end_moves_the_list_to_the_bottom(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        a, b = await _seed_ids(async_connection, "A", "B")

        response = await authenticated_client.post(
            f"/api/task-lists/{a}/move", json=_move(INT32_MAX)
        )

        assert response.status_code == 200
        assert _ids(response.json()) == [b, a]

    async def test_a_move_records_no_event(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        a, _ = await _seed_ids(async_connection, "A", "B")

        await authenticated_client.post(f"/api/task-lists/{a}/move", json=_move(1))

        assert await count(async_connection, _COUNT_OUTBOX, {}) == 0

    async def test_an_archived_list_is_refused_as_a_conflict(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        (a,) = await _seed_ids(async_connection, "A")
        archived = await seed_task_list(
            async_connection, "Old trip", archived_at=ARCHIVED_AT
        )

        response = await authenticated_client.post(
            f"/api/task-lists/{archived.id}/move", json=_move(0)
        )

        assert response.status_code == 409
        error = _error(response.json())
        assert error["code"] == "TASK_LIST_ARCHIVED"
        assert "unarchive" in str(error["detail"]).lower()
        listing = await authenticated_client.get("/api/task-lists?archived=all")
        assert _ids(listing.json()) == [a, archived.id]

    async def test_another_users_list_is_indistinguishable_from_a_missing_one(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        foreign = await seed_task_list(
            async_connection, "Theirs", user_id=OTHER_USER_ID
        )
        await _seed_ids(async_connection, "A")

        foreign_response = await authenticated_client.post(
            f"/api/task-lists/{foreign.id}/move", json=_move(0)
        )
        missing_response = await authenticated_client.post(
            f"/api/task-lists/{INT32_MAX}/move", json=_move(0)
        )

        assert foreign_response.status_code == missing_response.status_code == 404
        foreign_error = _error(foreign_response.json())
        assert foreign_error["code"] == "TASK_LIST_NOT_FOUND"
        assert foreign_error["detail"] == f"Task list with ID {foreign.id} not found"
        assert _error(missing_response.json())["code"] == "TASK_LIST_NOT_FOUND"
        assert "Theirs" not in foreign_response.text

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param(_move(-1), id="negative-index"),
            pytest.param(_move(INT32_MAX + 1), id="index-out-of-range"),
            pytest.param(_move("first"), id="non-integer-index"),
            pytest.param(_move(1.5), id="fractional-index"),
            pytest.param(
                {"data": {"type": "task-list-moves", "attributes": {}}},
                id="missing-index",
            ),
            pytest.param(
                {
                    "data": {
                        "type": "task-list-moves",
                        "attributes": {"index": 0, "position": 0},
                    }
                },
                id="unknown-attribute",
            ),
            pytest.param(
                {"data": {"type": "task-lists", "attributes": {"index": 0}}},
                id="another-resource-type",
            ),
            pytest.param({**_move(0), "x": 1}, id="unknown-envelope-member"),
        ],
    )
    async def test_a_malformed_body_is_refused_and_nothing_moves(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        body: dict[str, object],
    ) -> None:
        a, b = await _seed_ids(async_connection, "A", "B")

        response = await authenticated_client.post(
            f"/api/task-lists/{a}/move", json=body
        )

        assert response.status_code == 400
        assert response.json()["errors"][0]["code"] == "VALIDATION_ERROR"
        listing = await authenticated_client.get("/api/task-lists")
        assert _ids(listing.json()) == [a, b]

    @pytest.mark.parametrize("list_id", ["0", str(INT32_MAX + 1), "abc"])
    async def test_an_out_of_range_id_is_a_bad_request(
        self, authenticated_client: AsyncClient, list_id: str
    ) -> None:
        response = await authenticated_client.post(
            f"/api/task-lists/{list_id}/move", json=_move(0)
        )

        assert response.status_code == 400


class TestPublishedSchema:
    def test_the_icon_set_is_published_as_a_named_enum(
        self, test_settings: Settings
    ) -> None:
        """The icon picker takes its keys from here rather than a hand copy."""
        schemas = create_app(settings=test_settings).openapi()["components"]["schemas"]

        assert schemas["TaskIcon"]["enum"] == [icon.value for icon in TaskIcon]


async def _seed_counted_lists(conn: AsyncConnection) -> tuple[int, int, int]:
    """Packing (2 open, 1 done, 1 cancelled), Empty (none), Old (archived, 1
    open) — and another user's open task on a list of theirs."""
    packing = await seed_task_list(conn, "Packing")
    empty = await seed_task_list(conn, "Empty")
    old = await seed_task_list(conn, "Old", archived_at=ARCHIVED_AT)
    theirs = await seed_task_list(conn, "Theirs", user_id=OTHER_USER_ID)
    assert packing.id and empty.id and old.id and theirs.id
    for status in (
        TaskStatus.NOT_DONE,
        TaskStatus.NOT_DONE,
        TaskStatus.DONE,
        TaskStatus.CANCELLED,
    ):
        await create_list_task(conn, task_list_id=packing.id, status=status)
    await create_list_task(conn, task_list_id=old.id)
    await create_list_task(conn, task_list_id=theirs.id, user_id=OTHER_USER_ID)
    return packing.id, empty.id, old.id


def _counts(response_json: dict[str, Any]) -> dict[str, int]:
    return {
        resource["attributes"]["name"]: resource["attributes"]["open_task_count"]
        for resource in response_json["data"]
    }


class TestTheListingCarriesOpenTaskCounts:
    async def test_each_active_list_carries_its_open_task_count(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        """Done and cancelled tasks are not open; a list with none says 0."""
        await _seed_counted_lists(async_connection)

        response = await authenticated_client.get("/api/task-lists")

        assert response.status_code == 200
        assert _counts(response.json()) == {"Packing": 2, "Empty": 0}

    @pytest.mark.parametrize(
        ("archived", "expected"),
        [
            ("archived", {"Old": 1}),
            ("all", {"Packing": 2, "Empty": 0, "Old": 1}),
        ],
    )
    async def test_every_archived_filter_carries_the_counts(
        self,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        archived: str,
        expected: dict[str, int],
    ) -> None:
        await _seed_counted_lists(async_connection)

        response = await authenticated_client.get(
            "/api/task-lists", params={"archived": archived}
        )

        assert _counts(response.json()) == expected

    async def test_another_users_open_tasks_never_count_or_show(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        """Their task on my list is not one of my open tasks either."""
        mine = await seed_task_list(async_connection, "Mine")
        assert mine.id is not None
        await create_list_task(
            async_connection, task_list_id=mine.id, user_id=OTHER_USER_ID
        )
        theirs = await seed_task_list(async_connection, "Theirs", user_id=OTHER_USER_ID)
        assert theirs.id is not None
        await create_list_task(
            async_connection, task_list_id=theirs.id, user_id=OTHER_USER_ID
        )

        response = await authenticated_client.get(
            "/api/task-lists", params={"archived": "all"}
        )

        assert _counts(response.json()) == {"Mine": 0}

    async def test_an_unknown_filter_is_refused(
        self, authenticated_client: AsyncClient
    ) -> None:
        response = await authenticated_client.get(
            "/api/task-lists", params={"archived": "yes"}
        )

        assert response.status_code == 400

    async def test_a_single_list_read_is_unchanged(
        self, authenticated_client: AsyncClient, async_connection: AsyncConnection
    ) -> None:
        """The count is the listing's; reading one list answers the list alone."""
        packing_id, _, _ = await _seed_counted_lists(async_connection)

        response = await authenticated_client.get(f"/api/task-lists/{packing_id}")

        assert "open_task_count" not in response.json()["data"]["attributes"]
