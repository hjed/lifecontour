"""Unit tests for the paging arguments of a list's closed-task read.

``find_closed_tasks_on_list`` pages with ``limit`` and ``offset``. An empty or
negative page is a caller's bug, refused before any statement reaches the
database — so the connection here fails the test if it is ever used.
"""

from dataclasses import FrozenInstanceError
from unittest.mock import AsyncMock

import pytest
from core_shared.models.tasks import TaskPage

from app.core.tasks.adapters.sql.task_repository import SqlTaskRepository

pytestmark = pytest.mark.unit


def _repository() -> tuple[SqlTaskRepository, AsyncMock]:
    connection = AsyncMock()
    connection.execute.side_effect = AssertionError("no statement may run")
    return SqlTaskRepository(connection), connection


@pytest.mark.parametrize(
    ("limit", "offset", "message"),
    [
        pytest.param(0, 0, "limit", id="empty-page"),
        pytest.param(-1, 0, "limit", id="negative-limit"),
        pytest.param(10, -1, "offset", id="negative-offset"),
    ],
)
async def test_an_impossible_page_is_refused_before_any_statement(
    limit: int, offset: int, message: str
) -> None:
    repository, connection = _repository()

    with pytest.raises(ValueError, match=message):
        await repository.find_closed_tasks_on_list(
            1, "user-1", limit=limit, offset=offset
        )

    connection.execute.assert_not_called()


def test_a_task_page_is_frozen() -> None:
    page = TaskPage(tasks=(), total=0)

    with pytest.raises(FrozenInstanceError):
        page.total = 3  # type: ignore[misc]
