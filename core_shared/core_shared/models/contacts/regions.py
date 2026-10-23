"""Address region rules shared by the backend and the integration imports.

An AU, US or CA region given as its ISO 3166-2 subdivision code or name - in
any case, with or without accents ("new south wales", "Québec") - is stored as
the code. One that matches no subdivision is *unrecognised*: the backend
rejects it on a write, and an import skips that address for the user to review
(#1820). The Google push merge reads the same rule, so an address the import
skipped is never treated as one the app owns.
"""

import unicodedata
from functools import cache
from typing import Final

import pycountry

# Countries whose regions are checked against their ISO 3166-2 subdivisions.
# Elsewhere a region is free text.
REGION_CHECKED_COUNTRIES: Final = frozenset({"AU", "US", "CA"})


def normalise_region(country_code: str, region: str | None) -> str | None:
    """The region as stored: a known one's code, ``None`` if blank, else trimmed."""
    if region is None or not region.strip():
        return None
    trimmed = region.strip()
    if country_code not in REGION_CHECKED_COUNTRIES:
        return trimmed
    return _subdivision_codes(country_code).get(_fold(trimmed), trimmed)


def is_unrecognised_region(country_code: str, region: str | None) -> bool:
    """Whether ``region`` names no subdivision of a country whose regions are checked."""
    if country_code not in REGION_CHECKED_COUNTRIES:
        return False
    if region is None or not region.strip():
        return False
    return _fold(region.strip()) not in _subdivision_codes(country_code)


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
