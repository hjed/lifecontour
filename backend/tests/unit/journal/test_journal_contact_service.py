"""JournalContactService refuses a contact the journal's owner does not hold.

The ownership check runs first, so a refused link writes no row and publishes
no summary-refresh event.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.models.journals import (
    JournalContactRelationship,
    JournalContactRelationshipType,
)

from app.core.contacts.models.exceptions import ContactNotFoundError
from app.core.journal.services.journal_contact_service import JournalContactService

OWNER = "owner-1"
CONTACT_ID = 7


def _relationship() -> JournalContactRelationship:
    return JournalContactRelationship(
        journal_id=3,
        contact_id=CONTACT_ID,
        relationship_type=JournalContactRelationshipType.PARTICIPANT,
    )


def _service(
    *, owned: bool
) -> tuple[JournalContactService, AsyncMock, AsyncMock, AsyncMock]:
    contact_repo = AsyncMock()
    contact_repo.contact_exists.return_value = owned
    relationship_repo = AsyncMock()
    relationship_repo.create.return_value = _relationship()
    publisher = AsyncMock()
    service = JournalContactService(
        contact_relationship_repo=relationship_repo,
        event_publisher=publisher,
        contact_repo=contact_repo,
    )
    return service, contact_repo, relationship_repo, publisher


@pytest.mark.unit
class TestAddContactToJournal:
    async def test_a_contact_the_owner_does_not_hold_is_not_found(self) -> None:
        service, contact_repo, relationship_repo, publisher = _service(owned=False)

        with pytest.raises(ContactNotFoundError):
            await service.add_contact_to_journal(
                _relationship(), user_id=OWNER, transaction=MagicMock()
            )

        contact_repo.contact_exists.assert_awaited_once_with(CONTACT_ID, user_id=OWNER)
        relationship_repo.create.assert_not_awaited()
        publisher.publish.assert_not_awaited()

    async def test_the_owners_contact_is_linked_and_announced(self) -> None:
        service, _, relationship_repo, publisher = _service(owned=True)

        await service.add_contact_to_journal(
            _relationship(), user_id=OWNER, transaction=MagicMock()
        )

        relationship_repo.create.assert_awaited_once()
        publisher.publish.assert_awaited_once()
