"""Unit tests for JournalService._calculate_changed_fields (ITER12-002 Phase 2).

The service computes base-field ``changed_fields`` as ``{field: (old, new)}``
pairs by diffing the existing journal against the updated journal, mirroring the
contact ``_calculate_changed_fields`` pattern. Only fields that actually changed
appear, so "no change → no entry" falls out naturally.
"""

from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from core_shared.models.journals import EventDateRange, Journal

from app.core.journal.services.journal_service import JournalService


def _no_anchored_tasks() -> AsyncMock:
    """An anchor repository that reports nothing blocking a journal delete.

    The guard is a required collaborator, so every service built here has to
    supply one; these tests are about other behaviour, so it always answers
    "nothing is anchored". The delete guard has its own suite in
    ``test_journal_delete_guard.py``.
    """
    repo = AsyncMock()
    repo.find_tasks_anchored_to_journal.return_value = []
    return repo


@pytest.fixture
def journal_service() -> JournalService:
    return JournalService(
        journal_repo=AsyncMock(),
        event_publisher=AsyncMock(),
        task_anchor_repo=_no_anchored_tasks(),
    )


def _journal(
    *,
    title: str = "Title",
    content: str = "Content",
    parent_id: int | None = None,
    order: int | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    journal_id: int | None = 1,
) -> Journal:
    return Journal(
        id=journal_id,
        user_id="user123",
        title=title,
        content=content,
        event_date_range=EventDateRange(
            start=start or datetime(2024, 1, 1),
            end=end or datetime(2024, 1, 1),
        ),
        parent_id=parent_id,
        order=order,
    )


class TestCalculateChangedFields:
    def test_no_changes_returns_empty(self, journal_service: JournalService) -> None:
        existing = _journal()
        updated = _journal()
        assert journal_service._calculate_changed_fields(existing, updated) == {}

    def test_title_change_is_a_pair(self, journal_service: JournalService) -> None:
        existing = _journal(title="Old")
        updated = _journal(title="New")
        changed = journal_service._calculate_changed_fields(existing, updated)
        assert changed["title"] == ("Old", "New")
        assert set(changed) == {"title"}

    def test_content_change_is_a_pair(self, journal_service: JournalService) -> None:
        changed = journal_service._calculate_changed_fields(
            _journal(content="a"), _journal(content="b")
        )
        assert changed["content"] == ("a", "b")

    def test_parent_id_change_is_a_pair(self, journal_service: JournalService) -> None:
        changed = journal_service._calculate_changed_fields(
            _journal(parent_id=None), _journal(parent_id=5)
        )
        assert changed["parent_id"] == (None, 5)

    def test_order_change_is_a_pair(self, journal_service: JournalService) -> None:
        changed = journal_service._calculate_changed_fields(
            _journal(order=1), _journal(order=2)
        )
        assert changed["order"] == (1, 2)

    def test_event_date_range_change_is_a_serialisable_pair(
        self, journal_service: JournalService
    ) -> None:
        existing = _journal(start=datetime(2024, 1, 1), end=datetime(2024, 1, 1, 1))
        updated = _journal(start=datetime(2024, 2, 2), end=datetime(2024, 2, 2, 1))
        changed = journal_service._calculate_changed_fields(existing, updated)
        old_value, new_value = changed["event_date_range"]
        # Values must be JSON-round-trippable scalars (they travel through Redis).
        assert isinstance(old_value, str)
        assert isinstance(new_value, str)
        assert "2024-01-01" in old_value
        assert "2024-02-02" in new_value

    def test_event_date_range_unchanged_is_omitted(
        self, journal_service: JournalService
    ) -> None:
        existing = _journal(start=datetime(2024, 1, 1), end=datetime(2024, 1, 2))
        updated = _journal(start=datetime(2024, 1, 1), end=datetime(2024, 1, 2))
        assert "event_date_range" not in journal_service._calculate_changed_fields(
            existing, updated
        )

    def test_multiple_fields_change(self, journal_service: JournalService) -> None:
        existing = _journal(title="Old", content="a", order=1)
        updated = _journal(title="New", content="b", order=2)
        changed = journal_service._calculate_changed_fields(existing, updated)
        assert changed["title"] == ("Old", "New")
        assert changed["content"] == ("a", "b")
        assert changed["order"] == (1, 2)
