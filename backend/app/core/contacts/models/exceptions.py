"""Custom exceptions for the contacts domain."""

from app.core.exceptions import DomainError


class ContactDomainError(DomainError):
    """Base exception for contact domain errors."""
    pass


class ContactNotFoundError(ContactDomainError):
    """Contact not found in repository."""

    def __init__(self, contact_id: int):
        super().__init__(f"Contact with ID {contact_id} not found", 404)
        self.contact_id = contact_id


class TagNotFoundError(ContactDomainError):
    """Tag not found in repository."""

    def __init__(self, tag_id: int):
        super().__init__(f"Tag with ID {tag_id} not found", 404)
        self.tag_id = tag_id


class DuplicateEmailError(ContactDomainError):
    """Email address already exists for another contact."""

    def __init__(self, email: str, existing_contact_id: int):
        super().__init__(
            f"Email address '{email}' is already associated with contact ID {existing_contact_id}",
            409
        )
        self.email = email
        self.existing_contact_id = existing_contact_id


class DuplicateTagNameError(ContactDomainError):
    """Tag name already exists."""

    def __init__(self, tag_name: str):
        super().__init__(f"Tag name '{tag_name}' already exists", 409)
        self.tag_name = tag_name


class InvalidTagNameError(ContactDomainError):
    """Tag name contains invalid characters."""

    def __init__(self, tag_name: str):
        super().__init__(
            f"Tag name '{tag_name}' contains invalid characters. Only alphanumeric, -, _, & allowed",
            400
        )
        self.tag_name = tag_name


class TooManyTagsError(ContactDomainError):
    """Contact has too many tags assigned."""

    def __init__(self, current_count: int, contact_id: int):
        super().__init__(
            f"Contact {contact_id} has {current_count} tags. Maximum allowed is 25",
            400
        )
        self.current_count = current_count
        self.contact_id = contact_id


class ContactValidationError(ContactDomainError):
    """Contact data validation failed."""

    def __init__(self, field: str, message: str):
        super().__init__(f"Validation error for {field}: {message}", 400)
        self.field = field


class InvalidEmailError(ContactDomainError):
    """Invalid email format."""

    def __init__(self, email: str):
        super().__init__(f"Invalid email format: {email}", 400)
        self.email = email


class InvalidPhoneNumberError(ContactDomainError):
    """Invalid phone number format."""

    def __init__(self, phone: str):
        super().__init__(f"Invalid phone number format: {phone}", 400)
        self.phone = phone


class InvalidCountryCodeError(ContactDomainError):
    """Invalid country code format."""

    def __init__(self, country_code: str):
        super().__init__(
            f"Invalid country code: {country_code}. Must be 2 uppercase letters (ISO 3166-1 alpha-2)",
            400
        )
        self.country_code = country_code


class InvalidAddressError(ContactDomainError):
    """Invalid address format."""

    def __init__(self, message: str):
        super().__init__(f"Invalid address: {message}", 400)


class PrimaryMethodConflictError(ContactDomainError):
    """Attempt to set multiple primary methods of the same type."""

    def __init__(self, contact_id: int, method_type: str):
        super().__init__(
            f"Contact {contact_id} already has a primary {method_type}. Only one primary method per type allowed",
            409
        )
        self.contact_id = contact_id
        self.method_type = method_type


class PrimaryAddressConflictError(ContactDomainError):
    """Attempt to set multiple primary addresses."""

    def __init__(self, contact_id: int):
        super().__init__(
            f"Contact {contact_id} already has a primary address. Only one primary address allowed",
            409
        )
        self.contact_id = contact_id


class ContactHistoryError(ContactDomainError):
    """Error recording contact history."""

    def __init__(self, message: str):
        super().__init__(f"Contact history error: {message}", 500)
