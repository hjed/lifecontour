"""Journal-contact relationship entity."""

from dataclasses import dataclass
from datetime import datetime

from .journal_relationship_types import JournalContactRelationshipType


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
        created_at: Creation timestamp
    """

    journal_id: int
    contact_id: int
    relationship_type: JournalContactRelationshipType
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate relationship properties."""
        self._validate_ids()

    def _validate_ids(self) -> None:
        """Validate that IDs are positive."""
        if self.journal_id <= 0:
            raise ValueError("Journal ID must be positive")
        if self.contact_id <= 0:
            raise ValueError("Contact ID must be positive")

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
