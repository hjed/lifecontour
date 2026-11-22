"""Reconcile a recurrence whose instance ids Google re-issued.

Moving a whole recurrence to a new time ("all events") gives every instance a
new id: instance ids are ``<recurrence>_<original start>``, and the original
start changed. Under ``singleEvents=true`` the sync then receives each new
instance as an event nobody has journalled - and **no cancellation for the
old ids**. Left alone, every occurrence ends up with two journals: the old
one, linked to an id Google no longer has, and a new one.

This module finds those orphaned links and retires each one:

- **adopted** when exactly one new, unlinked instance of the same recurrence
  falls on its local day (in the user's zone): the new instance becomes an
  update of the old journal, so notes and history stay put. No title check -
  the recurrence id already proves identity, and a re-time often comes with a
  rename. Anything ambiguous (a sub-daily recurrence, say) pairs nothing,
  because a wrong merge is worse than a duplicate;
- **cancelled** otherwise, exactly as if Google had sent the cancellation, so
  the backend's usual policy (past events kept, untouched continuations
  deleted) applies.

"Gone" is decided from Google, never from the batch alone: an incremental
batch holds only what changed. A sync-token listing asks
``events().instances`` for each recurrence that shows the symptom (an
unlinked instance beside linked ones the batch did not mention); a
time-ranged listing already is Google's whole view and is used as is. Either
way only links inside the window Google answered for - from the query's
``time_min`` to the last instance it returned - are retired: Google expands an
endless recurrence only so far, and a link past that may still be live.

Links synced outbound-only, and legacy links that never recorded their
recurrence, are never retired.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from core_shared.logging import get_logger
from googleapiclient.errors import HttpError
from sqlalchemy import text

from calendar_models import GoogleEvent
from split_adoption import (
    InstanceAdoption,
    event_start,
    parse_events,
    start_moment,
)

logger = get_logger(__name__)

# How far before the earliest orphan candidate to ask Google from, so a
# candidate on the window's first day is inside it in every zone.
_WINDOW_LEAD = timedelta(days=1)


class RecurrenceReader(Protocol):
    """The Google calls this module makes."""

    async def list_instances(
        self, calendar_id: str, event_id: str, time_min: str
    ) -> list[dict[str, Any]]: ...

    async def get_event(
        self, event_id: str, calendar_id: str = "primary"
    ) -> dict[str, Any]: ...


# A window with no end: Google listed every instance there is.
_UNBOUNDED = datetime.max.replace(tzinfo=UTC)


def instance_slot(external_event_id: str, zone: ZoneInfo) -> datetime | None:
    """When the rule scheduled an instance, from its ``<recurrence>_<slot>`` id.

    The slot is UTC (``20261214T030000Z``) or, all-day, a date
    (``20261214``) taken as midnight in ``zone``. ``None`` for any other id.
    """
    _, _, suffix = external_event_id.rpartition("_")
    for pattern, tzinfo in (("%Y%m%dT%H%M%SZ", UTC), ("%Y%m%d", zone)):
        try:
            return datetime.strptime(suffix, pattern).replace(tzinfo=tzinfo)
        except ValueError:
            continue
    return None


def rule_is_bounded(master: Mapping[str, Any]) -> bool:
    """Whether a recurring master's rules all end (``UNTIL`` or ``COUNT``).

    Only then does a listing return every instance. An endless rule is
    expanded only so far, and a master we could not read is treated as
    endless.
    """
    lines = master.get("recurrence") or []
    rules = [line.upper() for line in lines if line.upper().startswith("RRULE:")]
    if not lines:
        return False
    return all("UNTIL=" in rule or "COUNT=" in rule for rule in rules)


@dataclass(frozen=True)
class RecurrenceLink:
    """A link in this calendar to an instance (or a legacy link in the batch).

    ``start`` is the journal's, which a local edit may have moved; ``slot``
    is when the rule scheduled the instance (read from its id), which is how
    Google places it against the window it expanded.
    """

    external_event_id: str
    recurring_event_id: str | None
    journal_id: int
    start: datetime
    slot: datetime
    sync_capability: str


@dataclass(frozen=True)
class LiveInstances:
    """Google's live instances of one recurrence, and the window they cover.

    ``window_end`` is exclusive.
    """

    event_ids: frozenset[str]
    window_start: datetime
    window_end: datetime


@dataclass(frozen=True)
class RetiredInstance:
    """A linked instance Google no longer has."""

    external_event_id: str
    recurring_event_id: str
    journal_id: int


@dataclass(frozen=True)
class RekeyedPlan:
    """New event id -> the journal it adopts, and every instance retired.

    ``retired`` includes the adopted instances: their cancellation is only
    dropped once the adoption has really been sent.
    """

    targets: Mapping[str, InstanceAdoption] = field(default_factory=dict)
    retired: tuple[RetiredInstance, ...] = ()


def _retired_links(
    events: Sequence[GoogleEvent],
    links: Sequence[RecurrenceLink],
    live: Mapping[str, LiveInstances],
) -> list[RecurrenceLink]:
    batch_ids = {event.id for event in events}
    retired = []
    for link in links:
        instances = live.get(link.recurring_event_id or "")
        if (
            instances is not None
            and link.sync_capability != "outbound"
            and link.external_event_id not in instances.event_ids
            # An instance the batch cancelled is handled by that cancellation.
            and link.external_event_id not in batch_ids
            and instances.window_start <= link.slot < instances.window_end
        ):
            retired.append(link)
    return retired


def plan_rekeyed_instances(
    events: Sequence[GoogleEvent],
    links: Sequence[RecurrenceLink],
    live: Mapping[str, LiveInstances],
    zone: ZoneInfo,
) -> RekeyedPlan:
    """Retire the links of ``live``'s recurrences that Google no longer has.

    ``links`` holds this calendar's links to those recurrences' instances,
    plus any link to an event in the batch (a legacy link records no
    recurrence but still means the event is journalled).
    """
    retired = _retired_links(events, links, live)
    linked_ids = {link.external_event_id for link in links}

    old_by_key: dict[tuple[str, date], list[RecurrenceLink]] = defaultdict(list)
    for link in retired:
        key = (link.recurring_event_id or "", link.start.astimezone(zone).date())
        old_by_key[key].append(link)
    new_by_key: dict[tuple[str, date], list[GoogleEvent]] = defaultdict(list)
    for event in events:
        recurrence = event.recurring_event_id
        if (
            recurrence is not None
            and recurrence in live
            and event.status != "cancelled"
            and event.id not in linked_ids
            and (moment := event_start(event, zone)) is not None
        ):
            new_by_key[(recurrence, moment.astimezone(zone).date())].append(event)

    targets: dict[str, InstanceAdoption] = {}
    for key, olds in old_by_key.items():
        news = new_by_key.get(key, [])
        if len(olds) == 1 and len(news) == 1:
            targets[news[0].id] = InstanceAdoption(
                journal_id=olds[0].journal_id,
                old_event_id=olds[0].external_event_id,
                rekeyed=True,
            )
    return RekeyedPlan(
        targets=targets,
        retired=tuple(
            RetiredInstance(
                external_event_id=link.external_event_id,
                recurring_event_id=link.recurring_event_id or "",
                journal_id=link.journal_id,
            )
            for link in retired
        ),
    )


_LINKS = text("""
    SELECT l.external_event_id, l.recurring_event_id, l.journal_id,
           l.sync_capability, j.event_date_range_start
    FROM journal_external_event_links l
    JOIN journals j ON j.id = l.journal_id
    WHERE l.calendar_id = :calendar_id
      AND l.external_event_id IS NOT NULL
      AND j.event_date_range_start IS NOT NULL
      AND (l.recurring_event_id = ANY(:recurrences)
           OR l.external_event_id = ANY(:event_ids))
