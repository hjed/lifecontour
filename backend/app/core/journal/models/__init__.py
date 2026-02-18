"""Journal domain models."""

from .calendar import Calendar
from .calendar_info import CalendarInfo
from .constants import (
    MAX_CALENDAR_NAME_LENGTH,
    MAX_ENERGY_LEVEL,
    MAX_HIERARCHY_DEPTH,
    MAX_IMMICH_ALBUM_ID_LENGTH,
    MAX_LOCATION_LENGTH,
    MAX_MOOD_LABEL_LENGTH,
    MAX_MOOD_VALUE,
    MAX_PLAN_DOCUMENT_TITLE_LENGTH,
    MAX_PLAN_DOCUMENT_URL_LENGTH,
    MAX_TITLE_LENGTH,
    MAX_USER_ID_LENGTH,
    MIN_ENERGY_LEVEL,
    MIN_MOOD_VALUE,
)
from .entities import Journal
from .events import (
    DomainEvent,
    JournalCreated,
    JournalDeleted,
    JournalTypeAdded,
    JournalTypeRemoved,
    JournalUpdated,
    RouteCreated,
    RouteDeleted,
    RouteUpdated,
)
from .exceptions import (
    CalendarInfoValidationError,
    CalendarNotFoundError,
    CalendarValidationError,
    FitnessDataValidationError,
    JournalCycleError,
    JournalError,
    JournalHierarchyError,
    JournalMaxDepthExceededError,
    JournalNotFoundError,
    JournalValidationError,
    MoodDataValidationError,
    PhotoAlbumDataValidationError,
    PlanDataValidationError,
    PlanDocumentValidationError,
    RouteInUseError,
    RouteNotFoundError,
    RouteValidationError,
    TravelAccommodationValidationError,
    TravelDataValidationError,
    TravelFlightValidationError,
    TravelTransportationValidationError,
)
from .fitness_data import FitnessData
from .journal_contact_relationship import JournalContactRelationship
from .journal_relationship_types import JournalContactRelationshipType
from .journal_tag import JournalTag
from .journal_types import JournalType
from .mood_data import MoodData
from .photo_album_data import PhotoAlbumData
from .plan_data import PlanData, PlanDocument
from .repositories import (
    CalendarInfoRepository,
    CalendarRepository,
    FitnessDataRepository,
    JournalContactRelationshipRepository,
    JournalRepository,
    JournalTagRepository,
    MoodDataRepository,
    PhotoAlbumDataRepository,
    PlanDataRepository,
    RouteRepository,
    TravelDataRepository,
)
from .travel_data import (
    TravelAccommodation,
    TravelData,
    TravelFlight,
    TravelTransportation,
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
    "MAX_IMMICH_ALBUM_ID_LENGTH",
    "MAX_PLAN_DOCUMENT_TITLE_LENGTH",
    "MAX_PLAN_DOCUMENT_URL_LENGTH",
    # Entities
    "Journal",
    "Calendar",
    "CalendarInfo",
    "FitnessData",
    "MoodData",
    "PhotoAlbumData",
    "PlanData",
    "PlanDocument",
    "TravelData",
    "TravelFlight",
    "TravelAccommodation",
    "TravelTransportation",
    "JournalTag",
    "JournalContactRelationship",
    # Enums
    "JournalType",
    "JournalContactRelationshipType",
    # Events
    "DomainEvent",
    "JournalCreated",
    "JournalUpdated",
    "JournalDeleted",
    "JournalTypeAdded",
    "JournalTypeRemoved",
    "RouteCreated",
    "RouteUpdated",
    "RouteDeleted",
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
    "FitnessDataValidationError",
    "MoodDataValidationError",
    "PhotoAlbumDataValidationError",
    "PlanDataValidationError",
    "PlanDocumentValidationError",
    "TravelDataValidationError",
    "TravelFlightValidationError",
    "TravelAccommodationValidationError",
    "TravelTransportationValidationError",
    "RouteNotFoundError",
    "RouteInUseError",
    "RouteValidationError",
    # Repositories
    "JournalRepository",
    "CalendarRepository",
    "CalendarInfoRepository",
    "FitnessDataRepository",
    "MoodDataRepository",
    "PhotoAlbumDataRepository",
    "PlanDataRepository",
    "TravelDataRepository",
    "JournalTagRepository",
    "JournalContactRelationshipRepository",
    "RouteRepository",
    # Value Objects
    "EventDateRange",
]
