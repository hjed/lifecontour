"""
External link URL construction helpers.

Provides functions to build URLs for external system links displayed
on journal and contact detail pages. Handles Strava, Google Calendar,
and Google Contacts URL patterns.

No new database tables are required — links are derived from existing
JournalExternalEventLink, fitness_data, and ExternalReference records.
"""

import base64
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExternalLinkInfo:
    """Information about an external system link.

    Attributes:
        source: Integration source identifier (e.g. 'strava', 'google_calendar')
        url: Clickable URL to the external record, or None if not constructable
        external_id: The external system's identifier for the entity
    """

    source: str
    url: str | None
    external_id: str
    unique_key: str


def build_strava_activity_url(strava_activity_id: str | None) -> str | None:
    """Build a Strava activity URL from an activity ID.

    Args:
        strava_activity_id: Strava activity ID string, or None.

    Returns:
        Full Strava activity URL, or None if ID is missing/empty.
    """
    if not strava_activity_id or not strava_activity_id.strip():
        return None
    return f"https://www.strava.com/activities/{strava_activity_id.strip()}"


def build_google_calendar_event_url(
    external_event_id: str | None, calendar_id: str | None = None
) -> str | None:
    """Build a Google Calendar event URL from an external event ID.

    The event ID and optional calendar ID are urlsafe base64-encoded
    as required by Google Calendar's URL scheme.

    Args:
        external_event_id: Google Calendar event ID string, or None.
        calendar_id: Optional Google Calendar ID.

    Returns:
        Full Google Calendar event URL, or None if ID is missing/empty.
    """
    if not external_event_id or not external_event_id.strip():
        return None

    eid_content = external_event_id.strip()
    if calendar_id and calendar_id.strip():
        eid_content = f"{eid_content} {calendar_id.strip()}"

    eid = base64.urlsafe_b64encode(eid_content.encode()).decode().rstrip("=")
    return f"https://calendar.google.com/calendar/event?eid={eid}"


def build_google_contacts_url(external_entity_id: str | None) -> str | None:
    """Build a Google Contacts URL from an external entity ID.

    Handles resource names that may include a 'people/' prefix by stripping it.

    Args:
        external_entity_id: Google Contacts resource name, or None.

    Returns:
        Full Google Contacts person URL, or None if ID is missing/empty.
    """
    if not external_entity_id or not external_entity_id.strip():
        return None
    resource_name = external_entity_id.strip()
    # Strip 'people/' prefix if present (Google People API format)
    if resource_name.startswith("people/"):
        resource_name = resource_name[len("people/") :]
    return f"https://contacts.google.com/person/{resource_name}"


def build_snipeit_asset_url(base_url: str | None, asset_id: str | None) -> str | None:
    """Build a Snipe-IT hardware asset URL.

    Args:
        base_url: The Snipe-IT base URL for the user.
        asset_id: The Snipe-IT asset ID.

    Returns:
        Full Snipe-IT asset URL, or None if parameters are missing.
    """
    if not base_url or not base_url.strip() or not asset_id or not asset_id.strip():
        return None

    # Strip trailing slashes or /api/v1 from base_url to get the frontend URL
    # base_url might be "https://snipeit.example.com" or "https://snipeit.example.com/api/v1/"
    clean_base = base_url.strip().rstrip("/")
    if clean_base.endswith("/api/v1"):
        clean_base = clean_base[:-7]

    return f"{clean_base}/hardware/{asset_id.strip()}"


def build_snipeit_maintenance_url(
    base_url: str | None, maintenance_id: str | None
) -> str | None:
    """Build a Snipe-IT maintenance URL.

    Args:
        base_url: The Snipe-IT base URL for the user.
        maintenance_id: The Snipe-IT maintenance ID.

    Returns:
        Full Snipe-IT maintenance URL, or None if parameters are missing.
    """
    if (
        not base_url
        or not base_url.strip()
        or not maintenance_id
        or not maintenance_id.strip()
    ):
        return None

    clean_base = base_url.strip().rstrip("/")
    if clean_base.endswith("/api/v1"):
        clean_base = clean_base[:-7]

    clean_maintenance_id = maintenance_id.strip()
    if clean_maintenance_id.startswith("snipeit_maint:"):
        clean_maintenance_id = clean_maintenance_id[len("snipeit_maint:") :]

    return f"{clean_base}/hardware/maintenances/{clean_maintenance_id}"


def build_immich_person_url(
    server_url: str | None, person_id: str | None
) -> str | None:
    """Build an Immich People URL from a server URL and person ID.

    Args:
        server_url: The user's Immich server base URL, or None.
        person_id: The Immich person UUID, or None.

    Returns:
        Full Immich person URL, or None if either parameter is missing/empty.
    """
    if (
        not server_url
        or not server_url.strip()
        or not person_id
        or not person_id.strip()
    ):
        return None
    return f"{server_url.strip().rstrip('/')}/people/{person_id.strip()}"


def build_immich_album_url(server_url: str | None, album_id: str | None) -> str | None:
    """Build an Immich album URL from a server URL and album ID.

    Args:
        server_url: The user's Immich server base URL, or None.
        album_id: The Immich album UUID, or None.

    Returns:
        Full Immich album URL, or None if either parameter is missing/empty.
    """
    if not server_url or not server_url.strip() or not album_id or not album_id.strip():
        return None
    return f"{server_url.strip().rstrip('/')}/albums/{album_id.strip()}"


