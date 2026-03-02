"""Value objects for the contacts domain."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Email:
    """Email address value object with validation."""

    value: str

    def __post_init__(self) -> None:
        """Validate email format."""
        if not self.value:
            raise ValueError("Email cannot be empty")

        # Basic email validation pattern
        email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        if not re.match(email_pattern, self.value):
            raise ValueError(f"Invalid email format: {self.value}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class PhoneNumber:
    """Phone number value object with international support."""

    value: str

    def __post_init__(self) -> None:
        """Validate phone number format."""
        if not self.value:
            raise ValueError("Phone number cannot be empty")

        # Allow any format for international support
        # Just ensure it contains some digits
        if not re.search(r"\d", self.value):
            raise ValueError("Phone number must contain at least one digit")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class CountryCode:
    """ISO 3166-1 alpha-2 country code value object."""

    value: str

    def __post_init__(self) -> None:
        """Validate country code format."""
        if not self.value:
            raise ValueError("Country code cannot be empty")

        # Must be exactly 2 uppercase letters
        if not re.match(r"^[A-Z]{2}$", self.value):
            raise ValueError(
                f"Country code must be 2 uppercase letters (ISO 3166-1 alpha-2): {self.value}"
            )

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class Address:
    """Structured international address value object."""

    street_line_1: str
    country_code: CountryCode
    street_line_2: str | None = None
    locality: str | None = None  # city/town
    region: str | None = None  # state/province/region
    postal_code: str | None = None

    def __post_init__(self) -> None:
        """Validate address components."""
        if not self.street_line_1.strip():
            raise ValueError("Street line 1 is required")

        # Validate lengths
        if len(self.street_line_1) > 255:
            raise ValueError("Street line 1 cannot exceed 255 characters")

        if self.street_line_2 and len(self.street_line_2) > 255:
            raise ValueError("Street line 2 cannot exceed 255 characters")

        if self.locality and len(self.locality) > 100:
            raise ValueError("Locality cannot exceed 100 characters")

        if self.region and len(self.region) > 100:
            raise ValueError("Region cannot exceed 100 characters")

        if self.postal_code and len(self.postal_code) > 20:
            raise ValueError("Postal code cannot exceed 20 characters")

    def format_single_line(self) -> str:
        """Format address as a single line for display."""
        parts = [self.street_line_1]

        if self.street_line_2:
            parts.append(self.street_line_2)

        if self.locality:
            parts.append(self.locality)

        if self.region:
            parts.append(self.region)

        if self.postal_code:
            parts.append(self.postal_code)

        parts.append(str(self.country_code))

        return ", ".join(parts)


@dataclass(frozen=True)
class TagName:
    """Tag name value object with validation."""

    value: str

    def __post_init__(self) -> None:
        """Validate tag name format."""
        if not self.value:
            raise ValueError("Tag name cannot be empty")

        # Only alphanumeric, hyphens, underscores, and ampersands
        if not re.match(r"^[a-zA-Z0-9_&-]+$", self.value):
            raise ValueError(
                f"Tag name contains invalid characters. Only alphanumeric, -, _, & allowed: {self.value}"
            )

        if len(self.value) > 100:
            raise ValueError("Tag name cannot exceed 100 characters")

    def __str__(self) -> str:
        return self.value
