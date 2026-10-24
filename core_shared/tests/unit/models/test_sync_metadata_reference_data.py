"""Reading the address fallback a link records (#1820)."""

import json

import pytest

from core_shared.models.sync_metadata import (
    ADDRESS_FALLBACK_COUNTRY_KEY,
    recorded_address_fallback,
)


def test_reads_the_recorded_country() -> None:
    reference_data = json.dumps(
        {"synced_tags": ["Kin"], ADDRESS_FALLBACK_COUNTRY_KEY: "NZ"}
    )

    assert recorded_address_fallback(reference_data) == "NZ"


@pytest.mark.parametrize(
    "reference_data",
    [
        None,
        "",
        "not json",
        json.dumps(["a", "list"]),
        json.dumps({"synced_tags": []}),
        json.dumps({ADDRESS_FALLBACK_COUNTRY_KEY: None}),
        json.dumps({ADDRESS_FALLBACK_COUNTRY_KEY: 61}),
    ],
    ids=[
        "none",
        "empty",
        "malformed",
        "not-an-object",
        "never-recorded",
        "null",
        "not-text",
    ],
)
def test_anything_else_records_no_fallback(reference_data: str | None) -> None:
    """No record keeps every countryless address: the safe reading."""
    assert recorded_address_fallback(reference_data) is None
