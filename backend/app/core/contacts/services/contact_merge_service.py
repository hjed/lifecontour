"""Service for merging two contacts into a single surviving record.

ITER13-001 Phase 1 builds the engine's hardest re-points — contact-to-contact
relationships and journal links — behind a not-yet-exposed service. Scalar/
sub-entity handling, source deletion, summary regeneration, the ``ContactMerged``
event, and the REST/MCP surface land in later phases.
"""

import structlog
from core_shared.models.contacts.entities import Contact
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.exceptions import (
    ContactMergeConflictError,
    ContactNotFoundError,
)
from app.core.contacts.models.repositories import (
    ContactRelationshipRepository,
    ContactRepository,
)
from app.core.journal.models.repositories import JournalContactRelationshipRepository
from app.infrastructure.unit_of_work import transactional

logger = structlog.get_logger(__name__)


class ContactMergeService:
    """Merge a source contact into a user-chosen surviving contact."""

    def __init__(
        self,
        contact_repo: ContactRepository,
        relationship_repo: ContactRelationshipRepository,
        journal_relationship_repo: JournalContactRelationshipRepository,
    ):
        self.contact_repo = contact_repo
        self.relationship_repo = relationship_repo
        self.journal_relationship_repo = journal_relationship_repo

    @transactional
    async def merge_contacts(
        self,
        survivor_id: int,
        source_id: int,
        *,
        transaction: AsyncConnection,
    ) -> Contact:
        """Absorb the source contact's relationships and journal links into the survivor.

        Phase 1 scope: validate preconditions and re-point the contact-to-contact
        relationships and journal links. The survivor is returned unchanged; the
        source is not yet deleted (Phase 2).
        """
        if survivor_id == source_id:
            raise ContactMergeConflictError("Cannot merge a contact into itself")

        survivor = await self.contact_repo.find_by_id(survivor_id)
        if survivor is None:
            raise ContactNotFoundError(survivor_id)

        source = await self.contact_repo.find_by_id(source_id)
        if source is None:
            raise ContactNotFoundError(source_id)

        await self.relationship_repo.repoint_contact(
            source_id, survivor_id, transaction
        )
        await self.journal_relationship_repo.repoint_contact(
            source_id, survivor_id, transaction
        )

        logger.info(
            "Contact relationships and journal links re-pointed for merge",
            survivor_id=survivor_id,
            source_id=source_id,
        )
        return survivor
