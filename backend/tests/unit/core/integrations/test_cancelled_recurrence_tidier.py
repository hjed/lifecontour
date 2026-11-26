"""Unit tests for CancelledRecurrenceTidier's serialisation and list-task keep.

What it deletes is covered against a real database in
``test_cancelled_recurrence_keep_next``. What this pins is the ordering that
makes concurrent cancellations safe: two consumers cancelling adjacent
occurrences each mark their own first, so each must read the recurrence only
after the other's mark has committed - or both would see the other live and
keep their own.
"""

from unittest.mock import AsyncMock, MagicMock, call
from uuid import uuid4

import pytest
from core_shared.models.history import Provenance

from app.core.integrations.adapters.sql.journal_event_link_repository import (
    SeriesLinkedJournal,
)
from app.core.integrations.cancelled_recurrence_tidier import (
    CancelledRecurrenceTidier,
)
from app.core.journal.services.journal_service import JournalDeletePreview


@pytest.mark.asyncio
async def test_the_recurrence_is_locked_before_it_is_read() -> None:
    link_repo = AsyncMock()
    link_repo.find_journals_for_series.return_value = []
    calls = MagicMock()
    calls.attach_mock(link_repo.lock_recurrence, "lock")
    calls.attach_mock(link_repo.find_journals_for_series, "read")
    calendar_id = uuid4()
    tidier = CancelledRecurrenceTidier(AsyncMock(), link_repo, AsyncMock())

    await tidier.tidy(
        calendar_id=calendar_id,
        recurring_event_id="master-1",
        source=Provenance.GOOGLE_CALENDAR,
        changed_by="google",
    )

    assert calls.mock_calls[:2] == [
        call.lock(calendar_id, "master-1"),
        call.read(calendar_id=calendar_id, recurring_event_id="master-1"),
    ]


def _continuation() -> SeriesLinkedJournal:
    """A cancelled continuation the keep-next rule would delete."""
    return SeriesLinkedJournal(
        journal_id=42,
        user_id="test-user-123",
        calendar_id=uuid4(),
        external_event_id="instance-2",
        recurring_event_id="master-1",
        link_sync_status="cancelled",
        link_updated_at=None,
        journal_updated_at=None,
        event_date_range_start=None,
        event_date_range_end=None,
    )


def _unprotected_link_repo() -> AsyncMock:
    """Links that protect nothing, so only the list-task check can keep it."""
    link_repo = AsyncMock()
    link_repo.has_other_live_links.return_value = False
    link_repo.get_deletion_protection_facts.return_value = MagicMock(is_protected=False)
    link_repo.has_user_history.return_value = False
    return link_repo


class TestAListTaskKeepsAContinuation:
    """A list task linked to a journal is something the user added to it.

    Since a list task no longer blocks a journal delete — it loses its link —
    the delete guard's refusal can no longer stand in for that protection, and
    without this check a calendar sync would silently undate the user's task.
    ``preview_delete`` is set explicitly in each test: on a bare ``AsyncMock``
    its count would be a truthy mock, and the keep would pass for the wrong
    reason.
    """

    @pytest.mark.asyncio
    async def test_a_continuation_a_list_task_links_to_is_kept(self) -> None:
        journal_service = AsyncMock()
        journal_service.preview_delete.return_value = JournalDeletePreview(
            list_tasks_losing_link=1, lists_losing_association=0
        )
        tidier = CancelledRecurrenceTidier(
            AsyncMock(), _unprotected_link_repo(), journal_service
        )

        deleted = await tidier._delete_unless_protected(
            _continuation(), source=Provenance.GOOGLE_CALENDAR, changed_by="google"
        )

        assert deleted is False
        journal_service.preview_delete.assert_awaited_once_with(42)
        journal_service.delete_journal.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_continuation_no_list_task_links_to_is_deleted(self) -> None:
        journal_service = AsyncMock()
        journal_service.preview_delete.return_value = JournalDeletePreview(
            list_tasks_losing_link=0, lists_losing_association=0
        )
        tidier = CancelledRecurrenceTidier(
            AsyncMock(), _unprotected_link_repo(), journal_service
        )

        deleted = await tidier._delete_unless_protected(
            _continuation(), source=Provenance.GOOGLE_CALENDAR, changed_by="google"
        )

        assert deleted is True
        journal_service.delete_journal.assert_awaited_once()


@pytest.mark.asyncio
async def test_the_journal_is_locked_before_its_list_task_links_are_counted() -> None:
    """Counted unlocked, a link committed before the delete would be detached by
    a delete that had decided there were none to protect."""
    link_repo = _unprotected_link_repo()
    journal_service = AsyncMock()
    journal_service.preview_delete.return_value = JournalDeletePreview(
        list_tasks_losing_link=0, lists_losing_association=0
    )
    calls = MagicMock()
    calls.attach_mock(link_repo.lock_journal, "lock")
    calls.attach_mock(journal_service.preview_delete, "count")
    calls.attach_mock(journal_service.delete_journal, "delete")
    tidier = CancelledRecurrenceTidier(AsyncMock(), link_repo, journal_service)

    await tidier._delete_unless_protected(
        _continuation(), source=Provenance.GOOGLE_CALENDAR, changed_by="google"
    )

    assert [c[0] for c in calls.mock_calls] == ["lock", "count", "delete"]
