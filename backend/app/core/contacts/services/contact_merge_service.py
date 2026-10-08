"""Service for merging two contacts into a single surviving record.

ITER13-001 Phase 1 built the engine's hardest re-points — contact-to-contact
relationships and journal links — behind a not-yet-exposed service. Phase 2
completes the aggregate merge: it re-points the remaining sub-entities (methods,
addresses, notes, important dates, tags), applies the scalar identity fields with
a prefer-non-empty (survivor-wins) policy, deletes the source, records the merge
as an inline ``field_history`` row, and requests regeneration of the survivor's
AI summary. The ``ContactMerged`` event and the REST/MCP surface land in Phase 3.
"""

from typing import Any

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
from app.core.history.models import FieldHistoryRepository
from app.core.integrations.adapters.sql.sync_metadata_repository import (
    SyncMetadataRepository,
)
from app.core.journal.models.repositories import JournalContactRelationshipRepository
from app.core.tasks.services.task_contact_merge_service import (
    TaskContactMergeService,
)
from app.infrastructure.unit_of_work import transactional

logger = structlog.get_logger(__name__)

# Scalar identity fields that participate in the merge (ITER13-001 / ITER13-002).
_SCALAR_FIELDS = (
    "first_name",
    "last_name",
    "middle_name",
    "nick_name",
    "company",
    "job_title",
    "photo_url",
    "is_favourite",
)

# Fields surfaced to the user as conflicts when both sides differ. ``is_favourite``
# is a boolean OR-merge (default ``False``) with no meaningful "both set and
# differing" state, so it is excluded from conflict detection — it can still be
# set explicitly via an override.
_CONFLICT_FIELDS = (
    "first_name",
    "last_name",
    "middle_name",
    "nick_name",
    "company",
    "job_title",
    "photo_url",
)


