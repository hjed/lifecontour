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


def build_journal_external_links(
    *,
    strava_activity_id: str | None,
    external_event_links: list[dict[str, Any]],
) -> list[ExternalLinkInfo]:
    """Build a list of external links for a journal.

    Aggregates links from Strava fitness data and Google Calendar
    external event links.

    Args:
        strava_activity_id: Strava activity ID from fitness_data, or None.
        external_event_links: List of dicts with 'external_event_id' and
            'calendar_id' keys from JournalExternalEventLink records.

    Returns:
        List of ExternalLinkInfo objects for display.
    """
    links: list[ExternalLinkInfo] = []

    # Strava link from fitness data
    if strava_activity_id and strava_activity_id.strip():
        links.append(
            ExternalLinkInfo(
                source="strava",
                url=build_strava_activity_url(strava_activity_id),
                external_id=strava_activity_id.strip(),
                unique_key=strava_activity_id.strip(),
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

    return links


def build_contact_external_links(
    *,
    external_references: list[dict[str, Any]],
) -> list[ExternalLinkInfo]:
    """Build a list of external links for a contact.

    Aggregates links from ExternalReference records for the contact.

    Args:
        external_references: List of dicts with 'external_system',
            'external_entity_id', and 'external_entity_type' keys.

    Returns:
        List of ExternalLinkInfo objects for display.
    """
    links: list[ExternalLinkInfo] = []

    for ref in external_references:
        system = ref.get("external_system", "")
        entity_id = ref.get("external_entity_id", "")

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
