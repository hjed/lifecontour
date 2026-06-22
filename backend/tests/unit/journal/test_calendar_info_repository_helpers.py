"""Unit tests for calendar info repository compatibility helpers."""

from datetime import UTC, date, datetime, time
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from core_shared.models.journals import CalendarInfo

from app.core.journal.adapters.sql.calendar_info_repository import (
    SqlCalendarInfoRepository,
    project_calendar_info_to_linked_calendar,
)


@pytest.mark.unit
class TestProjectCalendarInfoToLinkedCalendar:
    """Test compatibility projection for linked calendars."""

    def test_projects_legacy_calendar_info_to_requested_link(self) -> None:
        """Projecting a legacy event to a linked calendar should preserve event data."""
        original_calendar_id = uuid4()
        linked_calendar_id = uuid4()
        created_at = datetime.now(UTC)
        updated_at = datetime.now(UTC)
        calendar_info = CalendarInfo(
            journal_id=42,
            calendar_id=original_calendar_id,
            start_time=time(9, 0),
            end_time=time(10, 0),
            location="Conference Room A",
            sync_invitees=True,
            created_at=created_at,
            updated_at=updated_at,
        )

        projected = project_calendar_info_to_linked_calendar(
            calendar_info,
            linked_calendar_id,
        )

        assert projected is not calendar_info
        assert projected.journal_id == calendar_info.journal_id
        assert projected.calendar_id == linked_calendar_id
        assert projected.start_time == calendar_info.start_time
        assert projected.end_time == calendar_info.end_time
        assert projected.location == calendar_info.location
        assert projected.sync_invitees is True
        assert projected.created_at == created_at
        assert projected.updated_at == updated_at
        assert calendar_info.calendar_id == original_calendar_id

    def test_projects_invalid_legacy_record_without_revalidating(self) -> None:
        """Projection must tolerate an invalid persisted record.

        A legacy/externally-synced event may have start_time > end_time on a
        single day; re-validating during projection would crash calendar reads.
        """
        invalid = CalendarInfo(
            journal_id=42,
            calendar_id=uuid4(),
            start_time=time(23, 0),
            end_time=time(1, 0),
            event_start_date=date(2026, 6, 21),
            event_end_date=date(2026, 6, 21),
            validate=False,
        )

        projected = project_calendar_info_to_linked_calendar(invalid, uuid4())

        assert projected.start_time == time(23, 0)
        assert projected.end_time == time(1, 0)


@pytest.mark.unit
class TestRowToCalendarInfoTolerance:
    """Reading persisted rows must never re-run write-time validation."""

    def test_invalid_stored_row_does_not_raise(self) -> None:
        """A row with reversed same-day times hydrates instead of crashing reads.

        This is the journals-list failure: one bad row reconstructed via
        _row_to_calendar_info would otherwise 400 the entire list.
        """
        repo = SqlCalendarInfoRepository(MagicMock())
        midnight = datetime(2026, 6, 21, 0, 0, tzinfo=UTC)
        row = SimpleNamespace(
            journal_id=42,
            calendar_id=uuid4(),
            description=None,
            start_time=time(23, 0),
            end_time=time(1, 0),
            is_all_day=False,
            location=None,
            timezone=None,
            sync_invitees=False,
            private_description=False,
            event_state="confirmed",
            event_date_range_start=midnight,
            event_date_range_end=midnight,  # same local day -> reversed times
            created_at=midnight,
            updated_at=midnight,
        )

        calendar_info = repo._row_to_calendar_info(row)

        assert calendar_info.start_time == time(23, 0)
        assert calendar_info.end_time == time(1, 0)
