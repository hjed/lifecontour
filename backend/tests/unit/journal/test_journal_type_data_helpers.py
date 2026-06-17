"""Unit tests for the journal type-data helper functions.

These helpers contain no transaction management — they orchestrate reads/writes
against the per-type repositories and raise domain validation errors. The tests
pin the GEAR_USAGE coverage added for issue #967 (servicifying the MCP
create/update journal-entry tools), so the composite ``JournalWriteService``
path persists GEAR_USAGE exactly like the old MCP tool path did.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from core_shared.models.journals import (
    ClimbingData,
    JournalType,
    JournalValidationError,
)
from core_shared.models.journals.gear_usage_data import GearUsageData

from app.core.journal.services import journal_type_data_helpers as helpers

_CREATE_REPO_NAMES = [
    "mood_data_repo",
    "plan_data_repo",
    "travel_data_repo",
    "fitness_data_repo",
    "outdoor_activity_data_repo",
    "bushwalking_data_repo",
    "jogging_data_repo",
    "abseiling_data_repo",
    "abseil_pitch_repo",
    "canyoning_data_repo",
    "caving_data_repo",
    "canoeing_data_repo",
    "climbing_data_repo",
    "kayaking_data_repo",
    "skiing_data_repo",
    "snorkelling_data_repo",
    "diving_data_repo",
    "downhill_skiing_data_repo",
    "outdoor_planning_data_repo",
    "outdoor_training_data_repo",
    "gear_maintenance_data_repo",
    "gear_usage_data_repo",
]

_DELETE_REPO_NAMES = [
    "mood_data_repo",
    "plan_data_repo",
    "travel_data_repo",
    "photo_album_data_repo",
    "fitness_data_repo",
    "outdoor_activity_data_repo",
    "bushwalking_data_repo",
    "jogging_data_repo",
    "abseiling_data_repo",
    "abseil_pitch_repo",
    "canyoning_data_repo",
    "caving_data_repo",
    "canoeing_data_repo",
    "climbing_data_repo",
    "kayaking_data_repo",
    "skiing_data_repo",
    "snorkelling_data_repo",
    "diving_data_repo",
    "downhill_skiing_data_repo",
    "outdoor_planning_data_repo",
    "outdoor_training_data_repo",
    "gear_maintenance_data_repo",
    "gear_usage_data_repo",
]


def _mock_repos(names: list[str]) -> dict[str, AsyncMock]:
    return {name: AsyncMock() for name in names}


class TestUpdateClimbingTypeData:
    @pytest.mark.asyncio
    async def test_sets_indoor_flag_on_existing_row(self) -> None:
        repo = AsyncMock()
        repo.find_by_journal_id.return_value = ClimbingData(journal_id=5)

        await helpers.update_climbing_type_data(5, "CLIMBING", {"indoor": True}, repo)

        repo.save.assert_awaited_once()
        saved = repo.save.await_args.args[0]
        assert isinstance(saved, ClimbingData)
        assert saved.indoor is True

    @pytest.mark.asyncio
    async def test_indoor_is_independent_of_climbing_type(self) -> None:
        repo = AsyncMock()
        repo.find_by_journal_id.return_value = ClimbingData(
            journal_id=5, climbing_type="sport"
        )

        await helpers.update_climbing_type_data(5, "CLIMBING", {"indoor": True}, repo)

        saved = repo.save.await_args.args[0]
        assert saved.climbing_type == "sport"
        assert saved.indoor is True

    @pytest.mark.asyncio
    async def test_non_bool_indoor_raises(self) -> None:
        repo = AsyncMock()
        repo.find_by_journal_id.return_value = ClimbingData(journal_id=5)

        with pytest.raises(JournalValidationError):
            await helpers.update_climbing_type_data(
                5, "CLIMBING", {"indoor": "yes"}, repo
            )

        repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_top_rope_climbing_type_is_accepted(self) -> None:
        repo = AsyncMock()
        repo.find_by_journal_id.return_value = ClimbingData(journal_id=5)

        await helpers.update_climbing_type_data(
            5, "CLIMBING", {"climbing_type": "top_rope"}, repo
        )

        saved = repo.save.await_args.args[0]
        assert saved.climbing_type == "top_rope"


class TestGearUsageCreate:
    @pytest.mark.asyncio
    async def test_create_type_specific_data_gear_usage_is_noop(self) -> None:
        """GEAR_USAGE needs gear_item_id, so the default-row create is deferred."""
        repos = _mock_repos(_CREATE_REPO_NAMES)

        await helpers.create_type_specific_data(JournalType.GEAR_USAGE, 1, **repos)

        repos["gear_usage_data_repo"].save.assert_not_awaited()


class TestGearUsageDelete:
    @pytest.mark.asyncio
    async def test_delete_type_specific_data_gear_usage_deletes(self) -> None:
        repos = _mock_repos(_DELETE_REPO_NAMES)

        await helpers.delete_type_specific_data(JournalType.GEAR_USAGE, 7, **repos)

        repos["gear_usage_data_repo"].delete.assert_awaited_once_with(7)


class TestUpdateGearUsageTypeData:
    @pytest.mark.asyncio
    async def test_creates_when_missing_and_parses_iso_dates(self) -> None:
        repo = AsyncMock()
        repo.find_by_journal_id.return_value = None
        gear_item_id = uuid4()

        await helpers.update_gear_usage_type_data(
            5,
            "GEAR_USAGE",
            {
                "gear_item_id": str(gear_item_id),
                "checkout_date": "2024-01-01T08:00:00+00:00",
            },
            repo,
        )

        repo.save.assert_awaited_once()
        saved = repo.save.await_args.args[0]
        assert isinstance(saved, GearUsageData)
        assert saved.journal_id == 5
        assert saved.gear_item_id == gear_item_id
        assert saved.checkout_date == datetime(2024, 1, 1, 8, 0, tzinfo=UTC)

    @pytest.mark.asyncio
    async def test_missing_gear_item_id_on_create_raises(self) -> None:
        repo = AsyncMock()
        repo.find_by_journal_id.return_value = None

        with pytest.raises(JournalValidationError):
            await helpers.update_gear_usage_type_data(5, "GEAR_USAGE", {}, repo)

        repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_updates_existing_row(self) -> None:
        repo = AsyncMock()
        existing = GearUsageData(
            journal_id=5,
            gear_item_id=uuid4(),
            checkout_date=datetime(2024, 1, 1, 8, 0, tzinfo=UTC),
        )
        repo.find_by_journal_id.return_value = existing

        await helpers.update_gear_usage_type_data(
            5,
            "GEAR_USAGE",
            {"checkin_date": "2024-01-02T18:00:00+00:00"},
            repo,
        )

        repo.save.assert_awaited_once()
        saved = repo.save.await_args.args[0]
        assert saved.gear_item_id == existing.gear_item_id
        assert saved.checkin_date == datetime(2024, 1, 2, 18, 0, tzinfo=UTC)
