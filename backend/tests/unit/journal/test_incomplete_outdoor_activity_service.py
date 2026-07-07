"""Unit tests for IncompleteOutdoorActivityService."""

import datetime
from unittest.mock import AsyncMock

import pytest
from core_shared.models.journals import (
    CanoeingData,
    EventDateRange,
    IncompletenessReason,
    KayakingData,
    OutdoorActivityFacts,
)

from app.core.journal.services.incomplete_outdoor_activity_service import (
    IncompleteOutdoorActivityService,
)

USER_ID = "test-user-123"


def make_facts(
    journal_id: int,
    *,
    start: datetime.datetime | None = None,
    incomplete: bool = True,
) -> OutdoorActivityFacts:
    """Facts for a kayaking journal; incomplete = empty kayaking row."""
    event_start = start or datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    return OutdoorActivityFacts(
        journal_id=journal_id,
        title=f"Journal {journal_id}",
        event_date_range=EventDateRange(start=event_start, end=event_start),
        kayaking_data=KayakingData(
            journal_id=journal_id,
            water_type=None if incomplete else "river",
        ),
        participant_count=1,
    )


@pytest.fixture
def mock_facts_repo() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_dismissal_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.list_dismissed_journal_ids.return_value = set()
    return repo


@pytest.fixture
def service(
    mock_facts_repo: AsyncMock, mock_dismissal_repo: AsyncMock
) -> IncompleteOutdoorActivityService:
    return IncompleteOutdoorActivityService(
        facts_repo=mock_facts_repo, dismissal_repo=mock_dismissal_repo
    )


class TestListIncomplete:
    @pytest.mark.asyncio
    async def test_returns_incomplete_entries_with_reasons(
        self,
        service: IncompleteOutdoorActivityService,
        mock_facts_repo: AsyncMock,
    ) -> None:
        mock_facts_repo.list_outdoor_activity_facts.return_value = [make_facts(10)]

        result = await service.list_incomplete(USER_ID)

        assert len(result) == 1
        assert result[0].journal_id == 10
        assert result[0].reasons == [IncompletenessReason.NO_ATTRIBUTES]

    @pytest.mark.asyncio
    async def test_excludes_complete_journals(
        self,
        service: IncompleteOutdoorActivityService,
        mock_facts_repo: AsyncMock,
    ) -> None:
        mock_facts_repo.list_outdoor_activity_facts.return_value = [
            make_facts(10, incomplete=False),
            make_facts(11),
        ]

        result = await service.list_incomplete(USER_ID)

        assert [entry.journal_id for entry in result] == [11]

    @pytest.mark.asyncio
    async def test_filters_dismissed_journal_ids(
        self,
        service: IncompleteOutdoorActivityService,
        mock_facts_repo: AsyncMock,
        mock_dismissal_repo: AsyncMock,
    ) -> None:
        mock_facts_repo.list_outdoor_activity_facts.return_value = [
            make_facts(10),
            make_facts(11),
        ]
        mock_dismissal_repo.list_dismissed_journal_ids.return_value = {10}

        result = await service.list_incomplete(USER_ID)

        assert [entry.journal_id for entry in result] == [11]

    @pytest.mark.asyncio
    async def test_scopes_both_repo_calls_to_user(
        self,
        service: IncompleteOutdoorActivityService,
        mock_facts_repo: AsyncMock,
        mock_dismissal_repo: AsyncMock,
    ) -> None:
        mock_facts_repo.list_outdoor_activity_facts.return_value = []

        await service.list_incomplete(USER_ID)

        mock_facts_repo.list_outdoor_activity_facts.assert_awaited_once_with(USER_ID)
        mock_dismissal_repo.list_dismissed_journal_ids.assert_awaited_once_with(USER_ID)

    @pytest.mark.asyncio
    async def test_orders_newest_first(
        self,
        service: IncompleteOutdoorActivityService,
        mock_facts_repo: AsyncMock,
    ) -> None:
        january = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        march = datetime.datetime(2026, 3, 1, tzinfo=datetime.UTC)
        mock_facts_repo.list_outdoor_activity_facts.return_value = [
            make_facts(10, start=january),
            make_facts(11, start=march),
        ]

        result = await service.list_incomplete(USER_ID)

        assert [entry.journal_id for entry in result] == [11, 10]

    @pytest.mark.asyncio
    async def test_multi_reason_entry_carries_all_reasons(
        self,
        service: IncompleteOutdoorActivityService,
        mock_facts_repo: AsyncMock,
    ) -> None:
        facts = OutdoorActivityFacts(
            journal_id=12,
            title="Empty canoe trip",
            event_date_range=EventDateRange(
                start=datetime.datetime(2026, 2, 1, tzinfo=datetime.UTC),
                end=datetime.datetime(2026, 2, 1, tzinfo=datetime.UTC),
            ),
            canoeing_data=CanoeingData(journal_id=12),
            participant_count=0,
        )
        mock_facts_repo.list_outdoor_activity_facts.return_value = [facts]

        result = await service.list_incomplete(USER_ID)

        assert result[0].reasons == [
            IncompletenessReason.NO_ATTRIBUTES,
            IncompletenessReason.NO_PARTICIPANTS,
        ]
