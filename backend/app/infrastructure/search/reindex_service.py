"""
Bulk re-indexing service for MeiliSearch.

Provides functionality to rebuild MeiliSearch indices from PostgreSQL data.
Used during MeiliSearch upgrades or when the search index needs
to be rebuilt from scratch.
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import structlog
from meilisearch.errors import MeilisearchError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.infrastructure.search.meilisearch_client import (
    CONTACTS_INDEX_SETTINGS,
    JOURNAL_INDEX_SETTINGS,
    get_index_name,
    get_meilisearch_client,
)

logger = structlog.get_logger()

# Number of IDs to fetch from DB per page for document building
DB_BATCH_SIZE = 100

# Maximum number of documents to push in a single MeiliSearch batch
MEILI_BATCH_SIZE = 100


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

        contacts_result = await self.reindex_contacts()
        journals_result = await self.reindex_journals()

        duration_ms = int((time.monotonic() - start) * 1000)

        logger.info(
            "Full re-index completed",
            contacts_indexed=contacts_result.count,
            journals_indexed=journals_result.count,
            duration_ms=duration_ms,
        )

        return ReindexResult(
            contacts_indexed=contacts_result.count,
            journals_indexed=journals_result.count,
            duration_ms=duration_ms,
        )

    async def reindex_contacts(self) -> SingleReindexResult:
        """Re-index all contacts from PostgreSQL.

        Ensures the contacts index exists with correct settings, clears
        existing documents, then fetches and indexes contacts using
        keyset pagination to avoid loading all IDs into memory at once.

        Returns:
            SingleReindexResult with count and duration.
        """
        start = time.monotonic()
        index_name = get_index_name("contacts")

        await self._ensure_index_exists(index_name, CONTACTS_INDEX_SETTINGS)

        # Clear existing documents
        await self._run_sync(lambda: self._delete_all_documents(index_name))

        # Fetch and index using keyset pagination
        total_indexed = 0
        last_id = 0

        while True:
            result = await self.db_connection.execute(
                text(
                    "SELECT id FROM contacts WHERE id > :last_id "
                    "ORDER BY id LIMIT :batch_size"
                ),
                {"last_id": last_id, "batch_size": DB_BATCH_SIZE},
            )
            batch_ids = [row.id for row in result.fetchall()]

            if not batch_ids:
                break

            last_id = batch_ids[-1]
            documents: list[dict[str, Any]] = []

            for contact_id in batch_ids:
                doc = await self._fetch_contact_document(contact_id)
                if doc:
                    documents.append(doc)

            if documents:
                await self._run_sync(
                    lambda docs=documents: self._batch_add_documents(index_name, docs)
                )
                total_indexed += len(documents)

        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info("Contacts re-indexed", count=total_indexed, duration_ms=duration_ms)
        return SingleReindexResult(count=total_indexed, duration_ms=duration_ms)

    async def reindex_journals(self) -> SingleReindexResult:
        """Re-index all journals from PostgreSQL.

        Ensures the journals index exists with correct settings, clears
        existing documents, then fetches and indexes journals using
        keyset pagination to avoid loading all IDs into memory at once.

        Returns:
            SingleReindexResult with count and duration.
        """
        start = time.monotonic()
        index_name = get_index_name("journals")

        await self._ensure_index_exists(index_name, JOURNAL_INDEX_SETTINGS)

        # Clear existing documents
        await self._run_sync(lambda: self._delete_all_documents(index_name))

        # Fetch and index using keyset pagination
        total_indexed = 0
        last_id = 0

        while True:
            result = await self.db_connection.execute(
                text(
                    "SELECT id FROM journals WHERE id > :last_id "
                    "ORDER BY id LIMIT :batch_size"
                ),
                {"last_id": last_id, "batch_size": DB_BATCH_SIZE},
            )
            batch_ids = [row.id for row in result.fetchall()]

            if not batch_ids:
                break

            last_id = batch_ids[-1]
            documents: list[dict[str, Any]] = []

            for journal_id in batch_ids:
                doc = await self._fetch_journal_document(journal_id)
                if doc:
                    documents.append(doc)

            if documents:
                await self._run_sync(
                    lambda docs=documents: self._batch_add_documents(index_name, docs)
                )
                total_indexed += len(documents)

        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info("Journals re-indexed", count=total_indexed, duration_ms=duration_ms)
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
                self.client.wait_for_task(task.task_uid)

            # Always apply latest settings (handles upgrades / config changes)
            index = self.client.index(index_name)
            task = index.update_settings(settings)
            self.client.wait_for_task(task.task_uid)

        await self._run_sync(_sync_ensure)

    def _delete_all_documents(self, index_name: str) -> None:
        """Delete all documents from a MeiliSearch index.

        Args:
            index_name: Name of the index.
        """
        index = self.client.index(index_name)
        task = index.delete_all_documents()
        self.client.wait_for_task(task.task_uid)

    def _batch_add_documents(
        self, index_name: str, documents: list[dict[str, Any]]
    ) -> None:
        """Add documents to a MeiliSearch index in batches.

        Args:
            index_name: Name of the index.
            documents: Documents to add.
        """
        index = self.client.index(index_name)
        for i in range(0, len(documents), MEILI_BATCH_SIZE):
            batch = documents[i : i + MEILI_BATCH_SIZE]
            task = index.add_documents(batch)
            self.client.wait_for_task(task.task_uid)
            logger.debug(
                "Batch indexed",
                index_name=index_name,
                batch_start=i,
                batch_size=len(batch),
            )

    @staticmethod
    async def _run_sync(func: Any) -> Any:
        """Run a synchronous function in a threadpool.

        Prevents blocking the async event loop during MeiliSearch client calls.
        """
        return await asyncio.to_thread(func)

    async def _fetch_contact_document(self, contact_id: int) -> dict[str, Any] | None:
        """Fetch a single contact's search document from the database.

        Uses the same query pattern as SearchIndexer._fetch_complete_contact_data.

        Args:
            contact_id: ID of the contact.

        Returns:
            Document dict for MeiliSearch, or None if not found.
        """
        try:
            contact_result = await self.db_connection.execute(
                text("""
                    SELECT id, first_name, last_name, middle_name, nick_name,
                           company, job_title, is_favourite, created_at, updated_at
                    FROM contacts
                    WHERE id = :contact_id
                """),
                {"contact_id": contact_id},
            )
            contact_row = contact_result.fetchone()
            if not contact_row:
                return None

            methods_result = await self.db_connection.execute(
                text("""
                    SELECT method_type, value, label, is_primary
                    FROM contact_methods
                    WHERE contact_id = :contact_id
                    ORDER BY is_primary DESC, created_at ASC
                """),
                {"contact_id": contact_id},
            )
            methods_rows = methods_result.fetchall()

            notes_result = await self.db_connection.execute(
                text("""
                    SELECT content
                    FROM contact_notes
                    WHERE contact_id = :contact_id
                    ORDER BY created_at DESC
                """),
                {"contact_id": contact_id},
            )
            notes_rows = notes_result.fetchall()

            tags_result = await self.db_connection.execute(
                text("""
                    SELECT t.name
                    FROM tags t
                    JOIN contact_tags ct ON t.id = ct.tag_id
                    WHERE ct.contact_id = :contact_id
                    ORDER BY t.name
                """),
                {"contact_id": contact_id},
            )
            tags_rows = tags_result.fetchall()

            emails = [row.value for row in methods_rows if row.method_type == "email"]
            phones = [row.value for row in methods_rows if row.method_type == "phone"]
            primary_email = next(
                (
                    row.value
                    for row in methods_rows
                    if row.method_type == "email" and row.is_primary
                ),
                emails[0] if emails else None,
            )
            primary_phone = next(
                (
                    row.value
                    for row in methods_rows
                    if row.method_type == "phone" and row.is_primary
                ),
                phones[0] if phones else None,
            )

            full_name = (
                f"{contact_row.first_name} {contact_row.last_name or ''}".strip()
            )

            return {
                "id": contact_row.id,
                "first_name": contact_row.first_name,
                "last_name": contact_row.last_name or "",
                "middle_name": contact_row.middle_name or "",
                "nick_name": contact_row.nick_name or "",
                "company": contact_row.company,
                "job_title": contact_row.job_title,
                "full_name": full_name,
                "email": primary_email,
                "emails": emails,
                "phone": primary_phone,
                "phones": phones,
                "notes_content": " ".join(row.content for row in notes_rows),
                "tags": [row.name for row in tags_rows],
                "entity_type": "contact",
                "is_favourite": contact_row.is_favourite,
                "created_at": contact_row.created_at.isoformat()
                if contact_row.created_at
                else None,
                "updated_at": contact_row.updated_at.isoformat()
                if contact_row.updated_at
                else None,
            }

        except Exception as e:  # noqa: BLE001
            logger.error(
                "Failed to fetch contact for re-indexing",
                contact_id=contact_id,
                error=str(e),
            )
            return None

    async def _fetch_journal_document(self, journal_id: int) -> dict[str, Any] | None:
        """Fetch a single journal's search document from the database.

        Uses the same query pattern as
        JournalIndexingService._fetch_complete_journal_data.

        Args:
            journal_id: ID of the journal.

        Returns:
            Document dict for MeiliSearch, or None if not found.
        """
        try:
            journal_result = await self.db_connection.execute(
                text("""
                    SELECT id, user_id, title, content,
                           event_date_range_start, event_date_range_end,
                           parent_id, created_at, updated_at
                    FROM journals
                    WHERE id = :journal_id
                """),
                {"journal_id": journal_id},
            )
            journal_row = journal_result.fetchone()
            if not journal_row:
                return None

            types = await SqlJournalRepository(self.db_connection).get_types(journal_id)

            contacts_result = await self.db_connection.execute(
                text("""
                    SELECT DISTINCT contact_id
                    FROM journal_contact_relationships
                    WHERE journal_id = :journal_id
                """),
                {"journal_id": journal_id},
            )
            contact_ids = [row.contact_id for row in contacts_result.fetchall()]

            tags_result = await self.db_connection.execute(
                text("""
                    SELECT DISTINCT tag_id
                    FROM journal_tag_assignments
                    WHERE journal_id = :journal_id
                """),
                {"journal_id": journal_id},
            )
            tag_ids = [str(row.tag_id) for row in tags_result.fetchall()]

            calendar_id = None
            location = None
            if "EVENT" in types:
                cal_result = await self.db_connection.execute(
                    text("""
                        SELECT calendar_id, location
                        FROM journal_calendar_info
                        WHERE journal_id = :journal_id
                    """),
                    {"journal_id": journal_id},
                )
                cal_row = cal_result.fetchone()
                if cal_row:
                    calendar_id = (
                        str(cal_row.calendar_id) if cal_row.calendar_id else None
                    )
                    location = cal_row.location

            return {
                "id": journal_row.id,
                "user_id": journal_row.user_id,
                "title": journal_row.title,
                "content": journal_row.content,
                "event_date_range_start": (
                    journal_row.event_date_range_start.isoformat()
                    if journal_row.event_date_range_start
                    else None
                ),
                "event_date_range_end": (
                    journal_row.event_date_range_end.isoformat()
                    if journal_row.event_date_range_end
                    else None
                ),
                "types": types,
                "contact_ids": contact_ids,
                "tag_ids": tag_ids,
                "calendar_id": calendar_id,
                "parent_id": journal_row.parent_id,
                "location": location,
                "entity_type": "journal",
                "created_at": journal_row.created_at.isoformat()
                if journal_row.created_at
                else None,
                "updated_at": journal_row.updated_at.isoformat()
                if journal_row.updated_at
                else None,
            }

        except Exception as e:  # noqa: BLE001
            logger.error(
                "Failed to fetch journal for re-indexing",
                journal_id=journal_id,
                error=str(e),
            )
            return None
