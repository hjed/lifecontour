"""Unit tests for JournalMergeService."""

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.models.journals import (
    EventDateRange,
    FitnessMergeMode,
    Journal,
)

from app.core.journal.services.journal_merge_service import (
    JournalMergeService,
)
from app.core.tasks.models.repositories import TaskAnchorRepository


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
def mock_task_anchor_repo():
    """An anchor-repository mock held to the real port's surface.

    ``spec`` matters here: the merge service must call a method the port
    actually declares, so a typo or a method that only exists on the mock
    cannot pass. It also pins that merge reaches tasks through the *anchor*
    port, which cannot write a task's text, status or contacts, rather than
    through the full ``TaskRepository``.
    """
    return AsyncMock(spec=TaskAnchorRepository)


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
def merge_service(mock_journal_repo, mock_event_publisher, mock_task_anchor_repo):
    return JournalMergeService(
        journal_repo=mock_journal_repo,
        event_publisher=mock_event_publisher,
        task_anchor_repo=mock_task_anchor_repo,
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


_CALENDAR_COLUMN_TYPES = {
    "journal_id": "integer",
    "calendar_id": "uuid",
    "start_time": "time without time zone",
    "end_time": "time without time zone",
    "is_all_day": "boolean",
    "location": "character varying",
    "sync_invitees": "boolean",
    "timezone": "character varying",
}


def _column_type_rows(column_types: dict[str, str]) -> list[Any]:
    """Rows shaped like ``information_schema.columns`` answers."""
    rows = []
    for name, data_type in column_types.items():
        row = MagicMock()
        row.column_name = name
        row.data_type = data_type
        rows.append(row)
    return rows


def _mock_calendar_execute(query, params=None):
    """Two timed events on one calendar, plus the column types of their table."""
    from datetime import time

    q_str = str(query)
    mock_res = MagicMock()
    mock_res.fetchone.return_value = None
    mock_res.fetchall.return_value = []

    if "information_schema.columns" in q_str:
        mock_res.fetchall.return_value = _column_type_rows(_CALENDAR_COLUMN_TYPES)
    elif "journal_calendar_info" in q_str and "SELECT" in q_str:
        if params and (params.get("target_id") == 1 or params.get("id") == 1):
            row = MagicMock()
            row._mapping = {
                "journal_id": 1,
                "calendar_id": "cal-1",
                "start_time": time(9, 0),
                "end_time": time(10, 0),
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
                "start_time": time(19, 30),
                "end_time": time(22, 0),
                "is_all_day": False,
                "location": None,
                "sync_invitees": False,
                "timezone": None,
            }
            mock_res.fetchone.return_value = row
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
    async def test_merge_journals_accepts_lowercase_type_data_override_keys(
        self, merge_service, mock_journal_repo, mock_transaction
    ):
        """The read API returns lowercase type keys and the merge panel echoes them back."""
        target = create_test_journal(id=1, title="Target Title")
        source = create_test_journal(id=2, title="Source Title")

        mock_journal_repo.find_by_id.side_effect = lambda j_id: (
            target if j_id == 1 else source
        )
        mock_journal_repo.save.return_value = target

        mock_transaction.execute.side_effect = _mock_type_data_execute

        overrides = {"type_data": {"mood_rating": {"mood_value": 8}}}

        await merge_service.merge_journals(1, 2, mock_transaction, overrides=overrides)

        update_calls = [
            call
            for call in mock_transaction.execute.call_args_list
            if "UPDATE journal_mood_data" in str(call[0][0])
        ]

        assert len(update_calls) == 1
        assert update_calls[0][0][1]["mood_value"] == 8

    @pytest.mark.asyncio
    async def test_merge_binds_a_clock_time_override_as_a_time(
        self, merge_service, mock_journal_repo, mock_transaction
    ):
        """A JSON time override must reach the TIME column as a ``time``.

        The merge panel echoes back the read API's ``'19:30:00'``. Bound as a
        string, asyncpg rejects it outright ("'str' object has no attribute
        'hour'"), which surfaced as a 500 on every timed-event merge.
        """
        from datetime import time

        target = create_test_journal(id=1, title="Timed Event")
        source = create_test_journal(id=2, title="Other Timed Event")

        mock_journal_repo.find_by_id.side_effect = lambda j_id: (
            target if j_id == 1 else source
        )
        mock_journal_repo.save.return_value = target
        mock_transaction.execute.side_effect = _mock_calendar_execute

        overrides = {
            "type_data": {"event": {"start_time": "19:30:00", "end_time": "22:00:00"}}
        }

        await merge_service.merge_journals(1, 2, mock_transaction, overrides=overrides)

        update_calls = [
            call
            for call in mock_transaction.execute.call_args_list
            if "UPDATE journal_calendar_info" in str(call[0][0])
        ]

        assert len(update_calls) == 1
        params = update_calls[0][0][1]
        assert params["start_time"] == time(19, 30)
        assert params["end_time"] == time(22, 0)

    @pytest.mark.asyncio
    async def test_merge_rejects_an_unparseable_time_override(
        self, merge_service, mock_journal_repo, mock_transaction
    ):
        """Nonsense in a typed column is the caller's error, not a driver crash."""
        from core_shared.models.journals.exceptions import JournalValidationError

        target = create_test_journal(id=1, title="Timed Event")
        source = create_test_journal(id=2, title="Other Timed Event")

        mock_journal_repo.find_by_id.side_effect = lambda j_id: (
            target if j_id == 1 else source
        )
        mock_journal_repo.save.return_value = target
        mock_transaction.execute.side_effect = _mock_calendar_execute

        overrides = {"type_data": {"event": {"start_time": "half past seven"}}}

        with pytest.raises(JournalValidationError):
            await merge_service.merge_journals(
                1, 2, mock_transaction, overrides=overrides
            )

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

    @pytest.mark.asyncio
    async def test_merge_resolves_related_review_items(
        self, merge_service, mock_journal_repo, mock_transaction
    ):
        """Verifies that related review items are resolved during the merge."""
        target = create_test_journal(id=1, title="Target")
        source = create_test_journal(id=2, title="Source")

        mock_journal_repo.find_by_id.side_effect = lambda j_id: (
            target if j_id == 1 else source
        )
        mock_journal_repo.save.return_value = target

        await merge_service.merge_journals(1, 2, mock_transaction)

        execute_calls = mock_transaction.execute.call_args_list
        update_calls = [
            call
            for call in execute_calls
            if "UPDATE journal_review_items" in str(call[0][0])
        ]

        assert len(update_calls) == 1
        query_text = str(update_calls[0][0][0])
        params = update_calls[0][0][1]

        assert "status = 'resolved'" in query_text
        assert params["target_id"] == 1
        assert params["source_id"] == 2


TARGET_ID = 1
SOURCE_ID = 2

_FITNESS_COLUMNS = (
    "heart_rate_avg",
    "heart_rate_max",
    "distance",
    "elevation_gain",
    "elevation_loss",
    "duration",
    "calories",
    "strava_activity_id",
)


def _fitness_row(journal_id: int, **values):
    """Build a mock ``journal_fitness_data`` row with every column present."""
    row = MagicMock()
    row._mapping = {
        "journal_id": journal_id,
        **{col: values.get(col) for col in _FITNESS_COLUMNS},
        "created_at": datetime(2024, 1, 1),
        "updated_at": datetime(2024, 1, 1),
    }
    return row


def _fitness_execute(
    target_values: dict[str, Any] | None, source_values: dict[str, Any] | None
):
    """Mock ``execute`` serving fitness rows for the target and source journals.

    ``None`` stands for "this journal has no fitness row". Every other type
    table reports no row, so the merge only exercises the fitness path.
    """

    def _execute(query, params=None):
        q_str = str(query)
        mock_res = MagicMock()
        mock_res.fetchall.return_value = []
        mock_res.fetchone.return_value = None

        if "journal_fitness_data" in q_str and q_str.strip().startswith("SELECT"):
            params = params or {}
            if params.get("target_id") == TARGET_ID and target_values is not None:
                mock_res.fetchone.return_value = _fitness_row(
                    TARGET_ID, **target_values
                )
            elif params.get("source_id") == SOURCE_ID and source_values is not None:
                mock_res.fetchone.return_value = _fitness_row(
                    SOURCE_ID, **source_values
                )
        return mock_res

    return _execute


def _fitness_update_params(mock_transaction) -> dict[str, Any]:
    """Return the params of the single ``UPDATE journal_fitness_data`` call."""
    update_calls = [
        call
        for call in mock_transaction.execute.call_args_list
        if "UPDATE journal_fitness_data" in str(call[0][0])
    ]
    assert len(update_calls) == 1, (
        f"expected exactly one fitness update, got {len(update_calls)}"
    )
    params: dict[str, Any] = update_calls[0][0][1]
    return params


class TestAdditiveFitnessMerge:
    """Additive mode treats two fitness rows as two parts of one outing."""

    @pytest.fixture
    def merged_journals(self, mock_journal_repo):
        target = create_test_journal(id=TARGET_ID, title="Ride")
        source = create_test_journal(id=SOURCE_ID, title="Ride")
        mock_journal_repo.find_by_id.side_effect = lambda j_id: (
            target if j_id == TARGET_ID else source
        )
        mock_journal_repo.save.return_value = target
        return target, source

    @pytest.mark.asyncio
    async def test_sums_distance_duration_elevation_and_calories(
        self, merge_service, merged_journals, mock_transaction
    ):
        mock_transaction.execute.side_effect = _fitness_execute(
            {
                "distance": 5000,
                "duration": 1800,
                "elevation_gain": 50,
                "elevation_loss": 40,
                "calories": 300,
            },
            {
                "distance": 3000,
                "duration": 1200,
                "elevation_gain": 30,
                "elevation_loss": 25,
                "calories": 200,
            },
        )

        await merge_service.merge_journals(
            TARGET_ID,
            SOURCE_ID,
            mock_transaction,
            fitness_merge_mode=FitnessMergeMode.ADDITIVE,
        )

        params = _fitness_update_params(mock_transaction)
        assert params["distance"] == 8000
        assert params["duration"] == 3000
        assert params["elevation_gain"] == 80
        assert params["elevation_loss"] == 65
        assert params["calories"] == 500

    @pytest.mark.asyncio
    async def test_heart_rate_takes_max_and_duration_weighted_average(
        self, merge_service, merged_journals, mock_transaction
    ):
        mock_transaction.execute.side_effect = _fitness_execute(
            {"heart_rate_avg": 140, "heart_rate_max": 175, "duration": 1800},
            {"heart_rate_avg": 160, "heart_rate_max": 185, "duration": 1200},
        )

        await merge_service.merge_journals(
            TARGET_ID,
            SOURCE_ID,
            mock_transaction,
            fitness_merge_mode=FitnessMergeMode.ADDITIVE,
        )

        params = _fitness_update_params(mock_transaction)
        # (140 * 1800 + 160 * 1200) / 3000 = 148
        assert params["heart_rate_avg"] == 148
        assert params["heart_rate_max"] == 185

    @pytest.mark.asyncio
    async def test_heart_rate_average_falls_back_to_plain_mean(
        self, merge_service, merged_journals, mock_transaction
    ):
        """Without durations there is nothing to weight by, so weight equally."""
        mock_transaction.execute.side_effect = _fitness_execute(
            {"heart_rate_avg": 140},
            {"heart_rate_avg": 162},
        )

        await merge_service.merge_journals(
            TARGET_ID,
            SOURCE_ID,
            mock_transaction,
            fitness_merge_mode=FitnessMergeMode.ADDITIVE,
        )

        params = _fitness_update_params(mock_transaction)
        assert params["heart_rate_avg"] == 151  # (140 + 162) / 2

    @pytest.mark.asyncio
    async def test_a_recorded_zero_duration_still_weights_the_average(
        self, merge_service, merged_journals, mock_transaction
    ):
        """A zero-length part contributes its heart rate but no weight."""
        mock_transaction.execute.side_effect = _fitness_execute(
            {"heart_rate_avg": 100, "duration": 0},
            {"heart_rate_avg": 160, "duration": 1200},
        )

        await merge_service.merge_journals(
            TARGET_ID,
            SOURCE_ID,
            mock_transaction,
            fitness_merge_mode=FitnessMergeMode.ADDITIVE,
        )

        params = _fitness_update_params(mock_transaction)
        assert params["heart_rate_avg"] == 160

    @pytest.mark.asyncio
    async def test_two_zero_durations_fall_back_to_equal_weights(
        self, merge_service, merged_journals, mock_transaction
    ):
        """Weighting by zero everywhere would divide by zero."""
        mock_transaction.execute.side_effect = _fitness_execute(
            {"heart_rate_avg": 140, "duration": 0},
            {"heart_rate_avg": 162, "duration": 0},
        )

        await merge_service.merge_journals(
            TARGET_ID,
            SOURCE_ID,
            mock_transaction,
            fitness_merge_mode=FitnessMergeMode.ADDITIVE,
        )

        params = _fitness_update_params(mock_transaction)
        assert params["heart_rate_avg"] == 151

    @pytest.mark.asyncio
    async def test_missing_values_are_absent_not_zero(
        self, merge_service, merged_journals, mock_transaction
    ):
        """A null on one side yields the other side's value, never a null-as-zero sum."""
        mock_transaction.execute.side_effect = _fitness_execute(
            {"distance": None, "calories": 300},
            {"distance": 3000, "calories": None},
        )

        await merge_service.merge_journals(
            TARGET_ID,
            SOURCE_ID,
            mock_transaction,
            fitness_merge_mode=FitnessMergeMode.ADDITIVE,
        )

        params = _fitness_update_params(mock_transaction)
        assert params["distance"] == 3000
        # The target already holds the only calorie count, so nothing to write.
        assert params.get("calories", 300) == 300

    @pytest.mark.asyncio
    async def test_explicit_override_beats_the_computed_sum(
        self, merge_service, merged_journals, mock_transaction
    ):
        mock_transaction.execute.side_effect = _fitness_execute(
            {"distance": 5000},
            {"distance": 3000},
        )

        await merge_service.merge_journals(
            TARGET_ID,
            SOURCE_ID,
            mock_transaction,
            overrides={"type_data": {"FITNESS": {"distance": 7500}}},
            fitness_merge_mode=FitnessMergeMode.ADDITIVE,
        )

        params = _fitness_update_params(mock_transaction)
        assert params["distance"] == 7500

    @pytest.mark.asyncio
    async def test_target_keeps_its_own_strava_activity_id(
        self, merge_service, merged_journals, mock_transaction
    ):
        """The source's id survives as a sync_metadata link, not in the column."""
        mock_transaction.execute.side_effect = _fitness_execute(
            {"distance": 5000, "strava_activity_id": "111"},
            {"distance": 3000, "strava_activity_id": "222"},
        )

        await merge_service.merge_journals(
            TARGET_ID,
            SOURCE_ID,
            mock_transaction,
            fitness_merge_mode=FitnessMergeMode.ADDITIVE,
        )

        params = _fitness_update_params(mock_transaction)
        assert params.get("strava_activity_id", "111") == "111"

    @pytest.mark.asyncio
    async def test_source_strava_id_fills_an_empty_target(
        self, merge_service, merged_journals, mock_transaction
    ):
        mock_transaction.execute.side_effect = _fitness_execute(
            {"distance": 5000, "strava_activity_id": None},
            {"distance": 3000, "strava_activity_id": "222"},
        )

        await merge_service.merge_journals(
            TARGET_ID,
            SOURCE_ID,
            mock_transaction,
            fitness_merge_mode=FitnessMergeMode.ADDITIVE,
        )

        params = _fitness_update_params(mock_transaction)
        assert params["strava_activity_id"] == "222"

    @pytest.mark.asyncio
    async def test_replace_mode_keeps_the_targets_metrics(
        self, merge_service, merged_journals, mock_transaction
    ):
        """The default mode is unchanged: the target's numbers stand."""
        mock_transaction.execute.side_effect = _fitness_execute(
            {"distance": 5000, "calories": None},
            {"distance": 3000, "calories": 200},
        )

        await merge_service.merge_journals(TARGET_ID, SOURCE_ID, mock_transaction)

        params = _fitness_update_params(mock_transaction)
        assert params.get("distance", 5000) == 5000
        # Gaps are still filled from the source.
        assert params["calories"] == 200

    @pytest.mark.asyncio
    async def test_additive_mode_leaves_other_type_data_alone(
        self, merge_service, mock_journal_repo, mock_transaction
    ):
        """Mood values are descriptive, not additive — they keep conflict semantics."""
        target = create_test_journal(id=TARGET_ID, title="Ride")
        source = create_test_journal(id=SOURCE_ID, title="Ride")
        mock_journal_repo.find_by_id.side_effect = lambda j_id: (
            target if j_id == TARGET_ID else source
        )
        mock_journal_repo.save.return_value = target
        mock_transaction.execute.side_effect = _mock_type_data_execute

        await merge_service.merge_journals(
            TARGET_ID,
            SOURCE_ID,
            mock_transaction,
            fitness_merge_mode=FitnessMergeMode.ADDITIVE,
        )

        update_calls = [
            call
            for call in mock_transaction.execute.call_args_list
            if "UPDATE journal_mood_data" in str(call[0][0])
        ]
        # Target mood 5 wins over source mood 8; nothing is summed to 13.
        assert update_calls == []

    @pytest.mark.asyncio
    async def test_source_only_fitness_data_transfers_in_additive_mode(
        self, merge_service, merged_journals, mock_transaction
    ):
        """With no target row there is nothing to add to — the row moves across."""
        mock_transaction.execute.side_effect = _fitness_execute(
            None, {"distance": 3000}
        )

        await merge_service.merge_journals(
            TARGET_ID,
            SOURCE_ID,
            mock_transaction,
            fitness_merge_mode=FitnessMergeMode.ADDITIVE,
        )

        move_calls = [
            call
            for call in mock_transaction.execute.call_args_list
            if "UPDATE journal_fitness_data SET journal_id" in str(call[0][0])
        ]
        assert len(move_calls) == 1


class TestTaskLinkRepointing:
    """Merge moves a task's journal links onto the survivor.

    A task's two anchors are ``ON DELETE RESTRICT`` foreign keys and its
    intermediate links are ``ON DELETE CASCADE``, so *when* the re-point runs
    decides whether the merge raises an integrity error or quietly destroys
    links. These tests pin the orchestration — that it happens, once, with the
    ids the right way round, and before the source journal is deleted.

    The rules the statements themselves implement — duplicate collapse, the
    creating-equals-due outcome, cross-role redundancy — are set-based SQL over
    two tables, so they are pinned against the real schema in
    ``tests/integration/tasks/test_journal_merge_task_links_integration.py``
    instead. A primary-key violation and an ``ON DELETE CASCADE`` cannot happen
    against a mock.
    """

    @staticmethod
    def _arrange(mock_journal_repo):
        """Point the repo at a target (1) and a source (2)."""
        target = create_test_journal(id=1, title="Target Title")
        source = create_test_journal(id=2, title="Target Title")
        mock_journal_repo.find_by_id.side_effect = lambda j_id: (
            target if j_id == 1 else source
        )
        mock_journal_repo.save.return_value = target
        return target

    @pytest.mark.asyncio
    async def test_merge_repoints_task_links_onto_the_survivor(
        self, merge_service, mock_journal_repo, mock_task_anchor_repo, mock_transaction
    ):
        """The source's task links are re-pointed exactly once, ids not transposed."""
        self._arrange(mock_journal_repo)

        await merge_service.merge_journals(1, 2, mock_transaction)

        mock_task_anchor_repo.repoint_journal_links.assert_awaited_once_with(
            source_journal_id=2, target_journal_id=1
        )

    @pytest.mark.asyncio
    async def test_task_links_are_repointed_before_any_journal_is_written(
        self, merge_service, mock_journal_repo, mock_task_anchor_repo, mock_transaction
    ):
        """Order is the whole point, and it is load-bearing twice.

        Re-pointing after the **delete** would raise a foreign-key violation on
        the ``RESTRICT`` anchors, and the intermediate links would already have
        been cascaded away.

        Re-pointing after the **save** would be subtler and worse. The
        repository locks both journals in ascending id order, which only keeps
        two merges from deadlocking if nothing in the transaction locked a
        journal first — and ``save(target)`` locks the target. So the re-point
        has to come before every journal write, not merely before the delete,
        and this asserts the stronger order.
        """
        self._arrange(mock_journal_repo)
        order: list[str] = []

        def record(name: str):
            def record_call(*_args: Any, **_kwargs: Any) -> None:
                order.append(name)

            return record_call

        mock_task_anchor_repo.repoint_journal_links.side_effect = record("repoint")
        mock_journal_repo.save.side_effect = record("save_target")
        mock_journal_repo.delete.side_effect = record("delete_source")

        await merge_service.merge_journals(1, 2, mock_transaction)

        assert order == ["repoint", "save_target", "delete_source"]

    @pytest.mark.asyncio
    async def test_merge_touches_nothing_else_on_a_task(
        self, merge_service, mock_journal_repo, mock_task_anchor_repo, mock_transaction
    ):
        """Merge re-points links and stops there — it never changes a status.

        Asserted as "no other repository method was called" rather than "status
        is unchanged". The anchor port cannot change a status at all, so this
        also pins that the service has not quietly grown a second task
        dependency that could.
        """
        self._arrange(mock_journal_repo)

        await merge_service.merge_journals(1, 2, mock_transaction)

        called = {name for name, _args, _kwargs in mock_task_anchor_repo.mock_calls}
        assert called == {"repoint_journal_links"}

    @pytest.mark.asyncio
    async def test_merge_is_not_blocked_by_tasks(
        self, merge_service, mock_journal_repo, mock_task_anchor_repo, mock_transaction
    ):
        """Unlike delete, merge stays available — calendar sync depends on it."""
        target = self._arrange(mock_journal_repo)

        result = await merge_service.merge_journals(1, 2, mock_transaction)

        assert result is target
        mock_journal_repo.delete.assert_called_once_with(2)
        mock_task_anchor_repo.repoint_journal_links.assert_awaited_once()


class TestHasBaseConflicts:
    """Tests for the has_base_conflicts method that determines if two journals have conflicting fields."""

    def test_identical_journals_have_no_conflicts(self):
        """Journals with identical title, content, and date range have no base conflicts."""
        now = datetime(2024, 1, 1)
        target = Journal(
            id=1,
            user_id="user123",
            title="Same Title",
            content="Same Content",
            event_date_range=EventDateRange(start=now, end=now),
        )
        source = Journal(
            id=2,
            user_id="user123",
            title="Same Title",
            content="Same Content",
            event_date_range=EventDateRange(start=now, end=now),
        )

        service = JournalMergeService(
            journal_repo=AsyncMock(),
            event_publisher=AsyncMock(),
            task_anchor_repo=AsyncMock(spec=TaskAnchorRepository),
        )
        assert service.has_base_conflicts(target, source) is False

    def test_different_titles_are_a_conflict(self):
        """Journals with different non-empty titles have a base conflict."""
        now = datetime(2024, 1, 1)
        target = Journal(
            id=1,
            user_id="user123",
            title="Target Title",
            content="Same Content",
            event_date_range=EventDateRange(start=now, end=now),
        )
        source = Journal(
            id=2,
            user_id="user123",
            title="Source Title",
            content="Same Content",
            event_date_range=EventDateRange(start=now, end=now),
        )

        service = JournalMergeService(
            journal_repo=AsyncMock(),
            event_publisher=AsyncMock(),
            task_anchor_repo=AsyncMock(spec=TaskAnchorRepository),
        )
        assert service.has_base_conflicts(target, source) is True

    def test_different_content_is_a_conflict(self):
        """Journals with different non-empty content have a base conflict."""
        now = datetime(2024, 1, 1)
        target = Journal(
            id=1,
            user_id="user123",
            title="Same Title",
            content="Target Content",
            event_date_range=EventDateRange(start=now, end=now),
        )
        source = Journal(
            id=2,
            user_id="user123",
            title="Same Title",
            content="Source Content",
            event_date_range=EventDateRange(start=now, end=now),
        )

        service = JournalMergeService(
            journal_repo=AsyncMock(),
            event_publisher=AsyncMock(),
            task_anchor_repo=AsyncMock(spec=TaskAnchorRepository),
        )
        assert service.has_base_conflicts(target, source) is True

    def test_different_date_ranges_are_a_conflict(self):
        """Journals with different non-null date ranges have a base conflict."""
        target = Journal(
            id=1,
            user_id="user123",
            title="Same Title",
            content="Same Content",
            event_date_range=EventDateRange(
                start=datetime(2024, 1, 1), end=datetime(2024, 1, 1)
            ),
        )
        source = Journal(
            id=2,
            user_id="user123",
            title="Same Title",
            content="Same Content",
            event_date_range=EventDateRange(
                start=datetime(2024, 2, 1), end=datetime(2024, 2, 1)
            ),
        )

        service = JournalMergeService(
            journal_repo=AsyncMock(),
            event_publisher=AsyncMock(),
            task_anchor_repo=AsyncMock(spec=TaskAnchorRepository),
        )
        assert service.has_base_conflicts(target, source) is True

    def test_source_only_content_is_not_a_conflict(self):
        """When only the source has content and target is empty, it's not a conflict."""
        now = datetime(2024, 1, 1)
        target = Journal(
            id=1,
            user_id="user123",
            title="Same Title",
            content="",
            event_date_range=EventDateRange(start=now, end=now),
        )
        source = Journal(
            id=2,
            user_id="user123",
            title="Same Title",
            content="Source Content",
            event_date_range=EventDateRange(start=now, end=now),
        )

        service = JournalMergeService(
            journal_repo=AsyncMock(),
            event_publisher=AsyncMock(),
            task_anchor_repo=AsyncMock(spec=TaskAnchorRepository),
        )
        assert service.has_base_conflicts(target, source) is False

    def test_one_empty_content_is_not_a_conflict(self):
        """When one journal has empty content, it's not a conflict."""
        now = datetime(2024, 1, 1)
        target = Journal(
            id=1,
            user_id="user123",
            title="Same",
            content="Target Content",
            event_date_range=EventDateRange(start=now, end=now),
        )
        source = Journal(
            id=2,
            user_id="user123",
            title="Same",
            content="",
            event_date_range=EventDateRange(start=now, end=now),
        )

        service = JournalMergeService(
            journal_repo=AsyncMock(),
            event_publisher=AsyncMock(),
            task_anchor_repo=AsyncMock(spec=TaskAnchorRepository),
        )
        assert service.has_base_conflicts(target, source) is False
