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

    def test_a_naive_datetime_is_read_as_utc(self) -> None:
        """``field_history.created_at`` is a ``timestamptz``, so a naive value
        is interpreted in the database session's timezone — silently moving the
        change by the server's UTC offset.

        The projection is handed naive timestamps in the ordinary case:
        ``outbox_events.occurred_at`` is a ``timestamp`` *without* time zone, so
        the offset is already gone by the time the relay serialises the row and
        ``stream_event_to_outbox_event`` parses it back. Everything in this
        system stamps ``datetime.now(tz=UTC)``, so a naive one is UTC and saying
        so here is what keeps history on the right day.
        """
        assert SqlFieldHistoryRepository._coerce_created_at(
            datetime(2024, 1, 2, 3, 4, 5)
        ) == datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)

    def test_a_naive_iso_string_is_read_as_utc(self) -> None:
        assert SqlFieldHistoryRepository._coerce_created_at(
            "2024-01-02T03:04:05"
        ) == datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)

    def test_malformed_string_falls_back_to_none(self) -> None:
        """A bad timestamp must not raise (which would dead-letter the event);
        it falls back to None so the DB default (now()) applies."""
        assert SqlFieldHistoryRepository._coerce_created_at("not-a-timestamp") is None