""")


async def _load_links(
    session: Any,
    calendar_id: UUID,
    recurrences: Sequence[str],
    event_ids: Sequence[str],
    zone: ZoneInfo,
) -> list[RecurrenceLink]:
    result = await session.execute(
        _LINKS,
        {
            "calendar_id": calendar_id,
            "recurrences": list(recurrences),
            "event_ids": list(event_ids),
        },
    )
    return [
        RecurrenceLink(
            external_event_id=row.external_event_id,
            recurring_event_id=row.recurring_event_id,
            journal_id=row.journal_id,
            start=row.event_date_range_start,
            slot=instance_slot(row.external_event_id, zone)
            or row.event_date_range_start,
            sync_capability=row.sync_capability,
        )
        for row in result.fetchall()
    ]


def _live_instances(
    instances: Sequence[GoogleEvent],
    window_start: datetime,
    zone: ZoneInfo,
    *,
    bounded: bool,
) -> LiveInstances | None:
    """Google's view of one recurrence, or ``None`` when it returned none.

    A bounded rule is listed whole, so its window never ends. An endless one
    covers through the last listed instance's local day: a recurrence moved
    earlier has its last old occurrence on that day, after the last new one.
    """
    live = [event for event in instances if event.status != "cancelled"]
    if not live:
        return None
    if bounded:
        window_end = _UNBOUNDED
    else:
        # Only an instance still at its slot shows how far Google expanded
        # the rule: a moved one (an exception) keeps a slot that may lie far
        # past that, or far before where it now sits, either way proving
        # nothing about the dates between.
        slots = [
            start
            for event in live
            if (start := event_start(event, zone)) is not None
            and start_moment(event.original_start_time, zone) in (None, start)
        ]
        if not slots:
            return None
        window_end = _expansion_end(slots, zone)
    return LiveInstances(
        event_ids=frozenset(event.id for event in live),
        window_start=window_start,
        window_end=window_end,
    )


def _expansion_end(slots: Sequence[datetime], zone: ZoneInfo) -> datetime:
    """Where an endless rule's listing stops proving instances gone (exclusive).

    Through the last listed local day when the rule has at most one slot a
    day: a recurrence moved earlier has its last old occurrence on that day,
    after the last new one. A sub-daily rule may stop expanding mid-day, so
    its later slots that day were never listed: it ends at its last slot.
    """
    last = max(slots)
    days = {slot.astimezone(zone).date() for slot in slots}
    if len(days) < len(slots):
        return last + timedelta(microseconds=1)
    return datetime.combine(
        last.astimezone(zone).date() + timedelta(days=1), time(), tzinfo=zone
    )


async def _is_bounded(
    client: RecurrenceReader, google_calendar_id: str, recurrence: str
) -> bool:
    try:
        master = await client.get_event(recurrence, google_calendar_id)
    except HttpError as e:
        logger.warning(
            "Could not read a recurrence's rule, treating it as endless",
            recurring_event_id=recurrence,
            error=str(e),
        )
        return False
    return rule_is_bounded(master)


async def _ask_google(
    client: RecurrenceReader,
    google_calendar_id: str,
    recurrence: str,
    window_start: datetime,
    zone: ZoneInfo,
    *,
    bounded: bool,
) -> LiveInstances | None:
    """Google's live instances of ``recurrence`` from ``window_start`` on."""
    try:
        listed = await client.list_instances(
            google_calendar_id, recurrence, window_start.isoformat()
        )
    except HttpError as e:
        # The recurrence may be gone altogether (its master's cancellation
        # handles that): retire nothing on a guess.
        logger.warning(
            "Could not list a recurrence's instances, not reconciling it",
            recurring_event_id=recurrence,
            error=str(e),
        )
        return None
    return _live_instances(parse_events(listed), window_start, zone, bounded=bounded)


