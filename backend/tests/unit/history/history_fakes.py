"""Test doubles shared by the owner-scoped history read services' unit tests."""

from app.core.history.models import FieldHistoryEntry


class FakeHistoryRepo:
    """Records what it was asked, so the service's arithmetic is observable."""

    def __init__(
        self, *, owner: str | None, entries: list[FieldHistoryEntry] | None = None
    ) -> None:
        self._owner = owner
        self._entries = entries or []
        self.owner_calls: list[tuple[str, int]] = []
        self.aggregate_calls: list[tuple[str, int, int, int]] = []
        self.count_calls: list[tuple[str, int]] = []

    async def get_history_owner(self, entity_type: str, entity_id: int) -> str | None:
        self.owner_calls.append((entity_type, entity_id))
        return self._owner

    async def get_history_for_aggregate(
        self, root_type: str, root_id: int, limit: int = 50, offset: int = 0
    ) -> list[FieldHistoryEntry]:
        self.aggregate_calls.append((root_type, root_id, limit, offset))
        return self._entries

    async def get_history_for_aggregate_count(
        self, root_type: str, root_id: int
    ) -> int:
        self.count_calls.append((root_type, root_id))
        return len(self._entries)
