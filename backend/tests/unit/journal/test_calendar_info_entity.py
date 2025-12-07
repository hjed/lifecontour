"""Unit tests for CalendarInfo entity (EVENT type)."""

from datetime import time
from uuid import uuid4

import pytest

from app.core.journal.models.calendar_info import CalendarInfo
from app.core.journal.models.constants import MAX_LOCATION_LENGTH
from app.core.journal.models.exceptions import CalendarInfoValidationError


@pytest.mark.unit
class TestCalendarInfo:
    """Test CalendarInfo entity."""

    def test_create_calendar_info_minimal(self):
        """Test creating calendar info with minimal required fields."""
        calendar_id = uuid4()
        calendar_info = CalendarInfo(
            journal_id=1,
            calendar_id=calendar_id,
        )

        assert calendar_info.journal_id == 1
        assert calendar_info.calendar_id == calendar_id
        assert calendar_info.start_time is None
        assert calendar_info.end_time is None
        assert calendar_info.is_all_day is False
        assert calendar_info.location is None
        assert calendar_info.sync_invitees is False

    def test_create_calendar_info_with_times(self):
        """Test creating calendar info with times."""
        calendar_id = uuid4()
        start = time(9, 0)
        end = time(17, 0)

        calendar_info = CalendarInfo(
            journal_id=1,
            calendar_id=calendar_id,
            start_time=start,
            end_time=end,
        )

        assert calendar_info.start_time == start
        assert calendar_info.end_time == end
        assert calendar_info.is_all_day is False

    def test_create_all_day_event(self):
        """Test creating an all-day event."""
        calendar_id = uuid4()
        calendar_info = CalendarInfo(
            journal_id=1,
            calendar_id=calendar_id,
            is_all_day=True,
        )

        assert calendar_info.is_all_day is True
        assert calendar_info.start_time is None
        assert calendar_info.end_time is None

    def test_create_calendar_info_complete(self):
        """Test creating calendar info with all fields."""
        calendar_id = uuid4()
        calendar_info = CalendarInfo(
            journal_id=1,
            calendar_id=calendar_id,
            start_time=time(10, 0),
            end_time=time(11, 30),
            is_all_day=False,
            location="Conference Room A",
            sync_invitees=True,
        )

        assert calendar_info.location == "Conference Room A"
        assert calendar_info.sync_invitees is True


@pytest.mark.unit
class TestCalendarInfoValidation:
    """Test CalendarInfo validation."""

    def test_invalid_journal_id_raises_error(self):
        """Test that invalid journal_id raises error."""
        calendar_id = uuid4()
        with pytest.raises(
            CalendarInfoValidationError,
            match="Journal ID must be a positive integer",
        ):
            CalendarInfo(journal_id=0, calendar_id=calendar_id)

        with pytest.raises(
            CalendarInfoValidationError,
            match="Journal ID must be a positive integer",
        ):
            CalendarInfo(journal_id=-1, calendar_id=calendar_id)

    def test_missing_calendar_id_raises_error(self):
        """Test that missing calendar_id raises error."""
        with pytest.raises(
            CalendarInfoValidationError,
            match="Calendar ID is required",
        ):
            CalendarInfo(journal_id=1, calendar_id=None)  # type: ignore[arg-type]


@pytest.mark.unit
class TestCalendarInfoTimeValidation:
    """Test CalendarInfo time validation."""

    def test_all_day_with_times_raises_error(self):
        """Test that all-day event with times raises error."""
        calendar_id = uuid4()
        with pytest.raises(
            CalendarInfoValidationError,
            match="All-day events should not have start_time or end_time",
        ):
            CalendarInfo(
                journal_id=1,
                calendar_id=calendar_id,
                is_all_day=True,
                start_time=time(9, 0),
            )

    def test_start_time_only_raises_error(self):
        """Test that providing only start_time raises error."""
        calendar_id = uuid4()
        with pytest.raises(
            CalendarInfoValidationError,
            match="Both start_time and end_time must be provided",
        ):
            CalendarInfo(
                journal_id=1,
                calendar_id=calendar_id,
                start_time=time(9, 0),
                end_time=None,
            )

    def test_end_time_before_start_raises_error(self):
        """Test that end_time before start_time raises error."""
        calendar_id = uuid4()
        with pytest.raises(
            CalendarInfoValidationError,
            match="end_time must be after or equal to start_time",
        ):
            CalendarInfo(
                journal_id=1,
                calendar_id=calendar_id,
                start_time=time(17, 0),
                end_time=time(9, 0),
            )

    def test_location_too_long_raises_error(self):
        """Test that location exceeding max length raises error."""
        calendar_id = uuid4()
        long_location = "a" * (MAX_LOCATION_LENGTH + 1)
        with pytest.raises(
            CalendarInfoValidationError,
            match=f"Location cannot exceed {MAX_LOCATION_LENGTH}",
        ):
            CalendarInfo(journal_id=1, calendar_id=calendar_id, location=long_location)

