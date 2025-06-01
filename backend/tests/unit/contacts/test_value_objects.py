"""Unit tests for contacts domain value objects."""

import pytest

from app.core.contacts.models.value_objects import (
    Address,
    CountryCode,
    Email,
    PhoneNumber,
    TagName,
)


class TestEmail:
    """Test Email value object."""

    def test_valid_email(self):
        """Test valid email creation."""
        email = Email("test@example.com")
        assert email.value == "test@example.com"
        assert str(email) == "test@example.com"

    def test_valid_email_with_subdomain(self):
        """Test valid email with subdomain."""
        email = Email("user@mail.example.com")
        assert email.value == "user@mail.example.com"

    def test_valid_email_with_plus(self):
        """Test valid email with plus sign."""
        email = Email("user+tag@example.com")
        assert email.value == "user+tag@example.com"

    def test_empty_email_raises_error(self):
        """Test empty email raises ValueError."""
        with pytest.raises(ValueError, match="Email cannot be empty"):
            Email("")

    def test_invalid_email_format_raises_error(self):
        """Test invalid email format raises ValueError."""
        invalid_emails = [
            "invalid",
            "@example.com",
            "user@",
            "user@.com",
            "user.example.com",
            "user@example",
        ]
        for invalid_email in invalid_emails:
            with pytest.raises(ValueError, match="Invalid email format"):
                Email(invalid_email)


class TestPhoneNumber:
    """Test PhoneNumber value object."""

    def test_valid_phone_numbers(self):
        """Test valid phone number creation."""
        valid_phones = [
            "+61 2 1234 5678",
            "02 1234 5678",
            "+1-555-123-4567",
            "(02) 1234 5678",
            "0412 345 678",
            "+44 20 7946 0958",
        ]
        for phone in valid_phones:
            phone_obj = PhoneNumber(phone)
            assert phone_obj.value == phone
            assert str(phone_obj) == phone

    def test_empty_phone_raises_error(self):
        """Test empty phone number raises ValueError."""
        with pytest.raises(ValueError, match="Phone number cannot be empty"):
            PhoneNumber("")

    def test_phone_without_digits_raises_error(self):
        """Test phone number without digits raises ValueError."""
        with pytest.raises(ValueError, match="Phone number must contain at least one digit"):
            PhoneNumber("abc-def-ghij")


class TestCountryCode:
    """Test CountryCode value object."""

    def test_valid_country_codes(self):
        """Test valid country code creation."""
        valid_codes = ["AU", "US", "GB", "DE", "FR", "JP"]
        for code in valid_codes:
            country_code = CountryCode(code)
            assert country_code.value == code
            assert str(country_code) == code

    def test_empty_country_code_raises_error(self):
        """Test empty country code raises ValueError."""
        with pytest.raises(ValueError, match="Country code cannot be empty"):
            CountryCode("")

    def test_invalid_country_code_format_raises_error(self):
        """Test invalid country code format raises ValueError."""
        invalid_codes = [
            "A",      # Too short
            "ABC",    # Too long
            "au",     # Lowercase
            "A1",     # Contains number
            "A-",     # Contains special character
        ]
        for invalid_code in invalid_codes:
            with pytest.raises(ValueError, match="Country code must be 2 uppercase letters"):
                CountryCode(invalid_code)


