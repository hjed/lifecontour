"""The whole-contact save reconciles sub-entities instead of replacing them.

``update_contact`` takes the whole desired state of a contact's methods,
addresses, notes and important dates. It used to apply that by deleting every
row and re-inserting it, which left an *edit* indistinguishable from a re-save:
the row's id churned and the per-item events were suppressed, so the activity
feed showed nothing (issue #1524). These tests pin the reconcile that replaced
it — a matched row is updated in place and published as the edit it is.
"""

import pytest
from core_shared.models.contacts.entities import (
    Contact,
    ContactAddress,
    ContactMethod,
    ContactNote,
    ImportantDate,
    MethodType,
)
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)
from core_shared.models.history import Provenance
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.services.contact_service import ContactService
from tests.integration.contacts.contact_service_harness import (
    RecordingEventPublisher,
    build_contact_service,
)


@pytest.fixture
def recorded_events() -> RecordingEventPublisher:
    return RecordingEventPublisher()


@pytest.fixture
def contact_service(
    async_connection: AsyncConnection, recorded_events: RecordingEventPublisher
) -> ContactService:
    return build_contact_service(async_connection, recorded_events)


def _birthday(contact_id: int = 0, *, year: int = 1990) -> ImportantDate:
    return ImportantDate(
        contact_id=contact_id,
        date_type=ImportantDateType.BIRTHDAY,
        precision=DatePrecision.FULL,
        year=year,
        month=3,
        day=9,
    )


def _anniversary(contact_id: int = 0, *, year: int = 2015) -> ImportantDate:
    return ImportantDate(
        contact_id=contact_id,
        date_type=ImportantDateType.WORK_ANNIVERSARY,
        precision=DatePrecision.YEAR,
        year=year,
    )


async def _contact_with(
    service: ContactService,
    connection: AsyncConnection,
    events: RecordingEventPublisher,
    **attached: object,
) -> Contact:
    """Create a contact with sub-entities attached, then forget those events."""
    contact = Contact(first_name="Reconcile", last_name="Test")
    for name, value in attached.items():
        setattr(contact, name, value)
    saved = await service.create_contact(
        contact, connection, changed_by="ui", source=Provenance.UI
    )
    assert saved.id is not None
    events.clear()
    return saved


def _changed_fields(events: RecordingEventPublisher) -> dict[str, object]:
    """The changed_fields of the one aggregate ContactUpdated a save publishes."""
    updates = events.of_type("ContactUpdated")
    assert len(updates) == 1, f"expected one ContactUpdated, got {len(updates)}"
    return dict(updates[0].event_data["changed_fields"])


