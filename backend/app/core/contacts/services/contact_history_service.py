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
        """Get field history for a specific contact with pagination."""
        return await self.history_repo.get_contact_history(contact_id, limit, offset)

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
