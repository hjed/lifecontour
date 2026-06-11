"""Service layer for gear item mutations.

Wraps gear item create/update/delete in explicit units of work so each write is
committed before the HTTP response is sent (issue #945), keeping transaction
ownership in the service layer rather than the controller. The update path also
publishes a ``GearItemUpdated`` event inside the same unit of work.
"""

from datetime import date, datetime
from typing import Any

from core_shared.models.history import Provenance
from core_shared.models.journals import GearItemValidationError
from core_shared.models.journals.gear_item import GearItem
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.events import GearItemUpdated
from app.core.journal.models.repositories import GearItemRepository
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.unit_of_work import transactional

# Fields whose changes are tracked in the GearItemUpdated event.
_TRACKED_FIELDS = ("name", "model", "serial_number", "purchase_date", "manufacturer")


def _to_event_value(value: Any) -> Any:
    """Serialize a field value for the ``(old, new)`` changed-fields payload."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


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
        transaction: AsyncConnection,
        *,
        changed_by: str = "ui",
        source: Provenance = Provenance.UI,
    ) -> GearItem:
        """Persist changes to a gear item and publish a ``GearItemUpdated`` event.

        The caller loads the gear item, applies the requested changes and runs
        domain validation. The changed-fields diff is computed **here**, inside
        the unit of work, against the persisted state — so the event payload
        always reflects what was actually saved (per the service-layer
        changed-fields guideline) rather than depending on each call site.

        Args:
            gear_item: The mutated gear item to persist (must have an id).
            transaction: Request connection; the write commits before the response.
            changed_by: Who/what made the change (event provenance).
            source: Provenance of the change.

        Raises:
            GearItemValidationError: If the item has no id, or no gear item with
                that id exists (so ``update`` can never silently create a record
                via the repository upsert without the expected event/audit trail).
        """
        if gear_item.id is None:
            raise GearItemValidationError("id", "Gear item id is required for update")

        existing = await self.gear_item_repo.find_by_id(str(gear_item.id))
        if existing is None:
            raise GearItemValidationError(
                "id", f"Gear item {gear_item.id} not found; cannot update"
            )

        updated = await self.gear_item_repo.save(gear_item)

        changed_fields: dict[str, Any] = {}
        for field in _TRACKED_FIELDS:
            old_val = _to_event_value(getattr(existing, field, None))
            new_val = _to_event_value(getattr(updated, field, None))
            if old_val != new_val:
                changed_fields[field] = (old_val, new_val)

        if changed_fields:
            # A plain gear edit is not scoped to a single journal (gear is shared
            # across journals), so journal_id is left unset and the history
            # projection skips it.
            event = GearItemUpdated(
                gear_item_id=str(updated.id),
                changed_fields=changed_fields,
                source=source,
                changed_by=changed_by,
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
