"""Unit tests for what a task list listing may ask for.

The name filter is one rule for REST and MCP alike, so it is held by the
domain value both surfaces build: trimmed, and refused when blank or longer
than any list name can be.
"""

import pytest
from core_shared.models.tasks import (
    MAX_TASK_LIST_NAME_LENGTH,
    TaskListArchiveFilter,
    TaskListListing,
    TaskListPageWindow,
    TaskListValidationError,
)


class TestTheNameFilter:
    def test_no_name_filters_nothing(self) -> None:
        listing = TaskListListing(archived=TaskListArchiveFilter.ARCHIVED)

        assert listing.name_contains is None

    def test_the_name_is_trimmed(self) -> None:
        listing = TaskListListing(
            archived=TaskListArchiveFilter.ARCHIVED, name_contains="  pack \t"
        )

        assert listing.name_contains == "pack"

    def test_a_name_at_the_list_name_bound_is_accepted(self) -> None:
        name = "n" * MAX_TASK_LIST_NAME_LENGTH

        listing = TaskListListing(
            archived=TaskListArchiveFilter.ALL, name_contains=f" {name} "
        )

        assert listing.name_contains == name

    @pytest.mark.parametrize("name", ["", "   ", "\t\n"])
    def test_a_blank_name_is_refused(self, name: str) -> None:
        with pytest.raises(TaskListValidationError) as refused:
            TaskListListing(archived=TaskListArchiveFilter.ACTIVE, name_contains=name)

        assert refused.value.field == "name"

    def test_a_name_longer_than_any_list_name_is_refused(self) -> None:
        with pytest.raises(TaskListValidationError) as refused:
            TaskListListing(
                archived=TaskListArchiveFilter.ACTIVE,
                name_contains="n" * (MAX_TASK_LIST_NAME_LENGTH + 1),
            )

        assert refused.value.field == "name"


class TestThePageWindow:
    def test_a_listing_is_unpaged_by_default(self) -> None:
        assert TaskListListing(archived=TaskListArchiveFilter.ACTIVE).page is None

    def test_a_page_window_carries_its_limit_and_offset(self) -> None:
        listing = TaskListListing(
            archived=TaskListArchiveFilter.ARCHIVED,
            page=TaskListPageWindow(limit=20, offset=40),
        )

        assert listing.page == TaskListPageWindow(limit=20, offset=40)
