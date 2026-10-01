"""Unit tests for JournalSeriesMergeService's series-level write order."""

import uuid
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.journal_series import JournalSeries
from app.core.journal.models.series_merge import SeriesMergePolicies
from app.core.journal.services.journal_series_merge_service import (
    JournalSeriesMergeService,
)

USER_ID = "user-1"

# @transactional treats a non-AsyncConnection as "no transaction management".
NO_TRANSACTION = cast(AsyncConnection, None)


async def test_series_are_locked_first_and_aliased_before_the_members_move() -> None:
    """The series-level writes run in the one order that keeps them safe.

    Both series rows are locked before either is read, so a merge sharing a
    series with this one runs before or after it, never interleaved. Aliasing
    locks every recurrence key the source answers for, which keeps a
    concurrent sync from adding a journal to the source after its members
    have moved, where deleting the series would drop it. So the aliasing comes
    before the move, and the delete last.
    """
    source = JournalSeries(id=uuid.uuid4(), user_id=USER_ID, name="Old")
    destination = JournalSeries(id=uuid.uuid4(), user_id=USER_ID, name="New")
    series_repo = AsyncMock()
    series_repo.find_by_id.side_effect = lambda series_id, _user: (
        source if series_id == source.id else destination
    )
    series_repo.get_member_journal_ids.return_value = []
    journal_repo = AsyncMock()
    journal_repo.find_by_ids_for_user.return_value = []
    date_resolver = AsyncMock()
    date_resolver.timezone_for.return_value = ZoneInfo("UTC")
    calls = MagicMock()
    calls.attach_mock(series_repo.lock_for_merge, "lock_for_merge")
    calls.attach_mock(series_repo.find_by_id, "find_by_id")
    calls.attach_mock(series_repo.alias_recurrences, "alias_recurrences")
    calls.attach_mock(series_repo.move_members, "move_members")
    calls.attach_mock(series_repo.delete, "delete")
    service = JournalSeriesMergeService(
        series_repo=series_repo,
        journal_repo=journal_repo,
        calendar_info_repo=AsyncMock(),
        date_resolver=date_resolver,
        journal_merge_service=AsyncMock(),
    )

    await service.merge_series(
        destination_series_id=cast(uuid.UUID, destination.id),
        source_series_id=cast(uuid.UUID, source.id),
        user_id=USER_ID,
        policies=SeriesMergePolicies(),
        pairs=[],
        transaction=NO_TRANSACTION,
    )

    names = [name for name, _args, _kwargs in calls.mock_calls]
    assert names == [
        "lock_for_merge",
        "find_by_id",
        "find_by_id",
        "alias_recurrences",
        "move_members",
        "delete",
    ]
    series_repo.lock_for_merge.assert_awaited_once_with(
        [destination.id, source.id], USER_ID
    )
