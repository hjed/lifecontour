"""How an inbound record is named when a merge keeps it as an alias.

A merge records an absorbed record under the name of the link store it was
read from (``google_calendar``, ``strava``); the workers and the backend sync
processors ask about it in the terms of their payloads (``google``,
``strava:<activity id>``). This module is the one place those two vocabularies
meet, so a worker never has to know how the backend stores links.

A source missing here has no inbound records to alias: a record pushed *to*
it is undone upstream when the journal goes, not re-imported.
"""

from __future__ import annotations

from dataclasses import dataclass

# Payload ``integration_source`` → the link-store source a merge records under.
_LINK_SOURCE_BY_PAYLOAD_SOURCE: dict[str, str] = {
    "google": "google_calendar",
    "google_calendar": "google_calendar",
    "strava": "strava",
    "snipeit_maintenance": "snipeit_maintenance",
    "immich_album": "immich_album",
}

# Prefixes a worker adds to an id that the link stores hold bare. Strava's
# synthetic-calendar link is ``strava:<id>`` where ``sync_metadata`` and the
# fitness row hold ``<id>``.
_ID_PREFIX_BY_LINK_SOURCE: dict[str, str] = {
    "strava": "strava:",
}


@dataclass(frozen=True)
class MergedAliasKey:
    """The ``(integration_source, external_id)`` an alias is stored under."""

    integration_source: str
    external_id: str


def merged_alias_key(
    payload_source: str | None, external_id: str
) -> MergedAliasKey | None:
    """The alias key for a record, or ``None`` when it cannot be an alias.

    Accepts either vocabulary: a payload's source and id, or a link store's.
    """
    if not payload_source:
        return None
    link_source = _LINK_SOURCE_BY_PAYLOAD_SOURCE.get(payload_source)
    normalised = external_id.strip()
    if link_source is None or not normalised:
        return None
    prefix = _ID_PREFIX_BY_LINK_SOURCE.get(link_source)
    if prefix and normalised.startswith(prefix):
        normalised = normalised.removeprefix(prefix)
    return MergedAliasKey(integration_source=link_source, external_id=normalised)
