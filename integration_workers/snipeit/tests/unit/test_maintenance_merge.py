"""Tests for the per-field three-way merge of a Snipe-IT maintenance (#1898)."""

import json
from typing import Any

from maintenance_merge import (
    base_after,
    base_of,
    effective_base,
    merge,
    payload_for,
    pull_base,
    push_base,
    queued_by,
    recorded_queued_entries,
)

SYNCED: dict[str, Any] = {
    "name": "Rewaxed skis",
    "notes": "Base layer",
    "asset_maintenance_type": "Maintenance",
    "start_date": "2024-01-15",
    "completion_date": "2024-01-16",
}


def _with(**changes: Any) -> dict[str, Any]:
    return {**SYNCED, **changes}


class TestBaseOf:
    def test_every_field_is_keyed(self) -> None:
        assert set(base_of(SYNCED)) == {
            "name",
            "notes",
            "asset_maintenance_type",
            "start_date",
            "completion_date",
        }

    def test_a_missing_field_keys_as_none(self) -> None:
        missing = {k: v for k, v in SYNCED.items() if k != "completion_date"}
        assert base_of(missing) == base_of(_with(completion_date=None))

    def test_fields_outside_the_merge_are_ignored(self) -> None:
        assert base_of(_with(asset_id=7)) == base_of(SYNCED)


class TestKeyedAsTheJournalHoldsIt:
    def test_a_missing_completion_is_the_start(self) -> None:
        missing = {k: v for k, v in SYNCED.items() if k != "completion_date"}
        assert base_of(missing) == base_of(_with(completion_date="2024-01-15"))

    def test_an_unknown_type_is_the_type_it_imports_as(self) -> None:
        assert base_of(_with(asset_maintenance_type="Cleaning")) == base_of(SYNCED)
        assert base_of(_with(asset_maintenance_type=None)) == base_of(SYNCED)

    def test_an_empty_name_is_the_fallback_title(self) -> None:
        assert base_of(_with(name="")) == base_of(
            _with(name="Gear maintenance: routine maintenance")
        )

    def test_an_untouched_import_of_a_record_without_a_completion_is_not_local(
        self,
    ) -> None:
        remote = {k: v for k, v in SYNCED.items() if k != "completion_date"}
        journal = _with(completion_date="2024-01-15")
        merged = merge(base_of(remote), local=journal, remote=remote)
        assert merged.local_fields == set()


class TestMerge:
    def test_a_local_only_change_is_local(self) -> None:
        merged = merge(base_of(SYNCED), local=_with(name="Waxed"), remote=SYNCED)
        assert merged.local_fields == {"name"}
        assert not merged.remote_won

    def test_a_remote_only_change_is_left_to_the_remote(self) -> None:
        remote = _with(completion_date="2024-01-20")
        merged = merge(base_of(SYNCED), local=SYNCED, remote=remote)
        assert merged.local_fields == set()
        assert merged.remote_won

    def test_changes_to_different_fields_merge(self) -> None:
        merged = merge(
            base_of(SYNCED),
            local=_with(name="Waxed"),
            remote=_with(notes="Edited remotely"),
        )
        assert merged.local_fields == {"name"}
        assert merged.remote_won

    def test_the_same_change_on_both_sides_is_neither(self) -> None:
        both = _with(name="Waxed")
        merged = merge(base_of(SYNCED), local=both, remote=both)
        assert merged.local_fields == set()
        assert not merged.remote_won

    def test_a_conflict_is_local(self) -> None:
        merged = merge(
            base_of(SYNCED), local=_with(name="Local"), remote=_with(name="Remote")
        )
        assert merged.local_fields == {"name"}


class TestDatesStayAPair:
    def test_a_split_that_inverts_the_range_takes_both_dates_from_local(
        self,
    ) -> None:
        base = base_of(_with(start_date="2024-01-11", completion_date="2024-01-20"))
        merged = merge(
            base,
            local=_with(start_date="2024-01-15", completion_date="2024-01-20"),
            remote=_with(start_date="2024-01-11", completion_date="2024-01-12"),
        )
        assert merged.local_fields == {"start_date", "completion_date"}
        assert not merged.remote_won

    def test_a_split_that_keeps_the_range_stays_split(self) -> None:
        base = base_of(_with(start_date="2024-01-11", completion_date="2024-01-20"))
        merged = merge(
            base,
            local=_with(start_date="2024-01-12", completion_date="2024-01-20"),
            remote=_with(start_date="2024-01-11", completion_date="2024-01-25"),
        )
        assert merged.local_fields == {"start_date"}
        assert merged.remote_fields == {"completion_date"}