class ContactMergeService:
    """Merge a source contact into a user-chosen surviving contact.

    ITER12-003 Phase 2: the inline ``merged_from`` audit row is produced by the
    event-driven HistoryProjectionConsumer from the ``ContactUpdated`` event
    published here, rather than a synchronous ``history_service.record_*`` call.

    **A merge is a list of tables, and that is the thing to remember about this
    class.** It re-points exactly the tables that existed when each step was
    written, and nothing fails when a new one is missed: ``task_contacts``
    arrived two iterations after the rest with ``ON DELETE CASCADE`` on
    ``contact_id``, which is right for *deleting* a contact and silently wrong
    for merging one — the delete below took the task links with it, unnoticed,
    for thirty-one phases. Every new table referencing ``contacts`` is a line
    somebody has to add here.
    """

    def __init__(
        self,
        contact_repo: ContactRepository,
        relationship_repo: ContactRelationshipRepository,
        journal_relationship_repo: JournalContactRelationshipRepository,
        event_publisher: ContactEventPublisher,
        history_repo: FieldHistoryRepository,
        sync_metadata_repo: SyncMetadataRepository,
        task_merge_service: TaskContactMergeService,
    ):
        self.contact_repo = contact_repo
        self.relationship_repo = relationship_repo
        self.journal_relationship_repo = journal_relationship_repo
        self.event_publisher = event_publisher
        self.history_repo = history_repo
        self.sync_metadata_repo = sync_metadata_repo
        self.task_merge_service = task_merge_service

    def has_scalar_conflicts(self, survivor: Contact, source: Contact) -> bool:
        """Report whether two contacts have conflicting scalar identity fields.

        Returns ``True`` when any string identity field is non-empty on **both**
        contacts and the values differ — the case that needs field-by-field
        resolution. Mirrors ``has_base_conflicts`` in ``journal_merge_service``.
        ``is_favourite`` is excluded (boolean OR-merge — see ``_CONFLICT_FIELDS``).
        """
        for field in _CONFLICT_FIELDS:
            survivor_value = getattr(survivor, field)
            source_value = getattr(source, field)
            if survivor_value and source_value and survivor_value != source_value:
                return True
        return False

    @transactional
    async def merge_contacts(
        self,
        survivor_id: int,
        source_id: int,
        *,
        transaction: AsyncConnection,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
        overrides: dict[str, Any] | None = None,
        user_id: str,
    ) -> Contact:
        """Absorb the source contact into the survivor, returning the unified contact.

        Re-points and dedupes the full aggregate (relationships, journal links,
        methods, addresses, notes, important dates, tags, task links), re-points
        the source's top-level ``field_history`` rows onto the survivor so the
        unified record carries both contacts' audit trail, applies the scalar
        identity fields, deletes the source, records an inline ``merged_from``
        history row carrying provenance, and requests regeneration of the
        survivor's AI summary. The whole operation is a single atomic unit of work.

        Scalar fields resolve per ``overrides`` (ITER13-002): a present, non-``None``
        ``overrides[field]`` is applied verbatim (the caller has already resolved
        the survivor / source / custom choice into a concrete value, mirroring the
        journal ``MergeResolutionDialog`` ↔ ``merge_journals`` contract); fields
        without an override fall back to the ITER13-001 prefer-non-empty default
        (survivor wins on conflict).
        """
        if survivor_id == source_id:
            raise ContactMergeConflictError("Cannot merge a contact into itself")

        survivor = await self.contact_repo.find_by_id(survivor_id, user_id=user_id)
        if survivor is None:
            raise ContactNotFoundError(survivor_id)

        source_contact = await self.contact_repo.find_by_id(source_id, user_id=user_id)
        if source_contact is None:
            raise ContactNotFoundError(source_id)

        # 0. Re-point the source's task links onto the survivor. This one is
        #    not optional housekeeping: ``task_contacts.contact_id`` is
        #    ON DELETE CASCADE, so without it the delete in step 3 destroys
        #    every task link the absorbed contact held — silently, since a
        #    cascade raises nothing. The tasks domain performs the move and
        #    announces one event per task it touched, because a task's history
        #    is the tasks domain's to write.
        #
        #    **It is step 0 for a locking reason**, exactly as the equivalent
        #    call is the first write in ``merge_journals``. The re-point takes
        #    both contacts FOR UPDATE in ascending id order so two merges queue
        #    instead of deadlocking — and that only holds if nothing in this
        #    transaction has already locked one of the pair. Every re-point
        #    below writes ``contact_id = survivor_id`` into a table with a
        #    foreign key to ``contacts``, and PostgreSQL takes FOR KEY SHARE on
        #    the survivor's row to validate each one. Running the task re-point
        #    after them would mean two merges into the same survivor both held
        #    KEY SHARE on it and both then asked for FOR UPDATE, which is a
        #    deadlock rather than a queue.
        await self.task_merge_service.repoint_contact_links(
            source_contact_id=source_id,
            survivor_contact_id=survivor_id,
            transaction=transaction,
            source=source,
            changed_by=changed_by,
        )

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

        # 1b. Carry the source's top-level ``contact`` history rows onto the
        #     survivor so the unified record's aggregate history is complete.
        #     Sub-entity history rows keep their own ids — already re-pointed
        #     above — so only the ``entity_type = "contact"`` rows move. Runs after
        #     the sub-entities have moved and before the source row is deleted,
        #     within the same merge transaction.
        await self.history_repo.repoint_entity_history(
            source_id, survivor_id, "contact", transaction
        )

        # 1b-ii. And the source's *task* records, which the statement above
        #     cannot reach. A person's record of a task is filed on the task
        #     and names them only in its field name (``contact:{id}``), so it
        #     is found by field name rather than by entity id — two statements
        #     over disjoint sets, not one that could have been widened.
        #
        #     Without it the merge does not delete these rows, it strands them:
        #     ``field_history`` has no foreign key to ``contacts``, so they
        #     survive the delete in step 3 and become unreadable, since the only
        #     predicate that selects them matches on a contact id that is gone.
        #     Same placement and the same reason as the call above — inside this
        #     unit of work and before that delete, after which the id it
        #     searches for no longer exists.
        await self.history_repo.repoint_contact_task_history(
            source_id, survivor_id, transaction
        )

        # 1c. Re-point the source's external links onto the survivor so the merge
        #     does not orphan ``sync_metadata`` link rows (no
        #     ON DELETE CASCADE). Same-service collisions are surfaced for remote
        #     reconciliation by the integration workers. Local-only re-point — the
        #     remote calls stay in the workers consuming ``ContactMerged``.
        collisions = await self.sync_metadata_repo.repoint_contact_links(
            source_id, survivor_id, transaction, user_id=user_id
        )

        # 2. Apply scalar identity fields: overrides win, else prefer-non-empty.
        merged, override_changes = self._merge_scalars(
            survivor, source_contact, overrides or {}
        )
        await self.contact_repo.save(merged)

        # 3. The source's aggregate has moved; delete the now-empty source row.
        #    Note: we deliberately do NOT emit ``ContactDeleted`` here — that
        #    event makes integration workers (e.g. Google) delete the *remote*
        #    contact unconditionally, which contradicts merge semantics (the
        #    source's links may need to carry over to, or consolidate onto, the
        #    survivor — ITER13-005). The source's now-stale search row is instead
        #    removed by the search indexer's ``ContactMerged`` handler.
        await self.contact_repo.delete(source_id, user_id=user_id)

        # 4. Publish the merge as a ContactUpdated event; the history projection
        #    decodes the plain "merged_from" key to a contact-level audit row
        #    carrying provenance (identical to the prior dual-write row). Any
        #    explicitly-overridden scalar fields are recorded alongside as
        #    (old, new) so the override choices stay auditable.
        changed_fields: dict[str, Any] = {"merged_from": (source_id, survivor_id)}
        changed_fields.update(override_changes)
        await self.event_publisher.publish(
            ContactUpdated(
                survivor_id,
                changed_fields,
                source=source,
                changed_by=changed_by,
                transaction=transaction,
                user_id=survivor.user_id,
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
                user_id=survivor.user_id,
                external_collisions=[c.as_dict() for c in collisions],
            )
        )

        logger.info(
            "Contacts merged",
            survivor_id=survivor_id,
            source_id=source_id,
            source=str(source),
        )

        merged_survivor = await self.contact_repo.find_by_id(
            survivor_id, user_id=user_id
        )
        if merged_survivor is None:  # pragma: no cover - survivor was just updated
            raise ContactNotFoundError(survivor_id)
        return merged_survivor

    @staticmethod
    def _merge_scalars(
        survivor: Contact, source: Contact, overrides: dict[str, Any]
    ) -> tuple[Contact, dict[str, Any]]:
        """Build the survivor's merged scalar identity, honouring overrides.

        For each scalar field: a present, non-``None`` ``overrides[field]`` is
        applied verbatim; otherwise prefer-non-empty (survivor wins, then source
        fills the gap). Returns the merged contact plus a dict of the fields an
        override actually changed, as ``{field: (old, new)}`` for the audit trail.
        """
        resolved: dict[str, Any] = {}
        override_changes: dict[str, Any] = {}
        for field in _SCALAR_FIELDS:
            survivor_value = getattr(survivor, field)
            override_value = overrides.get(field)
            if override_value is not None:
                resolved[field] = override_value
                if override_value != survivor_value:
                    override_changes[field] = (survivor_value, override_value)
            else:
                resolved[field] = survivor_value or getattr(source, field)
        # ``resolved`` is a dict, so mypy cannot see a missing owner here: name
        # it explicitly. A merge never re-owns the survivor.
        return (
            Contact(id=survivor.id, user_id=survivor.user_id, **resolved),
            override_changes,
        )
