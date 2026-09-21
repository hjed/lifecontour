"""Integration tests for JournalService with real database."""

import json
from datetime import datetime
from typing import Any, NamedTuple

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
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_service import JournalService
from app.core.tasks.adapters.sql.task_anchor_repository import (
    SqlTaskAnchorRepository,
)
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


OTHER_USER_ID = "other-user-456"


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
    def journal_service(
        self, journal_repo, event_publisher, clean_database: AsyncConnection
    ):
        """Create JournalService with real dependencies."""
        return JournalService(
            journal_repo=journal_repo,
            event_publisher=event_publisher,
            task_anchor_repo=SqlTaskAnchorRepository(clean_database),
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
    async def test_create_journal_rejects_another_users_parent(
        self, journal_service, journal_repo, clean_database: AsyncConnection
    ):
        """A parent owned by somebody else is refused, exactly as an absent one.

        Issue #1312: the parent was resolved without an owner predicate, so any
        id in the table was accepted and the caller's journal was written as a
        child of a stranger's — a child the owner can neither see nor delete,
        with nothing in the response to reveal the link had been made.
        """
        # Arrange - a journal that belongs to another user entirely
        theirs = await journal_repo.save(
            create_test_journal(title="Somebody Else's Trip", user_id=OTHER_USER_ID)
        )
        child = create_test_journal(title="Child Journal", parent_id=theirs.id)

        # Act & Assert - refused, and refused the same way a missing id is
        with pytest.raises(JournalNotFoundError) as foreign:
            await journal_service.create_journal(child, clean_database)

        absent = create_test_journal(title="Child Journal", parent_id=999_999)
        with pytest.raises(JournalNotFoundError) as missing:
            await journal_service.create_journal(absent, clean_database)

        # Both refusals are the same sentence about the id they were handed, so
        # nothing distinguishes a real journal that is not yours from one that
        # does not exist.
        assert foreign.value.message == f"Journal with ID {theirs.id} not found"
        assert missing.value.message == "Journal with ID 999999 not found"

        # Nothing was written
        written = await clean_database.execute(
            text("SELECT COUNT(*) FROM journals WHERE title = 'Child Journal'")
        )
        assert written.scalar_one() == 0

    @pytest.mark.asyncio
    async def test_update_journal_rejects_another_users_parent(
        self, journal_service, journal_repo, clean_database: AsyncConnection
    ):
        """Re-parenting an existing journal onto another user's is refused too."""
        # Arrange
        theirs = await journal_repo.save(
            create_test_journal(title="Somebody Else's Trip", user_id=OTHER_USER_ID)
        )
        mine = await journal_service.create_journal(
            create_test_journal(title="My Journal"), clean_database
        )

        mine.parent_id = theirs.id

        # Act & Assert
        with pytest.raises(JournalNotFoundError):
            await journal_service.update_journal(mine, clean_database)

        # The persisted journal is still a root
        stored = await clean_database.execute(
            text("SELECT parent_id FROM journals WHERE id = :id"), {"id": mine.id}
        )
        assert stored.scalar_one() is None

    @pytest.mark.asyncio
    async def test_update_journal_refuses_to_change_the_owner(
        self, journal_service, clean_database: AsyncConnection
    ):
        """An update may not move a journal to a different user.

        The UPDATE writes ``user_id`` straight from the entity it is handed and
        the change calculation does not diff it, so without this guard the row
        was silently re-owned and no history recorded it. The calendar sync
        reaches exactly that: it rebuilds the journal taking parent_id and
        order from the stored row but user_id from the event payload.
        """
        # Arrange
        mine = await journal_service.create_journal(
            create_test_journal(title="My Journal"), clean_database
        )
        impostor = create_test_journal(
            journal_id=mine.id, title="My Journal", user_id=OTHER_USER_ID
        )

        # Act & Assert
        with pytest.raises(JournalValidationError):
            await journal_service.update_journal(impostor, clean_database)

        stored = await clean_database.execute(
            text("SELECT user_id FROM journals WHERE id = :id"), {"id": mine.id}
        )
        assert stored.scalar_one() == "user123"

    @pytest.mark.asyncio
    async def test_update_journal_refuses_an_owner_change_before_reparenting(
        self, journal_service, journal_repo, clean_database: AsyncConnection
    ):
        """The owner guard runs first, so a re-parent cannot ride along with it.

        The entity is internally consistent — it claims the other user's
        ownership *and* points at that user's journal — which is what a parent
        lookup reading the owner off the argument would accept. The guard
        rejects the whole update before the hierarchy is consulted.
        """
        # Arrange
        theirs = await journal_repo.save(
            create_test_journal(title="Somebody Else's Trip", user_id=OTHER_USER_ID)
        )
        mine = await journal_service.create_journal(
            create_test_journal(title="My Journal"), clean_database
        )

        impostor = create_test_journal(
            journal_id=mine.id,
            title="My Journal",
            parent_id=theirs.id,
            user_id=OTHER_USER_ID,
        )

        # Act & Assert
        with pytest.raises(JournalValidationError):
            await journal_service.update_journal(impostor, clean_database)

        # Neither the parent nor the ownership moved
        stored = await clean_database.execute(
            text("SELECT parent_id, user_id FROM journals WHERE id = :id"),
            {"id": mine.id},
        )
        assert stored.one() == (None, "user123")

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
    def journal_service(
        self, journal_repo, event_publisher, clean_database: AsyncConnection
    ):
        """Create JournalService with real dependencies."""
        return JournalService(
            journal_repo=journal_repo,
            event_publisher=event_publisher,
            task_anchor_repo=SqlTaskAnchorRepository(clean_database),
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


_GOOGLE_CALENDAR_ID = "11111111-1111-5111-8111-111111111111"
_SNIPEIT_MAINTENANCE_CALENDAR_ID = "d7e0f8a1-4b2c-5e3d-9a6f-1c8b7d5e4f3a"


class _Link(NamedTuple):
    """A calendar a journal reached, and the event id it was given there.

    One value per test scenario, because what separates the scenarios is the
    calendar: who owns it, and whether the source is recorded on it at all.
    """

    calendar_id: str
    name: str
    integration_source: str | None
    external_event_id: str
    google_calendar_id: str | None = None


_GOOGLE = _Link(
    calendar_id=_GOOGLE_CALENDAR_ID,
    name="Work",
    integration_source="google",
    external_event_id="google-event-1",
    google_calendar_id="work@group.calendar.google.com",
)
# The Google worker creates and updates its own calendar rows, so one it wrote
# after the backfill carries no source: the id it syncs under stands in for one.
_GOOGLE_UNRECORDED = _GOOGLE._replace(integration_source=None)
_SNIPEIT = _Link(
    calendar_id=_SNIPEIT_MAINTENANCE_CALENDAR_ID,
    name="Snipe-IT Maintenance",
    integration_source="snipeit_maintenance",
    external_event_id="snipeit_maint:17",
)
# A calendar of the user's own: no integration syncs it, and no worker owns it.
_JUST_MINE = _Link(
    calendar_id=_GOOGLE_CALENDAR_ID,
    name="Just mine",
    integration_source=None,
    external_event_id="local-only",
)


def _entry(link: _Link) -> dict[str, Any]:
    """The identifier a deletion carries for ``link``."""
    return {
        "external_event_id": link.external_event_id,
        "calendar_id": link.calendar_id,
        "google_calendar_id": link.google_calendar_id,
    }


async def _a_journal_reaching(
    journal_service: JournalService,
    connection: AsyncConnection,
    *links: _Link,
) -> int:
    """A journal linked to each calendar, as the outbox processor leaves it."""
    journal = await journal_service.create_journal(create_test_journal(), connection)
    assert journal.id is not None
    for link in links:
        await connection.execute(
            text("""
                INSERT INTO calendars
                    (id, user_id, name, color, google_calendar_id,
                     integration_source)
                VALUES (:id, 'user123', :name, '#808080', :google_calendar_id,
                        :source)
            """),
            {
                "id": link.calendar_id,
                "name": link.name,
                "google_calendar_id": link.google_calendar_id,
                "source": link.integration_source,
            },
        )
        await connection.execute(
            text("""
                INSERT INTO journal_external_event_links
                    (journal_id, calendar_id, external_event_id,
                     sync_capability, sync_status)
                VALUES (:journal_id, :calendar_id, :external_event_id,
                        'bidirectional', 'synced')
            """),
            {
                "journal_id": journal.id,
                "calendar_id": link.calendar_id,
                "external_event_id": link.external_event_id,
            },
        )
    return journal.id


async def _identifiers_of_deleting(
    journal_service: JournalService,
    connection: AsyncConnection,
    journal_id: int,
) -> dict[str, Any]:
    """Delete the journal and read the identifiers its event carried."""
    await journal_service.delete_journal(journal_id, connection)
    row = (
        await connection.execute(
            text("""
                SELECT event_data FROM outbox_events
                WHERE event_type = 'JournalDeleted'
                  AND aggregate_id = :journal_id
            """),
            {"journal_id": journal_id},
        )
    ).one()
    event_data = row.event_data
    if isinstance(event_data, str):
        event_data = json.loads(event_data)
    identifiers: dict[str, Any] = event_data["external_identifiers"]
    return identifiers


@pytest.mark.integration
class TestDeletionIdentifiersAreFiledBySource:
    """``JournalDeleted`` carries each system's identifiers under its own key.

    A worker cleaning up after a deleted journal can only find what it put in
    its own system if the event says whose each identifier is. Filing them all
    under ``"google"`` also handed the Google worker Snipe-IT identifiers, which
    it tried to delete from a Google calendar.
    """

    @pytest.fixture
    def journal_repo(self, clean_database: AsyncConnection):
        return SqlJournalRepository(clean_database)

    @pytest.fixture
    def journal_service(self, journal_repo, clean_database: AsyncConnection):
        return JournalService(
            journal_repo=journal_repo,
            event_publisher=OutboxEventPublisher(clean_database),
            task_anchor_repo=SqlTaskAnchorRepository(clean_database),
        )

    @pytest.mark.asyncio
    async def test_each_source_gets_its_own_key(
        self, journal_service, clean_database: AsyncConnection
    ):
        """One journal in two systems: each worker finds only its own identifier."""
        journal_id = await _a_journal_reaching(
            journal_service, clean_database, _GOOGLE, _SNIPEIT
        )

        identifiers = await _identifiers_of_deleting(
            journal_service, clean_database, journal_id
        )

        assert identifiers == {
            "google": [_entry(_GOOGLE)],
            "snipeit_maintenance": [_entry(_SNIPEIT)],
        }

    @pytest.mark.asyncio
    async def test_a_snipeit_identifier_is_not_filed_under_google(
        self, journal_service, clean_database: AsyncConnection
    ):
        """The Google worker deletes what this key holds, so nothing else may be in it.

        It took an entry with no ``google_calendar_id`` to mean the user's
        primary calendar, so a Snipe-IT identifier became a delete issued
        against Google for a record Google never had.
        """
        journal_id = await _a_journal_reaching(
            journal_service, clean_database, _SNIPEIT
        )

        identifiers = await _identifiers_of_deleting(
            journal_service, clean_database, journal_id
        )

        assert "google" not in identifiers

    @pytest.mark.asyncio
    async def test_a_calendar_with_no_source_recorded_is_google(
        self, journal_service, clean_database: AsyncConnection
    ):
        """Google's own calendars are the ones it names, whatever the column says."""
        journal_id = await _a_journal_reaching(
            journal_service, clean_database, _GOOGLE_UNRECORDED
        )

        identifiers = await _identifiers_of_deleting(
            journal_service, clean_database, journal_id
        )

        assert list(identifiers) == ["google"]

    @pytest.mark.asyncio
    async def test_a_link_no_system_claims_is_left_out(
        self, journal_service, clean_database: AsyncConnection
    ):
        """A calendar of the user's own belongs to no worker, so nothing may act on it."""
        journal_id = await _a_journal_reaching(
            journal_service, clean_database, _JUST_MINE
        )

        assert (
            await _identifiers_of_deleting(journal_service, clean_database, journal_id)
            == {}
        )
