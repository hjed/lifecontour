"""The country an imported Google address without one is given (#1820).

Google holds addresses typed in by hand or imported from a phone with no
``countryCode``, which the local model requires. The country is taken, in
order, from:

1. the contact's **primary** phone;
2. the country every other phone agrees on;
3. the syncing user's default country (``user_settings.default_country``).

Only international (``+``) numbers count: a national number names no country
without one to read it in. Every answer is an ISO 3166-1 country, as the
backend's address validation requires: libphonenumber also numbers regions
that are not (Kosovo, Ascension Island). Google fills ``canonicalForm`` as E.164 from the
account's region, so a number typed nationally usually still has one.

Inbound import and the push merge must both resolve it this way, from the same
person: the merge keeps only what inbound does not import (#1788), so a
divergence would push the address back beside Google's countryless original.
"""

from collections.abc import Sequence

import phonenumbers
import pycountry

from api_models import GooglePhoneNumber

# What ``region_code_for_number`` answers for a non-geographic number.
_NON_GEOGRAPHIC_REGION = "001"


def resolve_address_country(
    phones: Sequence[GooglePhoneNumber], default_country: str | None
) -> str | None:
    """The country to import a countryless address with, or None to skip it."""
    primary = next((phone for phone in phones if phone.metadata.primary), None)
    if primary is not None and (country := phone_country(primary)) is not None:
        return country

    countries = {
        country
        for phone in phones
        if phone is not primary and (country := phone_country(phone)) is not None
    }
    if len(countries) == 1:
        return countries.pop()
    return _iso_country(default_country)


def phone_country(phone: GooglePhoneNumber) -> str | None:
    """The ISO alpha-2 country of an international, valid number."""
    number = (phone.canonical_form or phone.value).strip()
    if not number.startswith("+"):
        return None
    try:
        parsed = phonenumbers.parse(number, None)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    region = phonenumbers.region_code_for_number(parsed)
    if region is None or region == _NON_GEOGRAPHIC_REGION:
        return None
    return _iso_country(str(region))


def _iso_country(country: str | None) -> str | None:
    """``country`` as an uppercase ISO 3166-1 alpha-2 code, or None.

    The default country is read straight from the database, which only the
    API validates.
    """
    if country is None:
        return None
    normalised = country.strip().upper()
    if len(normalised) != 2 or pycountry.countries.get(alpha_2=normalised) is None:
        return None
    return normalised
