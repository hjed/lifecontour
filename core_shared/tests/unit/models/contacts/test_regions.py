"""Address region rules shared by the backend and the Google import (#1820)."""

import pytest

from core_shared.models.contacts.regions import (
    is_unrecognised_region,
    normalise_region,
)


@pytest.mark.parametrize(
    ("country_code", "region", "normalised"),
    [
        ("AU", "NSW", "NSW"),
        ("AU", "nsw", "NSW"),
        ("AU", "  New South Wales ", "NSW"),
        ("AU", "Australian Capital Territory", "ACT"),
        ("US", "ca", "CA"),
        ("US", "district of columbia", "DC"),
        ("CA", "Québec", "QC"),
        ("CA", "quebec", "QC"),
        ("CA", "Newfoundland and Labrador", "NL"),
    ],
)
def test_a_known_region_is_its_code(
    country_code: str, region: str, normalised: str
) -> None:
    assert normalise_region(country_code, region) == normalised
    assert not is_unrecognised_region(country_code, region)


@pytest.mark.parametrize("region", [None, "", "   "])
def test_a_blank_region_is_none_and_never_unrecognised(region: str | None) -> None:
    assert normalise_region("AU", region) is None
    assert not is_unrecognised_region("AU", region)


@pytest.mark.parametrize(
    ("country_code", "region"),
    [("AU", "London"), ("US", "XX"), ("CA", "Somewhere")],
)
def test_an_unknown_region_where_regions_are_known_is_unrecognised(
    country_code: str, region: str
) -> None:
    assert is_unrecognised_region(country_code, region)
    assert normalise_region(country_code, f" {region} ") == region


def test_a_region_elsewhere_is_free_text() -> None:
    """Only AU, US and CA regions are checked; elsewhere they are only trimmed."""
    assert normalise_region("GB", " Greater London ") == "Greater London"
    assert not is_unrecognised_region("GB", "Anything")
