"""
Bulk re-indexing service for MeiliSearch.

Provides functionality to rebuild MeiliSearch indices from PostgreSQL data.
Used during MeiliSearch upgrades or when the search index needs
to be rebuilt from scratch.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import structlog
from meilisearch.errors import MeilisearchError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.search.indexed_entities import (
    CONTACTS,
    JOURNALS,
    IndexedEntity,
    ReindexIncompleteError,
    build_documents,
    iter_id_pages,
)
from app.infrastructure.search.meilisearch_client import (
    add_documents_reporting_rejected,
    get_index_name,
    get_meilisearch_client,
    wait_for_task_success,
)

logger = structlog.get_logger()


@dataclass
class SingleReindexResult:
    """Result of a single-entity re-index operation."""

    count: int
    duration_ms: int


@dataclass
class ReindexResult:
    """Result of a bulk re-index operation."""

    contacts_indexed: int
    journals_indexed: int
    duration_ms: int


class ReindexService:
    """Bulk re-indexing from PostgreSQL to MeiliSearch.

    Reads all data from the database and pushes it to MeiliSearch,
    replacing any existing document contents. Useful for:
    - MeiliSearch version upgrades (wipe volume + re-index)
    - Recovery from corrupted indices
    - Initial index population

    MeiliSearch client calls are synchronous and are run in a threadpool
    to avoid blocking the async event loop.
    """

    def __init__(self, db_connection: AsyncConnection) -> None:
        """Initialize the re-index service.

        Args:
            db_connection: Active database connection for reading data.
        """
        self.client = get_meilisearch_client()
        self.db_connection = db_connection

    async def reindex_all(self) -> ReindexResult:
        """Re-index all entity types from PostgreSQL into MeiliSearch.

        Ensures indices exist with correct settings, clears existing
        documents, and bulk-inserts all records from PostgreSQL.

        Returns:
            ReindexResult with counts and duration.
        """
        start = time.monotonic()
        failed_ids: dict[str, list[int]] = {}

        contacts_indexed = await self._count_collecting_failures(
            self.reindex_contacts, failed_ids
        )
        journals_indexed = await self._count_collecting_failures(
            self.reindex_journals, failed_ids
        )

        if failed_ids:
            raise ReindexIncompleteError(failed_ids)

        duration_ms = int((time.monotonic() - start) * 1000)

        logger.info(
            "Full re-index completed",
            contacts_indexed=contacts_indexed,
            journals_indexed=journals_indexed,
            duration_ms=duration_ms,
        )

        return ReindexResult(
            contacts_indexed=contacts_indexed,
            journals_indexed=journals_indexed,
            duration_ms=duration_ms,
        )

    @staticmethod
    async def _count_collecting_failures(
        reindex: Callable[[], Awaitable[SingleReindexResult]],
        failed_ids: dict[str, list[int]],
    ) -> int:
        """Run one entity's re-index so that the next still runs if it is incomplete."""
        try:
            return (await reindex()).count
        except ReindexIncompleteError as incomplete:
            failed_ids.update(incomplete.failed_ids)
            return 0

    async def reindex_contacts(self) -> SingleReindexResult:
        """Rebuild the contacts index from PostgreSQL.

        Returns:
            SingleReindexResult with count and duration.

        Raises:
            ReindexIncompleteError: Some contacts could not be indexed. The
                rest were, so re-running is safe.
        """
        return await self._reindex(CONTACTS)

    async def reindex_journals(self) -> SingleReindexResult:
        """Rebuild the journals index from PostgreSQL.

        Returns:
            SingleReindexResult with count and duration.

        Raises:
            ReindexIncompleteError: Some journals could not be indexed. The
                rest were, so re-running is safe.
        """
        return await self._reindex(JOURNALS)

    async def _reindex(self, entity: IndexedEntity) -> SingleReindexResult:
        """Clear one index and refill it from its table."""
        start = time.monotonic()
        index_name = get_index_name(entity.entity_type)

        await self._ensure_index_exists(index_name, dict(entity.settings))
        await self._run_sync(lambda: self._delete_all_documents(index_name))

        total_indexed = 0
        failed: list[int] = []

        async for ids in iter_id_pages(self.db_connection, entity):
            documents, unbuilt = await build_documents(self.db_connection, entity, ids)
            failed.extend(unbuilt)
            if not documents:
                continue
            rejected = await self._run_sync(
                lambda docs=documents: add_documents_reporting_rejected(
                    self.client, index_name, docs
                )
            )
            failed.extend(rejected)
            total_indexed += len(documents) - len(rejected)

        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "Search index rebuilt",
            entity_type=entity.entity_type,
            count=total_indexed,
            failed=len(failed),
            duration_ms=duration_ms,
        )
        if failed:
            raise ReindexIncompleteError({entity.entity_type: failed})
        return SingleReindexResult(count=total_indexed, duration_ms=duration_ms)

    async def _ensure_index_exists(
        self, index_name: str, settings: dict[str, Any]
    ) -> None:
        """Ensure a MeiliSearch index exists with the correct settings.

        Creates the index if missing, and always applies the latest
        settings so that upgrades or config changes take effect.

        Args:
            index_name: Name of the index.
            settings: Index settings to apply.
        """

        def _sync_ensure() -> None:
            try:
                index = self.client.index(index_name)
                index.get_stats()
            except MeilisearchError:
                logger.info("Creating search index", index_name=index_name)
                task = self.client.create_index(index_name, {"primaryKey": "id"})
                wait_for_task_success(self.client, task.task_uid)

            # Always apply latest settings (handles upgrades / config changes)
            index = self.client.index(index_name)
            task = index.update_settings(settings)
            wait_for_task_success(self.client, task.task_uid)

        await self._run_sync(_sync_ensure)

    def _delete_all_documents(self, index_name: str) -> None:
        """Delete all documents from a MeiliSearch index.

        Args:
            index_name: Name of the index.
        """
        index = self.client.index(index_name)
        task = index.delete_all_documents()
        wait_for_task_success(self.client, task.task_uid)

    @staticmethod
    async def _run_sync(func: Any) -> Any:
        """Run a synchronous function in a threadpool.

        Prevents blocking the async event loop during MeiliSearch client calls.
        """
        return await asyncio.to_thread(func)
