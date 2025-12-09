"""Exceptions for the journal domain."""


class JournalError(Exception):
    """Base exception for journal domain errors."""

    pass


class JournalFieldValidationError(JournalError):
    """Base exception for field validation errors in journal domain.

    This base class provides common implementation for all field validation errors.
    Subclasses only need to provide a docstring describing the specific validation context.
    """

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


class JournalValidationError(JournalFieldValidationError):
    """Exception raised when journal validation fails."""

    pass


class CalendarValidationError(JournalFieldValidationError):
    """Exception raised when calendar validation fails."""

    pass


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


class JournalNotFoundError(JournalError):
    """Exception raised when a journal is not found."""

    def __init__(self, journal_id: int):
        self.journal_id = journal_id
        super().__init__(f"Journal with ID {journal_id} not found")


class JournalHierarchyError(JournalError):
    """Exception raised when journal hierarchy constraints are violated."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class JournalMaxDepthExceededError(JournalHierarchyError):
    """Exception raised when journal hierarchy exceeds maximum depth."""

    def __init__(self, max_depth: int, attempted_depth: int):
        self.max_depth = max_depth
        self.attempted_depth = attempted_depth
        super().__init__(
            f"Journal hierarchy depth {attempted_depth} exceeds maximum allowed depth of {max_depth}"
        )


class JournalCycleError(JournalHierarchyError):
    """Exception raised when a cycle would be created in journal hierarchy."""

    def __init__(self, journal_id: int, parent_id: int):
        self.journal_id = journal_id
        self.parent_id = parent_id
        super().__init__(
            f"Cannot set journal {journal_id} as child of {parent_id}: would create a cycle"
        )


class JournalContactRelationshipValidationError(JournalFieldValidationError):
    """Exception raised when journal contact relationship validation fails."""

    pass


class JournalTagValidationError(JournalFieldValidationError):
    """Exception raised when journal tag validation fails."""

    pass


class JournalTagAssignmentValidationError(JournalFieldValidationError):
    """Exception raised when journal tag assignment validation fails."""

    pass


class JournalTagNotFoundError(JournalError):
    """Exception raised when a journal tag is not found."""

    def __init__(self, tag_id: str):
        self.tag_id = tag_id
        super().__init__(f"Journal tag with ID {tag_id} not found")


class JournalTagCycleError(JournalError):
    """Exception raised when a cycle would be created in tag hierarchy."""

    def __init__(self, tag_id: str, parent_id: str):
        self.tag_id = tag_id
        self.parent_id = parent_id
        super().__init__(
            f"Cannot set tag {tag_id} as child of {parent_id}: would create a cycle"
        )
