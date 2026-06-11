"""Service for managing journal-contact relationships and associated events."""

import structlog
from core_shared.models.journals import (
    JournalContactRelationship,
    JournalContactRelationshipType,
)
from core_shared.models.journals.attendee_status import AttendeeStatus
from core_shared.models.journals.contact_event_role import ContactEventRole
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.events import ContactSummaryRefreshRequested
from app.core.journal.models.repositories import JournalContactRelationshipRepository
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.unit_of_work import transactional

logger = structlog.get_logger()


class JournalContactService:
    """
    Service for managing journal-contact relationships.

    Handles CRUD operations for relationships between journals and contacts,
    ensuring appropriate domain events (like summary refreshes) are published.
    """

    def __init__(
        self,
        contact_relationship_repo: JournalContactRelationshipRepository,
        event_publisher: OutboxEventPublisher,
    ):
        """
        Initialize the journal contact service.

        Args:
            contact_relationship_repo: Repository for contact relationships
            event_publisher: Publisher for domain events via outbox pattern
        """
        self.contact_relationship_repo = contact_relationship_repo
        self.event_publisher = event_publisher

    @transactional
    async def add_contact_to_journal(
        self, relationship: JournalContactRelationship, transaction: AsyncConnection
    ) -> JournalContactRelationship:
        """
        Add a contact relationship to a journal.

        Publishes ContactSummaryRefreshRequested for the contact.
        """
        created = await self.contact_relationship_repo.create(relationship)
        await self.event_publisher.publish(
            ContactSummaryRefreshRequested(created.contact_id, transaction=transaction)
        )
        return created

    @transactional
    async def remove_contact_from_journal(
        self,
        journal_id: int,
        contact_id: int,
        relationship_type: JournalContactRelationshipType,
        transaction: AsyncConnection,
    ) -> None:
        """
        Remove a contact relationship from a journal.

        Publishes ContactSummaryRefreshRequested for the contact.
        """
        await self.contact_relationship_repo.delete(
            journal_id=journal_id,
            contact_id=contact_id,
            relationship_type=relationship_type,
        )
        await self.event_publisher.publish(
            ContactSummaryRefreshRequested(contact_id, transaction=transaction)
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
    ) -> JournalContactRelationship | None:
        """
        Update specific attributes of a contact relationship.
        """
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
                    updated.contact_id, transaction=transaction
                )
            )
        return updated
