"""Integration tests for SqlJournalRepository."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from core_shared.models.journals import EventDateRange, Journal, JournalNotFoundError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from tests.integration.statement_recorder import recorded_statements


@pytest_asyncio.fixture
async def journal_repository(
    async_connection: AsyncConnection,
) -> SqlJournalRepository:
    """Create a journal repository for testing."""
    return SqlJournalRepository(async_connection)


async def _insert_tag(
    connection: AsyncConnection, name: str, parent_id: object | None = None
) -> object:
    """Insert a journal tag and return its id."""
    result = await connection.execute(
        text("""
        INSERT INTO journal_tags (name, color, parent_id)
        VALUES (:name, '#FF0000', :parent_id)
        RETURNING id
        """),
        {"name": name, "parent_id": parent_id},
    )
    row = result.fetchone()
    assert row is not None
    return row[0]


async def _assign_tag(
    connection: AsyncConnection, journal_id: int | None, tag_id: object
) -> None:
    """Assign a journal tag to a journal."""
    await connection.execute(
        text("""
        INSERT INTO journal_tag_assignments (journal_id, tag_id)
        VALUES (:journal_id, :tag_id)
        """),
        {"journal_id": journal_id, "tag_id": tag_id},
    )


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
class TestJournalRepositoryFindByIdForUser:
    """The owner-scoped read, which is where ownership is enforced (#1267)."""

    OWNER = "owner"
    STRANGER = "somebody-else"

    async def test_returns_the_journal_to_its_owner(
        self, journal_repository: SqlJournalRepository
    ):
        saved = await journal_repository.save(create_test_journal(user_id=self.OWNER))

        found = await journal_repository.find_by_id_for_user(saved.id, self.OWNER)  # type: ignore[arg-type]

        assert found is not None
        assert found.id == saved.id

    async def test_another_users_journal_is_absent_not_forbidden(
        self, journal_repository: SqlJournalRepository
    ):
        """Absent, not refused: the caller never holds the row to leak it.

        Returning ``None`` rather than raising is what lets every caller answer
        404 without having to decide between "missing" and "not yours" — the
        two are the same answer by design.
        """
        saved = await journal_repository.save(create_test_journal(user_id=self.OWNER))

        found = await journal_repository.find_by_id_for_user(saved.id, self.STRANGER)  # type: ignore[arg-type]

        assert found is None

    async def test_missing_journal_is_none(
        self, journal_repository: SqlJournalRepository
    ):
        assert await journal_repository.find_by_id_for_user(99999, self.OWNER) is None


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

        # Filter by tag_ids
        filtered = await journal_repository.get_all(
            "test-user-123", tag_ids=[str(tag1_id)]
        )

        assert len(filtered) == 1
        assert filtered[0].title == "Work Journal"

    async def test_filter_by_multiple_tag_ids_returns_union(
        self,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """Multiple tag ids combine as a logical OR, matching contact filtering."""
        work_id, personal_id, other_id = [
            await _insert_tag(async_connection, name)
            for name in ("Work", "Personal", "Other")
        ]

        work_journal = await journal_repository.save(
            create_test_journal(title="Work Journal")
        )
        personal_journal = await journal_repository.save(
            create_test_journal(title="Personal Journal")
        )
        other_journal = await journal_repository.save(
            create_test_journal(title="Other Journal")
        )
        await _assign_tag(async_connection, work_journal.id, work_id)
        await _assign_tag(async_connection, personal_journal.id, personal_id)
        await _assign_tag(async_connection, other_journal.id, other_id)

        filtered = await journal_repository.get_all(
            "test-user-123", tag_ids=[str(work_id), str(personal_id)]
        )

        assert {journal.title for journal in filtered} == {
            "Work Journal",
            "Personal Journal",
        }

    async def test_journal_matching_multiple_tags_returned_once(
        self,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """A journal carrying both filter tags is not duplicated by the JOIN."""
        work_id = await _insert_tag(async_connection, "Work")
        personal_id = await _insert_tag(async_connection, "Personal")

        journal = await journal_repository.save(create_test_journal(title="Both Tags"))
        await _assign_tag(async_connection, journal.id, work_id)
        await _assign_tag(async_connection, journal.id, personal_id)

        tag_ids = [str(work_id), str(personal_id)]
        filtered = await journal_repository.get_all("test-user-123", tag_ids=tag_ids)
        count = await journal_repository.count_all("test-user-123", tag_ids=tag_ids)

        assert len(filtered) == 1
        assert count == 1

    async def test_tag_filter_ands_with_date_range(
        self,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """Tag filtering keeps AND semantics against the other filters."""
        work_id = await _insert_tag(async_connection, "Work")
        now = datetime.now(UTC)

        in_range = await journal_repository.save(
            create_test_journal(title="In Range", start=now, end=now)
        )
        out_of_range = await journal_repository.save(
            create_test_journal(
                title="Out Of Range",
                start=now - timedelta(days=30),
                end=now - timedelta(days=30),
            )
        )
        await _assign_tag(async_connection, in_range.id, work_id)
        await _assign_tag(async_connection, out_of_range.id, work_id)

        filtered = await journal_repository.get_all(
            "test-user-123",
            tag_ids=[str(work_id)],
            start_date=(now - timedelta(days=1)).date().isoformat(),
            end_date=(now + timedelta(days=1)).date().isoformat(),
        )

        assert [journal.title for journal in filtered] == ["In Range"]

    async def test_empty_tag_ids_list_does_not_filter(
        self,
        journal_repository: SqlJournalRepository,
    ):
        """An empty list means "no tag filter", not "match nothing"."""
        await journal_repository.save(create_test_journal(title="Untagged"))

        filtered = await journal_repository.get_all("test-user-123", tag_ids=[])

        assert [journal.title for journal in filtered] == ["Untagged"]

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


@pytest.mark.integration
class TestJournalRepositoryFindIdsByFilters:
    """``find_ids_by_filters`` resolves the list filters down to bare ids.

    MCP ``search_journals`` uses it to intersect the relational filters with a
    MeiliSearch full-text query, so the ids it returns must agree exactly with
    the rows ``get_all`` returns for the same filters.
    """

    async def test_date_window_bounds_the_ids(
        self, journal_repository: SqlJournalRepository
    ):
        """Only journals overlapping the window are returned."""
        inside = await journal_repository.save(
            create_test_journal(
                title="Inside",
                start=datetime(2026, 3, 10, 9, 0, tzinfo=UTC),
                end=datetime(2026, 3, 10, 10, 0, tzinfo=UTC),
            )
        )
        before = await journal_repository.save(
            create_test_journal(
                title="Before",
                start=datetime(2026, 2, 1, 9, 0, tzinfo=UTC),
                end=datetime(2026, 2, 1, 10, 0, tzinfo=UTC),
            )
        )
        after = await journal_repository.save(
            create_test_journal(
                title="After",
                start=datetime(2026, 4, 1, 9, 0, tzinfo=UTC),
                end=datetime(2026, 4, 1, 10, 0, tzinfo=UTC),
            )
        )

        ids = await journal_repository.find_ids_by_filters(
            "test-user-123",
            start_date="2026-03-01T00:00:00+00:00",
            end_date="2026-03-31T23:59:59+00:00",
        )

        assert ids == {inside.id}
        assert before.id not in ids
        assert after.id not in ids

    async def test_agrees_with_get_all_for_combined_filters(
        self,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """The id set matches the rows ``get_all`` returns for the same filters."""
        await async_connection.execute(
            text("""
            INSERT INTO contacts (id, first_name, last_name)
            VALUES (:id, :first_name, :last_name)
            """),
            {"id": 501, "first_name": "Dana", "last_name": "Scully"},
        )
        matching = await journal_repository.save(
            create_test_journal(
                title="Project sync with Dana",
                content="Talked about the project",
                start=datetime(2026, 3, 10, 9, 0, tzinfo=UTC),
                end=datetime(2026, 3, 10, 10, 0, tzinfo=UTC),
            )
        )
        unlinked = await journal_repository.save(
            create_test_journal(
                title="Project sync alone",
                content="Talked about the project",
                start=datetime(2026, 3, 11, 9, 0, tzinfo=UTC),
                end=datetime(2026, 3, 11, 10, 0, tzinfo=UTC),
            )
        )
        await async_connection.execute(
            text("""
            INSERT INTO journal_contact_relationships (
                journal_id, contact_id, relationship_type
            )
            VALUES (:journal_id, :contact_id, 'PARTICIPANT')
            """),
            {"journal_id": matching.id, "contact_id": 501},
        )

        ids = await journal_repository.find_ids_by_filters(
            "test-user-123",
            contact_id="501",
            start_date="2026-03-01T00:00:00+00:00",
            end_date="2026-03-31T23:59:59+00:00",
            search="project",
        )
        rows = await journal_repository.get_all(
            "test-user-123",
            limit=100,
            contact_id="501",
            start_date="2026-03-01T00:00:00+00:00",
            end_date="2026-03-31T23:59:59+00:00",
            search="project",
        )

        assert ids == {matching.id}
        assert ids == {journal.id for journal in rows}
        assert unlinked.id not in ids

    async def test_tag_filter_selects_tagged_journals(
        self,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """A tag id narrows the result to journals carrying that tag."""
        tag_id = await _insert_tag(async_connection, "find-ids-hiking")
        tagged = await journal_repository.save(create_test_journal(title="Tagged"))
        untagged = await journal_repository.save(create_test_journal(title="Untagged"))
        await _assign_tag(async_connection, tagged.id, tag_id)

        ids = await journal_repository.find_ids_by_filters(
            "test-user-123", tag_ids=[str(tag_id)]
        )

        assert ids == {tagged.id}
        assert untagged.id not in ids

    async def test_parent_filter_selects_children(
        self, journal_repository: SqlJournalRepository
    ):
        """``parent_id`` returns only that journal's direct children."""
        parent = await journal_repository.save(create_test_journal(title="Trip"))
        child = await journal_repository.save(
            create_test_journal(title="Day one", parent_id=parent.id)
        )
        unrelated = await journal_repository.save(create_test_journal(title="Other"))

        ids = await journal_repository.find_ids_by_filters(
            "test-user-123", parent_id=parent.id
        )

        assert ids == {child.id}
        assert unrelated.id not in ids

    async def test_another_users_journals_are_never_returned(
        self, journal_repository: SqlJournalRepository
    ):
        """The id set is scoped to the acting user."""
        mine = await journal_repository.save(
            create_test_journal(user_id="owner-user", title="Mine")
        )
        theirs = await journal_repository.save(
            create_test_journal(user_id="other-user", title="Theirs")
        )

        ids = await journal_repository.find_ids_by_filters("owner-user")

        assert mine.id in ids
        assert theirs.id not in ids

    async def test_journal_ids_intersects_rather_than_widens(
        self, journal_repository: SqlJournalRepository
    ):
        """``journal_ids`` is an AND, and an empty candidate list matches nothing."""
        first = await journal_repository.save(create_test_journal(title="First"))
        second = await journal_repository.save(create_test_journal(title="Second"))

        assert first.id is not None
        intersected = await journal_repository.find_ids_by_filters(
            "test-user-123", journal_ids=[first.id]
        )
        assert intersected == {first.id}
        assert second.id not in intersected

        assert (
            await journal_repository.find_ids_by_filters(
                "test-user-123", journal_ids=[]
            )
            == set()
        )

    async def test_type_filter_is_applied(
        self,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """A journal type narrows the ids the same way it narrows ``get_all``."""
        typed = await journal_repository.save(create_test_journal(title="Mood day"))
        untyped = await journal_repository.save(create_test_journal(title="Plain note"))
        await async_connection.execute(
            text("""
            INSERT INTO journal_mood_data (journal_id, mood_value)
            VALUES (:journal_id, 4)
            """),
            {"journal_id": typed.id},
        )

        ids = await journal_repository.find_ids_by_filters(
            "test-user-123", journal_type="MOOD_RATING"
        )

        assert ids == {typed.id}
        assert untyped.id not in ids


def saved_id(journal: Journal) -> int:
    """A saved journal's id, narrowed once so the lock tests can pass lists of them."""
    assert journal.id is not None
    return journal.id


@pytest.mark.integration
class TestJournalRepositoryFindAndLockByIdsForUser:
    """The ordered locking read a retarget takes before it locks its task row.

    ``TaskService.retarget_due_journal`` and a journal merge touch the same two
    kinds of row, and until ITER18-002 Phase 6 they took them in opposite orders.
    This read is what puts the retarget's journal locks in front of its task
    lock, in the same ascending-id order ``SqlTaskAnchorRepository._lock_journals``
    uses — so the two queue instead of deadlocking.

    Its owner scoping is the ordinary journal-domain contract, and the tests for
    it read the same as ``find_by_ids_for_user``'s. What is particular to this
    method is the last three: the ids are locked one statement at a time in
    ascending order, and the mode is ``FOR KEY SHARE`` — strong enough to queue
    behind a merge or a delete, weak enough that editing a journal is never
    blocked by somebody retargeting a task into it.
    """

    OWNER = "lock-owner"
    STRANGER = "lock-stranger"

    async def test_returns_the_users_journals(
        self, journal_repository: SqlJournalRepository
    ):
        first = await journal_repository.save(create_test_journal(user_id=self.OWNER))
        second = await journal_repository.save(create_test_journal(user_id=self.OWNER))

        found = await journal_repository.find_and_lock_by_ids_for_user(
            self.OWNER, [saved_id(first), saved_id(second)]
        )

        assert {journal.id for journal in found} == {first.id, second.id}

    async def test_another_users_journal_is_absent_not_forbidden(
        self, journal_repository: SqlJournalRepository
    ):
        """Ownership is enforced by the query, so the caller never holds the row.

        This is what lets the retarget answer ``TaskAnchorJournalNotFoundError``
        without deciding between "missing" and "not yours" — and what stops it
        taking a lock on a journal it was never allowed to see.
        """
        mine = await journal_repository.save(create_test_journal(user_id=self.OWNER))
        theirs = await journal_repository.save(
            create_test_journal(user_id=self.STRANGER)
        )

        found = await journal_repository.find_and_lock_by_ids_for_user(
            self.OWNER, [saved_id(mine), saved_id(theirs)]
        )

        assert [journal.id for journal in found] == [mine.id]

    async def test_a_missing_id_is_simply_absent(
        self, journal_repository: SqlJournalRepository
    ):
        mine = await journal_repository.save(create_test_journal(user_id=self.OWNER))

        found = await journal_repository.find_and_lock_by_ids_for_user(
            self.OWNER, [saved_id(mine), 999999]
        )

        assert [journal.id for journal in found] == [mine.id]

    async def test_no_ids_costs_no_statement(
        self,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """A retarget never asks for nothing, but a lock loop that did would round trip."""
        with recorded_statements(async_connection) as statements:
            found = await journal_repository.find_and_lock_by_ids_for_user(
                self.OWNER, []
            )

        assert found == []
        assert statements == []

    async def test_one_statement_per_id_in_ascending_order(
        self,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """The ordering claim is about statements, so the statements are counted.

        ``FOR KEY SHARE`` does not promise to lock in the order a query returns
        its rows, so one ordered statement over three ids would leave the order
        up to the plan — the reason ``_lock_journals`` issues one per id too. The
        ids are handed over out of order here, and the locks still have to be
        taken low to high.
        """
        journals = [
            await journal_repository.save(create_test_journal(user_id=self.OWNER))
            for _ in range(3)
        ]
        ids = sorted(saved_id(journal) for journal in journals)

        with recorded_statements(async_connection) as statements:
            await journal_repository.find_and_lock_by_ids_for_user(
                self.OWNER, [ids[2], ids[0], ids[1]]
            )

        assert len(statements) == 3
        assert all("FOR KEY SHARE" in statement for statement in statements)

    async def test_the_ids_are_locked_low_to_high(
        self,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """Asserted on the rows each statement returned, not on the SQL text.

        The statements are identical apart from their bound parameter, which the
        recorder does not capture, so the order is read off the journals the
        method hands back — it returns them in the order it locked them.
        """
        journals = [
            await journal_repository.save(create_test_journal(user_id=self.OWNER))
            for _ in range(3)
        ]
        ids = sorted(saved_id(journal) for journal in journals)

        found = await journal_repository.find_and_lock_by_ids_for_user(
            self.OWNER, [ids[2], ids[0], ids[1]]
        )

        assert [journal.id for journal in found] == ids


@pytest.mark.integration
class TestTheJournalLockHoldsAgainstAnotherConnection:
    """What ``FOR KEY SHARE`` blocks, and what it deliberately does not.

    The mode is the whole design of the fix. It has to conflict with the merge's
    ``FOR UPDATE`` — and with the ``DELETE`` that ends a merge — or the two
    operations would not queue and the lock ordering would guarantee nothing. It
    must **not** conflict with an ordinary journal ``UPDATE``, or retargeting a
    task into a journal would start blocking somebody editing that journal's
    title, which is a cost the deadlock fix has no right to impose. It is also
    exactly the lock the intermediate-link insert's and the anchor update's
    foreign keys take later, so nothing new is being held — only held earlier.

    Two real connections are needed to see any of that, which the savepoint
    fixture cannot give: its outer transaction is invisible to everyone else.
    So these rows are committed for real under a one-off user id and deleted in
    a ``finally``.
    """

    @staticmethod
    async def _committed_journal(async_engine: AsyncEngine) -> tuple[str, int]:
        user_id = f"lock-race-{uuid4()}"
        async with async_engine.connect() as setup:
            saved = await SqlJournalRepository(setup).save(
                create_test_journal(user_id=user_id, title="Contended")
            )
            await setup.commit()
        assert saved.id is not None
        return user_id, saved.id

    @staticmethod
    async def _cleanup(async_engine: AsyncEngine, user_id: str) -> None:
        async with async_engine.connect() as cleanup:
            await cleanup.execute(
                text("DELETE FROM journals WHERE user_id = :user_id"),
                {"user_id": user_id},
            )
            await cleanup.commit()

    async def test_a_for_update_waits_for_the_lock_holder(
        self, async_engine: AsyncEngine
    ):
        """A merge's lock queues behind a retarget's, rather than deadlocking with it.

        The waiter is given a ``lock_timeout`` so a regression fails in a second
        instead of hanging the suite; the assertion is that it times out while
        the holder is inside its transaction and succeeds once that commits.
        """
        user_id, journal_id = await self._committed_journal(async_engine)
        try:
            async with (
                async_engine.connect() as holder,
                async_engine.connect() as waiter,
            ):
                await holder.begin()
                await SqlJournalRepository(holder).find_and_lock_by_ids_for_user(
                    user_id, [journal_id]
                )

                await waiter.execute(text("SET lock_timeout = '1s'"))
                with pytest.raises(DBAPIError):
                    await waiter.execute(
                        text("SELECT id FROM journals WHERE id = :id FOR UPDATE"),
                        {"id": journal_id},
                    )
                await waiter.rollback()

                await holder.commit()

                result = await waiter.execute(
                    text("SELECT id FROM journals WHERE id = :id FOR UPDATE"),
                    {"id": journal_id},
                )
                assert result.scalar_one() == journal_id
                await waiter.rollback()
        finally:
            await self._cleanup(async_engine, user_id)

    async def test_a_delete_waits_for_the_lock_holder(self, async_engine: AsyncEngine):
        """The other half of the claim, and the half a merge actually ends with.

        ``repoint_journal_links`` takes ``FOR UPDATE`` and the merge then deletes
        the absorbed journal; a `DELETE` takes the same strength, so the lock has
        to hold against it too or a journal could vanish out from under a
        retarget between its check and its write.
        """
        user_id, journal_id = await self._committed_journal(async_engine)
        try:
            async with (
                async_engine.connect() as holder,
                async_engine.connect() as deleter,
            ):
                await holder.begin()
                await SqlJournalRepository(holder).find_and_lock_by_ids_for_user(
                    user_id, [journal_id]
                )

                await deleter.execute(text("SET lock_timeout = '1s'"))
                with pytest.raises(DBAPIError):
                    await deleter.execute(
                        text("DELETE FROM journals WHERE id = :id"), {"id": journal_id}
                    )
                await deleter.rollback()

                await holder.commit()
        finally:
            await self._cleanup(async_engine, user_id)

    async def test_an_ordinary_update_is_not_blocked(self, async_engine: AsyncEngine):
        """``FOR KEY SHARE``, not ``FOR UPDATE``: editing a journal stays free.

        A retarget holds these locks for the rest of its unit of work, so a
        stronger mode would make every journal edit wait behind an unrelated
        task move. It would also make the future-dated rule's documented window
        narrower by accident — the specification wants a task whose due journal
        later moves into the past to be *lapsed*, not refused.
        """
        user_id, journal_id = await self._committed_journal(async_engine)
        try:
            async with (
                async_engine.connect() as holder,
                async_engine.connect() as editor,
            ):
                await holder.begin()
                await SqlJournalRepository(holder).find_and_lock_by_ids_for_user(
                    user_id, [journal_id]
                )

                await editor.execute(text("SET lock_timeout = '1s'"))
                await editor.execute(
                    text("UPDATE journals SET title = :title WHERE id = :id"),
                    {"title": "Edited while locked", "id": journal_id},
                )
                await editor.commit()

                await holder.commit()

            async with async_engine.connect() as check:
                result = await check.execute(
                    text("SELECT title FROM journals WHERE id = :id"),
                    {"id": journal_id},
                )
                assert result.scalar_one() == "Edited while locked"
        finally:
            await self._cleanup(async_engine, user_id)


@pytest.mark.integration
class TestJournalRepositoryFindOverlappingForUser:
    """The merge-candidate read: the user's other journals overlapping a range."""

    OWNER = "overlap-owner"
    STRANGER = "overlap-stranger"
    DAY = datetime(2025, 5, 10, tzinfo=UTC)

    async def _save(
        self,
        journal_repository: SqlJournalRepository,
        title: str,
        start_hour: int,
        end_hour: int,
        user_id: str = OWNER,
    ) -> Journal:
        return await journal_repository.save(
            create_test_journal(
                user_id=user_id,
                title=title,
                start=self.DAY + timedelta(hours=start_hour),
                end=self.DAY + timedelta(hours=end_hour),
            )
        )

    async def test_returns_the_users_other_overlapping_journals_by_start(
        self, journal_repository: SqlJournalRepository
    ) -> None:
        target = await self._save(journal_repository, "Target", 10, 12)
        later = await self._save(journal_repository, "Runs past the end", 11, 13)
        touching = await self._save(journal_repository, "Ends at the start", 8, 10)
        await self._save(journal_repository, "Before", 8, 9)
        await self._save(journal_repository, "Stranger's", 10, 12, self.STRANGER)

        found = await journal_repository.find_overlapping_for_user(
            self.OWNER,
            exclude_journal_id=saved_id(target),
            date_range=target.event_date_range,
            limit=10,
        )

        assert [journal.id for journal in found] == [touching.id, later.id]
        assert found[1].title == "Runs past the end"
        assert found[1].content == "Test content"

    async def test_limit_caps_the_candidates(
        self, journal_repository: SqlJournalRepository
    ) -> None:
        target = await self._save(journal_repository, "Target", 10, 12)
        first = await self._save(journal_repository, "First", 9, 11)
        await self._save(journal_repository, "Second", 11, 12)

        found = await journal_repository.find_overlapping_for_user(
            self.OWNER,
            exclude_journal_id=saved_id(target),
            date_range=target.event_date_range,
            limit=1,
        )

        assert [journal.id for journal in found] == [first.id]
