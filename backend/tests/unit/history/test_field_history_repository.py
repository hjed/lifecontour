"""Unit tests for SqlFieldHistoryRepository pure helpers."""

from datetime import UTC, datetime

from app.core.history.adapters.sql.field_history_repository import (
    SqlFieldHistoryRepository,
)


class TestCoerceCreatedAt:
    """`_coerce_created_at` normalises an entry's created_at for binding."""

    def test_none_passes_through(self) -> None:
        assert SqlFieldHistoryRepository._coerce_created_at(None) is None

    def test_datetime_passes_through(self) -> None:
        dt = datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)
        assert SqlFieldHistoryRepository._coerce_created_at(dt) is dt

    def test_iso_string_is_parsed(self) -> None:
        result = SqlFieldHistoryRepository._coerce_created_at(
            "2024-01-02T03:04:05+00:00"
        )
        assert result == datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)

    def test_malformed_string_falls_back_to_none(self) -> None:
        """A bad timestamp must not raise (which would dead-letter the event);
        it falls back to None so the DB default (now()) applies."""
        assert SqlFieldHistoryRepository._coerce_created_at("not-a-timestamp") is None
