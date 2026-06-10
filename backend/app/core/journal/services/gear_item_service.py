"""Service layer for gear item mutations.

Wraps gear item create/update/delete in explicit units of work so each write is
committed before the HTTP response is sent (issue #945), keeping transaction
ownership in the service layer rather than the controller. The update path also
publishes a ``GearItemUpdated`` event inside the same unit of work.
"""

from typing import Any

from core_shared.models.history import Provenance
from core_shared.models.journals.gear_item import GearItem
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.events import GearItemUpdated
from app.core.journal.models.repositories import GearItemRepository
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.unit_of_work import transactional


class GearItemService:
    """Service for persisting gear items as committed units of work."""

    def __init__(
        self,
        gear_item_repo: GearItemRepository,
        event_publisher: OutboxEventPublisher,
    ) -> None:
        self.gear_item_repo = gear_item_repo
        self.event_publisher = event_publisher

    @transactional
    async def create(
        self,
        gear_item: GearItem,
        transaction: AsyncConnection,
    ) -> GearItem:
        """Persist a new gear item and return the created entity as a committed unit.

        The caller is responsible for constructing and validating the entity.
        """
        return await self.gear_item_repo.save(gear_item)

    @transactional
    async def update(
        self,
        gear_item: GearItem,
        changed_fields: dict[str, Any],
        transaction: AsyncConnection,
    ) -> GearItem:
        """Persist changes to a gear item and publish a ``GearItemUpdated`` event.

        The caller loads the gear item, applies the requested changes, runs domain
        validation, and computes ``changed_fields`` before calling this method.

        Args:
            gear_item: The mutated gear item to persist (must have an id).
            changed_fields: Map of field name to ``(old, new)`` for the event;
                when empty, no event is published.
            transaction: Request connection; the write commits before the response.
        """
        updated = await self.gear_item_repo.save(gear_item)

        if changed_fields:
            # A plain gear edit is not scoped to a single journal (gear is shared
            # across journals), so journal_id is left unset and the history
            # projection skips it. Provenance is still carried for any future
            # journal-scoped gear edit path.
            event = GearItemUpdated(
                gear_item_id=str(updated.id),
                changed_fields=changed_fields,
                source=Provenance.UI,
                changed_by="ui",
                transaction=transaction,
            )
            await self.event_publisher.publish(event)

        return updated

    @transactional
    async def delete(
        self,
        gear_item_id: str,
        transaction: AsyncConnection,
    ) -> None:
        """Delete a gear item as a committed unit.

        The caller is responsible for verifying existence and ownership.
        """
        await self.gear_item_repo.delete(gear_item_id)
