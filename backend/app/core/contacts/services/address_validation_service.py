"""Address validation and normalisation using pycountry."""

import dataclasses

import pycountry
from core_shared.models.contacts.entities import ContactAddress
from core_shared.models.contacts.exceptions import ContactValidationError
from core_shared.models.contacts.regions import (
    is_unrecognised_region,
    normalise_region,
)
from sqlalchemy.ext.asyncio import AsyncConnection


class AddressValidationService:
    """Validates and normalises international addresses.

    A known AU/US/CA region is normalised to its code, whatever its case or
    accents, and postcodes are not checked: a badly typed field must not fail
    - on import, dead-letter - a whole contact (#1820). A region no subdivision
    matches is rejected on a write; the Google import skips such an address
    for the user to review rather than sending it. The rules are shared with
    the import (``core_shared.models.contacts.regions``).
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

    def normalise_region(self, country_code: str, region: str | None) -> str | None:
        """The region as stored: a known AU/US/CA one as its code, blank as None."""
        return normalise_region(country_code, region)

    def normalise_address(self, address: ContactAddress) -> ContactAddress:
        """``address`` with its region normalised (a copy; value objects rebuilt)."""
        region = self.normalise_region(address.country_code, address.region)
        if region == address.region:
            return address
        return dataclasses.replace(address, region=region)

    def validate_address_format(self, address: ContactAddress) -> None:
        """Validate the address's country, street and (AU/US/CA) region."""
        self.validate_country_code(address.country_code)

        if not address.street_line_1.strip():
            raise ContactValidationError("street_line_1", "Street address is required")

        if is_unrecognised_region(address.country_code, address.region):
            raise ContactValidationError(
                "region",
                f"Unrecognised region for {address.country_code}: {address.region}. "
                "Use a state, province or territory name or code",
            )

    async def validate_with_transaction(
        self, address: ContactAddress, _transaction: AsyncConnection | None = None
    ) -> None:
        """Validate address with transaction context (for future database lookups)."""
        self.validate_address_format(address)
