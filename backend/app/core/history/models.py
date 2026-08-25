"""Domain models, repository interface, and aggregation strategies for history.

This is the entity-agnostic foundation shared by the contacts and journals domains.
A history entry records a single field-level change to some entity, identified by an
``(entity_type, entity_id)`` pair, with provenance and (optionally) the originating
domain ``event_id`` used to make projection idempotent.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from core_shared.models.history import Provenance
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.tasks.models.events import CONTACT_FIELD_PREFIX

#: The field names a create and a hard delete are recorded under.
#:
#: The journal marker convention, which a task follows (ITER18-003 Phase 6).
#: Named here rather than spelt at each site because the contact aggregation
#: predicate below now **reads** the delete marker the projection **writes**, and
#: a format with two readers is one that can drift.
CREATED_MARKER = "__created__"
DELETED_MARKER = "__deleted__"


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
        entity_label: str | None = None,
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
        # The name of the entity this row is *about*, resolved at read time and
        # never stored. It exists for one case: a row whose subject is not the
        # aggregate being read. A task's contact-membership row is filed under
        # the task and surfaces on the *contact's* feed, where both of its
        # values are the reader's own id and nothing names the commitment. Left
        # ``None`` on every read where the row names itself.
        self.entity_label = entity_label


def resolve_task_label(
    rows: Sequence[tuple[str, str | None, str | datetime | None]],
) -> str | None:
    """Name a task from its own history rows, most recent wording first.

    ``rows`` is ``(field_name, new_value, created_at)`` for one task, in any
    order. A task is named by the last thing it was called: its newest ``text``
    row, falling back to the ``__created__`` marker the projection opens every
    task's history with.

    **Resolved from history rather than from ``tasks``**, and that is the point
    rather than a shortcut. A task is hard-deleted, so the entry that most needs
    a name — the one a person is left with after a commitment they were part of
    was deleted — is exactly the one a lookup against the live table cannot
    answer. These rows are permanent.

    Returns ``None`` when nothing names it, which is a real state and not an
    error: projection lags the write, so a task linked a second ago has no rows
    yet. The surface renders its unnamed wording rather than a placeholder.
    """
    named = [
        (created_at, value)
        for field_name, value, created_at in rows
        if field_name in (CREATED_MARKER, "text") and value is not None
    ]
    if not named:
        return None
    # A missing timestamp sorts first rather than dropping the row: an unnamed
    # entry is worse than one named from a row whose order is uncertain.
    return max(named, key=lambda row: _sort_key(row[0]))[1]


def _sort_key(created_at: str | datetime | None) -> datetime:
    """Order a history row by when it happened, tolerating an absent stamp."""
    if created_at is None:
        return datetime.min.replace(tzinfo=UTC)
    if isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at)
        except ValueError:
            return datetime.min.replace(tzinfo=UTC)
    if created_at.tzinfo is None:
        return created_at.replace(tzinfo=UTC)
    return created_at


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
    every ``(entity_type, entity_id)`` belonging to the root, parameterised on the
    ``:root_id`` bind parameter.

    A second bind, ``:root_id_text``, carries the same id as text. Both are always
    supplied by the repository. It exists because the contact predicate has to build
    a ``field_name`` from the root id, and reusing the integer bind inside a string
    concatenation would ask PostgreSQL to infer two types for one parameter.
    """

    root_type: str
    where_clause: str


