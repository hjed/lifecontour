"""Unit tests for JournalWriteService composite writes.

The ``@transactional`` decorator is a no-op when ``transaction`` is not a real
``AsyncConnection`` (these tests pass mocks), so the tests exercise the
orchestration and atomicity contract directly: every sub-write runs inside the
single composite call, and a mid-write failure propagates (so the surrounding
unit of work would roll the whole journal back) without running later steps.
"""

from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from core_shared.models.history import Provenance
from core_shared.models.journals import (
    BushwalkingData,
    BushwalkingDataValidationError,
    EventDateRange,
    Journal,
    JournalContactRelationshipType,
    JournalDomainError,
    JournalType,
    JournalValidationError,
    MoodData,
    MoodDataValidationError,
    OutdoorActivityData,
    OutdoorActivityDataValidationError,
)
from core_shared.models.journals.constants import MAX_ROLE_LENGTH
from core_shared.models.journals.gear_usage_data import GearUsageData

from app.core.journal.models.journal_tag import JournalTag
from app.core.journal.services.journal_write_service import JournalWriteService


@pytest.fixture
def mock_journal_service():
    service = AsyncMock()
    service.add_type_to_journal.return_value = []
    return service


@pytest.fixture
def mock_journal_contact_service():
    return AsyncMock()


@pytest.fixture
def mock_transaction():
    return AsyncMock()


@pytest.fixture
def mock_tag_service():
    return AsyncMock()


@pytest.fixture
def write_service(mock_journal_service, mock_journal_contact_service, mock_tag_service):
    """Build a JournalWriteService with all repos/services mocked."""
    repos = {name: AsyncMock() for name in _REPO_PARAM_NAMES}
    return JournalWriteService(
        journal_service=mock_journal_service,
        journal_contact_service=mock_journal_contact_service,
        tag_service=mock_tag_service,
        event_publisher=AsyncMock(),
        **repos,
    )


_REPO_PARAM_NAMES = [
    "calendar_info_repo",
    "photo_album_data_repo",
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
    "tag_repo",
]


def _journal(journal_id: int | None = None) -> Journal:
    return Journal(
        id=journal_id,
        user_id="user-1",
        title="Trip",
        content="",
        event_date_range=EventDateRange(
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
        ),
    )


class TestCreateJournal:
    @pytest.mark.asyncio
    async def test_create_journal_orchestrates_all_steps(
        self,
        write_service,
        mock_journal_service,
        mock_journal_contact_service,
        mock_transaction,
    ):
        """create_journal creates the journal then types, type-data and contacts."""
        created = _journal(journal_id=42)
        mock_journal_service.create_journal.return_value = created
        # MOOD_RATING has no dependencies, so a single type is returned.
        mock_journal_service.add_type_to_journal.return_value = [
            JournalType.MOOD_RATING
        ]
        # mood data repo: no existing row, so a default row is created.
        write_service.mood_data_repo.find_by_journal_id.return_value = None

        contacts = [
            {"attributes": {"contact_id": "5", "relationship_type": "PARTICIPANT"}}
        ]

        result = await write_service.create_journal(
            _journal(),
            ["mood_rating"],
            {"mood_rating": {"mood_value": 4}},
            contacts,
            mock_transaction,
            changed_by="ui",
        )

        assert result is created
        mock_journal_service.create_journal.assert_awaited_once()
        mock_journal_service.add_type_to_journal.assert_awaited_once()
        # type-data processing persisted the mood row
        assert write_service.mood_data_repo.save.await_count >= 1
        # contact relationship was added through the contact service
        mock_journal_contact_service.add_contact_to_journal.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_journal_rolls_back_on_type_data_failure(
        self, write_service, mock_journal_service, mock_transaction
    ):
        """A failure during type-data processing propagates and stops later steps.

        The atomicity contract: the exception bubbles out of the single composite
        call so the enclosing unit of work rolls back the whole journal. The
        contact-relationship step (which runs after type-data) must NOT run.
        """
        created = _journal(journal_id=42)
        mock_journal_service.create_journal.return_value = created
        mock_journal_service.add_type_to_journal.return_value = [
            JournalType.MOOD_RATING
        ]
        write_service.mood_data_repo.find_by_journal_id.return_value = None
        write_service.mood_data_repo.save.side_effect = RuntimeError("db down")

        with pytest.raises(RuntimeError, match="db down"):
            await write_service.create_journal(
                _journal(),
                ["mood_rating"],
                {"mood_rating": {"mood_value": 4}},
                [
                    {
                        "attributes": {
                            "contact_id": "5",
                            "relationship_type": "PARTICIPANT",
                        }
                    }
                ],
                mock_transaction,
            )

        # The later contact-processing step never ran.
        write_service.journal_contact_service.add_contact_to_journal.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_create_journal_skips_invalid_type_strings(
        self, write_service, mock_journal_service, mock_transaction
    ):
        """Invalid type strings are skipped rather than raising."""
        created = _journal(journal_id=42)
        mock_journal_service.create_journal.return_value = created

        await write_service.create_journal(
            _journal(),
            ["not_a_real_type"],
            None,
            None,
            mock_transaction,
        )

        # No type was added because parsing failed and was swallowed.
        mock_journal_service.add_type_to_journal.assert_not_awaited()


