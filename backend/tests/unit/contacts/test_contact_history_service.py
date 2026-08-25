"""Tests for the read-only ContactHistoryService.

ITER12-003 Phase 2 removed the synchronous ``record_*`` write methods (contact
history is now produced by the event-driven HistoryProjectionConsumer). Only the
read methods remain, so only they are tested here.
"""

from unittest.mock import AsyncMock

import pytest

from app.core.contacts.models.repositories import ContactFieldHistoryEntry
from app.core.contacts.services.contact_history_service import ContactHistoryService


class TestContactHistoryService:
    """Test ContactHistoryService read methods."""

    @pytest.fixture
    def mock_history_repo(self):
        """Create mock history repository."""
        return AsyncMock()

    @pytest.fixture
    def mock_transaction(self):
        """Create mock transaction."""
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_history_repo):
        """Create ContactHistoryService instance."""
        return ContactHistoryService(mock_history_repo)

    @pytest.mark.asyncio
    async def test_get_contact_history(
        self, service, mock_history_repo, mock_transaction
    ):
        """Test getting contact history."""
        expected_entries = [
            ContactFieldHistoryEntry(
                entity_type="contact",
                entity_id=1,
                field_name="first_name",
                old_value="John",
                new_value="Jane",
                changed_by="system",
            )
        ]
        mock_history_repo.get_contact_history.return_value = expected_entries

        result = await service.get_contact_history(
            1, limit=50, _transaction=mock_transaction
        )

        assert result == expected_entries
        mock_history_repo.get_contact_history.assert_called_once_with(
            1, 50, 0, reader_user_id=None
        )

    @pytest.mark.asyncio
    async def test_get_entity_history(
        self, service, mock_history_repo, mock_transaction
    ):
        """Test getting entity history."""
        expected_entries = [
            ContactFieldHistoryEntry(
                entity_type="contact_method",
                entity_id=1,
                field_name="value",
                old_value="old@example.com",
                new_value="new@example.com",
                changed_by="system",
            )
        ]
        mock_history_repo.get_entity_history.return_value = expected_entries

        result = await service.get_entity_history(
            "contact_method", 1, _transaction=mock_transaction
        )

        assert result == expected_entries
        mock_history_repo.get_entity_history.assert_called_once_with(
            "contact_method", 1
        )

    @pytest.mark.asyncio
    async def test_the_reader_reaches_the_read_and_the_naming_query(
        self, service, mock_history_repo
    ):
        """Both, because both can disclose another user's task.

        The aggregate read is what returns their rows; the naming query is what
        returns the task's **text**. Scoping one and not the other would swap a
        leak of "a task exists" for a leak of what it says.
        """
        mock_history_repo.get_contact_history.return_value = [
            ContactFieldHistoryEntry(
                entity_type="task",
                entity_id=7,
                field_name="contact:1",
                old_value=None,
                new_value="1",
            )
        ]
        mock_history_repo.get_task_labels.return_value = {7: "Their commitment"}

        entries = await service.get_contact_history(1, reader_user_id="reader-9")

        mock_history_repo.get_contact_history.assert_called_once_with(
            1, 50, 0, reader_user_id="reader-9"
        )
        mock_history_repo.get_task_labels.assert_called_once_with(
            [7], reader_user_id="reader-9"
        )
        assert entries[0].entity_label == "Their commitment"

    @pytest.mark.asyncio
    async def test_a_page_with_no_task_rows_asks_for_no_names(
        self, service, mock_history_repo
    ):
        """The extra query is paid for only when there is something to name."""
        mock_history_repo.get_contact_history.return_value = [
            ContactFieldHistoryEntry(
                entity_type="contact",
                entity_id=1,
                field_name="first_name",
                old_value="John",
                new_value="Jane",
            )
        ]

        await service.get_contact_history(1, reader_user_id="reader-9")

        mock_history_repo.get_task_labels.assert_not_called()

    @pytest.mark.asyncio
    async def test_the_count_is_scoped_to_the_same_reader(
        self, service, mock_history_repo
    ):
        """A count over a wider set both discloses and breaks the page."""
        mock_history_repo.get_contact_history_count.return_value = 3

        await service.get_contact_history_count(1, reader_user_id="reader-9")

        mock_history_repo.get_contact_history_count.assert_called_once_with(
            1, reader_user_id="reader-9"
        )
