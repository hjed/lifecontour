"""Integration tests for important date service methods."""

import pytest
from core_shared.models.contacts.entities import Contact, ImportantDate
from core_shared.models.contacts.exceptions import ContactValidationError
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.services.contact_service import ContactService
from tests.integration.contact_seeding import TEST_USER_ID
from tests.integration.contacts.contact_service_harness import (
    RecordingEventPublisher,
    build_contact_service,
)


@pytest.fixture
def recorded_events() -> RecordingEventPublisher:
    """An event publisher that records instead of discarding."""
    return RecordingEventPublisher()


@pytest.fixture
def recording_contact_service(
    async_connection: AsyncConnection, recorded_events: RecordingEventPublisher
) -> ContactService:
    """A ContactService whose published events can be inspected."""
    return build_contact_service(async_connection, recorded_events)


@pytest.fixture
def contact_service(async_connection: AsyncConnection) -> ContactService:
    """A ContactService whose events go nowhere."""
    return build_contact_service(async_connection, RecordingEventPublisher())


@pytest.mark.asyncio
async def test_create_contact_with_important_dates(
    contact_service: ContactService, async_connection: AsyncConnection
) -> None:
    """Test creating a contact with important dates attached."""
    contact = Contact(user_id=TEST_USER_ID, first_name="John", last_name="Doe")
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
    contact = Contact(user_id=TEST_USER_ID, first_name="Jane", last_name="Doe")
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
        saved_contact, async_connection, user_id=TEST_USER_ID
    )

    assert updated_contact.important_dates is not None
    assert len(updated_contact.important_dates) == 1
    assert updated_contact.important_dates[0].id is not None

    # Remove via update (replace with empty list)
    updated_contact.important_dates = []
    updated_contact = await contact_service.update_contact(
        updated_contact, async_connection, user_id=TEST_USER_ID
    )

    dates = updated_contact.important_dates
    assert dates is not None
    assert len(dates) == 0


@pytest.mark.asyncio
async def test_add_and_delete_important_date(
    contact_service: ContactService, async_connection: AsyncConnection
) -> None:
    """Test adding and deleting individual important dates."""
    contact = Contact(user_id=TEST_USER_ID, first_name="Jack", last_name="Smith")
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
        saved_contact.id, date, async_connection, user_id=TEST_USER_ID
    )
    assert saved_date.id is not None

    # Verify
    fetched = await contact_service.get_contact_by_id(
        saved_contact.id, user_id=TEST_USER_ID
    )
    assert fetched is not None
    assert fetched.important_dates is not None
    assert len(fetched.important_dates) == 1

    # Delete individual
    await contact_service.delete_contact_important_date(
        saved_contact.id, saved_date.id, async_connection, user_id=TEST_USER_ID
    )

    # Verify
    fetched2 = await contact_service.get_contact_by_id(
        saved_contact.id, user_id=TEST_USER_ID
    )
    assert fetched2 is not None
    assert len(fetched2.important_dates or []) == 0


async def _contact_with_date(
    contact_service: ContactService,
    connection: AsyncConnection,
    date: ImportantDate,
) -> tuple[Contact, ImportantDate]:
    """Persist a contact carrying one important date, returning both."""
    contact = await contact_service.create_contact(
        Contact(user_id=TEST_USER_ID, first_name="Edit", last_name="Target"), connection
    )
    assert contact.id is not None
    date.contact_id = contact.id
    saved_date = await contact_service.add_contact_important_date(
        contact.id, date, connection, user_id=TEST_USER_ID
    )
    return contact, saved_date