class TestProcessEventTypeData:
    @pytest.mark.asyncio
    async def test_cross_midnight_event_anchored_to_journal_date_range(
        self, write_service, mock_journal_service, mock_transaction
    ):
        """A cross-midnight event (23:00→01:00) is persisted, not rejected.

        CalendarInfo carries clock-only times, so the create path must anchor
        them to the journal's event date range (which spans two days here) or the
        start<=end validation wrongly rejects the event with
        CALENDAR_INFO_VALIDATION_ERROR.
        """
        journal = Journal(
            id=42,
            user_id="user-1",
            title="Late event",
            content="",
            event_date_range=EventDateRange(
                start=datetime(2026, 6, 21, 23, 0, tzinfo=UTC),
                end=datetime(2026, 6, 22, 1, 0, tzinfo=UTC),
            ),
        )
        mock_journal_service.journal_repo.find_by_id.return_value = journal

        await write_service._process_journal_type_data(
            42,
            {
                "event": {
                    "calendar_id": str(uuid4()),
                    "start_time": "23:00",
                    "end_time": "01:00",
                }
            },
            mock_transaction,
        )

        saved = write_service.calendar_info_repo.save.await_args.args[0]
        assert saved.start_time.hour == 23
        assert saved.end_time.hour == 1


class TestUpdatePhotoAlbumTypeData:
    @pytest.mark.asyncio
    async def test_photo_album_data_is_rejected_without_publishing(
        self, write_service: JournalWriteService, mock_transaction: AsyncMock
    ) -> None:
        """PHOTO_ALBUM data belongs to Immich album sync, so an edit fails fast.

        A validation error (not a silent no-op) is what lets the REST and MCP
        callers tell the user nothing was saved.
        """
        with pytest.raises(JournalValidationError, match="managed by Immich"):
            await write_service.update_type_data(
                42,
                JournalType.PHOTO_ALBUM,
                {"immich_album_id": "album-123"},
                mock_transaction,
            )

        cast(AsyncMock, write_service.event_publisher).publish.assert_not_awaited()


class TestDeleteJournal:
    @pytest.mark.asyncio
    async def test_delete_journal_delegates(
        self, write_service, mock_journal_service, mock_transaction
    ):
        await write_service.delete_journal(7, mock_transaction, changed_by="ui")
        mock_journal_service.delete_journal.assert_awaited_once()


