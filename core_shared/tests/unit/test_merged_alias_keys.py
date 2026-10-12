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


def test_a_record_locks_the_same_keys_in_either_vocabulary() -> None:
    """The merge and a sync must contend for one lock per record.

    The merge names a record as its link store does, the backend processor
    as its payload does; serialising them only works if both reach the
    same key.
    """
    from core_shared.merged_alias_keys import merged_alias_lock_keys

    by_payload = merged_alias_lock_keys("u1", "strava", "strava:222", None)
    by_store = merged_alias_lock_keys("u1", "strava", "222", None)

    assert by_payload == by_store == ["merged_alias:u1:strava:222"]


def test_an_identity_is_locked_too_and_keys_come_sorted() -> None:
    """Another calendar's copy shares only the identity, so it is locked on."""
    from core_shared.merged_alias_keys import merged_alias_lock_keys

    keys = merged_alias_lock_keys("u1", "google", "evt-1", "token")

    assert keys == sorted(keys)
    assert set(keys) == {
        "merged_alias:u1:google_calendar:evt-1",
        "merged_alias_identity:u1:google_calendar:token",
    }


def test_an_unaliasable_record_locks_nothing() -> None:
    from core_shared.merged_alias_keys import merged_alias_lock_keys

    assert merged_alias_lock_keys("u1", "snipeit_checkout", "x", "t") == []
