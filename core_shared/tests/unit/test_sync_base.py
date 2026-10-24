"""Unit tests for the synced base an outbound push merges against (#1861).

The fixtures are deliberately integration-neutral — plain key sets and column
values — because the helpers are meant for every integration that pushes, not
only Google contacts.
"""

import json

import pytest

from core_shared.sync_base import (
    PENDING_IMPORT_KEY,
    SYNCED_ENTRIES_KEY,
    Winner,
    entry_key,
    pending_import,
    recorded_synced_entries,
    remote_unchanged_since_sync,
    serialise_synced_entries,
    three_way_entries,
    three_way_keys,
    three_way_value,
)

pytestmark = pytest.mark.unit


class TestEntryKey:
    def test_is_stable_for_the_same_parts(self) -> None:
        first = entry_key("email", "ada@example.com")
        second = entry_key("email", "ada@example.com")

        assert first == second

    def test_differs_when_any_part_differs(self) -> None:
        assert entry_key("email", "ada@example.com") != entry_key(
            "phone", "ada@example.com"
        )

    def test_does_not_run_parts_together(self) -> None:
        assert entry_key("ab", "c") != entry_key("a", "bc")

    def test_hides_the_value(self) -> None:
        assert "ada@example.com" not in entry_key("email", "ada@example.com")


class TestRecordedSyncedEntries:
    def test_reads_the_recorded_keys_per_field(self) -> None:
        reference_data = json.dumps(
            {SYNCED_ENTRIES_KEY: {"columns": ["a", "b"], "tags": []}}
        )

        assert recorded_synced_entries(reference_data) == {
            "columns": frozenset({"a", "b"}),
            "tags": frozenset(),
        }

    @pytest.mark.parametrize(
        "reference_data",
        [
            None,
            "",
            "not json",
            "[1, 2]",
            json.dumps({"synced_tags": ["x"]}),
            json.dumps({SYNCED_ENTRIES_KEY: None}),
            json.dumps({SYNCED_ENTRIES_KEY: ["a"]}),
        ],
    )
    def test_anything_unreadable_is_no_record(self, reference_data: str | None) -> None:
        assert recorded_synced_entries(reference_data) is None

    def test_a_field_with_unreadable_keys_is_left_out(self) -> None:
        reference_data = json.dumps(
            {SYNCED_ENTRIES_KEY: {"good": ["a"], "bad": "a", "mixed": ["a", 1]}}
        )

        assert recorded_synced_entries(reference_data) == {"good": frozenset({"a"})}

    def test_round_trips_through_serialise(self) -> None:
        entries = {"columns": frozenset({"b", "a"})}
        reference_data = json.dumps(
            {SYNCED_ENTRIES_KEY: serialise_synced_entries(entries)}
        )

        assert recorded_synced_entries(reference_data) == entries

    def test_serialises_keys_in_a_stable_order(self) -> None:
        assert serialise_synced_entries({"f": frozenset({"b", "a"})}) == {
            "f": ["a", "b"]
        }


class TestPendingImport:
    def test_set_when_recorded_true(self) -> None:
        assert pending_import(json.dumps({PENDING_IMPORT_KEY: True})) is True

    @pytest.mark.parametrize(
        "reference_data",
        [
            None,
            "not json",
            json.dumps({}),
            json.dumps({PENDING_IMPORT_KEY: False}),
            json.dumps({PENDING_IMPORT_KEY: "yes"}),
        ],
    )
    def test_anything_else_is_not_pending(self, reference_data: str | None) -> None:
        assert pending_import(reference_data) is False


class TestRemoteUnchangedSinceSync:
    def test_same_version_is_unchanged(self) -> None:
        assert remote_unchanged_since_sync("v1", "v1") is True

    def test_a_different_version_is_changed(self) -> None:
        assert remote_unchanged_since_sync("v1", "v2") is False

    @pytest.mark.parametrize(
        ("recorded", "remote"), [(None, None), ("", ""), (None, "v1"), ("v1", None)]
    )
    def test_an_unknown_version_counts_as_changed(
        self, recorded: str | None, remote: str | None
    ) -> None:
        assert remote_unchanged_since_sync(recorded, remote) is False


