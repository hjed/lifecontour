"""Integration tests for JournalContactRelationshipRepository."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from core_shared.models.journals import (
    JournalContactRelationship,
    JournalContactRelationshipType,
)
from core_shared.models.journals.attendee_status import AttendeeStatus
from core_shared.models.journals.contact_event_role import ContactEventRole
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)


@pytest_asyncio.fixture
async def rel_repo(
    async_connection: AsyncConnection,
) -> SqlJournalContactRelationshipRepository:
    """Create a relationship repository instance."""
    return SqlJournalContactRelationshipRepository(async_connection)


@pytest_asyncio.fixture
async def sample_journal_and_contact(
    async_connection: AsyncConnection,
) -> tuple[int, int]:
    """Create sample journal and contact for testing."""
    # Create a journal
    journal_query = text(
        """
        INSERT INTO journals (user_id, title, content, event_date_range_start, event_date_range_end)
        VALUES (:user_id, :title, :content, :start, :end)
        RETURNING id
    """
    )
    now = datetime.now(UTC)
    journal_result = await async_connection.execute(
        journal_query,
        {
            "user_id": "test_user",
            "title": "Test Journal",
            "content": "Test content",
            "start": now,
            "end": now + timedelta(hours=1),
        },
    )
    journal_id = journal_result.scalar()
    assert journal_id is not None

    # Create a contact
    contact_query = text(
        """
        INSERT INTO contacts (first_name)
        VALUES (:first_name)
        RETURNING id
    """
    )
    contact_result = await async_connection.execute(
        contact_query, {"first_name": "Test Contact"}
    )
    contact_id = contact_result.scalar()
    assert contact_id is not None

    return journal_id, contact_id


@pytest.mark.integration
class TestJournalContactRelationshipRepositoryIntegration:
    """Integration tests for journal-contact relationship repository."""

    async def test_create_relationship(self, rel_repo, sample_journal_and_contact):
        """Test creating a relationship."""
        journal_id, contact_id = sample_journal_and_contact

        rel = JournalContactRelationship(
            journal_id=journal_id,
            contact_id=contact_id,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
        )
        created_rel = await rel_repo.create(rel)

        assert created_rel.journal_id == journal_id
        assert created_rel.contact_id == contact_id
        assert (
            created_rel.relationship_type == JournalContactRelationshipType.PARTICIPANT
        )
        assert created_rel.created_at is not None

    async def test_get_by_journal(self, rel_repo, sample_journal_and_contact):
        """Test getting relationships by journal."""
        journal_id, contact_id = sample_journal_and_contact

        rel = JournalContactRelationship(
            journal_id=journal_id,
            contact_id=contact_id,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
        )
        await rel_repo.create(rel)

        relationships = await rel_repo.get_by_journal(journal_id)
        assert len(relationships) == 1
        assert relationships[0].contact_id == contact_id

    async def test_get_by_contact(self, rel_repo, sample_journal_and_contact):
        """Test getting relationships by contact."""
        journal_id, contact_id = sample_journal_and_contact

        rel = JournalContactRelationship(
            journal_id=journal_id,
            contact_id=contact_id,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
        )
        await rel_repo.create(rel)

        relationships = await rel_repo.get_by_contact(contact_id)
        assert len(relationships) == 1
        assert relationships[0].journal_id == journal_id

    async def test_get_by_journal_and_type(self, rel_repo, sample_journal_and_contact):
        """Test getting relationships by journal and type."""
        journal_id, contact_id = sample_journal_and_contact

        # Create multiple relationships with different types
        rel1 = JournalContactRelationship(
            journal_id=journal_id,
            contact_id=contact_id,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
        )
        rel2 = JournalContactRelationship(
            journal_id=journal_id,
            contact_id=contact_id,
            relationship_type=JournalContactRelationshipType.INVITEE,
        )
        await rel_repo.create(rel1)
        await rel_repo.create(rel2)

        # Get only PARTICIPANT relationships
        participants = await rel_repo.get_by_journal_and_type(
            journal_id, JournalContactRelationshipType.PARTICIPANT
        )
        assert len(participants) == 1
        assert (
            participants[0].relationship_type
            == JournalContactRelationshipType.PARTICIPANT
        )

    async def test_delete_relationship(self, rel_repo, sample_journal_and_contact):
        """Test deleting a relationship."""
        journal_id, contact_id = sample_journal_and_contact

        rel = JournalContactRelationship(
            journal_id=journal_id,
            contact_id=contact_id,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
        )
        await rel_repo.create(rel)

        await rel_repo.delete(
            journal_id, contact_id, JournalContactRelationshipType.PARTICIPANT
        )

        relationships = await rel_repo.get_by_journal(journal_id)
        assert len(relationships) == 0

    async def test_multiple_relationship_types_same_contact(
        self, rel_repo, sample_journal_and_contact
    ):
        """Test same contact can have multiple relationship types."""
        journal_id, contact_id = sample_journal_and_contact

        rel1 = JournalContactRelationship(
            journal_id=journal_id,
            contact_id=contact_id,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
        )
        rel2 = JournalContactRelationship(
            journal_id=journal_id,
            contact_id=contact_id,
            relationship_type=JournalContactRelationshipType.MENTION,
        )
        await rel_repo.create(rel1)
        await rel_repo.create(rel2)

        relationships = await rel_repo.get_by_journal(journal_id)
        assert len(relationships) == 2
        types = [rel.relationship_type for rel in relationships]
        assert JournalContactRelationshipType.PARTICIPANT in types
        assert JournalContactRelationshipType.MENTION in types


@pytest.mark.integration
class TestJournalContactRelationshipStatusRole:
    """Integration tests for status and role fields on journal-contact relationships."""

    async def test_create_with_status(self, rel_repo, sample_journal_and_contact):
        """Test creating a PARTICIPANT relationship with status=ATTENDING."""
        journal_id, contact_id = sample_journal_and_contact

        rel = JournalContactRelationship(
            journal_id=journal_id,
            contact_id=contact_id,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
            status=AttendeeStatus.ATTENDING,
        )
        created = await rel_repo.create(rel)

        assert created.status == AttendeeStatus.ATTENDING
        assert created.role is None

    async def test_create_with_role(self, rel_repo, sample_journal_and_contact):
        """Test creating a PARTICIPANT relationship with role=ORGANISER."""
        journal_id, contact_id = sample_journal_and_contact

        rel = JournalContactRelationship(
            journal_id=journal_id,
            contact_id=contact_id,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
            role=ContactEventRole.ORGANISER,
        )
        created = await rel_repo.create(rel)

        assert created.role == ContactEventRole.ORGANISER
        assert created.status is None

    async def test_create_with_status_and_role(
        self, rel_repo, sample_journal_and_contact
    ):
        """Test creating a relationship with both status and role."""
        journal_id, contact_id = sample_journal_and_contact

        rel = JournalContactRelationship(
            journal_id=journal_id,
            contact_id=contact_id,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
            status=AttendeeStatus.MAYBE,
            role=ContactEventRole.FACILITATOR_HELPER,
        )
        created = await rel_repo.create(rel)

        assert created.status == AttendeeStatus.MAYBE
        assert created.role == ContactEventRole.FACILITATOR_HELPER

    async def test_create_without_status_role(
        self, rel_repo, sample_journal_and_contact
    ):
        """Test creating without status/role preserves backward compatibility."""
        journal_id, contact_id = sample_journal_and_contact

        rel = JournalContactRelationship(
            journal_id=journal_id,
            contact_id=contact_id,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
        )
        created = await rel_repo.create(rel)

        assert created.status is None
        assert created.role is None

    async def test_get_by_journal_returns_status_role(
        self, rel_repo, sample_journal_and_contact
    ):
        """Test get_by_journal returns status and role from the database."""
        journal_id, contact_id = sample_journal_and_contact

        rel = JournalContactRelationship(
            journal_id=journal_id,
            contact_id=contact_id,
            relationship_type=JournalContactRelationshipType.INVITEE,
            status=AttendeeStatus.DECLINED,
            role=ContactEventRole.ORGANISER,
        )
        await rel_repo.create(rel)

        relationships = await rel_repo.get_by_journal(journal_id)
        assert len(relationships) == 1
        assert relationships[0].status == AttendeeStatus.DECLINED
        assert relationships[0].role == ContactEventRole.ORGANISER

    async def test_get_by_contact_returns_status_role(
        self, rel_repo, sample_journal_and_contact
    ):
        """Test get_by_contact returns status and role from the database."""
        journal_id, contact_id = sample_journal_and_contact

        rel = JournalContactRelationship(
            journal_id=journal_id,
            contact_id=contact_id,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
            status=AttendeeStatus.NO_REPLY,
        )
        await rel_repo.create(rel)

        relationships = await rel_repo.get_by_contact(contact_id)
        assert len(relationships) == 1
        assert relationships[0].status == AttendeeStatus.NO_REPLY
        assert relationships[0].role is None

    async def test_check_constraint_rejects_invalid_status(
        self, rel_repo, sample_journal_and_contact
    ):
        """Test that the DB CHECK constraint rejects an invalid status value."""
        journal_id, contact_id = sample_journal_and_contact

        with pytest.raises(Exception):  # noqa: B017 - DB constraint error
            await rel_repo.conn.execute(
                text(
                    """
                    INSERT INTO journal_contact_relationships
                    (journal_id, contact_id, relationship_type, status)
                    VALUES (:journal_id, :contact_id, :rel_type, :status)
                """
                ),
                {
                    "journal_id": journal_id,
                    "contact_id": contact_id,
                    "rel_type": "PARTICIPANT",
                    "status": "INVALID_STATUS",
                },
            )

    async def test_check_constraint_rejects_invalid_role(
        self, rel_repo, sample_journal_and_contact
    ):
        """Test that the DB CHECK constraint rejects an invalid role value."""
        journal_id, contact_id = sample_journal_and_contact

        with pytest.raises(Exception):  # noqa: B017 - DB constraint error
            await rel_repo.conn.execute(
                text(
                    """
                    INSERT INTO journal_contact_relationships
                    (journal_id, contact_id, relationship_type, role)
                    VALUES (:journal_id, :contact_id, :rel_type, :role)
                """
                ),
                {
                    "journal_id": journal_id,
                    "contact_id": contact_id,
                    "rel_type": "PARTICIPANT",
                    "role": "INVALID_ROLE",
                },
            )
