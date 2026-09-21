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
from app.core.contacts.services.contact_subentity_sync import SubResourceMerge
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
    async def test_retyping_a_date_is_reported_on_the_aggregate(
        self,
        contact_service: ContactService,
        async_connection: AsyncConnection,
        recorded_events: RecordingEventPublisher,
    ) -> None:
        """A date whose type moves has no match, so it is a delete and an add,
        and the aggregate row is its record. The count does not move, which is
        why that row has to describe the dates rather than count them."""
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
        assert _changed_fields(recorded_events)["important_dates"] == (
            "work_anniversary:2015",
            "birthday:1990-03-09",
        )

    @pytest.mark.asyncio
    async def test_a_stale_date_id_is_an_insert_not_an_edit_of_the_birthday(
        self,
        contact_service: ContactService,
        async_connection: AsyncConnection,
        recorded_events: RecordingEventPublisher,
    ) -> None:
        """A REST client holding an id for a date since deleted has named a row
        that is not there. That is not the stored birthday under another name,
        whatever its type: the natural key matches id-less submissions only."""
        saved = await _contact_with(
            contact_service,
            async_connection,
            recorded_events,
            important_dates=[_birthday()],
        )
        assert saved.important_dates is not None
        stored_id = saved.important_dates[0].id
        stale = _birthday(saved.id or 0, year=1991)
        stale.id = 999_999
        saved.important_dates = [stale]

        updated = await contact_service.update_contact(saved, async_connection)

        assert updated.important_dates is not None
        (date,) = updated.important_dates
        assert date.id not in (stored_id, 999_999)
        assert date.year == 1991
        assert recorded_events.of_type("ImportantDateUpdated") == []
        assert len(recorded_events.of_type("ImportantDateAdded")) == 1

    @pytest.mark.asyncio
    async def test_date_edits_are_published_in_the_order_they_were_submitted(
        self,
        contact_service: ContactService,
        async_connection: AsyncConnection,
        recorded_events: RecordingEventPublisher,
    ) -> None:
        """An id-less date matched on its type, submitted before one matched by
        id, is still published first - ids are matched in an earlier pass, but
        that is not the order the caller asked for."""
        saved = await _contact_with(
            contact_service,
            async_connection,
            recorded_events,
            important_dates=[_birthday(), _anniversary()],
        )
        assert saved.important_dates is not None
        by_type = {d.date_type: d for d in saved.important_dates}
        birthday_id = by_type[ImportantDateType.BIRTHDAY].id
        anniversary_id = by_type[ImportantDateType.WORK_ANNIVERSARY].id
        edited_anniversary = _anniversary(saved.id or 0, year=2016)
        edited_anniversary.id = anniversary_id
        saved.important_dates = [
            _birthday(saved.id or 0, year=1991),
            edited_anniversary,
        ]

        await contact_service.update_contact(saved, async_connection)

        published = recorded_events.of_type("ImportantDateUpdated")
        assert [e.event_data["date_id"] for e in published] == [
            birthday_id,
            anniversary_id,
        ]


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
        changed = _changed_fields(recorded_events)
        assert changed[f"method_{method_id}_value"] == (
            "before@example.com",
            "after@example.com",
        )
        # The per-field row is the record, as it is for a field-level PATCH; an
        # aggregate row beside it would report the same edit twice.
        assert "contact_methods" not in changed
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
        changed = _changed_fields(recorded_events)
        assert changed[f"address_{address_id}_street_line_1"] == (
            "1 Old Street",
            "2 New Street",
        )
        assert "addresses" not in changed

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

    @pytest.mark.asyncio
    async def test_replacing_a_note_is_reported_on_the_aggregate(
        self,
        contact_service: ContactService,
        async_connection: AsyncConnection,
        recorded_events: RecordingEventPublisher,
    ) -> None:
        """One note out, another in: the count holds, so a count-based row
        would have said nothing about it."""
        saved = await _contact_with(
            contact_service,
            async_connection,
            recorded_events,
            notes=[ContactNote(content="Met at the conference", contact_id=0)],
        )
        saved.notes = [ContactNote(content="Follows the cricket", contact_id=0)]

        await contact_service.update_contact(saved, async_connection)

        assert _changed_fields(recorded_events)["notes"] == (
            "Met at the conference",
            "Follows the cricket",
        )

    @pytest.mark.asyncio
    async def test_resubmitting_a_note_without_its_id_is_not_a_change(
        self,
        contact_service: ContactService,
        async_connection: AsyncConnection,
        recorded_events: RecordingEventPublisher,
    ) -> None:
        """A client that drops the id re-creates the note, but nothing a reader
        of the feed could see has moved."""
        saved = await _contact_with(
            contact_service,
            async_connection,
            recorded_events,
            notes=[ContactNote(content="Met at the conference", contact_id=0)],
        )
        saved.notes = [ContactNote(content="Met at the conference", contact_id=0)]

        await contact_service.update_contact(saved, async_connection)

        assert recorded_events.of_type("ContactUpdated") == []


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


