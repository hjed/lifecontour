"""Address validation service using pycountry and python-stdnum."""

import pycountry
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.entities import ContactAddress
from app.core.contacts.models.exceptions import ContactValidationError


class AddressValidationService:
    """Service for validating international addresses using external libraries."""

    def __init__(self) -> None:
        """Initialize the address validation service.

        This service uses external libraries (pycountry, python-stdnum)
        for validating international addresses and postal codes.
        """

    def validate_country_code(self, country_code: str) -> None:
        """Validate country code using pycountry."""
        try:
            country = pycountry.countries.get(alpha_2=country_code)
            if not country:
                raise ContactValidationError(
                    "country_code",
                    f"Invalid country code: {country_code}. Must be valid ISO 3166-1 alpha-2 code",
                )
        except Exception as e:
            raise ContactValidationError(
                "country_code",
                f"Invalid country code: {country_code}. Must be valid ISO 3166-1 alpha-2 code",
            ) from e

    def validate_postal_code(self, postal_code: str, country_code: str) -> None:
        """Validate postal code format for the given country using python-stdnum."""
        if not postal_code:
            return  # Postal code is optional

        try:
            self._validate_country_specific_postal_code(postal_code, country_code)
        except ImportError as e:
            self._validate_basic_postal_code_format(postal_code, e)
        except Exception as e:
            if isinstance(e, ContactValidationError):
                raise
            # For any other validation errors, provide generic message
            raise ContactValidationError(
                "postal_code", f"Invalid postal code: {postal_code}"
            ) from e

    def _validate_country_specific_postal_code(
        self, postal_code: str, country_code: str
    ) -> None:
        """Validate postal code using country-specific rules."""
        if country_code == "NL":
            self._validate_dutch_postal_code(postal_code)
        elif country_code == "SE":
            self._validate_swedish_postal_code(postal_code)
        elif country_code == "ES":
            self._validate_spanish_postal_code(postal_code)
        else:
            self._validate_basic_postal_code_format(postal_code)

    def _validate_dutch_postal_code(self, postal_code: str) -> None:
        """Validate Dutch postal code."""
        from stdnum.nl import postcode

        if not postcode.is_valid(postal_code):
            raise ContactValidationError(
                "postal_code", f"Invalid Dutch postal code: {postal_code}"
            )

    def _validate_swedish_postal_code(self, postal_code: str) -> None:
        """Validate Swedish postal code."""
        from stdnum.se import postal_code as se_postal

        if not se_postal.is_valid(postal_code):
            raise ContactValidationError(
                "postal_code", f"Invalid Swedish postal code: {postal_code}"
            )

    def _validate_spanish_postal_code(self, postal_code: str) -> None:
        """Validate Spanish postal code."""
        if not (postal_code.isdigit() and len(postal_code) == 5):
            raise ContactValidationError(
                "postal_code",
                f"Invalid Spanish postal code: {postal_code}. Must be 5 digits.",
            )

    def _validate_basic_postal_code_format(
        self, postal_code: str, error: Exception | None = None
    ) -> None:
        """Validate basic postal code format for countries without specific validation."""
        if not postal_code.replace(" ", "").replace("-", "").isalnum():
            message = f"Invalid postal code format: {postal_code}"
            if error:
                raise ContactValidationError("postal_code", message) from error
            else:
                raise ContactValidationError("postal_code", message)

    def validate_address_format(self, address: ContactAddress) -> None:
        """Validate address format for the given country."""
        # Validate country code
        self.validate_country_code(address.country_code)

        # Basic validation
        if not address.street_line_1.strip():
            raise ContactValidationError("street_line_1", "Street address is required")

        # Validate postal code if provided
        if address.postal_code:
            self.validate_postal_code(address.postal_code, address.country_code)

        # Country-specific validation rules
        self._validate_country_specific_rules(address)

    def _validate_country_specific_rules(self, address: ContactAddress) -> None:
        """Apply country-specific validation rules."""
        country_code = address.country_code

        if country_code == "AU":
            self._validate_australian_region(address.region)
        elif country_code == "US":
            self._validate_us_region(address.region)
        elif country_code == "CA":
            self._validate_canadian_region(address.region)
        # Add more country-specific rules as needed

    def _validate_australian_region(self, region: str | None) -> None:
        """Validate Australian state/territory codes."""
        if not region:
            return

        valid_regions = ["NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT"]
        if region not in valid_regions:
            raise ContactValidationError(
                "region", f"Invalid Australian state/territory: {region}"
            )

    def _validate_us_region(self, region: str | None) -> None:
        """Validate US state codes."""
        if not region or len(region) != 2:
            return

        us_states = [
            "AL",
            "AK",
            "AZ",
            "AR",
            "CA",
            "CO",
            "CT",
            "DE",
            "FL",
            "GA",
            "HI",
            "ID",
            "IL",
            "IN",
            "IA",
            "KS",
            "KY",
            "LA",
            "ME",
            "MD",
            "MA",
            "MI",
            "MN",
            "MS",
            "MO",
            "MT",
            "NE",
            "NV",
            "NH",
            "NJ",
            "NM",
            "NY",
            "NC",
            "ND",
            "OH",
            "OK",
            "OR",
            "PA",
            "RI",
            "SC",
            "SD",
            "TN",
            "TX",
            "UT",
            "VT",
            "VA",
            "WA",
            "WV",
            "WI",
            "WY",
            "DC",
        ]
        if region not in us_states:
            raise ContactValidationError("region", f"Invalid US state code: {region}")

    def _validate_canadian_region(self, region: str | None) -> None:
        """Validate Canadian province/territory codes."""
        if not region or len(region) != 2:
            return

        ca_provinces = [
            "AB",
            "BC",
            "MB",
            "NB",
            "NL",
            "NS",
            "NT",
            "NU",
            "ON",
            "PE",
            "QC",
            "SK",
            "YT",
        ]
        if region not in ca_provinces:
            raise ContactValidationError(
                "region", f"Invalid Canadian province/territory: {region}"
            )

    async def validate_with_transaction(
        self, address: ContactAddress, _transaction: AsyncConnection | None = None
    ) -> None:
        """Validate address with transaction context (for future database lookups)."""
        # For now, just call the regular validation
        # In the future, this could include database lookups for address verification
        self.validate_address_format(address)
