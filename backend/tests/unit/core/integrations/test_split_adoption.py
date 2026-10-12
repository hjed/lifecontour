"""Unit tests for SplitAdopter's lock ordering and its journal data.

What adoption does to the database is covered in
``test_series_split_adoption``. What this pins is that the old recurrence is
locked before adoption writes anything: the update re-points a link of that
recurrence and the re-plan may delete another, so a cancellation of the same
recurrence processed meanwhile must take the lock in the same order.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from core_shared.models.journals import EventDateRange, Journal
from core_shared.models.outbox_events import JournalSyncEventData

from app.core.integrations.adapters.sql.journal_event_link_repository import (
    SeriesLinkedJournal,
)
from app.core.integrations.split_adoption import SplitAdopter, adopted_journal_data

START = datetime(2026, 10, 16, 1, 10, tzinfo=UTC)


def _journal() -> Journal:
    return Journal(
        id=42,
        user_id="user-1",
        title="pilates (studio 2)",
        content="Bring a mat",
        event_date_range=EventDateRange(start=START, end=START),
    )


def _payload() -> JournalSyncEventData:
    return JournalSyncEventData(
        integration_source="google",
        external_event_id="new-1_20261016T012000Z",
        calendar_id=str(uuid4()),
        journal_data={"title": "Pilates", "content": "Studio 2", "user_id": "user-1"},
        calendar_info_data={},
        sync_timestamp=START.isoformat(),
        sync_action="updated",
        existing_journal_id=42,
        recurring_event_id="new-1",
        series_recurring_event_id="new-1",
        split_adopted_from="old-1",
    )


@pytest.mark.asyncio
async def test_the_old_recurrence_is_locked_before_anything_is_written() -> None:
    calendar_id = uuid4()
    link_repo = AsyncMock()
    link_repo.find_by_journal.return_value = SeriesLinkedJournal(
        journal_id=42,
        user_id="user-1",
        calendar_id=calendar_id,
        external_event_id="old-1_20261016T011000Z",
        recurring_event_id="old-1",
        link_sync_status="cancelled",
        link_updated_at=START,
        journal_updated_at=START,
        event_date_range_start=START,
        event_date_range_end=START,
    )
    series_repo = AsyncMock()
    calls = MagicMock()
    calls.attach_mock(link_repo.lock_recurrence, "lock")
    calls.attach_mock(series_repo.adopt_recurrence, "adopt")
    adopter = SplitAdopter(link_repo, series_repo, AsyncMock())

    await adopter.begin(journal=_journal(), calendar_id=calendar_id, payload=_payload())

    assert [c[0] for c in calls.mock_calls] == ["lock", "adopt"]
    assert calls.mock_calls[0].args == (calendar_id, "old-1")


def test_the_journal_keeps_its_title_and_notes() -> None:
    data = adopted_journal_data(_payload().journal_data, _journal())

    assert data == {"title": "pilates (studio 2)", "user_id": "user-1"}
