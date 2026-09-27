"""Unit tests for the journal type-data helper functions.

These helpers contain no transaction management — they orchestrate reads/writes
against the per-type repositories and raise domain validation errors. The tests
pin the GEAR_USAGE coverage added for issue #967 (servicifying the MCP
create/update journal-entry tools), so the composite ``JournalWriteService``
path persists GEAR_USAGE exactly like the old MCP tool path did.
"""

from datetime import UTC, date, datetime, time
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from core_shared.models.journals import (
    AbseilingData,
    AbseilPitchValidationError,
    CalendarInfo,
    ClimbingData,
    JournalType,
    JournalValidationError,
)
from core_shared.models.journals.gear_usage_data import GearUsageData, GearUsageItem

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
        assert saved.items == (
            GearUsageItem(
                gear_item_id=gear_item_id,
                checkout_date=datetime(2024, 1, 1, 8, 0, tzinfo=UTC),
            ),
        )

    @pytest.mark.asyncio
    async def test_missing_gear_item_id_on_create_raises(self) -> None:
        repo = AsyncMock()
        repo.find_by_journal_id.return_value = None

        with pytest.raises(JournalValidationError):
            await helpers.update_gear_usage_type_data(5, "GEAR_USAGE", {}, repo)

        repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_updates_the_existing_items_dates(self) -> None:
        repo = AsyncMock()
        gear_item_id = uuid4()
        existing = GearUsageData(
            journal_id=5,
            items=(
                GearUsageItem(
                    gear_item_id=gear_item_id,
                    checkout_date=datetime(2024, 1, 1, 8, 0, tzinfo=UTC),
                ),
            ),
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
        assert saved.items == (
            GearUsageItem(
                gear_item_id=gear_item_id,
                checkout_date=datetime(2024, 1, 1, 8, 0, tzinfo=UTC),
                checkin_date=datetime(2024, 1, 2, 18, 0, tzinfo=UTC),
            ),
        )

    @pytest.mark.asyncio
    async def test_another_gear_item_is_added_alongside(self) -> None:
        """The single-item form adds or updates one item and removes none."""
        repo = AsyncMock()
        first = GearUsageItem(
            gear_item_id=uuid4(),
            checkout_date=datetime(2024, 1, 1, 8, 0, tzinfo=UTC),
        )
        repo.find_by_journal_id.return_value = GearUsageData(
            journal_id=5, items=(first,)
        )
        added = uuid4()

        await helpers.update_gear_usage_type_data(
            5, "GEAR_USAGE", {"gear_item_id": str(added)}, repo
        )

        saved = repo.save.await_args.args[0]
        assert saved.items == (first, GearUsageItem(gear_item_id=added))

    @pytest.mark.asyncio
    async def test_a_named_item_has_only_its_sent_dates_patched(self) -> None:
        repo = AsyncMock()
        checkout = datetime(2024, 1, 1, 8, 0, tzinfo=UTC)
        first = GearUsageItem(gear_item_id=uuid4(), checkout_date=checkout)
        second = GearUsageItem(gear_item_id=uuid4())
        repo.find_by_journal_id.return_value = GearUsageData(
            journal_id=5, items=(first, second)
        )

        await helpers.update_gear_usage_type_data(
            5,
            "GEAR_USAGE",
            {
                "gear_item_id": str(first.gear_item_id),
                "checkin_date": "2024-01-02T18:00:00+00:00",
            },
            repo,
        )

        saved = repo.save.await_args.args[0]
        assert saved.items == (
            GearUsageItem(
                gear_item_id=first.gear_item_id,
                checkout_date=checkout,
                checkin_date=datetime(2024, 1, 2, 18, 0, tzinfo=UTC),
            ),
            second,
        )

    @pytest.mark.asyncio
    async def test_dates_alone_are_refused_when_several_items_could_be_meant(
        self,
    ) -> None:
        repo = AsyncMock()
        repo.find_by_journal_id.return_value = GearUsageData(
            journal_id=5,
            items=(
                GearUsageItem(gear_item_id=uuid4()),
                GearUsageItem(gear_item_id=uuid4()),
            ),
        )

        with pytest.raises(JournalValidationError) as caught:
            await helpers.update_gear_usage_type_data(
                5, "GEAR_USAGE", {"checkin_date": "2024-01-02T18:00:00+00:00"}, repo
            )

        assert caught.value.field == "gear_item_id"
        repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_items_replace_the_whole_list(self) -> None:
        repo = AsyncMock()
        kept = GearUsageItem(
            gear_item_id=uuid4(),
            checkout_date=datetime(2024, 1, 1, 8, 0, tzinfo=UTC),
        )
        repo.find_by_journal_id.return_value = GearUsageData(
            journal_id=5, items=(kept, GearUsageItem(gear_item_id=uuid4()))
        )
        added = uuid4()

        await helpers.update_gear_usage_type_data(
            5,
            "GEAR_USAGE",
            {
                "items": [
                    {"gear_item_id": str(added)},
                    # A listed item is complete: its omitted checkout is cleared.
                    {
                        "gear_item_id": str(kept.gear_item_id),
                        "checkin_date": "2024-01-02T18:00:00+00:00",
                    },
                ]
            },
            repo,
        )

        saved = repo.save.await_args.args[0]
        assert saved.journal_id == 5
        assert saved.items == (
            GearUsageItem(gear_item_id=added),
            GearUsageItem(
                gear_item_id=kept.gear_item_id,
                checkin_date=datetime(2024, 1, 2, 18, 0, tzinfo=UTC),
            ),
        )

    @pytest.mark.asyncio
    async def test_items_create_the_entry(self) -> None:
        repo = AsyncMock()
        repo.find_by_journal_id.return_value = None
        gear_item_id = uuid4()

        await helpers.update_gear_usage_type_data(
            5, "GEAR_USAGE", {"items": [{"gear_item_id": str(gear_item_id)}]}, repo
        )

        saved = repo.save.await_args.args[0]
        assert saved == GearUsageData(
            journal_id=5, items=(GearUsageItem(gear_item_id=gear_item_id),)
        )

    @pytest.mark.asyncio
    async def test_an_empty_list_empties_an_existing_entry(self) -> None:
        repo = AsyncMock()
        repo.find_by_journal_id.return_value = GearUsageData(
            journal_id=5, items=(GearUsageItem(gear_item_id=uuid4()),)
        )

        await helpers.update_gear_usage_type_data(5, "GEAR_USAGE", {"items": []}, repo)

        assert repo.save.await_args.args[0].items == ()

    @pytest.mark.asyncio
    async def test_a_new_entry_needs_a_gear_item(self) -> None:
        repo = AsyncMock()
        repo.find_by_journal_id.return_value = None

        with pytest.raises(JournalValidationError) as caught:
            await helpers.update_gear_usage_type_data(
                5, "GEAR_USAGE", {"items": []}, repo
            )

        assert caught.value.field == "items"
        repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_mixing_the_list_with_a_single_item_is_refused(self) -> None:
        repo = AsyncMock()
        repo.find_by_journal_id.return_value = None

        with pytest.raises(JournalValidationError) as caught:
            await helpers.update_gear_usage_type_data(
                5,
                "GEAR_USAGE",
                {
                    "items": [{"gear_item_id": str(uuid4())}],
                    "checkin_date": "2024-01-02T18:00:00+00:00",
                },
                repo,
            )

        assert caught.value.field == "items"

    @pytest.mark.asyncio
    async def test_a_bad_item_is_named_by_its_position(self) -> None:
        repo = AsyncMock()
        repo.find_by_journal_id.return_value = None

        with pytest.raises(JournalValidationError) as caught:
            await helpers.update_gear_usage_type_data(
                5,
                "GEAR_USAGE",
                {
                    "items": [
                        {"gear_item_id": str(uuid4())},
                        {
                            "gear_item_id": str(uuid4()),
                            "checkout_date": "2024-01-02T18:00:00+00:00",
                            "checkin_date": "2024-01-01T18:00:00+00:00",
                        },
                    ]
                },
                repo,
            )

        assert caught.value.field == "items[1].checkin_date"

    @pytest.mark.asyncio
    async def test_a_gear_item_listed_twice_is_refused(self) -> None:
        repo = AsyncMock()
        repo.find_by_journal_id.return_value = None
        gear_item_id = str(uuid4())

        with pytest.raises(JournalValidationError) as caught:
            await helpers.update_gear_usage_type_data(
                5,
                "GEAR_USAGE",
                {"items": [{"gear_item_id": gear_item_id}] * 2},
                repo,
            )

        assert caught.value.field == "items"


class TestUpdateAbseilingTypeData:
    """The consolidated ``template_id`` is read/written at the abseiling level
    (ITER16-001 Phase 2). It is co-located with the pitch data and must survive a
    pitch-only edit so the logbook keeps a durable template reference.
    """

    @pytest.mark.asyncio
    async def test_sets_template_id_on_existing_row(self) -> None:
        repo = AsyncMock()
        repo.find_by_journal_id.return_value = AbseilingData(journal_id=5)
        pitch_repo = AsyncMock()
        template_id = uuid4()

        await helpers.update_abseiling_type_data(
            5, "ABSEILING_TRIP", {"template_id": str(template_id)}, repo, pitch_repo
        )

        repo.save.assert_awaited_once()
        saved = repo.save.await_args.args[0]
        assert isinstance(saved, AbseilingData)
        assert saved.template_id == template_id

    @pytest.mark.asyncio
    async def test_pitch_only_edit_preserves_template_id(self) -> None:
        repo = AsyncMock()
        template_id = uuid4()
        repo.find_by_journal_id.return_value = AbseilingData(
            journal_id=5, template_id=template_id
        )
        pitch_repo = AsyncMock()

        await helpers.update_abseiling_type_data(
            5,
            "ABSEILING_TRIP",
            {
                "pitches": [
                    {"pitch_number": 1, "height": 20, "anchor_type": "double bolt"}
                ]
            },
            repo,
            pitch_repo,
        )

        repo.save.assert_awaited_once()
        saved = repo.save.await_args.args[0]
        assert saved.template_id == template_id

    @pytest.mark.asyncio
    async def test_template_id_can_be_cleared_explicitly(self) -> None:
        repo = AsyncMock()
        repo.find_by_journal_id.return_value = AbseilingData(
            journal_id=5, template_id=uuid4()
        )
        pitch_repo = AsyncMock()

        await helpers.update_abseiling_type_data(
            5, "ABSEILING_TRIP", {"template_id": None}, repo, pitch_repo
        )

        saved = repo.save.await_args.args[0]
        assert saved.template_id is None

    @pytest.mark.asyncio
    async def test_pitch_notes_are_persisted(self) -> None:
        repo = AsyncMock()
        repo.find_by_journal_id.return_value = AbseilingData(journal_id=5)
        pitch_repo = AsyncMock()

        await helpers.update_abseiling_type_data(
            5,
            "ABSEILING_TRIP",
            {"pitches": [{"pitch_number": 1, "height": 20, "notes": "wet start"}]},
            repo,
            pitch_repo,
        )

        pitch_repo.save.assert_awaited_once()
        saved_pitch = pitch_repo.save.await_args.args[0]
        assert saved_pitch.notes == "wet start"

    @pytest.mark.asyncio
    async def test_pitch_notes_absent_default_to_none(self) -> None:
        repo = AsyncMock()
        repo.find_by_journal_id.return_value = AbseilingData(journal_id=5)
        pitch_repo = AsyncMock()

        await helpers.update_abseiling_type_data(
            5,
            "ABSEILING_TRIP",
            {"pitches": [{"pitch_number": 1, "height": 20}]},
            repo,
            pitch_repo,
        )

        pitch_repo.save.assert_awaited_once()
        saved_pitch = pitch_repo.save.await_args.args[0]
        assert saved_pitch.notes is None

    @pytest.mark.asyncio
    async def test_pitch_type_is_persisted(self) -> None:
        repo = AsyncMock()
        repo.find_by_journal_id.return_value = AbseilingData(journal_id=5)
        pitch_repo = AsyncMock()

        await helpers.update_abseiling_type_data(
            5,
            "ABSEILING_TRIP",
            {"pitches": [{"pitch_number": 1, "height": 5, "pitch_type": "jump"}]},
            repo,
            pitch_repo,
        )

        pitch_repo.save.assert_awaited_once()
        saved_pitch = pitch_repo.save.await_args.args[0]
        assert saved_pitch.pitch_type == "jump"

    @pytest.mark.asyncio
    async def test_invalid_pitch_type_raises(self) -> None:
        repo = AsyncMock()
        repo.find_by_journal_id.return_value = AbseilingData(journal_id=5)
        pitch_repo = AsyncMock()

        with pytest.raises(AbseilPitchValidationError):
            await helpers.update_abseiling_type_data(
                5,
                "ABSEILING_TRIP",
                {"pitches": [{"pitch_number": 1, "pitch_type": "swim"}]},
                repo,
                pitch_repo,
            )

        pitch_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_invalid_template_id_raises(self) -> None:
        repo = AsyncMock()
        repo.find_by_journal_id.return_value = AbseilingData(journal_id=5)
        pitch_repo = AsyncMock()

        with pytest.raises(JournalValidationError):
            await helpers.update_abseiling_type_data(
                5, "ABSEILING_TRIP", {"template_id": "not-a-uuid"}, repo, pitch_repo
            )

        repo.save.assert_not_awaited()


class TestUpdateEventTypeData:
    """EVENT updates on the path both the REST and MCP update tools take."""

    @staticmethod
    def _repo_holding(calendar_info: CalendarInfo) -> AsyncMock:
        repo = AsyncMock()
        repo.find_by_journal_id.return_value = calendar_info
        return repo

    @pytest.mark.asyncio
    async def test_parses_time_strings(self) -> None:
        repo = self._repo_holding(
            CalendarInfo(journal_id=42, calendar_id=uuid4(), is_all_day=False)
        )

        await helpers.update_event_type_data(
            42,
            JournalType.EVENT.value,
            {"start_time": "09:15", "end_time": "10:45:30"},
            repo,
        )

        saved = repo.save.await_args.args[0]
        assert saved.start_time == time(9, 15)
        assert saved.end_time == time(10, 45, 30)

    @pytest.mark.asyncio
    async def test_cross_midnight_times_anchored_to_existing_event_dates(
        self,
    ) -> None:
        """A 23:00→01:00 update keeps the journal's two-day span, so it is valid.

        The loaded record carries the journal's event dates (via the journals
        JOIN); the update must keep them rather than judge the clock times alone.
        """
        repo = self._repo_holding(
            CalendarInfo(
                journal_id=42,
                calendar_id=uuid4(),
                start_time=time(20, 0),
                end_time=time(21, 0),
                event_start_date=date(2026, 6, 21),
                event_end_date=date(2026, 6, 22),
            )
        )

        await helpers.update_event_type_data(
            42,
            JournalType.EVENT.value,
            {"start_time": "23:00", "end_time": "01:00"},
            repo,
        )

        saved = repo.save.await_args.args[0]
        assert saved.start_time == time(23, 0)
        assert saved.end_time == time(1, 0)

    @pytest.mark.asyncio
    async def test_invalid_time_string_raises_before_saving(self) -> None:
        repo = self._repo_holding(
            CalendarInfo(journal_id=42, calendar_id=uuid4(), is_all_day=False)
        )

        with pytest.raises(JournalValidationError, match="start_time"):
            await helpers.update_event_type_data(
                42,
                JournalType.EVENT.value,
                {"start_time": "not-a-time", "end_time": "10:00"},
                repo,
            )

        repo.save.assert_not_awaited()
