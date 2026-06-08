"""Shared, entity-agnostic activity-history value objects.

These are shared across domains (contacts, journals) and integration workers so
provenance can travel on domain events into the history projection.
"""

from enum import StrEnum


class Provenance(StrEnum):
    """Source of an entity data change, recorded against every history entry."""

    UI = "ui"
    MCP = "mcp"
    GOOGLE_CONTACTS = "google_contacts"
    GOOGLE_CALENDAR = "google_calendar"
    STRAVA = "strava"
    SUMMARY_REGENERATION = "summary_regeneration"
    SYSTEM = "system"
    IMMICH = "immich"


__all__ = ["Provenance"]
