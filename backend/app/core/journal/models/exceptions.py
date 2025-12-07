"""Exceptions for the journal domain."""


class JournalError(Exception):
    """Base exception for journal domain errors."""

    pass


class JournalValidationError(JournalError):
    """Exception raised when journal validation fails."""

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


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
