"""Address validation service using pycountry and python-stdnum."""

import pycountry
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.entities import ContactAddress
from app.core.contacts.models.exceptions import ContactValidationError


class AddressValidationService:
    """Service for validating international addresses using external libraries."""

    def __init__(self) -> None:
        pass

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
            # Import specific postal code validators based on country
            if country_code == "NL":
                from stdnum.nl import postcode

                if not postcode.is_valid(postal_code):
                    raise ContactValidationError(
                        "postal_code", f"Invalid Dutch postal code: {postal_code}"
                    )
            elif country_code == "SE":
                from stdnum.se import postal_code as se_postal

                if not se_postal.is_valid(postal_code):
                    raise ContactValidationError(
                        "postal_code", f"Invalid Swedish postal code: {postal_code}"
                    )
            elif country_code == "ES":
                # Spanish postal codes - basic validation since stdnum.es doesn't have postcode
                if not (postal_code.isdigit() and len(postal_code) == 5):
                    raise ContactValidationError(
                        "postal_code",
                        f"Invalid Spanish postal code: {postal_code}. Must be 5 digits.",
                    )
            # Add more countries as they become available in python-stdnum
            else:
                # For countries without specific validation, do basic format check
                if not postal_code.replace(" ", "").replace("-", "").isalnum():
                    raise ContactValidationError(
                        "postal_code", f"Invalid postal code format: {postal_code}"
                    )

        except ImportError as e:
            # If specific country module not available, do basic validation
            if not postal_code.replace(" ", "").replace("-", "").isalnum():
                raise ContactValidationError(
                    "postal_code", f"Invalid postal code format: {postal_code}"
                ) from e
        except Exception as e:
            if isinstance(e, ContactValidationError):
                raise
            # For any other validation errors, provide generic message
            raise ContactValidationError(
                "postal_code", f"Invalid postal code: {postal_code}"
            ) from e

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

        # Australia specific rules
        if country_code == "AU":
            if address.region and address.region not in [
                "NSW",
                "VIC",
                "QLD",
                "WA",
                "SA",
                "TAS",
                "ACT",
                "NT",
            ]:
                raise ContactValidationError(
                    "region", f"Invalid Australian state/territory: {address.region}"
                )

        # US specific rules
        elif country_code == "US":
            if address.region and len(address.region) == 2:
                # Validate US state codes (basic check)
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
                if address.region not in us_states:
                    raise ContactValidationError(
                        "region", f"Invalid US state code: {address.region}"
                    )

        # Canada specific rules
        elif country_code == "CA":
            if address.region and len(address.region) == 2:
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
                if address.region not in ca_provinces:
                    raise ContactValidationError(
                        "region",
                        f"Invalid Canadian province/territory: {address.region}",
                    )

        # Add more country-specific rules as needed

    async def validate_with_transaction(
        self, address: ContactAddress, _transaction: AsyncConnection | None = None
    ) -> None:
        """Validate address with transaction context (for future database lookups)."""
        # For now, just call the regular validation
        # In the future, this could include database lookups for address verification
        self.validate_address_format(address)
