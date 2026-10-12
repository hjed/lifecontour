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
from app.core.contacts.models.exceptions import (
    CustomDateTypeNotFoundError,
    DuplicateCustomDateTypeNameError,
)
from tests.integration.contact_seeding import OTHER_USER_ID, TEST_USER_ID


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
    contact = Contact(user_id=TEST_USER_ID, first_name="Alice", last_name="Smith")
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
    reloaded_contact = await contact_repo.find_by_id(
        sample_contact.id, user_id=TEST_USER_ID
    )
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
    ctype = await custom_date_repo.create(name="Graduation", user_id=TEST_USER_ID)

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
    ctype1 = await custom_date_repo.create(name="First Custom", user_id=TEST_USER_ID)
    _ctype2 = await custom_date_repo.create(name="Another Custom", user_id=TEST_USER_ID)

    # Read by ID
    assert ctype1.id is not None
    fetched_type = await custom_date_repo.get_by_id(ctype1.id, user_id=TEST_USER_ID)
    assert fetched_type is not None
    assert fetched_type.name == "First Custom"

    # Read by name
    fetched_name = await custom_date_repo.get_by_name(
        "First Custom", user_id=TEST_USER_ID
    )
    assert fetched_name is not None
    assert fetched_name.id == ctype1.id

    # List all
    all_types = await custom_date_repo.list_all(user_id=TEST_USER_ID)
    # It might have types from other tests depending on transaction isolation,
    # but isolation is generally per-test. So we expect 2.
    names = {t.name for t in all_types}
    assert "First Custom" in names
    assert "Another Custom" in names

    # Delete
    await custom_date_repo.delete(ctype1.id, user_id=TEST_USER_ID)
    deleted_type = await custom_date_repo.get_by_id(ctype1.id, user_id=TEST_USER_ID)
    assert deleted_type is None


@pytest.mark.asyncio
async def test_create_stamps_the_owner_and_every_read_returns_it(
    custom_date_repo: SqlCustomDateTypeRepository,
) -> None:
    """A created type belongs to the user who created it, on every read."""
    created = await custom_date_repo.create(name="Sobriety", user_id=TEST_USER_ID)
    assert created.id is not None

    by_id = await custom_date_repo.get_by_id(created.id, user_id=TEST_USER_ID)
    by_name = await custom_date_repo.get_by_name("Sobriety", user_id=TEST_USER_ID)
    listed = await custom_date_repo.list_all(user_id=TEST_USER_ID)

    assert created.user_id == TEST_USER_ID
    assert by_id is not None and by_id.user_id == TEST_USER_ID
    assert by_name is not None and by_name.user_id == TEST_USER_ID
    assert [t.user_id for t in listed if t.id == created.id] == [TEST_USER_ID]


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
    ctype = await custom_date_repo.create(name="Required Date", user_id=TEST_USER_ID)
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
        await custom_date_repo.delete(ctype.id, user_id=TEST_USER_ID)


@pytest.mark.asyncio
class TestCustomDateTypeReadsAreScopedToTheOwner:
    """Another user's type reads, and refuses deletion, as a missing one."""

    async def test_their_type_is_invisible_to_every_read(
        self, custom_date_repo: SqlCustomDateTypeRepository
    ) -> None:
        theirs = await custom_date_repo.create(name="Sobriety", user_id=OTHER_USER_ID)
        mine = await custom_date_repo.create(name="Graduation", user_id=TEST_USER_ID)
        assert theirs.id is not None

        assert await custom_date_repo.get_by_id(theirs.id, user_id=TEST_USER_ID) is None
        assert (
            await custom_date_repo.get_by_name("Sobriety", user_id=TEST_USER_ID) is None
        )
        assert [
            t.id for t in await custom_date_repo.list_all(user_id=TEST_USER_ID)
        ] == [mine.id]

    async def test_deleting_their_type_is_not_found_and_leaves_it(
        self, custom_date_repo: SqlCustomDateTypeRepository
    ) -> None:
        theirs = await custom_date_repo.create(name="Sobriety", user_id=OTHER_USER_ID)
        assert theirs.id is not None

        with pytest.raises(CustomDateTypeNotFoundError):
            await custom_date_repo.delete(theirs.id, user_id=TEST_USER_ID)

        assert await custom_date_repo.get_by_id(theirs.id, user_id=OTHER_USER_ID)

    async def test_two_users_may_each_name_a_type_the_same(
        self, custom_date_repo: SqlCustomDateTypeRepository
    ) -> None:
        theirs = await custom_date_repo.create(name="Sobriety", user_id=OTHER_USER_ID)
        mine = await custom_date_repo.create(name="Sobriety", user_id=TEST_USER_ID)

        found = await custom_date_repo.get_by_name("Sobriety", user_id=TEST_USER_ID)

        assert theirs.id != mine.id
        assert found is not None and found.id == mine.id

    async def test_one_user_cannot_name_two_types_the_same(
        self, custom_date_repo: SqlCustomDateTypeRepository
    ) -> None:
        await custom_date_repo.create(name="Sobriety", user_id=TEST_USER_ID)

        with pytest.raises(DuplicateCustomDateTypeNameError):
            await custom_date_repo.create(name="Sobriety", user_id=TEST_USER_ID)