class TestRemoveType:
    @pytest.mark.asyncio
    async def test_remove_type_removes_and_deletes_data(
        self, write_service, mock_journal_service, mock_transaction
    ):
        await write_service.remove_type(
            7, JournalType.MOOD_RATING, mock_transaction, changed_by="ui"
        )
        mock_journal_service.remove_type_from_journal.assert_awaited_once()
        write_service.mood_data_repo.delete.assert_awaited_once_with(7)


class TestUpdateTypeData:
    @pytest.mark.asyncio
    async def test_update_type_data_mood(self, write_service, mock_transaction):
        """update_type_data for MOOD_RATING updates the mood row.

        A real entity rather than a mock: the update rebuilds it so the
        entity's own bounds run, and a mock would accept anything.
        """
        write_service.mood_data_repo.find_by_journal_id.return_value = MoodData(
            journal_id=7
        )

        await write_service.update_type_data(
            7, JournalType.MOOD_RATING, {"mood_value": 5}, mock_transaction
        )

        write_service.mood_data_repo.save.assert_awaited_once()
        assert write_service.mood_data_repo.save.await_args.args[0].mood_value == 5

    @pytest.mark.asyncio
    async def test_update_type_data_gear_usage(self, write_service, mock_transaction):
        """update_type_data for GEAR_USAGE writes via the gear-usage repo.

        Regression guard: the single-field type-data endpoint must dispatch
        GEAR_USAGE rather than rejecting it with "no type-specific data".
        """
        existing = GearUsageData(
            journal_id=7,
            gear_item_id=uuid4(),
            checkout_date=datetime(2024, 1, 1, 8, 0, tzinfo=UTC),
        )
        write_service.gear_usage_data_repo.find_by_journal_id.return_value = existing

        await write_service.update_type_data(
            7,
            JournalType.GEAR_USAGE,
            {"checkin_date": "2024-01-02T18:00:00+00:00"},
            mock_transaction,
        )

        write_service.gear_usage_data_repo.save.assert_awaited_once()


class TestCreateJournalTags:
    """Tag assignment routes through JournalTagService so events are published.

    Find-or-create by name stays here (it is a write-service concern); the
    junction write and its ``JournalTagAssigned`` event belong to the tag service,
    so these tests assert the delegation and the provenance passed with it.
    """

    @pytest.mark.asyncio
    async def test_finds_existing_tag_and_assigns_without_saving(
        self, write_service, mock_journal_service, mock_tag_service, mock_transaction
    ):
        """An existing tag (by name) is assigned, not re-created."""
        mock_journal_service.create_journal.return_value = _journal(journal_id=42)
        existing_tag = JournalTag(id=uuid4(), name="alpha", color="#123456")
        write_service.tag_repo.find_by_name.return_value = existing_tag

        await write_service.create_journal(
            _journal(), None, None, None, mock_transaction, tags=["alpha"]
        )

        write_service.tag_repo.save.assert_not_awaited()
        mock_tag_service.assign_tag.assert_awaited_once_with(
            42,
            existing_tag.id,
            mock_transaction,
            source=Provenance.SYSTEM,
            changed_by="system",
        )

    @pytest.mark.asyncio
    async def test_creates_missing_tag_then_assigns(
        self, write_service, mock_journal_service, mock_tag_service, mock_transaction
    ):
        """A tag name with no existing row is created (grey default) then assigned."""
        mock_journal_service.create_journal.return_value = _journal(journal_id=42)
        write_service.tag_repo.find_by_name.return_value = None
        created_tag = JournalTag(id=uuid4(), name="beta", color="#808080")
        write_service.tag_repo.save.return_value = created_tag

        await write_service.create_journal(
            _journal(), None, None, None, mock_transaction, tags=["beta"]
        )

        write_service.tag_repo.save.assert_awaited_once()
        saved = write_service.tag_repo.save.await_args.args[0]
        assert saved.name == "beta"
        assert saved.color == "#808080"
        assert mock_tag_service.assign_tag.await_args.args[:2] == (42, created_tag.id)

    @pytest.mark.asyncio
    async def test_passes_caller_provenance_through_to_the_tag_service(
        self, write_service, mock_journal_service, mock_tag_service, mock_transaction
    ):
        """MCP-created journals must produce MCP-provenance tag history."""
        mock_journal_service.create_journal.return_value = _journal(journal_id=42)
        existing_tag = JournalTag(id=uuid4(), name="alpha", color="#123456")
        write_service.tag_repo.find_by_name.return_value = existing_tag

        await write_service.create_journal(
            _journal(),
            None,
            None,
            None,
            mock_transaction,
            tags=["alpha"],
            changed_by="mcp",
            source=Provenance.MCP,
        )

        assert mock_tag_service.assign_tag.await_args.kwargs == {
            "source": Provenance.MCP,
            "changed_by": "mcp",
        }

    @pytest.mark.asyncio
    async def test_no_tags_means_no_tag_calls(
        self, write_service, mock_journal_service, mock_tag_service, mock_transaction
    ):
        """Default tags=None leaves the tag repo untouched (REST back-compat)."""
        mock_journal_service.create_journal.return_value = _journal(journal_id=42)

        await write_service.create_journal(
            _journal(), None, None, None, mock_transaction
        )

        write_service.tag_repo.find_by_name.assert_not_awaited()
        mock_tag_service.assign_tag.assert_not_awaited()


