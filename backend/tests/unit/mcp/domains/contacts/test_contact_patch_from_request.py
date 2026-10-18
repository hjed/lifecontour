"""What MCP ``update_contact`` hands the service: only the fields it was given."""

import pytest
from core_shared.models.contacts.entities import MethodType
from core_shared.models.contacts.exceptions import ContactValidationError

from app.core.contacts.services.contact_patch import ContactFieldsPatch, ContactPatch
from app.mcp.domains.contacts.schemas import ContactUpdateRequest, ImportantDateInfo
from app.mcp.domains.contacts.tools import contact_patch_from_request


def test_a_request_naming_one_field_patches_only_that_field() -> None:
    patch = contact_patch_from_request(
        ContactUpdateRequest(contact_id=7, company="Difference Engines Ltd")
    )

    assert patch == ContactPatch(
        fields=ContactFieldsPatch(company="Difference Engines Ltd")
    )


@pytest.mark.parametrize(
    "field", ["first_name", "last_name", "middle_name", "nick_name"]
)
def test_an_empty_name_leaves_the_name_alone(field: str) -> None:
    patch = contact_patch_from_request(
        ContactUpdateRequest.model_validate({"contact_id": 7, field: ""})
    )

    assert patch.fields.changes() == {}


@pytest.mark.parametrize("field", ["company", "job_title"])
def test_an_empty_company_or_job_title_clears_it(field: str) -> None:
    patch = contact_patch_from_request(
        ContactUpdateRequest.model_validate({"contact_id": 7, field: ""})
    )

    assert patch.fields.changes() == {field: ""}


def test_email_phone_notes_and_tags_are_named_changes() -> None:
    patch = contact_patch_from_request(
        ContactUpdateRequest(
            contact_id=7,
            email="ada@example.com",
            phone="+61412345678",
            notes="Follows the cricket",
            tags=["friends"],
        )
    )

    assert patch.primary_methods == {
        MethodType.EMAIL: "ada@example.com",
        MethodType.PHONE: "+61412345678",
    }
    assert list(patch.new_notes) == ["Follows the cricket"]
    assert patch.tag_names == ["friends"]
    assert patch.important_dates is None


def test_a_custom_important_date_type_is_refused() -> None:
    request = ContactUpdateRequest(
        contact_id=7,
        important_dates=[
            ImportantDateInfo(
                date_type="custom", precision="full", year=2020, month=1, day=2
            )
        ],
    )

    with pytest.raises(ContactValidationError):
        contact_patch_from_request(request)