@pytest.mark.asyncio
async def test_update_important_date_keeps_the_same_row(
    contact_service: ContactService, async_connection: AsyncConnection
) -> None:
    """An edit updates the date in place rather than replacing it."""
    # Arrange
    contact, saved_date = await _contact_with_date(
        contact_service,
        async_connection,
        ImportantDate(
            contact_id=0,
            date_type=ImportantDateType.BIRTHDAY,
            precision=DatePrecision.FULL,
            year=1990,
            month=5,
            day=15,
        ),
    )
    assert contact.id is not None
    assert saved_date.id is not None

    # Act - correct the birth year
    edited = ImportantDate(
        id=saved_date.id,
        contact_id=contact.id,
        date_type=ImportantDateType.BIRTHDAY,
        precision=DatePrecision.FULL,
        year=1991,
        month=5,
        day=15,
    )
    returned = await contact_service.update_contact_important_date(
        contact.id, saved_date.id, edited, async_connection, user_id=TEST_USER_ID
    )

    # Assert
    assert returned.id == saved_date.id, "the date must keep its id across an edit"

    fetched = await contact_service.get_contact_by_id(contact.id, user_id=TEST_USER_ID)
    assert fetched is not None
    dates = fetched.important_dates or []
    assert len(dates) == 1
    assert dates[0].id == saved_date.id
    assert dates[0].year == 1991


@pytest.mark.asyncio
async def test_update_important_date_publishes_changed_fields(
    recording_contact_service: ContactService,
    recorded_events: RecordingEventPublisher,
    async_connection: AsyncConnection,
) -> None:
    """The edit publishes ImportantDateUpdated carrying only what changed."""
    # Arrange
    contact, saved_date = await _contact_with_date(
        recording_contact_service,
        async_connection,
        ImportantDate(
            contact_id=0,
            date_type=ImportantDateType.WORK_ANNIVERSARY,
            precision=DatePrecision.YEAR,
            year=2020,
        ),
    )
    assert contact.id is not None
    assert saved_date.id is not None

    # Act - same type and precision, different year
    edited = ImportantDate(
        id=saved_date.id,
        contact_id=contact.id,
        date_type=ImportantDateType.WORK_ANNIVERSARY,
        precision=DatePrecision.YEAR,
        year=2021,
    )
    await recording_contact_service.update_contact_important_date(
        contact.id, saved_date.id, edited, async_connection, user_id=TEST_USER_ID
    )

    # Assert
    published = recorded_events.of_type("ImportantDateUpdated")
    assert len(published) == 1
    data = published[0].event_data
    assert data["contact_id"] == contact.id
    assert data["date_id"] == saved_date.id
    assert data["changed_fields"] == {"year": (2020, 2021)}, (
        "only the year moved, and it is reported as an (old, new) pair"
    )


@pytest.mark.asyncio
async def test_update_important_date_reports_type_and_precision_changes(
    recording_contact_service: ContactService,
    recorded_events: RecordingEventPublisher,
    async_connection: AsyncConnection,
) -> None:
    """Enum-valued fields are reported by value, so the payload stays JSON-safe."""
    # Arrange
    contact, saved_date = await _contact_with_date(
        recording_contact_service,
        async_connection,
        ImportantDate(
            contact_id=0,
            date_type=ImportantDateType.WORK_ANNIVERSARY,
            precision=DatePrecision.YEAR,
            year=2020,
        ),
    )
    assert contact.id is not None
    assert saved_date.id is not None

    # Act
    edited = ImportantDate(
        id=saved_date.id,
        contact_id=contact.id,
        date_type=ImportantDateType.FIRST_MET,
        precision=DatePrecision.DAY_MONTH,
        month=6,
        day=1,
    )
    await recording_contact_service.update_contact_important_date(
        contact.id, saved_date.id, edited, async_connection, user_id=TEST_USER_ID
    )

    # Assert
    changed = recorded_events.of_type("ImportantDateUpdated")[0].event_data[
        "changed_fields"
    ]
    assert changed["date_type"] == ("work_anniversary", "first_met")
    assert changed["precision"] == ("year", "day_month")
    assert changed["year"] == (2020, None)
    assert changed["month"] == (None, 6)
    assert changed["day"] == (None, 1)


