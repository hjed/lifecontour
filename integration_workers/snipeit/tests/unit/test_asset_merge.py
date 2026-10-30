"""Tests for the per-column three-way merge of a Snipe-IT asset (#1898)."""

from dataclasses import replace
from datetime import date

from core_shared.sync_base import entry_key

from asset_merge import (
    AssetValues,
    base_after,
    base_of,
    holds_other_values,
    merge_pull,
    merge_push,
    payload_for,
    pull_base,
    push_base,
)

SYNCED = AssetValues(
    name="Tent",
    serial_number="SN-1",
    purchase_date=date(2024, 1, 15),
    model="Hubba",
    manufacturer="MSR",
)


class TestBaseOf:
    def test_every_pushed_column_is_keyed(self) -> None:
        assert set(base_of(SYNCED)) == {"name", "serial_number", "purchase_date"}

    def test_none_is_keyed_apart_from_any_value(self) -> None:
        cleared = base_of(replace(SYNCED, serial_number=None))
        assert cleared["serial_number"] != base_of(SYNCED)["serial_number"]
        assert (
            cleared["serial_number"]
            != base_of(replace(SYNCED, serial_number=""))["serial_number"]
        )

    def test_date_is_keyed_by_its_iso_string(self) -> None:
        assert base_of(SYNCED)["purchase_date"] == frozenset({entry_key("2024-01-15")})

    def test_name_keys_as_the_import_stores_it(self) -> None:
        assert base_of(replace(SYNCED, name="  Tent ")) == base_of(SYNCED)

    def test_equal_values_give_an_equal_base(self) -> None:
        assert base_of(replace(SYNCED)) == base_of(SYNCED)


class TestMergePush:
    def test_a_local_only_change_is_sent(self) -> None:
        local = replace(SYNCED, name="Big Tent")
        merged = merge_push(base_of(SYNCED), local=local, remote=SYNCED)
        assert merged.send == {"name": "Big Tent"}
        assert not merged.remote_won

    def test_a_remote_only_change_is_not_sent(self) -> None:
        remote = replace(SYNCED, serial_number="SN-2")
        merged = merge_push(base_of(SYNCED), local=SYNCED, remote=remote)
        assert merged.send == {}
        assert merged.remote_won

    def test_local_and_remote_changes_to_different_columns_merge(self) -> None:
        local = replace(SYNCED, name="Big Tent")
        remote = replace(SYNCED, serial_number="SN-2")
        merged = merge_push(base_of(SYNCED), local=local, remote=remote)
        assert merged.send == {"name": "Big Tent"}
        assert merged.remote_won

    def test_the_same_change_on_both_sides_is_not_sent(self) -> None:
        both = replace(SYNCED, name="Big Tent")
        merged = merge_push(base_of(SYNCED), local=both, remote=both)
        assert merged.send == {}
        assert not merged.remote_won

    def test_a_conflict_sends_the_local_value(self) -> None:
        local = replace(SYNCED, name="Local Tent")
        remote = replace(SYNCED, name="Remote Tent")
        merged = merge_push(base_of(SYNCED), local=local, remote=remote)
        assert merged.send == {"name": "Local Tent"}

    def test_no_change_sends_nothing(self) -> None:
        merged = merge_push(base_of(SYNCED), local=SYNCED, remote=SYNCED)
        assert merged.send == {}
        assert not merged.remote_won

    def test_a_cleared_date_is_sent_as_none(self) -> None:
        local = replace(SYNCED, purchase_date=None)
        merged = merge_push(base_of(SYNCED), local=local, remote=SYNCED)
        assert merged.send == {"purchase_date": None}


