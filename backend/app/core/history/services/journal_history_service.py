"""Read service for journal field-level history.

Thin wrapper over the entity-agnostic :class:`FieldHistoryRepository` that resolves
a journal's history via the registered ``"journal"`` aggregation strategy. Mirrors
``ContactHistoryService``'s read methods so the journal history endpoint reads the
same way the contact one does.
"""

from app.core.history.models import FieldHistoryEntry, FieldHistoryRepository

_JOURNAL_ROOT_TYPE = "journal"


class JournalHistoryService:
    """Provides paginated read access to a journal's field-level history."""

    def __init__(self, history_repo: FieldHistoryRepository):
        self.history_repo = history_repo

    async def get_journal_history(
        self, journal_id: int, limit: int = 20, offset: int = 0
    ) -> list[FieldHistoryEntry]:
        """Get paginated history for a journal (most recent first)."""
        return await self.history_repo.get_history_for_aggregate(
            _JOURNAL_ROOT_TYPE, journal_id, limit, offset
        )

    async def get_journal_history_count(self, journal_id: int) -> int:
        """Get the total number of history entries for a journal."""
        return await self.history_repo.get_history_for_aggregate_count(
            _JOURNAL_ROOT_TYPE, journal_id
        )
