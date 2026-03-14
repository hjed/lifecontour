"""Unit tests for JournalService."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.models.journals import (
    EventDateRange,
    Journal,
    JournalCycleError,
    JournalMaxDepthExceededError,
    JournalNotFoundError,
    JournalType,
    JournalValidationError,
)

from app.core.journal.services.journal_service import JournalService


@pytest.fixture
def mock_journal_repo():
    """Create a mock journal repository."""
    return AsyncMock()


@pytest.fixture
def mock_event_publisher():
    """Create a mock event publisher."""
    return AsyncMock()


@pytest.fixture
def mock_transaction():
    """Create a mock database transaction."""
    return AsyncMock()


@pytest.fixture
def journal_service(mock_journal_repo, mock_event_publisher):
    """Create a JournalService instance with mocked dependencies."""
    return JournalService(
        journal_repo=mock_journal_repo,
        event_publisher=mock_event_publisher,
    )


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


class TestJournalServiceCRUD:
    """Test CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_journal_success(
        self, journal_service, mock_journal_repo, mock_event_publisher, mock_transaction
    ):
        """Test successful journal creation."""
        # Arrange
        journal = create_test_journal()
        saved_journal = create_test_journal(journal_id=1)

        mock_journal_repo.save.return_value = saved_journal

        # Act
        result = await journal_service.create_journal(journal, mock_transaction)

        # Assert
        assert result == saved_journal
        mock_journal_repo.save.assert_called_once_with(journal)
        mock_event_publisher.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_journal_with_parent_validates_hierarchy(
        self, journal_service, mock_journal_repo, mock_event_publisher, mock_transaction
    ):
        """Test journal creation with parent validates hierarchy."""
        # Arrange
        parent_journal = create_test_journal(journal_id=1, title="Parent Journal")
        journal = create_test_journal(title="Child Journal", parent_id=1)
        saved_journal = create_test_journal(
            journal_id=2, title="Child Journal", parent_id=1
        )

        mock_journal_repo.find_by_id.return_value = parent_journal
        mock_journal_repo.get_depth.return_value = 1
        mock_journal_repo.save.return_value = saved_journal

        # Act
        result = await journal_service.create_journal(journal, mock_transaction)

        # Assert
        assert result == saved_journal
        mock_journal_repo.find_by_id.assert_called_once_with(1)
        mock_journal_repo.get_depth.assert_called_once_with(1)
        mock_journal_repo.save.assert_called_once_with(journal)

    @pytest.mark.asyncio
    async def test_create_journal_parent_not_found(
        self, journal_service, mock_journal_repo, mock_transaction
    ):
        """Test journal creation fails when parent doesn't exist."""
        # Arrange
        journal = create_test_journal(title="Child Journal", parent_id=999)

        mock_journal_repo.find_by_id.return_value = None

        # Act & Assert
        with pytest.raises(JournalNotFoundError):
            await journal_service.create_journal(journal, mock_transaction)

    @pytest.mark.asyncio
    async def test_create_journal_max_depth_exceeded(
        self, journal_service, mock_journal_repo, mock_transaction
    ):
        """Test journal creation fails when max depth is exceeded."""
        # Arrange
        parent_journal = create_test_journal(journal_id=1, title="Parent Journal")
        journal = create_test_journal(title="Child Journal", parent_id=1)

        mock_journal_repo.find_by_id.return_value = parent_journal
        mock_journal_repo.get_depth.return_value = 5  # Max depth

        # Act & Assert
        with pytest.raises(JournalMaxDepthExceededError):
            await journal_service.create_journal(journal, mock_transaction)

    @pytest.mark.asyncio
    async def test_update_journal_success(
        self, journal_service, mock_journal_repo, mock_event_publisher, mock_transaction
    ):
        """Test successful journal update."""
        # Arrange
        journal = create_test_journal(journal_id=1, title="Updated Title")
        changed_fields = {"title": "Updated Title"}

        mock_journal_repo.save.return_value = journal

        # Act
        result = await journal_service.update_journal(
            journal, changed_fields, mock_transaction
        )

        # Assert
        assert result == journal
        mock_journal_repo.save.assert_called_once_with(journal)
        mock_event_publisher.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_journal_no_id_fails(self, journal_service, mock_transaction):
        """Test update fails when journal has no ID."""
        # Arrange
        journal = create_test_journal()
        changed_fields = {"title": "Updated Title"}

        # Act & Assert
        with pytest.raises(JournalValidationError):
            await journal_service.update_journal(
                journal, changed_fields, mock_transaction
            )

    @pytest.mark.asyncio
    async def test_update_journal_parent_validates_hierarchy(
        self, journal_service, mock_journal_repo, mock_event_publisher, mock_transaction
    ):
        """Test updating parent validates hierarchy."""
        # Arrange
        parent_journal = create_test_journal(journal_id=2, title="Parent Journal")
        journal = create_test_journal(journal_id=1, title="Child Journal", parent_id=2)
        changed_fields = {"parent_id": 2}

        mock_journal_repo.find_by_id.return_value = parent_journal
        mock_journal_repo.get_depth.return_value = 1
        mock_journal_repo.get_ancestors.return_value = []
        mock_journal_repo.save.return_value = journal

        # Act
        result = await journal_service.update_journal(
            journal, changed_fields, mock_transaction
        )

        # Assert
        assert result == journal
        mock_journal_repo.find_by_id.assert_called_once_with(2)
        mock_journal_repo.get_depth.assert_called_once_with(2)
        mock_journal_repo.get_ancestors.assert_called_once_with(2)

    @pytest.mark.asyncio
    async def test_update_journal_cycle_detection(
        self, journal_service, mock_journal_repo, mock_transaction
    ):
        """Test update fails when it would create a cycle."""
        # Arrange
        parent_journal = create_test_journal(journal_id=2, title="Parent Journal")
        # Journal 1 trying to set parent to 2, but 1 is an ancestor of 2
        journal = create_test_journal(journal_id=1, title="Child Journal", parent_id=2)
        changed_fields = {"parent_id": 2}

        # Mock: journal 1 is an ancestor of journal 2
        ancestor_journal = create_test_journal(journal_id=1, title="Child Journal")

        mock_journal_repo.find_by_id.return_value = parent_journal
        mock_journal_repo.get_depth.return_value = 1
        mock_journal_repo.get_ancestors.return_value = [ancestor_journal]

        # Act & Assert
        with pytest.raises(JournalCycleError):
            await journal_service.update_journal(
                journal, changed_fields, mock_transaction
            )

    @pytest.mark.asyncio
    async def test_delete_journal_success(
        self, journal_service, mock_journal_repo, mock_event_publisher, mock_transaction
    ):
        """Test successful journal deletion."""
        # Arrange
        journal = create_test_journal(journal_id=1)

        mock_journal_repo.find_by_id.return_value = journal

        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_transaction.execute.return_value = mock_result

        # Act
        await journal_service.delete_journal(1, mock_transaction)

        # Assert
        mock_journal_repo.find_by_id.assert_called_once_with(1)
        mock_journal_repo.delete.assert_called_once_with(1)
        mock_event_publisher.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_journal_not_found(
        self, journal_service, mock_journal_repo, mock_transaction
    ):
        """Test delete fails when journal doesn't exist."""
        # Arrange
        mock_journal_repo.find_by_id.return_value = None

        # Act & Assert
        with pytest.raises(JournalNotFoundError):
            await journal_service.delete_journal(999, mock_transaction)

    @pytest.mark.asyncio
    async def test_get_journal_success(self, journal_service, mock_journal_repo):
        """Test successful journal retrieval."""
        # Arrange
        journal = create_test_journal(journal_id=1)

        mock_journal_repo.find_by_id.return_value = journal

        # Act
        result = await journal_service.get_journal(1)

        # Assert
        assert result == journal
        mock_journal_repo.find_by_id.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_get_journal_not_found(self, journal_service, mock_journal_repo):
        """Test get_journal returns None when journal doesn't exist."""
        # Arrange
        mock_journal_repo.find_by_id.return_value = None

        # Act
        result = await journal_service.get_journal(999)

        # Assert
        assert result is None
        mock_journal_repo.find_by_id.assert_called_once_with(999)


