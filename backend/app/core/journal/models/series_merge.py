"""Planning a series merge: which journals pair up, and what each pair keeps.

Merging series S into series D moves every S member into D. On top of that,
an S member and a D member whose events start on the same **local** day (the
user's configured timezone) are candidates to be merged into one journal, the
D member surviving. The user's per-field policies decide, for every pair at
once, which side's value survives — or that a pair whose values differ on a
field must not be merged at all.

Everything here is pure: the service loads the members and the timezone, and
reuses ``JournalMergeService`` for each pair with the overrides built here. The
preview and the execute call share :func:`plan_series_merge`, so a preview and
a merge over unchanged data agree by construction.
"""

from __future__ import annotations

import dataclasses
import datetime
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from core_shared.models.journals import CalendarInfo, Journal, JournalValidationError

from app.core.journal.services.journal_date_resolver import journal_date

if TYPE_CHECKING:
    from zoneinfo import ZoneInfo


class SeriesMergeField(StrEnum):
    """A field the user sets a series-wide merge policy for."""

    TITLE = "title"
    CONTENT = "content"
    # The date range and the calendar row's clock times, zone and all-day flag:
    # one answer, because the times mean nothing without the rest.
    TIMING = "timing"
    LOCATION = "location"
    EVENT_DESCRIPTION = "event_description"


class SeriesFieldPolicy(StrEnum):
    """What survives in a merged pair for one field."""

    DESTINATION = "destination"
    SOURCE = "source"
    # Content only: the single-journal merge's own concatenation.
    COMBINE = "combine"
    # Don't merge a pair whose two values differ on this field.
    SKIP_IF_DIFFERENT = "skip_if_different"


class SeriesDayOutcomeKind(StrEnum):
    """What happens to the journals of one local day."""

    CANDIDATE = "candidate"
    SKIPPED = "skipped"
    AMBIGUOUS = "ambiguous"
    UNPAIRED = "unpaired"
    ALREADY_SHARED = "already_shared"
    # Set by the execute call only.
    MERGED = "merged"
    EXCLUDED = "excluded"
    FAILED = "failed"


@dataclass(frozen=True)
class SeriesMergePolicies:
    """One policy per field, applied to every pair in the merge."""

    title: SeriesFieldPolicy = SeriesFieldPolicy.DESTINATION
    content: SeriesFieldPolicy = SeriesFieldPolicy.COMBINE
    timing: SeriesFieldPolicy = SeriesFieldPolicy.DESTINATION
    location: SeriesFieldPolicy = SeriesFieldPolicy.DESTINATION
    event_description: SeriesFieldPolicy = SeriesFieldPolicy.DESTINATION

    def __post_init__(self) -> None:
        """Reject ``COMBINE`` anywhere but content: nothing else concatenates."""
        for field in SeriesMergeField:
            if (
                field is not SeriesMergeField.CONTENT
                and self.for_field(field) is SeriesFieldPolicy.COMBINE
            ):
                raise JournalValidationError(
                    field.value, "Only content can be combined"
                )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, str] | None) -> SeriesMergePolicies:
        """Policies from ``{field: policy}`` strings; unnamed fields keep defaults.

        For callers holding untyped input (the MCP tools): an unknown field or
        policy is a validation error, not silently ignored.
        """
        policies: dict[str, SeriesFieldPolicy] = {}
        for name, value in (raw or {}).items():
            try:
                field = SeriesMergeField(name)
            except ValueError as e:
                raise JournalValidationError(name, "Unknown merge field") from e
            try:
                policies[field.value] = SeriesFieldPolicy(value)
            except ValueError as e:
                raise JournalValidationError(name, f"Unknown policy {value!r}") from e
        return cls(**policies)

    @classmethod
    def with_policy(
        cls, field: SeriesMergeField, policy: SeriesFieldPolicy
    ) -> SeriesMergePolicies:
        """The defaults with one field's policy replaced."""
        return dataclasses.replace(cls(), **{field.value: policy})

    def for_field(self, field: SeriesMergeField) -> SeriesFieldPolicy:
        """The policy set for ``field``."""
        policy: SeriesFieldPolicy = getattr(self, field.value)
        return policy


@dataclass(frozen=True)
class SeriesMember:
    """A series member journal with its calendar row, if it is an event."""

    journal: Journal
    calendar_info: CalendarInfo | None

    @property
    def journal_id(self) -> int:
        """The persisted journal's id."""
        assert self.journal.id is not None
        return self.journal.id


