"""Unit tests for rendering a list's tasks: the open listing and a completed page.

The two answers differ in one way that matters to a client: the open listing is
the whole working set and advertises no page controls, while the completed one
is a page and carries the shared pagination ``meta`` and ``links``. Each row is
the same ``TaskReadResource`` every task read returns.
"""

from __future__ import annotations

import datetime

import pytest
from core_shared.models.tasks import (
    Task,
    TaskListRef,
    TaskReadModel,
    TaskReadModelPage,
    TaskStatus,
)

from app.api.tasks.schemas import (
    to_completed_list_tasks_response,
    to_list_tasks_response,
)

pytestmark = pytest.mark.unit

USER_ID = "test-user-123"
TASK_LIST_ID = 99
BASE_URL = "http://test"
COMPLETED_URL = f"{BASE_URL}/api/task-lists/{TASK_LIST_ID}/tasks/completed"
PACKING = TaskListRef(id=TASK_LIST_ID, name="Packing", icon=None, archived=False)


def list_model(
    task_id: int, *, status: TaskStatus = TaskStatus.NOT_DONE
) -> TaskReadModel:
    """An assembled list task with no journals."""
    return TaskReadModel(
        task=Task(
            id=task_id,
            user_id=USER_ID,
            text=f"task {task_id}",
            task_list_id=TASK_LIST_ID,
            position=task_id,
            due_date=datetime.date(2026, 8, 20),
            status=status,
        ),
        creating_journal=None,
        due_journal=None,
        intermediate_journals=(),
        contacts=(),
        task_list=PACKING,
        overdue=False,
        lapse_reason=None,
    )


class TestTheOpenListing:
    def test_rows_are_read_resources_in_the_given_order(self) -> None:
        page = TaskReadModelPage(models=(list_model(3), list_model(1)), total=2)

        response = to_list_tasks_response(page, BASE_URL)

        assert [row.id for row in response.data] == ["3", "1"]
        first = response.data[0]
        assert first.type == "tasks"
        assert first.attributes.task_list is not None
        assert first.attributes.task_list.name == "Packing"
        assert first.attributes.due_date == datetime.date(2026, 8, 20)
        assert first.links is not None
        assert first.links.self == f"{BASE_URL}/api/tasks/3"

    def test_meta_is_the_total_and_nothing_else(self) -> None:
        """No page controls: the open listing is not paged."""
        response = to_list_tasks_response(
            TaskReadModelPage(models=(list_model(1),), total=1), BASE_URL
        )

        assert response.model_dump(mode="json")["meta"] == {"total": 1}
        assert "links" not in response.model_dump()

    def test_an_empty_list_is_an_empty_listing(self) -> None:
        response = to_list_tasks_response(
            TaskReadModelPage(models=(), total=0), BASE_URL
        )

        assert response.data == []
        assert response.meta.total == 0


class TestTheCompletedPage:
    def test_rows_keep_their_status_so_cancelled_ones_are_marked(self) -> None:
        page = TaskReadModelPage(
            models=(
                list_model(9, status=TaskStatus.CANCELLED),
                list_model(4, status=TaskStatus.DONE),
            ),
            total=2,
        )

        response = to_completed_list_tasks_response(
            page, self_url=COMPLETED_URL, page=1, limit=20
        )

        assert [(row.id, row.attributes.status) for row in response.data] == [
            ("9", TaskStatus.CANCELLED),
            ("4", TaskStatus.DONE),
        ]

    def test_meta_carries_the_shared_pagination_fields(self) -> None:
        response = to_completed_list_tasks_response(
            TaskReadModelPage(models=(list_model(1), list_model(2)), total=5),
            self_url=COMPLETED_URL,
            page=2,
            limit=2,
        )

        assert response.meta.total_count == 5
        assert response.meta.page_count == 3
        assert response.meta.current_page == 2
        assert response.meta.per_page == 2

    def test_the_first_page_has_no_prev_and_a_next(self) -> None:
        response = to_completed_list_tasks_response(
            TaskReadModelPage(models=(list_model(1),), total=3),
            self_url=COMPLETED_URL,
            page=1,
            limit=1,
        )

        assert response.links.prev is None
        assert response.links.next == f"{COMPLETED_URL}?page=2&limit=1"
        assert response.links.self == f"{COMPLETED_URL}?page=1&limit=1"

    def test_the_last_page_has_a_prev_and_no_next(self) -> None:
        response = to_completed_list_tasks_response(
            TaskReadModelPage(models=(list_model(1),), total=3),
            self_url=COMPLETED_URL,
            page=3,
            limit=1,
        )

        assert response.links.prev == f"{COMPLETED_URL}?page=2&limit=1"
        assert response.links.next is None

    def test_a_page_past_the_end_is_empty_and_keeps_the_total(self) -> None:
        response = to_completed_list_tasks_response(
            TaskReadModelPage(models=(), total=3),
            self_url=COMPLETED_URL,
            page=9,
            limit=20,
        )

        assert response.data == []
        assert response.meta.total_count == 3
