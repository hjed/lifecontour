"""Domain models, repository interface, and aggregation strategies for history.

This is the entity-agnostic foundation shared by the contacts and journals domains.
A history entry records a single field-level change to some entity, identified by an
``(entity_type, entity_id)`` pair, with provenance and (optionally) the originating
domain ``event_id`` used to make projection idempotent.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from core_shared.models.history import Provenance
from sqlalchemy.ext.asyncio import AsyncConnection


class FieldHistoryEntry:
    """Field-level change history entry for any entity."""

    def __init__(
        self,
        entity_type: str,
        entity_id: int,
        field_name: str,
        old_value: str | None = None,
        new_value: str | None = None,
        changed_by: str | None = None,
        source: Provenance = Provenance.SYSTEM,
        event_id: str | None = None,
        id: int | None = None,
        created_at: str | datetime | None = None,
        user_id: str | None = None,
    ):
        self.id = id
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.field_name = field_name
        self.old_value = old_value
        self.new_value = new_value
        self.changed_by = changed_by
        self.source = source
        self.event_id = event_id
        self.created_at = created_at
        # Who owns the entity this row describes, for the reads that cannot ask
        # the entity itself. Set for task rows only — see ``_owner_for`` in the
        # history service for why the column is deliberately half-populated.
        # Do not confuse it with ``changed_by``, which records who *acted*: a
        # row can be owned by one person and changed by an integration.
        self.user_id = user_id


class UnknownAggregationRootError(ValueError):
    """Raised when history is requested for an unregistered aggregation root type."""

    def __init__(self, root_type: str):
        self.root_type = root_type
        super().__init__(
            f"No history aggregation strategy registered for root type: {root_type!r}"
        )


@dataclass(frozen=True)
class HistoryAggregationStrategy:
    """Resolves the set of history rows that belong to an aggregate root.

    ``where_clause`` is a SQL predicate (over the ``field_history`` table) that selects
    every ``(entity_type, entity_id)`` belonging to the root, parameterised on a single
    ``:root_id`` bind parameter.
    """

    root_type: str
    where_clause: str


# The contact aggregation predicate: the contact itself plus all related sub-entities.
# This is the generalisation of the previously hard-coded contact history WHERE clause.
_CONTACT_AGGREGATION_WHERE = """
    (entity_type = 'contact' AND entity_id = :root_id)
    OR (entity_type = 'contact_method' AND entity_id IN (SELECT id FROM contact_methods WHERE contact_id = :root_id))
    OR (entity_type = 'contact_address' AND entity_id IN (SELECT id FROM contact_addresses WHERE contact_id = :root_id))
    OR (entity_type = 'contact_note' AND entity_id IN (SELECT id FROM contact_notes WHERE contact_id = :root_id))
    OR (entity_type = 'contact_tag' AND entity_id IN (SELECT tag_id FROM contact_tags WHERE contact_id = :root_id))
    OR (entity_type = 'contact_relationship' AND entity_id IN (SELECT id FROM contact_relationships WHERE from_contact_id = :root_id OR to_contact_id = :root_id))
    OR (entity_type = 'contact_important_date' AND entity_id IN (SELECT id FROM contact_important_dates WHERE contact_id = :root_id))
    OR (entity_type = 'contact_summary' AND entity_id = :root_id)
"""


_AGGREGATION_STRATEGIES: dict[str, HistoryAggregationStrategy] = {}


def register_aggregation_strategy(strategy: HistoryAggregationStrategy) -> None:
    """Register a per-root aggregation strategy."""
    _AGGREGATION_STRATEGIES[strategy.root_type] = strategy


def get_aggregation_strategy(root_type: str) -> HistoryAggregationStrategy:
    """Return the aggregation strategy for ``root_type`` or raise if unknown."""
    try:
        return _AGGREGATION_STRATEGIES[root_type]
    except KeyError:
        raise UnknownAggregationRootError(root_type) from None


register_aggregation_strategy(
    HistoryAggregationStrategy(
        root_type="contact",
        where_clause=_CONTACT_AGGREGATION_WHERE,
    )
)


# The journal aggregation predicate. The history projection tags every journal,
# route, gear, and type change to the journal itself (entity_type='journal',
# entity_id=journal_id) — route/gear ids are UUIDs and cannot live in the integer
# entity_id column, and tagging to the journal keeps route/gear history readable
# after the route/gear row is deleted — so the predicate keys on the journal
# directly with no joins.
_JOURNAL_AGGREGATION_WHERE = """
    entity_type = 'journal' AND entity_id = :root_id
"""


register_aggregation_strategy(
    HistoryAggregationStrategy(
        root_type="journal",
        where_clause=_JOURNAL_AGGREGATION_WHERE,
    )
)


# The task aggregation predicate. Every task event projects with
# entity_type='task', entity_id=task_id — a task has no sub-entities, unlike a
# contact — so this keys on the task directly with no joins.
#
# **It deliberately does not reach through the ``tasks`` table.** Tasks are
# hard-deleted, and a task's history has to stay readable afterwards: joining to
# a row that may be gone would silently empty a deleted task's feed, which is
# the surface the ``__deleted__`` marker is written to. Ownership is carried on
# the rows instead (``field_history.user_id``) and checked by
# ``TaskHistoryService`` before this predicate ever runs.
_TASK_AGGREGATION_WHERE = """
    entity_type = 'task' AND entity_id = :root_id
"""


register_aggregation_strategy(
    HistoryAggregationStrategy(
        root_type="task",
        where_clause=_TASK_AGGREGATION_WHERE,
    )
)


class FieldHistoryRepository(ABC):
    """Repository interface for entity-agnostic field-level change history."""

    @abstractmethod
    async def record_change(self, entry: FieldHistoryEntry) -> FieldHistoryEntry:
        """Record a field change. Idempotent on ``(event_id, entity_type, entity_id, field_name)``."""

    @abstractmethod
    async def get_history_for_aggregate(
        self, root_type: str, root_id: int, limit: int = 50, offset: int = 0
    ) -> list[FieldHistoryEntry]:
        """Get paginated history for an aggregate root using its strategy."""

    @abstractmethod
    async def get_history_for_aggregate_count(
        self, root_type: str, root_id: int
    ) -> int:
        """Get the total history count for an aggregate root using its strategy."""

    @abstractmethod
    async def get_entity_history(
        self, entity_type: str, entity_id: int
    ) -> list[FieldHistoryEntry]:
        """Get field history for a single entity."""

    @abstractmethod
    async def get_history_owner(self, entity_type: str, entity_id: int) -> str | None:
        """Return the owner recorded on an entity's history rows, if any.

        The answer to *"whose history is this?"* for a read that cannot ask the
        entity, because the entity may no longer exist. Only task rows carry an
        owner today (see ``field_history.user_id``), so this returns ``None``
        for a journal or a contact — and also for an entity whose events have
        not been projected yet, which a caller must distinguish from "not
        yours" rather than treat as a refusal.
        """

    @abstractmethod
    async def repoint_entity_history(
        self,
        old_entity_id: int,
        new_entity_id: int,
        entity_type: str,
        transaction: AsyncConnection,
    ) -> int:
        """Re-point an entity's top-level history rows onto another entity.

        Moves every ``(entity_type, old_entity_id)`` row to ``new_entity_id``,
        respecting the ``(event_id, entity_type, entity_id, field_name)`` dedup
        index (``ON CONFLICT DO NOTHING``). Idempotent and returns the number of
        rows moved. Used by the contact merge to carry the source's history onto
        the survivor.
        """