@dataclass(frozen=True)
class SeriesMergePair:
    """A source journal to merge into a destination journal."""

    source_journal_id: int
    destination_journal_id: int


@dataclass(frozen=True)
class DayOutcome:
    """The planned (or, after execute, actual) outcome for one local day."""

    date: datetime.date
    kind: SeriesDayOutcomeKind
    source_journal_ids: tuple[int, ...]
    destination_journal_ids: tuple[int, ...]
    differing_fields: tuple[SeriesMergeField, ...] = ()
    skip_reason: SeriesMergeField | None = None

    @property
    def pair(self) -> SeriesMergePair | None:
        """The pair this day would merge, when it has exactly one per side."""
        if len(self.source_journal_ids) != 1 or len(self.destination_journal_ids) != 1:
            return None
        return SeriesMergePair(
            self.source_journal_ids[0], self.destination_journal_ids[0]
        )


@dataclass(frozen=True)
class SeriesMergePlan:
    """Every day either series has a member on, in date order."""

    days: tuple[DayOutcome, ...]

    @property
    def candidates(self) -> tuple[SeriesMergePair, ...]:
        """The pairs that may be merged."""
        return tuple(
            pair
            for day in self.days
            if day.kind is SeriesDayOutcomeKind.CANDIDATE
            and (pair := day.pair) is not None
        )


def plan_series_merge(
    source_members: Iterable[SeriesMember],
    destination_members: Iterable[SeriesMember],
    tz: ZoneInfo,
    policies: SeriesMergePolicies,
) -> SeriesMergePlan:
    """Group both series' members by local date and decide each day's outcome.

    A day pairs only with exactly one member on each side. A journal already in
    both series stays where it is and takes no part in pairing.
    """
    sources = {m.journal_id: m for m in source_members}
    destinations = {m.journal_id: m for m in destination_members}
    shared_ids = sources.keys() & destinations.keys()

    by_day: dict[datetime.date, tuple[list[SeriesMember], list[SeriesMember]]] = (
        defaultdict(lambda: ([], []))
    )
    shared_by_day: dict[datetime.date, list[int]] = defaultdict(list)
    for member in sources.values():
        day = journal_date(member.journal, tz)
        if member.journal_id in shared_ids:
            shared_by_day[day].append(member.journal_id)
        else:
            by_day[day][0].append(member)
    for member in destinations.values():
        if member.journal_id not in shared_ids:
            by_day[journal_date(member.journal, tz)][1].append(member)

    days: list[DayOutcome] = [
        DayOutcome(
            date=day,
            kind=SeriesDayOutcomeKind.ALREADY_SHARED,
            source_journal_ids=tuple(sorted(ids)),
            destination_journal_ids=tuple(sorted(ids)),
        )
        for day, ids in shared_by_day.items()
    ]
    days.extend(
        _day_outcome(day, day_sources, day_destinations, policies)
        for day, (day_sources, day_destinations) in by_day.items()
    )
    days.sort(
        key=lambda outcome: (
            outcome.date,
            outcome.kind is not SeriesDayOutcomeKind.ALREADY_SHARED,
        )
    )
    return SeriesMergePlan(days=tuple(days))


def _day_outcome(
    day: datetime.date,
    day_sources: Sequence[SeriesMember],
    day_destinations: Sequence[SeriesMember],
    policies: SeriesMergePolicies,
) -> DayOutcome:
    source_ids = tuple(sorted(m.journal_id for m in day_sources))
    destination_ids = tuple(sorted(m.journal_id for m in day_destinations))
    if not day_sources or not day_destinations:
        kind = SeriesDayOutcomeKind.UNPAIRED
        return DayOutcome(day, kind, source_ids, destination_ids)
    if len(day_sources) > 1 or len(day_destinations) > 1:
        kind = SeriesDayOutcomeKind.AMBIGUOUS
        return DayOutcome(day, kind, source_ids, destination_ids)

    differing = differing_fields(day_sources[0], day_destinations[0])
    skip_reason = next(
        (
            field
            for field in differing
            if policies.for_field(field) is SeriesFieldPolicy.SKIP_IF_DIFFERENT
        ),
        None,
    )
    return DayOutcome(
        date=day,
        kind=(
            SeriesDayOutcomeKind.SKIPPED
            if skip_reason
            else SeriesDayOutcomeKind.CANDIDATE
        ),
        source_journal_ids=source_ids,
        destination_journal_ids=destination_ids,
        differing_fields=differing,
        skip_reason=skip_reason,
    )


