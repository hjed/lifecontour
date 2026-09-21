"""Reconciling a contact's sub-entity lists against what is stored.

The whole-contact save takes the *whole desired state* of a contact's methods,
addresses, notes and important dates. Replacing that state by deleting every
row and re-inserting it loses the one thing the activity feed needs: which row
an edit belongs to. These helpers pair what was submitted with what is stored,
so a matched row can be updated in place and published as the edit it is
(issue #1524).

Everything here is pure: no database, no events. The service decides what to do
with a :class:`Reconciliation`; these functions only decide what matches what,
and what moved.
"""

from collections.abc import Callable, Hashable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from core_shared.models.contacts.entities import ImportantDate

# ``{field: (old, new)}`` — the shape the history projection reads, where the
# two-element tuple is what its ``len(change) == 2`` guard is asking for.
type ChangedFields = dict[str, tuple[Any, Any]]


class SubEntity(Protocol):
    """A contact sub-entity: a row of its own, with its own id."""

    id: int | None


type NaturalKey[T] = Callable[[T], Hashable]


@dataclass(frozen=True)
class Reconciliation[T: SubEntity]:
    """What a submitted list means for the rows already stored.

    ``updates`` pairs each stored row with the submission that claimed it, in
    the order the submission arrived.
    """

    inserts: list[T]
    updates: list[tuple[T, T]]
    deletions: list[T]


def reconcile[T: SubEntity](
    existing: Sequence[T] | None,
    incoming: Sequence[T] | None,
    *,
    natural_key: NaturalKey[T] | None = None,
) -> Reconciliation[T]:
    """Pair ``incoming`` against ``existing``.

    Ids are matched first and across the whole list, so a submission that names
    a row always claims that row rather than losing it to a natural-key match
    made earlier in the list. What is left over is then matched on
    ``natural_key``, in order within each key group, for callers whose
    submissions carry no ids — MCP sends important dates that way. Without a
    ``natural_key`` an id-less submission is always an insert.

    A submitted id matching no stored row is an insert too, and is never
    matched on its natural key: it cannot be an edit of a row that is not
    there, nor of one it did not name. The same holds for a second submission
    naming an id another has already claimed.
    """
    stored = list(existing or [])
    submitted = list(incoming or [])

    by_id = {item.id: item for item in stored if item.id is not None}
    claimed: set[int] = set()
    updates: list[tuple[T, T]] = []
    unmatched: list[T] = []

    for item in submitted:
        match = by_id.get(item.id) if item.id is not None else None
        if match is None or id(match) in claimed:
            unmatched.append(item)
            continue
        claimed.add(id(match))
        updates.append((match, item))

    if natural_key is not None and unmatched:
        by_key: dict[Hashable, list[T]] = {}
        for item in stored:
            if id(item) not in claimed:
                by_key.setdefault(natural_key(item), []).append(item)

        still_unmatched: list[T] = []
        for item in unmatched:
            # Only a submission with no id is matched on its natural key. One
            # naming an id has said which row it is: an id that is stale, or
            # already claimed, is not some other row under a different name.
            group = by_key.get(natural_key(item)) if item.id is None else None
            if not group:
                still_unmatched.append(item)
                continue
            match = group.pop(0)
            claimed.add(id(match))
            updates.append((match, item))
        unmatched = still_unmatched

    # The id pass runs over the whole list before the natural-key pass, so put
    # the pairs back in the order their submissions arrived.
    position = {id(item): index for index, item in enumerate(submitted)}
    updates.sort(key=lambda pair: position[id(pair[1])])

    deletions = [item for item in stored if id(item) not in claimed]

    return Reconciliation(inserts=unmatched, updates=updates, deletions=deletions)


def diff_fields(
    existing: object, incoming: object, fields: Sequence[str]
) -> ChangedFields:
    """Diff two sub-entities into ``{field: (old, new)}`` pairs.

    Only ``fields`` are compared, so ids and timestamps — which move on their
    own — are never reported as somebody's edit. Enums are compared and
    reported by value, because the result is carried in an outbox event payload
    and has to survive JSON.
    """
    changed: ChangedFields = {}
    for name in fields:
        old = _serialisable(getattr(existing, name))
        new = _serialisable(getattr(incoming, name))
        if old != new:
            changed[name] = (old, new)
    return changed


def prefixed(prefix: str, entity_id: int, changed: ChangedFields) -> ChangedFields:
    """Key a sub-entity's diff for the aggregate ``ContactUpdated`` event.

    ``"method_5_value"`` — the format
    ``HistoryService._SUBENTITY_FIELD_RE`` decodes back to the row it belongs
    to. This is the only place it is written.
    """
    return {f"{prefix}_{entity_id}_{name}": pair for name, pair in changed.items()}


def important_date_key(date: ImportantDate) -> Hashable:
    """What makes two important dates the same date.

    A contact has at most one birthday, so a submitted birthday is an edit of
    the stored one; two work anniversaries are told apart by their position in
    the submitted list.
    """
    return (date.date_type.value, date.custom_date_type_id)


def _serialisable(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


# The prefixes the history projection knows. Important dates are absent by
# design: their edits travel as ``ImportantDateUpdated``, which carries
# ``changed_fields`` of its own.
METHOD_PREFIX = "method"
ADDRESS_PREFIX = "address"
NOTE_PREFIX = "note"

# The fields a user can edit on each sub-entity — everything else on the
# dataclass is an id, a timestamp or a value derived from a foreign key.
METHOD_FIELDS: Sequence[str] = ("method_type", "value", "label", "is_primary")
ADDRESS_FIELDS: Sequence[str] = (
    "label",
    "street_line_1",
    "street_line_2",
    "locality",
    "region",
    "postal_code",
    "country_code",
    "is_primary",
)
NOTE_FIELDS: Sequence[str] = ("content",)
IMPORTANT_DATE_FIELDS: Sequence[str] = (
    "date_type",
    "precision",
    "year",
    "month",
    "day",
    "custom_date_type_id",
)
