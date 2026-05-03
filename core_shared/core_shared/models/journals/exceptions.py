"""Exceptions for the journal domain."""

from core_shared.exceptions import DomainError


class JournalDomainError(DomainError):
    """Base exception for journal domain errors."""

    pass


class JournalError(Exception):
    """Base exception for journal domain errors (legacy)."""

    pass


class JournalValidationError(JournalDomainError):
    """Exception raised when journal validation fails."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}", 400)
        # Store field separately for programmatic access (e.g. in error handlers)
        self.field = field


class CalendarValidationError(JournalDomainError):
    """Exception raised when calendar validation fails."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}", 400)
        self.field = field


class CalendarNotFoundError(JournalDomainError):
    """Exception raised when a calendar is not found."""

    def __init__(self, calendar_id: str):
        super().__init__(f"Calendar with ID {calendar_id} not found", 404)
        self.calendar_id = calendar_id


class CalendarInfoValidationError(JournalDomainError):
    """Exception raised when calendar info (EVENT type) validation fails."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}", 400)
        self.field = field


class MoodDataValidationError(JournalDomainError):
    """Exception raised when mood data (MOOD_RATING type) validation fails."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}", 400)
        self.field = field


class FitnessDataValidationError(JournalDomainError):
    """Exception raised when fitness data (FITNESS type) validation fails."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}", 400)
        self.field = field


class JournalNotFoundError(JournalDomainError):
    """Exception raised when a journal is not found."""

    def __init__(self, journal_id: int):
        super().__init__(f"Journal with ID {journal_id} not found", 404)
        self.journal_id = journal_id


class JournalHierarchyError(JournalDomainError):
    """Exception raised when journal hierarchy constraints are violated."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message, status_code)


class JournalMaxDepthExceededError(JournalHierarchyError):
    """Exception raised when journal hierarchy exceeds maximum depth."""

    def __init__(self, max_depth: int, attempted_depth: int):
        self.max_depth = max_depth
        self.attempted_depth = attempted_depth
        super().__init__(
            f"Journal hierarchy depth {attempted_depth} exceeds maximum allowed depth of {max_depth}",
            400,
        )


class JournalCycleError(JournalHierarchyError):
    """Exception raised when a cycle would be created in journal hierarchy."""

    def __init__(self, journal_id: int, parent_id: int):
        self.journal_id = journal_id
        self.parent_id = parent_id
        super().__init__(
            f"Cannot set journal {journal_id} as child of {parent_id}: would create a cycle",
            400,
        )


class JournalTypeDependencyError(JournalDomainError):
    """Exception raised when a journal type dependency constraint is violated."""

    def __init__(self, message: str):
        super().__init__(message, 400)


class PhotoAlbumDataValidationError(JournalDomainError):
    """Exception raised when photo album data (PHOTO_ALBUM type) validation fails."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}", 400)
        self.field = field


class PlanDataValidationError(JournalDomainError):
    """Exception raised when plan data (PLAN type) validation fails."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}", 400)
        self.field = field


class PlanDocumentValidationError(JournalDomainError):
    """Exception raised when plan document validation fails."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}", 400)
        self.field = field


class TravelDataValidationError(JournalDomainError):
    """Exception raised when travel data (TRAVEL type) validation fails."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}", 400)
        self.field = field


class TravelFlightValidationError(JournalDomainError):
    """Exception raised when travel flight validation fails."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}", 400)
        self.field = field


class TravelAccommodationValidationError(JournalDomainError):
    """Exception raised when travel accommodation validation fails."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}", 400)
        self.field = field


class TravelTransportationValidationError(JournalDomainError):
    """Exception raised when travel transportation validation fails."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}", 400)
        self.field = field


class RouteNotFoundError(JournalDomainError):
    """Exception raised when a route is not found."""

    def __init__(self, route_id: str):
        super().__init__(f"Route with ID {route_id} not found", 404)
        self.route_id = route_id


class RouteInUseError(JournalDomainError):
    """Exception raised when attempting to delete a route that is in use."""

    def __init__(self, route_id: str):
        super().__init__(
            f"Route with ID {route_id} is in use and cannot be deleted", 409
        )
        self.route_id = route_id


class RouteValidationError(JournalDomainError):
    """Exception raised when route validation fails."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}", 400)
        self.field = field


class OutdoorActivityDataValidationError(JournalDomainError):
    """Exception raised when outdoor activity data (OUTDOOR_ACTIVITY type) validation fails."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}", 400)
        self.field = field


class BushwalkingDataValidationError(JournalDomainError):
    """Exception raised when bushwalking data (BUSHWALKING type) validation fails."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}", 400)
        self.field = field


class JoggingDataValidationError(JournalDomainError):
    """Exception raised when jogging data (JOGGING type) validation fails."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}", 400)
        self.field = field


class AbseilingDataValidationError(JournalDomainError):
    """Exception raised when abseiling data (ABSEILING_TRIP type) validation fails."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}", 400)
        self.field = field


class AbseilPitchValidationError(JournalDomainError):
    """Exception raised when abseil pitch validation fails."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}", 400)
        self.field = field


class CanyoningDataValidationError(JournalDomainError):
    """Exception raised when canyoning data (CANYONING type) validation fails."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}", 400)
        self.field = field


class CavingDataValidationError(JournalDomainError):
    """Exception raised when caving data (CAVING type) validation fails."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}", 400)
        self.field = field


class CanoeingDataValidationError(JournalDomainError):
    """Exception raised when canoeing data (CANOEING type) validation fails."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}", 400)
        self.field = field


class SnorkellingDataValidationError(JournalDomainError):
    """Exception raised when snorkelling data validation fails."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}", 400)
        self.field = field


class DivingDataValidationError(JournalDomainError):
    """Exception raised when diving data validation fails."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}", 400)
        self.field = field


class DownhillSkiingDataValidationError(JournalDomainError):
    """Exception raised when downhill skiing data validation fails."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}", 400)
        self.field = field


class ClimbingDataValidationError(JournalDomainError):
    """Exception raised when climbing data (CLIMBING type) validation fails."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}", 400)
        self.field = field


class KayakingDataValidationError(JournalDomainError):
    """Exception raised when kayaking data (KAYAKING type) validation fails."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}", 400)
        self.field = field


class CrossCountrySkiingDataValidationError(JournalDomainError):
    """Exception raised when cross-country skiing data (CROSS_COUNTRY_SKIING type) validation fails."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}", 400)
        self.field = field


class GPXParsingError(JournalDomainError):
    """Exception raised when GPX data cannot be parsed or contains no tracks."""

    def __init__(self, message: str):
        super().__init__(message, 422)


class JournalMergeConflictError(JournalDomainError):
    """Exception raised when there is a conflict in merging journals."""

    def __init__(self, message: str):
        super().__init__(message, 409)


class ActivityTemplateValidationError(JournalDomainError):
    """Exception raised when activity template validation fails."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}", 400)
        self.field = field


class TemplatePitchValidationError(JournalDomainError):
    """Exception raised when template pitch validation fails."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}", 400)
        self.field = field
