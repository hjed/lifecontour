"""
Repairs search documents that an owner-filtered search cannot see.

Every search filters on the owner, so a record with no document, or a document
with no ``user_id``, is invisible. That happens when an index loses its data,
as a MeiliSearch upgrade can, leaving only the documents written by later
events.

The backfill only ever upserts what is missing, so it is safe beside the live
search consumer, and running it again changes nothing.
"""

import asyncio
from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.search.indexed_entities import (
    CONTACTS,
    JOURNALS,
    IndexedEntity,
    build_documents,
    iter_id_pages,
)
from app.infrastructure.search.meilisearch_client import (
    add_documents_reporting_rejected,
    get_index_name,
    get_meilisearch_client,
)

logger = structlog.get_logger()

# Documents read per request when listing what the index already holds.
OWNER_PAGE_SIZE = 1000


@dataclass(frozen=True)
class SearchBackfillResult:
    """What one backfill run found and did."""

    examined: int
    documents_written: int
    failed_ids: list[int]


class SearchBackfillService:
    """Upserts documents for records the search index cannot return.

    The MeiliSearch client is synchronous, so every call runs in a thread to
    keep the API responsive while this runs in the background.
    """

    def __init__(self, db_connection: AsyncConnection) -> None:
        """Initialize the backfill.

        Args:
            db_connection: Connection used to read records. Nothing is written.
        """
        self.client = get_meilisearch_client()
        self.db_connection = db_connection

    async def backfill_contacts(self) -> SearchBackfillResult:
        """Restore contacts missing from the index or lacking an owner."""
        return await self._backfill(CONTACTS)

    async def backfill_journals(self) -> SearchBackfillResult:
        """Restore journals missing from the index or lacking an owner."""
        return await self._backfill(JOURNALS)

    async def _backfill(self, entity: IndexedEntity) -> SearchBackfillResult:
        """Compare one table with its index and upsert the difference."""
        index_name = get_index_name(entity.entity_type)
        await asyncio.to_thread(entity.ensure_index, self.client)
        owned = await asyncio.to_thread(self._owned_document_ids, index_name)

        examined = 0
        written = 0
        failed: list[int] = []

        async for ids in iter_id_pages(self.db_connection, entity):
            examined += len(ids)
            missing = [entity_id for entity_id in ids if entity_id not in owned]
            if not missing:
                continue
            documents, unbuilt = await build_documents(
                self.db_connection, entity, missing
            )
            failed.extend(unbuilt)
            if not documents:
                continue
            rejected = await asyncio.to_thread(
                add_documents_reporting_rejected, self.client, index_name, documents
            )
            failed.extend(rejected)
            written += len(documents) - len(rejected)

        logger.info(
            "Search backfill finished",
            entity_type=entity.entity_type,
            examined=examined,
            documents_written=written,
            failed_ids=failed,
        )
        return SearchBackfillResult(
            examined=examined, documents_written=written, failed_ids=failed
        )

    def _owned_document_ids(self, index_name: str) -> set[int]:
        """Return the ids of every document in the index that has an owner."""
        index = self.client.index(index_name)
        owned: set[int] = set()
        offset = 0
        while True:
            page = index.get_documents(
                {
                    "fields": ["id", "user_id"],
                    "limit": OWNER_PAGE_SIZE,
                    "offset": offset,
                }
            )
            # An absent field raises on attribute access, so read it as a dict.
            # An empty owner, as the journal event fallback writes when its
            # event names none, matches no owner filter either.
            for document in page.results:
                fields = dict(document)
                if fields.get("user_id") not in (None, ""):
                    owned.add(fields["id"])
            offset += len(page.results)
            if not page.results or offset >= page.total:
                return owned
