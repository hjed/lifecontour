"""Every by-id ContactService operation treats another user's contact as missing.

The repository is owner-scoped, so for a foreign id its reads come back empty
(``find_by_id`` is ``None``, ``contact_exists`` is false). These tests stand in
that answer and prove each operation then raises ``ContactNotFoundError``, asks
for the contact *as the acting user*, and writes and publishes nothing.
"""

from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock

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

from app.core.contacts.models.exceptions import ContactNotFoundError
from app.core.contacts.services import (
    AddressValidationService,
    ContactHistoryService,
    ContactValidationService,
    TagHierarchyService,
)
from app.core.contacts.services.contact_service import ContactService
from tests.integration.contact_seeding import OTHER_USER_ID, TEST_USER_ID

FOREIGN_ID = 7

# Every repository method that writes the aggregate or one of its child rows.
WRITES = (
    "save",
    "delete",
    "add_method",
    "update_method",
    "delete_method",
    "add_address",
    "update_address",
    "delete_address",
    "add_note",
    "update_note",
    "delete_note",
    "assign_tag",
    "remove_tag",
    "add_important_date",
    "update_important_date",
    "delete_important_date",
    "touch",
)

Operation = Callable[[ContactService, AsyncMock], Awaitable[Any]]


def _date() -> ImportantDate:
    return ImportantDate(
        contact_id=FOREIGN_ID,
        date_type=ImportantDateType.BIRTHDAY,
        precision=DatePrecision.FULL,
        year=1990,
        month=5,
        day=15,
    )


OPERATIONS: dict[str, Operation] = {
    "get_contact_by_id": lambda s, tx: s.get_contact_by_id(
        FOREIGN_ID, user_id=TEST_USER_ID
    ),
    "update_contact": lambda s, tx: s.update_contact(
        Contact(id=FOREIGN_ID, first_name="Kyle", user_id=TEST_USER_ID),
        tx,
        user_id=TEST_USER_ID,
    ),
    "update_contact_field": lambda s, tx: s.update_contact_field(
        FOREIGN_ID, "first_name", "Kyle", tx, user_id=TEST_USER_ID
    ),
    "update_contact_method_field": lambda s, tx: s.update_contact_method_field(
        FOREIGN_ID, 1, "is_archived", True, tx, user_id=TEST_USER_ID
    ),
    "update_contact_address_field": lambda s, tx: s.update_contact_address_field(
        FOREIGN_ID, 1, "is_archived", True, tx, user_id=TEST_USER_ID
    ),
    "update_contact_note_field": lambda s, tx: s.update_contact_note_field(
        FOREIGN_ID, 1, "content", "x", tx, user_id=TEST_USER_ID
    ),
    "delete_contact": lambda s, tx: s.delete_contact(
        FOREIGN_ID, tx, user_id=TEST_USER_ID
    ),
    "toggle_contact_favourite": lambda s, tx: s.toggle_contact_favourite(
        FOREIGN_ID, tx, user_id=TEST_USER_ID
    ),
    "assign_tag_to_contact": lambda s, tx: s.assign_tag_to_contact(
        FOREIGN_ID, 1, tx, user_id=TEST_USER_ID
    ),
    "remove_tag_from_contact": lambda s, tx: s.remove_tag_from_contact(
        FOREIGN_ID, 1, tx, user_id=TEST_USER_ID
    ),
    "add_contact_method": lambda s, tx: s.add_contact_method(
        FOREIGN_ID,
        ContactMethod(
            method_type=MethodType.EMAIL, value="k@example.com", contact_id=FOREIGN_ID
        ),
        tx,
        user_id=TEST_USER_ID,
    ),
    "add_contact_address": lambda s, tx: s.add_contact_address(
        FOREIGN_ID,
        ContactAddress(
            street_line_1="1 Main St", country_code="AU", contact_id=FOREIGN_ID
        ),
        tx,
        user_id=TEST_USER_ID,
    ),
    "add_contact_note": lambda s, tx: s.add_contact_note(
        FOREIGN_ID,
        ContactNote(content="hello", contact_id=FOREIGN_ID),
        tx,
        user_id=TEST_USER_ID,
    ),
    "add_contact_important_date": lambda s, tx: s.add_contact_important_date(
        FOREIGN_ID, _date(), tx, user_id=TEST_USER_ID
    ),
    "update_contact_important_date": lambda s, tx: s.update_contact_important_date(
        FOREIGN_ID, 1, _date(), tx, user_id=TEST_USER_ID
    ),
    "delete_contact_method": lambda s, tx: s.delete_contact_method(
        FOREIGN_ID, 1, tx, user_id=TEST_USER_ID
    ),
    "delete_contact_address": lambda s, tx: s.delete_contact_address(
        FOREIGN_ID, 1, tx, user_id=TEST_USER_ID
    ),
    "delete_contact_important_date": lambda s, tx: s.delete_contact_important_date(
        FOREIGN_ID, 1, tx, user_id=TEST_USER_ID
    ),
    "get_external_references": lambda s, tx: s.get_external_references(
        FOREIGN_ID, user_id=TEST_USER_ID
    ),
    "get_contact_history": lambda s, tx: s.get_contact_history(
        FOREIGN_ID, user_id=TEST_USER_ID
    ),
}


