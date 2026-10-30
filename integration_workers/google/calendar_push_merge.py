"""The journal push, merged against the synced base (#1899).

The push used to PATCH every field it writes, so an edit made in Google since
the last sync was overwritten by the next local change to anything — and the
pull that followed saw the push's own etag and skipped the event, losing the
edit on both sides.

Against the base (what both sides last agreed on) the push needs no read of
Google's copy first: a field whose local value is still in the base was not
changed locally, so it is left out of the PATCH and Google keeps whatever it
holds. Google's PATCH response then says what that is. A field Google holds
differently from the base was changed there: its base stays as it was, and the
link is marked ``pending_import`` so the next pull applies it even though the
event's etag is the push's own.

A link without a base pushes every field, as before bases existed, and records
one.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from core_shared.calendar_sync_base import (
    IMPORTABLE_ON_UPDATE,
    CalendarBase,
    CalendarSyncField,
    changed,
    description_key,
    google_event_keys,
    location_key,
    summary_key,
    when_key,
)

# The keys of the event payload each field is written to.
_PAYLOAD_KEYS: Final[Mapping[CalendarSyncField, tuple[str, ...]]] = {
    CalendarSyncField.SUMMARY: ("summary",),
    CalendarSyncField.DESCRIPTION: ("description",),
    CalendarSyncField.LOCATION: ("location",),
    CalendarSyncField.WHEN: ("start", "end"),
}


@dataclass(frozen=True)
class EventPushPlan:
    """What a push sends.

    * ``payload`` — the PATCH body.
    * ``sent`` — the fields it writes.
    * ``local`` — the key of every field the push owns, as local holds it.
    """

    payload: dict[str, Any]
    sent: frozenset[CalendarSyncField]
    local: Mapping[CalendarSyncField, str]


@dataclass(frozen=True)
class EventPushRecord:
    """What a push writes to the link's base, and whether Google won.

    * ``agreed`` — the fields it sent, each agreed on in both spellings.
    * ``seeded`` — local's key for each field it owns that has no base yet;
      written only where the link still holds none.
    * ``pending_import`` — Google holds a field the next pull can import.

    Any other field is not written: a pull may have recorded it since the
    push read the base, and the push decided nothing about it.
    """

    agreed: dict[CalendarSyncField, frozenset[str]]
    seeded: dict[CalendarSyncField, frozenset[str]]
    pending_import: bool


# A key no value is keyed as (``entry_key`` gives hex digests): a field whose
# base holds only this agrees with nothing, so the next push sends it and a
# pull keeps local's value meanwhile.
UNCONFIRMED_KEY: Final = "unconfirmed"


def _local_keys(
    payload: Mapping[str, Any], location: str | None
) -> dict[CalendarSyncField, str]:
    keys = {
        CalendarSyncField.SUMMARY: summary_key(payload.get("summary")),
        CalendarSyncField.LOCATION: location_key(location),
        CalendarSyncField.WHEN: when_key(payload["start"], payload["end"]),
    }
    # A private description is never pushed, so the push does not own it.
    if "description" in payload:
        keys[CalendarSyncField.DESCRIPTION] = description_key(payload["description"])
    return keys


def plan_event_push(
    payload: Mapping[str, Any],
    *,
    location: str | None,
    base: CalendarBase | None,
) -> EventPushPlan:
    """The PATCH for ``payload``: only the fields local changed since ``base``.

    ``location`` is the journal's own, which the full payload omits when it is
    empty. Against a base a location cleared locally is sent as empty, so the
    clear reaches Google rather than being imported back from it.
    """
    local = _local_keys(payload, location)
    if base is None:
        return EventPushPlan(
            payload=dict(payload),
            sent=frozenset(
                field
                for field in local
                if all(key in payload for key in _PAYLOAD_KEYS[field])
            ),
            local=local,
        )

    sent = frozenset(
        field for field, key in local.items() if changed(key, base.get(field))
    )
    patch = {
        key: payload[key]
        for field in sent
        for key in _PAYLOAD_KEYS[field]
        if key in payload
    }
    if CalendarSyncField.LOCATION in sent:
        patch["location"] = location or ""
    return EventPushPlan(payload=patch, sent=sent, local=local)


def record_event_push(
    plan: EventPushPlan,
    *,
    base: CalendarBase | None,
    response: Mapping[str, Any],
) -> EventPushRecord:
    """The base a push leaves, from Google's copy of the event after it.

    A field the push wrote is agreed on in both spellings: as sent, and as
    Google answered with it. One it left alone keeps its base — or, with none
    yet, is seeded with local's value — and if Google holds something else
    there, Google won it: the next pull imports it, when a pull can.
    """
    remote = google_event_keys(response)
    base = base or {}
    agreed: dict[CalendarSyncField, frozenset[str]] = {}
    seeded: dict[CalendarSyncField, frozenset[str]] = {}
    pending_import = False
    for field, local_key in plan.local.items():
        if field in plan.sent:
            agreed[field] = frozenset({local_key, remote[field]})
            continue
        kept = base.get(field)
        if kept is None:
            kept = seeded[field] = frozenset({local_key})
        if field in IMPORTABLE_ON_UPDATE and remote[field] not in kept:
            pending_import = True
    return EventPushRecord(agreed=agreed, seeded=seeded, pending_import=pending_import)


def unconfirmed_push(
    plan: EventPushPlan,
) -> dict[CalendarSyncField, frozenset[str]]:
    """The base a failed push leaves for the fields it sent.

    Google may have applied the PATCH before the push failed — a lost
    response, or an error recording it — so Google may hold either the value
    sent or the one before. Neither is known to agree with local any more:
    were local reverted to the old value, the old base would read it as
    unchanged and the push would skip it, leaving Google's copy of the
    reverted value for the next pull to import over the revert.
    """
    return {field: frozenset({UNCONFIRMED_KEY}) for field in plan.sent}
