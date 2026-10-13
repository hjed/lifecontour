"""The backend's series key agrees with the Google worker's."""

import pytest

from app.core.integrations.recurrence_keys import root_recurring_event_id


@pytest.mark.parametrize(
    ("recurring_event_id", "root"),
    [
        ("abc123", "abc123"),
        ("abc123_R20260801T090000", "abc123"),
        ("abc123_R20260801T090000Z", "abc123"),
        ("abc123_R20260801", "abc123"),
        ("abc123_R20260801T090000_R20260901T090000", "abc123"),
        ("abc123_20260801T090000Z", "abc123_20260801T090000Z"),
    ],
)
def test_split_suffixes_fold_away(recurring_event_id: str, root: str) -> None:
    assert root_recurring_event_id(recurring_event_id) == root