# The one read whose not-found answer is ``None`` rather than a raise; its
# callers turn that into the 404. Every other operation must raise itself.
ANSWERS_NONE = frozenset({"get_contact_by_id"})


@pytest.fixture
def contact_repo() -> AsyncMock:
    """A repository answering as it does for another user's contact."""
    repo = AsyncMock()
    repo.find_by_id.return_value = None
    repo.contact_exists.return_value = False
    return repo


@pytest.fixture
def event_publisher() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def history_repo() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def service(
    contact_repo: AsyncMock, event_publisher: AsyncMock, history_repo: AsyncMock
) -> ContactService:
    tag_repo = AsyncMock()
    return ContactService(
        contact_repo=contact_repo,
        tag_repo=tag_repo,
        history_repo=history_repo,
        event_publisher=event_publisher,
        address_validation_service=AddressValidationService(),
        contact_validation_service=ContactValidationService(contact_repo),
        history_service=ContactHistoryService(history_repo),
        tag_hierarchy_service=TagHierarchyService(tag_repo),
    )


def _asked_as_acting_user(contact_repo: AsyncMock) -> bool:
    """Whether the contact was looked up for TEST_USER_ID, never anyone else."""
    lookups = [
        *contact_repo.find_by_id.await_args_list,
        *contact_repo.contact_exists.await_args_list,
    ]
    return bool(lookups) and all(
        call.kwargs.get("user_id") == TEST_USER_ID for call in lookups
    )


@pytest.mark.parametrize("name", [*OPERATIONS])
async def test_foreign_contact_is_not_found(
    name: str, service: ContactService, contact_repo: AsyncMock
) -> None:
    operation = OPERATIONS[name]

    if name in ANSWERS_NONE:
        assert await operation(service, AsyncMock()) is None
    else:
        with pytest.raises(ContactNotFoundError):
            await operation(service, AsyncMock())

    assert _asked_as_acting_user(contact_repo)


@pytest.mark.parametrize("name", [*OPERATIONS])
async def test_foreign_contact_is_left_unchanged(
    name: str,
    service: ContactService,
    contact_repo: AsyncMock,
    event_publisher: AsyncMock,
    history_repo: AsyncMock,
) -> None:
    operation = OPERATIONS[name]

    try:
        await operation(service, AsyncMock())
    except ContactNotFoundError:
        pass

    written = [w for w in WRITES if getattr(contact_repo, w).await_count]
    assert written == []
    event_publisher.publish.assert_not_awaited()
    assert history_repo.method_calls == []


async def test_history_of_a_foreign_contact_reads_no_rows(
    service: ContactService, history_repo: AsyncMock
) -> None:
    with pytest.raises(ContactNotFoundError):
        await service.get_contact_history(FOREIGN_ID, user_id=OTHER_USER_ID)

    assert history_repo.method_calls == []
