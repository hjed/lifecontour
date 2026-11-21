"""Integration tests for the task list endpoints: create, read, list, update, move,
archive and unarchive.

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
from core_shared.models.tasks import MAX_TASK_LIST_NAME_LENGTH, TaskIcon
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.common.identifiers import INT32_MAX
from app.infrastructure.config import Settings
from app.main import create_app
from tests.integration.tasks.task_seeding import (
    OTHER_USER_ID,
    USER_ID,
    count,
    seed_task_list,
    task_list_events,
)

pytestmark = pytest.mark.integration

ARCHIVED_AT = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
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