def differing_fields(
    source: SeriesMember, destination: SeriesMember
) -> tuple[SeriesMergeField, ...]:
    """The fields on which both journals hold a value and the values differ.

    One empty side is not a difference: the merge fills it from the other.
    """
    return tuple(
        field
        for field in SeriesMergeField
        if _differs(_value(source, field), _value(destination, field))
        and not (field is SeriesMergeField.TIMING and _same_timing(source, destination))
    )


def _same_timing(source: SeriesMember, destination: SeriesMember) -> bool:
    """Whether the two occupy the same time, comparing clocks only when both have one.

    A journal that is not an event has no clock times to disagree with, so
    only its date range is compared.
    """
    source_range = source.journal.event_date_range
    destination_range = destination.journal.event_date_range
    if (source_range.start, source_range.end) != (
        destination_range.start,
        destination_range.end,
    ):
        return False
    if source.calendar_info is None or destination.calendar_info is None:
        return True
    same: bool = _value(source, SeriesMergeField.TIMING) == _value(
        destination, SeriesMergeField.TIMING
    )
    return same


def overrides_for_pair(
    source: SeriesMember,
    destination: SeriesMember,
    policies: SeriesMergePolicies,
) -> dict[str, Any]:
    """The ``merge_journals`` overrides that realise the policies for one pair.

    Every surviving value is pinned explicitly rather than left to the
    single-journal merge's own precedence, which favours a non-event journal's
    base fields over an event's — a rule that has nothing to say about which
    series the user preferred. ``COMBINE`` is the one policy expressed by
    *omitting* an override, since concatenation is that merge's default.
    """
    overrides: dict[str, Any] = {}
    event_overrides: dict[str, Any] = {}

    title = _chosen(source, destination, SeriesMergeField.TITLE, policies)
    if title:
        overrides["title"] = title

    if policies.content is not SeriesFieldPolicy.COMBINE:
        content = _chosen(source, destination, SeriesMergeField.CONTENT, policies)
        if content:
            overrides["content"] = content

    timing_from = source if policies.timing is SeriesFieldPolicy.SOURCE else destination
    date_range = timing_from.journal.event_date_range
    overrides["event_date_range"] = {
        "start": date_range.start.isoformat(),
        "end": date_range.end.isoformat(),
    }
    if timing_from.calendar_info is not None:
        info = timing_from.calendar_info
        event_overrides.update(
            start_time=_time_or_none(info.start_time),
            end_time=_time_or_none(info.end_time),
            timezone=info.timezone,
            is_all_day=info.is_all_day,
        )

    for field, column in (
        (SeriesMergeField.LOCATION, "location"),
        (SeriesMergeField.EVENT_DESCRIPTION, "description"),
    ):
        value = _chosen(source, destination, field, policies)
        if value:
            event_overrides[column] = value

    if source.calendar_info is not None or destination.calendar_info is not None:
        overrides["type_data"] = {"event": event_overrides}
    return overrides


def _chosen(
    source: SeriesMember,
    destination: SeriesMember,
    field: SeriesMergeField,
    policies: SeriesMergePolicies,
) -> Any:
    """The preferred side's value, or the other side's when it is empty."""
    preferred, other = (
        (source, destination)
        if policies.for_field(field) is SeriesFieldPolicy.SOURCE
        else (destination, source)
    )
    return _value(preferred, field) or _value(other, field)


def _value(member: SeriesMember, field: SeriesMergeField) -> Any:
    info = member.calendar_info
    match field:
        case SeriesMergeField.TITLE:
            return member.journal.title
        case SeriesMergeField.CONTENT:
            return member.journal.content
        case SeriesMergeField.TIMING:
            date_range = member.journal.event_date_range
            clock = (
                (info.start_time, info.end_time, info.timezone, info.is_all_day)
                if info is not None
                else None
            )
            return (date_range.start, date_range.end, clock)
        case SeriesMergeField.LOCATION:
            return info.location if info is not None else None
        case SeriesMergeField.EVENT_DESCRIPTION:
            return info.description if info is not None else None


def _differs(a: Any, b: Any) -> bool:
    return bool(a) and bool(b) and a != b


def _time_or_none(value: datetime.time | None) -> str | None:
    return value.isoformat() if value is not None else None
