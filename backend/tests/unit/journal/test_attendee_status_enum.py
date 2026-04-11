"""Unit tests for AttendeeStatus enum."""

import pytest
from core_shared.models.journals import AttendeeStatus


@pytest.mark.unit
class TestAttendeeStatus:
    """Test AttendeeStatus enum."""

    def test_enum_values(self):
        """Test all 5 members are present with correct string values."""
        assert AttendeeStatus.ATTENDING == "ATTENDING"
        assert AttendeeStatus.ATTENDED == "ATTENDED"
        assert AttendeeStatus.MAYBE == "MAYBE"
        assert AttendeeStatus.NO_REPLY == "NO_REPLY"
        assert AttendeeStatus.DECLINED == "DECLINED"
        assert len(AttendeeStatus) == 5

    def test_str_representation(self):
        """Test string representation returns the value."""
        assert str(AttendeeStatus.ATTENDING) == "ATTENDING"
        assert str(AttendeeStatus.ATTENDED) == "ATTENDED"
        assert str(AttendeeStatus.MAYBE) == "MAYBE"
        assert str(AttendeeStatus.NO_REPLY) == "NO_REPLY"
        assert str(AttendeeStatus.DECLINED) == "DECLINED"

    def test_construction_from_string(self):
        """Test constructing enum from string value."""
        assert AttendeeStatus("ATTENDING") == AttendeeStatus.ATTENDING
        assert AttendeeStatus("ATTENDED") == AttendeeStatus.ATTENDED
        assert AttendeeStatus("MAYBE") == AttendeeStatus.MAYBE
        assert AttendeeStatus("NO_REPLY") == AttendeeStatus.NO_REPLY
        assert AttendeeStatus("DECLINED") == AttendeeStatus.DECLINED

    def test_invalid_value_raises(self):
        """Test invalid string value raises ValueError."""
        with pytest.raises(ValueError):
            AttendeeStatus("INVALID")

        with pytest.raises(ValueError):
            AttendeeStatus("attending")  # Case-sensitive
