"""Unit tests for the contact sync scope: what an inbound sync may change."""

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from core_shared.models.contacts.entities import (
    Contact,
    ContactMethod,
    ContactNote,
    ImportantDate,
    MethodType,
)
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)
from core_shared.models.contacts.sync_scope import (
    ContactSyncField,
    ContactSyncScope,
    apply_sync_scope,
)
from core_shared.models.outbox import OutboxEvent
from core_shared.models.outbox_events import ContactSyncEventData

NAMES_ONLY = ContactSyncScope(
    fields=frozenset({ContactSyncField.FIRST_NAME, ContactSyncField.LAST_NAME}),
)


def _date(
    date_type: ImportantDateType, day: int, date_id: int | None = None
) -> ImportantDate:
    return ImportantDate(
        contact_id=1,
        date_type=date_type,
        precision=DatePrecision.DAY_MONTH,
        month=3,
        day=day,
        id=date_id,
    )


def _stored() -> Contact:
    return Contact(
        id=1,
        user_id="user-1",
        first_name="Robert",
        last_name="Smith",
        middle_name="James",
        nick_name="Bob",
        company="Acme",
        job_title="Engineer",
        photo_url="/api/contacts/1/avatar",
        is_favourite=True,
        methods=[
            ContactMethod(MethodType.EMAIL, "bob@example.com", contact_id=1, id=7)
        ],
        notes=[ContactNote(contact_id=1, content="Met at the conference", id=8)],
        important_dates=[
            _date(ImportantDateType.BIRTHDAY, 1, date_id=11),
            _date(ImportantDateType.FIRST_MET, 2, date_id=12),
        ],
    )


class TestApplySyncScopeScalars:
    def test_unowned_scalars_keep_stored_values(self) -> None:
        incoming = Contact(user_id="user-1", first_name="Rob", last_name="Smyth")

        apply_sync_scope(incoming, _stored(), NAMES_ONLY)

        assert (incoming.first_name, incoming.last_name) == ("Rob", "Smyth")
        assert incoming.middle_name == "James"
        assert incoming.nick_name == "Bob"
        assert incoming.company == "Acme"
        assert incoming.job_title == "Engineer"
        assert incoming.photo_url == "/api/contacts/1/avatar"
        assert incoming.is_favourite is True

    def test_owned_scalar_set_to_none_clears(self) -> None:
        scope = ContactSyncScope(
            fields=frozenset({ContactSyncField.FIRST_NAME, ContactSyncField.NICK_NAME})
        )
        incoming = Contact(user_id="user-1", first_name="Robert", nick_name=None)

        apply_sync_scope(incoming, _stored(), scope)

        assert incoming.nick_name is None

    def test_no_scope_leaves_incoming_untouched(self) -> None:
        incoming = Contact(user_id="user-1", first_name="Rob")

        apply_sync_scope(incoming, _stored(), None)

        assert incoming.nick_name is None
        assert incoming.company is None
        assert incoming.methods is None


class TestApplySyncScopeLists:
    def test_unowned_lists_are_left_alone(self) -> None:
        incoming = Contact(
            user_id="user-1",
            first_name="Rob",
            methods=[],
            notes=[],
            addresses=[],
            tags=[],
        )

        apply_sync_scope(incoming, _stored(), NAMES_ONLY)

        assert incoming.methods is None
        assert incoming.notes is None
        assert incoming.addresses is None
        assert incoming.tags is None

    def test_owned_list_is_kept_even_when_empty(self) -> None:
        scope = ContactSyncScope(
            fields=frozenset({ContactSyncField.FIRST_NAME, ContactSyncField.METHODS})
        )
        incoming = Contact(user_id="user-1", first_name="Rob", methods=[])

        apply_sync_scope(incoming, _stored(), scope)

        assert incoming.methods == []


class TestApplySyncScopeImportantDates:
    BIRTHDAYS = ContactSyncScope(
        fields=frozenset({ContactSyncField.FIRST_NAME}),
        important_date_types=frozenset({ImportantDateType.BIRTHDAY}),
    )

    def test_owned_type_replaced_and_unowned_stored_dates_kept(self) -> None:
        incoming = Contact(
            user_id="user-1",
            first_name="Rob",
            important_dates=[_date(ImportantDateType.BIRTHDAY, 9)],
        )

        apply_sync_scope(incoming, _stored(), self.BIRTHDAYS)

        dates = incoming.important_dates or []
        assert [(d.date_type, d.day, d.id) for d in dates] == [
            (ImportantDateType.BIRTHDAY, 9, None),
            (ImportantDateType.FIRST_MET, 2, 12),
        ]

    def test_empty_owned_dates_clear_owned_types_only(self) -> None:
        incoming = Contact(user_id="user-1", first_name="Rob", important_dates=[])

        apply_sync_scope(incoming, _stored(), self.BIRTHDAYS)

        dates = incoming.important_dates or []
        assert [(d.date_type, d.id) for d in dates] == [
            (ImportantDateType.FIRST_MET, 12)
        ]

    def test_incoming_dates_of_unowned_types_are_dropped(self) -> None:
        incoming = Contact(
            user_id="user-1",
            first_name="Rob",
            important_dates=[
                _date(ImportantDateType.BIRTHDAY, 9),
                _date(ImportantDateType.WORK_ANNIVERSARY, 5),
            ],
        )

        apply_sync_scope(incoming, _stored(), self.BIRTHDAYS)

        dates = incoming.important_dates or []
        assert [(d.date_type, d.id) for d in dates] == [
            (ImportantDateType.BIRTHDAY, None),
            (ImportantDateType.FIRST_MET, 12),
        ]

    def test_none_dates_leave_stored_dates_untouched(self) -> None:
        incoming = Contact(user_id="user-1", first_name="Rob", important_dates=None)

        apply_sync_scope(incoming, _stored(), self.BIRTHDAYS)

        assert incoming.important_dates is None

    def test_scope_owning_no_date_types_leaves_dates_untouched(self) -> None:
        incoming = Contact(
            user_id="user-1",
            first_name="Rob",
            important_dates=[_date(ImportantDateType.BIRTHDAY, 9)],
        )

        apply_sync_scope(incoming, _stored(), NAMES_ONLY)

        assert incoming.important_dates is None


class TestContactSyncScopeOnTheEvent:
    def test_event_round_trips_scope_through_json(self) -> None:
        scope = ContactSyncScope(
            fields=frozenset({ContactSyncField.PHOTO_URL}),
            important_date_types=frozenset({ImportantDateType.BIRTHDAY}),
        )

        event = OutboxEvent.create_contact_sync_event(
            contact_data={"first_name": "Rob"},
            integration_source="immich",
            external_id="person-1",
            sync_type="updated",
            user_id="user-1",
            sync_scope=scope,
        )
        stored_json = json.loads(json.dumps(event.event_data))

        assert stored_json["sync_scope"] == {
            "fields": ["photo_url"],
            "important_date_types": ["birthday"],
        }
        parsed = ContactSyncEventData.model_validate(stored_json)
        assert parsed.sync_scope == scope

    def test_event_without_scope_parses_as_none(self) -> None:
        parsed = ContactSyncEventData.model_validate(
            {
                "integration_source": "google",
                "external_id": "people/c1",
                "contact_data": {"first_name": "Rob"},
                "sync_timestamp": datetime.now(UTC).isoformat(),
                "sync_type": "updated",
                "user_id": "user-1",
            }
        )

        assert parsed.sync_scope is None

    def test_unknown_field_name_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ContactSyncScope.model_validate({"fields": ["nickname"]})
