"""A journal participant, reported by an integration, that matched no contact."""

from dataclasses import dataclass

from core_shared.models.journals.attendee_status import AttendeeStatus
from core_shared.models.journals.contact_event_role import ContactEventRole
from core_shared.models.journals.journal_relationship_types import (
    JournalContactRelationshipType,
)


@dataclass(frozen=True)
class UnmatchedParticipantEmail:
    """An email on a synced journal that resolved to no contact.

    Keeps what the integration said about the participant, so a contact created
    or chosen for the email later can be linked to the journal exactly as the
    sync would have linked it. ``email`` is always lower-cased.
    """

    journal_id: int
    email: str
    relationship_type: JournalContactRelationshipType
    display_name: str | None = None
    status: AttendeeStatus | None = None
    role: ContactEventRole | None = None
