"""Integration tests for SqlJournalRepository."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.models.entities import Journal
from app.core.journal.models.exceptions import JournalNotFoundError
from app.core.journal.models.value_objects import EventDateRange


@pytest_asyncio.fixture
async def journal_repository(
    async_connection: AsyncConnection,
) -> SqlJournalRepository:
    """Create a journal repository for testing."""
    return SqlJournalRepository(async_connection)


def create_test_journal(
    user_id: str = "test-user-123",
    title: str = "Test Journal",
    content: str = "Test content",
    start: datetime | None = None,
    end: datetime | None = None,
    parent_id: int | None = None,
    order: int | None = None,
) -> Journal:
    """Helper function to create a test journal."""
    now = datetime.now(UTC)
    return Journal(
        user_id=user_id,
        title=title,
        content=content,
        event_date_range=EventDateRange(
            start=start or now,
            end=end or now + timedelta(hours=1),
        ),
        parent_id=parent_id,
        order=order,
    )


@pytest.mark.integration
class TestJournalRepositorySave:
    """Test journal save operations."""

    async def test_save_creates_new_journal(
        self, journal_repository: SqlJournalRepository
    ):
        """Test creating a new journal."""
        journal = create_test_journal()

        saved = await journal_repository.save(journal)

        assert saved.id is not None
        assert saved.user_id == "test-user-123"
        assert saved.title == "Test Journal"
        assert saved.content == "Test content"
        assert saved.created_at is not None
        assert saved.updated_at is not None

    async def test_save_with_parent_id(self, journal_repository: SqlJournalRepository):
        """Test creating a child journal with parent_id."""
        parent = create_test_journal(title="Parent Journal")
        saved_parent = await journal_repository.save(parent)

        child = create_test_journal(
            title="Child Journal",
            parent_id=saved_parent.id,
        )
        saved_child = await journal_repository.save(child)

        assert saved_child.id is not None
        assert saved_child.parent_id == saved_parent.id

    async def test_save_updates_existing_journal(
        self, journal_repository: SqlJournalRepository
    ):
        """Test updating an existing journal."""
        journal = create_test_journal()
        saved = await journal_repository.save(journal)

        # Update the title
        saved.title = "Updated Title"
        updated = await journal_repository.save(saved)

        assert updated.id == saved.id
        assert updated.title == "Updated Title"
        assert updated.updated_at is not None
        assert saved.updated_at is not None
        assert updated.updated_at >= saved.updated_at


@pytest.mark.integration
class TestJournalRepositoryFindById:
    """Test journal find by ID operations."""

    async def test_find_by_id_returns_journal(
        self, journal_repository: SqlJournalRepository
    ):
        """Test finding a journal by ID."""
        journal = create_test_journal()
        saved = await journal_repository.save(journal)

        found = await journal_repository.find_by_id(saved.id)  # type: ignore[arg-type]

        assert found is not None
        assert found.id == saved.id
        assert found.title == saved.title

    async def test_find_by_id_returns_none_for_missing(
        self, journal_repository: SqlJournalRepository
    ):
        """Test finding a non-existent journal returns None."""
        found = await journal_repository.find_by_id(99999)

        assert found is None


@pytest.mark.integration
class TestJournalRepositoryDelete:
    """Test journal delete operations."""

    async def test_delete_removes_journal(
        self, journal_repository: SqlJournalRepository
    ):
        """Test deleting a journal."""
        journal = create_test_journal()
        saved = await journal_repository.save(journal)

        await journal_repository.delete(saved.id)  # type: ignore[arg-type]

        found = await journal_repository.find_by_id(saved.id)  # type: ignore[arg-type]
        assert found is None

    async def test_delete_nonexistent_raises_error(
        self, journal_repository: SqlJournalRepository
    ):
        """Test deleting a non-existent journal raises error."""
        with pytest.raises(JournalNotFoundError):
            await journal_repository.delete(99999)

    async def test_delete_parent_orphans_children(
        self, journal_repository: SqlJournalRepository
    ):
        """Test deleting a parent sets children's parent_id to NULL."""
        parent = create_test_journal(title="Parent")
        saved_parent = await journal_repository.save(parent)

        child = create_test_journal(title="Child", parent_id=saved_parent.id)
        saved_child = await journal_repository.save(child)

        await journal_repository.delete(saved_parent.id)  # type: ignore[arg-type]

        # Child should still exist but with parent_id = NULL
        found_child = await journal_repository.find_by_id(saved_child.id)  # type: ignore[arg-type]
        assert found_child is not None
        assert found_child.parent_id is None


