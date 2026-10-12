"""Unit tests for CancelledRecurrenceTidier's serialisation.

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

from app.core.integrations.cancelled_recurrence_tidier import (
    CancelledRecurrenceTidier,
)


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