class TestAddress:
    """Test Address value object."""

    def test_valid_address_minimal(self):
        """Test valid address with minimal required fields."""
        address = Address(
            street_line_1="123 Main St",
            country_code=CountryCode("AU")
        )
        assert address.street_line_1 == "123 Main St"
        assert address.country_code.value == "AU"
        assert address.street_line_2 is None
        assert address.locality is None
        assert address.region is None
        assert address.postal_code is None

    def test_valid_address_complete(self):
        """Test valid address with all fields."""
        address = Address(
            street_line_1="123 Main St",
            street_line_2="Apt 4B",
            locality="Sydney",
            region="NSW",
            postal_code="2000",
            country_code=CountryCode("AU")
        )
        assert address.street_line_1 == "123 Main St"
        assert address.street_line_2 == "Apt 4B"
        assert address.locality == "Sydney"
        assert address.region == "NSW"
        assert address.postal_code == "2000"
        assert address.country_code.value == "AU"

    def test_empty_street_line_1_raises_error(self):
        """Test empty street line 1 raises ValueError."""
        with pytest.raises(ValueError, match="Street line 1 is required"):
            Address(
                street_line_1="",
                country_code=CountryCode("AU")
            )

    def test_whitespace_only_street_line_1_raises_error(self):
        """Test whitespace-only street line 1 raises ValueError."""
        with pytest.raises(ValueError, match="Street line 1 is required"):
            Address(
                street_line_1="   ",
                country_code=CountryCode("AU")
            )

    def test_field_length_validation(self):
        """Test field length validation."""
        # Test street_line_1 too long
        with pytest.raises(ValueError, match="Street line 1 cannot exceed 255 characters"):
            Address(
                street_line_1="x" * 256,
                country_code=CountryCode("AU")
            )

        # Test street_line_2 too long
        with pytest.raises(ValueError, match="Street line 2 cannot exceed 255 characters"):
            Address(
                street_line_1="123 Main St",
                street_line_2="x" * 256,
                country_code=CountryCode("AU")
            )

        # Test locality too long
        with pytest.raises(ValueError, match="Locality cannot exceed 100 characters"):
            Address(
                street_line_1="123 Main St",
                locality="x" * 101,
                country_code=CountryCode("AU")
            )

        # Test region too long
        with pytest.raises(ValueError, match="Region cannot exceed 100 characters"):
            Address(
                street_line_1="123 Main St",
                region="x" * 101,
                country_code=CountryCode("AU")
            )

        # Test postal_code too long
        with pytest.raises(ValueError, match="Postal code cannot exceed 20 characters"):
            Address(
                street_line_1="123 Main St",
                postal_code="x" * 21,
                country_code=CountryCode("AU")
            )

    def test_format_single_line(self):
        """Test single line address formatting."""
        # Minimal address
        address = Address(
            street_line_1="123 Main St",
            country_code=CountryCode("AU")
        )
        assert address.format_single_line() == "123 Main St, AU"

        # Complete address
        address = Address(
            street_line_1="123 Main St",
            street_line_2="Apt 4B",
            locality="Sydney",
            region="NSW",
            postal_code="2000",
            country_code=CountryCode("AU")
        )
        expected = "123 Main St, Apt 4B, Sydney, NSW, 2000, AU"
        assert address.format_single_line() == expected


class TestTagName:
    """Test TagName value object."""

    def test_valid_tag_names(self):
        """Test valid tag name creation."""
        valid_names = [
            "work",
            "family",
            "work-contact",
            "high_priority",
            "client&partner",
            "tag123",
            "a",
            "x" * 100,  # Maximum length
        ]
        for name in valid_names:
            tag_name = TagName(name)
            assert tag_name.value == name
            assert str(tag_name) == name

    def test_empty_tag_name_raises_error(self):
        """Test empty tag name raises ValueError."""
        with pytest.raises(ValueError, match="Tag name cannot be empty"):
            TagName("")

    def test_invalid_tag_name_characters_raise_error(self):
        """Test invalid tag name characters raise ValueError."""
        invalid_names = [
            "tag with spaces",
            "tag@email",
            "tag#hash",
            "tag$dollar",
            "tag%percent",
            "tag.dot",
            "tag/slash",
            "tag\\backslash",
        ]
        for invalid_name in invalid_names:
            with pytest.raises(ValueError, match="Tag name contains invalid characters"):
                TagName(invalid_name)

    def test_tag_name_too_long_raises_error(self):
        """Test tag name too long raises ValueError."""
        with pytest.raises(ValueError, match="Tag name cannot exceed 100 characters"):
            TagName("x" * 101)
