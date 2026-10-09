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
from tests.integration.contact_seeding import TEST_USER_ID


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


def _no_anchored_tasks() -> AsyncMock:
    """An anchor repository that reports nothing blocking a journal delete.

    The guard is a required collaborator, so every service built here has to
    supply one; these tests are about other behaviour, so it always answers
    "nothing is anchored". The delete guard has its own suite in
    ``test_journal_delete_guard.py``.
    """
    repo = AsyncMock()
    repo.find_tasks_anchored_to_journal.return_value = []
    return repo


@pytest.fixture
def journal_service(mock_journal_repo, mock_event_publisher):
    """Create a JournalService instance with mocked dependencies."""
    return JournalService(
        journal_repo=mock_journal_repo,
        event_publisher=mock_event_publisher,
        task_anchor_repo=_no_anchored_tasks(),
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


def owner_scoped_lookup(journals: dict[int, Journal]):
    """A ``find_by_id_for_user`` stub that honours the owner predicate.

    The real implementation puts ``user_id`` in the WHERE clause, so a journal
    belonging to somebody else is indistinguishable from one that never
    existed. A bare ``AsyncMock`` would hand back the journal regardless and
    the ownership assertion would be vacuous.
    """

    def _find(journal_id: int, user_id: str) -> Journal | None:
        journal = journals.get(journal_id)
        if journal is None or journal.user_id != user_id:
            return None
        return journal

    return _find


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

        mock_journal_repo.find_by_id_for_user.return_value = parent_journal
        mock_journal_repo.get_depth.return_value = 1
        mock_journal_repo.save.return_value = saved_journal

        # Act
        result = await journal_service.create_journal(journal, mock_transaction)

        # Assert
        assert result == saved_journal
        mock_journal_repo.find_by_id_for_user.assert_called_once_with(1, "user123")
        mock_journal_repo.get_depth.assert_called_once_with(1)
        mock_journal_repo.save.assert_called_once_with(journal)

    @pytest.mark.asyncio
    async def test_create_journal_parent_not_found(
        self, journal_service, mock_journal_repo, mock_transaction
    ):
        """Test journal creation fails when parent doesn't exist."""
        # Arrange
        journal = create_test_journal(title="Child Journal", parent_id=999)

        mock_journal_repo.find_by_id_for_user.return_value = None

        # Act & Assert
        with pytest.raises(JournalNotFoundError):
            await journal_service.create_journal(journal, mock_transaction)

    @pytest.mark.asyncio
    async def test_create_journal_rejects_another_users_parent(
        self, journal_service, mock_journal_repo, mock_transaction
    ):
        """Another user's journal cannot be used as a parent (issue #1312).

        The parent has to be resolved owner-scoped, so it reads as missing
        rather than as a usable parent — the same answer an id that never
        existed gets, which is what keeps the surface from confirming it is
        real. Resolving it unscoped hung the caller's journal off a stranger's:
        a child the victim can neither see nor delete.
        """
        # Arrange
        foreign_parent = create_test_journal(
            journal_id=1, title="Somebody Else's Journal", user_id="other-user"
        )
        journal = create_test_journal(title="Child Journal", parent_id=1)

        # The unscoped lookup still finds it — that is precisely the bug.
        mock_journal_repo.find_by_id.return_value = foreign_parent
        mock_journal_repo.find_by_id_for_user.side_effect = owner_scoped_lookup(
            {1: foreign_parent}
        )

        # Act & Assert
        with pytest.raises(JournalNotFoundError):
            await journal_service.create_journal(journal, mock_transaction)

        mock_journal_repo.save.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_journal_max_depth_exceeded(
        self, journal_service, mock_journal_repo, mock_transaction
    ):
        """Test journal creation fails when max depth is exceeded."""
        # Arrange
        parent_journal = create_test_journal(journal_id=1, title="Parent Journal")
        journal = create_test_journal(title="Child Journal", parent_id=1)

        mock_journal_repo.find_by_id_for_user.return_value = parent_journal
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

        # find_by_id(1) -> persisted journal (for the diff); the parent is
        # resolved owner-scoped.
        mock_journal_repo.find_by_id.return_value = existing
        mock_journal_repo.find_by_id_for_user.side_effect = owner_scoped_lookup(
            {1: existing, 2: parent_journal}
        )
        mock_journal_repo.get_depth.return_value = 1
        mock_journal_repo.get_ancestors.return_value = []
        mock_journal_repo.save.return_value = journal

        # Act
        result = await journal_service.update_journal(journal, mock_transaction)

        # Assert
        assert result == journal
        mock_journal_repo.find_by_id_for_user.assert_called_once_with(2, "user123")
        mock_journal_repo.get_depth.assert_called_once_with(2)
        mock_journal_repo.get_ancestors.assert_called_once_with(2)

    @pytest.mark.asyncio
    async def test_update_journal_rejects_another_users_parent(
        self, journal_service, mock_journal_repo, mock_transaction
    ):
        """Re-parenting onto somebody else's journal is refused (issue #1312)."""
        # Arrange
        existing = create_test_journal(journal_id=1, title="My Journal")
        foreign_parent = create_test_journal(
            journal_id=2, title="Somebody Else's Journal", user_id="other-user"
        )
        journal = create_test_journal(journal_id=1, title="My Journal", parent_id=2)

        mock_journal_repo.find_by_id.side_effect = lambda jid: {
            1: existing,
            2: foreign_parent,
        }.get(jid)
        mock_journal_repo.find_by_id_for_user.side_effect = owner_scoped_lookup(
            {1: existing, 2: foreign_parent}
        )

        # Act & Assert
        with pytest.raises(JournalNotFoundError):
            await journal_service.update_journal(journal, mock_transaction)

        mock_journal_repo.save.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_journal_refuses_to_change_the_owner(
        self, journal_service, mock_journal_repo, mock_transaction
    ):
        """An update may not move a journal to a different user.

        ``_update`` writes ``user_id`` straight from the entity it is handed and
        ``_calculate_changed_fields`` does not diff it, so without this guard a
        mismatched owner was persisted silently and left no history row. The
        calendar sync reaches exactly that: it rebuilds the journal taking
        parent_id and order from the stored row but user_id from the event
        payload, so a journal whose calendar belongs to somebody else was
        re-owned to them on the next sync.
        """
        # Arrange
        existing = create_test_journal(journal_id=1, title="My Journal")
        journal = create_test_journal(
            journal_id=1, title="My Journal", user_id="other-user"
        )

        mock_journal_repo.find_by_id.return_value = existing

        # Act & Assert
        with pytest.raises(JournalValidationError):
            await journal_service.update_journal(journal, mock_transaction)

        mock_journal_repo.save.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_journal_refuses_an_owner_change_before_reparenting(
        self, journal_service, mock_journal_repo, mock_transaction
    ):
        """The owner guard runs first, so a re-parent cannot ride along with it.

        The entity here is internally consistent — it claims ``other-user``'s
        ownership *and* points at ``other-user``'s journal — which is what a
        parent lookup reading the owner off the argument would accept. The
        guard rejects the whole update before the hierarchy is consulted.
        """
        # Arrange
        existing = create_test_journal(journal_id=1, title="My Journal")
        foreign_parent = create_test_journal(
            journal_id=2, title="Somebody Else's Journal", user_id="other-user"
        )
        journal = create_test_journal(
            journal_id=1,
            title="My Journal",
            parent_id=2,
            user_id="other-user",
        )

        mock_journal_repo.find_by_id.return_value = existing
        mock_journal_repo.find_by_id_for_user.side_effect = owner_scoped_lookup(
            {1: existing, 2: foreign_parent}
        )

        # Act & Assert
        with pytest.raises(JournalValidationError):
            await journal_service.update_journal(journal, mock_transaction)

        mock_journal_repo.find_by_id_for_user.assert_not_called()
        mock_journal_repo.save.assert_not_called()

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

        mock_journal_repo.find_by_id.return_value = existing
        mock_journal_repo.find_by_id_for_user.side_effect = owner_scoped_lookup(
            {1: existing, 2: parent_journal}
        )
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
        mock_row1.calendar_id = "cal-uuid-1"
        mock_row1.google_calendar_id = "cal1"
        mock_row1.integration_source = "google"
        mock_row2 = MagicMock()
        mock_row2.external_event_id = "ext2"
        mock_row2.calendar_id = "cal-uuid-2"
        mock_row2.google_calendar_id = "cal2"
        mock_row2.integration_source = "google"
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
            task_anchor_repo=_no_anchored_tasks(),
        )

    @staticmethod
    def _tag(tag_id: UUID, name: str) -> JournalTag:
        return JournalTag(user_id=TEST_USER_ID, id=tag_id, name=name)

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
            task_anchor_repo=_no_anchored_tasks(),
        )
        tag_id = uuid4()
        mock_journal_repo.get_all.return_value = []

        await service.get_journals_paginated(user_id="user123", tag_ids=[str(tag_id)])

        assert mock_journal_repo.get_all.call_args.kwargs["tag_ids"] == [str(tag_id)]