async def find_rekeyed_instances(
    session: Any,
    client: RecurrenceReader,
    calendar_id: UUID,
    google_calendar_id: str,
    raw_events: Sequence[dict[str, Any]],
    zone_name: str | None,
    *,
    listing_time_min: datetime | None,
) -> RekeyedPlan:
    """Plan the retirement of every orphaned instance link this batch reveals.

    ``listing_time_min`` is the ``time_min`` the batch was listed from, or
    ``None`` for a sync-token listing, which holds only what changed. Costs
    nothing for a batch without live recurring instances, one link query
    otherwise, and - for a sync-token listing only - one paged
    ``list_instances`` per recurrence showing the symptom.
    """
    events = parse_events(raw_events)
    by_recurrence: dict[str, list[GoogleEvent]] = defaultdict(list)
    for event in events:
        if event.recurring_event_id and event.status != "cancelled":
            by_recurrence[event.recurring_event_id].append(event)
    if not by_recurrence:
        return RekeyedPlan()

    zone = ZoneInfo(zone_name) if zone_name else ZoneInfo("UTC")
    links = await _load_links(
        session, calendar_id, list(by_recurrence), [e.id for e in events], zone
    )
    batch_ids = {event.id for event in events}
    linked_ids = {link.external_event_id for link in links}

    live: dict[str, LiveInstances] = {}
    for recurrence, instances in by_recurrence.items():
        absent = [
            link
            for link in links
            if link.recurring_event_id == recurrence
            and link.external_event_id not in batch_ids
            and link.sync_capability != "outbound"
        ]
        if not absent:
            continue
        if listing_time_min is None and all(
            event.id in linked_ids for event in instances
        ):
            continue
        bounded = await _is_bounded(client, google_calendar_id, recurrence)
        if listing_time_min is not None:
            view = _live_instances(instances, listing_time_min, zone, bounded=bounded)
        else:
            view = await _ask_google(
                client,
                google_calendar_id,
                recurrence,
                # Google filters by where an instance is now: the slot for one
                # still there, the journal's date for one moved with it.
                min(min(link.slot, link.start) for link in absent) - _WINDOW_LEAD,
                zone,
                bounded=bounded,
            )
        if view is not None:
            live[recurrence] = view
    if not live:
        return RekeyedPlan()
    return plan_rekeyed_instances(events, links, live, zone)
