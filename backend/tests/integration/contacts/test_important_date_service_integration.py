"""Integration tests for important date service methods."""

import pytest
from core_shared.models.contacts.entities import Contact, ImportantDate
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_repository import SqlContactRepository
from app.core.contacts.services.contact_service import ContactService


@pytest.fixture
def contact_service(
    async_connection: AsyncConnection,
) -> ContactService:
    from app.core.contacts.adapters.sql.contact_field_history_repository import (
        SqlContactFieldHistoryRepository,
    )
    from app.core.contacts.adapters.sql.tag_repository import SqlTagRepository
    from app.core.contacts.models.repositories import ContactEventPublisher
    from app.core.contacts.services.address_validation_service import (
        AddressValidationService,
    )
    from app.core.contacts.services.contact_history_service import ContactHistoryService
    from app.core.contacts.services.contact_validation_service import (
        ContactValidationService,
    )
    from app.core.contacts.services.tag_hierarchy_service import TagHierarchyService

    class MockEventPublisher(ContactEventPublisher):
        async def publish(self, event, connection=None):
            pass

        async def publish_batch(self, events, connection=None):
            pass

    contact_repo = SqlContactRepository(connection=async_connection)
    tag_repo = SqlTagRepository(connection=async_connection)
    history_repo = SqlContactFieldHistoryRepository(connection=async_connection)
    event_publisher = MockEventPublisher()

    return ContactService(
        contact_repo=contact_repo,
        tag_repo=tag_repo,
        history_repo=history_repo,
        event_publisher=event_publisher,
        address_validation_service=AddressValidationService(),
        contact_validation_service=ContactValidationService(contact_repo),
        history_service=ContactHistoryService(history_repo),
        tag_hierarchy_service=TagHierarchyService(tag_repo),
    )


@pytest.mark.asyncio
async def test_create_contact_with_important_dates(
    contact_service: ContactService, async_connection: AsyncConnection
) -> None:
    """Test creating a contact with important dates attached."""
    contact = Contact(first_name="John", last_name="Doe")
    contact.important_dates = [
        ImportantDate(
            contact_id=0,
            date_type=ImportantDateType.BIRTHDAY,
            precision=DatePrecision.DAY_MONTH,
            month=5,
            day=15,
        )
    ]

    saved_contact = await contact_service.create_contact(contact, async_connection)

    assert saved_contact.id is not None
    assert saved_contact.important_dates is not None
    assert len(saved_contact.important_dates) == 1
    assert saved_contact.important_dates[0].id is not None
    assert saved_contact.important_dates[0].contact_id == saved_contact.id
    assert saved_contact.important_dates[0].date_type == ImportantDateType.BIRTHDAY


@pytest.mark.asyncio
async def test_update_contact_with_important_dates(
    contact_service: ContactService, async_connection: AsyncConnection
) -> None:
    """Test updating a contact's important dates."""
    # Create
    contact = Contact(first_name="Jane", last_name="Doe")
    saved_contact = await contact_service.create_contact(contact, async_connection)
    assert saved_contact.id is not None

    # Add a date via update
    date = ImportantDate(
        contact_id=saved_contact.id,
        date_type=ImportantDateType.WORK_ANNIVERSARY,
        precision=DatePrecision.YEAR,
        year=2020,
    )
    saved_contact.important_dates = [date]
    updated_contact = await contact_service.update_contact(
        saved_contact, async_connection
    )

    assert updated_contact.important_dates is not None
    assert len(updated_contact.important_dates) == 1
    assert updated_contact.important_dates[0].id is not None

    # Remove via update (replace with empty list)
    updated_contact.important_dates = []
    updated_contact = await contact_service.update_contact(
        updated_contact, async_connection
    )

    dates = updated_contact.important_dates
    assert dates is not None
    assert len(dates) == 0


@pytest.mark.asyncio
async def test_add_and_delete_important_date(
    contact_service: ContactService, async_connection: AsyncConnection
) -> None:
    """Test adding and deleting individual important dates."""
    contact = Contact(first_name="Jack", last_name="Smith")
    saved_contact = await contact_service.create_contact(contact, async_connection)
    assert saved_contact.id is not None

    date = ImportantDate(
        contact_id=saved_contact.id,
        date_type=ImportantDateType.FIRST_MET,
        precision=DatePrecision.FULL,
        year=2015,
        month=1,
        day=1,
    )

    # Add individual
    saved_date = await contact_service.add_contact_important_date(
        saved_contact.id, date, async_connection
    )
    assert saved_date.id is not None

    # Verify
    fetched = await contact_service.get_contact_by_id(saved_contact.id)
    assert fetched is not None
    assert fetched.important_dates is not None
    assert len(fetched.important_dates) == 1

    # Delete individual
    await contact_service.delete_contact_important_date(
        saved_contact.id, saved_date.id, async_connection
    )

    # Verify
    fetched2 = await contact_service.get_contact_by_id(saved_contact.id)
    assert fetched2 is not None
    assert len(fetched2.important_dates or []) == 0
