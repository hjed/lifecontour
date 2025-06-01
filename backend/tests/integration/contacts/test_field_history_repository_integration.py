"""Integration tests for ContactFieldHistoryRepository with real database."""

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql import SqlContactFieldHistoryRepository
from app.core.contacts.models.repositories import ContactFieldHistoryEntry


@pytest.mark.integration
class TestContactFieldHistoryRepositoryIntegration:
    """Integration tests for ContactFieldHistoryRepository with real database."""

    @pytest.fixture
    def history_repo(self, clean_database: AsyncConnection):
        """Create ContactFieldHistoryRepository instance with real database connection."""
        return SqlContactFieldHistoryRepository(clean_database)

    @pytest.mark.asyncio
    async def test_record_change_single_field(self, history_repo):
        """Test recording a single field change."""
        # Arrange
        entry = ContactFieldHistoryEntry(
            entity_type="contact",
            entity_id=1,
            field_name="first_name",
            old_value="John",
            new_value="Jane",
            changed_by="test_user",
        )

        # Act
        saved_entry = await history_repo.record_change(entry)

        # Assert
        assert saved_entry.id is not None
        assert saved_entry.entity_type == "contact"
        assert saved_entry.entity_id == 1
        assert saved_entry.field_name == "first_name"
        assert saved_entry.old_value == "John"
        assert saved_entry.new_value == "Jane"
        assert saved_entry.changed_by == "test_user"
        assert saved_entry.created_at is not None

    @pytest.mark.asyncio
    async def test_record_change_null_values(self, history_repo):
        """Test recording field change with null values."""
        # Arrange - Test adding a field (old_value is None)
        entry1 = ContactFieldHistoryEntry(
            entity_type="contact",
            entity_id=1,
            field_name="nick_name",
            old_value=None,
            new_value="Johnny",
            changed_by="system",
        )

        # Act
        saved_entry1 = await history_repo.record_change(entry1)

        # Assert
        assert saved_entry1.old_value is None
        assert saved_entry1.new_value == "Johnny"

        # Arrange - Test removing a field (new_value is None)
        entry2 = ContactFieldHistoryEntry(
            entity_type="contact",
            entity_id=1,
            field_name="nick_name",
            old_value="Johnny",
            new_value=None,
            changed_by="system",
        )

        # Act
        saved_entry2 = await history_repo.record_change(entry2)

        # Assert
        assert saved_entry2.old_value == "Johnny"
        assert saved_entry2.new_value is None

    @pytest.mark.asyncio
    async def test_record_multiple_changes(self, history_repo):
        """Test recording multiple field changes."""
        # Arrange
        entries = [
            ContactFieldHistoryEntry(
                entity_type="contact",
                entity_id=1,
                field_name="first_name",
                old_value="John",
                new_value="Jane",
                changed_by="user1",
            ),
            ContactFieldHistoryEntry(
                entity_type="contact",
                entity_id=1,
                field_name="last_name",
                old_value="Doe",
                new_value="Smith",
                changed_by="user1",
            ),
            ContactFieldHistoryEntry(
                entity_type="contact",
                entity_id=1,
                field_name="email",
                old_value="john@example.com",
                new_value="jane@example.com",
                changed_by="user1",
            ),
        ]

        # Act
        saved_entries = await history_repo.record_multiple_changes(entries)

        # Assert
        assert len(saved_entries) == 3
        for saved_entry in saved_entries:
            assert saved_entry.id is not None
            assert saved_entry.entity_id == 1
            assert saved_entry.changed_by == "user1"

        # Verify field names are correct
        field_names = [entry.field_name for entry in saved_entries]
        assert "first_name" in field_names
        assert "last_name" in field_names
        assert "email" in field_names

    @pytest.mark.asyncio
    async def test_get_contact_history(self, history_repo):
        """Test getting history for a specific contact."""
        # Arrange - Create history entries for multiple contacts
        entries = [
            ContactFieldHistoryEntry(
                entity_type="contact",
                entity_id=1,
                field_name="first_name",
                old_value="John",
                new_value="Jane",
                changed_by="user1",
            ),
            ContactFieldHistoryEntry(
                entity_type="contact",
                entity_id=1,
                field_name="last_name",
                old_value="Doe",
                new_value="Smith",
                changed_by="user1",
            ),
            ContactFieldHistoryEntry(
                entity_type="contact",
                entity_id=2,
                field_name="first_name",
                old_value="Bob",
                new_value="Robert",
                changed_by="user2",
            ),
        ]

        for entry in entries:
            await history_repo.record_change(entry)

        # Act
        contact1_history = await history_repo.get_contact_history(1)

        # Assert
        assert len(contact1_history) == 2
        for entry in contact1_history:
            assert entry.entity_id == 1
            assert entry.entity_type == "contact"

        field_names = [entry.field_name for entry in contact1_history]
        assert "first_name" in field_names
        assert "last_name" in field_names

    @pytest.mark.asyncio
    async def test_get_contact_history_with_limit(self, history_repo):
        """Test getting contact history with limit."""
        # Arrange - Create multiple history entries
        for i in range(10):
            entry = ContactFieldHistoryEntry(
                entity_type="contact",
                entity_id=1,
                field_name=f"field_{i}",
                old_value=f"old_{i}",
                new_value=f"new_{i}",
                changed_by="system",
            )
            await history_repo.record_change(entry)

        # Act
        limited_history = await history_repo.get_contact_history(1, limit=5)

        # Assert
        assert len(limited_history) == 5
        # Should be ordered by created_at DESC (most recent first)
        for i in range(len(limited_history) - 1):
            assert limited_history[i].created_at >= limited_history[i + 1].created_at

    @pytest.mark.asyncio
    async def test_get_field_history(self, history_repo):
        """Test getting history for a specific field."""
        # Arrange - Create history for multiple fields
        entries = [
            ContactFieldHistoryEntry(
                entity_type="contact",
                entity_id=1,
                field_name="first_name",
                old_value="John",
                new_value="Jane",
                changed_by="user1",
            ),
            ContactFieldHistoryEntry(
                entity_type="contact",
                entity_id=1,
                field_name="first_name",
                old_value="Jane",
                new_value="Janet",
                changed_by="user2",
            ),
            ContactFieldHistoryEntry(
                entity_type="contact",
                entity_id=1,
                field_name="last_name",
                old_value="Doe",
                new_value="Smith",
                changed_by="user1",
            ),
        ]

        for entry in entries:
            await history_repo.record_change(entry)

        # Act
        first_name_history = await history_repo.get_field_history(1, "first_name")

        # Assert
        assert len(first_name_history) == 2
        for entry in first_name_history:
            assert entry.entity_id == 1
            assert entry.field_name == "first_name"

        # Check the progression of values
        values = [(entry.old_value, entry.new_value) for entry in first_name_history]
        assert ("John", "Jane") in values
        assert ("Jane", "Janet") in values

    @pytest.mark.asyncio
    async def test_get_changes_by_user(self, history_repo):
        """Test getting changes made by a specific user."""
        # Arrange - Create changes by different users
        entries = [
            ContactFieldHistoryEntry(
                entity_type="contact",
                entity_id=1,
                field_name="first_name",
                old_value="John",
                new_value="Jane",
                changed_by="user1",
            ),
            ContactFieldHistoryEntry(
                entity_type="contact",
                entity_id=2,
                field_name="last_name",
                old_value="Doe",
                new_value="Smith",
                changed_by="user1",
            ),
            ContactFieldHistoryEntry(
                entity_type="contact",
                entity_id=3,
                field_name="email",
                old_value="old@example.com",
                new_value="new@example.com",
                changed_by="user2",
            ),
        ]

        for entry in entries:
            await history_repo.record_change(entry)

        # Act
        user1_changes = await history_repo.get_changes_by_user("user1")

        # Assert
        assert len(user1_changes) == 2
        for entry in user1_changes:
            assert entry.changed_by == "user1"

        entity_ids = [entry.entity_id for entry in user1_changes]
        assert 1 in entity_ids
        assert 2 in entity_ids
        assert 3 not in entity_ids

    @pytest.mark.asyncio
    async def test_different_entity_types(self, history_repo):
        """Test recording changes for different entity types."""
        # Arrange
        entries = [
            ContactFieldHistoryEntry(
                entity_type="contact",
                entity_id=1,
                field_name="first_name",
                old_value="John",
                new_value="Jane",
                changed_by="system",
            ),
            ContactFieldHistoryEntry(
                entity_type="contact_method",
                entity_id=1,
                field_name="value",
                old_value="old@example.com",
                new_value="new@example.com",
                changed_by="system",
            ),
            ContactFieldHistoryEntry(
                entity_type="contact_tag",
                entity_id=1,
                field_name="tag_id",
                old_value=None,
                new_value="5",
                changed_by="system",
            ),
        ]

        # Act
        for entry in entries:
            saved_entry = await history_repo.record_change(entry)
            assert saved_entry.id is not None

        # Assert - Get all history and verify entity types
        contact_history = await history_repo.get_contact_history(1)
        entity_types = [entry.entity_type for entry in contact_history]

        assert "contact" in entity_types
        # Note: contact_method and contact_tag changes might not appear in contact history
        # depending on implementation - they track different entities
