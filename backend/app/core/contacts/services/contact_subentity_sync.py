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

from collections.abc import Callable, Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Protocol

from core_shared.models.contacts.entities import (
    Contact,
    ContactAddress,
    ContactMethod,
    ContactNote,
    ImportantDate,
    MethodType,
)
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)

# ``{field: (old, new)}`` — the shape the history projection reads, where the
# two-element tuple is what its ``len(change) == 2`` guard is asking for.
type ChangedFields = dict[str, tuple[Any, Any]]


class SubEntity(Protocol):
    """A contact sub-entity: a row of its own, belonging to one contact."""

    id: int | None
    contact_id: int


type NaturalKey[T] = Callable[[T], Hashable]

# The unique-index keys a row occupies while it reads as it does - for a
# method, ``("email", "ann@example.com")`` and, if it is primary,
# ``("primary", "email")``.
type UniqueClaims[T] = Callable[[T], frozenset[Hashable]]


@dataclass(frozen=True)
class Reconciliation[T: SubEntity]:
    """What a submitted list means for the rows already stored.

    ``updates`` pairs each stored row with the submission that claimed it, in
    an order the database can apply one row at a time. ``recreated`` pairs are
    edits too, but ones no order can apply in place - one side of a swap of
    unique values - so the stored row is deleted with the deletions and the
    submission inserted with the inserts, while the pairing is kept so the edit
    can still be reported.
    """

    inserts: list[T]
    updates: list[tuple[T, T]]
    deletions: list[T]
    recreated: list[tuple[T, T]] = field(default_factory=list)


