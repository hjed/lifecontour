"""Unit tests for JournalWriteService composite writes.

The ``@transactional`` decorator is a no-op when ``transaction`` is not a real
``AsyncConnection`` (these tests pass mocks), so the tests exercise the
orchestration and atomicity contract directly: every sub-write runs inside the
single composite call, and a mid-write failure propagates (so the surrounding
unit of work would roll the whole journal back) without running later steps.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.models.journals import EventDateRange, Journal, JournalType

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
def write_service(mock_journal_service, mock_journal_contact_service):
    """Build a JournalWriteService with all repos/services mocked."""
    repos = {name: AsyncMock() for name in _REPO_PARAM_NAMES}
    return JournalWriteService(
        journal_service=mock_journal_service,
        journal_contact_service=mock_journal_contact_service,
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
        """update_type_data for MOOD_RATING updates the mood row."""
        existing = MagicMock()
        write_service.mood_data_repo.find_by_journal_id.return_value = existing

        await write_service.update_type_data(
            7, JournalType.MOOD_RATING, {"mood_value": 5}, mock_transaction
        )

        write_service.mood_data_repo.save.assert_awaited_once()
