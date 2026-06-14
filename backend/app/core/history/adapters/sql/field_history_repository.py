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

        A malformed string falls back to ``None`` (DB default ``now()``) rather
        than raising, so a single bad timestamp can never fail the projection and
        dead-letter the event.
        """
        if isinstance(created_at, str):
            try:
                return datetime.fromisoformat(created_at)
            except ValueError:
                return None
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

    async def repoint_entity_history(
        self,
        old_entity_id: int,
        new_entity_id: int,
        entity_type: str,
        transaction: AsyncConnection,
    ) -> int:
        """Move an entity's top-level history rows onto another entity.

        Used by the contact merge to carry the source contact's
        ``entity_type = "contact"`` history onto the survivor so the survivor's
        aggregate history is complete. Sub-entity rows (methods, addresses, …) are
        deliberately NOT touched — they keep their own ids, which the merge already
        re-pointed to the survivor, so the contact aggregation strategy already
        picks them up.

        Implemented as copy-then-delete in a single statement so the
        ``(event_id, entity_type, entity_id, field_name)`` dedup index can drop any
        row the survivor already carries (``ON CONFLICT DO NOTHING`` is only
        available on ``INSERT``). The copy preserves ``event_id``, ``created_at``,
        ``source`` and ``changed_by`` so ordering and provenance survive. Both CTEs
        run from the same snapshot, so the delete removes the original source rows
        regardless of which the insert skipped. Idempotent: once the source's rows
        are gone a re-run copies and deletes nothing. Returns the rows moved.

        A no-op when ``old_entity_id == new_entity_id``: copying onto the same id
        conflicts on every row (so nothing is inserted) while the delete would wipe
        that entity's history, so the self-move is rejected to prevent data loss.
        """
        if old_entity_id == new_entity_id:
            return 0
        query = text(
            """
            WITH moved AS (
                INSERT INTO field_history
                    (entity_type, entity_id, field_name, old_value, new_value,
                     changed_by, source, event_id, created_at)
                SELECT entity_type, :new_entity_id, field_name, old_value,
                       new_value, changed_by, source, event_id, created_at
                FROM field_history
                WHERE entity_type = :entity_type AND entity_id = :old_entity_id
                ON CONFLICT (event_id, entity_type, entity_id, field_name)
                    DO NOTHING
                RETURNING 1
            ),
            deleted AS (
                DELETE FROM field_history
                WHERE entity_type = :entity_type AND entity_id = :old_entity_id
                RETURNING 1
            )
            SELECT
                (SELECT count(*) FROM moved) AS moved_count,
                (SELECT count(*) FROM deleted) AS deleted_count
            """
        )
        result = await transaction.execute(
            query,
            {
                "new_entity_id": new_entity_id,
                "old_entity_id": old_entity_id,
                "entity_type": entity_type,
            },
        )
        row = result.fetchone()
        return int(row.moved_count) if row else 0

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
