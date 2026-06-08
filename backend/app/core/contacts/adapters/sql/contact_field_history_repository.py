"""SQL implementation of ContactFieldHistoryRepository.

Contacts now ride on the shared, entity-agnostic ``SqlFieldHistoryRepository``. This
class is a thin contact-rooted façade that preserves the existing contact read API
(``get_contact_history`` / ``get_contact_history_count``) by delegating to the shared
"contact" aggregation strategy. Behaviour is unchanged.
"""

from app.core.contacts.models.repositories import (
    ContactFieldHistoryEntry,
    ContactFieldHistoryRepository,
)
from app.core.history.adapters.sql.field_history_repository import (
    SqlFieldHistoryRepository,
)

_CONTACT_ROOT = "contact"


class SqlContactFieldHistoryRepository(
    SqlFieldHistoryRepository, ContactFieldHistoryRepository
):
    """SQL contact history repository backed by the shared field-history repository."""

    async def get_contact_history(
        self, contact_id: int, limit: int = 50, offset: int = 0
    ) -> list[ContactFieldHistoryEntry]:
        """Get field history for a specific contact with pagination."""
        return await self.get_history_for_aggregate(
            _CONTACT_ROOT, contact_id, limit, offset
        )

    async def get_contact_history_count(self, contact_id: int) -> int:
        """Get total count of history entries for a specific contact."""
        return await self.get_history_for_aggregate_count(_CONTACT_ROOT, contact_id)
