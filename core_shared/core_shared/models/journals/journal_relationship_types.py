"""Relationship types for journal-contact relationships."""

from enum import StrEnum


class JournalContactRelationshipType(StrEnum):
    """
    Enum for journal-contact relationship types.

    Defines how a contact relates to a journal entry.
    """

    PARTICIPANT = "PARTICIPANT"
    """Contact attended/participated in the event."""

    INVITEE = "INVITEE"
    """Contact was invited to the event."""

    MENTION = "MENTION"
    """Contact is mentioned in the journal content (manually tagged)."""

    ABOUT = "ABOUT"
    """Journal is specifically about this contact."""

    def __str__(self) -> str:
        """Return the string representation of the relationship type."""
        return self.value
