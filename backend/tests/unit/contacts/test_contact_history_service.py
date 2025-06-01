"""Tests for ContactHistoryService."""

from unittest.mock import AsyncMock

import pytest

from app.core.contacts.models.repositories import ContactFieldHistoryEntry
from app.core.contacts.services.contact_history_service import ContactHistoryService


class TestContactHistoryService:
    """Test ContactHistoryService."""

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
    async def test_record_contact_change_with_fields(
        self, service, mock_history_repo, mock_transaction
    ):
        """Test recording contact change with changed fields."""
        changed_fields = {"first_name": ("John", "Jane"), "last_name": ("Doe", "Smith")}

        await service.record_contact_change(
            contact_id=1,
            changed_fields=changed_fields,
            changed_by="user123",
            _transaction=mock_transaction,
        )

        # Should record one entry per changed field
        assert mock_history_repo.record_change.call_count == 2

        # Check the calls
        calls = mock_history_repo.record_change.call_args_list

        # First call for first_name
        first_call_entry = calls[0][0][0]
        assert first_call_entry.entity_type == "contact"
        assert first_call_entry.entity_id == 1
        assert first_call_entry.field_name == "first_name"
        assert first_call_entry.old_value == "John"
        assert first_call_entry.new_value == "Jane"
        assert first_call_entry.changed_by == "user123"

        # Second call for last_name
        second_call_entry = calls[1][0][0]
        assert second_call_entry.entity_type == "contact"
        assert second_call_entry.entity_id == 1
        assert second_call_entry.field_name == "last_name"
        assert second_call_entry.old_value == "Doe"
        assert second_call_entry.new_value == "Smith"
        assert second_call_entry.changed_by == "user123"

    @pytest.mark.asyncio
    async def test_record_contact_change_default_changed_by(
        self, service, mock_history_repo, mock_transaction
    ):
        """Test recording contact change with default changed_by."""
        changed_fields = {"first_name": ("John", "Jane")}

        await service.record_contact_change(
            contact_id=1, changed_fields=changed_fields, _transaction=mock_transaction
        )

        # Check default changed_by
        call_entry = mock_history_repo.record_change.call_args[0][0]
        assert call_entry.changed_by == "system"

    @pytest.mark.asyncio
    async def test_record_method_change_with_fields(
        self, service, mock_history_repo, mock_transaction
    ):
        """Test recording method change with changed fields."""
        changed_fields = {
            "value": ("old@example.com", "new@example.com"),
            "is_primary": (False, True),
        }

        await service.record_method_change(
            method_id=1,
            changed_fields=changed_fields,
            changed_by="user123",
            _transaction=mock_transaction,
        )

        # Should record one entry per changed field
        assert mock_history_repo.record_change.call_count == 2

        # Check first call
        first_call_entry = mock_history_repo.record_change.call_args_list[0][0][0]
        assert first_call_entry.entity_type == "contact_method"
        assert first_call_entry.entity_id == 1
        assert first_call_entry.field_name == "value"
        assert first_call_entry.old_value == "old@example.com"
        assert first_call_entry.new_value == "new@example.com"

    @pytest.mark.asyncio
    async def test_record_address_change_with_fields(
        self, service, mock_history_repo, mock_transaction
    ):
        """Test recording address change with changed fields."""
        changed_fields = {
            "street_line_1": ("123 Old St", "456 New St"),
            "postal_code": ("12345", "67890"),
        }

        await service.record_address_change(
            address_id=1, changed_fields=changed_fields, _transaction=mock_transaction
        )

        assert mock_history_repo.record_change.call_count == 2

        first_call_entry = mock_history_repo.record_change.call_args_list[0][0][0]
        assert first_call_entry.entity_type == "contact_address"
        assert first_call_entry.entity_id == 1

    @pytest.mark.asyncio
    async def test_record_note_change_with_fields(
        self, service, mock_history_repo, mock_transaction
    ):
        """Test recording note change with changed fields."""
        changed_fields = {"content": ("Old note", "New note")}

        await service.record_note_change(
            note_id=1, changed_fields=changed_fields, _transaction=mock_transaction
        )

        call_entry = mock_history_repo.record_change.call_args[0][0]
        assert call_entry.entity_type == "contact_note"
        assert call_entry.entity_id == 1
        assert call_entry.field_name == "content"
        assert call_entry.old_value == "Old note"
        assert call_entry.new_value == "New note"

    @pytest.mark.asyncio
    async def test_record_tag_change_assigned(
        self, service, mock_history_repo, mock_transaction
    ):
        """Test recording tag assignment."""
        await service.record_tag_change(
            contact_id=1,
            tag_id=2,
            action="assigned",
            changed_by="user123",
            _transaction=mock_transaction,
        )

        call_entry = mock_history_repo.record_change.call_args[0][0]
        assert call_entry.entity_type == "contact_tag"
        assert call_entry.entity_id == 2
        assert call_entry.field_name == "contact_id"
        assert call_entry.old_value is None
        assert call_entry.new_value == "1"
        assert call_entry.changed_by == "user123"

    @pytest.mark.asyncio
    async def test_record_tag_change_removed(
        self, service, mock_history_repo, mock_transaction
    ):
        """Test recording tag removal."""
        await service.record_tag_change(
            contact_id=1, tag_id=2, action="removed", _transaction=mock_transaction
        )

        call_entry = mock_history_repo.record_change.call_args[0][0]
        assert call_entry.entity_type == "contact_tag"
        assert call_entry.entity_id == 2
        assert call_entry.field_name == "contact_id"
        assert call_entry.old_value == "1"
        assert call_entry.new_value is None
        assert call_entry.changed_by == "system"

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
        mock_history_repo.get_contact_history.assert_called_once_with(1, 50)

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