# The contact aggregation predicate: the contact itself, all related sub-entities,
# and the rows recording a task's membership of this person.
# This is the generalisation of the previously hard-coded contact history WHERE clause.
#
# **The task branch keys on the field name, never on a join.** Task events project
# onto the *task* (``entity_type='task'``, ``entity_id=task_id``), and a contact's
# membership of one is written under ``contact:{id}`` (ITER18-003 Phase 5), so a
# contact's own rows would never see it. Reaching those rows through
# ``task_contacts`` instead would be the obvious design and is the wrong one: the
# link row cascades away when the task is hard-deleted and disappears when the task
# is unlinked, so a joined predicate would quietly erase what the feed had already
# recorded. This is the same argument the ``task`` predicate below carries about
# the ``tasks`` table, one level out.
#
# It is deliberately **equality**, not a prefix match: ``contact:1`` must not match
# ``contact:12``, which a ``LIKE 'contact:%'`` would.
#
# The link rows are reached, **and the delete marker of a task they name**. A
# task's text, status and retarget rows belong to its own history — the
# specification's *Where tasks appear* allows two working surfaces, and a person's
# page is not a third one (ITER18-003 open decision 3) — but a hard delete is not
# progress, it is the end of the thing the record points at. Without it the feed
# keeps "linked to a task" forever for a task that no longer exists, and the only
# entry a person has about it reads as a commitment still standing.
#
# The delete branch is narrowed by **history itself**, not by ``task_contacts``:
# the link row is the only record of the link that survives the task, and the
# subquery is over the same permanent table the outer predicate reads. It matches
# a task the contact was *ever* linked to, including one they were unlinked from
# before it was deleted — the unlink entry already stands above it, and the pair
# reads as a sequence rather than as a contradiction.
#
# **This branch carries no owner filter, and the assumption is stated rather than
# left implicit.** Every other branch reaches contact-domain rows, which have no
# owner: ``contacts`` has no ``user_id`` column and neither does the read that
# serves this predicate. Task rows are the one kind that *does* carry one
# (``field_history.user_id``, stamped by ``HistoryService._owner_for``), so in a
# multi-tenant deployment this branch would surface another user's task on a
# shared contact's feed. It cannot be narrowed here — the strategy is
# parameterised on the root id alone, and the contact history read has no user to
# thread through — so scoping it means giving the contact domain an owner first.
# Recorded as a follow-up on ITER18-003 Phase 9.
_CONTACT_AGGREGATION_WHERE = f"""
    (entity_type = 'contact' AND entity_id = :root_id)
    OR (entity_type = 'contact_method' AND entity_id IN (SELECT id FROM contact_methods WHERE contact_id = :root_id))
    OR (entity_type = 'contact_address' AND entity_id IN (SELECT id FROM contact_addresses WHERE contact_id = :root_id))
    OR (entity_type = 'contact_note' AND entity_id IN (SELECT id FROM contact_notes WHERE contact_id = :root_id))
    OR (entity_type = 'contact_tag' AND entity_id IN (SELECT tag_id FROM contact_tags WHERE contact_id = :root_id))
    OR (entity_type = 'contact_relationship' AND entity_id IN (SELECT id FROM contact_relationships WHERE from_contact_id = :root_id OR to_contact_id = :root_id))
    OR (entity_type = 'contact_important_date' AND entity_id IN (SELECT id FROM contact_important_dates WHERE contact_id = :root_id))
    OR (entity_type = 'contact_summary' AND entity_id = :root_id)
    OR (entity_type = 'task' AND field_name = '{CONTACT_FIELD_PREFIX}' || :root_id_text)
    OR (entity_type = 'task' AND field_name = '{DELETED_MARKER}' AND entity_id IN (
        SELECT link.entity_id FROM field_history AS link
        WHERE link.entity_type = 'task'
          AND link.field_name = '{CONTACT_FIELD_PREFIX}' || :root_id_text))
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
    async def get_task_labels(self, task_ids: Sequence[int]) -> dict[int, str]:
        """Name each of these tasks from its own history rows.

        Resolved from ``field_history`` rather than from ``tasks`` because a
        task is hard-deleted and the entry that most needs a name is the one it
        leaves behind. A task with nothing naming it yet is **absent** from the
        result rather than mapped to ``None``: projection lags the write, so
        that is an ordinary state and the caller renders its unnamed wording.

        One query for the whole page — a contact's feed can hold many task rows.
        """

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
