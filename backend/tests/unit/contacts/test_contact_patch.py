"""Unit tests for ``ContactPatch``: a partial update applied to the stored contact."""

from copy import deepcopy

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

from app.core.contacts.services.contact_patch import ContactFieldsPatch, ContactPatch
from tests.integration.contact_seeding import TEST_USER_ID


def _stored() -> Contact:
    return Contact(
        id=7,
        user_id=TEST_USER_ID,
        first_name="Ada",
        last_name="Lovelace",
        company="Analytical Engines Ltd",
        job_title="Programmer",
        photo_url="/api/contacts/7/avatar",
        is_favourite=True,
        methods=[
            ContactMethod(
                id=1,
                contact_id=7,
                method_type=MethodType.EMAIL,
                value="ada@example.com",
                is_primary=True,
            ),
            ContactMethod(
                id=2,
                contact_id=7,
                method_type=MethodType.PHONE,
                value="+61412345678",
                is_primary=True,
            ),
        ],
        notes=[ContactNote(id=3, contact_id=7, content="Met at the salon")],
    )


class TestContactFields:
    def test_named_fields_change_and_the_rest_are_the_stored_ones(self) -> None:
        desired = ContactPatch(
            fields=ContactFieldsPatch(company="Difference Engines Ltd")
        ).apply_to(_stored())

        assert desired.company == "Difference Engines Ltd"
        assert (desired.first_name, desired.last_name, desired.job_title) == (
            "Ada",
            "Lovelace",
            "Programmer",
        )
        # Fields no patch can name are the stored ones too, not their defaults.
        assert desired.photo_url == "/api/contacts/7/avatar"
        assert desired.is_favourite is True

    def test_none_clears_a_field(self) -> None:
        desired = ContactPatch(fields=ContactFieldsPatch(job_title=None)).apply_to(
            _stored()
        )

        assert desired.job_title is None

    def test_children_it_does_not_name_are_left_as_stored(self) -> None:
        desired = ContactPatch(
            fields=ContactFieldsPatch(first_name="Augusta")
        ).apply_to(_stored())

        assert desired.methods is None
        assert desired.notes is None
        assert desired.addresses is None
        assert desired.important_dates is None
        assert desired.tags is None

    def test_the_stored_contact_is_not_modified(self) -> None:
        stored = _stored()
        before = deepcopy(stored)

        ContactPatch(
            fields=ContactFieldsPatch(first_name="Augusta"),
            primary_methods={MethodType.EMAIL: "augusta@example.com"},
            new_notes=["Follows the cricket"],
        ).apply_to(stored)

        assert stored == before


class TestChildMerges:
    def test_a_primary_email_keeps_the_stored_phone(self) -> None:
        desired = ContactPatch(
            primary_methods={MethodType.EMAIL: "augusta@example.com"}
        ).apply_to(_stored())

        assert desired.methods is not None
        primary = {m.method_type: m.value for m in desired.methods if m.is_primary}
        assert primary == {
            MethodType.EMAIL: "augusta@example.com",
            MethodType.PHONE: "+61412345678",
        }

    def test_a_note_is_added_after_the_stored_ones(self) -> None:
        desired = ContactPatch(new_notes=["Follows the cricket"]).apply_to(_stored())

        assert desired.notes is not None
        assert [(n.id, n.content) for n in desired.notes] == [
            (3, "Met at the salon"),
            (None, "Follows the cricket"),
        ]

    def test_important_dates_replace_the_stored_set(self) -> None:
        birthday = ImportantDate(
            contact_id=7,
            date_type=ImportantDateType.BIRTHDAY,
            precision=DatePrecision.FULL,
            year=1815,
            month=12,
            day=10,
        )

        desired = ContactPatch(important_dates=[birthday]).apply_to(_stored())

        assert desired.important_dates == [birthday]
