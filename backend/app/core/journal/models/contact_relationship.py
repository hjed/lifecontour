"""JournalContactRelationship entity for the journal domain.

This module defines the relationship between journals and contacts, allowing
journals to reference contacts in multiple ways (participant, invitee, mention, about).
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ContactRelationshipType(str, Enum):
    """Types of relationships between journals and contacts.

    - PARTICIPANT: Contact attended/participated in the event
    - INVITEE: Contact was invited to the event
    - MENTION: Contact is mentioned in journal content (manually tagged)
    - ABOUT: Journal is specifically about this contact
    """

    PARTICIPANT = "PARTICIPANT"
    INVITEE = "INVITEE"
    MENTION = "MENTION"
    ABOUT = "ABOUT"


@dataclass
class JournalContactRelationship:
    """
    JournalContactRelationship entity representing a relationship between a journal and a contact.

    This entity links journals to contacts with a specific relationship type.
    Multiple relationships can exist between the same journal and contact with different types.

    Attributes:
        journal_id: Foreign key to the journal (part of composite PK)
        contact_id: Foreign key to the contact (part of composite PK)
        relationship_type: Type of relationship (part of composite PK)
        created_at: Creation timestamp
    """

    journal_id: int
    contact_id: int
    relationship_type: ContactRelationshipType
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate journal contact relationship properties."""

        self._validate_journal_id()
        self._validate_contact_id()
        self._validate_relationship_type()

    def _validate_journal_id(self) -> None:
        """Validate journal_id is positive."""
        from .exceptions import JournalContactRelationshipValidationError

        if self.journal_id <= 0:
            raise JournalContactRelationshipValidationError(
                "journal_id", "Journal ID must be a positive integer"
            )

    def _validate_contact_id(self) -> None:
        """Validate contact_id is positive."""
        from .exceptions import JournalContactRelationshipValidationError

        if self.contact_id <= 0:
            raise JournalContactRelationshipValidationError(
                "contact_id", "Contact ID must be a positive integer"
            )

    def _validate_relationship_type(self) -> None:
        """Validate relationship_type is a valid ContactRelationshipType."""
        from .exceptions import JournalContactRelationshipValidationError

        if not isinstance(self.relationship_type, ContactRelationshipType):
            raise JournalContactRelationshipValidationError(
                "relationship_type",
                f"Relationship type must be a ContactRelationshipType enum, got {type(self.relationship_type)}",
            )
