"""Integration tests for important date repository methods."""

import pytest
from core_shared.models.contacts.entities import Contact, ImportantDate
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_repository import SqlContactRepository
from app.core.contacts.adapters.sql.custom_date_type_repository import (
    SqlCustomDateTypeRepository,
)


@pytest.fixture
def contact_repo(async_connection: AsyncConnection) -> SqlContactRepository:
    """Fixture providing a ContactRepository connected to the test database."""
    return SqlContactRepository(connection=async_connection)


@pytest.fixture
def custom_date_repo(async_connection: AsyncConnection) -> SqlCustomDateTypeRepository:
    """Fixture providing a CustomDateTypeRepository connected to the test database."""
    return SqlCustomDateTypeRepository(connection=async_connection)


@pytest.fixture
async def sample_contact(contact_repo: SqlContactRepository) -> Contact:
    """Fixture to create a sample contact for testing."""
    contact = Contact(first_name="Alice", last_name="Smith")
    return await contact_repo.save(contact)


@pytest.mark.asyncio
async def test_add_and_get_important_dates(
    contact_repo: SqlContactRepository, sample_contact: Contact
) -> None:
    """Test adding and retrieving important dates."""
    assert sample_contact.id is not None
    date1 = ImportantDate(
        contact_id=sample_contact.id,
        date_type=ImportantDateType.BIRTHDAY,
        precision=DatePrecision.FULL,
        year=1990,
        month=5,
        day=15,
    )
    date2 = ImportantDate(
        contact_id=sample_contact.id,
        date_type=ImportantDateType.WORK_ANNIVERSARY,
        precision=DatePrecision.YEAR,
        year=2020,
    )

    # Add dates
    saved1 = await contact_repo.add_important_date(sample_contact.id, date1)
    saved2 = await contact_repo.add_important_date(sample_contact.id, date2)

    assert saved1.id is not None
    assert saved2.id is not None

    # Retrieve directly
    dates = await contact_repo.get_important_dates(sample_contact.id)
    assert len(dates) == 2
    types = {d.date_type for d in dates}
    assert ImportantDateType.BIRTHDAY in types
    assert ImportantDateType.WORK_ANNIVERSARY in types

    # Retrieve via find_by_id
    reloaded_contact = await contact_repo.find_by_id(sample_contact.id)
    assert reloaded_contact is not None
    assert reloaded_contact.important_dates is not None
    assert len(reloaded_contact.important_dates) == 2


@pytest.mark.asyncio
async def test_important_dates_custom_type(
    contact_repo: SqlContactRepository,
    custom_date_repo: SqlCustomDateTypeRepository,
    sample_contact: Contact,
) -> None:
    """Test adding custom types."""
    ctype = await custom_date_repo.create(name="Graduation")

    assert sample_contact.id is not None
    assert ctype.id is not None

    date = ImportantDate(
        contact_id=sample_contact.id,
        date_type=ImportantDateType.CUSTOM,
        precision=DatePrecision.YEAR,
        year=2025,
        custom_date_type_id=ctype.id,
    )

    saved = await contact_repo.add_important_date(sample_contact.id, date)
    assert saved.id is not None

    dates = await contact_repo.get_important_dates(sample_contact.id)
    assert len(dates) == 1
    assert dates[0].custom_date_type_id == ctype.id
    assert dates[0].custom_date_type_name == "Graduation"


@pytest.mark.asyncio
async def test_delete_important_date(
    contact_repo: SqlContactRepository, sample_contact: Contact
) -> None:
    """Test deleting an important date."""
    assert sample_contact.id is not None
    date = ImportantDate(
        contact_id=sample_contact.id,
        date_type=ImportantDateType.WORK_ANNIVERSARY,
        precision=DatePrecision.YEAR,
        year=2020,
    )
    saved = await contact_repo.add_important_date(sample_contact.id, date)
    assert saved.id is not None

    # Delete
    await contact_repo.delete_important_date(saved.id)

    # Verify
    dates = await contact_repo.get_important_dates(sample_contact.id)
    assert len(dates) == 0


