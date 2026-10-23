"""Address validation and normalisation using pycountry."""

import dataclasses
import unicodedata
from functools import cache

import pycountry
from core_shared.models.contacts.entities import ContactAddress
from core_shared.models.contacts.exceptions import ContactValidationError
from sqlalchemy.ext.asyncio import AsyncConnection

# Countries whose region is mapped onto its ISO 3166-2 subdivision code. They
# are the ones regions were once validated for; elsewhere a region is free text.
_NORMALISED_REGION_COUNTRIES = frozenset({"AU", "US", "CA"})


class AddressValidationService:
    """Validates and normalises international addresses.

    A badly typed region or postcode must never fail a contact - on import it
    would dead-letter the whole contact (#1820) - so neither is rejected: a
    known region is normalised to its code, and postcodes are not checked.
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
        """The region as stored: a known AU/US/CA one as its code.

        A subdivision's code or name is recognised whatever its case, accents
        or surrounding space ("new south wales", "Québec"). A blank region is
        ``None``; any other is kept as written, trimmed - an import may have
        inferred the wrong country, and that must not fail the contact.
        """
        if region is None or not region.strip():
            return None
        trimmed = region.strip()
        if country_code not in _NORMALISED_REGION_COUNTRIES:
            return trimmed
        return _subdivision_codes(country_code).get(_fold(trimmed), trimmed)

    def normalise_address(self, address: ContactAddress) -> ContactAddress:
        """``address`` with its region normalised (a copy; value objects rebuilt)."""
        region = self.normalise_region(address.country_code, address.region)
        if region == address.region:
            return address
        return dataclasses.replace(address, region=region)

    def validate_address_format(self, address: ContactAddress) -> None:
        """Validate the address's country and street."""
        self.validate_country_code(address.country_code)

        if not address.street_line_1.strip():
            raise ContactValidationError("street_line_1", "Street address is required")

    async def validate_with_transaction(
        self, address: ContactAddress, _transaction: AsyncConnection | None = None
    ) -> None:
        """Validate address with transaction context (for future database lookups)."""
        self.validate_address_format(address)


def _fold(value: str) -> str:
    """``value`` compared without case or accents."""
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


@cache
def _subdivision_codes(country_code: str) -> dict[str, str]:
    """Each subdivision's folded code and name, mapped to its code ("NSW")."""
    codes: dict[str, str] = {}
    for subdivision in pycountry.subdivisions.get(country_code=country_code) or []:
        code = subdivision.code.split("-", 1)[1]
        codes[_fold(code)] = code
        codes[_fold(subdivision.name)] = code
    return codes