class TestCreateJournalGearUsage:
    @pytest.mark.asyncio
    async def test_gear_usage_type_data_persisted(
        self, write_service, mock_journal_service, mock_transaction
    ):
        """GEAR_USAGE type_data is written through the gear-usage repo on create."""
        mock_journal_service.create_journal.return_value = _journal(journal_id=42)
        mock_journal_service.add_type_to_journal.return_value = [JournalType.GEAR_USAGE]
        write_service.gear_usage_data_repo.find_by_journal_id.return_value = None
        gear_item_id = uuid4()

        await write_service.create_journal(
            _journal(),
            ["gear_usage"],
            {
                "gear_usage": {
                    "gear_item_id": str(gear_item_id),
                    "checkout_date": "2024-01-01T08:00:00+00:00",
                }
            },
            None,
            mock_transaction,
        )

        write_service.gear_usage_data_repo.save.assert_awaited_once()
        saved = write_service.gear_usage_data_repo.save.await_args.args[0]
        assert saved.gear_item_id == gear_item_id


class TestUpdateJournalComposite:
    """The composite replace-all update behind the MCP update_journal_entry tool."""

    @pytest.mark.asyncio
    async def test_core_only_leaves_associations_untouched(
        self, write_service, mock_journal_service, mock_transaction
    ):
        """types/type_data/relationships/tags=None → only core fields update."""
        updated = _journal(journal_id=9)
        mock_journal_service.update_journal.return_value = updated
        write_service._get_current_types = AsyncMock(return_value=set())

        result = await write_service.update_journal_composite(
            _journal(journal_id=9), mock_transaction
        )

        assert result.journal is updated
        assert result.types_removed == []
        assert result.type_data_discarded == {}
        mock_journal_service.update_journal.assert_awaited_once()
        mock_journal_service.add_type_to_journal.assert_not_awaited()
        mock_journal_service.remove_type_from_journal.assert_not_awaited()
        write_service.tag_repo.get_tags_for_journal.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_types_replace_removes_old_and_adds_new(
        self, write_service, mock_journal_service, mock_transaction
    ):
        """Replacing types removes those no longer desired and adds the new ones."""
        mock_journal_service.update_journal.return_value = _journal(journal_id=9)
        write_service._get_current_types = AsyncMock(
            return_value={JournalType.MOOD_RATING}
        )
        mock_journal_service.add_type_to_journal.return_value = [JournalType.FITNESS]
        write_service.fitness_data_repo.find_by_journal_id.return_value = None

        await write_service.update_journal_composite(
            _journal(journal_id=9), mock_transaction, types=["fitness"]
        )

        # MOOD_RATING (current, not desired) is removed + its data deleted.
        mock_journal_service.remove_type_from_journal.assert_awaited_once()
        assert (
            mock_journal_service.remove_type_from_journal.await_args.args[1]
            == JournalType.MOOD_RATING
        )
        write_service.mood_data_repo.delete.assert_awaited_once_with(9)
        # FITNESS (desired, not current) is added.
        mock_journal_service.add_type_to_journal.assert_awaited_once()
        assert (
            mock_journal_service.add_type_to_journal.await_args.args[1]
            == JournalType.FITNESS
        )

    @pytest.mark.asyncio
    async def test_retype_to_dependent_type_keeps_shared_ancestor_data(
        self, write_service, mock_journal_service, mock_transaction
    ):
        """BUSHWALKING → CANYONING must not delete and recreate FITNESS etc.

        CANYONING depends on BUSHWALKING, OUTDOOR_ACTIVITY and FITNESS, so the
        requested list is expanded through its dependencies before diffing.
        Without that, the shared ancestors were removed (wiping the fitness
        block and Strava link) and then re-added empty as CANYONING's deps.
        """
        mock_journal_service.update_journal.return_value = _journal(journal_id=9)
        write_service._get_current_types = AsyncMock(
            return_value={
                JournalType.FITNESS,
                JournalType.OUTDOOR_ACTIVITY,
                JournalType.BUSHWALKING,
            }
        )
        mock_journal_service.add_type_to_journal.return_value = [
            JournalType.CANYONING,
            JournalType.ABSEILING_TRIP,
        ]
        write_service.canyoning_data_repo.find_by_journal_id.return_value = None
        write_service.abseiling_data_repo.find_by_journal_id.return_value = None

        result = await write_service.update_journal_composite(
            _journal(journal_id=9), mock_transaction, types=["canyoning"]
        )

        mock_journal_service.remove_type_from_journal.assert_not_awaited()
        write_service.fitness_data_repo.delete.assert_not_awaited()
        write_service.outdoor_activity_data_repo.delete.assert_not_awaited()
        write_service.bushwalking_data_repo.delete.assert_not_awaited()
        added = [
            call.args[1]
            for call in mock_journal_service.add_type_to_journal.await_args_list
        ]
        assert set(added) == {JournalType.ABSEILING_TRIP, JournalType.CANYONING}
        assert result.types_removed == []
        assert result.type_data_discarded == {}

    @pytest.mark.asyncio
    async def test_types_replace_reports_removed_types_and_populated_fields(
        self, write_service, mock_journal_service, mock_transaction
    ):
        """A genuinely dropped type is named, with the fields that held values."""
        mock_journal_service.update_journal.return_value = _journal(journal_id=9)
        write_service._get_current_types = AsyncMock(
            return_value={JournalType.FITNESS, JournalType.MOOD_RATING}
        )
        write_service.fitness_data_repo.find_by_journal_id.return_value = MagicMock(
            distance=12.5,
            strava_activity_id="123",
            heart_rate_avg=None,
            heart_rate_max=None,
            elevation_gain=None,
            elevation_loss=None,
            duration=None,
            calories=None,
        )
        write_service.mood_data_repo.find_by_journal_id.return_value = MagicMock(
            mood_value=None, mood_label=None, energy_level=None
        )
        # A defaulted boolean (false) is not "held data" and must not be reported.
        write_service.fitness_data_repo.find_by_journal_id.return_value.calories = False
        # A real zero is held data (0 == False in Python, so this guards the predicate).
        write_service.fitness_data_repo.find_by_journal_id.return_value.elevation_gain = 0

        result = await write_service.update_journal_composite(
            _journal(journal_id=9), mock_transaction, types=["mood_rating"]
        )

        assert result.types_removed == ["fitness"]
        assert result.type_data_discarded == {
            "fitness": ["distance", "elevation_gain", "strava_activity_id"]
        }
        write_service.fitness_data_repo.delete.assert_awaited_once_with(9)
        write_service.mood_data_repo.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_tags_replace_all(
        self, write_service, mock_journal_service, mock_tag_service, mock_transaction
    ):
        """tags=[...] drops the tags that left and assigns the ones that arrived."""
        mock_journal_service.update_journal.return_value = _journal(journal_id=9)
        existing = JournalTag(id=uuid4(), name="old", color="#111111")
        write_service.tag_repo.get_tags_for_journal.return_value = [existing]
        new_tag = JournalTag(id=uuid4(), name="new", color="#808080")
        write_service.tag_repo.find_by_name.return_value = new_tag

        await write_service.update_journal_composite(
            _journal(journal_id=9), mock_transaction, tags=["new"]
        )

        assert mock_tag_service.remove_tag.await_args.args[:2] == (9, existing.id)
        assert mock_tag_service.assign_tag.await_args.args[:2] == (9, new_tag.id)

    @pytest.mark.asyncio
    async def test_unchanged_tag_is_neither_removed_nor_reassigned(
        self, write_service, mock_journal_service, mock_tag_service, mock_transaction
    ):
        """Re-sending the same tag list must not touch the junction table.

        The pre-event implementation removed every assignment and re-added it,
        which would now write a bogus "Removed Tags"/"Added Tags" pair into the
        activity feed for an update that changed nothing.
        """
        mock_journal_service.update_journal.return_value = _journal(journal_id=9)
        kept = JournalTag(id=uuid4(), name="keep", color="#111111")
        write_service.tag_repo.get_tags_for_journal.return_value = [kept]
        write_service.tag_repo.find_by_name.return_value = kept

        await write_service.update_journal_composite(
            _journal(journal_id=9), mock_transaction, tags=["keep"]
        )

        mock_tag_service.remove_tag.assert_not_awaited()
        mock_tag_service.assign_tag.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_tag_replace_matches_names_case_insensitively(
        self, write_service, mock_journal_service, mock_tag_service, mock_transaction
    ):
        """Tag lookup is case-insensitive, so the diff must be too.

        Otherwise re-sending "Keep" for a journal tagged "keep" would churn the
        assignment and fabricate history.
        """
        mock_journal_service.update_journal.return_value = _journal(journal_id=9)
        kept = JournalTag(id=uuid4(), name="keep", color="#111111")
        write_service.tag_repo.get_tags_for_journal.return_value = [kept]
        write_service.tag_repo.find_by_name.return_value = kept

        await write_service.update_journal_composite(
            _journal(journal_id=9), mock_transaction, tags=["KEEP"]
        )

        mock_tag_service.remove_tag.assert_not_awaited()
        mock_tag_service.assign_tag.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_tags_list_clears_all(
        self, write_service, mock_journal_service, mock_tag_service, mock_transaction
    ):
        """tags=[] clears all assignments and adds nothing (distinct from None)."""
        mock_journal_service.update_journal.return_value = _journal(journal_id=9)
        existing = JournalTag(id=uuid4(), name="old", color="#111111")
        write_service.tag_repo.get_tags_for_journal.return_value = [existing]

        await write_service.update_journal_composite(
            _journal(journal_id=9), mock_transaction, tags=[]
        )

        assert mock_tag_service.remove_tag.await_args.args[:2] == (9, existing.id)
        mock_tag_service.assign_tag.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_tag_replace_passes_caller_provenance(
        self, write_service, mock_journal_service, mock_tag_service, mock_transaction
    ):
        """Both halves of the diff carry the caller's provenance."""
        mock_journal_service.update_journal.return_value = _journal(journal_id=9)
        existing = JournalTag(id=uuid4(), name="old", color="#111111")
        write_service.tag_repo.get_tags_for_journal.return_value = [existing]
        new_tag = JournalTag(id=uuid4(), name="new", color="#808080")
        write_service.tag_repo.find_by_name.return_value = new_tag

        await write_service.update_journal_composite(
            _journal(journal_id=9),
            mock_transaction,
            tags=["new"],
            changed_by="mcp",
            source=Provenance.MCP,
        )

        expected = {"source": Provenance.MCP, "changed_by": "mcp"}
        assert mock_tag_service.remove_tag.await_args.kwargs == expected
        assert mock_tag_service.assign_tag.await_args.kwargs == expected

    @pytest.mark.asyncio
    async def test_relationships_replace_all(
        self,
        write_service,
        mock_journal_service,
        mock_journal_contact_service,
        mock_transaction,
    ):
        """relationships=[...] removes existing then adds the provided set."""
        mock_journal_service.update_journal.return_value = _journal(journal_id=9)
        existing_rel = MagicMock()
        existing_rel.contact_id = 7
        existing_rel.relationship_type = JournalContactRelationshipType.PARTICIPANT
        repo = AsyncMock()
        repo.get_by_journal.return_value = [existing_rel]
        mock_journal_contact_service.contact_relationship_repo = repo

        await write_service.update_journal_composite(
            _journal(journal_id=9),
            mock_transaction,
            relationships=[
                {"attributes": {"contact_id": "5", "relationship_type": "PARTICIPANT"}}
            ],
        )

        mock_journal_contact_service.remove_contact_from_journal.assert_awaited_once()
        mock_journal_contact_service.add_contact_to_journal.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_replace_types_ignores_type_data_for_non_desired_types(
        self, write_service, mock_journal_service, mock_transaction
    ):
        """type_data for a type not in the new `types` set is not applied.

        Otherwise a stray key (e.g. EVENT) would recreate that type's row and
        defeat the replace-all semantics.
        """
        mock_journal_service.update_journal.return_value = _journal(journal_id=9)
        write_service._get_current_types = AsyncMock(return_value=set())
        mock_journal_service.add_type_to_journal.return_value = [JournalType.FITNESS]
        write_service.fitness_data_repo.find_by_journal_id.return_value = None

        await write_service.update_journal_composite(
            _journal(journal_id=9),
            mock_transaction,
            types=["fitness"],
            type_data={"EVENT": {"calendar_id": "irrelevant"}},
        )

        # EVENT is not among the desired types, so its type_data is dropped.
        write_service.calendar_info_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_replace_types_removing_event_deletes_calendar_info(
        self, write_service, mock_journal_service, mock_transaction
    ):
        """Dropping EVENT deletes its journal_calendar_info marker row."""
        mock_journal_service.update_journal.return_value = _journal(journal_id=9)
        write_service._get_current_types = AsyncMock(return_value={JournalType.EVENT})
        mock_journal_service.add_type_to_journal.return_value = [
            JournalType.MOOD_RATING
        ]
        write_service.mood_data_repo.find_by_journal_id.return_value = None

        await write_service.update_journal_composite(
            _journal(journal_id=9), mock_transaction, types=["mood_rating"]
        )

        write_service.calendar_info_repo.delete.assert_awaited_once_with(9)

    @pytest.mark.asyncio
    async def test_type_presence_repos_covers_every_removable_type(self, write_service):
        """Detection must cover every type the delete helper can remove.

        Otherwise a replace-all update could fail to detect a current type and
        leave it (and its data) behind. PHOTO_ALBUM is intentionally excluded
        (Immich-synced).
        """
        covered = {jtype for jtype, _ in write_service._type_presence_repos()}
        expected = set(JournalType) - {JournalType.NOTE, JournalType.PHOTO_ALBUM}
        assert covered == expected

    @pytest.mark.asyncio
    async def test_replace_types_raises_on_invalid_type(
        self, write_service, mock_journal_service, mock_transaction
    ):
        """An unparseable type aborts the replace rather than silently dropping it."""
        mock_journal_service.update_journal.return_value = _journal(journal_id=9)
        write_service._get_current_types = AsyncMock(return_value=set())

        with pytest.raises(JournalValidationError):
            await write_service.update_journal_composite(
                _journal(journal_id=9), mock_transaction, types=["not_a_real_type"]
            )

        # No type was removed/added because we bailed before mutating.
        mock_journal_service.remove_type_from_journal.assert_not_awaited()
        mock_journal_service.add_type_to_journal.assert_not_awaited()


