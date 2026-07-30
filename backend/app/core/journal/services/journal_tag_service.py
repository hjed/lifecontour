"""Service layer for journal tag mutations.

Wraps journal tag create/delete and journal<->tag assignment in explicit units
of work so each write commits before the HTTP response is sent (issue #945),
keeping transaction ownership in the service layer rather than the controller.

Assignment and removal also publish ``JournalTagAssigned`` / ``JournalTagRemoved``
through the transactional outbox, in the same unit of work as the junction-table
write, so the journal activity feed cannot drift from what actually happened.
Renaming a tag publishes ``JournalTagRenamed`` the same way, once per journal
that carries it, and deleting one publishes ``JournalTagDeleted`` once per
journal that carried it.
"""

from dataclasses import replace
from uuid import UUID

from core_shared.models.history import Provenance
from core_shared.models.journals import (
    JournalTagNotFoundError,
    JournalValidationError,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.events import (
    JournalTagAssigned,
    JournalTagDeleted,
    JournalTagRemoved,
    JournalTagRenamed,
)
from app.core.journal.models.journal_tag import JournalTag
from app.core.journal.models.repositories import JournalTagRepository
from app.core.journal.services.journal_tag_hierarchy_service import (
    JournalTagHierarchyService,
)
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.unit_of_work import transactional


class JournalTagService:
    """Service for persisting journal tags as committed units of work."""

    def __init__(
        self,
        tag_repo: JournalTagRepository,
        hierarchy_service: JournalTagHierarchyService,
        event_publisher: OutboxEventPublisher,
    ) -> None:
        self.tag_repo = tag_repo
        self.hierarchy_service = hierarchy_service
        self.event_publisher = event_publisher

    @transactional
    async def create_tag(
        self,
        tag: JournalTag,
        transaction: AsyncConnection,
    ) -> JournalTag:
        """Persist a new journal tag, mapping duplicate names to a domain error.

        Raises:
            JournalValidationError: If a tag with the same name already exists.
        """
        try:
            return await self.tag_repo.save(tag)
        except IntegrityError as e:
            # Check if it's a duplicate name error
            if "uq_journal_tags_name" in str(e) or "duplicate key" in str(e).lower():
                raise JournalValidationError(
                    "name",
                    f"A journal tag with the name '{tag.name}' already exists. "
                    "Tag names must be unique.",
                ) from e
            # Re-raise other integrity errors
            raise

    @transactional
    async def update_tag(
        self,
        tag_id: UUID,
        transaction: AsyncConnection,
        name: str | None = None,
        color: str | None = None,
        description: str | None = None,
        parent_id: UUID | None = None,
        set_parent_null: bool = False,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> JournalTag:
        """Update a journal tag, validating names, colour and hierarchy.

        Only the supplied fields change; omitting a field leaves it untouched.
        Clearing the parent requires the explicit ``set_parent_null`` flag,
        since a ``None`` ``parent_id`` is indistinguishable from "not supplied".

        A **name** change also publishes ``JournalTagRenamed`` for every journal
        carrying the tag, in the same unit of work as the write, so each
        journal's activity feed records the change. Colour, description and
        parent publish nothing: they are tag-namespace attributes that are
        invisible on a journal, and the activity-history specification forbids
        recording a change that did not alter the entity.

        Args:
            tag_id: The tag to update.
            transaction: Request connection; the write commits before the response.
            name: New name, if changing.
            color: New hex colour (``#RRGGBB``), if changing.
            description: New description, if changing.
            parent_id: New parent tag, if changing.
            set_parent_null: Move the tag to the root, clearing its parent.
            source: Provenance recorded against a rename.
            changed_by: Actor recorded against a rename.

        Raises:
            JournalTagNotFoundError: The tag, or a supplied parent, does not exist.
            JournalValidationError: The name is taken, the colour is malformed,
                or the parent would create a cycle.
        """
        existing = await self._require_tag(tag_id)

        changes: dict[str, object] = {}

        if name is not None and name != existing.name:
            await self.hierarchy_service.validate_tag_name_uniqueness(
                name, exclude_tag_id=tag_id
            )
            changes["name"] = name

        if color is not None and color != existing.color:
            changes["color"] = color

        if description is not None and description != existing.description:
            changes["description"] = description

        # An explicit parent wins over set_parent_null when both are supplied,
        # matching the contact TagService precedence.
        if parent_id is not None:
            if parent_id != existing.parent_id:
                await self.hierarchy_service.validate_parent(parent_id, tag_id)
                changes["parent_id"] = parent_id
        elif set_parent_null and existing.parent_id is not None:
            changes["parent_id"] = None

        if not changes:
            return existing

        # Rebuild through the dataclass so __post_init__ re-runs its name and
        # colour validation, then surface those as domain errors.
        try:
            updated = replace(existing, **changes)  # type: ignore[arg-type]
        except ValueError as e:
            field = "color" if "color" in str(e).lower() else "name"
            raise JournalValidationError(field, str(e)) from e

        try:
            saved = await self.tag_repo.save(updated)
        except IntegrityError as e:
            # A concurrent insert can take the name between the uniqueness
            # check above and this write; map it the same way create_tag does.
            if "uq_journal_tags_name" in str(e) or "duplicate key" in str(e).lower():
                raise JournalValidationError(
                    "name",
                    f"A journal tag with the name '{updated.name}' already exists. "
                    "Tag names must be unique.",
                ) from e
            raise

        # After the write: the event names the saved row, and a write the
        # constraint rejects therefore cannot reach the publish at all. The unit
        # of work would roll an early outbox row back anyway, so this is belt to
        # that braces rather than the only thing keeping the feed honest.
        if "name" in changes:
            await self._publish_rename(
                tag_id,
                old_name=existing.name,
                new_name=saved.name,
                transaction=transaction,
                source=source,
                changed_by=changed_by,
            )

        return saved

    async def _publish_rename(
        self,
        tag_id: UUID,
        *,
        old_name: str,
        new_name: str,
        transaction: AsyncConnection,
        source: Provenance,
        changed_by: str,
    ) -> None:
        """Fan the rename out to every journal carrying the tag.

        One event per journal rather than one carrying a list of journal ids:
        ``DomainEvent.aggregate_id`` is an ``int`` journal id, and each journal's
        feed is a separate entry the dedup index keys independently.
        """
        for journal_id in await self.tag_repo.get_journal_ids_for_tag(tag_id):
            await self.event_publisher.publish(
                JournalTagRenamed(
                    journal_id,
                    tag_id,
                    old_name,
                    new_name,
                    source=source,
                    changed_by=changed_by,
                    transaction=transaction,
                )
            )

    @transactional
    async def delete_tag(
        self,
        tag_id: UUID,
        transaction: AsyncConnection,
        *,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> None:
        """Delete a journal tag, un-assigning it from every journal.

        Mirrors the contact ``TagService.delete_tag`` contract: an in-use tag is
        deleted rather than blocked. The ``journal_tag_assignments`` rows are
        removed by the table's ``ON DELETE CASCADE`` FK and any child tags are
        re-parented to NULL by ``journal_tags.parent_id``'s ``ON DELETE SET
        NULL``, so no explicit clean-up is needed here.

        Every journal that carried the tag also gets a ``JournalTagDeleted``
        event in the same unit of work, so the tag leaving is recorded in each
        journal's activity feed rather than vanishing silently.

        Args:
            tag_id: The tag to delete.
            transaction: Request connection; the write commits before the response.
            source: Provenance recorded against each journal's history entry.
            changed_by: Actor recorded against each journal's history entry.

        Raises:
            JournalTagNotFoundError: No tag exists with this id.
        """
        tag = await self._require_tag(tag_id)

        # Read the carriers *before* the delete: the assignment rows go with the
        # tag through the cascade, so afterwards there is nothing left to read.
        journal_ids = await self.tag_repo.get_journal_ids_for_tag(tag_id)

        await self.tag_repo.delete(tag_id)

        # Publish after the write, matching update_tag: the events name a write
        # that completed. The unit of work would discard them with a failed
        # delete either way, since the outbox shares this connection.
        for journal_id in journal_ids:
            await self.event_publisher.publish(
                JournalTagDeleted(
                    journal_id,
                    tag_id,
                    tag.name,
                    source=source,
                    changed_by=changed_by,
                    transaction=transaction,
                )
            )

    @transactional
    async def merge_tag(
        self,
        source_id: UUID,
        target_id: UUID,
        transaction: AsyncConnection,
    ) -> None:
        """Merge the source tag into the target tag, deleting the source.

        Mirrors the contact ``TagService.merge_tags`` contract: journals tagged
        with the source end up tagged with the target (journals already holding
        both keep one assignment), the source's children are adopted by the
        target, and the source tag is deleted. The row-level work lives in the
        repository so this layer holds no SQL.

        Args:
            source_id: The tag to merge away and delete.
            target_id: The surviving tag.
            transaction: Request connection; the write commits before the response.

        Raises:
            JournalTagNotFoundError: Either tag does not exist.
            JournalValidationError: The target is the source itself or one of
                its descendants.
        """
        await self.hierarchy_service.validate_merge_target(source_id, target_id)

        await self.tag_repo.merge_into(source_id, target_id)

    @transactional
    async def assign_tag(
        self,
        journal_id: int,
        tag_id: UUID,
        transaction: AsyncConnection,
        *,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> None:
        """Assign an existing tag to a journal as a committed unit of work.

        Publishes ``JournalTagAssigned`` in the same unit of work, but only if the
        assignment did not already exist: the insert is ``ON CONFLICT DO NOTHING``,
        and an event for a no-op would put an "Added Tags" entry in the activity
        feed for a change that never happened.

        Raises:
            JournalTagNotFoundError: No tag exists with this id.
        """
        tag = await self._require_tag(tag_id)

        if not await self.tag_repo.assign_tag(journal_id, tag_id):
            return

        await self.event_publisher.publish(
            JournalTagAssigned(
                journal_id,
                tag_id,
                tag.name,
                source=source,
                changed_by=changed_by,
                transaction=transaction,
            )
        )

    @transactional
    async def remove_tag(
        self,
        journal_id: int,
        tag_id: UUID,
        transaction: AsyncConnection,
        *,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> None:
        """Remove a tag from a journal as a committed unit of work.

        Publishes ``JournalTagRemoved`` only if an assignment was actually deleted,
        for the same reason :meth:`assign_tag` guards its event.

        A tag that does not exist is a no-op rather than an error: to the caller it
        is indistinguishable from a tag that exists but was not assigned, which the
        endpoint has always answered with a successful no-op.
        """
        tag = await self.tag_repo.find_by_id(tag_id)
        if tag is None:
            return

        if not await self.tag_repo.remove_tag(journal_id, tag_id):
            return

        await self.event_publisher.publish(
            JournalTagRemoved(
                journal_id,
                tag_id,
                tag.name,
                source=source,
                changed_by=changed_by,
                transaction=transaction,
            )
        )

    async def _require_tag(self, tag_id: UUID) -> JournalTag:
        """Load the tag or raise, so the service owns the existence rule.

        Assignment also needs the loaded tag's ``name`` for the history event:
        reading it here rather than trusting the caller keeps the event consistent
        with the row the assignment actually points at.
        """
        tag = await self.tag_repo.find_by_id(tag_id)
        if tag is None:
            raise JournalTagNotFoundError(str(tag_id))
        return tag
