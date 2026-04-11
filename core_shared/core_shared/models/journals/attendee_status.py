"""Attendee status for journal-contact relationships."""

from enum import StrEnum


class AttendeeStatus(StrEnum):
    """
    Enum for attendee status on journal-contact relationships.

    Tracks each contact's RSVP/attendance state for PARTICIPANT and INVITEE
    relationship types. Syncs with Google Calendar's responseStatus.
    """

    ATTENDING = "ATTENDING"
    """Contact is confirmed to attend / has accepted."""

    ATTENDED = "ATTENDED"
    """Contact attended the event (post-event transition)."""

    MAYBE = "MAYBE"
    """Contact may attend (tentative)."""

    NO_REPLY = "NO_REPLY"
    """Contact has not responded."""

    DECLINED = "DECLINED"
    """Contact has declined."""

    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value