@pytest.mark.asyncio
async def test_delete_all_important_dates(
    contact_repo: SqlContactRepository, sample_contact: Contact
) -> None:
    """Test deleting all important dates for a contact."""
    assert sample_contact.id is not None
    date1 = ImportantDate(
        contact_id=sample_contact.id,
        date_type=ImportantDateType.BIRTHDAY,
        precision=DatePrecision.YEAR,
        year=1990,
    )
    date2 = ImportantDate(
        contact_id=sample_contact.id,
        date_type=ImportantDateType.WORK_ANNIVERSARY,
        precision=DatePrecision.YEAR,
        year=2020,
    )
    await contact_repo.add_important_date(sample_contact.id, date1)
    await contact_repo.add_important_date(sample_contact.id, date2)

    assert len(await contact_repo.get_important_dates(sample_contact.id)) == 2

    await contact_repo.delete_all_important_dates(sample_contact.id)

    assert len(await contact_repo.get_important_dates(sample_contact.id)) == 0


@pytest.mark.asyncio
async def test_custom_date_type_repository_crud(
    custom_date_repo: SqlCustomDateTypeRepository,
) -> None:
    """Test CRUD operations for custom date types."""
    # Create
    ctype1 = await custom_date_repo.create(name="First Custom")
    _ctype2 = await custom_date_repo.create(name="Another Custom")

    # Read by ID
    assert ctype1.id is not None
    fetched_type = await custom_date_repo.get_by_id(ctype1.id)
    assert fetched_type is not None
    assert fetched_type.name == "First Custom"

    # Read by name
    fetched_name = await custom_date_repo.get_by_name("First Custom")
    assert fetched_name is not None
    assert fetched_name.id == ctype1.id

    # List all
    all_types = await custom_date_repo.list_all()
    # It might have types from other tests depending on transaction isolation,
    # but isolation is generally per-test. So we expect 2.
    names = {t.name for t in all_types}
    assert "First Custom" in names
    assert "Another Custom" in names

    # Delete
    await custom_date_repo.delete(ctype1.id)
    deleted_type = await custom_date_repo.get_by_id(ctype1.id)
    assert deleted_type is None


@pytest.mark.asyncio
async def test_duplicate_birthday_raises_error(
    contact_repo: SqlContactRepository, sample_contact: Contact
) -> None:
    """Test inserting duplicate birthday raises DuplicateBirthdayError."""
    assert sample_contact.id is not None
    date1 = ImportantDate(
        contact_id=sample_contact.id,
        date_type=ImportantDateType.BIRTHDAY,
        precision=DatePrecision.YEAR,
        year=1990,
    )
    await contact_repo.add_important_date(sample_contact.id, date1)

    date2 = ImportantDate(
        contact_id=sample_contact.id,
        date_type=ImportantDateType.BIRTHDAY,
        precision=DatePrecision.YEAR,
        year=1995,
    )
    from app.core.contacts.models.exceptions import DuplicateBirthdayError

    with pytest.raises(DuplicateBirthdayError, match="already has a birthday"):
        await contact_repo.add_important_date(sample_contact.id, date2)


@pytest.mark.asyncio
async def test_custom_date_type_in_use_error(
    custom_date_repo: SqlCustomDateTypeRepository,
    contact_repo: SqlContactRepository,
    sample_contact: Contact,
) -> None:
    """Test deleting an in-use custom date type raises CustomDateTypeInUseError."""
    assert sample_contact.id is not None
    ctype = await custom_date_repo.create(name="Required Date")
    assert ctype.id is not None

    date = ImportantDate(
        contact_id=sample_contact.id,
        date_type=ImportantDateType.CUSTOM,
        precision=DatePrecision.YEAR,
        year=2020,
        custom_date_type_id=ctype.id,
    )
    await contact_repo.add_important_date(sample_contact.id, date)

    from app.core.contacts.models.exceptions import CustomDateTypeInUseError

    with pytest.raises(
        CustomDateTypeInUseError, match="cannot be deleted because it is referenced"
    ):
        await custom_date_repo.delete(ctype.id)
