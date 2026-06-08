"""SQL implementation of the entity-agnostic FieldHistoryRepository."""

from datetime import datetime

from core_shared.models.history import Provenance
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.history.models import (
    FieldHistoryEntry,
    FieldHistoryRepository,
    get_aggregation_strategy,
)

_SELECT_COLUMNS = (
    "id, entity_type, entity_id, field_name, old_value, new_value, "
    "changed_by, source, event_id, created_at"
)


class SqlFieldHistoryRepository(FieldHistoryRepository):
    """SQL implementation of FieldHistoryRepository using SQLAlchemy Core."""

    def __init__(self, connection: AsyncConnection):
        self.conn = connection

    @staticmethod
    def _coerce_created_at(created_at: str | datetime | None) -> datetime | None:
        """Normalise an entry's created_at to a datetime for binding.

        ``record_change`` writes back the persisted ``created_at`` as an ISO
        string, so a re-recorded (reused) instance arrives here as a string;
        parse it so the COALESCE bind stays a timestamp. Projection callers pass
        a ``datetime`` (the event's occurred_at); the contact dual-write passes
        ``None`` and falls through to the DB default.
        """
        if isinstance(created_at, str):
            return datetime.fromisoformat(created_at)
        return created_at

    @staticmethod
    def _parse_provenance(source: str | None) -> Provenance:
        if not source:
            return Provenance.SYSTEM
        try:
            return Provenance(source)
        except ValueError:
            return Provenance.SYSTEM

    def _row_to_entry(self, row) -> FieldHistoryEntry:  # type: ignore[no-untyped-def]
        return FieldHistoryEntry(
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            field_name=row.field_name,
            old_value=row.old_value,
            new_value=row.new_value,
            changed_by=row.changed_by,
            source=self._parse_provenance(row.source),
            event_id=row.event_id,
            id=row.id,
            created_at=row.created_at.isoformat() if row.created_at else None,
        )

    async def record_change(self, entry: FieldHistoryEntry) -> FieldHistoryEntry:
        """Record a field change.

        Uses ``INSERT ... ON CONFLICT DO NOTHING`` against the
        ``(event_id, entity_type, entity_id, field_name)`` unique index so that
        re-delivery of the same domain event never writes a duplicate row. On a
        conflict no row is returned and the entry is returned with ``id`` and
        ``created_at`` cleared (even if the caller reused an already-persisted
        instance), so the returned entry always reflects whether a row was written.
        Rows with a NULL ``event_id`` (e.g. the synchronous contact dual-write) are
        never deduplicated because PostgreSQL treats NULLs as distinct.
        """
        query = text(
            """
            INSERT INTO field_history
            (entity_type, entity_id, field_name, old_value, new_value,
             changed_by, source, event_id, created_at)
            VALUES (:entity_type, :entity_id, :field_name, :old_value, :new_value,
                    :changed_by, :source, :event_id, COALESCE(:created_at, now()))
            ON CONFLICT (event_id, entity_type, entity_id, field_name) DO NOTHING
            RETURNING id, created_at
            """
        )
        result = await self.conn.execute(
            query,
            {
                "entity_type": entry.entity_type,
                "entity_id": entry.entity_id,
                "field_name": entry.field_name,
                "old_value": entry.old_value,
                "new_value": entry.new_value,
                "changed_by": entry.changed_by,
                "source": entry.source.value,
                "event_id": entry.event_id,
                # When projecting a domain event the caller sets created_at to the
                # event's occurred_at so history reflects when the change actually
                # happened. The synchronous contact dual-write passes None and the
                # COALESCE falls through to the DB default (now()), unchanged.
                "created_at": self._coerce_created_at(entry.created_at),
            },
        )
        row = result.fetchone()
        if row is not None:
            entry.id = row.id
            entry.created_at = row.created_at.isoformat() if row.created_at else None
        else:
            # Conflict: this change was already recorded. Clear any pre-existing
            # metadata so a reused instance never reports a stale id/created_at.
            entry.id = None
            entry.created_at = None
        return entry

    async def record_multiple_changes(
        self, entries: list[FieldHistoryEntry]
    ) -> list[FieldHistoryEntry]:
        """Record multiple field changes."""
        return [await self.record_change(entry) for entry in entries]

    async def get_history_for_aggregate(
        self, root_type: str, root_id: int, limit: int = 50, offset: int = 0
    ) -> list[FieldHistoryEntry]:
        """Get paginated history for an aggregate root via its strategy."""
        strategy = get_aggregation_strategy(root_type)
        query = text(
            f"""
            SELECT {_SELECT_COLUMNS}
            FROM field_history
            WHERE {strategy.where_clause}
            ORDER BY created_at DESC, id DESC
            LIMIT :limit OFFSET :offset
            """
        )
        result = await self.conn.execute(
            query, {"root_id": root_id, "limit": limit, "offset": offset}
        )
        return [self._row_to_entry(row) for row in result.fetchall()]

    async def get_history_for_aggregate_count(
        self, root_type: str, root_id: int
    ) -> int:
        """Get the total history count for an aggregate root via its strategy."""
        strategy = get_aggregation_strategy(root_type)
        query = text(
            f"""
            SELECT COUNT(*) AS total
            FROM field_history
            WHERE {strategy.where_clause}
            """
        )
        result = await self.conn.execute(query, {"root_id": root_id})
        row = result.fetchone()
        return row.total if row else 0

    async def get_entity_history(
        self, entity_type: str, entity_id: int
    ) -> list[FieldHistoryEntry]:
        """Get field history for a single entity."""
        query = text(
            f"""
            SELECT {_SELECT_COLUMNS}
            FROM field_history
            WHERE entity_type = :entity_type AND entity_id = :entity_id
            ORDER BY created_at DESC, id DESC
            """
        )
        result = await self.conn.execute(
            query, {"entity_type": entity_type, "entity_id": entity_id}
        )
        return [self._row_to_entry(row) for row in result.fetchall()]

    async def get_field_history(
        self, entity_id: int, field_name: str, entity_type: str = "contact"
    ) -> list[FieldHistoryEntry]:
        """Get history for a specific field of an entity."""
        query = text(
            f"""
            SELECT {_SELECT_COLUMNS}
            FROM field_history
            WHERE entity_type = :entity_type AND entity_id = :entity_id
                  AND field_name = :field_name
            ORDER BY created_at DESC, id DESC
            """
        )
        result = await self.conn.execute(
            query,
            {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "field_name": field_name,
            },
        )
        return [self._row_to_entry(row) for row in result.fetchall()]

    async def get_changes_by_user(
        self, changed_by: str, limit: int = 50
    ) -> list[FieldHistoryEntry]:
        """Get changes made by a specific user."""
        query = text(
            f"""
            SELECT {_SELECT_COLUMNS}
            FROM field_history
            WHERE changed_by = :changed_by
            ORDER BY created_at DESC, id DESC
            LIMIT :limit
            """
        )
        result = await self.conn.execute(
            query, {"changed_by": changed_by, "limit": limit}
        )
        return [self._row_to_entry(row) for row in result.fetchall()]