class TestJournalServiceTypeManagement:
    """Test type management operations."""

    @pytest.mark.asyncio
    async def test_add_type_to_journal_success(
        self, journal_service, mock_journal_repo, mock_event_publisher, mock_transaction
    ):
        """Test successful type addition."""
        # Arrange
        journal = create_test_journal(journal_id=1)

        mock_journal_repo.find_by_id.return_value = journal

        # Act
        result = await journal_service.add_type_to_journal(
            1, JournalType.EVENT, mock_transaction
        )

        # Assert
        assert result == [JournalType.EVENT]
        mock_journal_repo.find_by_id.assert_called_once_with(1)
        mock_event_publisher.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_type_to_journal_not_found(
        self, journal_service, mock_journal_repo, mock_transaction
    ):
        """Test add type fails when journal doesn't exist."""
        # Arrange
        mock_journal_repo.find_by_id.return_value = None

        # Act & Assert
        with pytest.raises(JournalNotFoundError):
            await journal_service.add_type_to_journal(
                999, JournalType.EVENT, mock_transaction
            )

    @pytest.mark.asyncio
    async def test_remove_type_from_journal_success(
        self, journal_service, mock_journal_repo, mock_event_publisher, mock_transaction
    ):
        """Test successful type removal."""
        # Arrange
        journal = create_test_journal(journal_id=1)

        mock_journal_repo.find_by_id.return_value = journal

        # Act
        await journal_service.remove_type_from_journal(
            1, JournalType.EVENT, mock_transaction
        )

        # Assert
        mock_journal_repo.find_by_id.assert_called_once_with(1)
        mock_event_publisher.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_type_from_journal_not_found(
        self, journal_service, mock_journal_repo, mock_transaction
    ):
        """Test remove type fails when journal doesn't exist."""
        # Arrange
        mock_journal_repo.find_by_id.return_value = None

        # Act & Assert
        with pytest.raises(JournalNotFoundError):
            await journal_service.remove_type_from_journal(
                999, JournalType.EVENT, mock_transaction
            )

    def test_resolve_type_dependencies_base_type(self, journal_service):
        """Test dependency resolution for base types (no dependencies)."""
        # Act
        result = journal_service._resolve_type_dependencies(JournalType.EVENT)

        # Assert
        assert result == [JournalType.EVENT]

    def test_resolve_type_dependencies_note_type(self, journal_service):
        """Test dependency resolution for NOTE type."""
        # Act
        result = journal_service._resolve_type_dependencies(JournalType.NOTE)

        # Assert
        assert result == [JournalType.NOTE]

    def test_resolve_type_dependencies_all_base_types(self, journal_service):
        """Test all base types have no dependencies."""
        # Arrange
        base_types = [
            JournalType.NOTE,
            JournalType.EVENT,
            JournalType.MOOD_RATING,
            JournalType.PLAN,
            JournalType.TRAVEL,
            JournalType.PHOTO_ALBUM,
        ]

        # Act & Assert
        for jtype in base_types:
            result = journal_service._resolve_type_dependencies(jtype)
            assert result == [jtype], f"Type {jtype} should have no dependencies"
