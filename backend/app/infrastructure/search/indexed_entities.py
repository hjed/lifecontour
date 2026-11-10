"""
What bulk search maintenance needs to know about each indexed entity.

The re-index and the backfill both walk a table and rebuild documents from it.
Both build through the event indexers, so a document looks the same however it
reached the index.
"""

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import structlog
from meilisearch import Client as MeiliSearchClient
from sqlalchemy import TextClause, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.search.journal_indexing_service import (
    JournalIndexingService,
    ensure_journal_search_index,
)
from app.infrastructure.search.meilisearch_client import (
    CONTACTS_INDEX_SETTINGS,
    JOURNAL_INDEX_SETTINGS,
)
from app.infrastructure.search.search_indexer import (
    SearchIndexer,
    ensure_contact_search_index,
)
from app.infrastructure.unit_of_work import savepoint

logger = structlog.get_logger()

# Number of IDs to fetch from the database per page.
DB_BATCH_SIZE = 100

SearchDocument = dict[str, Any]


class ReindexIncompleteError(Exception):
    """A bulk run finished, but some records did not reach the index."""

    def __init__(self, failed_ids: Mapping[str, list[int]]) -> None:
        self.failed_ids = dict(failed_ids)
        summary = "; ".join(
            f"{entity_type}: {ids}" for entity_type, ids in self.failed_ids.items()
        )
        super().__init__(f"Records could not be indexed ({summary})")


async def _build_contact(
    connection: AsyncConnection, contact_id: int
) -> SearchDocument | None:
    indexer = SearchIndexer(db_connection=connection)
    return await indexer.build_contact_document(contact_id)


async def _build_journal(
    connection: AsyncConnection, journal_id: int
) -> SearchDocument | None:
    indexer = JournalIndexingService(db_connection=connection)
    return await indexer.build_journal_document(journal_id)


@dataclass(frozen=True)
class IndexedEntity:
    """One kind of record kept in a search index."""

    entity_type: str
    ids_after: TextClause
    settings: Mapping[str, Any]
    ensure_index: Callable[[MeiliSearchClient], bool]
    build_document: Callable[[AsyncConnection, int], Awaitable[SearchDocument | None]]


CONTACTS = IndexedEntity(
    entity_type="contacts",
    ids_after=text(
        "SELECT id FROM contacts WHERE id > :last_id ORDER BY id LIMIT :batch_size"
    ),
    settings=CONTACTS_INDEX_SETTINGS,
    ensure_index=ensure_contact_search_index,
    build_document=_build_contact,
)

JOURNALS = IndexedEntity(
    entity_type="journals",
    ids_after=text(
        "SELECT id FROM journals WHERE id > :last_id ORDER BY id LIMIT :batch_size"
    ),
    settings=JOURNAL_INDEX_SETTINGS,
    ensure_index=ensure_journal_search_index,
    build_document=_build_journal,
)


async def iter_id_pages(
    connection: AsyncConnection, entity: IndexedEntity
) -> AsyncIterator[list[int]]:
    """Yield pages of an entity's ids in ascending order, by keyset pagination."""
    last_id = 0
    while True:
        result = await connection.execute(
            entity.ids_after, {"last_id": last_id, "batch_size": DB_BATCH_SIZE}
        )
        ids = [row.id for row in result.fetchall()]
        if not ids:
            return
        last_id = ids[-1]
        yield ids


async def build_documents(
    connection: AsyncConnection, entity: IndexedEntity, ids: list[int]
) -> tuple[list[SearchDocument], list[int]]:
    """Build documents for ``ids``, returning them and the ids that failed.

    Each build runs in its own savepoint: a failed statement would otherwise
    abort the transaction and fail every record after it. A row that no longer
    exists was deleted during the run, and is neither a document nor a failure.
    """
    documents: list[SearchDocument] = []
    failed: list[int] = []
    for entity_id in ids:
        try:
            async with savepoint(connection):
                document = await entity.build_document(connection, entity_id)
        except Exception as error:  # noqa: BLE001 - one record must not stop the run
            logger.error(
                "Could not build search document",
                entity_type=entity.entity_type,
                entity_id=entity_id,
                error=str(error),
            )
            failed.append(entity_id)
            continue
        if document is not None:
            documents.append(document)
    return documents, failed
