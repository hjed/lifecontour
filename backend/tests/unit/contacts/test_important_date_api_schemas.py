"""Unit tests for important date API schemas and converters."""

from datetime import datetime

from core_shared.models.contacts.entities import ImportantDate
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)

from app.api.contacts.converters import ContactConverter, ContactRequestConverter
from app.api.contacts.schemas import (
    ImportantDateAttributes,
    ImportantDateCreateData,
    ImportantDateResource,
)


def test_to_important_date_resource_full():
    """Test converting a full precision domain entity to an API resource."""
    date = ImportantDate(
        id=1,
        contact_id=2,
        date_type=ImportantDateType.BIRTHDAY,
        precision=DatePrecision.FULL,
        year=1990,
        month=5,
        day=15,
        created_at=datetime(2023, 1, 1),
        updated_at=datetime(2023, 1, 2),
    )

    resource = ContactConverter.to_important_date_resource(date)

    assert resource.id == 1
    assert resource.attributes.date_type == "birthday"
    assert resource.attributes.precision == "full"
    assert resource.attributes.year == 1990
    assert resource.attributes.month == 5
    assert resource.attributes.day == 15
    assert resource.attributes.custom_date_type_id is None
    assert resource.attributes.created_at == date.created_at
    assert resource.attributes.updated_at == date.updated_at


def test_to_important_date_resource_day_month():
    """Test converting a day_month precision domain entity to an API resource."""
    date = ImportantDate(
        id=1,
        contact_id=2,
        date_type=ImportantDateType.MARRIAGE_ANNIVERSARY,
        precision=DatePrecision.DAY_MONTH,
        month=10,
        day=20,
    )

    resource = ContactConverter.to_important_date_resource(date)

    assert resource.attributes.date_type == "marriage_anniversary"
    assert resource.attributes.precision == "day_month"
    assert resource.attributes.year is None
    assert resource.attributes.month == 10
    assert resource.attributes.day == 20


def test_to_important_date_resource_year():
    """Test converting a year precision domain entity to an API resource."""
    date = ImportantDate(
        id=1,
        contact_id=2,
        date_type=ImportantDateType.WORK_ANNIVERSARY,
        precision=DatePrecision.YEAR,
        year=2020,
    )

    resource = ContactConverter.to_important_date_resource(date)

    assert resource.attributes.date_type == "work_anniversary"
    assert resource.attributes.precision == "year"
    assert resource.attributes.year == 2020
    assert resource.attributes.month is None
    assert resource.attributes.day is None


def test_to_important_date_resource_custom():
    """Test converting a custom domain entity to an API resource."""
    date = ImportantDate(
        id=1,
        contact_id=2,
        date_type=ImportantDateType.CUSTOM,
        precision=DatePrecision.YEAR,
        year=2020,
        custom_date_type_id=3,
        custom_date_type_name="Graduation",
    )

    resource = ContactConverter.to_important_date_resource(date)

    assert resource.attributes.date_type == "custom"
    assert resource.attributes.custom_date_type_id == 3
    assert resource.attributes.custom_date_type_name == "Graduation"


def test_from_important_date_resource():
    """Test converting an API resource back to a domain entity."""
    resource = ImportantDateResource(
        id=1,
        attributes=ImportantDateAttributes(
            date_type="birthday",
            precision="full",
            year=1990,
            month=5,
            day=15,
        ),
    )

    date = ContactRequestConverter.from_important_date_resource(resource, contact_id=2)

    assert date.id == 1
    assert date.contact_id == 2
    assert date.date_type == ImportantDateType.BIRTHDAY
    assert date.precision == DatePrecision.FULL
    assert date.year == 1990
    assert date.month == 5
    assert date.day == 15
    assert date.custom_date_type_id is None


def test_from_important_date_create_request():
    """Test converting an API create request to a domain entity."""
    request_data = ImportantDateCreateData(
        attributes=ImportantDateAttributes(
            date_type="custom",
            precision="year",
            year=2020,
            custom_date_type_id=3,
        )
    )

    date = ContactRequestConverter.from_important_date_create_request(
        request_data, contact_id=2
    )

    assert date.id is None
    assert date.contact_id == 2
    assert date.date_type == ImportantDateType.CUSTOM
    assert date.precision == DatePrecision.YEAR
    assert date.year == 2020
    assert date.month is None
    assert date.day is None
    assert date.custom_date_type_id == 3
