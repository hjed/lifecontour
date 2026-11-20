"""Every task-list-by-id route refuses another user's list, and the table of
those routes is checked against the app itself.

The same guard ``test_journal_ownership.py`` keeps for ``{journal_id}`` routes,
which cannot see ``{list_id}`` ones. Each route is driven against a second
user's *real* list — an absent id would pass a query that forgot its owner
filter — and must answer 404, leak nothing of the list, and leave its row
exactly as it was, so a write that happened and *then* answered 404 cannot pass
either.

Adding a ``{list_id}`` route fails :class:`TestTaskListOwnershipCoverageIsComplete`
until it is listed in ``CROSS_USER_REQUESTS`` (or in ``COVERED_ELSEWHERE`` with
its reason).
"""

import json
from dataclasses import dataclass
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.config import Settings
from app.main import create_app
from tests.integration.tasks.task_seeding import OTHER_USER_ID, seed_task_list

pytestmark = pytest.mark.integration

OTHER_NAME = "Their Private List"
LIST_ROUTE = "/api/task-lists/{list_id}"


@dataclass(frozen=True)
class CrossUserRequest:
    """One request made against another user's list.

    ``route`` is the mounted path template verbatim, so the coverage tests can
    compare this table against the app's own routes.
    """

    method: str
    route: str
    body: dict[str, Any] | None = None

    def path(self, list_id: int) -> str:
        return self.route.replace("{list_id}", str(list_id))

    def filled_body(self, list_id: int) -> dict[str, Any] | None:
        if self.body is None:
            return None
        filled: dict[str, Any] = json.loads(
            json.dumps(self.body).replace("{list_id}", str(list_id))
        )
        return filled


CROSS_USER_REQUESTS: tuple[CrossUserRequest, ...] = (
    CrossUserRequest("GET", LIST_ROUTE),
    CrossUserRequest(
        "PATCH",
        LIST_ROUTE,
        {
            "data": {
                "type": "task-lists",
                "id": "{list_id}",
                "attributes": {"name": "Hijacked", "icon": None},
            }
        },
    ),
    # A valid index, so the refusal can only come from the ownership check.
    CrossUserRequest(
        "POST",
        LIST_ROUTE + "/move",
        body={"data": {"type": "task-list-moves", "attributes": {"index": 0}}},
    ),
)

# ``(method, route)`` -> why its ownership is asserted somewhere else instead.
COVERED_ELSEWHERE: dict[tuple[str, str], str] = {}


def _mounted_list_id_routes(app: Any) -> set[tuple[str, str]]:
    """Every ``(method, path)`` the app serves whose path carries a list id."""
    return {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if "{list_id}" in path
        for method in operations
        if method.upper() not in {"HEAD", "OPTIONS"}
    }


_SNAPSHOT = text("SELECT * FROM task_lists WHERE id = :list_id")


async def _snapshot(connection: AsyncConnection, list_id: int) -> dict[str, Any]:
    row = (await connection.execute(_SNAPSHOT, {"list_id": list_id})).one()
    return dict(row._mapping)


@pytest_asyncio.fixture
async def foreign_list_id(async_connection: AsyncConnection) -> int:
    foreign = await seed_task_list(async_connection, OTHER_NAME, user_id=OTHER_USER_ID)
    assert foreign.id is not None
    return foreign.id


class TestTaskListOwnershipIsEnforced:
    @pytest.mark.parametrize(
        "request_spec",
        CROSS_USER_REQUESTS,
        ids=lambda spec: f"{spec.method} {spec.route}",
    )
    async def test_another_users_list_reads_as_an_absent_one(
        self,
        request_spec: CrossUserRequest,
        authenticated_client: AsyncClient,
        async_connection: AsyncConnection,
        foreign_list_id: int,
    ) -> None:
        before = await _snapshot(async_connection, foreign_list_id)

        response = await authenticated_client.request(
            request_spec.method,
            request_spec.path(foreign_list_id),
            json=request_spec.filled_body(foreign_list_id),
        )

        assert response.status_code == 404, (
            f"{request_spec.method} {request_spec.route} answered "
            f"{response.status_code} for another user's list: {response.text[:400]}"
        )
        assert response.json()["errors"][0]["code"] == "TASK_LIST_NOT_FOUND"
        assert OTHER_NAME not in response.text
        assert await _snapshot(async_connection, foreign_list_id) == before


class TestTaskListOwnershipCoverageIsComplete:
    """The route table is checked against the app, not against memory."""

    def test_every_list_id_route_is_covered_by_an_ownership_test(
        self, test_settings: Settings
    ) -> None:
        mounted = _mounted_list_id_routes(create_app(settings=test_settings))
        tested = {(spec.method, spec.route) for spec in CROSS_USER_REQUESTS}
        uncovered = mounted - tested - set(COVERED_ELSEWHERE)

        assert not uncovered, (
            "these list-by-id operations have no ownership test: "
            f"{sorted(uncovered)}. Add each to CROSS_USER_REQUESTS, or to "
            "COVERED_ELSEWHERE with the reason it does not belong there."
        )

    def test_the_table_does_not_name_routes_the_app_does_not_serve(
        self, test_settings: Settings
    ) -> None:
        """A renamed or deleted route must not leave a test passing vacuously."""
        mounted = _mounted_list_id_routes(create_app(settings=test_settings))

        stale_requests = {
            (spec.method, spec.route)
            for spec in CROSS_USER_REQUESTS
            if (spec.method, spec.route) not in mounted
        }
        stale_exemptions = set(COVERED_ELSEWHERE) - mounted

        assert not stale_requests, f"no longer served: {sorted(stale_requests)}"
        assert not stale_exemptions, f"no longer served: {sorted(stale_exemptions)}"
