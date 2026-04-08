"""Unit tests for JournalMergeService."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.models.journals import (
    EventDateRange,
    Journal,
)

from app.core.journal.services.journal_merge_service import (
    JournalMergeService,
)


@pytest.fixture
def mock_journal_repo(mock_transaction):
    mock_repo = AsyncMock()
    mock_repo.get_ancestors.return_value = []
    mock_repo.conn = mock_transaction
    return mock_repo


@pytest.fixture
def mock_event_publisher():
    return AsyncMock()


@pytest.fixture
def mock_transaction():
    mock_tx = AsyncMock()
    # Mocking standard execute response for any select queries
    # to return empty rows unless overridden
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []

    # By default fetchone returns None for selects
    mock_result.fetchone.return_value = None
    mock_tx.execute.return_value = mock_result
    return mock_tx


@pytest.fixture
def merge_service(mock_journal_repo, mock_event_publisher):
    return JournalMergeService(
        journal_repo=mock_journal_repo,
        event_publisher=mock_event_publisher,
    )


def create_test_journal(
    id: int,
    title: str = "Test",
    content: str = "",
) -> Journal:
    now = datetime(2024, 1, 1)
    return Journal(
        id=id,
        user_id="user123",
        title=title,
        content=content,
        event_date_range=EventDateRange(start=now, end=now),
    )


def _mock_type_data_execute(query, params=None):
    q_str = str(query)
    mock_res = MagicMock()
    if "journal_types" in q_str and "SELECT" in q_str:
        row = MagicMock()
        row.type = "MOOD_RATING"
        mock_res.fetchall.return_value = [row]
        mock_res.fetchone.return_value = None
    elif "journal_mood_data" in q_str and "SELECT" in q_str:
        if params and (params.get("id") == 1 or params.get("target_id") == 1):
            row = MagicMock()
            row._mapping = {"journal_id": 1, "mood_value": 5, "energy_level": 5}
            mock_res.fetchone.return_value = row
        elif params and (params.get("id") == 2 or params.get("source_id") == 2):
            row = MagicMock()
            row._mapping = {"journal_id": 2, "mood_value": 8, "energy_level": 8}
            mock_res.fetchone.return_value = row
        else:
            mock_res.fetchone.return_value = None
        mock_res.fetchall.return_value = []
    else:
        mock_res.fetchone.return_value = None
        mock_res.fetchall.return_value = []
    return mock_res


class TestJournalMergeService:
    @pytest.mark.asyncio
    async def test_merge_journals_basic_fields(
        self, merge_service, mock_journal_repo, mock_transaction
    ):
        target = create_test_journal(
            id=1, title="Target Title", content="Target Content"
        )
        source = create_test_journal(
            id=2, title="Target Title", content="Source Content"
        )

        mock_journal_repo.find_by_id.side_effect = lambda j_id: (
            target if j_id == 1 else source
        )
        mock_journal_repo.save.return_value = target

        result = await merge_service.merge_journals(1, 2, mock_transaction)

        assert result.title == "Target Title"
        # Content should be concatenated
        assert result.content == "Target Content\n\n---\n\nSource Content"
        mock_journal_repo.save.assert_called_once()
        mock_journal_repo.delete.assert_called_once_with(2)

    @pytest.mark.asyncio
    async def test_merge_journals_resolves_differing_titles_with_target_title(
        self, merge_service, mock_journal_repo, mock_transaction
    ):
        target = create_test_journal(id=1, title="Target Title")
        source = create_test_journal(id=2, title="Source Title")

        mock_journal_repo.find_by_id.side_effect = lambda j_id: (
            target if j_id == 1 else source
        )
        mock_journal_repo.save.return_value = target

        result = await merge_service.merge_journals(1, 2, mock_transaction)

        assert result.title == "Target Title"
        mock_journal_repo.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_merge_relationship_queries_executed(
        self, merge_service, mock_journal_repo, mock_transaction, mock_event_publisher
    ):
        target = create_test_journal(id=1, title="Target Title")
        source = create_test_journal(id=2, title="Target Title")

        mock_journal_repo.find_by_id.side_effect = lambda j_id: (
            target if j_id == 1 else source
        )
        mock_journal_repo.save.return_value = target

        await merge_service.merge_journals(1, 2, mock_transaction)

        # Verify that execute was called multiple times for merging relationships
        execute_calls = mock_transaction.execute.call_args_list
        queries = [call[0][0].text for call in execute_calls]

        # We expect queries like UPDATE tags, contacts, duplicate removal, etc.
        assert any("journal_tag_assignments" in q for q in queries)
        assert any("journal_contact_relationships" in q for q in queries)
        assert any("journal_external_event_links" in q for q in queries)

    @pytest.mark.asyncio
    async def test_merge_journals_with_base_overrides(
        self, merge_service, mock_journal_repo, mock_transaction
    ):
        target = create_test_journal(
            id=1, title="Target Title", content="Target Content"
        )
        source = create_test_journal(
            id=2, title="Source Title", content="Source Content"
        )

        mock_journal_repo.find_by_id.side_effect = lambda j_id: (
            target if j_id == 1 else source
        )
        mock_journal_repo.save.return_value = target

        overrides = {
            "title": "Override Title",
            "content": "Override Content",
        }

        result = await merge_service.merge_journals(
            1, 2, mock_transaction, overrides=overrides
        )

        assert result.title == "Override Title"
        assert result.content == "Override Content"
        mock_journal_repo.save.assert_called_once()
        mock_journal_repo.delete.assert_called_once_with(2)

    @pytest.mark.asyncio
    async def test_merge_journals_with_type_data_overrides(
        self, merge_service, mock_journal_repo, mock_transaction
    ):
        target = create_test_journal(id=1, title="Target Title")
        source = create_test_journal(id=2, title="Source Title")

        mock_journal_repo.find_by_id.side_effect = lambda j_id: (
            target if j_id == 1 else source
        )
        mock_journal_repo.save.return_value = target

        mock_transaction.execute.side_effect = _mock_type_data_execute

        overrides = {"type_data": {"MOOD_RATING": {"mood_value": 8, "energy_level": 5}}}

        await merge_service.merge_journals(1, 2, mock_transaction, overrides=overrides)

        # Check that the transaction execute was called with an UPDATE for journal_mood_data
        execute_calls = mock_transaction.execute.call_args_list
        update_calls = [
            call
            for call in execute_calls
            if "UPDATE journal_mood_data" in str(call[0][0])
        ]

        assert len(update_calls) == 1
        query_text = str(update_calls[0][0][0])
        params = update_calls[0][0][1]

        assert "mood_value = :mood_value" in query_text
        assert (
            "energy_level = :energy_level" not in query_text
        )  # only overridden fields are updated
        assert params["mood_value"] == 8
        assert params["target_id"] == 1

    @pytest.mark.asyncio
    async def test_merge_allday_target_with_timed_source_clears_times(
        self, merge_service, mock_journal_repo, mock_transaction
    ):
        """When target is all-day and source has times, merged result stays all-day with null times."""
        target = create_test_journal(id=1, title="All Day Event")
        source = create_test_journal(id=2, title="Timed Event")

        mock_journal_repo.find_by_id.side_effect = lambda j_id: (
            target if j_id == 1 else source
        )
        mock_journal_repo.save.return_value = target

        from datetime import time

        def mock_calendar_execute(query, params=None):
            q_str = str(query)
            mock_res = MagicMock()
            if "journal_calendar_info" in q_str and "SELECT" in q_str:
                if params and (params.get("target_id") == 1 or params.get("id") == 1):
                    row = MagicMock()
                    row._mapping = {
                        "journal_id": 1,
                        "calendar_id": "cal-1",
                        "start_time": None,
                        "end_time": None,
                        "is_all_day": True,
                        "location": None,
                        "sync_invitees": False,
                        "timezone": None,
                    }
                    mock_res.fetchone.return_value = row
                elif params and (params.get("source_id") == 2 or params.get("id") == 2):
                    row = MagicMock()
                    row._mapping = {
                        "journal_id": 2,
                        "calendar_id": "cal-1",
                        "start_time": time(10, 0),
                        "end_time": time(11, 0),
                        "is_all_day": False,
                        "location": "Office",
                        "sync_invitees": False,
                        "timezone": None,
                    }
                    mock_res.fetchone.return_value = row
                else:
                    mock_res.fetchone.return_value = None
            else:
                mock_res.fetchone.return_value = None
            mock_res.fetchall.return_value = []
            return mock_res

        mock_transaction.execute.side_effect = mock_calendar_execute

        await merge_service.merge_journals(1, 2, mock_transaction)

        execute_calls = mock_transaction.execute.call_args_list
        update_calls = [
            call
            for call in execute_calls
            if "UPDATE journal_calendar_info" in str(call[0][0])
        ]

        assert len(update_calls) == 1
        params = update_calls[0][0][1]
        # All-day events should have times forced to None
        assert params.get("start_time") is None
        assert params.get("end_time") is None

    @pytest.mark.asyncio
    async def test_merge_timed_target_with_allday_source_stays_valid(
        self, merge_service, mock_journal_repo, mock_transaction
    ):
        """When target has times and source is all-day, merged result keeps times and stays timed."""
        target = create_test_journal(id=1, title="Timed Event")
        source = create_test_journal(id=2, title="All Day Event")

        mock_journal_repo.find_by_id.side_effect = lambda j_id: (
            target if j_id == 1 else source
        )
        mock_journal_repo.save.return_value = target

        from datetime import time

        def mock_calendar_execute(query, params=None):
            q_str = str(query)
            mock_res = MagicMock()
            if "journal_calendar_info" in q_str and "SELECT" in q_str:
                if params and (params.get("target_id") == 1 or params.get("id") == 1):
                    row = MagicMock()
                    row._mapping = {
                        "journal_id": 1,
                        "calendar_id": "cal-1",
                        "start_time": time(14, 0),
                        "end_time": time(15, 0),
                        "is_all_day": False,
                        "location": None,
                        "sync_invitees": False,
                        "timezone": None,
                    }
                    mock_res.fetchone.return_value = row
                elif params and (params.get("source_id") == 2 or params.get("id") == 2):
                    row = MagicMock()
                    row._mapping = {
                        "journal_id": 2,
                        "calendar_id": "cal-1",
                        "start_time": None,
                        "end_time": None,
                        "is_all_day": True,
                        "location": "Park",
                        "sync_invitees": True,
                        "timezone": None,
                    }
                    mock_res.fetchone.return_value = row
                else:
                    mock_res.fetchone.return_value = None
            else:
                mock_res.fetchone.return_value = None
            mock_res.fetchall.return_value = []
            return mock_res

        mock_transaction.execute.side_effect = mock_calendar_execute

        await merge_service.merge_journals(1, 2, mock_transaction)

        execute_calls = mock_transaction.execute.call_args_list
        update_calls = [
            call
            for call in execute_calls
            if "UPDATE journal_calendar_info" in str(call[0][0])
        ]

        # Should have an update (at minimum for location from source)
        assert len(update_calls) == 1
        params = update_calls[0][0][1]
        # Target keeps its times, so is_all_day should NOT be set to True
        # The merged state should remain is_all_day=False with existing times
        assert "is_all_day" not in params or params.get("is_all_day") is not True
