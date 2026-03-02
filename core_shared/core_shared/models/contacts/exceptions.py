"""Custom exceptions for the contacts domain."""

from core_shared.exceptions import DomainError


class ContactDomainError(DomainError):
    """Base exception for contact domain errors."""

    pass


class ContactValidationError(ContactDomainError):
    """Contact data validation failed."""

    def __init__(self, field: str, message: str):
        super().__init__(f"Validation error for {field}: {message}", 422)
        self.field = field
