"""Contact event role for journal-contact relationships."""

from enum import StrEnum


class ContactEventRole(StrEnum):
    """
    Enum for contact event roles on journal-contact relationships.

    Captures the role a contact plays in an event. ORGANISER syncs from
    Google Calendar; FACILITATOR_HELPER is manual-only.
    """

    ORGANISER = "ORGANISER"
    """Contact is the event organiser (synced from Google Calendar)."""

    FACILITATOR_HELPER = "FACILITATOR_HELPER"
    """Contact is a facilitator or helper for the event (manual-only)."""

    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value
