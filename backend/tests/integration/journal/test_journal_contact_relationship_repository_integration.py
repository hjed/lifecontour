"""Integration tests for JournalContactRelationshipRepository."""

import pytest

from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.journal.models.journal_contact_relationship import (
    JournalContactRelationship,
)
from app.core.journal.models.journal_relationship_types import (
    JournalContactRelationshipType,
)


@pytest.mark.integration
class TestJournalContactRelationshipRepositoryIntegration:
    """Integration tests for journal-contact relationship repository."""

    @pytest.fixture
    async def rel_repo(self, async_connection):
        """Create a relationship repository instance."""
        return SqlJournalContactRelationshipRepository(async_connection)

    @pytest.fixture
    async def sample_journal_and_contact(self, async_connection):
        """Create sample journal and contact for testing."""
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import text

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

        return journal_id, contact_id

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
