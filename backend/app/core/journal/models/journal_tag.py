"""JournalTag entity for the journal domain.

This module defines hierarchical tags for journals, similar to contact tags but
separate to allow independent organization of journal content.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from .constants import MAX_TAG_COLOR_LENGTH, MAX_TAG_NAME_LENGTH


@dataclass
class JournalTag:
    """
    JournalTag entity for hierarchical organization of journals.

    Tags can have parent-child relationships to create a hierarchy.
    Each tag has a color for visual identification.

    Attributes:
        id: Unique identifier (UUID)
        name: Tag name (required, max 100 chars)
        parent_id: Parent tag ID for hierarchy (nullable)
        color: Hex color code (required, format: #RRGGBB)
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    id: UUID
    name: str
    color: str
    parent_id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate journal tag properties."""
        self._validate_name()
        self._validate_color()

    def _validate_name(self) -> None:
        """Validate tag name is provided and within length limit."""
        from .exceptions import JournalTagValidationError

        if not self.name or not self.name.strip():
            raise JournalTagValidationError("name", "Tag name is required")

        if len(self.name) > MAX_TAG_NAME_LENGTH:
            raise JournalTagValidationError(
                "name",
                f"Tag name cannot exceed {MAX_TAG_NAME_LENGTH} characters"
            )

    def _validate_color(self) -> None:
        """Validate color is a valid hex color code."""
        from .exceptions import JournalTagValidationError

        if not self.color or not self.color.strip():
            raise JournalTagValidationError("color", "Tag color is required")

        # Check format: #RRGGBB
        if not self.color.startswith("#") or len(self.color) != MAX_TAG_COLOR_LENGTH:
            raise JournalTagValidationError(
                "color",
                "Tag color must be in hex format: #RRGGBB"
            )

        # Validate hex characters
        try:
            int(self.color[1:], 16)
        except ValueError as e:
            raise JournalTagValidationError(
                "color",
                "Tag color must contain valid hexadecimal characters"
            ) from e


@dataclass
class JournalTagAssignment:
    """
    JournalTagAssignment entity representing the assignment of a tag to a journal.

    This is a many-to-many relationship between journals and tags.

    Attributes:
        journal_id: Foreign key to the journal (part of composite PK)
        tag_id: Foreign key to the tag (part of composite PK)
        created_at: Creation timestamp
    """

    journal_id: int
    tag_id: UUID
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate journal tag assignment properties."""

        self._validate_journal_id()

    def _validate_journal_id(self) -> None:
        """Validate journal_id is positive."""
        from .exceptions import JournalTagAssignmentValidationError

        if self.journal_id <= 0:
            raise JournalTagAssignmentValidationError(
                "journal_id", "Journal ID must be a positive integer"
            )

