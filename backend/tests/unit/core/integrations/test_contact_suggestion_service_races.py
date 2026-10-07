"""What accepting a suggestion does when another one got there first.

The contact is read before ``add_contact_method`` takes its lock, so two
accepts of the same suggestion can both decide to add the email. The loser's
insert is refused, which is the outcome it wanted as long as the winner landed
on the same contact. Driven with stubs because the race cannot be arranged
against a real database from one test.
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest
from core_shared.models.contacts.entities import Contact, ContactMethod, MethodType
from core_shared.models.history import Provenance

from app.core.contacts.models.exceptions import DuplicateEmailError
from app.core.integrations.services.contact_suggestion_service import (
    ContactSuggestionService,
    ExistingContactTarget,
)

CONTACT_ID = 7
EMAIL = "jane@x.com"
# The accepting user, who owns the contact the email is accepted into.
USER_ID = "user-1"


def _contact(*emails: str) -> Contact:
    return Contact(
        user_id=USER_ID,
        first_name="Jane",
        id=CONTACT_ID,
        methods=[
            ContactMethod(method_type=MethodType.EMAIL, value=e, contact_id=CONTACT_ID)
            for e in emails
        ],
    )


def _service(contact_service: Any) -> ContactSuggestionService:
    unmatched_repo = AsyncMock()
    unmatched_repo.list_for_email.return_value = []
    return ContactSuggestionService(
        unmatched_repo=unmatched_repo,
        ignore_repo=AsyncMock(),
        contact_service=contact_service,
        journal_contact_service=AsyncMock(),
    )


async def _accept(service: ContactSuggestionService) -> Contact:
    accepted = await service.accept(
        USER_ID,
        EMAIL,
        ExistingContactTarget(contact_id=CONTACT_ID),
        transaction=AsyncMock(),
        provenance=Provenance.UI,
    )
    return accepted.contact


@pytest.mark.asyncio
async def test_a_concurrent_accept_of_the_same_contact_succeeds() -> None:
    contact_service = AsyncMock()
    # Read without the email, then refused, then read with it: the other
    # accept added it in between.
    contact_service.get_contact_by_id.side_effect = [_contact(), _contact(EMAIL)]
    contact_service.add_contact_method.side_effect = DuplicateEmailError(
        EMAIL, existing_contact_id=CONTACT_ID
    )

    contact = await _accept(_service(contact_service))

    assert [m.value for m in contact.methods or []] == [EMAIL]


@pytest.mark.asyncio
async def test_an_email_taken_by_another_contact_still_raises() -> None:
    contact_service = AsyncMock()
    contact_service.get_contact_by_id.side_effect = [_contact(), _contact()]
    contact_service.add_contact_method.side_effect = DuplicateEmailError(
        EMAIL, existing_contact_id=CONTACT_ID
    )

    with pytest.raises(DuplicateEmailError):
        await _accept(_service(contact_service))