class TestMatchedImportantDate:
    @pytest.mark.asyncio
    async def test_an_edited_date_keeps_its_row_and_publishes_the_edit(
        self,
        contact_service: ContactService,
        async_connection: AsyncConnection,
        recorded_events: RecordingEventPublisher,
    ) -> None:
        """MCP submits dates with no ids, so the birthday is matched on its
        type — and an edit of it is an edit, not a delete and a re-insert."""
        saved = await _contact_with(
            contact_service,
            async_connection,
            recorded_events,
            important_dates=[_birthday()],
        )
        assert saved.important_dates is not None
        original_id = saved.important_dates[0].id

        saved.important_dates = [_birthday(saved.id or 0, year=1991)]
        updated = await contact_service.update_contact(
            saved, async_connection, changed_by="mcp", source=Provenance.MCP
        )

        assert updated.important_dates is not None
        assert updated.important_dates[0].id == original_id
        assert updated.important_dates[0].year == 1991

        published = recorded_events.of_type("ImportantDateUpdated")
        assert len(published) == 1
        assert published[0].event_data["date_id"] == original_id
        assert published[0].event_data["changed_fields"] == {"year": (1990, 1991)}
        assert recorded_events.of_type("ImportantDateAdded") == []

    @pytest.mark.asyncio
    async def test_an_unchanged_date_is_not_written_at_all(
        self,
        contact_service: ContactService,
        async_connection: AsyncConnection,
        recorded_events: RecordingEventPublisher,
    ) -> None:
        saved = await _contact_with(
            contact_service,
            async_connection,
            recorded_events,
            important_dates=[_birthday()],
        )
        assert saved.important_dates is not None
        original_id = saved.important_dates[0].id

        saved.important_dates = [_birthday(saved.id or 0)]
        updated = await contact_service.update_contact(saved, async_connection)

        assert updated.important_dates is not None
        assert updated.important_dates[0].id == original_id
        assert recorded_events.of_type("ImportantDateUpdated") == []
        assert recorded_events.of_type("ImportantDateAdded") == []

    @pytest.mark.asyncio
    async def test_a_new_date_is_added_without_a_history_marker(
        self,
        contact_service: ContactService,
        async_connection: AsyncConnection,
        recorded_events: RecordingEventPublisher,
    ) -> None:
        """A bulk add keeps its aggregate row as the feed, as it always has."""
        saved = await _contact_with(
            contact_service,
            async_connection,
            recorded_events,
            important_dates=[_birthday()],
        )
        contact_id = saved.id or 0
        saved.important_dates = [_birthday(contact_id), _anniversary(contact_id)]

        updated = await contact_service.update_contact(saved, async_connection)

        assert updated.important_dates is not None
        assert len(updated.important_dates) == 2
        added = recorded_events.of_type("ImportantDateAdded")
        assert len(added) == 1
        assert added[0].event_data["affects_history"] is False
        assert recorded_events.of_type("ImportantDateUpdated") == []

    @pytest.mark.asyncio
    async def test_a_dropped_date_is_deleted_and_its_neighbour_kept(
        self,
        contact_service: ContactService,
        async_connection: AsyncConnection,
        recorded_events: RecordingEventPublisher,
    ) -> None:
        saved = await _contact_with(
            contact_service,
            async_connection,
            recorded_events,
            important_dates=[_birthday(), _anniversary()],
        )
        contact_id = saved.id or 0
        assert saved.important_dates is not None
        birthday_id = next(
            d.id
            for d in saved.important_dates
            if d.date_type == ImportantDateType.BIRTHDAY
        )
        saved.important_dates = [_birthday(contact_id)]

        updated = await contact_service.update_contact(saved, async_connection)

        assert updated.important_dates is not None
        assert [d.id for d in updated.important_dates] == [birthday_id]

    @pytest.mark.asyncio
    async def test_retyping_a_date_is_reported_field_by_field(
        self,
        contact_service: ContactService,
        async_connection: AsyncConnection,
        recorded_events: RecordingEventPublisher,
    ) -> None:
        """A date whose type moves has no match, so it is a delete and an add —
        the aggregate row is the feed for that, as for any other bulk add."""
        saved = await _contact_with(
            contact_service,
            async_connection,
            recorded_events,
            important_dates=[_anniversary()],
        )
        contact_id = saved.id or 0
        saved.important_dates = [_birthday(contact_id)]

        updated = await contact_service.update_contact(saved, async_connection)

        assert updated.important_dates is not None
        assert updated.important_dates[0].date_type == ImportantDateType.BIRTHDAY
        assert recorded_events.of_type("ImportantDateUpdated") == []
        assert len(recorded_events.of_type("ImportantDateAdded")) == 1