@pytest.mark.asyncio
async def test_update_important_date_with_no_changes_publishes_nothing(
    recording_contact_service: ContactService,
    recorded_events: RecordingEventPublisher,
    async_connection: AsyncConnection,
) -> None:
    """Re-submitting an unchanged date writes no history noise."""
    # Arrange
    contact, saved_date = await _contact_with_date(
        recording_contact_service,
        async_connection,
        ImportantDate(
            contact_id=0,
            date_type=ImportantDateType.FIRST_MET,
            precision=DatePrecision.YEAR,
            year=2015,
        ),
    )
    assert contact.id is not None
    assert saved_date.id is not None

    # Act - resubmit the identical date
    unchanged = ImportantDate(
        id=saved_date.id,
        contact_id=contact.id,
        date_type=ImportantDateType.FIRST_MET,
        precision=DatePrecision.YEAR,
        year=2015,
    )
    await recording_contact_service.update_contact_important_date(
        contact.id, saved_date.id, unchanged, async_connection, user_id=TEST_USER_ID
    )

    # Assert
    assert recorded_events.of_type("ImportantDateUpdated") == []


@pytest.mark.asyncio
async def test_update_important_date_rejects_a_date_from_another_contact(
    contact_service: ContactService, async_connection: AsyncConnection
) -> None:
    """A date id is only editable through the contact that owns it."""
    # Arrange - two contacts, each with a date
    _owner, owned_date = await _contact_with_date(
        contact_service,
        async_connection,
        ImportantDate(
            contact_id=0,
            date_type=ImportantDateType.FIRST_MET,
            precision=DatePrecision.YEAR,
            year=2015,
        ),
    )
    stranger = await contact_service.create_contact(
        Contact(user_id=TEST_USER_ID, first_name="Some", last_name="Stranger"),
        async_connection,
    )
    assert stranger.id is not None
    assert owned_date.id is not None

    # Act / Assert
    edited = ImportantDate(
        id=owned_date.id,
        contact_id=stranger.id,
        date_type=ImportantDateType.FIRST_MET,
        precision=DatePrecision.YEAR,
        year=2016,
    )
    with pytest.raises(ContactValidationError):
        await contact_service.update_contact_important_date(
            stranger.id, owned_date.id, edited, async_connection, user_id=TEST_USER_ID
        )


@pytest.mark.asyncio
async def test_update_important_date_rejects_unknown_date_id(
    contact_service: ContactService, async_connection: AsyncConnection
) -> None:
    """Editing a date that does not exist is refused."""
    # Arrange
    contact = await contact_service.create_contact(
        Contact(user_id=TEST_USER_ID, first_name="No", last_name="Dates"),
        async_connection,
    )
    assert contact.id is not None

    # Act / Assert
    edited = ImportantDate(
        id=999999,
        contact_id=contact.id,
        date_type=ImportantDateType.BIRTHDAY,
        precision=DatePrecision.YEAR,
        year=1990,
    )
    with pytest.raises(ContactValidationError):
        await contact_service.update_contact_important_date(
            contact.id, 999999, edited, async_connection, user_id=TEST_USER_ID
        )


@pytest.mark.asyncio
async def test_update_important_date_revalidates_the_entity(
    contact_service: ContactService, async_connection: AsyncConnection
) -> None:
    """The service re-runs domain validation on the entity it is handed.

    ``ImportantDate`` is a plain dataclass, so a caller that mutates one after
    construction can present a state ``__post_init__`` would have rejected -
    here, full precision with no day. The REST schema catches this earlier, but
    the service is the layer every surface shares.
    """
    # Arrange
    contact, saved_date = await _contact_with_date(
        contact_service,
        async_connection,
        ImportantDate(
            contact_id=0,
            date_type=ImportantDateType.BIRTHDAY,
            precision=DatePrecision.FULL,
            year=1990,
            month=5,
            day=15,
        ),
    )
    assert contact.id is not None
    assert saved_date.id is not None

    # Act - mutate past the constructor into an invalid state
    edited = ImportantDate(
        id=saved_date.id,
        contact_id=contact.id,
        date_type=ImportantDateType.BIRTHDAY,
        precision=DatePrecision.FULL,
        year=1990,
        month=5,
        day=15,
    )
    edited.day = None

    # Assert
    with pytest.raises(ValueError):
        await contact_service.update_contact_important_date(
            contact.id, saved_date.id, edited, async_connection, user_id=TEST_USER_ID
        )
