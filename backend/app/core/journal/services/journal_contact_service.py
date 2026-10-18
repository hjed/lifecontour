"""Service for managing journal-contact relationships and associated events."""

from collections.abc import Sequence

import structlog
from core_shared.models.journals import (
    JournalContactRelationship,
    JournalContactRelationshipType,
)
from core_shared.models.journals.attendee_status import AttendeeStatus
from core_shared.models.journals.contact_event_role import ContactEventRole
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.events import ContactSummaryRefreshRequested
from app.core.contacts.models.exceptions import ContactNotFoundError
from app.core.contacts.models.repositories import ContactRepository
from app.core.journal.models.repositories import (
    JournalContactRelationshipRepository,
    JournalRepository,
)
from app.core.journal.services.journal_write_guard import guard_journal_write
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.unit_of_work import transactional

logger = structlog.get_logger()


class JournalContactService:
    """
    Service for managing journal-contact relationships.

    Handles CRUD operations for relationships between journals and contacts,
    ensuring appropriate domain events (like summary refreshes) are published.

    A journal's people are its owner's contacts: linking is the one place that
    rule lands, so every path that adds a contact to a journal goes through
    :meth:`add_contact_to_journal`.
    """

    def __init__(
        self,
        contact_relationship_repo: JournalContactRelationshipRepository,
        event_publisher: OutboxEventPublisher,
        contact_repo: ContactRepository,
        journal_repo: JournalRepository,
    ):
        """
        Initialize the journal contact service.

        Args:
            contact_relationship_repo: Repository for contact relationships
            event_publisher: Publisher for domain events via outbox pattern
            contact_repo: Owner-scoped contact reads, for the ownership check
            journal_repo: The journal's locking read, which every write to a
                relationship takes first (the relationships are part of the
                journal's version)
        """
        self.contact_relationship_repo = contact_relationship_repo
        self.event_publisher = event_publisher
        self.contact_repo = contact_repo
        self.journal_repo = journal_repo

    @transactional
    async def add_contact_to_journal(
        self,
        relationship: JournalContactRelationship,
        *,
        user_id: str,
        transaction: AsyncConnection,
        expected_etags: Sequence[str] | None = None,
    ) -> JournalContactRelationship:
        """
        Add a contact relationship to a journal.

        ``user_id`` is the journal's owner, which every caller has already
        proved. The contact must be theirs too: another user's contact is not
        found, exactly as a missing one is, and nothing is written or published.

        Publishes ContactSummaryRefreshRequested for the contact.

        Raises:
            ContactNotFoundError: The contact is missing or another user's.
            PreconditionFailedError: ``expected_etags`` names a version the
                journal has moved on from.
        """
        await guard_journal_write(
            self.journal_repo, relationship.journal_id, expected_etags
        )
        if not await self.contact_repo.contact_exists(
            relationship.contact_id, user_id=user_id
        ):
            raise ContactNotFoundError(relationship.contact_id)
        created = await self.contact_relationship_repo.create(relationship)
        await self.event_publisher.publish(
            ContactSummaryRefreshRequested(
                created.contact_id,
                journal_id=created.journal_id,
                transaction=transaction,
            )
        )
        return created

    @transactional
    async def remove_contact_from_journal(
        self,
        journal_id: int,
        contact_id: int,
        relationship_type: JournalContactRelationshipType,
        transaction: AsyncConnection,
        expected_etags: Sequence[str] | None = None,
    ) -> None:
        """
        Remove a contact relationship from a journal.

        Publishes ContactSummaryRefreshRequested for the contact.
        """
        await guard_journal_write(self.journal_repo, journal_id, expected_etags)
        await self.contact_relationship_repo.delete(
            journal_id=journal_id,
            contact_id=contact_id,
            relationship_type=relationship_type,
        )
        await self.event_publisher.publish(
            ContactSummaryRefreshRequested(
                contact_id, journal_id=journal_id, transaction=transaction
            )
        )

    @transactional
    async def update_attributes(
        self,
        journal_id: int,
        contact_id: int,
        relationship_type: JournalContactRelationshipType,
        transaction: AsyncConnection,
        status: AttendeeStatus | None = None,
        role: ContactEventRole | None = None,
        update_status: bool = False,
        update_role: bool = False,
        expected_etags: Sequence[str] | None = None,
    ) -> JournalContactRelationship | None:
        """
        Update specific attributes of a contact relationship.
        """
        await guard_journal_write(self.journal_repo, journal_id, expected_etags)
        updated = await self.contact_relationship_repo.update_attributes(
            journal_id=journal_id,
            contact_id=contact_id,
            relationship_type=relationship_type,
            status=status,
            role=role,
            update_status=update_status,
            update_role=update_role,
        )
        if updated:
            await self.event_publisher.publish(
                ContactSummaryRefreshRequested(
                    updated.contact_id,
                    journal_id=updated.journal_id,
                    transaction=transaction,
                )
            )
        return updated
