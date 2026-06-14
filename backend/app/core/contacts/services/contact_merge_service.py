"""Service for merging two contacts into a single surviving record.

ITER13-001 Phase 1 built the engine's hardest re-points — contact-to-contact
relationships and journal links — behind a not-yet-exposed service. Phase 2
completes the aggregate merge: it re-points the remaining sub-entities (methods,
addresses, notes, important dates, tags), applies the scalar identity fields with
a prefer-non-empty (survivor-wins) policy, deletes the source, records the merge
as an inline ``field_history`` row, and requests regeneration of the survivor's
AI summary. The ``ContactMerged`` event and the REST/MCP surface land in Phase 3.
"""

import structlog
from core_shared.models.contacts.entities import Contact
from core_shared.models.contacts.value_objects import Provenance
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.events import (
    ContactMerged,
    ContactSummaryRefreshRequested,
    ContactUpdated,
)
from app.core.contacts.models.exceptions import (
    ContactMergeConflictError,
    ContactNotFoundError,
)
from app.core.contacts.models.repositories import (
    ContactEventPublisher,
    ContactRelationshipRepository,
    ContactRepository,
)
from app.core.journal.models.repositories import JournalContactRelationshipRepository
from app.infrastructure.unit_of_work import transactional

logger = structlog.get_logger(__name__)


class ContactMergeService:
    """Merge a source contact into a user-chosen surviving contact.

    ITER12-003 Phase 2: the inline ``merged_from`` audit row is produced by the
    event-driven HistoryProjectionConsumer from the ``ContactUpdated`` event
    published here, rather than a synchronous ``history_service.record_*`` call.
    """

    def __init__(
        self,
        contact_repo: ContactRepository,
        relationship_repo: ContactRelationshipRepository,
        journal_relationship_repo: JournalContactRelationshipRepository,
        event_publisher: ContactEventPublisher,
    ):
        self.contact_repo = contact_repo
        self.relationship_repo = relationship_repo
        self.journal_relationship_repo = journal_relationship_repo
        self.event_publisher = event_publisher

    @transactional
    async def merge_contacts(
        self,
        survivor_id: int,
        source_id: int,
        *,
        transaction: AsyncConnection,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
    ) -> Contact:
        """Absorb the source contact into the survivor, returning the unified contact.

        Re-points and dedupes the full aggregate (relationships, journal links,
        methods, addresses, notes, important dates, tags), applies the scalar
        identity fields with a prefer-non-empty policy (survivor wins on
        conflict — per-field overrides arrive in ITER13-002), deletes the source,
        records an inline ``merged_from`` history row carrying provenance, and
        requests regeneration of the survivor's AI summary. The whole operation
        is a single atomic unit of work.
        """
        if survivor_id == source_id:
            raise ContactMergeConflictError("Cannot merge a contact into itself")

        survivor = await self.contact_repo.find_by_id(survivor_id)
        if survivor is None:
            raise ContactNotFoundError(survivor_id)

        source_contact = await self.contact_repo.find_by_id(source_id)
        if source_contact is None:
            raise ContactNotFoundError(source_id)

        # 1. Re-point the relationship graph (Phase 1) and the sub-entities.
        await self.relationship_repo.repoint_contact(
            source_id, survivor_id, transaction
        )
        await self.journal_relationship_repo.repoint_contact(
            source_id, survivor_id, transaction
        )
        await self.contact_repo.repoint_methods(source_id, survivor_id, transaction)
        await self.contact_repo.repoint_addresses(source_id, survivor_id, transaction)
        await self.contact_repo.repoint_notes(source_id, survivor_id, transaction)
        await self.contact_repo.repoint_important_dates(
            source_id, survivor_id, transaction
        )
        await self.contact_repo.repoint_tags(source_id, survivor_id, transaction)

        # 2. Apply scalar identity fields with prefer-non-empty (survivor wins).
        merged = self._merge_scalars(survivor, source_contact)
        await self.contact_repo.save(merged)

        # 3. The source's aggregate has moved; delete the now-empty source row.
        #    Note: we deliberately do NOT emit ``ContactDeleted`` here — that
        #    event makes integration workers (e.g. Google) delete the *remote*
        #    contact unconditionally, which contradicts merge semantics (the
        #    source's links may need to carry over to, or consolidate onto, the
        #    survivor — ITER13-005). The source's now-stale search row is instead
        #    removed by the search indexer's ``ContactMerged`` handler.
        await self.contact_repo.delete(source_id)

        # 4. Publish the merge as a ContactUpdated event; the history projection
        #    decodes the plain "merged_from" key to a contact-level audit row
        #    carrying provenance (identical to the prior dual-write row).
        await self.event_publisher.publish(
            ContactUpdated(
                survivor_id,
                {"merged_from": (source_id, survivor_id)},
                source=source,
                changed_by=changed_by,
                transaction=transaction,
            )
        )

        # 5. The survivor's interaction summary is now stale — regenerate it.
        await self.event_publisher.publish(
            ContactSummaryRefreshRequested(survivor_id, transaction=transaction)
        )

        # 6. Announce the merge so downstream consumers (ITER13-005 external-sync
        #    reconciliation) can reconcile the survivor's external links. No
        #    consumer exists yet; an absent consumer must not error.
        await self.event_publisher.publish(
            ContactMerged(
                survivor_id,
                source_id,
                source=source,
                changed_by=changed_by,
                transaction=transaction,
            )
        )

        logger.info(
            "Contacts merged",
            survivor_id=survivor_id,
            source_id=source_id,
            source=str(source),
        )

        merged_survivor = await self.contact_repo.find_by_id(survivor_id)
        if merged_survivor is None:  # pragma: no cover - survivor was just updated
            raise ContactNotFoundError(survivor_id)
        return merged_survivor

    @staticmethod
    def _merge_scalars(survivor: Contact, source: Contact) -> Contact:
        """Build the survivor's merged scalar identity using prefer-non-empty.

        The survivor's value wins whenever it is set; otherwise the source's
        value fills the gap. Per-field overrides arrive in ITER13-002.
        """
        return Contact(
            id=survivor.id,
            first_name=survivor.first_name or source.first_name,
            last_name=survivor.last_name or source.last_name,
            middle_name=survivor.middle_name or source.middle_name,
            nick_name=survivor.nick_name or source.nick_name,
            company=survivor.company or source.company,
            job_title=survivor.job_title or source.job_title,
            photo_url=survivor.photo_url or source.photo_url,
            is_favourite=survivor.is_favourite or source.is_favourite,
        )