def reconcile[T: SubEntity](
    existing: Sequence[T] | None,
    incoming: Sequence[T] | None,
    *,
    natural_key: NaturalKey[T] | None = None,
    unique_claims: UniqueClaims[T] | None = None,
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

    With ``unique_claims``, ``updates`` come back in an order the database can
    apply one row at a time; see :func:`_order_around_unique_keys`.
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

    recreated: list[tuple[T, T]] = []
    if unique_claims is not None and updates:
        updates, recreated = _order_around_unique_keys(updates, unique_claims)

    return Reconciliation(
        inserts=unmatched, updates=updates, deletions=deletions, recreated=recreated
    )


def _order_around_unique_keys[T](
    updates: list[tuple[T, T]], claims: UniqueClaims[T]
) -> tuple[list[tuple[T, T]], list[tuple[T, T]]]:
    """Order in-place updates so none takes a unique value another still holds.

    Postgres checks a non-deferrable unique index row by row, and these indexes
    cannot be deferred - they are partial. So an update that takes a value
    (makes a method primary, makes a date the birthday, gives a row an email)
    must run after the update that lets it go, or a valid final state is
    refused for the order the list happened to be in. The delete-all save
    never met this: every row was gone before any was written.

    Updates are taken in submitted order whenever nothing still pending holds
    what they take. Only values can form a cycle - two rows swapping emails -
    since "at most one primary" or "one birthday" is only ever let go by one
    row and taken by another. A cycle is broken by returning its first member
    to be re-created instead: its value is released in the deletion phase and
    taken back in the insert phase, around the updates. Nothing references a
    method row by id, so re-creating one loses no link, and the pairing is kept
    so its edit is still reported - under the id the row has afterwards.

    Returns the ordered updates and the ones to re-create.
    """
    gains = [claims(new) - claims(old) for old, new in updates]
    losses = [claims(old) - claims(new) for old, new in updates]

    remaining = list(range(len(updates)))
    ordered: list[int] = []
    recreated: list[int] = []
    while remaining:
        ready = next(
            (
                i
                for i in remaining
                if not any(gains[i] & losses[j] for j in remaining if j != i)
            ),
            None,
        )
        if ready is None:
            ready = remaining[0]
            recreated.append(ready)
        else:
            ordered.append(ready)
        remaining.remove(ready)

    return [updates[i] for i in ordered], [updates[i] for i in recreated]


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


def method_unique_claims(method: ContactMethod) -> frozenset[Hashable]:
    """The unique indexes a method occupies.

    ``ix_contact_methods_primary_unique`` - one primary per type - and
    ``ix_contact_methods_email_unique``, on ``LOWER(BTRIM(value))`` for emails,
    so the value is normalised the way the index normalises it.
    """
    keys: set[Hashable] = set()
    if method.is_primary:
        keys.add(("primary", method.method_type.value))
    if method.method_type == MethodType.EMAIL:
        keys.add(("email", method.value.strip().lower()))
    return frozenset(keys)


def important_date_unique_claims(date: ImportantDate) -> frozenset[Hashable]:
    """``uq_contact_birthday``: a contact has at most one birthday."""
    if date.date_type == ImportantDateType.BIRTHDAY:
        return frozenset({("birthday",)})
    return frozenset()


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
METHOD_FIELDS: Sequence[str] = (
    "method_type",
    "value",
    "label",
    "is_primary",
    "is_archived",
)
ADDRESS_FIELDS: Sequence[str] = (
    "label",
    "street_line_1",
    "street_line_2",
    "locality",
    "region",
    "postal_code",
    "country_code",
    "is_primary",
    "is_archived",
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


# How much of a note the aggregate row keeps - the same cut ContactNoteAdded
# makes in its own payload.
NOTE_RENDER_LIMIT = 100


def render_method(method: ContactMethod) -> str:
    """``email:ann@example.com``."""
    return f"{method.method_type.value}:{method.value}"


def render_address(address: ContactAddress) -> str:
    """The address's populated lines, comma separated."""
    parts = [
        address.street_line_1,
        address.street_line_2,
        address.locality,
        address.region,
        address.postal_code,
        address.country_code,
    ]
    return ", ".join(str(p) for p in parts if p) or "Unknown Address"


def render_note(note: ContactNote) -> str:
    """The note's words, cut at :data:`NOTE_RENDER_LIMIT`."""
    if len(note.content) <= NOTE_RENDER_LIMIT:
        return note.content
    return note.content[:NOTE_RENDER_LIMIT] + "…"


def render_important_date(date: ImportantDate) -> str:
    """``birthday:1990-03-09`` - ISO 8601, truncated to the date's precision.

    A day and month with no year is ``--03-09``, the standard's own form for
    it; a custom type is named by its own label, since ``custom`` alone would
    make two different custom dates read the same.
    """
    kind = date.date_type.value
    if date.date_type == ImportantDateType.CUSTOM:
        kind = f"custom({date.custom_date_type_name or date.custom_date_type_id})"

    if date.precision == DatePrecision.FULL:
        when = f"{date.year:04d}-{date.month:02d}-{date.day:02d}"
    elif date.precision == DatePrecision.DAY_MONTH:
        when = f"--{date.month:02d}-{date.day:02d}"
    else:
        when = f"{date.year:04d}"
    return f"{kind}:{when}"


@dataclass(frozen=True)
class SubEntityKind[T: SubEntity]:
    """Everything the whole-contact save needs to know about one sub-resource.

    ``aggregate_key`` names the row that records a change to the list's
    membership; ``prefix`` is the per-sub-entity key a matched edit rides the
    aggregate ContactUpdated under, or ``None`` for a type whose edit has an
    event of its own.
    """

    aggregate_key: str
    fields: Sequence[str]
    render: Callable[[T], str]
    separator: str
    prefix: str | None = None
    natural_key: NaturalKey[T] | None = None
    unique_claims: UniqueClaims[T] | None = None


METHODS: SubEntityKind[ContactMethod] = SubEntityKind(
    aggregate_key="contact_methods",
    fields=METHOD_FIELDS,
    render=render_method,
    separator=", ",
    prefix=METHOD_PREFIX,
    unique_claims=method_unique_claims,
)
ADDRESSES: SubEntityKind[ContactAddress] = SubEntityKind(
    aggregate_key="addresses",
    fields=ADDRESS_FIELDS,
    render=render_address,
    separator=" | ",
    prefix=ADDRESS_PREFIX,
)
NOTES: SubEntityKind[ContactNote] = SubEntityKind(
    aggregate_key="notes",
    fields=NOTE_FIELDS,
    render=render_note,
    separator=" | ",
    prefix=NOTE_PREFIX,
)
IMPORTANT_DATES: SubEntityKind[ImportantDate] = SubEntityKind(
    aggregate_key="important_dates",
    fields=IMPORTANT_DATE_FIELDS,
    render=render_important_date,
    separator=", ",
    natural_key=important_date_key,
    unique_claims=important_date_unique_claims,
)


def aggregate_change[T: SubEntity](
    kind: SubEntityKind[T], before: Iterable[T], after: Iterable[T]
) -> ChangedFields:
    """The aggregate row for a list whose membership changed, if it reads
    differently.

    Both sides are rendered and sorted, so the row says which items came and
    went rather than how many there are - a retyped date or a replaced note
    keeps the count. Lists that render the same report nothing: a note deleted
    and re-created with the same words has new ids and nothing a reader of the
    feed could see.
    """
    old = _render_list(kind, before)
    new = _render_list(kind, after)
    return {} if old == new else {kind.aggregate_key: (old, new)}


def _render_list[T: SubEntity](kind: SubEntityKind[T], items: Iterable[T]) -> str:
    rendered = sorted(kind.render(item) for item in items)
    return kind.separator.join(rendered) if rendered else "None"


def with_primary_method(
    methods: Sequence[ContactMethod],
    method_type: MethodType,
    value: str,
    contact_id: int,
) -> list[ContactMethod]:
    """``methods``, with the primary ``method_type`` set to ``value``.

    Edits the primary method of that type in place - a copy keeping its id, so
    the save can report what the value was - or, when none is primary,
    promotes the first active method of the type, or adds one. Every other method is
    returned as it is, and the ones passed in are not modified: they are the
    before-image the reconcile diffs against.
    """
    # An archived method is out of use: it is never the one made primary.
    of_type = [m for m in methods if m.method_type == method_type and not m.is_archived]
    target = next((m for m in of_type if m.is_primary), None) or next(
        iter(of_type), None
    )
    if target is None:
        return [
            *methods,
            ContactMethod(
                method_type=method_type,
                value=value,
                contact_id=contact_id,
                is_primary=True,
            ),
        ]
    return [
        replace(m, value=value, is_primary=True) if m is target else m for m in methods
    ]


def archived_match_key(item: ContactMethod | ContactAddress) -> Hashable:
    """What makes an incoming value the same as an archived one.

    Emails compare as the unique index does - trimmed and case-insensitive;
    phones on their digits, since a provider may format the same number
    differently; addresses on every line, trimmed and case-insensitive.
    """
    if isinstance(item, ContactAddress):
        return tuple(
            (part or "").strip().lower()
            for part in (
                item.street_line_1,
                item.street_line_2,
                item.locality,
                item.region,
                item.postal_code,
                item.country_code,
            )
        )
    if item.method_type == MethodType.PHONE:
        return (item.method_type.value, "".join(c for c in item.value if c.isdigit()))
    return (item.method_type.value, item.value.strip().lower())


def keep_archived[T: (ContactMethod, ContactAddress)](
    stored: Sequence[T] | None, incoming: Sequence[T] | None
) -> list[T] | None:
    """An integration's list, with the contact's archived values kept.

    Archived values are never synced out, so an integration's whole-list
    payload never holds them and would otherwise delete them. They are kept
    under their ids, which the reconcile matches as unchanged. An incoming
    value matching an archived one is the provider holding it again: it takes
    that row's id and is saved un-archived, so the edit reads as a restore.

    ``None`` - the integration said nothing about the list - stays ``None``.
    """
    if incoming is None:
        return None
    archived = [row for row in stored or [] if row.is_archived]
    by_key = {archived_match_key(row): row for row in archived}
    restored: set[int] = set()
    result: list[T] = []
    for item in incoming:
        match = by_key.pop(archived_match_key(item), None) if item.id is None else None
        if match is None:
            result.append(item)
            continue
        restored.add(id(match))
        result.append(replace(item, id=match.id, is_archived=False))
    return result + [row for row in archived if id(row) not in restored]


@dataclass(frozen=True)
class SubResourceMerge:
    """Sub-resource changes named rather than listed.

    A caller that wants to set the primary email, or add one note, would
    otherwise have to hand ``update_contact`` the whole list, built from a
    read it made itself - and a row added by someone else between that read
    and the write would be missing from the list, and deleted. The service
    applies a merge to the contact as it reads it under the row lock instead,
    so there is no such window. The ``tag_names`` argument does the same for
    tags.
    """

    primary_methods: Mapping[MethodType, str] = field(default_factory=dict)
    new_notes: Sequence[str] = ()

    def conflicts(self, contact: Contact) -> list[str]:
        """The sub-resources ``contact`` also gives a whole list for.

        Two answers to one question: refused rather than guessed between.
        """
        clashes = []
        if self.primary_methods and contact.methods is not None:
            clashes.append("methods")
        if self.new_notes and contact.notes is not None:
            clashes.append("notes")
        return clashes

    def apply_to(self, contact: Contact, stored: Contact) -> None:
        """Give ``contact`` the whole lists this merge implies over ``stored``."""
        contact_id = stored.id or 0
        if self.primary_methods:
            methods = list(stored.methods or [])
            for method_type, value in self.primary_methods.items():
                methods = with_primary_method(methods, method_type, value, contact_id)
            contact.methods = methods
        if self.new_notes:
            contact.notes = [
                *(stored.notes or []),
                *(
                    ContactNote(content=content, contact_id=contact_id)
                    for content in self.new_notes
                ),
            ]
