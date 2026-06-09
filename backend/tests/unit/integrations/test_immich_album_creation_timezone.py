"""Unit tests for the journal date-range -> Immich photo-search window.

The journal's ``event_date_range`` is stored in UTC. To find the photos a user
would consider "that day", the range is expanded to full days in the user's
configured timezone and converted back to UTC for the Immich query. This is the
reverse of the worker's album date-range derivation.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.integrations.immich.album_creation_service import compute_search_window


def test_positive_offset_timezone_expands_to_local_day() -> None:
    """The product-spec example: a 15 January journal in Sydney (UTC+11 in
    January) must capture photos taken at 23:00 UTC on 14 January."""
    instant = datetime(2026, 1, 15, 5, 0, tzinfo=UTC)

    after, before = compute_search_window(instant, instant, "Australia/Sydney")

    assert after == "2026-01-14T13:00:00+00:00"
    assert before == "2026-01-15T12:59:59.999999+00:00"


def test_negative_offset_timezone_expands_to_local_day() -> None:
    """A UTC instant on the 15th that is still the 14th in New York maps to the
    New York local day."""
    instant = datetime(2026, 1, 15, 2, 0, tzinfo=UTC)

    after, before = compute_search_window(instant, instant, "America/New_York")

    assert after == "2026-01-14T05:00:00+00:00"
    assert before == "2026-01-15T04:59:59.999999+00:00"


def test_utc_multi_day_range() -> None:
    start = datetime(2026, 3, 10, 8, 0, tzinfo=UTC)
    end = datetime(2026, 3, 12, 20, 0, tzinfo=UTC)

    after, before = compute_search_window(start, end, "UTC")

    assert after == "2026-03-10T00:00:00+00:00"
    assert before == "2026-03-12T23:59:59.999999+00:00"


def test_naive_datetimes_assumed_utc() -> None:
    start = datetime(2026, 1, 15, 5, 0)
    end = datetime(2026, 1, 15, 5, 0)

    after, before = compute_search_window(start, end, "UTC")

    assert after == "2026-01-15T00:00:00+00:00"
    assert before == "2026-01-15T23:59:59.999999+00:00"


def test_unknown_timezone_falls_back_to_utc() -> None:
    instant = datetime(2026, 1, 15, 5, 0, tzinfo=UTC)

    after, before = compute_search_window(instant, instant, "Not/AZone")

    assert after == "2026-01-15T00:00:00+00:00"
    assert before == "2026-01-15T23:59:59.999999+00:00"