class TestMatchedMethodAddressAndNote:
    @pytest.mark.asyncio
    async def test_an_edited_method_reports_its_field_on_the_contact_event(
        self,
        contact_service: ContactService,
        async_connection: AsyncConnection,
        recorded_events: RecordingEventPublisher,
    ) -> None:
        """The same key a field-level PATCH writes, so the feed reads the same
        whichever surface made the change."""
        saved = await _contact_with(
            contact_service,
            async_connection,
            recorded_events,
            methods=[
                ContactMethod(
                    method_type=MethodType.EMAIL,
                    value="before@example.com",
                    contact_id=0,
                )
            ],
        )
        assert saved.methods is not None
        method_id = saved.methods[0].id
        saved.methods[0].value = "after@example.com"

        updated = await contact_service.update_contact(
            saved, async_connection, changed_by="ui", source=Provenance.UI
        )

        assert updated.methods is not None
        assert updated.methods[0].id == method_id
        assert _changed_fields(recorded_events)[f"method_{method_id}_value"] == (
            "before@example.com",
            "after@example.com",
        )
        assert recorded_events.of_type("ContactMethodAdded") == []

    @pytest.mark.asyncio
    async def test_an_edited_address_reports_its_field(
        self,
        contact_service: ContactService,
        async_connection: AsyncConnection,
        recorded_events: RecordingEventPublisher,
    ) -> None:
        saved = await _contact_with(
            contact_service,
            async_connection,
            recorded_events,
            addresses=[
                ContactAddress(
                    street_line_1="1 Old Street",
                    country_code="AU",
                    contact_id=0,
                    locality="Sydney",
                    postal_code="2000",
                )
            ],
        )
        assert saved.addresses is not None
        address_id = saved.addresses[0].id
        saved.addresses[0].street_line_1 = "2 New Street"

        updated = await contact_service.update_contact(saved, async_connection)

        assert updated.addresses is not None
        assert updated.addresses[0].id == address_id
        assert _changed_fields(recorded_events)[
            f"address_{address_id}_street_line_1"
        ] == ("1 Old Street", "2 New Street")

    @pytest.mark.asyncio
    async def test_an_edited_note_reports_its_field(
        self,
        contact_service: ContactService,
        async_connection: AsyncConnection,
        recorded_events: RecordingEventPublisher,
    ) -> None:
        """A note edit that keeps the count published nothing at all before:
        the aggregate only compares how many there are."""
        saved = await _contact_with(
            contact_service,
            async_connection,
            recorded_events,
            notes=[ContactNote(content="Met at the conference", contact_id=0)],
        )
        assert saved.notes is not None
        note_id = saved.notes[0].id
        saved.notes[0].content = "Met at the cricket"

        updated = await contact_service.update_contact(saved, async_connection)

        assert updated.notes is not None
        assert updated.notes[0].id == note_id
        assert _changed_fields(recorded_events)[f"note_{note_id}_content"] == (
            "Met at the conference",
            "Met at the cricket",
        )

    @pytest.mark.asyncio
    async def test_an_id_less_note_is_added_beside_the_stored_one(
        self,
        contact_service: ContactService,
        async_connection: AsyncConnection,
        recorded_events: RecordingEventPublisher,
    ) -> None:
        """Content is a note's payload, not a key, so a new note is never
        mistaken for an edit of the note already there."""
        saved = await _contact_with(
            contact_service,
            async_connection,
            recorded_events,
            notes=[ContactNote(content="Met at the conference", contact_id=0)],
        )
        contact_id = saved.id or 0
        assert saved.notes is not None
        stored_id = saved.notes[0].id
        saved.notes = [
            saved.notes[0],
            ContactNote(content="Follows the cricket", contact_id=contact_id),
        ]

        updated = await contact_service.update_contact(saved, async_connection)

        assert updated.notes is not None
        assert len(updated.notes) == 2
        assert stored_id in [n.id for n in updated.notes]
        assert len(recorded_events.of_type("ContactNoteAdded")) == 1


class TestPrimaryAndUniquenessGuards:
    @pytest.mark.asyncio
    async def test_making_a_matched_method_primary_is_allowed(
        self,
        contact_service: ContactService,
        async_connection: AsyncConnection,
        recorded_events: RecordingEventPublisher,
    ) -> None:
        """An in-place edit does not re-run the insert path's primary check,
        which has no way to exclude the row being edited; the partial unique
        index is what guarantees one primary per type."""
        saved = await _contact_with(
            contact_service,
            async_connection,
            recorded_events,
            methods=[
                ContactMethod(
                    method_type=MethodType.EMAIL,
                    value="promote@example.com",
                    contact_id=0,
                    is_primary=True,
                )
            ],
        )
        assert saved.methods is not None
        method_id = saved.methods[0].id
        saved.methods[0].value = "promoted@example.com"

        updated = await contact_service.update_contact(saved, async_connection)

        assert updated.methods is not None
        assert updated.methods[0].id == method_id
        assert updated.methods[0].is_primary is True

    @pytest.mark.asyncio
    async def test_editing_a_method_onto_another_contacts_email_is_refused(
        self,
        contact_service: ContactService,
        async_connection: AsyncConnection,
        recorded_events: RecordingEventPublisher,
    ) -> None:
        """Updating the row in place must keep the guarantee the insert had."""
        await _contact_with(
            contact_service,
            async_connection,
            recorded_events,
            methods=[
                ContactMethod(
                    method_type=MethodType.EMAIL,
                    value="taken@example.com",
                    contact_id=0,
                )
            ],
        )
        saved = await _contact_with(
            contact_service,
            async_connection,
            recorded_events,
            methods=[
                ContactMethod(
                    method_type=MethodType.EMAIL,
                    value="free@example.com",
                    contact_id=0,
                )
            ],
        )
        assert saved.methods is not None
        saved.methods[0].value = "taken@example.com"

        with pytest.raises(Exception, match="(?i)email"):
            await contact_service.update_contact(saved, async_connection)
