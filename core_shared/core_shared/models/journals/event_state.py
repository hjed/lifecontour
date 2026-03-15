"""Event state enumeration for EVENT type journals.

Represents the participation/status state of a calendar event journal.
Maps to Google Calendar event statuses and attendee response statuses.

Mapping from Google Calendar:
- Event status "confirmed" + self-attendee "accepted"/absent → CONFIRMED
- Event status "tentative" or self-attendee "tentative" → TENTATIVE
- Self-attendee "needsAction" (not yet accepted) → INVITED
- Event status "cancelled" → CANCELLED (handled via CANCEL_JOURNAL flow)
"""

from enum import StrEnum


class EventState(StrEnum):
    """State of a calendar event journal.

    Values:
        INVITED: User has been invited but hasn't responded yet
        TENTATIVE: User has tentatively accepted or event is tentative
        CONFIRMED: Event is confirmed (default for user-created events)
        CANCELLED: Event has been cancelled
    """

    INVITED = "invited"
    TENTATIVE = "tentative"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