class TestRemoveTypeEvent:
    @pytest.mark.asyncio
    async def test_remove_event_type_deletes_calendar_info(
        self, write_service, mock_journal_service, mock_transaction
    ):
        """remove_type(EVENT) deletes the calendar_info marker so EVENT is gone."""
        await write_service.remove_type(
            9, JournalType.EVENT, mock_transaction, changed_by="ui"
        )

        mock_journal_service.remove_type_from_journal.assert_awaited_once()
        write_service.calendar_info_repo.delete.assert_awaited_once_with(9)


class TestReplaceTypesValidatesTypeData:
    """Type-data supplied alongside ``types`` must run the domain's validation.

    The composite update splits on whether ``types`` was sent: ``type_data``
    alone routes through ``update_type_data`` (which rebuilds the entity with
    ``dataclasses.replace``, so ``__post_init__`` runs), while sending ``types``
    too routes through ``_process_journal_type_data``. That branch used to
    assign the attributes in place, so no validation ran at all and an
    over-long value reached the column and surfaced as an opaque 500. Both
    branches must reject the same input with the same domain error.
    """

    @pytest.mark.asyncio
    async def test_over_long_role_is_rejected(self, write_service):
        """A role past the column's cap is a validation error, not a DB failure."""
        write_service.outdoor_activity_data_repo.find_by_journal_id.return_value = (
            OutdoorActivityData(journal_id=7)
        )

        with pytest.raises(OutdoorActivityDataValidationError, match="role"):
            await write_service._process_journal_type_data(
                7,
                {"outdoor_activity": {"role": "x" * (MAX_ROLE_LENGTH + 1)}},
                AsyncMock(),
            )

        write_service.outdoor_activity_data_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_off_vocabulary_track_grading_is_rejected(self, write_service):
        """track_grading is a closed vocabulary on both write paths."""
        write_service.bushwalking_data_repo.find_by_journal_id.return_value = (
            BushwalkingData(journal_id=7)
        )

        with pytest.raises(BushwalkingDataValidationError, match="track_grading"):
            await write_service._process_journal_type_data(
                7, {"bushwalking": {"track_grading": "Grade 9"}}, AsyncMock()
            )

        write_service.bushwalking_data_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_out_of_range_mood_value_is_rejected(self, write_service):
        """mood_value outside 1-10 fails the entity's own bounds check."""
        write_service.mood_data_repo.find_by_journal_id.return_value = MoodData(
            journal_id=7
        )

        with pytest.raises(MoodDataValidationError, match="mood_value"):
            await write_service._process_journal_type_data(
                7, {"mood_rating": {"mood_value": 99}}, AsyncMock()
            )

        write_service.mood_data_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_integer_mood_value_raises_a_domain_error(self, write_service):
        """A service must not raise HTTPException: MCP cannot recognise one.

        ``mcp_unified_error_handler`` matches domain errors and ValueError; an
        HTTPException falls through to the catch-all and is reported as
        "Internal error", which tells an agent nothing it can act on.
        """
        write_service.mood_data_repo.find_by_journal_id.return_value = MoodData(
            journal_id=7
        )

        with pytest.raises(JournalDomainError):
            await write_service._process_journal_type_data(
                7, {"mood_rating": {"mood_value": "not-a-number"}}, AsyncMock()
            )
