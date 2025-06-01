"""Unit tests for contacts domain exceptions."""


from app.core.contacts.models.exceptions import (
    ContactDomainError,
    ContactHistoryError,
    ContactNotFoundError,
    ContactValidationError,
    DuplicateEmailError,
    DuplicateTagNameError,
    InvalidAddressError,
    InvalidCountryCodeError,
    InvalidEmailError,
    InvalidPhoneNumberError,
    InvalidTagNameError,
    PrimaryAddressConflictError,
    PrimaryMethodConflictError,
    TagNotFoundError,
    TooManyTagsError,
)


class TestContactDomainError:
    """Test ContactDomainError base exception."""

    def test_create_with_default_status_code(self):
        """Test creating exception with default status code."""
        error = ContactDomainError("Test error")
        assert str(error) == "Test error"
        assert error.message == "Test error"
        assert error.status_code == 400

    def test_create_with_custom_status_code(self):
        """Test creating exception with custom status code."""
        error = ContactDomainError("Test error", 500)
        assert str(error) == "Test error"
        assert error.message == "Test error"
        assert error.status_code == 500


class TestContactNotFoundError:
    """Test ContactNotFoundError exception."""

    def test_create_error(self):
        """Test creating ContactNotFoundError."""
        error = ContactNotFoundError(123)
        assert str(error) == "Contact with ID 123 not found"
        assert error.message == "Contact with ID 123 not found"
        assert error.status_code == 404
        assert error.contact_id == 123


class TestTagNotFoundError:
    """Test TagNotFoundError exception."""

    def test_create_error(self):
        """Test creating TagNotFoundError."""
        error = TagNotFoundError(456)
        assert str(error) == "Tag with ID 456 not found"
        assert error.message == "Tag with ID 456 not found"
        assert error.status_code == 404
        assert error.tag_id == 456


class TestDuplicateEmailError:
    """Test DuplicateEmailError exception."""

    def test_create_error(self):
        """Test creating DuplicateEmailError."""
        error = DuplicateEmailError("test@example.com", 123)
        expected_message = "Email address 'test@example.com' is already associated with contact ID 123"
        assert str(error) == expected_message
        assert error.message == expected_message
        assert error.status_code == 409
        assert error.email == "test@example.com"
        assert error.existing_contact_id == 123


class TestDuplicateTagNameError:
    """Test DuplicateTagNameError exception."""

    def test_create_error(self):
        """Test creating DuplicateTagNameError."""
        error = DuplicateTagNameError("work")
        assert str(error) == "Tag name 'work' already exists"
        assert error.message == "Tag name 'work' already exists"
        assert error.status_code == 409
        assert error.tag_name == "work"


class TestInvalidTagNameError:
    """Test InvalidTagNameError exception."""

    def test_create_error(self):
        """Test creating InvalidTagNameError."""
        error = InvalidTagNameError("invalid tag")
        expected_message = "Tag name 'invalid tag' contains invalid characters. Only alphanumeric, -, _, & allowed"
        assert str(error) == expected_message
        assert error.message == expected_message
        assert error.status_code == 400
        assert error.tag_name == "invalid tag"


class TestTooManyTagsError:
    """Test TooManyTagsError exception."""

    def test_create_error(self):
        """Test creating TooManyTagsError."""
        error = TooManyTagsError(26, 123)
        expected_message = "Contact 123 has 26 tags. Maximum allowed is 25"
        assert str(error) == expected_message
        assert error.message == expected_message
        assert error.status_code == 400
        assert error.current_count == 26
        assert error.contact_id == 123


class TestContactValidationError:
    """Test ContactValidationError exception."""

    def test_create_error(self):
        """Test creating ContactValidationError."""
        error = ContactValidationError("first_name", "First name is required")
        expected_message = "Validation error for first_name: First name is required"
        assert str(error) == expected_message
        assert error.message == expected_message
        assert error.status_code == 400
        assert error.field == "first_name"


class TestInvalidEmailError:
    """Test InvalidEmailError exception."""

    def test_create_error(self):
        """Test creating InvalidEmailError."""
        error = InvalidEmailError("invalid-email")
        assert str(error) == "Invalid email format: invalid-email"
        assert error.message == "Invalid email format: invalid-email"
        assert error.status_code == 400
        assert error.email == "invalid-email"


class TestInvalidPhoneNumberError:
    """Test InvalidPhoneNumberError exception."""

    def test_create_error(self):
        """Test creating InvalidPhoneNumberError."""
        error = InvalidPhoneNumberError("abc-def")
        assert str(error) == "Invalid phone number format: abc-def"
        assert error.message == "Invalid phone number format: abc-def"
        assert error.status_code == 400
        assert error.phone == "abc-def"


class TestInvalidCountryCodeError:
    """Test InvalidCountryCodeError exception."""

    def test_create_error(self):
        """Test creating InvalidCountryCodeError."""
        error = InvalidCountryCodeError("aus")
        expected_message = "Invalid country code: aus. Must be 2 uppercase letters (ISO 3166-1 alpha-2)"
        assert str(error) == expected_message
        assert error.message == expected_message
        assert error.status_code == 400
        assert error.country_code == "aus"


class TestInvalidAddressError:
    """Test InvalidAddressError exception."""

    def test_create_error(self):
        """Test creating InvalidAddressError."""
        error = InvalidAddressError("Street address is required")
        assert str(error) == "Invalid address: Street address is required"
        assert error.message == "Invalid address: Street address is required"
        assert error.status_code == 400


class TestPrimaryMethodConflictError:
    """Test PrimaryMethodConflictError exception."""

    def test_create_error(self):
        """Test creating PrimaryMethodConflictError."""
        error = PrimaryMethodConflictError(123, "email")
        expected_message = "Contact 123 already has a primary email. Only one primary method per type allowed"
        assert str(error) == expected_message
        assert error.message == expected_message
        assert error.status_code == 409
        assert error.contact_id == 123
        assert error.method_type == "email"


class TestPrimaryAddressConflictError:
    """Test PrimaryAddressConflictError exception."""

    def test_create_error(self):
        """Test creating PrimaryAddressConflictError."""
        error = PrimaryAddressConflictError(123)
        expected_message = "Contact 123 already has a primary address. Only one primary address allowed"
        assert str(error) == expected_message
        assert error.message == expected_message
        assert error.status_code == 409
        assert error.contact_id == 123


class TestContactHistoryError:
    """Test ContactHistoryError exception."""

    def test_create_error(self):
        """Test creating ContactHistoryError."""
        error = ContactHistoryError("Failed to record change")
        assert str(error) == "Contact history error: Failed to record change"
        assert error.message == "Contact history error: Failed to record change"
        assert error.status_code == 500