class TestThreeWayKeys:
    def test_an_entry_added_remotely_is_kept(self) -> None:
        result = three_way_keys(base={"a"}, local={"a"}, remote={"a", "new"})

        assert result.kept == {"new"}
        assert result.dropped == frozenset()
        assert result.suppressed == frozenset()
        assert result.remote_won is True

    def test_an_entry_deleted_locally_is_dropped(self) -> None:
        result = three_way_keys(base={"a", "b"}, local={"a"}, remote={"a", "b"})

        assert result.dropped == {"b"}
        assert result.kept == frozenset()
        assert result.remote_won is False

    def test_an_entry_deleted_remotely_is_not_pushed_back(self) -> None:
        result = three_way_keys(base={"a", "b"}, local={"a", "b"}, remote={"a"})

        assert result.suppressed == {"b"}
        assert result.remote_won is True

    def test_an_entry_edited_remotely_replaces_the_unchanged_local_one(self) -> None:
        result = three_way_keys(base={"old"}, local={"old"}, remote={"edited"})

        assert result.kept == {"edited"}
        assert result.suppressed == {"old"}

    def test_an_entry_added_locally_is_pushed(self) -> None:
        result = three_way_keys(base={"a"}, local={"a", "mine"}, remote={"a"})

        assert result == three_way_keys(base={"a"}, local={"a"}, remote={"a"})
        assert result.remote_won is False

    def test_an_entry_added_on_both_sides_is_neither_kept_nor_suppressed(
        self,
    ) -> None:
        result = three_way_keys(base=set(), local={"both"}, remote={"both"})

        assert result.kept == frozenset()
        assert result.suppressed == frozenset()

    def test_an_entry_edited_locally_replaces_the_base_one(self) -> None:
        result = three_way_keys(base={"old"}, local={"edited"}, remote={"old"})

        assert result.dropped == {"old"}
        assert result.kept == frozenset()


class TestThreeWayEntries:
    """Entries that can be written several ways carry a key per spelling.

    A phone typed nationally and the same phone in E.164 are one entry: two
    entries match when any of their keys does.
    """

    def test_an_entry_added_remotely_is_kept(self) -> None:
        result = three_way_entries(
            base={"a"}, local=[{"a"}], remote=[{"a", "a2"}, {"new", "new2"}]
        )

        assert result.kept == {1}
        assert result.suppressed == frozenset()
        assert result.remote_won is True

    def test_an_entry_held_on_both_sides_under_other_spellings_is_not_kept(
        self,
    ) -> None:
        """Added on both sides, typed differently but sharing one spelling."""
        result = three_way_entries(
            base=set(), local=[{"e164", "typed"}], remote=[{"e164", "other"}]
        )

        assert result.kept == frozenset()
        assert result.remote_won is False

    def test_an_entry_deleted_locally_is_not_kept(self) -> None:
        result = three_way_entries(
            base={"a", "b"}, local=[{"a"}], remote=[{"a"}, {"b"}]
        )

        assert result.kept == frozenset()
        assert result.remote_won is False

    def test_an_entry_deleted_remotely_is_suppressed(self) -> None:
        result = three_way_entries(
            base={"a", "b", "b-typed"}, local=[{"a"}, {"b-typed"}], remote=[{"a"}]
        )

        assert result.suppressed == {1}
        assert result.remote_won is True

    def test_an_entry_still_held_remotely_under_another_spelling_is_not_suppressed(
        self,
    ) -> None:
        result = three_way_entries(
            base={"b", "b-typed"}, local=[{"b-typed"}], remote=[{"b", "b-typed"}]
        )

        assert result.suppressed == frozenset()

    def test_an_entry_added_locally_is_neither(self) -> None:
        result = three_way_entries(base=set(), local=[{"mine"}], remote=[])

        assert (result.kept, result.suppressed) == (frozenset(), frozenset())

    def test_an_entry_with_no_keys_is_neither(self) -> None:
        """Unkeyed entries are the caller's to judge (e.g. never imported)."""
        result = three_way_entries(base=set(), local=[set()], remote=[set()])

        assert (result.kept, result.suppressed) == (frozenset(), frozenset())


class TestThreeWayValue:
    def test_only_local_changed(self) -> None:
        assert three_way_value(base="a", local="b", remote="a") is Winner.LOCAL

    def test_only_remote_changed(self) -> None:
        assert three_way_value(base="a", local="a", remote="b") is Winner.REMOTE

    def test_neither_changed(self) -> None:
        assert three_way_value(base="a", local="a", remote="a") is Winner.SAME

    def test_both_changed_to_the_same_value(self) -> None:
        assert three_way_value(base="a", local="b", remote="b") is Winner.SAME

    def test_both_changed_differently(self) -> None:
        assert three_way_value(base="a", local="b", remote="c") is Winner.CONFLICT

    def test_none_is_a_value(self) -> None:
        assert three_way_value(base=None, local="b", remote=None) is Winner.LOCAL
