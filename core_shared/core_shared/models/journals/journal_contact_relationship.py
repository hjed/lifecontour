"""Journal-contact relationship entity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .attendee_status import AttendeeStatus
from .contact_event_role import ContactEventRole
from .journal_relationship_types import JournalContactRelationshipType

_STATUS_ROLE_ALLOWED_TYPES = frozenset(
    {
        JournalContactRelationshipType.PARTICIPANT,
        JournalContactRelationshipType.INVITEE,
    }
)


@dataclass
class JournalContactRelationship:
    """
    Journal-contact relationship entity.

    Represents a relationship between a journal and a contact.
    A journal can have multiple contacts with different relationship types.
    The same contact can have multiple relationship types to the same journal.

    Attributes:
        journal_id: ID of the journal
        contact_id: ID of the contact
        relationship_type: Type of relationship (PARTICIPANT, INVITEE, MENTION, ABOUT)
        status: Optional attendee status (only for PARTICIPANT/INVITEE)
        role: Optional event role (only for PARTICIPANT/INVITEE)
        created_at: Creation timestamp
    """

    journal_id: int
    contact_id: int
    relationship_type: JournalContactRelationshipType
    created_at: datetime | None = None
    status: AttendeeStatus | None = None
    role: ContactEventRole | None = None

    def __post_init__(self) -> None:
        """Validate relationship properties."""
        self._validate_ids()
        self._validate_status_role()

    def _validate_ids(self) -> None:
        """Validate that IDs are positive."""
        if self.journal_id <= 0:
            raise ValueError("Journal ID must be positive")
        if self.contact_id <= 0:
            raise ValueError("Contact ID must be positive")

    def _validate_status_role(self) -> None:
        """Validate that status and role are only set on allowed relationship types."""
        if (self.status is not None or self.role is not None) and (
            self.relationship_type not in _STATUS_ROLE_ALLOWED_TYPES
        ):
            raise ValueError(
                "status and role are only permitted on PARTICIPANT and INVITEE "
                f"relationship types, got {self.relationship_type}"
            )

    def __eq__(self, other: object) -> bool:
        """Check equality based on journal_id, contact_id, and relationship_type."""
        if not isinstance(other, JournalContactRelationship):
            return False
        return (
            self.journal_id == other.journal_id
            and self.contact_id == other.contact_id
            and self.relationship_type == other.relationship_type
        )

    def __hash__(self) -> int:
        """Hash based on composite key."""
        return hash((self.journal_id, self.contact_id, self.relationship_type))
