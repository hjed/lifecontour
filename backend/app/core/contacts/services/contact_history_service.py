"""Contact field-level history *read* service.

ITER12-003 Phase 2 removed the synchronous ``record_*`` write methods: contact
history is now produced solely by the event-driven ``HistoryProjectionConsumer``
from contact domain events. This service is read-only — it backs the REST
``GET /api/contacts/{id}/history`` endpoint, the MCP ``get_contact_history`` tool,
and the summary generator's history reads.
"""

from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.repositories import (
    ContactFieldHistoryEntry,
    ContactFieldHistoryRepository,
)

_TASK_ENTITY_TYPE = "task"


class ContactHistoryService:
    """Read-only service for contact field-level history."""

    def __init__(self, history_repo: ContactFieldHistoryRepository):
        self.history_repo = history_repo

    async def get_contact_history(
        self,
        contact_id: int,
        limit: int = 50,
        offset: int = 0,
        _transaction: AsyncConnection | None = None,
    ) -> list[ContactFieldHistoryEntry]:
        """Get field history for a specific contact with pagination.

        Task rows on this feed are **named** before they are returned. A task
        linked to this person is recorded on the *task* (ITER18-003 Phase 9), so
        the row that reaches a contact's page carries the reader's own id in
        both of its values and nothing that identifies the commitment. Without
        the name the entry reads "Linked to a task" and points at nothing — and
        a task has no route of its own to link to instead.

        One extra query, and only when the page actually holds task rows.
        """
        entries = await self.history_repo.get_contact_history(contact_id, limit, offset)
        await self._name_the_tasks(entries)
        return entries

    async def _name_the_tasks(self, entries: list[ContactFieldHistoryEntry]) -> None:
        """Stamp ``entity_label`` on the task rows of one page, in place."""
        task_ids = {e.entity_id for e in entries if e.entity_type == _TASK_ENTITY_TYPE}
        if not task_ids:
            return

        labels = await self.history_repo.get_task_labels(sorted(task_ids))
        for entry in entries:
            if entry.entity_type == _TASK_ENTITY_TYPE:
                entry.entity_label = labels.get(entry.entity_id)

    async def get_contact_history_count(
        self,
        contact_id: int,
        _transaction: AsyncConnection | None = None,
    ) -> int:
        """Get total count of history entries for a specific contact."""
        return await self.history_repo.get_contact_history_count(contact_id)

    async def get_entity_history(
        self,
        entity_type: str,
        entity_id: int,
        _transaction: AsyncConnection | None = None,
    ) -> list[ContactFieldHistoryEntry]:
        """Get field history for a specific entity."""
        return await self.history_repo.get_entity_history(entity_type, entity_id)