class TestUniqueIndexesDuringASave:
    """A valid final state must not fail because of the order the list was in.

    The delete-all save never met these indexes mid-save; updating rows in
    place does, one row at a time, so the updates have to be ordered.
    """

    @pytest.mark.asyncio
    async def test_moving_the_primary_between_two_stored_methods(
        self,
        contact_service: ContactService,
        async_connection: AsyncConnection,
        recorded_events: RecordingEventPublisher,
    ) -> None:
        saved = await _contact_with(
            contact_service,
            async_connection,
            recorded_events,
            methods=[
                ContactMethod(
                    method_type=MethodType.EMAIL,
                    value="old.primary@example.com",
                    contact_id=0,
                    is_primary=True,
                ),
                ContactMethod(
                    method_type=MethodType.EMAIL,
                    value="new.primary@example.com",
                    contact_id=0,
                ),
            ],
        )
        assert saved.methods is not None
        old, new = saved.methods
        # The promotion comes first in the list - the order that fails when
        # rows are updated as they come.
        saved.methods = [
            ContactMethod(
                id=new.id,
                method_type=MethodType.EMAIL,
                value=new.value,
                contact_id=0,
                is_primary=True,
            ),
            ContactMethod(
                id=old.id,
                method_type=MethodType.EMAIL,
                value=old.value,
                contact_id=0,
                is_primary=False,
            ),
        ]

        updated = await contact_service.update_contact(saved, async_connection)

        assert updated.methods is not None
        primaries = {m.id: m.is_primary for m in updated.methods}
        assert primaries == {new.id: True, old.id: False}

    @pytest.mark.asyncio
    async def test_swapping_which_stored_date_is_the_birthday(
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
        assert saved.important_dates is not None
        by_type = {d.date_type: d for d in saved.important_dates}
        birthday_id = by_type[ImportantDateType.BIRTHDAY].id
        anniversary_id = by_type[ImportantDateType.WORK_ANNIVERSARY].id
        # REST sends ids, so each row is matched by id and retyped - with the
        # row becoming the birthday first.
        becomes_birthday = _birthday(saved.id or 0, year=2015)
        becomes_birthday.id = anniversary_id
        becomes_anniversary = _anniversary(saved.id or 0, year=1990)
        becomes_anniversary.id = birthday_id
        saved.important_dates = [becomes_birthday, becomes_anniversary]

        updated = await contact_service.update_contact(saved, async_connection)

        assert updated.important_dates is not None
        assert {d.id: d.date_type for d in updated.important_dates} == {
            anniversary_id: ImportantDateType.BIRTHDAY,
            birthday_id: ImportantDateType.WORK_ANNIVERSARY,
        }
        assert len(recorded_events.of_type("ImportantDateUpdated")) == 2

    @pytest.mark.asyncio
    async def test_swapping_two_stored_emails(
        self,
        contact_service: ContactService,
        async_connection: AsyncConnection,
        recorded_events: RecordingEventPublisher,
    ) -> None:
        saved = await _contact_with(
            contact_service,
            async_connection,
            recorded_events,
            methods=[
                ContactMethod(
                    method_type=MethodType.EMAIL,
                    value="swap.one@example.com",
                    contact_id=0,
                    label="home",
                ),
                ContactMethod(
                    method_type=MethodType.EMAIL,
                    value="swap.two@example.com",
                    contact_id=0,
                    label="work",
                ),
            ],
        )
        assert saved.methods is not None
        home, work = saved.methods
        home.value, work.value = work.value, home.value

        updated = await contact_service.update_contact(saved, async_connection)

        assert updated.methods is not None
        assert {m.label: m.value for m in updated.methods} == {
            "home": "swap.two@example.com",
            "work": "swap.one@example.com",
        }
        # Both halves of the swap are edits and both reach the feed - including
        # the row re-created to break the cycle, keyed by its new id.
        ids = {m.label: m.id for m in updated.methods}
        changed = _changed_fields(recorded_events)
        assert changed[f"method_{ids['home']}_value"] == (
            "swap.one@example.com",
            "swap.two@example.com",
        )
        assert changed[f"method_{ids['work']}_value"] == (
            "swap.two@example.com",
            "swap.one@example.com",
        )
        assert "contact_methods" not in changed


class TestSubResourceMerge:
    """A change named rather than listed, applied to the contact as it stands.

    MCP sets one primary email or adds one note. The merge is applied by the
    service after it has locked the contact and read its rows, so a row the
    caller never saw - one added while it was deciding - is kept.
    """

    @pytest.mark.asyncio
    async def test_a_primary_email_merge_keeps_the_stored_phone(
        self,
        contact_service: ContactService,
        async_connection: AsyncConnection,
        recorded_events: RecordingEventPublisher,
    ) -> None:
        saved = await _contact_with(
            contact_service,
            async_connection,
            recorded_events,
            methods=[
                ContactMethod(
                    method_type=MethodType.EMAIL,
                    value="merge.before@example.com",
                    contact_id=0,
                    is_primary=True,
                ),
                ContactMethod(
                    method_type=MethodType.PHONE,
                    value="+61412345678",
                    contact_id=0,
                    is_primary=True,
                ),
            ],
        )
        assert saved.methods is not None
        ids = {m.method_type: m.id for m in saved.methods}

        # The contact handed in carries no methods at all: what is kept can
        # only have come from the service's own read.
        updated = await contact_service.update_contact(
            Contact(
                id=saved.id, first_name=saved.first_name, last_name=saved.last_name
            ),
            async_connection,
            subresource_merge=SubResourceMerge(
                primary_methods={MethodType.EMAIL: "merge.after@example.com"}
            ),
        )

        assert updated.methods is not None
        by_type = {m.method_type: m for m in updated.methods}
        assert by_type[MethodType.EMAIL].id == ids[MethodType.EMAIL]
        assert by_type[MethodType.EMAIL].value == "merge.after@example.com"
        assert by_type[MethodType.PHONE].id == ids[MethodType.PHONE]
        changed = _changed_fields(recorded_events)
        assert changed[f"method_{ids[MethodType.EMAIL]}_value"] == (
            "merge.before@example.com",
            "merge.after@example.com",
        )

    @pytest.mark.asyncio
    async def test_a_note_merge_appends_to_the_stored_notes(
        self,
        contact_service: ContactService,
        async_connection: AsyncConnection,
        recorded_events: RecordingEventPublisher,
    ) -> None:
        saved = await _contact_with(
            contact_service,
            async_connection,
            recorded_events,
            notes=[ContactNote(content="Met at the conference", contact_id=0)],
        )
        assert saved.notes is not None
        stored_id = saved.notes[0].id

        updated = await contact_service.update_contact(
            Contact(
                id=saved.id, first_name=saved.first_name, last_name=saved.last_name
            ),
            async_connection,
            subresource_merge=SubResourceMerge(new_notes=["Follows the cricket"]),
        )

        assert updated.notes is not None
        assert [(n.id == stored_id, n.content) for n in updated.notes] == [
            (True, "Met at the conference"),
            (False, "Follows the cricket"),
        ]
