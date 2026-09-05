"""SQL implementation of the entity-agnostic FieldHistoryRepository."""

from collections.abc import Sequence
from datetime import UTC, datetime

from core_shared.models.history import Provenance
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.history.models import (
    CREATED_MARKER,
    FieldHistoryEntry,
    FieldHistoryRepository,
    get_aggregation_strategy,
    resolve_task_label,
)
from app.core.tasks.models.events import contact_field_name

_SELECT_COLUMNS = (
    "id, entity_type, entity_id, field_name, old_value, new_value, "
    "changed_by, source, event_id, created_at, user_id"
)

#: The ``entity_type`` a task's history rows carry. Task events project onto the
#: task itself, so a person's membership of one is a ``task`` row under a
#: ``contact:{id}`` field name rather than a row of that person's own.
_TASK_ENTITY_TYPE = "task"


class SqlFieldHistoryRepository(FieldHistoryRepository):
    """SQL implementation of FieldHistoryRepository using SQLAlchemy Core."""

    def __init__(self, connection: AsyncConnection):
        self.conn = connection

    @staticmethod
    def _coerce_created_at(created_at: str | datetime | None) -> datetime | None:
        """Normalise an entry's created_at to a UTC-aware datetime for binding.

        ``record_change`` writes back the persisted ``created_at`` as an ISO
        string, so a re-recorded (reused) instance arrives here as a string;
        parse it so the COALESCE bind stays a timestamp. Projection callers pass
        a ``datetime`` (the event's occurred_at); the contact dual-write passes
        ``None`` and falls through to the DB default.

        A malformed string falls back to ``None`` (DB default ``now()``) rather
        than raising, so a single bad timestamp can never fail the projection and
        dead-letter the event.

        **A naive value is read as UTC rather than passed through.**
        ``created_at`` is a ``timestamptz``, so PostgreSQL resolves a naive bind
        against the *session's* timezone and silently moves the change by the
        server's UTC offset — a history line landing on the wrong day, or hours
        out of order against rows written by a session configured differently.
        The projection is handed naive timestamps in the ordinary case:
        ``outbox_events.occurred_at`` is a ``timestamp`` *without* time zone, so
        the offset is gone before the relay ever serialises the row. Everything
        here stamps ``datetime.now(tz=UTC)``, so a naive one is UTC, and saying
        so is the difference between recording that fact and re-deriving it from
        whatever the database happens to be set to.
        """
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at)
            except ValueError:
                return None
        if created_at is not None and created_at.tzinfo is None:
            return created_at.replace(tzinfo=UTC)
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
            user_id=row.user_id,
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
             changed_by, source, event_id, created_at, user_id)
            VALUES (:entity_type, :entity_id, :field_name, :old_value, :new_value,
                    :changed_by, :source, :event_id, COALESCE(:created_at, now()),
                    :user_id)
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
                # Only task rows carry one; every other producer passes None.
                "user_id": entry.user_id,
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
                     changed_by, source, event_id, created_at, user_id)
                SELECT entity_type, :new_entity_id, field_name, old_value,
                       new_value, changed_by, source, event_id, created_at,
                       user_id
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

    async def repoint_contact_task_history(
        self,
        old_contact_id: int,
        new_contact_id: int,
        transaction: AsyncConnection,
    ) -> int:
        """Move a contact's task records onto another contact by field name.

        **Copy-then-delete, for the reason its neighbour is.** ``ON CONFLICT``
        exists only on ``INSERT``, and the conflict is real here rather than
        theoretical: one action can put both people on a task, writing a row per
        person under a single ``event_id``, and the moment the absorbed row
        takes the survivor's field name the two agree on all four columns of
        ``ux_field_history_event_dedup``. An ``UPDATE`` would raise and fail the
        whole merge. Both CTEs run from one snapshot, so the delete removes
        every source row regardless of which the insert skipped, and the delete
        cannot reach the copies — they carry the *new* field name.

        **Every column is carried over, and two of them are load-bearing.**
        ``user_id`` because both task branches of the contact predicate are
        owner-scoped: a row that lost its owner would not surface on the wrong
        feed, it would vanish from every feed, which is a harder failure to
        notice than the one this method exists to fix. ``event_id`` because
        ``TaskHistoryBackfill`` treats any row bearing an event's id as proof
        that event was projected — drop it and the next application start would
        rebuild, under the absorbed contact's name, every row this just moved.

        The field names are built with :func:`contact_field_name` rather than
        interpolated, because the format now has four readers and one of them is
        the predicate that decides whether the moved row is readable at all.

        A no-op when the two ids are equal: the copy would conflict on every row
        while the delete removed the originals, so a self-move would silently
        erase a person's whole task trail. The merge rejects a self-merge long
        before it reaches here; this is for the caller that does not.
        """
        if old_contact_id == new_contact_id:
            return 0
        query = text(
            """
            WITH moved AS (
                INSERT INTO field_history
                    (entity_type, entity_id, field_name, old_value, new_value,
                     changed_by, source, event_id, created_at, user_id)
                SELECT entity_type, entity_id, :new_field_name, old_value,
                       new_value, changed_by, source, event_id, created_at,
                       user_id
                FROM field_history
                WHERE entity_type = :entity_type AND field_name = :old_field_name
                ON CONFLICT (event_id, entity_type, entity_id, field_name)
                    DO NOTHING
                RETURNING 1
            ),
            deleted AS (
                DELETE FROM field_history
                WHERE entity_type = :entity_type AND field_name = :old_field_name
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
                "entity_type": _TASK_ENTITY_TYPE,
                "old_field_name": contact_field_name(old_contact_id),
                "new_field_name": contact_field_name(new_contact_id),
            },
        )
        row = result.fetchone()
        return int(row.moved_count) if row else 0

    async def get_history_for_aggregate(
        self,
        root_type: str,
        root_id: int,
        limit: int = 50,
        offset: int = 0,
        *,
        reader_user_id: str | None = None,
    ) -> list[FieldHistoryEntry]:
        """Get paginated history for an aggregate root via its strategy.

        ``:root_id``, ``:root_id_text`` and ``:reader_user_id`` are **all** bound,
        whether or not the strategy names them, so the listing and the count
        cannot disagree about what a predicate may use.

        ``:root_id_text`` exists because the contact predicate builds a
        ``field_name`` from the root id, and reusing the integer bind inside a
        string concatenation would ask PostgreSQL to infer two types for one
        parameter. ``:reader_user_id`` scopes the owned rows the contact
        aggregate reaches — a task's — and defaults to ``None``, which matches
        nothing: forgetting to say who is asking costs those rows rather than
        exposing them.
        """
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
            query,
            {
                "root_id": root_id,
                "root_id_text": str(root_id),
                "reader_user_id": reader_user_id,
                "limit": limit,
                "offset": offset,
            },
        )
        return [self._row_to_entry(row) for row in result.fetchall()]

    async def get_history_for_aggregate_count(
        self, root_type: str, root_id: int, *, reader_user_id: str | None = None
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
        result = await self.conn.execute(
            query,
            {
                "root_id": root_id,
                "root_id_text": str(root_id),
                "reader_user_id": reader_user_id,
            },
        )
        row = result.fetchone()
        return row.total if row else 0

    async def get_task_labels(
        self, task_ids: Sequence[int], *, reader_user_id: str | None = None
    ) -> dict[int, str]:
        """Name each task from its own history rows, in one query.

        Only the two naming field names are fetched, and the ordering is done in
        Python by :func:`resolve_task_label` rather than in SQL: the rule for
        which row names a task — newest reword, else the creation marker, with a
        blank reword falling through — is a product decision, and a
        ``DISTINCT ON`` re-spelling it would be a second definition of it.
        """
        if not task_ids:
            return {}

        query = text(
            """
            SELECT entity_id, field_name, new_value, created_at
            FROM field_history
            WHERE entity_type = 'task'
              AND user_id = :reader_user_id
              AND field_name IN (:created_marker, 'text')
              AND entity_id = ANY(:task_ids)
            """
        )
        result = await self.conn.execute(
            query,
            {
                "created_marker": CREATED_MARKER,
                "task_ids": list(task_ids),
                "reader_user_id": reader_user_id,
            },
        )

        rows_by_task: dict[int, list[tuple[str, str | None, datetime | None]]] = {}
        for row in result.fetchall():
            rows_by_task.setdefault(row.entity_id, []).append(
                (row.field_name, row.new_value, row.created_at)
            )

        labels = {
            task_id: resolve_task_label(rows) for task_id, rows in rows_by_task.items()
        }
        return {
            task_id: label for task_id, label in labels.items() if label is not None
        }

    async def get_history_owner(self, entity_type: str, entity_id: int) -> str | None:
        """Return the owner recorded on an entity's history rows, if any.

        One row is enough: every row an entity's events project carries the same
        owner, because the owner comes off the payload of an event the owner's
        own writes produced. ``LIMIT 1`` over the ``(entity_type, entity_id)``
        index is therefore the whole question, and it stays answerable after the
        entity itself has been hard-deleted — which is the only reason the
        column exists.

        ``None`` means *no row carries an owner*, which is two different
        situations the caller has to tell apart: rows exist but predate the
        column (or belong to a domain that does not stamp it), or the projection
        has not caught up with a change made moments ago. Neither is "not
        yours", so this must not be treated as a refusal on its own.
        """
        query = text(
            """
            SELECT user_id
            FROM field_history
            WHERE entity_type = :entity_type
              AND entity_id = :entity_id
              AND user_id IS NOT NULL
            LIMIT 1
            """
        )
        result = await self.conn.execute(
            query, {"entity_type": entity_type, "entity_id": entity_id}
        )
        row = result.fetchone()
        return str(row.user_id) if row else None

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
