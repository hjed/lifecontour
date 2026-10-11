"""An inbound record is keyed the same way whichever side names it.

Workers and the backend name a record by the payload's ``integration_source``
and the id the worker emitted; the merge names it by the link store it was
read from. The alias key is what makes those two meet.
"""

import pytest

from core_shared.merged_alias_keys import MergedAliasKey, merged_alias_key


@pytest.mark.parametrize(
    ("payload_source", "external_id", "expected"),
    [
        # The Google worker says 'google'; the link store is 'google_calendar'.
        ("google", "evt_20260904T021500Z", ("google_calendar", "evt_20260904T021500Z")),
        ("google_calendar", "evt-1", ("google_calendar", "evt-1")),
        # Strava's synthetic calendar link carries a prefix sync_metadata does not.
        ("strava", "strava:16152597201", ("strava", "16152597201")),
        ("strava", "16152597201", ("strava", "16152597201")),
        ("snipeit_maintenance", "42", ("snipeit_maintenance", "42")),
        ("immich_album", "album-uuid", ("immich_album", "album-uuid")),
    ],
)
def test_payload_names_map_to_the_link_store_key(
    payload_source: str, external_id: str, expected: tuple[str, str]
) -> None:
    assert merged_alias_key(payload_source, external_id) == MergedAliasKey(*expected)


@pytest.mark.parametrize("payload_source", [None, "", "firefly_iii", "snipeit"])
def test_sources_with_no_inbound_records_have_no_key(
    payload_source: str | None,
) -> None:
    """Outbound-only sources (and unknown ones) are never aliased."""
    assert merged_alias_key(payload_source, "anything") is None


def test_a_blank_external_id_has_no_key() -> None:
    assert merged_alias_key("google", "  ") is None
