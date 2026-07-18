"""Journal tag entity with hierarchical support."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class JournalTag:
    """
    Journal tag entity with hierarchical support.

    Tags can have parent-child relationships to form a hierarchy.
    Each tag has a color for visual identification.

    Attributes:
        name: Tag name (required)
        id: UUID primary key (auto-generated)
        parent_id: UUID of parent tag (nullable, for hierarchy)
        color: Hex color code (e.g., #FF0000)
        description: Free-text description of what the tag is for (nullable)
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    name: str
    id: UUID | None = None
    parent_id: UUID | None = None
    color: str | None = None
    description: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate tag properties."""
        self._validate_name()
        self._validate_color()

    def _validate_name(self) -> None:
        """Validate tag name is not empty."""
        if not self.name or not self.name.strip():
            raise ValueError("Tag name cannot be empty")

        if len(self.name) > 100:
            raise ValueError("Tag name cannot exceed 100 characters")

    def _validate_color(self) -> None:
        """Validate color is a valid hex code."""
        if self.color is None:
            return

        if not self.color.startswith("#"):
            raise ValueError("Color must be a hex color code starting with #")

        if len(self.color) != 7:
            raise ValueError(
                "Color must be a 7-character hex color code (e.g., #FF0000)"
            )

        # Validate hex characters
        try:
            int(self.color[1:], 16)
        except ValueError as e:
            raise ValueError(f"Invalid hex color code: {self.color}") from e

    def __eq__(self, other: object) -> bool:
        """Check equality based on ID."""
        if not isinstance(other, JournalTag):
            return False
        return self.id == other.id

    def __hash__(self) -> int:
        """Hash based on ID."""
        return hash(self.id)