class TestEffectiveBase:
    def test_a_queued_value_the_journal_holds_is_the_base(self) -> None:
        queued = {"notes": base_of(_with(notes="Edited remotely"))["notes"]}
        local = _with(notes="Edited remotely")
        assert effective_base(base_of(SYNCED), queued, local=local) == base_of(local)

    def test_a_queued_value_the_journal_does_not_hold_yet_is_not(self) -> None:
        queued = {"notes": base_of(_with(notes="Edited remotely"))["notes"]}
        assert effective_base(base_of(SYNCED), queued, local=SYNCED) == base_of(SYNCED)

    def test_nothing_queued_is_the_recorded_base(self) -> None:
        assert effective_base(base_of(SYNCED), None, local=SYNCED) == base_of(SYNCED)


class TestPushBase:
    def test_a_recorded_base_is_used(self) -> None:
        recorded = base_of(SYNCED)
        assert push_base(recorded, remote=_with(name="Remote")) == recorded

    def test_without_a_base_every_differing_local_field_is_sent(self) -> None:
        base = push_base(None, remote=_with(notes="Edited remotely"))
        merged = merge(
            base, local=_with(name="Waxed"), remote=_with(notes="Edited remotely")
        )
        assert merged.local_fields == {"name", "notes"}

    def test_a_field_missing_from_the_recorded_base_falls_back(self) -> None:
        recorded = {"name": base_of(SYNCED)["name"]}
        remote = _with(notes="Edited remotely")
        assert push_base(recorded, remote=remote) == {
            **base_of(remote),
            "name": base_of(SYNCED)["name"],
        }


class TestPullBase:
    def test_without_a_base_the_remote_wins(self) -> None:
        local = _with(name="Waxed")
        merged = merge(pull_base(None, {}, local=local), local=local, remote=SYNCED)
        assert merged.local_fields == set()

    def test_a_queued_value_the_journal_holds_is_agreed(self) -> None:
        local = _with(notes="Edited remotely")
        queued = {"notes": base_of(local)["notes"]}
        assert pull_base(base_of(SYNCED), queued, local=local) == base_of(local)


class TestQueuedBy:
    def test_only_fields_the_journal_does_not_hold_or_keep_are_queued(
        self,
    ) -> None:
        remote = _with(name="Remote", notes="Edited remotely")
        queued = queued_by(
            local=_with(name="Local"), remote=remote, kept=frozenset({"name"})
        )
        assert queued == {"notes": base_of(remote)["notes"]}

    def test_queued_entries_are_read_back(self) -> None:
        queued = {"notes": base_of(_with(notes="Edited remotely"))["notes"]}
        reference = json.dumps({"queued_entries": {"notes": sorted(queued["notes"])}})
        assert recorded_queued_entries(reference) == queued
        assert recorded_queued_entries(None) == {}


class TestBaseAfterPush:
    def test_a_field_both_now_hold_takes_the_new_value(self) -> None:
        local = _with(name="Waxed")
        assert base_after(base_of(SYNCED), local=local, after=local) == base_of(local)

    def test_a_field_left_to_the_remote_keeps_its_base(self) -> None:
        local = _with(name="Waxed")
        after = _with(name="Waxed", notes="Edited remotely")
        base = base_after(base_of(SYNCED), local=local, after=after)
        assert base == base_of(local)
        merged = merge(base, local=local, remote=after)
        assert merged.local_fields == set()
        assert merged.remote_won


class TestPayloadFor:
    def test_only_local_fields_are_sent(self) -> None:
        assert payload_for(
            frozenset({"name", "completion_date"}), _with(name="Waxed")
        ) == {"name": "Waxed", "completion_date": "2024-01-16"}

    def test_a_field_local_cleared_is_sent_empty(self) -> None:
        local = {k: v for k, v in SYNCED.items() if k != "completion_date"}
        assert payload_for(frozenset({"completion_date"}), local) == {
            "completion_date": None
        }