class TestPushBase:
    def test_a_recorded_base_is_used(self) -> None:
        recorded = base_of(SYNCED)
        base = push_base(
            recorded,
            local=SYNCED,
            remote=SYNCED,
            remote_unchanged=False,
            changed_fields={},
        )
        assert base == recorded

    def test_no_base_and_an_unchanged_remote_takes_the_remote(self) -> None:
        remote = replace(SYNCED, name="Remote Tent")
        base = push_base(
            None,
            local=SYNCED,
            remote=remote,
            remote_unchanged=True,
            changed_fields={},
        )
        assert base == base_of(remote)

    def test_no_base_and_a_changed_remote_takes_the_old_local_values(self) -> None:
        local = replace(SYNCED, name="Big Tent", purchase_date=None)
        remote = replace(SYNCED, serial_number="SN-2")
        base = push_base(
            None,
            local=local,
            remote=remote,
            remote_unchanged=False,
            changed_fields={
                "name": ["Tent", "Big Tent"],
                "purchase_date": ["2024-01-15", None],
            },
        )
        assert base == base_of(SYNCED)
        merged = merge_push(base, local=local, remote=remote)
        assert merged.send == {"name": "Big Tent", "purchase_date": None}
        assert merged.remote_won

    def test_a_column_missing_from_the_recorded_base_falls_back(self) -> None:
        recorded = {"name": base_of(SYNCED)["name"]}
        remote = replace(SYNCED, serial_number="SN-2")
        base = push_base(
            recorded,
            local=SYNCED,
            remote=remote,
            remote_unchanged=False,
            changed_fields={},
        )
        assert base == base_of(SYNCED)

    def test_a_recorded_none_is_not_treated_as_missing(self) -> None:
        recorded = base_of(replace(SYNCED, serial_number=None))
        base = push_base(
            recorded,
            local=SYNCED,
            remote=SYNCED,
            remote_unchanged=True,
            changed_fields={},
        )
        assert base["serial_number"] == recorded["serial_number"]


class TestMergePull:
    def test_an_unpushed_local_edit_is_kept(self) -> None:
        local = replace(SYNCED, name="Big Tent")
        remote = replace(SYNCED, serial_number="SN-2")
        merged = merge_pull(pull_base(base_of(SYNCED), local=local), local, remote)
        assert merged == replace(SYNCED, name="Big Tent", serial_number="SN-2")

    def test_a_conflict_keeps_the_local_value(self) -> None:
        local = replace(SYNCED, name="Local Tent")
        remote = replace(SYNCED, name="Remote Tent")
        merged = merge_pull(pull_base(base_of(SYNCED), local=local), local, remote)
        assert merged.name == "Local Tent"

    def test_pull_only_columns_take_the_remote(self) -> None:
        local = replace(SYNCED, model="Local model")
        remote = replace(SYNCED, model="Hubba Hubba", manufacturer="Other")
        merged = merge_pull(pull_base(base_of(SYNCED), local=local), local, remote)
        assert merged == remote

    def test_without_a_base_the_remote_wins(self) -> None:
        local = replace(SYNCED, name="Big Tent")
        merged = merge_pull(pull_base(None, local=local), local, SYNCED)
        assert merged == SYNCED


class TestBaseAfterPush:
    def test_a_column_both_now_hold_takes_the_new_value(self) -> None:
        local = replace(SYNCED, name="Big Tent")
        base = base_after(base_of(SYNCED), local=local, after=local)
        assert base == base_of(local)

    def test_a_column_left_for_the_pull_keeps_its_base(self) -> None:
        local = replace(SYNCED, name="Big Tent")
        after = replace(local, serial_number="SN-2")
        base = base_after(base_of(SYNCED), local=local, after=after)
        assert base == base_of(local)
        assert merge_pull(base, local, after) == after
        assert merge_push(base, local=local, remote=after).send == {}


class TestHoldsOtherValues:
    def test_equal_values(self) -> None:
        assert not holds_other_values(SYNCED, replace(SYNCED, name=" Tent "))

    def test_a_pushed_column_differs(self) -> None:
        assert holds_other_values(replace(SYNCED, serial_number="SN-2"), SYNCED)

    def test_a_pull_only_column_differs(self) -> None:
        assert holds_other_values(replace(SYNCED, manufacturer="Other"), SYNCED)


class TestPayloadFor:
    def test_columns_map_to_snipeit_fields(self) -> None:
        assert payload_for(
            {
                "name": "Tent",
                "serial_number": "SN-1",
                "purchase_date": date(2024, 1, 15),
            }
        ) == {"name": "Tent", "serial": "SN-1", "purchase_date": "2024-01-15"}

    def test_a_cleared_date_is_sent_empty(self) -> None:
        assert payload_for({"purchase_date": None}) == {"purchase_date": ""}

    def test_a_cleared_serial_is_sent_empty(self) -> None:
        assert payload_for({"serial_number": None}) == {"serial": ""}
