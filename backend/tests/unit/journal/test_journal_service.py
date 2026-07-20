"""Unit tests for JournalService."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

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

from app.core.journal.models.journal_tag import JournalTag
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
        """Test successful journal update computes changed_fields and publishes."""
        # Arrange: persisted journal has the old title; the update changes it.
        existing = create_test_journal(journal_id=1, title="Original Title")
        journal = create_test_journal(journal_id=1, title="Updated Title")

        mock_journal_repo.find_by_id.return_value = existing
        mock_journal_repo.save.return_value = journal

        # Act
        result = await journal_service.update_journal(journal, mock_transaction)

        # Assert
        assert result == journal
        mock_journal_repo.find_by_id.assert_called_once_with(1)
        mock_journal_repo.save.assert_called_once_with(journal)
        mock_event_publisher.publish.assert_called_once()
        published_event = mock_event_publisher.publish.call_args[0][0]
        assert published_event.event_data["changed_fields"]["title"] == (
            "Original Title",
            "Updated Title",
        )

    @pytest.mark.asyncio
    async def test_update_journal_no_id_fails(self, journal_service, mock_transaction):
        """Test update fails when journal has no ID."""
        # Arrange
        journal = create_test_journal()

        # Act & Assert
        with pytest.raises(JournalValidationError):
            await journal_service.update_journal(journal, mock_transaction)

    @pytest.mark.asyncio
    async def test_update_journal_missing_journal_raises_not_found(
        self, journal_service, mock_journal_repo, mock_transaction
    ):
        """Test update fails when the persisted journal does not exist."""
        # Arrange
        journal = create_test_journal(journal_id=42, title="Ghost")
        mock_journal_repo.find_by_id.return_value = None

        # Act & Assert
        with pytest.raises(JournalNotFoundError):
            await journal_service.update_journal(journal, mock_transaction)

    @pytest.mark.asyncio
    async def test_update_journal_parent_validates_hierarchy(
        self, journal_service, mock_journal_repo, mock_event_publisher, mock_transaction
    ):
        """Test updating parent validates hierarchy."""
        # Arrange
        existing = create_test_journal(journal_id=1, title="Child Journal")
        parent_journal = create_test_journal(journal_id=2, title="Parent Journal")
        journal = create_test_journal(journal_id=1, title="Child Journal", parent_id=2)

        # find_by_id(1) -> persisted journal (for diff); find_by_id(2) -> parent.
        mock_journal_repo.find_by_id.side_effect = lambda jid: {
            1: existing,
            2: parent_journal,
        }.get(jid)
        mock_journal_repo.get_depth.return_value = 1
        mock_journal_repo.get_ancestors.return_value = []
        mock_journal_repo.save.return_value = journal

        # Act
        result = await journal_service.update_journal(journal, mock_transaction)

        # Assert
        assert result == journal
        mock_journal_repo.get_depth.assert_called_once_with(2)
        mock_journal_repo.get_ancestors.assert_called_once_with(2)

    @pytest.mark.asyncio
    async def test_update_journal_cycle_detection(
        self, journal_service, mock_journal_repo, mock_transaction
    ):
        """Test update fails when it would create a cycle."""
        # Arrange
        existing = create_test_journal(journal_id=1, title="Child Journal")
        parent_journal = create_test_journal(journal_id=2, title="Parent Journal")
        # Journal 1 trying to set parent to 2, but 1 is an ancestor of 2
        journal = create_test_journal(journal_id=1, title="Child Journal", parent_id=2)

        # Mock: journal 1 is an ancestor of journal 2
        ancestor_journal = create_test_journal(journal_id=1, title="Child Journal")

        mock_journal_repo.find_by_id.side_effect = lambda jid: {
            1: existing,
            2: parent_journal,
        }.get(jid)
        mock_journal_repo.get_depth.return_value = 1
        mock_journal_repo.get_ancestors.return_value = [ancestor_journal]

        # Act & Assert
        with pytest.raises(JournalCycleError):
            await journal_service.update_journal(journal, mock_transaction)

    @pytest.mark.asyncio
    async def test_delete_journal_success(
        self, journal_service, mock_journal_repo, mock_event_publisher, mock_transaction
    ):
        """Test successful journal deletion."""
        # Arrange
        journal = create_test_journal(journal_id=1)

        mock_journal_repo.find_by_id.return_value = journal

        mock_result = MagicMock()
        mock_row1 = MagicMock()
        mock_row1.external_event_id = "ext1"
        mock_row1.google_calendar_id = "cal1"
        mock_row2 = MagicMock()
        mock_row2.external_event_id = "ext2"
        mock_row2.google_calendar_id = "cal2"
        mock_result.fetchall.return_value = [mock_row1, mock_row2]
        mock_transaction.execute.return_value = mock_result

        # Act
        await journal_service.delete_journal(1, mock_transaction)

        # Assert
        mock_journal_repo.find_by_id.assert_called_once_with(1)
        mock_journal_repo.delete.assert_called_once_with(1)
        mock_event_publisher.publish.assert_called_once()
        published_event = mock_event_publisher.publish.mock_calls[0][1][0]
        assert "google" in published_event.event_data["external_identifiers"]
        assert len(published_event.event_data["external_identifiers"]["google"]) == 2
        assert (
            published_event.event_data["external_identifiers"]["google"][0][
                "external_event_id"
            ]
            == "ext1"
        )

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


class TestTagFilterExpansion:
    """Tag filters expand to descendants before reaching the repository.

    Mirrors ``ContactService._expand_tag_ids_with_descendants`` so a journal
    tagged only with a child tag is returned when filtering by its parent.
    """

    @pytest.fixture
    def mock_tag_hierarchy(self):
        """Create a mock journal tag hierarchy service."""
        return AsyncMock()

    @pytest.fixture
    def service_with_hierarchy(
        self, mock_journal_repo, mock_event_publisher, mock_tag_hierarchy
    ):
        """Create a JournalService wired to the mocked hierarchy service."""
        return JournalService(
            journal_repo=mock_journal_repo,
            event_publisher=mock_event_publisher,
            tag_hierarchy=mock_tag_hierarchy,
        )

    @staticmethod
    def _tag(tag_id: UUID, name: str) -> JournalTag:
        return JournalTag(id=tag_id, name=name)

    async def test_parent_tag_expands_to_all_descendants(
        self, service_with_hierarchy, mock_journal_repo, mock_tag_hierarchy
    ):
        parent_id, child_id, grandchild_id = uuid4(), uuid4(), uuid4()
        mock_tag_hierarchy.get_all_descendants_bulk.return_value = [
            self._tag(child_id, "Child"),
            self._tag(grandchild_id, "Grandchild"),
        ]
        mock_journal_repo.get_all.return_value = []

        await service_with_hierarchy.get_journals_paginated(
            user_id="user123", tag_ids=[str(parent_id)]
        )

        passed_tag_ids = mock_journal_repo.get_all.call_args.kwargs["tag_ids"]
        assert set(passed_tag_ids) == {
            str(parent_id),
            str(child_id),
            str(grandchild_id),
        }

    async def test_count_expands_parent_tag(
        self, service_with_hierarchy, mock_journal_repo, mock_tag_hierarchy
    ):
        parent_id, child_id = uuid4(), uuid4()
        mock_tag_hierarchy.get_all_descendants_bulk.return_value = [
            self._tag(child_id, "Child")
        ]
        mock_journal_repo.count_all.return_value = 0

        await service_with_hierarchy.get_journals_count(
            user_id="user123", tag_ids=[str(parent_id)]
        )

        passed_tag_ids = mock_journal_repo.count_all.call_args.kwargs["tag_ids"]
        assert set(passed_tag_ids) == {str(parent_id), str(child_id)}

    async def test_multiple_tags_are_deduplicated(
        self, service_with_hierarchy, mock_journal_repo, mock_tag_hierarchy
    ):
        parent_id, shared_child_id, other_id = uuid4(), uuid4(), uuid4()
        mock_tag_hierarchy.get_all_descendants_bulk.return_value = [
            self._tag(shared_child_id, "Shared"),
        ]
        mock_journal_repo.get_all.return_value = []

        await service_with_hierarchy.get_journals_paginated(
            user_id="user123",
            tag_ids=[str(parent_id), str(other_id), str(parent_id)],
        )

        passed_tag_ids = mock_journal_repo.get_all.call_args.kwargs["tag_ids"]
        assert sorted(passed_tag_ids) == sorted(
            {str(parent_id), str(other_id), str(shared_child_id)}
        )
        assert len(passed_tag_ids) == len(set(passed_tag_ids))

    async def test_leaf_tag_passes_through_unchanged(
        self, service_with_hierarchy, mock_journal_repo, mock_tag_hierarchy
    ):
        leaf_id = uuid4()
        mock_tag_hierarchy.get_all_descendants_bulk.return_value = []
        mock_journal_repo.get_all.return_value = []

        await service_with_hierarchy.get_journals_paginated(
            user_id="user123", tag_ids=[str(leaf_id)]
        )

        assert mock_journal_repo.get_all.call_args.kwargs["tag_ids"] == [str(leaf_id)]

    async def test_no_tag_filter_skips_expansion(
        self, service_with_hierarchy, mock_journal_repo, mock_tag_hierarchy
    ):
        mock_journal_repo.get_all.return_value = []

        await service_with_hierarchy.get_journals_paginated(user_id="user123")

        mock_tag_hierarchy.get_all_descendants_bulk.assert_not_awaited()
        assert mock_journal_repo.get_all.call_args.kwargs["tag_ids"] is None

    async def test_malformed_tag_id_is_skipped_by_expansion(
        self, service_with_hierarchy, mock_journal_repo, mock_tag_hierarchy
    ):
        """A non-UUID id is skipped for the hierarchy lookup rather than raising.

        The REST layer rejects malformed ids with a 400 before reaching here.
        """
        mock_tag_hierarchy.get_all_descendants_bulk.return_value = []
        mock_journal_repo.get_all.return_value = []

        await service_with_hierarchy.get_journals_paginated(
            user_id="user123", tag_ids=["not-a-uuid"]
        )

        mock_tag_hierarchy.get_all_descendants_bulk.assert_awaited_once_with([])
        assert mock_journal_repo.get_all.call_args.kwargs["tag_ids"] == ["not-a-uuid"]

    async def test_uuid_objects_are_expanded_not_skipped(
        self, service_with_hierarchy, mock_journal_repo, mock_tag_hierarchy
    ):
        """A caller holding UUID objects gets expansion, not a TypeError."""
        parent_id, child_id = uuid4(), uuid4()
        mock_tag_hierarchy.get_all_descendants_bulk.return_value = [
            self._tag(child_id, "Child")
        ]
        mock_journal_repo.get_all.return_value = []

        await service_with_hierarchy.get_journals_paginated(
            user_id="user123", tag_ids=[parent_id]
        )

        mock_tag_hierarchy.get_all_descendants_bulk.assert_awaited_once_with(
            [parent_id]
        )
        assert str(child_id) in mock_journal_repo.get_all.call_args.kwargs["tag_ids"]

    async def test_uuid_and_string_spellings_dedupe_to_one_string(
        self, service_with_hierarchy, mock_journal_repo, mock_tag_hierarchy
    ):
        """The same tag given as UUID and str collapses to a single str entry."""
        tag_id = uuid4()
        mock_tag_hierarchy.get_all_descendants_bulk.return_value = []
        mock_journal_repo.get_all.return_value = []

        await service_with_hierarchy.get_journals_paginated(
            user_id="user123", tag_ids=[tag_id, str(tag_id)]
        )

        passed_tag_ids = mock_journal_repo.get_all.call_args.kwargs["tag_ids"]
        assert passed_tag_ids == [str(tag_id)]
        assert all(isinstance(value, str) for value in passed_tag_ids)

    async def test_expansion_skipped_when_hierarchy_unavailable(
        self, mock_journal_repo, mock_event_publisher
    ):
        """Without the optional dependency the filter stays flat, not broken."""
        service = JournalService(
            journal_repo=mock_journal_repo,
            event_publisher=mock_event_publisher,
        )
        tag_id = uuid4()
        mock_journal_repo.get_all.return_value = []

        await service.get_journals_paginated(user_id="user123", tag_ids=[str(tag_id)])

        assert mock_journal_repo.get_all.call_args.kwargs["tag_ids"] == [str(tag_id)]
