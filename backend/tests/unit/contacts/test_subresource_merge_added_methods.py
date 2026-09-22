"""Unit tests for ``SubResourceMerge.added_methods``.

Adding a method keeps every stored one and never changes which is primary, so
an address can be added to a contact without touching the rest of its list.
"""

from core_shared.models.contacts.entities import Contact, ContactMethod, MethodType

from app.core.contacts.services.contact_subentity_sync import SubResourceMerge


def _stored(*methods: ContactMethod) -> Contact:
    return Contact(first_name="Jane", id=7, methods=list(methods))


def _email(value: str, *, is_primary: bool = False) -> ContactMethod:
    return ContactMethod(
        method_type=MethodType.EMAIL, value=value, contact_id=7, is_primary=is_primary
    )


def test_added_method_is_appended_as_non_primary() -> None:
    primary = _email("jane@home.com", is_primary=True)
    contact = Contact(first_name="Jane", id=7, methods=None)

    SubResourceMerge(added_methods=[(MethodType.EMAIL, "jane@work.com")]).apply_to(
        contact, _stored(primary)
    )

    assert contact.methods is not None
    assert [(m.value, m.is_primary) for m in contact.methods] == [
        ("jane@home.com", True),
        ("jane@work.com", False),
    ]


def test_first_method_of_its_type_becomes_primary() -> None:
    contact = Contact(first_name="Jane", id=7, methods=None)

    SubResourceMerge(added_methods=[(MethodType.EMAIL, "jane@work.com")]).apply_to(
        contact, _stored()
    )

    assert contact.methods is not None
    assert [(m.value, m.is_primary) for m in contact.methods] == [
        ("jane@work.com", True)
    ]


def test_email_already_held_in_another_case_is_not_added_again() -> None:
    held = _email("Jane@Work.com", is_primary=True)
    contact = Contact(first_name="Jane", id=7, methods=None)

    SubResourceMerge(added_methods=[(MethodType.EMAIL, "jane@work.com")]).apply_to(
        contact, _stored(held)
    )

    assert contact.methods == [held]


def test_added_methods_conflict_with_a_whole_method_list() -> None:
    merge = SubResourceMerge(added_methods=[(MethodType.EMAIL, "jane@work.com")])

    assert merge.conflicts(Contact(first_name="Jane", id=7, methods=[])) == ["methods"]
