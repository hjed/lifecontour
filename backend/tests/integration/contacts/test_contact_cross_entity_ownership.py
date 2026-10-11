"""Links between contacts, and a contact's history, stay within one owner.

A relationship joins two of the user's contacts, a merge absorbs one of the
user's contacts into another, and a contact's history is read for the reader.
In each, another user's contact is **not found**, exactly as a missing one is,
and nothing is written: the rows on both sides are byte-identical afterwards.

Each test seeds the foreign contact with ``OTHER_USER_ID`` — a real row
belonging to someone else, never a merely absent id.
"""

from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest
from core_shared.models.contacts.entities import ContactRelationship, RelationshipType
from core_shared.models.contacts.exceptions import ContactValidationError
from dishka import AsyncContainer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_relationship_repository import (
    SqlContactRelationshipRepository,
)
from app.core.contacts.models.exceptions import ContactNotFoundError
from app.core.contacts.services.contact_history_service import ContactHistoryService
from app.core.contacts.services.contact_merge_service import ContactMergeService
from app.core.contacts.services.contact_relationship_service import (
    ContactRelationshipService,
)
from tests.integration.contact_seeding import OTHER_USER_ID, TEST_USER_ID, seed_contact
from tests.integration.tasks.task_seeding import make_task_container

# Everything a refused write must leave as it was, for the contacts involved.
_SNAPSHOTS = (
    text("SELECT to_jsonb(t) FROM contacts t WHERE id = ANY(:ids)"),
    text("SELECT to_jsonb(t) FROM contact_methods t WHERE contact_id = ANY(:ids)"),
    text(
        "SELECT to_jsonb(t) FROM contact_relationships t "
        "WHERE from_contact_id = ANY(:ids) OR to_contact_id = ANY(:ids)"
    ),
)


@pytest.fixture
async def container(async_connection: AsyncConnection) -> AsyncIterator[AsyncContainer]:
    container = make_task_container(async_connection)
    async with container() as request_container:
        yield request_container
    await container.close()


async def _snapshot(connection: AsyncConnection, ids: Sequence[int]) -> list[Any]:
    state: list[Any] = []
    for query in _SNAPSHOTS:
        rows = await connection.execute(query, {"ids": list(ids)})
        state.append(sorted(str(row[0]) for row in rows.fetchall()))
    return state


async def _their_contact(connection: AsyncConnection) -> int:
    """Another user's contact, with an email so a merge would have work to do."""
    contact_id = await seed_contact(
        connection, user_id=OTHER_USER_ID, first_name="Theirs"
    )
    await connection.execute(
        text(
            "INSERT INTO contact_methods (contact_id, method_type, value) "
            "VALUES (:contact_id, 'email', 'theirs@example.com')"
        ),
        {"contact_id": contact_id},
    )
    return contact_id


@pytest.mark.integration
class TestRelationshipsStayWithinOneOwner:
    async def test_relating_your_contact_to_theirs_is_not_found(
        self, container: AsyncContainer, async_connection: AsyncConnection
    ) -> None:
        service = await container.get(ContactRelationshipService)
        yours = await seed_contact(async_connection)
        theirs = await _their_contact(async_connection)
        before = await _snapshot(async_connection, [yours, theirs])

        with pytest.raises(ContactNotFoundError) as exc_info:
            await service.create_relationship(
                yours,
                theirs,
                RelationshipType.FRIEND,
                create_bidirectional=True,
                transaction=async_connection,
                user_id=TEST_USER_ID,
            )

        assert exc_info.value.contact_id == theirs
        assert await _snapshot(async_connection, [yours, theirs]) == before

    async def test_relating_their_contact_to_yours_is_not_found(
        self, container: AsyncContainer, async_connection: AsyncConnection
    ) -> None:
        service = await container.get(ContactRelationshipService)
        yours = await seed_contact(async_connection)
        theirs = await _their_contact(async_connection)
        before = await _snapshot(async_connection, [yours, theirs])

        with pytest.raises(ContactNotFoundError) as exc_info:
            await service.create_relationship(
                theirs,
                yours,
                RelationshipType.FRIEND,
                transaction=async_connection,
                user_id=TEST_USER_ID,
            )

        assert exc_info.value.contact_id == theirs
        assert await _snapshot(async_connection, [yours, theirs]) == before

    async def test_their_relationship_cannot_be_changed_or_deleted(
        self, container: AsyncContainer, async_connection: AsyncConnection
    ) -> None:
        """A relationship is the user's when its from-contact is.

        Relationship-not-found has always been a ``ContactValidationError``; a
        foreign one answers exactly that.
        """
        service = await container.get(ContactRelationshipService)
        theirs = await _their_contact(async_connection)
        their_friend = await seed_contact(async_connection, user_id=OTHER_USER_ID)
        relationship = await SqlContactRelationshipRepository(async_connection).create(
            ContactRelationship(
                from_contact_id=theirs,
                to_contact_id=their_friend,
                relationship_type=RelationshipType.FRIEND,
            )
        )
        assert relationship.id is not None
        before = await _snapshot(async_connection, [theirs, their_friend])

        assert (
            await service.get_relationship_by_id(relationship.id, user_id=TEST_USER_ID)
            is None
        )
        with pytest.raises(ContactValidationError, match="not found"):
            await service.update_relationship(
                relationship.id,
                RelationshipType.COLLEAGUE,
                transaction=async_connection,
                user_id=TEST_USER_ID,
            )
        with pytest.raises(ContactValidationError, match="not found"):
            await service.delete_relationship(
                relationship.id, transaction=async_connection, user_id=TEST_USER_ID
            )

        assert await _snapshot(async_connection, [theirs, their_friend]) == before


@pytest.mark.integration
class TestMergeStaysWithinOneOwner:
    @pytest.mark.parametrize("theirs_is", ["survivor", "source"])
    async def test_merging_with_their_contact_is_not_found(
        self,
        container: AsyncContainer,
        async_connection: AsyncConnection,
        theirs_is: str,
    ) -> None:
        service = await container.get(ContactMergeService)
        yours = await seed_contact(async_connection)
        theirs = await _their_contact(async_connection)
        survivor, source = (
            (theirs, yours) if theirs_is == "survivor" else (yours, theirs)
        )
        before = await _snapshot(async_connection, [yours, theirs])

        with pytest.raises(ContactNotFoundError) as exc_info:
            await service.merge_contacts(
                survivor, source, transaction=async_connection, user_id=TEST_USER_ID
            )

        assert exc_info.value.contact_id == theirs
        assert await _snapshot(async_connection, [yours, theirs]) == before


@pytest.mark.integration
class TestHistoryIsReadForTheReader:
    async def test_their_contacts_history_is_not_found(
        self, container: AsyncContainer, async_connection: AsyncConnection
    ) -> None:
        service = await container.get(ContactHistoryService)
        theirs = await _their_contact(async_connection)

        with pytest.raises(ContactNotFoundError):
            await service.get_contact_history(theirs, reader_user_id=TEST_USER_ID)
        with pytest.raises(ContactNotFoundError):
            await service.get_contact_history_count(theirs, reader_user_id=TEST_USER_ID)

    async def test_your_contacts_history_is_read(
        self, container: AsyncContainer, async_connection: AsyncConnection
    ) -> None:
        service = await container.get(ContactHistoryService)
        yours = await seed_contact(async_connection)

        assert (
            await service.get_contact_history(yours, reader_user_id=TEST_USER_ID) == []
        )
        assert (
            await service.get_contact_history_count(yours, reader_user_id=TEST_USER_ID)
            == 0
        )
