"""Integration tests for the contact-merge re-point repository methods.

Covers ITER13-001 Phase 1: re-pointing contact-to-contact relationships and
journal links from a source contact onto a surviving contact, honouring the
constraint hotspots (self-loop drop, the two partial unique indexes, and the
``journal_contact_relationships`` composite PK).
"""

import pytest
import pytest_asyncio
from core_shared.models.contacts.entities import (
    Contact,
    ContactRelationship,
    RelationshipType,
)
from core_shared.models.journals import (
    JournalContactRelationship,
    JournalContactRelationshipType,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql import (
    SqlContactRelationshipRepository,
    SqlContactRepository,
)
from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from tests.integration.contact_seeding import TEST_USER_ID


@pytest_asyncio.fixture
async def contact_repo(async_connection: AsyncConnection) -> SqlContactRepository:
    """Create a contact repository for test setup."""
    return SqlContactRepository(async_connection)


@pytest_asyncio.fixture
async def relationship_repo(
    async_connection: AsyncConnection,
) -> SqlContactRelationshipRepository:
    """Create a contact relationship repository under test."""
    return SqlContactRelationshipRepository(async_connection)


@pytest_asyncio.fixture
async def journal_rel_repo(
    async_connection: AsyncConnection,
) -> SqlJournalContactRelationshipRepository:
    """Create a journal-contact relationship repository under test."""
    return SqlJournalContactRelationshipRepository(async_connection)


def _id(contact: Contact) -> int:
    assert contact.id is not None, "Contact must have an ID after save"
    return contact.id


async def _make_contact(contact_repo: SqlContactRepository, first_name: str) -> Contact:
    saved = await contact_repo.save(
        Contact(user_id=TEST_USER_ID, first_name=first_name)
    )
    assert saved.id is not None
    return saved


async def _make_journal(connection: AsyncConnection, title: str) -> int:
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    result = await connection.execute(
        text(
            """
            INSERT INTO journals
                (user_id, title, content, event_date_range_start, event_date_range_end)
            VALUES (:user_id, :title, :content, :start, :end)
            RETURNING id
            """
        ),
        {
            "user_id": "test_user",
            "title": title,
            "content": "content",
            "start": now,
            "end": now + timedelta(hours=1),
        },
    )
    journal_id = result.scalar()
    assert journal_id is not None
    return int(journal_id)


@pytest.mark.integration
class TestContactRelationshipRepointIntegration:
    """Integration tests for ``SqlContactRelationshipRepository.repoint_contact``."""

    @pytest.mark.asyncio
    async def test_repoint_dedupes_duplicate_contact_relationship(
        self,
        async_connection: AsyncConnection,
        contact_repo: SqlContactRepository,
        relationship_repo: SqlContactRelationshipRepository,
    ) -> None:
        """Duplicate relationships to the same target collapse to one."""
        survivor = await _make_contact(contact_repo, "Survivor")
        source = await _make_contact(contact_repo, "Source")
        other = await _make_contact(contact_repo, "Other")

        await relationship_repo.create(
            ContactRelationship(
                from_contact_id=_id(survivor),
                to_contact_id=_id(other),
                relationship_type=RelationshipType.FRIEND,
            )
        )
        await relationship_repo.create(
            ContactRelationship(
                from_contact_id=_id(source),
                to_contact_id=_id(other),
                relationship_type=RelationshipType.FRIEND,
            )
        )

        await relationship_repo.repoint_contact(
            _id(source), _id(survivor), async_connection
        )

        survivor_rels = await relationship_repo.get_relationships_from_contact(
            _id(survivor)
        )
        assert len(survivor_rels) == 1
        assert survivor_rels[0].to_contact_id == _id(other)
        assert survivor_rels[0].relationship_type == RelationshipType.FRIEND
        assert await relationship_repo.get_relationships_for_contact(_id(source)) == []

    @pytest.mark.asyncio
    async def test_repoint_drops_inter_contact_self_loops(
        self,
        async_connection: AsyncConnection,
        contact_repo: SqlContactRepository,
        relationship_repo: SqlContactRelationshipRepository,
    ) -> None:
        """Relationships directly between the two contacts are dropped, not self-looped."""
        survivor = await _make_contact(contact_repo, "Survivor")
        source = await _make_contact(contact_repo, "Source")

        # Both directions between the merged pair.
        await relationship_repo.create(
            ContactRelationship(
                from_contact_id=_id(source),
                to_contact_id=_id(survivor),
                relationship_type=RelationshipType.FRIEND,
            )
        )
        await relationship_repo.create(
            ContactRelationship(
                from_contact_id=_id(survivor),
                to_contact_id=_id(source),
                relationship_type=RelationshipType.COLLEAGUE,
            )
        )

        await relationship_repo.repoint_contact(
            _id(source), _id(survivor), async_connection
        )

        # No self-loop survives, and the source has no relationships left.
        assert (
            await relationship_repo.get_relationships_for_contact(_id(survivor)) == []
        )
        assert await relationship_repo.get_relationships_for_contact(_id(source)) == []

    @pytest.mark.asyncio
    async def test_repoint_to_user_relationships_dedupe_and_move(
        self,
        async_connection: AsyncConnection,
        contact_repo: SqlContactRepository,
        relationship_repo: SqlContactRelationshipRepository,
    ) -> None:
        """To-user relationships dedupe on the user-target index and otherwise move."""
        survivor = await _make_contact(contact_repo, "Survivor")
        source = await _make_contact(contact_repo, "Source")

        # Both have a PARENT-to-user relationship -> must dedupe to one.
        await relationship_repo.create(
            ContactRelationship(
                from_contact_id=_id(survivor),
                to_contact_id=None,
                relationship_type=RelationshipType.PARENT,
                to_user=True,
            )
        )
        await relationship_repo.create(
            ContactRelationship(
                from_contact_id=_id(source),
                to_contact_id=None,
                relationship_type=RelationshipType.PARENT,
                to_user=True,
            )
        )
        # Only the source has a CHILD-to-user relationship -> must move over.
        await relationship_repo.create(
            ContactRelationship(
                from_contact_id=_id(source),
                to_contact_id=None,
                relationship_type=RelationshipType.CHILD,
                to_user=True,
            )
        )

        await relationship_repo.repoint_contact(
            _id(source), _id(survivor), async_connection
        )

        survivor_rels = await relationship_repo.get_relationships_from_contact(
            _id(survivor)
        )
        to_user_types = sorted(
            r.relationship_type.value for r in survivor_rels if r.to_user
        )
        assert to_user_types == [
            RelationshipType.CHILD.value,
            RelationshipType.PARENT.value,
        ]
        assert await relationship_repo.get_relationships_for_contact(_id(source)) == []

    @pytest.mark.asyncio
    async def test_repoint_moves_both_directions(
        self,
        async_connection: AsyncConnection,
        contact_repo: SqlContactRepository,
        relationship_repo: SqlContactRelationshipRepository,
    ) -> None:
        """Re-point updates both the from-side and the to-side of relationships."""
        survivor = await _make_contact(contact_repo, "Survivor")
        source = await _make_contact(contact_repo, "Source")
        peer_a = await _make_contact(contact_repo, "PeerA")
        peer_b = await _make_contact(contact_repo, "PeerB")

        # source as 'from'
        await relationship_repo.create(
            ContactRelationship(
                from_contact_id=_id(source),
                to_contact_id=_id(peer_a),
                relationship_type=RelationshipType.FRIEND,
            )
        )
        # source as 'to'
        await relationship_repo.create(
            ContactRelationship(
                from_contact_id=_id(peer_b),
                to_contact_id=_id(source),
                relationship_type=RelationshipType.COLLEAGUE,
            )
        )

        await relationship_repo.repoint_contact(
            _id(source), _id(survivor), async_connection
        )

        from_rels = await relationship_repo.get_relationships_from_contact(
            _id(survivor)
        )
        to_rels = await relationship_repo.get_relationships_to_contact(_id(survivor))
        assert {(r.to_contact_id, r.relationship_type.value) for r in from_rels} == {
            (_id(peer_a), RelationshipType.FRIEND.value)
        }
        assert {(r.from_contact_id, r.relationship_type.value) for r in to_rels} == {
            (_id(peer_b), RelationshipType.COLLEAGUE.value)
        }
        assert await relationship_repo.get_relationships_for_contact(_id(source)) == []

    @pytest.mark.asyncio
    async def test_repoint_moves_non_colliding_relationship(
        self,
        async_connection: AsyncConnection,
        contact_repo: SqlContactRepository,
        relationship_repo: SqlContactRelationshipRepository,
    ) -> None:
        """A relationship the survivor lacks simply moves across."""
        survivor = await _make_contact(contact_repo, "Survivor")
        source = await _make_contact(contact_repo, "Source")
        other = await _make_contact(contact_repo, "Other")

        await relationship_repo.create(
            ContactRelationship(
                from_contact_id=_id(source),
                to_contact_id=_id(other),
                relationship_type=RelationshipType.FAMILY,
            )
        )

        await relationship_repo.repoint_contact(
            _id(source), _id(survivor), async_connection
        )

        survivor_rels = await relationship_repo.get_relationships_from_contact(
            _id(survivor)
        )
        assert len(survivor_rels) == 1
        assert survivor_rels[0].to_contact_id == _id(other)
        assert survivor_rels[0].relationship_type == RelationshipType.FAMILY
        assert await relationship_repo.get_relationships_for_contact(_id(source)) == []

    @pytest.mark.asyncio
    async def test_repoint_bumps_updated_at(
        self,
        async_connection: AsyncConnection,
        contact_repo: SqlContactRepository,
        relationship_repo: SqlContactRelationshipRepository,
    ) -> None:
        """Re-pointed rows get a fresh ``updated_at``, like other update paths.

        Both the from-side and to-side re-points are exercised. The source rows
        are backdated first so the re-point's ``CURRENT_TIMESTAMP`` (the test
        transaction's start time) is demonstrably newer than the stale value.
        """
        from datetime import UTC, datetime

        survivor = await _make_contact(contact_repo, "Survivor")
        source = await _make_contact(contact_repo, "Source")
        peer_a = await _make_contact(contact_repo, "PeerA")
        peer_b = await _make_contact(contact_repo, "PeerB")

        # source as 'from' and as 'to' so both UPDATE statements run.
        await relationship_repo.create(
            ContactRelationship(
                from_contact_id=_id(source),
                to_contact_id=_id(peer_a),
                relationship_type=RelationshipType.FRIEND,
            )
        )
        await relationship_repo.create(
            ContactRelationship(
                from_contact_id=_id(peer_b),
                to_contact_id=_id(source),
                relationship_type=RelationshipType.COLLEAGUE,
            )
        )

        stale = datetime(2000, 1, 1, tzinfo=UTC)
        await async_connection.execute(
            text(
                """
                UPDATE contact_relationships
                SET updated_at = :stale
                WHERE from_contact_id = :source_id OR to_contact_id = :source_id
                """
            ),
            {"stale": stale, "source_id": _id(source)},
        )

        await relationship_repo.repoint_contact(
            _id(source), _id(survivor), async_connection
        )

        survivor_rels = await relationship_repo.get_relationships_for_contact(
            _id(survivor)
        )
        assert len(survivor_rels) == 2
        for rel in survivor_rels:
            assert rel.updated_at is not None
            assert rel.updated_at > stale


@pytest.mark.integration
class TestJournalContactRelationshipRepointIntegration:
    """Integration tests for journal-link re-point."""

    @pytest.mark.asyncio
    async def test_repoint_moves_journal_links(
        self,
        async_connection: AsyncConnection,
        contact_repo: SqlContactRepository,
        journal_rel_repo: SqlJournalContactRelationshipRepository,
    ) -> None:
        """Journal links re-point from the source onto the survivor."""
        survivor = await _make_contact(contact_repo, "Survivor")
        source = await _make_contact(contact_repo, "Source")
        journal_id = await _make_journal(async_connection, "Trip")

        await journal_rel_repo.create(
            JournalContactRelationship(
                journal_id=journal_id,
                contact_id=_id(source),
                relationship_type=JournalContactRelationshipType.PARTICIPANT,
            )
        )

        await journal_rel_repo.repoint_contact(
            _id(source), _id(survivor), async_connection
        )

        survivor_links = await journal_rel_repo.get_by_contact(_id(survivor))
        assert len(survivor_links) == 1
        assert survivor_links[0].journal_id == journal_id
        assert (
            survivor_links[0].relationship_type
            == JournalContactRelationshipType.PARTICIPANT
        )
        assert await journal_rel_repo.get_by_contact(_id(source)) == []

    @pytest.mark.asyncio
    async def test_repoint_dedupes_journal_links_on_composite_pk(
        self,
        async_connection: AsyncConnection,
        contact_repo: SqlContactRepository,
        journal_rel_repo: SqlJournalContactRelationshipRepository,
    ) -> None:
        """A duplicate (journal, contact, type) link collapses to one on re-point."""
        survivor = await _make_contact(contact_repo, "Survivor")
        source = await _make_contact(contact_repo, "Source")
        journal_id = await _make_journal(async_connection, "Trip")

        await journal_rel_repo.create(
            JournalContactRelationship(
                journal_id=journal_id,
                contact_id=_id(survivor),
                relationship_type=JournalContactRelationshipType.PARTICIPANT,
            )
        )
        await journal_rel_repo.create(
            JournalContactRelationship(
                journal_id=journal_id,
                contact_id=_id(source),
                relationship_type=JournalContactRelationshipType.PARTICIPANT,
            )
        )
        # A second, non-colliding link only on the source -> must move.
        await journal_rel_repo.create(
            JournalContactRelationship(
                journal_id=journal_id,
                contact_id=_id(source),
                relationship_type=JournalContactRelationshipType.MENTION,
            )
        )

        await journal_rel_repo.repoint_contact(
            _id(source), _id(survivor), async_connection
        )

        survivor_links = await journal_rel_repo.get_by_contact(_id(survivor))
        assert sorted(link.relationship_type.value for link in survivor_links) == [
            JournalContactRelationshipType.MENTION.value,
            JournalContactRelationshipType.PARTICIPANT.value,
        ]
        assert await journal_rel_repo.get_by_contact(_id(source)) == []
