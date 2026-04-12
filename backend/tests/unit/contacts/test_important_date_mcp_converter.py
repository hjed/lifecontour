"""Unit tests for important date MCP schema translation."""

from core_shared.models.contacts.entities import Contact, ImportantDate
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)

from app.mcp.shared.converters import ContactConverter


def test_mcp_contact_response_with_important_dates():
    """Test converting a contact with important dates to MCP response."""
    birthday = ImportantDate(
        id=1,
        contact_id=1,
        date_type=ImportantDateType.BIRTHDAY,
        precision=DatePrecision.FULL,
        year=1990,
        month=5,
        day=15,
    )

    anniversary = ImportantDate(
        id=2,
        contact_id=1,
        date_type=ImportantDateType.MARRIAGE_ANNIVERSARY,
        precision=DatePrecision.DAY_MONTH,
        month=10,
        day=20,
    )

    custom_date = ImportantDate(
        id=3,
        contact_id=1,
        date_type=ImportantDateType.CUSTOM,
        precision=DatePrecision.YEAR,
        year=2020,
        custom_date_type_id=1,
        custom_date_type_name="Graduation",
    )

    contact = Contact(
        id=1,
        first_name="John",
        last_name="Doe",
        important_dates=[birthday, anniversary, custom_date],
    )

    response = ContactConverter.to_contact_response(contact)

    assert len(response.important_dates) == 3

    assert response.important_dates[0].date_type == "birthday"
    assert response.important_dates[0].precision == "full"
    assert response.important_dates[0].year == 1990
    assert response.important_dates[0].month == 5
    assert response.important_dates[0].day == 15

    assert response.important_dates[1].date_type == "marriage_anniversary"
    assert response.important_dates[1].precision == "day_month"
    assert response.important_dates[1].year is None
    assert response.important_dates[1].month == 10

    assert response.important_dates[2].date_type == "custom"
    assert response.important_dates[2].precision == "year"
    assert response.important_dates[2].year == 2020
    assert response.important_dates[2].custom_type_name == "Graduation"

    # Verify summary includes date context
    assert "Has dates for: " in response.summary
    assert "Birthday" in response.summary
    assert "Marriage Anniversary" in response.summary


def test_mcp_contact_response_without_important_dates():
    """Test contact conversion without important dates."""
    contact = Contact(
        id=1,
        first_name="Jane",
        last_name="Smith",
    )

    response = ContactConverter.to_contact_response(contact)

    assert response.important_dates == []
    assert "Has dates for:" not in response.summary
