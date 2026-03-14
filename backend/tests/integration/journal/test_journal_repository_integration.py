"""Integration tests for SqlJournalRepository."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from core_shared.models.journals import EventDateRange, Journal, JournalNotFoundError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository


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


@pytest.mark.integration
class TestJournalRepositoryFiltering:
    """Test journal filtering operations."""

    async def test_filter_by_journal_type_mood(
        self,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """Test filtering journals by MOOD_RATING type."""
        # Create a regular journal (NOTE type - no type data)
        note_journal = create_test_journal(title="Note Journal")
        await journal_repository.save(note_journal)

        # Create a MOOD_RATING journal
        mood_journal = create_test_journal(title="Mood Journal")
        saved_mood = await journal_repository.save(mood_journal)

        # Add mood data to make it a MOOD_RATING type
        await async_connection.execute(
            text("""
            INSERT INTO journal_mood_data (journal_id, mood_value, mood_label, energy_level)
            VALUES (:journal_id, :mood_value, :mood_label, :energy_level)
            """),
            {
                "journal_id": saved_mood.id,
                "mood_value": 8,
                "mood_label": "Happy",
                "energy_level": 7,
            },
        )

        # Filter by MOOD_RATING type
        mood_journals = await journal_repository.get_all(
            "test-user-123", journal_type="MOOD_RATING"
        )

        assert len(mood_journals) == 1
        assert mood_journals[0].id == saved_mood.id
        assert mood_journals[0].title == "Mood Journal"

    async def test_filter_by_journal_type_note(
        self,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """Test filtering journals by NOTE type (journals with no type data)."""
        # Create a regular journal (NOTE type - no type data)
        note_journal = create_test_journal(title="Note Journal")
        saved_note = await journal_repository.save(note_journal)

        # Create a MOOD_RATING journal
        mood_journal = create_test_journal(title="Mood Journal")
        saved_mood = await journal_repository.save(mood_journal)

        # Add mood data to make it a MOOD_RATING type
        await async_connection.execute(
            text("""
            INSERT INTO journal_mood_data (journal_id, mood_value)
            VALUES (:journal_id, :mood_value)
            """),
            {"journal_id": saved_mood.id, "mood_value": 8},
        )

        # Filter by NOTE type
        note_journals = await journal_repository.get_all(
            "test-user-123", journal_type="NOTE"
        )

        assert len(note_journals) == 1
        assert note_journals[0].id == saved_note.id
        assert note_journals[0].title == "Note Journal"

    async def test_filter_by_date_range(self, journal_repository: SqlJournalRepository):
        """Test filtering journals by date range."""
        now = datetime.now(UTC)
        yesterday = now - timedelta(days=1)
        tomorrow = now + timedelta(days=1)
        next_week = now + timedelta(days=7)

        # Create journals with different dates
        old_journal = create_test_journal(
            title="Old Journal",
            start=yesterday - timedelta(days=5),
            end=yesterday,
        )
        current_journal = create_test_journal(
            title="Current Journal",
            start=now,
            end=tomorrow,
        )
        future_journal = create_test_journal(
            title="Future Journal",
            start=next_week,
            end=next_week + timedelta(hours=1),
        )

        await journal_repository.save(old_journal)
        await journal_repository.save(current_journal)
        await journal_repository.save(future_journal)

        # Filter by date range (yesterday to tomorrow)
        filtered = await journal_repository.get_all(
            "test-user-123",
            start_date=yesterday.isoformat(),
            end_date=tomorrow.isoformat(),
        )

        assert len(filtered) == 2
        titles = {j.title for j in filtered}
        assert "Old Journal" in titles  # Ends within range
        assert "Current Journal" in titles  # Starts within range

    async def test_filter_by_contact_id(
        self,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """Test filtering journals by contact ID."""
        # Create test contacts
        await async_connection.execute(
            text("""
            INSERT INTO contacts (id, first_name, last_name)
            VALUES (:id, :first_name, :last_name)
            """),
            {"id": 1, "first_name": "John", "last_name": "Doe"},
        )
        await async_connection.execute(
            text("""
            INSERT INTO contacts (id, first_name, last_name)
            VALUES (:id, :first_name, :last_name)
            """),
            {"id": 2, "first_name": "Jane", "last_name": "Smith"},
        )

        # Create journals
        journal1 = create_test_journal(title="Journal with John")
        saved1 = await journal_repository.save(journal1)

        journal2 = create_test_journal(title="Journal with Jane")
        saved2 = await journal_repository.save(journal2)

        journal3 = create_test_journal(title="Journal with both")
        saved3 = await journal_repository.save(journal3)

        # Link journals to contacts
        await async_connection.execute(
            text("""
            INSERT INTO journal_contact_relationships (journal_id, contact_id, relationship_type)
            VALUES (:journal_id, :contact_id, :relationship_type)
            """),
            {
                "journal_id": saved1.id,
                "contact_id": 1,
                "relationship_type": "PARTICIPANT",
            },
        )
        await async_connection.execute(
            text("""
            INSERT INTO journal_contact_relationships (journal_id, contact_id, relationship_type)
            VALUES (:journal_id, :contact_id, :relationship_type)
            """),
            {
                "journal_id": saved2.id,
                "contact_id": 2,
                "relationship_type": "PARTICIPANT",
            },
        )
        await async_connection.execute(
            text("""
            INSERT INTO journal_contact_relationships (journal_id, contact_id, relationship_type)
            VALUES (:journal_id, :contact_id, :relationship_type)
            """),
            {
                "journal_id": saved3.id,
                "contact_id": 1,
                "relationship_type": "PARTICIPANT",
            },
        )
        await async_connection.execute(
            text("""
            INSERT INTO journal_contact_relationships (journal_id, contact_id, relationship_type)
            VALUES (:journal_id, :contact_id, :relationship_type)
            """),
            {"journal_id": saved3.id, "contact_id": 2, "relationship_type": "MENTION"},
        )

        # Filter by contact_id=1
        filtered = await journal_repository.get_all("test-user-123", contact_id="1")

        assert len(filtered) == 2
        titles = {j.title for j in filtered}
        assert "Journal with John" in titles
        assert "Journal with both" in titles

    async def test_filter_by_tag_id(
        self,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """Test filtering journals by tag ID."""
        # Create test tags
        tag1_result = await async_connection.execute(
            text("""
            INSERT INTO journal_tags (name, color)
            VALUES (:name, :color)
            RETURNING id
            """),
            {"name": "Work", "color": "#FF0000"},
        )
        tag1_row = tag1_result.fetchone()
        assert tag1_row is not None
        tag1_id = tag1_row[0]

        tag2_result = await async_connection.execute(
            text("""
            INSERT INTO journal_tags (name, color)
            VALUES (:name, :color)
            RETURNING id
            """),
            {"name": "Personal", "color": "#00FF00"},
        )
        tag2_row = tag2_result.fetchone()
        assert tag2_row is not None
        tag2_id = tag2_row[0]

        # Create journals
        journal1 = create_test_journal(title="Work Journal")
        saved1 = await journal_repository.save(journal1)

        journal2 = create_test_journal(title="Personal Journal")
        saved2 = await journal_repository.save(journal2)

        # Link journals to tags
        await async_connection.execute(
            text("""
            INSERT INTO journal_tag_assignments (journal_id, tag_id)
            VALUES (:journal_id, :tag_id)
            """),
            {"journal_id": saved1.id, "tag_id": tag1_id},
        )
        await async_connection.execute(
            text("""
            INSERT INTO journal_tag_assignments (journal_id, tag_id)
            VALUES (:journal_id, :tag_id)
            """),
            {"journal_id": saved2.id, "tag_id": tag2_id},
        )

        # Filter by tag_id
        filtered = await journal_repository.get_all(
            "test-user-123", tag_id=str(tag1_id)
        )

        assert len(filtered) == 1
        assert filtered[0].title == "Work Journal"

    async def test_filter_by_calendar_id(
        self,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """Test filtering journals by calendar ID."""
        # Create test calendars
        cal1_result = await async_connection.execute(
            text("""
            INSERT INTO calendars (user_id, name, color)
            VALUES (:user_id, :name, :color)
            RETURNING id
            """),
            {"user_id": "test-user-123", "name": "Work Calendar", "color": "#FF0000"},
        )
        cal1_row = cal1_result.fetchone()
        assert cal1_row is not None
        cal1_id = cal1_row[0]

        cal2_result = await async_connection.execute(
            text("""
            INSERT INTO calendars (user_id, name, color)
            VALUES (:user_id, :name, :color)
            RETURNING id
            """),
            {
                "user_id": "test-user-123",
                "name": "Personal Calendar",
                "color": "#00FF00",
            },
        )
        cal2_row = cal2_result.fetchone()
        assert cal2_row is not None
        cal2_id = cal2_row[0]

        # Create EVENT journals
        journal1 = create_test_journal(title="Work Event")
        saved1 = await journal_repository.save(journal1)

        journal2 = create_test_journal(title="Personal Event")
        saved2 = await journal_repository.save(journal2)

        # Add calendar info to make them EVENT type
        await async_connection.execute(
            text("""
            INSERT INTO journal_calendar_info (journal_id, calendar_id, is_all_day)
            VALUES (:journal_id, :calendar_id, :is_all_day)
            """),
            {"journal_id": saved1.id, "calendar_id": cal1_id, "is_all_day": True},
        )
        await async_connection.execute(
            text("""
            INSERT INTO journal_calendar_info (journal_id, calendar_id, is_all_day)
            VALUES (:journal_id, :calendar_id, :is_all_day)
            """),
            {"journal_id": saved2.id, "calendar_id": cal2_id, "is_all_day": True},
        )

        # Filter by calendar_id
        filtered = await journal_repository.get_all(
            "test-user-123", calendar_id=str(cal1_id)
        )

        assert len(filtered) == 1
        assert filtered[0].title == "Work Event"

    async def test_filter_by_parent_id(self, journal_repository: SqlJournalRepository):
        """Test filtering journals by parent ID."""
        # Create parent journal
        parent = create_test_journal(title="Parent Journal")
        saved_parent = await journal_repository.save(parent)

        # Create child journals
        child1 = create_test_journal(title="Child 1", parent_id=saved_parent.id)
        child2 = create_test_journal(title="Child 2", parent_id=saved_parent.id)
        await journal_repository.save(child1)
        await journal_repository.save(child2)

        # Create another root journal
        other_root = create_test_journal(title="Other Root")
        await journal_repository.save(other_root)

        # Filter by parent_id
        filtered = await journal_repository.get_all(
            "test-user-123", parent_id=saved_parent.id
        )

        assert len(filtered) == 2
        titles = {j.title for j in filtered}
        assert "Child 1" in titles
        assert "Child 2" in titles

    async def test_filter_by_search_text(
        self, journal_repository: SqlJournalRepository
    ):
        """Test filtering journals by search text."""
        # Create journals with different content
        journal1 = create_test_journal(
            title="Python Programming",
            content="Learning about Python decorators and generators",
        )
        journal2 = create_test_journal(
            title="JavaScript Notes",
            content="Understanding async/await in JavaScript",
        )
        journal3 = create_test_journal(
            title="Database Design",
            content="Python SQLAlchemy ORM patterns",
        )

        await journal_repository.save(journal1)
        await journal_repository.save(journal2)
        await journal_repository.save(journal3)

        # Search for "Python"
        filtered = await journal_repository.get_all("test-user-123", search="Python")

        assert len(filtered) == 2
        titles = {j.title for j in filtered}
        assert "Python Programming" in titles
        assert "Database Design" in titles  # Contains "Python" in content

    async def test_combined_filters(
        self,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """Test combining multiple filters (AND logic)."""
        now = datetime.now(UTC)

        # Create a contact
        await async_connection.execute(
            text("""
            INSERT INTO contacts (id, first_name, last_name)
            VALUES (:id, :first_name, :last_name)
            """),
            {"id": 1, "first_name": "John", "last_name": "Doe"},
        )

        # Create journals
        journal1 = create_test_journal(
            title="Meeting with John",
            content="Discussed project timeline",
            start=now,
            end=now + timedelta(hours=1),
        )
        saved1 = await journal_repository.save(journal1)

        journal2 = create_test_journal(
            title="Old meeting with John",
            content="Discussed initial ideas",
            start=now - timedelta(days=10),
            end=now - timedelta(days=10, hours=-1),
        )
        saved2 = await journal_repository.save(journal2)

        # Link both to contact
        await async_connection.execute(
            text("""
            INSERT INTO journal_contact_relationships (journal_id, contact_id, relationship_type)
            VALUES (:journal_id, :contact_id, :relationship_type)
            """),
            {
                "journal_id": saved1.id,
                "contact_id": 1,
                "relationship_type": "PARTICIPANT",
            },
        )
        await async_connection.execute(
            text("""
            INSERT INTO journal_contact_relationships (journal_id, contact_id, relationship_type)
            VALUES (:journal_id, :contact_id, :relationship_type)
            """),
            {
                "journal_id": saved2.id,
                "contact_id": 1,
                "relationship_type": "PARTICIPANT",
            },
        )

        # Filter by contact AND date range AND search
        yesterday = now - timedelta(days=1)
        tomorrow = now + timedelta(days=1)
        filtered = await journal_repository.get_all(
            "test-user-123",
            contact_id="1",
            start_date=yesterday.isoformat(),
            end_date=tomorrow.isoformat(),
            search="project",
        )

        # Should only return journal1 (recent, with John, contains "project")
        assert len(filtered) == 1
        assert filtered[0].title == "Meeting with John"

    async def test_combined_filters_with_note_type(
        self,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """Test combining date + type=note + contact filters (reproduces E2E test failure)."""
        # Create a contact
        await async_connection.execute(
            text("""
            INSERT INTO contacts (id, first_name, last_name)
            VALUES (:id, :first_name, :last_name)
            """),
            {"id": 100, "first_name": "Charlie", "last_name": "Brown"},
        )

        # Create a NOTE journal (no type-specific data) with contact in February
        feb_note = create_test_journal(
            title="February Note with Charlie",
            content="This matches all filters",
            start=datetime(2026, 2, 10, 9, 0, 0, tzinfo=UTC),
            end=datetime(2026, 2, 10, 17, 0, 0, tzinfo=UTC),
        )
        saved_feb_note = await journal_repository.save(feb_note)

        # Link to contact
        await async_connection.execute(
            text("""
            INSERT INTO journal_contact_relationships (journal_id, contact_id, relationship_type)
            VALUES (:journal_id, :contact_id, :relationship_type)
            """),
            {
                "journal_id": saved_feb_note.id,
                "contact_id": 100,
                "relationship_type": "PARTICIPANT",
            },
        )

        # Create a calendar for EVENT journals
        cal_result = await async_connection.execute(
            text("""
            INSERT INTO calendars (user_id, name, color)
            VALUES (:user_id, :name, :color)
            RETURNING id
            """),
            {"user_id": "test-user-123", "name": "Test Calendar", "color": "#FF0000"},
        )
        cal_row = cal_result.fetchone()
        assert cal_row is not None
        cal_id = cal_row[0]

        # Create an EVENT journal with contact in February (should be filtered out by type)
        feb_event = create_test_journal(
            title="February Event with Charlie",
            content="Wrong type",
            start=datetime(2026, 2, 11, 9, 0, 0, tzinfo=UTC),
            end=datetime(2026, 2, 11, 17, 0, 0, tzinfo=UTC),
        )
        saved_feb_event = await journal_repository.save(feb_event)

        # Add calendar info to make it an EVENT
        await async_connection.execute(
            text("""
            INSERT INTO journal_calendar_info (journal_id, calendar_id, is_all_day)
            VALUES (:journal_id, :calendar_id, :is_all_day)
            """),
            {
                "journal_id": saved_feb_event.id,
                "calendar_id": cal_id,
                "is_all_day": False,
            },
        )

        # Link to contact
        await async_connection.execute(
            text("""
            INSERT INTO journal_contact_relationships (journal_id, contact_id, relationship_type)
            VALUES (:journal_id, :contact_id, :relationship_type)
            """),
            {
                "journal_id": saved_feb_event.id,
                "contact_id": 100,
                "relationship_type": "PARTICIPANT",
            },
        )

        # Create a NOTE journal with contact in January (should be filtered out by date)
        jan_note = create_test_journal(
            title="January Note with Charlie",
            content="Wrong date",
            start=datetime(2026, 1, 10, 9, 0, 0, tzinfo=UTC),
            end=datetime(2026, 1, 10, 17, 0, 0, tzinfo=UTC),
        )
        saved_jan_note = await journal_repository.save(jan_note)

        # Link to contact
        await async_connection.execute(
            text("""
            INSERT INTO journal_contact_relationships (journal_id, contact_id, relationship_type)
            VALUES (:journal_id, :contact_id, :relationship_type)
            """),
            {
                "journal_id": saved_jan_note.id,
                "contact_id": 100,
                "relationship_type": "PARTICIPANT",
            },
        )

        # Create a NOTE journal in February without contact (should be filtered out by contact)
        feb_note_solo = create_test_journal(
            title="February Note Solo",
            content="Wrong contact",
            start=datetime(2026, 2, 12, 9, 0, 0, tzinfo=UTC),
            end=datetime(2026, 2, 12, 17, 0, 0, tzinfo=UTC),
        )
        await journal_repository.save(feb_note_solo)

        # Filter by date range (Feb 1-28) + type (note) + contact (Charlie)
        filtered = await journal_repository.get_all(
            "test-user-123",
            journal_type="note",
            start_date="2026-02-01T00:00:00+00:00",
            end_date="2026-02-28T23:59:59+00:00",
            contact_id="100",
        )

        # Should only return the February Note with Charlie
        assert len(filtered) == 1, (
            f"Expected 1 journal, got {len(filtered)}: {[j.title for j in filtered]}"
        )
        assert filtered[0].title == "February Note with Charlie"
