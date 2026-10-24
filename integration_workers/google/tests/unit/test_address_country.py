"""The country a Google address without one is imported with (#1820).

Tried in order: the contact's primary phone, then the country all its other
phones agree on, then the syncing user's default country. Only international
(``+``) numbers say where they are.
"""

from typing import Any

import pytest

from address_country import resolve_address_country
from api_models import GooglePhoneNumber

AU_MOBILE = "+61412345678"
NZ_MOBILE = "+6421234567"
GB_LANDLINE = "+442079460958"
US_NUMBER = "+12125550123"
CA_NUMBER = "+14165550199"


def _phone(
    value: str, *, canonical: str | None = None, primary: bool = False
) -> GooglePhoneNumber:
    data: dict[str, Any] = {"value": value, "metadata": {"primary": primary}}
    if canonical is not None:
        data["canonicalForm"] = canonical
    return GooglePhoneNumber.model_validate(data)


class TestOnePhone:
    @pytest.mark.parametrize(
        ("number", "country"),
        [(AU_MOBILE, "AU"), (US_NUMBER, "US"), (CA_NUMBER, "CA"), (GB_LANDLINE, "GB")],
        ids=["AU", "US", "CA-shares-+1", "GB"],
    )
    def test_an_international_number_gives_its_country(
        self, number: str, country: str
    ) -> None:
        assert resolve_address_country([_phone(number)], None) == country

    def test_reads_the_canonical_form_google_computed(self) -> None:
        phone = _phone("0412 345 678", canonical=AU_MOBILE)

        assert resolve_address_country([phone], None) == "AU"

    def test_a_national_number_says_nothing(self) -> None:
        assert resolve_address_country([_phone("0412 345 678")], "NZ") == "NZ"

    @pytest.mark.parametrize(
        "number",
        ["+999123", "+80012345678", "+61 1234 5678", "+61 999", "+38344123456"],
        ids=["unparseable", "non-geographic", "invalid", "too-short", "not-iso-3166"],
    )
    def test_a_number_with_no_country_says_nothing(self, number: str) -> None:
        assert resolve_address_country([_phone(number)], "NZ") == "NZ"


class TestSeveralPhones:
    def test_the_primary_phone_wins_over_the_others(self) -> None:
        phones = [_phone(AU_MOBILE), _phone(GB_LANDLINE, primary=True)]

        assert resolve_address_country(phones, "NZ") == "GB"

    def test_a_primary_with_no_country_falls_to_the_others(self) -> None:
        phones = [_phone("0412 345 678", primary=True), _phone(AU_MOBILE)]

        assert resolve_address_country(phones, "NZ") == "AU"

    def test_other_phones_that_agree_give_their_country(self) -> None:
        phones = [_phone(AU_MOBILE), _phone("+61 2 9374 4000")]

        assert resolve_address_country(phones, "NZ") == "AU"

    def test_other_phones_that_disagree_fall_to_the_default(self) -> None:
        phones = [_phone(AU_MOBILE), _phone(GB_LANDLINE)]

        assert resolve_address_country(phones, "NZ") == "NZ"


class TestDefaultCountry:
    def test_no_phones_gives_the_default(self) -> None:
        assert resolve_address_country([], "NZ") == "NZ"

    def test_no_phones_and_no_default_gives_none(self) -> None:
        assert resolve_address_country([], None) is None

    def test_a_lowercase_default_is_normalised(self) -> None:
        assert resolve_address_country([], " nz ") == "NZ"

    @pytest.mark.parametrize("default", ["", "NZL", "1A", "ZZ"])
    def test_a_default_that_is_not_a_country_is_ignored(self, default: str) -> None:
        assert resolve_address_country([], default) is None

    def test_a_phone_beats_the_default(self) -> None:
        assert resolve_address_country([_phone(NZ_MOBILE)], "AU") == "NZ"
