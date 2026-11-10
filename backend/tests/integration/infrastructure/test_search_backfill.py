"""The backfill restores documents search cannot see, and touches nothing else.

Real PostgreSQL and real MeiliSearch: what matters is whether an owner-filtered
search finds the record afterwards.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import pytest
from meilisearch import Client as MeiliSearchClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.search.meilisearch_client import (
    get_index_name,
    get_meilisearch_client,
    wait_for_task_success,
)
from app.infrastructure.search.search_backfill_service import SearchBackfillService
from app.infrastructure.search.search_indexer import SearchIndexer
from app.infrastructure.search.search_service import owner_filter
from tests.integration.contact_seeding import TEST_USER_ID, seed_contact

pytestmark = pytest.mark.integration


def _put(index_name: str, documents: list[dict[str, Any]]) -> None:
    """Write documents straight to the index, as an earlier release would have."""
    client = get_meilisearch_client()
    wait_for_task_success(
        client, client.index(index_name).add_documents(documents).task_uid
    )


def _owner_search(index_name: str, query: str) -> list[int]:
    """The ids an owner-filtered search returns: what the user can actually find."""
    response = (
        get_meilisearch_client()
        .index(index_name)
        .search(query, {"filter": [owner_filter(TEST_USER_ID)]})
    )
    return [hit["id"] for hit in response["hits"]]


async def _seed_journal(connection: AsyncConnection, title: str) -> int:
    now = datetime.now(UTC)
    result = await connection.execute(
        text("""
            INSERT INTO journals (user_id, title, content,
                                  event_date_range_start, event_date_range_end)
            VALUES (:user_id, :title, 'body', :now, :now)
            RETURNING id
        """),
        {"user_id": TEST_USER_ID, "title": title, "now": now},
    )
    return int(result.scalar_one())


@pytest.fixture
def contacts_index(index_contact: Callable[[int], Awaitable[None]]) -> str:
    """The contacts index, configured and empty."""
    return get_index_name("contacts")


@pytest.fixture
def journals_index(index_journal: Callable[[int], Awaitable[None]]) -> str:
    """The journals index, configured and empty."""
    return get_index_name("journals")


@pytest.mark.asyncio
async def test_a_contact_with_no_document_becomes_searchable(
    clean_database: AsyncConnection, contacts_index: str
) -> None:
    contact_id = await seed_contact(
        clean_database, first_name="Zebedee", last_name="Quill"
    )
    expected = await SearchIndexer(db_connection=clean_database).build_contact_document(
        contact_id
    )
    assert expected is not None

    result = await SearchBackfillService(clean_database).backfill_contacts()

    assert result.documents_written == 1
    assert result.failed_ids == []
    assert _owner_search(contacts_index, "Zebedee") == [contact_id]
    stored = get_meilisearch_client().index(contacts_index).get_document(contact_id)
    assert stored.activity_count_30d == expected["activity_count_30d"]
    assert stored.relationships == expected["relationships"]


# An empty owner is what the journal event fallback writes when its event names
# none; no owner filter matches it either.
@pytest.mark.parametrize("ownerless", [{}, {"user_id": None}, {"user_id": ""}])
@pytest.mark.asyncio
async def test_a_document_without_an_owner_is_repaired(
    clean_database: AsyncConnection,
    contacts_index: str,
    ownerless: dict[str, str | None],
) -> None:
    contact_id = await seed_contact(clean_database, first_name="Ottoline")
    _put(contacts_index, [{"id": contact_id, "first_name": "Ottoline", **ownerless}])
    assert _owner_search(contacts_index, "Ottoline") == []

    result = await SearchBackfillService(clean_database).backfill_contacts()

    assert result.documents_written == 1
    assert _owner_search(contacts_index, "Ottoline") == [contact_id]


@pytest.mark.asyncio
async def test_a_document_with_an_owner_is_left_alone(
    clean_database: AsyncConnection, contacts_index: str
) -> None:
    contact_id = await seed_contact(clean_database, first_name="Current")
    _put(
        contacts_index,
        [{"id": contact_id, "user_id": TEST_USER_ID, "first_name": "Marker"}],
    )

    result = await SearchBackfillService(clean_database).backfill_contacts()

    assert result.examined == 1
    assert result.documents_written == 0
    assert _owner_search(contacts_index, "Marker") == [contact_id]


@pytest.mark.asyncio
async def test_a_document_with_no_matching_contact_is_not_deleted(
    clean_database: AsyncConnection, contacts_index: str
) -> None:
    _put(
        contacts_index,
        [{"id": 987654321, "user_id": TEST_USER_ID, "first_name": "Orphan"}],
    )

    await SearchBackfillService(clean_database).backfill_contacts()

    assert _owner_search(contacts_index, "Orphan") == [987654321]


@pytest.mark.asyncio
async def test_a_second_run_writes_nothing(
    clean_database: AsyncConnection, contacts_index: str
) -> None:
    await seed_contact(clean_database, first_name="Once")
    backfill = SearchBackfillService(clean_database)
    await backfill.backfill_contacts()

    result = await backfill.backfill_contacts()

    assert result.examined == 1
    assert result.documents_written == 0


@pytest.mark.asyncio
async def test_an_index_that_has_gone_is_recreated_and_filled(
    clean_database: AsyncConnection, contacts_index: str
) -> None:
    contact_id = await seed_contact(clean_database, first_name="Phoenix")
    client: MeiliSearchClient = get_meilisearch_client()
    wait_for_task_success(client, client.delete_index(contacts_index).task_uid)

    result = await SearchBackfillService(clean_database).backfill_contacts()

    assert result.documents_written == 1
    assert _owner_search(contacts_index, "Phoenix") == [contact_id]


@pytest.mark.asyncio
async def test_a_contact_whose_sql_fails_does_not_stop_the_others(
    clean_database: AsyncConnection, contacts_index: str
) -> None:
    """A failed statement aborts the transaction unless each build is isolated."""
    bad_id = await seed_contact(clean_database, first_name="Broken")
    good_id = await seed_contact(clean_database, first_name="Survivor")
    original = SearchIndexer.build_contact_document

    async def fail_in_sql(
        self: SearchIndexer, contact_id: int
    ) -> dict[str, Any] | None:
        if contact_id == bad_id:
            assert self.db_connection is not None
            await self.db_connection.execute(text("SELECT 1 / 0"))
        return await original(self, contact_id)

    with patch.object(SearchIndexer, "build_contact_document", fail_in_sql):
        result = await SearchBackfillService(clean_database).backfill_contacts()

    assert result.failed_ids == [bad_id]
    assert result.documents_written == 1
    assert _owner_search(contacts_index, "Survivor") == [good_id]


@pytest.mark.asyncio
async def test_absent_and_ownerless_journals_are_restored(
    clean_database: AsyncConnection, journals_index: str
) -> None:
    absent_id = await _seed_journal(clean_database, "Kayaking absent")
    ownerless_id = await _seed_journal(clean_database, "Kayaking ownerless")
    _put(journals_index, [{"id": ownerless_id, "title": "Kayaking ownerless"}])

    result = await SearchBackfillService(clean_database).backfill_journals()

    assert result.documents_written == 2
    assert sorted(_owner_search(journals_index, "Kayaking")) == sorted(
        [absent_id, ownerless_id]
    )
