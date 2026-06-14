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
        mock_history_repo.get_contact_history.assert_called_once_with(1, 50, 0)

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
