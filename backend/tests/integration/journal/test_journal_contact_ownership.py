"""A journal's people are its owner's contacts.

Linking a contact to a journal requires the contact to belong to the journal's
owner. Another user's contact is **not found**, exactly as a missing one is, and
nothing is written: no link row, and no summary-refresh event naming it.

Every write path goes through ``JournalContactService.add_contact_to_journal``,
so it is the one place the rule lands; the composite create and update skip a
foreign contact the way they already skip a missing one.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from core_shared.models.journals import (
    EventDateRange,
    Journal,
    JournalContactRelationship,
    JournalContactRelationshipType,
)
from dishka import AsyncContainer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.exceptions import ContactNotFoundError
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_contact_service import JournalContactService
from app.core.journal.services.journal_write_service import JournalWriteService
from tests.integration.contact_seeding import OTHER_USER_ID, TEST_USER_ID
from tests.integration.tasks.task_seeding import (
    create_contact,
    create_journal,
    make_task_container,
)


@pytest.fixture
async def container(async_connection: AsyncConnection) -> AsyncIterator[AsyncContainer]:
    container = make_task_container(async_connection)
    async with container() as request_container:
        yield request_container
    await container.close()


async def _linked_contact_ids(connection: AsyncConnection, journal_id: int) -> set[int]:
    rows = await connection.execute(
        text(
            "SELECT contact_id FROM journal_contact_relationships "
            "WHERE journal_id = :journal_id"
        ),
        {"journal_id": journal_id},
    )
    return {row.contact_id for row in rows.fetchall()}


async def _refresh_events_for(connection: AsyncConnection, contact_id: int) -> int:
    rows = await connection.execute(
        text(
            "SELECT COUNT(*) FROM outbox_events "
            "WHERE event_type = 'ContactSummaryRefreshRequested' "
            "AND aggregate_id = :contact_id"
        ),
        {"contact_id": contact_id},
    )
    return int(rows.scalar_one())


def _participant(contact_id: int) -> dict[str, dict[str, str]]:
    """One contact entry as the composite create/update receives it."""
    return {
        "attributes": {
            "contact_id": str(contact_id),
            "relationship_type": JournalContactRelationshipType.PARTICIPANT.name,
        }
    }


@pytest.mark.integration
class TestLinkingAContact:
    async def test_their_contact_is_not_found_and_nothing_is_written(
        self, container: AsyncContainer, async_connection: AsyncConnection
    ) -> None:
        service = await container.get(JournalContactService)
        journal_id = await create_journal(SqlJournalRepository(async_connection))
        theirs = await create_contact(async_connection, user_id=OTHER_USER_ID)

        with pytest.raises(ContactNotFoundError) as exc_info:
            await service.add_contact_to_journal(
                JournalContactRelationship(
                    journal_id=journal_id,
                    contact_id=theirs,
                    relationship_type=JournalContactRelationshipType.PARTICIPANT,
                ),
                user_id=TEST_USER_ID,
                transaction=async_connection,
            )

        assert exc_info.value.contact_id == theirs
        assert await _linked_contact_ids(async_connection, journal_id) == set()
        assert await _refresh_events_for(async_connection, theirs) == 0

    async def test_your_contact_is_linked(
        self, container: AsyncContainer, async_connection: AsyncConnection
    ) -> None:
        service = await container.get(JournalContactService)
        journal_id = await create_journal(SqlJournalRepository(async_connection))
        yours = await create_contact(async_connection)

        await service.add_contact_to_journal(
            JournalContactRelationship(
                journal_id=journal_id,
                contact_id=yours,
                relationship_type=JournalContactRelationshipType.PARTICIPANT,
            ),
            user_id=TEST_USER_ID,
            transaction=async_connection,
        )

        assert await _linked_contact_ids(async_connection, journal_id) == {yours}


@pytest.mark.integration
class TestCompositeWritesSkipTheirContacts:
    """The composite writes skip a foreign contact as they skip a missing one."""

    async def test_create_links_only_your_contacts(
        self, container: AsyncContainer, async_connection: AsyncConnection
    ) -> None:
        service = await container.get(JournalWriteService)
        yours = await create_contact(async_connection, first_name="Mine")
        theirs = await create_contact(async_connection, user_id=OTHER_USER_ID)
        start = datetime(2024, 3, 1, 9, tzinfo=UTC)

        created = await service.create_journal(
            Journal(
                user_id=TEST_USER_ID,
                title="Climb",
                content="",
                event_date_range=EventDateRange(start=start, end=start),
            ),
            None,
            None,
            [_participant(yours), _participant(theirs)],
            async_connection,
        )

        assert created.id is not None
        assert await _linked_contact_ids(async_connection, created.id) == {yours}

    async def test_update_links_only_your_contacts(
        self, container: AsyncContainer, async_connection: AsyncConnection
    ) -> None:
        service = await container.get(JournalWriteService)
        journal_repo = SqlJournalRepository(async_connection)
        journal_id = await create_journal(journal_repo)
        journal = await journal_repo.find_by_id_for_user(journal_id, TEST_USER_ID)
        assert journal is not None
        yours = await create_contact(async_connection, first_name="Mine")
        theirs = await create_contact(async_connection, user_id=OTHER_USER_ID)

        await service.update_journal_composite(
            journal,
            async_connection,
            relationships=[_participant(yours), _participant(theirs)],
        )

        assert await _linked_contact_ids(async_connection, journal_id) == {yours}