@pytest.mark.integration
class TestJournalRepositoryHierarchy:
    """Test journal hierarchy operations."""

    async def test_get_children_returns_child_journals(
        self, journal_repository: SqlJournalRepository
    ):
        """Test getting child journals of a parent."""
        parent = create_test_journal(title="Parent")
        saved_parent = await journal_repository.save(parent)

        child1 = create_test_journal(title="Child 1", parent_id=saved_parent.id)
        child2 = create_test_journal(title="Child 2", parent_id=saved_parent.id)
        await journal_repository.save(child1)
        await journal_repository.save(child2)

        children = await journal_repository.get_children(saved_parent.id)  # type: ignore[arg-type]

        assert len(children) == 2
        assert {c.title for c in children} == {"Child 1", "Child 2"}

    async def test_get_children_ordered_by_date_then_order(
        self, journal_repository: SqlJournalRepository
    ):
        """Test children are ordered by event_date_range.start, then order field."""
        parent = create_test_journal(title="Parent")
        saved_parent = await journal_repository.save(parent)

        now = datetime.now(UTC)

        # Create children with different dates and orders
        child1 = create_test_journal(
            title="Third",
            parent_id=saved_parent.id,
            start=now + timedelta(days=2),
            end=now + timedelta(days=2, hours=1),
        )
        child2 = create_test_journal(
            title="First",
            parent_id=saved_parent.id,
            start=now,
            end=now + timedelta(hours=1),
            order=1,
        )
        child3 = create_test_journal(
            title="Second",
            parent_id=saved_parent.id,
            start=now,
            end=now + timedelta(hours=1),
            order=2,
        )

        await journal_repository.save(child1)
        await journal_repository.save(child2)
        await journal_repository.save(child3)

        children = await journal_repository.get_children(saved_parent.id)  # type: ignore[arg-type]

        assert len(children) == 3
        assert children[0].title == "First"  # Same date, order=1
        assert children[1].title == "Second"  # Same date, order=2
        assert children[2].title == "Third"  # Later date

    async def test_get_ancestors_returns_parent_chain(
        self, journal_repository: SqlJournalRepository
    ):
        """Test getting all ancestors from parent to root."""
        root = create_test_journal(title="Root")
        saved_root = await journal_repository.save(root)

        level1 = create_test_journal(title="Level 1", parent_id=saved_root.id)
        saved_level1 = await journal_repository.save(level1)

        level2 = create_test_journal(title="Level 2", parent_id=saved_level1.id)
        saved_level2 = await journal_repository.save(level2)

        ancestors = await journal_repository.get_ancestors(saved_level2.id)  # type: ignore[arg-type]

        assert len(ancestors) == 2
        assert ancestors[0].title == "Level 1"  # Immediate parent
        assert ancestors[1].title == "Root"  # Root ancestor

    async def test_get_depth_returns_correct_depth(
        self, journal_repository: SqlJournalRepository
    ):
        """Test depth calculation (1 for root, 2 for first-level child, etc.)."""
        root = create_test_journal(title="Root")
        saved_root = await journal_repository.save(root)

        level1 = create_test_journal(title="Level 1", parent_id=saved_root.id)
        saved_level1 = await journal_repository.save(level1)

        level2 = create_test_journal(title="Level 2", parent_id=saved_level1.id)
        saved_level2 = await journal_repository.save(level2)

        assert await journal_repository.get_depth(saved_root.id) == 1  # type: ignore[arg-type]
        assert await journal_repository.get_depth(saved_level1.id) == 2  # type: ignore[arg-type]
        assert await journal_repository.get_depth(saved_level2.id) == 3  # type: ignore[arg-type]


@pytest.mark.integration
class TestJournalRepositoryQueries:
    """Test journal query operations."""

    async def test_get_all_returns_user_journals(
        self, journal_repository: SqlJournalRepository
    ):
        """Test getting all journals for a user."""
        user1_j1 = create_test_journal(user_id="user-1", title="User 1 Journal 1")
        user1_j2 = create_test_journal(user_id="user-1", title="User 1 Journal 2")
        user2_j1 = create_test_journal(user_id="user-2", title="User 2 Journal 1")

        await journal_repository.save(user1_j1)
        await journal_repository.save(user1_j2)
        await journal_repository.save(user2_j1)

        user1_journals = await journal_repository.get_all("user-1")

        assert len(user1_journals) == 2
        assert all(j.user_id == "user-1" for j in user1_journals)

    async def test_get_root_journals_excludes_children(
        self, journal_repository: SqlJournalRepository
    ):
        """Test getting only root journals (no parent)."""
        root = create_test_journal(title="Root")
        saved_root = await journal_repository.save(root)

        child = create_test_journal(title="Child", parent_id=saved_root.id)
        await journal_repository.save(child)

        roots = await journal_repository.get_root_journals("test-user-123")

        assert len(roots) == 1
        assert roots[0].title == "Root"

    async def test_count_by_user_returns_correct_count(
        self, journal_repository: SqlJournalRepository
    ):
        """Test counting journals for a user."""
        for i in range(3):
            journal = create_test_journal(title=f"Journal {i}")
            await journal_repository.save(journal)

        count = await journal_repository.count_by_user("test-user-123")

        assert count == 3
