"""Domain types for contact important dates."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class DatePrecision(Enum):
    """Enumeration for the precision of an important date."""

    FULL = "full"  # year, month, and day are known
    DAY_MONTH = "day_month"  # only month and day are known
    YEAR = "year"  # only year is known

    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value

    @property
    def display_label(self) -> str:
        """Return a human-readable label for the precision."""
        labels = {
            DatePrecision.FULL: "Full Date",
            DatePrecision.DAY_MONTH: "Day and Month",
            DatePrecision.YEAR: "Year Only",
        }
        return labels.get(self, "Unknown")


class ImportantDateType(Enum):
    """Enumeration for built-in important date types."""

    BIRTHDAY = "birthday"
    MARRIAGE_ANNIVERSARY = "marriage_anniversary"
    WORK_ANNIVERSARY = "work_anniversary"
    FIRST_MET = "first_met"
    CUSTOM = "custom"

    def __str__(self) -> str:
        """Return the string value of the enum."""
        return self.value

    @property
    def display_label(self) -> str:
        """Return a human-readable label for the date type."""
        labels = {
            ImportantDateType.BIRTHDAY: "Birthday",
            ImportantDateType.MARRIAGE_ANNIVERSARY: "Marriage Anniversary",
            ImportantDateType.WORK_ANNIVERSARY: "Work Anniversary",
            ImportantDateType.FIRST_MET: "First Met",
            ImportantDateType.CUSTOM: "Custom",
        }
        return labels.get(self, "Unknown")


@dataclass
class CustomDateType:
    """Entity representing a global custom date type."""

    name: str
    id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate the custom date type."""
        if not self.name.strip():
            raise ValueError("Name cannot be empty")

        if len(self.name) > 100:
            raise ValueError("Name cannot exceed 100 characters")
