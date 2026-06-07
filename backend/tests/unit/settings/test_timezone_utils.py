"""Unit tests for timezone formatting utilities."""

from datetime import UTC, datetime

import pytest

from app.core.settings.timezone_utils import (
    DEFAULT_TIMEZONE,
    format_datetime,
    isoformat_in_tz,
    now_in_tz,
    resolve_timezone,
    to_user_tz,
)


@pytest.mark.unit
class TestResolveTimezone:
    def test_valid_iana_name(self) -> None:
        tz = resolve_timezone("Australia/Sydney")
        assert tz.key == "Australia/Sydney"

    def test_none_falls_back_to_utc(self) -> None:
        assert resolve_timezone(None).key == DEFAULT_TIMEZONE

    def test_empty_falls_back_to_utc(self) -> None:
        assert resolve_timezone("").key == DEFAULT_TIMEZONE

    def test_invalid_name_falls_back_to_utc(self) -> None:
        assert resolve_timezone("Not/A_Zone").key == DEFAULT_TIMEZONE


@pytest.mark.unit
class TestToUserTz:
    def test_naive_datetime_treated_as_utc(self) -> None:
        naive = datetime(2026, 6, 7, 0, 0, 0)
        local = to_user_tz(naive, resolve_timezone("Australia/Sydney"))
        # Sydney is UTC+10 in winter (June)
        assert local.hour == 10
        assert local.tzinfo is not None

    def test_aware_datetime_converted(self) -> None:
        aware = datetime(2026, 6, 7, 0, 0, 0, tzinfo=UTC)
        local = to_user_tz(aware, resolve_timezone("Australia/Sydney"))
        assert local.utcoffset() is not None
        assert local.hour == 10


@pytest.mark.unit
class TestNowInTz:
    def test_uses_provided_now(self) -> None:
        fixed = datetime(2026, 6, 7, 0, 0, 0, tzinfo=UTC)
        local = now_in_tz("Australia/Sydney", now=fixed)
        assert local.hour == 10
        assert local.date().isoformat() == "2026-06-07"

    def test_naive_now_treated_as_utc(self) -> None:
        fixed = datetime(2026, 6, 7, 0, 0, 0)
        local = now_in_tz("Australia/Sydney", now=fixed)
        assert local.hour == 10


@pytest.mark.unit
class TestFormatDatetime:
    def test_includes_explicit_timezone_label_and_offset(self) -> None:
        dt = datetime(2026, 6, 7, 0, 0, 0, tzinfo=UTC)
        result = format_datetime(dt, "Australia/Sydney")
        assert "2026-06-07 10:00:00" in result
        assert "AEST" in result
        assert "+10:00" in result

    def test_utc_includes_utc_label(self) -> None:
        dt = datetime(2026, 6, 7, 12, 0, 0, tzinfo=UTC)
        result = format_datetime(dt, "UTC")
        assert "2026-06-07 12:00:00" in result
        assert "UTC" in result
        assert "+00:00" in result

    def test_naive_treated_as_utc(self) -> None:
        dt = datetime(2026, 6, 7, 12, 0, 0)
        result = format_datetime(dt, "UTC")
        assert "2026-06-07 12:00:00" in result


@pytest.mark.unit
class TestIsoformatInTz:
    def test_includes_offset(self) -> None:
        dt = datetime(2026, 6, 7, 0, 0, 0, tzinfo=UTC)
        result = isoformat_in_tz(dt, "Australia/Sydney")
        assert result.startswith("2026-06-07T10:00:00")
        assert result.endswith("+10:00")

    def test_naive_treated_as_utc(self) -> None:
        dt = datetime(2026, 6, 7, 0, 0, 0)
        result = isoformat_in_tz(dt, "UTC")
        assert result.startswith("2026-06-07T00:00:00")
        assert result.endswith("+00:00")
