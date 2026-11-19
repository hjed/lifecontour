"""Integration tests for the task list endpoints: create, read one, list.

The rules themselves (bottom placement, owner scoping, the event) are proven
against ``TaskListService`` and ``TaskListReadService`` in
``tests/integration/tasks/test_task_list_service_integration.py``. These tests
hold the REST surface to its own promises: the JSON:API shapes, the status code
and error code of each refusal, the provenance it records, and that another
user's list is answered exactly as a missing one.
"""

from datetime import UTC, datetime

import pytest
from core_shared.models.tasks import MAX_TASK_LIST_NAME_LENGTH, TaskIcon
from httpx import AsyncClient
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


class TestPublishedSchema:
    def test_the_icon_set_is_published_as_a_named_enum(
        self, test_settings: Settings
    ) -> None:
        """The icon picker takes its keys from here rather than a hand copy."""
        schemas = create_app(settings=test_settings).openapi()["components"]["schemas"]

        assert schemas["TaskIcon"]["enum"] == [icon.value for icon in TaskIcon]
