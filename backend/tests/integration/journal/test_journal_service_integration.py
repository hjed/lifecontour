"""Integration tests for JournalService with real database."""

from datetime import datetime

import pytest
from core_shared.models.journals import (
    EventDateRange,
    Journal,
    JournalCycleError,
    JournalMaxDepthExceededError,
    JournalNotFoundError,
    JournalType,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_service import JournalService
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher


def create_test_journal(
    user_id: str = "user123",
    title: str = "Test Journal",
    content: str = "Test content",
    journal_id: int | None = None,
    parent_id: int | None = None,
) -> Journal:
    """Helper function to create a test journal."""
    return Journal(
        id=journal_id,
        user_id=user_id,
        title=title,
        content=content,
        event_date_range=EventDateRange(
            start=datetime(2024, 1, 1), end=datetime(2024, 1, 1)
        ),
        parent_id=parent_id,
    )


@pytest.mark.integration
class TestJournalServiceIntegration:
    """Integration tests for JournalService with real database."""

    @pytest.fixture
    def journal_repo(self, clean_database: AsyncConnection):
        """Create real journal repository."""
        return SqlJournalRepository(clean_database)

    @pytest.fixture
    def event_publisher(self, clean_database: AsyncConnection):
        """Create real event publisher."""
        return OutboxEventPublisher(clean_database)

    @pytest.fixture
    def journal_service(self, journal_repo, event_publisher):
        """Create JournalService with real dependencies."""
        return JournalService(
            journal_repo=journal_repo,
            event_publisher=event_publisher,
        )

    @pytest.mark.asyncio
    async def test_create_journal_success(
        self, journal_service, clean_database: AsyncConnection
    ):
        """Test successful journal creation with real database."""
        # Arrange
        journal = create_test_journal()

        # Act
        result = await journal_service.create_journal(journal, clean_database)

        # Assert
        assert result.id is not None
        assert result.user_id == "user123"
        assert result.title == "Test Journal"
        assert result.created_at is not None

        # Verify journal was actually saved to database
        saved_journal = await journal_service.get_journal(result.id)
        assert saved_journal is not None
        assert saved_journal.user_id == "user123"
        assert saved_journal.title == "Test Journal"

    @pytest.mark.asyncio
    async def test_create_journal_with_parent(
        self, journal_service, clean_database: AsyncConnection
    ):
        """Test creating journal with parent relationship."""
        # Arrange
        parent = create_test_journal(title="Parent Journal")
        parent = await journal_service.create_journal(parent, clean_database)

        child = create_test_journal(title="Child Journal", parent_id=parent.id)

        # Act
        result = await journal_service.create_journal(child, clean_database)

        # Assert
        assert result.id is not None
        assert result.parent_id == parent.id

        # Verify parent relationship in database
        saved_child = await journal_service.get_journal(result.id)
        assert saved_child is not None
        assert saved_child.parent_id == parent.id

    @pytest.mark.asyncio
    async def test_create_journal_max_depth_validation(
        self, journal_service, clean_database: AsyncConnection
    ):
        """Test max depth validation (5 levels)."""
        # Arrange - Create 5 levels of journals
        journals: list[Journal] = []
        for i in range(5):
            journal = create_test_journal(
                title=f"Level {i + 1} Journal",
                parent_id=journals[-1].id if journals else None,
            )
            created = await journal_service.create_journal(journal, clean_database)
            journals.append(created)

        # Try to create 6th level
        too_deep = create_test_journal(
            title="Too Deep Journal",
            parent_id=journals[-1].id,
        )

        # Act & Assert
        with pytest.raises(JournalMaxDepthExceededError):
            await journal_service.create_journal(too_deep, clean_database)

    @pytest.mark.asyncio
    async def test_update_journal_success(
        self, journal_service, clean_database: AsyncConnection
    ):
        """Test successful journal update."""
        # Arrange
        journal = create_test_journal(title="Original Title")
        journal = await journal_service.create_journal(journal, clean_database)

        # Update the journal (the service computes changed_fields by diffing the
        # persisted journal against this merged object).
        journal.title = "Updated Title"

        # Act
        result = await journal_service.update_journal(journal, clean_database)

        # Assert
        assert result.title == "Updated Title"

        # Verify update in database
        saved_journal = await journal_service.get_journal(journal.id)
        assert saved_journal is not None
        assert saved_journal.title == "Updated Title"

    @pytest.mark.asyncio
    async def test_update_journal_parent_cycle_detection(
        self, journal_service, clean_database: AsyncConnection
    ):
        """Test cycle detection when updating parent."""
        # Arrange - Create parent -> child relationship
        parent = create_test_journal(title="Parent Journal")
        parent = await journal_service.create_journal(parent, clean_database)

        child = create_test_journal(title="Child Journal", parent_id=parent.id)
        child = await journal_service.create_journal(child, clean_database)

        # Try to make parent a child of child (would create cycle)
        parent.parent_id = child.id

        # Act & Assert
        with pytest.raises(JournalCycleError):
            await journal_service.update_journal(parent, clean_database)

    @pytest.mark.asyncio
    async def test_delete_journal_success(
        self, journal_service, clean_database: AsyncConnection
    ):
        """Test successful journal deletion."""
        # Arrange
        journal = create_test_journal()
        journal = await journal_service.create_journal(journal, clean_database)
        journal_id = journal.id

        # Act
        await journal_service.delete_journal(journal_id, clean_database)

        # Assert - Journal should not exist
        deleted_journal = await journal_service.get_journal(journal_id)
        assert deleted_journal is None

    @pytest.mark.asyncio
    async def test_delete_journal_not_found(
        self, journal_service, clean_database: AsyncConnection
    ):
        """Test delete fails when journal doesn't exist."""
        # Act & Assert
        with pytest.raises(JournalNotFoundError):
            await journal_service.delete_journal(999, clean_database)

    @pytest.mark.asyncio
    async def test_add_type_to_journal_success(
        self, journal_service, clean_database: AsyncConnection
    ):
        """Test successful type addition."""
        # Arrange
        journal = create_test_journal()
        journal = await journal_service.create_journal(journal, clean_database)

        # Act
        result = await journal_service.add_type_to_journal(
            journal.id,
            JournalType.EVENT,
            clean_database,
        )

        # Assert
        assert result == [JournalType.EVENT]

    @pytest.mark.asyncio
    async def test_add_type_to_journal_not_found(
        self, journal_service, clean_database: AsyncConnection
    ):
        """Test add type fails when journal doesn't exist."""
        # Act & Assert
        with pytest.raises(JournalNotFoundError):
            await journal_service.add_type_to_journal(
                999, JournalType.EVENT, clean_database
            )

    @pytest.mark.asyncio
    async def test_remove_type_from_journal_success(
        self, journal_service, clean_database: AsyncConnection
    ):
        """Test successful type removal."""
        # Arrange
        journal = create_test_journal()
        journal = await journal_service.create_journal(journal, clean_database)

        # Add type first
        await journal_service.add_type_to_journal(
            journal.id,
            JournalType.EVENT,
            clean_database,
        )

        # Act
        await journal_service.remove_type_from_journal(
            journal.id,
            JournalType.EVENT,
            clean_database,
        )

        # Assert - No exception means success

    @pytest.mark.asyncio
    async def test_remove_type_from_journal_not_found(
        self, journal_service, clean_database: AsyncConnection
    ):
        """Test remove type fails when journal doesn't exist."""
        # Act & Assert
        with pytest.raises(JournalNotFoundError):
            await journal_service.remove_type_from_journal(
                999, JournalType.EVENT, clean_database
            )

    @pytest.mark.asyncio
    async def test_full_workflow_create_update_delete(
        self, journal_service, clean_database: AsyncConnection
    ):
        """Test full workflow: create, update, add type, delete."""
        # Create journal
        journal = create_test_journal(title="Workflow Test")
        journal = await journal_service.create_journal(journal, clean_database)
        assert journal.id is not None

        # Update journal
        journal.title = "Updated Workflow Test"
        journal = await journal_service.update_journal(journal, clean_database)
        assert journal.title == "Updated Workflow Test"

        # Add type
        types_added = await journal_service.add_type_to_journal(
            journal.id,
            JournalType.MOOD_RATING,
            clean_database,
        )
        assert JournalType.MOOD_RATING in types_added

        # Delete journal
        await journal_service.delete_journal(journal.id, clean_database)

        # Verify deletion
        deleted = await journal_service.get_journal(journal.id)
        assert deleted is None


@pytest.mark.integration
class TestJournalServiceFiltering:
    """Integration tests for JournalService filtering operations."""

    @pytest.fixture
    def journal_repo(self, clean_database: AsyncConnection):
        """Create real journal repository."""
        return SqlJournalRepository(clean_database)

    @pytest.fixture
    def event_publisher(self, clean_database: AsyncConnection):
        """Create real event publisher."""
        return OutboxEventPublisher(clean_database)

    @pytest.fixture
    def journal_service(self, journal_repo, event_publisher):
        """Create JournalService with real dependencies."""
        return JournalService(
            journal_repo=journal_repo,
            event_publisher=event_publisher,
        )

    @pytest.mark.asyncio
    async def test_get_journals_paginated_with_type_filter(
        self, journal_service, clean_database: AsyncConnection
    ):
        """Test that service passes journal_type filter to repository."""
        # Create a NOTE journal
        note_journal = create_test_journal(title="Note Journal")
        await journal_service.create_journal(note_journal, clean_database)

        # Create a MOOD_RATING journal
        mood_journal = create_test_journal(title="Mood Journal")
        mood_journal = await journal_service.create_journal(
            mood_journal, clean_database
        )

        # Add mood data
        await clean_database.execute(
            text("""
            INSERT INTO journal_mood_data (journal_id, mood_value)
            VALUES (:journal_id, :mood_value)
            """),
            {"journal_id": mood_journal.id, "mood_value": 8},
        )

        # Get journals with type filter
        mood_journals = await journal_service.get_journals_paginated(
            user_id="user123",
            journal_type="MOOD_RATING",
        )

        assert len(mood_journals) == 1
        assert mood_journals[0].title == "Mood Journal"

    @pytest.mark.asyncio
    async def test_get_journals_paginated_with_date_filter(
        self, journal_service, clean_database: AsyncConnection
    ):
        """Test that service passes date filters to repository."""
        # Create journals with different dates
        old_journal = Journal(
            user_id="user123",
            title="Old Journal",
            content="Old content",
            event_date_range=EventDateRange(
                start=datetime(2024, 1, 1),
                end=datetime(2024, 1, 2),
            ),
        )
        current_journal = Journal(
            user_id="user123",
            title="Current Journal",
            content="Current content",
            event_date_range=EventDateRange(
                start=datetime(2024, 1, 15),
                end=datetime(2024, 1, 16),
            ),
        )

        await journal_service.create_journal(old_journal, clean_database)
        await journal_service.create_journal(current_journal, clean_database)

        # Filter by date range
        filtered = await journal_service.get_journals_paginated(
            user_id="user123",
            start_date="2024-01-10",
            end_date="2024-01-20",
        )

        assert len(filtered) == 1
        assert filtered[0].title == "Current Journal"

    @pytest.mark.asyncio
    async def test_get_journals_paginated_with_search(
        self, journal_service, clean_database: AsyncConnection
    ):
        """Test that service passes search filter to repository."""
        # Create journals with different content
        journal1 = create_test_journal(
            title="Python Programming",
            content="Learning Python",
        )
        journal2 = create_test_journal(
            title="JavaScript Notes",
            content="Learning JavaScript",
        )

        await journal_service.create_journal(journal1, clean_database)
        await journal_service.create_journal(journal2, clean_database)

        # Search for "Python"
        filtered = await journal_service.get_journals_paginated(
            user_id="user123",
            search="Python",
        )

        assert len(filtered) == 1
        assert filtered[0].title == "Python Programming"

    @pytest.mark.asyncio
    async def test_get_journals_count_with_filters(
        self, journal_service, clean_database: AsyncConnection
    ):
        """Test that get_journals_count respects filters."""
        # Create journals
        journal1 = create_test_journal(title="Python Journal")
        journal2 = create_test_journal(title="JavaScript Journal")
        journal3 = create_test_journal(title="Python Tutorial")

        await journal_service.create_journal(journal1, clean_database)
        await journal_service.create_journal(journal2, clean_database)
        await journal_service.create_journal(journal3, clean_database)

        # Count all journals
        total_count = await journal_service.get_journals_count(user_id="user123")
        assert total_count == 3

        # Count with search filter
        python_count = await journal_service.get_journals_count(
            user_id="user123",
            search="Python",
        )
        assert python_count == 2
