"""Journal domain models."""

from .calendar import Calendar
from .calendar_info import CalendarInfo
from .constants import (
    MAX_CALENDAR_NAME_LENGTH,
    MAX_ENERGY_LEVEL,
    MAX_HIERARCHY_DEPTH,
    MAX_LOCATION_LENGTH,
    MAX_MOOD_LABEL_LENGTH,
    MAX_MOOD_VALUE,
    MAX_TITLE_LENGTH,
    MAX_USER_ID_LENGTH,
    MIN_ENERGY_LEVEL,
    MIN_MOOD_VALUE,
)
from .entities import Journal
from .exceptions import (
    CalendarInfoValidationError,
    CalendarNotFoundError,
    CalendarValidationError,
    JournalCycleError,
    JournalError,
    JournalHierarchyError,
    JournalMaxDepthExceededError,
    JournalNotFoundError,
    JournalValidationError,
    MoodDataValidationError,
)
from .journal_types import JournalType
from .mood_data import MoodData
from .repositories import (
    CalendarInfoRepository,
    CalendarRepository,
    JournalRepository,
    MoodDataRepository,
)
from .value_objects import EventDateRange

__all__ = [
    # Constants
    "MAX_HIERARCHY_DEPTH",
    "MAX_TITLE_LENGTH",
    "MAX_USER_ID_LENGTH",
    "MAX_CALENDAR_NAME_LENGTH",
    "MAX_LOCATION_LENGTH",
    "MIN_MOOD_VALUE",
    "MAX_MOOD_VALUE",
    "MIN_ENERGY_LEVEL",
    "MAX_ENERGY_LEVEL",
    "MAX_MOOD_LABEL_LENGTH",
    # Entities
    "Journal",
    "Calendar",
    "CalendarInfo",
    "MoodData",
    # Enums
    "JournalType",
    # Exceptions
    "JournalCycleError",
    "JournalError",
    "JournalHierarchyError",
    "JournalMaxDepthExceededError",
    "JournalNotFoundError",
    "JournalValidationError",
    "CalendarValidationError",
    "CalendarNotFoundError",
    "CalendarInfoValidationError",
    "MoodDataValidationError",
    # Repositories
    "JournalRepository",
    "CalendarRepository",
    "CalendarInfoRepository",
    "MoodDataRepository",
    # Value Objects
    "EventDateRange",
]
