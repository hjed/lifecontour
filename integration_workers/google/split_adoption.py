"""Pair the two halves of a split recurrence within one sync batch.

A "this and following" edit in Google can end the old recurrence and start a
new one. Sometimes the new recurrence's id is ``<old>_R<time>`` and the series
key folds it in (``recurrence.root_recurring_event_id``), but Google also
issues an **unrelated** id. Under ``singleEvents=true`` the change then reads
as two unrelated things in the same batch: each upcoming instance of the old
recurrence arrives cancelled, and each instance of the new one arrives as an
event nobody has journalled.

Left alone that cancels the old journals and creates a duplicate for every
date. Paired here instead, the new instance becomes an update of the old
journal - new times, new event id, same journal and series - and the old
instance's cancellation is dropped once that adoption has been sent.

Two instances pair when all of these hold:

- the old one is cancelled in this batch and linked to a journal displayed
  in this calendar (where its series is keyed - a copy shared from another
  calendar would be adopted with no series to fold into) that is not synced
  outbound-only and has not already ended (the sync's own past-cancellation
  skip, which reads the end);
- the new one is live, an instance of a *different* recurrence, and not yet
  linked here at all (a shared copy displayed elsewhere is still journalled);
- they fall on the same local day (in the user's zone) and have the same
  title, trimmed and ignoring case - a cancelled instance carries no title,
  so the old one's is the journal's;
- each is the only candidate on its side for that day and title. A wrong
  merge is worse than a duplicate, so anything ambiguous pairs nothing.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import text

from calendar_models import GoogleEvent
from recurrence import root_recurring_event_id

# Mirrors the sync's past-cancellation skip: a cancellation of an occurrence
# that already ended is never sent, so it cannot be half of a split.
_PAST_BUFFER = timedelta(days=1)


@dataclass(frozen=True)
class LinkedInstance:
    """An event in the batch that a journal in this calendar already links to."""

    external_event_id: str
    journal_id: int
    title: str
    start: datetime
    end: datetime | None
    sync_capability: str
    displayed_here: bool


@dataclass(frozen=True)
class SplitTarget:
    """The journal a new instance adopts, and the series it adopts from.

    ``old_event_id`` is the old instance whose cancellation the adoption makes
    redundant: it is dropped only once the new instance has adopted the
    journal, never on the pairing alone.
    """

    journal_id: int
    adopted_from: str
    old_event_id: str


@dataclass(frozen=True)
class SplitPairing:
    """New event id -> the journal it adopts (and the old event it replaces)."""

    targets: Mapping[str, SplitTarget] = field(default_factory=dict)


def _normalised(title: str | None) -> str:
    return (title or "").strip().casefold()


def _event_zone(name: str | None) -> ZoneInfo | None:
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _local_day(event: GoogleEvent, zone: ZoneInfo) -> date | None:
    """The event's local start day, or ``None`` when it has none we can read.

    Runs before the sync loop's per-event error boundary, so a malformed
    start must not raise: the event is simply not a split half, and the loop
    rejects it on its own.
    """
    if event.start is None:
        return None
    try:
        if event.start.date_time:
            moment = datetime.fromisoformat(event.start.date_time)
            if moment.tzinfo is None:
                # A bare local time is in the event's own zone (``timeZone``),
                # not the worker's.
                moment = moment.replace(
                    tzinfo=_event_zone(event.start.time_zone) or zone
                )
            return moment.astimezone(zone).date()
        if event.start.date:
            return date.fromisoformat(event.start.date)
    except ValueError:
        return None
    return None


def pair_split_instances(
    events: Sequence[GoogleEvent],
    links: Mapping[str, LinkedInstance],
    zone: ZoneInfo,
    now: datetime,
) -> SplitPairing:
    """Pair cancelled old instances with new ones of another recurrence.

    ``links`` holds the batch's events that already have a journal in this
    calendar, keyed by event id.
    """
    old_by_key: dict[tuple[date, str], list[tuple[GoogleEvent, LinkedInstance]]] = (
        defaultdict(list)
    )
    new_by_key: dict[tuple[date, str], list[GoogleEvent]] = defaultdict(list)
    for event in events:
        if not event.recurring_event_id:
            continue
        link = links.get(event.id)
        if event.status == "cancelled":
            if (
                link is not None
                and link.displayed_here
                and link.sync_capability != "outbound"
                and (link.end or link.start) >= now - _PAST_BUFFER
            ):
                key = (link.start.astimezone(zone).date(), _normalised(link.title))
                old_by_key[key].append((event, link))
        elif link is None:
            day = _local_day(event, zone)
            if day is not None:
                new_by_key[(day, _normalised(event.summary))].append(event)

    targets: dict[str, SplitTarget] = {}
    for key, olds in old_by_key.items():
        news = new_by_key.get(key, [])
        if len(olds) != 1 or len(news) != 1:
            continue
        [(old_event, old_link)], [new_event] = olds, news
        if old_event.recurring_event_id == new_event.recurring_event_id:
            continue
        adopted_from = root_recurring_event_id(old_event.recurring_event_id)
        if adopted_from is None:  # pragma: no cover - filtered above
            continue
        targets[new_event.id] = SplitTarget(
            journal_id=old_link.journal_id,
            adopted_from=adopted_from,
            old_event_id=old_event.id,
        )
    return SplitPairing(targets=targets)


def _has_both_halves(events: Sequence[GoogleEvent]) -> bool:
    recurring = [e for e in events if e.recurring_event_id]
    return any(e.status == "cancelled" for e in recurring) and any(
        e.status != "cancelled" for e in recurring
    )


def _parse(raw_events: Sequence[dict[str, Any]]) -> list[GoogleEvent]:
    """The batch's events, leaving out any the sync loop will itself reject."""
    events = []
    for raw in raw_events:
        try:
            events.append(GoogleEvent.from_api_response(raw))
        except ValueError:
            continue
    return events


async def find_split_pairing(
    session: Any,
    calendar_id: UUID,
    raw_events: Sequence[dict[str, Any]],
    zone_name: str | None,
) -> SplitPairing:
    """Load the batch's links in one query and pair the split halves.

    A batch without both a cancelled and a live recurring instance cannot
    hold a split, so it costs no query at all.
    """
    events = _parse(raw_events)
    if not _has_both_halves(events):
        return SplitPairing()
    result = await session.execute(
        text("""
            SELECT l.external_event_id, l.journal_id, l.sync_capability,
                   j.title, j.event_date_range_start, j.event_date_range_end,
                   EXISTS (
                       SELECT 1 FROM journal_calendar_info ci
                       WHERE ci.journal_id = l.journal_id
                         AND ci.calendar_id = l.calendar_id
                   ) AS displayed_here
            FROM journal_external_event_links l
            JOIN journals j ON j.id = l.journal_id
            WHERE l.calendar_id = :calendar_id
              AND l.external_event_id = ANY(:event_ids)
        """),
        {
            "calendar_id": calendar_id,
            "event_ids": [e.id for e in events if e.recurring_event_id],
        },
    )
    links = {
        row.external_event_id: LinkedInstance(
            external_event_id=row.external_event_id,
            journal_id=row.journal_id,
            title=row.title,
            start=row.event_date_range_start,
            end=row.event_date_range_end,
            sync_capability=row.sync_capability,
            displayed_here=bool(row.displayed_here),
        )
        for row in result.fetchall()
        if row.event_date_range_start is not None
    }
    zone = ZoneInfo(zone_name) if zone_name else ZoneInfo("UTC")
    return pair_split_instances(events, links, zone, datetime.now(UTC))
