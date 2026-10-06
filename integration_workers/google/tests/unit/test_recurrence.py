"""Unit tests for the root recurring id a split recurrence is folded under.

Editing a Google recurring event with "this and following events" ends the
original recurrence and starts a new one whose id is the original's plus an
``_R<start>`` suffix. These tests pin which ids are folded back to their root
and which are left alone.
"""

import pytest

from recurrence import root_recurring_event_id


class TestSplitRecurrences:
    """Every split of one recurrence answers with the original's id."""

    def test_timed_split_folds_to_the_original(self) -> None:
        assert (
            root_recurring_event_id("4mjae2cn4uaccq7n41clrsjaso_R20240115T231500")
            == "4mjae2cn4uaccq7n41clrsjaso"
        )

    def test_utc_suffixed_split_folds_to_the_original(self) -> None:
        assert root_recurring_event_id("abc123_R20240115T231500Z") == "abc123"

    def test_all_day_split_folds_to_the_original(self) -> None:
        assert root_recurring_event_id("abc123_R20181009") == "abc123"

    def test_split_of_a_split_folds_to_the_original(self) -> None:
        assert (
            root_recurring_event_id("abc123_R20240115T231500_R20240301T231500")
            == "abc123"
        )

    def test_split_of_an_underscored_id_keeps_its_underscores(self) -> None:
        # Outlook-originated ids start with an underscore and contain no
        # split marker of their own.
        assert root_recurring_event_id("_60q30c1g60o3_R20181009") == "_60q30c1g60o3"


class TestUnsplitRecurrences:
    """Anything that is not a split marker is returned unchanged."""

    def test_an_unsplit_master_is_its_own_root(self) -> None:
        assert root_recurring_event_id("abc123") == "abc123"

    def test_no_recurring_id_stays_none(self) -> None:
        assert root_recurring_event_id(None) is None

    @pytest.mark.parametrize(
        "recurring_event_id",
        [
            "_60q30c1g60o30e1i60o4ac1g60rj8gpl88rj2c1h84s34h9g60s30c1g",
            # Lowercase is a legal base32hex id fragment, not a split marker.
            "abc123_r20240115t231500",
            # A marker must end the id; a date mid-id is not a split.
            "abc123_R20240115T231500x",
            "abc123_R2024",
        ],
    )
    def test_lookalikes_are_not_folded(self, recurring_event_id: str) -> None:
        assert root_recurring_event_id(recurring_event_id) == recurring_event_id
