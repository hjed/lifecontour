"""Unit tests for important date ordering and display helpers."""

from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)


def test_display_labels():
    """Test the display_label properties on enums."""
    assert DatePrecision.FULL.display_label == "Full Date"
    assert DatePrecision.DAY_MONTH.display_label == "Day and Month"
    assert DatePrecision.YEAR.display_label == "Year Only"

    assert ImportantDateType.BIRTHDAY.display_label == "Birthday"
    assert (
        ImportantDateType.MARRIAGE_ANNIVERSARY.display_label == "Marriage Anniversary"
    )
    assert ImportantDateType.WORK_ANNIVERSARY.display_label == "Work Anniversary"
    assert ImportantDateType.FIRST_MET.display_label == "First Met"
    assert ImportantDateType.CUSTOM.display_label == "Custom"