def build_journal_external_links(
    *,
    strava_activity_ids: list[str] | None = None,
    external_event_links: list[dict[str, Any]],
    snipeit_links: list[dict[str, Any]] | None = None,
    immich_album_links: list[dict[str, Any]] | None = None,
    immich_server_url: str | None = None,
) -> list[ExternalLinkInfo]:
    """Build a list of external links for a journal.

    Aggregates links from Strava activities, Google Calendar
    external event links, and Snipe-IT sync metadata.

    Args:
        strava_activity_ids: Every Strava activity linked to the journal. A
            journal carries more than one after an additive fitness merge,
            where two activities making up a single outing both stay linked.
        external_event_links: List of dicts with 'external_event_id' and
            'calendar_id' keys from JournalExternalEventLink records.
        snipeit_links: List of dicts with 'integration_source', 'external_id',
            and 'base_url' keys from sync_metadata and snipeit_settings.
        immich_album_links: List of dicts with 'album_id' and 'shared_link_url'
            keys from sync_metadata and the album external reference.
        immich_server_url: The user's Immich server base URL, used to build
            album links, or None if Immich is not connected.

    Returns:
        List of ExternalLinkInfo objects for display.
    """
    links: list[ExternalLinkInfo] = []

    # One link per Strava activity the journal is linked to
    seen_activity_ids: set[str] = set()
    for strava_activity_id in strava_activity_ids or []:
        activity_id = (strava_activity_id or "").strip()
        if not activity_id or activity_id in seen_activity_ids:
            continue
        seen_activity_ids.add(activity_id)
        links.append(
            ExternalLinkInfo(
                source="strava",
                url=build_strava_activity_url(activity_id),
                external_id=activity_id,
                unique_key=activity_id,
            )
        )

    # Google Calendar links from external event links
    for event_link in external_event_links:
        event_id = event_link.get("external_event_id")
        cal_id = event_link.get("calendar_id")
        internal_cal_id = event_link.get("internal_calendar_id")

        links.append(
            ExternalLinkInfo(
                source="google_calendar",
                url=build_google_calendar_event_url(event_id, cal_id),
                external_id=event_id if event_id else "",
                unique_key=event_id if event_id else (internal_cal_id or ""),
            )
        )

    # Snipe-IT links from sync metadata
    if snipeit_links:
        for snipeit_link in snipeit_links:
            source = snipeit_link.get("integration_source", "")
            ext_id = snipeit_link.get("external_id", "")
            base_url = snipeit_link.get("base_url", "")

            if source == "snipeit_maintenance":
                links.append(
                    ExternalLinkInfo(
                        source="snipeit_maintenance",
                        url=build_snipeit_maintenance_url(base_url, ext_id),
                        external_id=ext_id,
                        unique_key=f"maint-{ext_id}",
                    )
                )
            elif source == "snipeit":
                links.append(
                    ExternalLinkInfo(
                        source="snipeit",
                        url=build_snipeit_asset_url(base_url, ext_id),
                        external_id=ext_id,
                        unique_key=f"asset-{ext_id}",
                    )
                )

    # Immich album links from sync metadata + album external reference
    if immich_album_links:
        for album_link in immich_album_links:
            album_id = album_link.get("album_id")
            if not album_id:
                continue
            links.append(
                ExternalLinkInfo(
                    source="immich_album",
                    url=build_immich_album_url(immich_server_url, album_id),
                    external_id=album_id,
                    unique_key=f"album-{album_id}",
                )
            )
            shared_link_url = album_link.get("shared_link_url")
            if shared_link_url and shared_link_url.strip():
                links.append(
                    ExternalLinkInfo(
                        source="immich_shared",
                        url=shared_link_url.strip(),
                        external_id=album_id,
                        unique_key=f"shared-{album_id}",
                    )
                )

    return links


def build_contact_external_links(
    *,
    external_references: list[dict[str, Any]],
    immich_server_url: str | None = None,
) -> list[ExternalLinkInfo]:
    """Build a list of external links for a contact.

    Aggregates links from ExternalReference records for the contact.

    Args:
        external_references: List of dicts with 'external_system',
            'external_entity_id', and 'external_entity_type' keys.
        immich_server_url: The user's Immich server base URL, used to build
            person links, or None if Immich is not connected.

    Returns:
        List of ExternalLinkInfo objects for display.
    """
    links: list[ExternalLinkInfo] = []

    for ref in external_references:
        system = ref.get("external_system", "")
        entity_id = ref.get("external_entity_id", "")
        entity_type = ref.get("external_entity_type", "")

        if system == "google":
            links.append(
                ExternalLinkInfo(
                    source="google_contacts",
                    url=build_google_contacts_url(entity_id),
                    external_id=entity_id,
                    unique_key=entity_id,
                )
            )
        elif system == "strava":
            # Strava athlete URL format TBC — icon only for now
            links.append(
                ExternalLinkInfo(
                    source="strava",
                    url=None,
                    external_id=entity_id,
                    unique_key=entity_id,
                )
            )
        elif system == "immich" and entity_type == "person":
            links.append(
                ExternalLinkInfo(
                    source="immich",
                    url=build_immich_person_url(immich_server_url, entity_id),
                    external_id=entity_id,
                    unique_key=entity_id,
                )
            )
        else:
            # Unknown system — include with icon only
            links.append(
                ExternalLinkInfo(
                    source=system,
                    url=None,
                    external_id=entity_id,
                    unique_key=entity_id,
                )
            )

    return links
