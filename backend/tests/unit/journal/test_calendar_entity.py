"""Unit tests for Calendar entity."""

from uuid import uuid4

import pytest

from app.core.journal.models.calendar import Calendar
from app.core.journal.models.constants import MAX_CALENDAR_NAME_LENGTH
from app.core.journal.models.exceptions import CalendarValidationError


@pytest.mark.unit
class TestCalendar:
    """Test Calendar entity."""

    def test_create_calendar_minimal(self):
        """Test creating calendar with minimal required fields."""
        calendar = Calendar(
            user_id="test-user-123",
            name="Personal",
            color="#FF5733",
        )

        assert calendar.id is None
        assert calendar.user_id == "test-user-123"
        assert calendar.name == "Personal"
        assert calendar.color == "#FF5733"
        assert calendar.description is None
        assert calendar.is_synced_to_google is False
        assert calendar.google_calendar_id is None

    def test_create_calendar_complete(self):
        """Test creating calendar with all fields."""
        calendar_id = uuid4()
        calendar = Calendar(
            id=calendar_id,
            user_id="test-user-123",
            name="Work",
            color="#3366FF",
            description="Work meetings and events",
            is_synced_to_google=True,
            google_calendar_id="primary@example.com",
        )

        assert calendar.id == calendar_id
        assert calendar.name == "Work"
        assert calendar.description == "Work meetings and events"
        assert calendar.is_synced_to_google is True
        assert calendar.google_calendar_id == "primary@example.com"

    def test_empty_user_id_raises_error(self):
        """Test that empty user_id raises error."""
        with pytest.raises(CalendarValidationError, match="User ID is required"):
            Calendar(user_id="", name="Test", color="#000000")

    def test_whitespace_user_id_raises_error(self):
        """Test that whitespace-only user_id raises error."""
        with pytest.raises(CalendarValidationError, match="User ID is required"):
            Calendar(user_id="   ", name="Test", color="#000000")

    def test_empty_name_raises_error(self):
        """Test that empty name raises error."""
        with pytest.raises(
            CalendarValidationError, match="Calendar name is required"
        ):
            Calendar(user_id="test-user", name="", color="#000000")

    def test_whitespace_name_raises_error(self):
        """Test that whitespace-only name raises error."""
        with pytest.raises(
            CalendarValidationError, match="Calendar name is required"
        ):
            Calendar(user_id="test-user", name="   ", color="#000000")

    def test_name_too_long_raises_error(self):
        """Test that name exceeding max length raises error."""
        long_name = "a" * (MAX_CALENDAR_NAME_LENGTH + 1)
        with pytest.raises(
            CalendarValidationError,
            match=f"Calendar name cannot exceed {MAX_CALENDAR_NAME_LENGTH}",
        ):
            Calendar(user_id="test-user", name=long_name, color="#000000")

    def test_name_at_max_length_is_valid(self):
        """Test that name at exactly max length is valid."""
        max_name = "a" * MAX_CALENDAR_NAME_LENGTH
        calendar = Calendar(user_id="test-user", name=max_name, color="#000000")
        assert len(calendar.name) == MAX_CALENDAR_NAME_LENGTH


@pytest.mark.unit
class TestCalendarColorValidation:
    """Test Calendar color validation."""

    def test_valid_hex_colors(self):
        """Test valid hex colors."""
        valid_colors = ["#000000", "#FFFFFF", "#ff5733", "#FF5733", "#123ABC"]
        for color in valid_colors:
            calendar = Calendar(user_id="test-user", name="Test", color=color)
            assert calendar.color == color

    def test_empty_color_raises_error(self):
        """Test that empty color raises error."""
        with pytest.raises(
            CalendarValidationError, match="Calendar color is required"
        ):
            Calendar(user_id="test-user", name="Test", color="")

    def test_invalid_color_format_raises_error(self):
        """Test that invalid color format raises error."""
        invalid_colors = [
            "FF5733",  # Missing #
            "#FF573",  # Too short
            "#FF57333",  # Too long
            "#GGGGGG",  # Invalid hex chars
            "red",  # Color name
        ]
        for color in invalid_colors:
            with pytest.raises(
                CalendarValidationError, match="hex format"
            ):
                Calendar(user_id="test-user", name="Test", color=color)


@pytest.mark.unit
class TestCalendarGoogleSync:
    """Test Calendar Google sync validation."""

    def test_synced_without_calendar_id_raises_error(self):
        """Test that synced=True without google_calendar_id raises error."""
        with pytest.raises(
            CalendarValidationError,
            match="Google Calendar ID is required when sync is enabled",
        ):
            Calendar(
                user_id="test-user",
                name="Test",
                color="#000000",
                is_synced_to_google=True,
                google_calendar_id=None,
            )

    def test_synced_with_calendar_id_is_valid(self):
        """Test that synced=True with google_calendar_id is valid."""
        calendar = Calendar(
            user_id="test-user",
            name="Test",
            color="#000000",
            is_synced_to_google=True,
            google_calendar_id="calendar@example.com",
        )
        assert calendar.is_synced_to_google is True
        assert calendar.google_calendar_id == "calendar@example.com"

    def test_not_synced_without_calendar_id_is_valid(self):
        """Test that synced=False without google_calendar_id is valid."""
        calendar = Calendar(
            user_id="test-user",
            name="Test",
            color="#000000",
            is_synced_to_google=False,
        )
        assert calendar.is_synced_to_google is False
        assert calendar.google_calendar_id is None

