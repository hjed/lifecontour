"""Exceptions for the journal domain."""

from app.core.exceptions import DomainError


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
        self.field = field


class CalendarValidationError(JournalError):
    """Exception raised when calendar validation fails."""

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


class CalendarNotFoundError(JournalError):
    """Exception raised when a calendar is not found."""

    def __init__(self, calendar_id: str):
        self.calendar_id = calendar_id
        super().__init__(f"Calendar with ID {calendar_id} not found")


class CalendarInfoValidationError(JournalError):
    """Exception raised when calendar info (EVENT type) validation fails."""

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


class MoodDataValidationError(JournalError):
    """Exception raised when mood data (MOOD_RATING type) validation fails."""

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


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


class PhotoAlbumDataValidationError(JournalError):
    """Exception raised when photo album data (PHOTO_ALBUM type) validation fails."""

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


class PlanDataValidationError(JournalError):
    """Exception raised when plan data (PLAN type) validation fails."""

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


class PlanDocumentValidationError(JournalError):
    """Exception raised when plan document validation fails."""

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


class TravelDataValidationError(JournalError):
    """Exception raised when travel data (TRAVEL type) validation fails."""

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


class TravelFlightValidationError(JournalError):
    """Exception raised when travel flight validation fails."""

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


class TravelAccommodationValidationError(JournalError):
    """Exception raised when travel accommodation validation fails."""

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


class TravelTransportationValidationError(JournalError):
    """Exception raised when travel transportation validation fails."""

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")
