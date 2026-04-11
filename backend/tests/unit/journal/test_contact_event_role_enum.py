"""Unit tests for ContactEventRole enum."""

import pytest
from core_shared.models.journals import ContactEventRole


@pytest.mark.unit
class TestContactEventRole:
    """Test ContactEventRole enum."""

    def test_enum_values(self):
        """Test all 2 members are present with correct string values."""
        assert ContactEventRole.ORGANISER == "ORGANISER"
        assert ContactEventRole.FACILITATOR_HELPER == "FACILITATOR_HELPER"
        assert len(ContactEventRole) == 2

    def test_str_representation(self):
        """Test string representation returns the value."""
        assert str(ContactEventRole.ORGANISER) == "ORGANISER"
        assert str(ContactEventRole.FACILITATOR_HELPER) == "FACILITATOR_HELPER"

    def test_construction_from_string(self):
        """Test constructing enum from string value."""
        assert ContactEventRole("ORGANISER") == ContactEventRole.ORGANISER
        assert (
            ContactEventRole("FACILITATOR_HELPER")
            == ContactEventRole.FACILITATOR_HELPER
        )

    def test_invalid_value_raises(self):
        """Test invalid string value raises ValueError."""
        with pytest.raises(ValueError):
            ContactEventRole("INVALID")

        with pytest.raises(ValueError):
            ContactEventRole("organiser")  # Case-sensitive

        with pytest.raises(ValueError):
            ContactEventRole("FACILITATOR")  # Not a valid standalone value

        with pytest.raises(ValueError):
            ContactEventRole("HELPER")  # Not a valid standalone value
