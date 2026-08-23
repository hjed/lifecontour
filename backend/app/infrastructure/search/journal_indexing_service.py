"""
Journal search indexing service.

Processes journal domain events from the outbox and updates MeiliSearch indices
to keep search data synchronized with the database.
"""

from typing import Any

import structlog
from meilisearch import Client as MeiliSearchClient
from meilisearch.errors import MeilisearchError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.infrastructure.events.outbox_repository import OutboxEvent
from app.infrastructure.search.meilisearch_client import (
    JOURNAL_INDEX_SETTINGS,
    JOURNAL_REQUIRED_FILTERABLE_ATTRIBUTES,
    get_index_name,
    get_meilisearch_client,
)

logger = structlog.get_logger()

# Journal tag events that change which tags a journal carries, and therefore make
# its indexed ``tag_ids`` stale.
#
# ``JournalTagRenamed`` is deliberately absent: the journal document indexes tag
# **ids** and never tag names, so a rename leaves every document byte-identical.
# If tag names are ever added to the document, the rename has to join this set.
_TAG_REINDEX_EVENT_TYPES = frozenset(
    {
        "JournalTagAssigned",
        "JournalTagRemoved",
        "JournalTagDeleted",
        "JournalTagMerged",
    }
)


class JournalIndexingService:
    """Handles MeiliSearch indexing for journals based on domain events."""

    def __init__(
        self,
        db_connection: AsyncConnection | None = None,
        client: MeiliSearchClient | None = None,
    ) -> None:
        """
        Initialize the journal indexing service.

        Args:
            db_connection: Optional database connection for fetching journal data
            client: Optional MeiliSearch client. If not provided, uses default client
        """
        self.client = client or get_meilisearch_client()
        self.db_connection = db_connection

    async def process_event(self, event: OutboxEvent) -> None:
        """
        Process a single outbox event and update search indices.

        Args:
            event: Outbox event to process
        """
        try:
            if event.event_type.startswith("Journal"):
                await self._process_journal_event(event)
            else:
                logger.debug(
                    "Skipping unsupported event type",
                    event_type=event.event_type,
                    event_id=event.event_id,
                )

        except Exception as e:
            logger.error(
                "Failed to process event for journal search indexing",
                event_id=event.event_id,
                event_type=event.event_type,
                error=str(e),
            )
            raise

    async def _process_journal_event(self, event: OutboxEvent) -> None:
        """
        Process journal-related events.

        Args:
            event: Journal event to process
        """
        journal_index_name = get_index_name("journals")

        try:
            # Ensure the journals index exists with proper settings
            self._ensure_journals_index_exists(journal_index_name)

            if event.event_type == "JournalCreated":
                await self._index_journal_created(journal_index_name, event)
            elif event.event_type == "JournalUpdated":
                await self._index_journal_updated(journal_index_name, event)
            elif event.event_type == "JournalDeleted":
                self._index_journal_deleted(journal_index_name, event)
            elif event.event_type in _TAG_REINDEX_EVENT_TYPES:
                await self._reindex_journal_for_tag_change(journal_index_name, event)
            else:
                logger.debug(
                    "Skipping unsupported journal event type",
                    event_type=event.event_type,
                    event_id=event.event_id,
                )

        except MeilisearchError as e:
            logger.error(
                "MeiliSearch error processing journal event",
                event_id=event.event_id,
                event_type=event.event_type,
                error=str(e),
            )
            raise

    def _ensure_journals_index_exists(self, index_name: str) -> bool:
        """
        Ensure the journals search index exists and is configured.

        Returns True when the index settings were (re)applied — i.e. the index
        was missing or predated a required filterable attribute — which means
        existing documents may need a reindex to carry the current schema.

        Args:
            index_name: Name of the journals index
        """
        needs_creation = False
        needs_settings = False
        needs_primary_key = False

        try:
            # Try to get the index
            index = self.client.index(index_name)

            # Fetch info grabs the primaryKey attribute
            index.fetch_info()
            if not getattr(index, "primary_key", None):
                needs_primary_key = True

            # Check if settings are configured (implicit creation leaves them empty)
            filterable = index.get_filterable_attributes()
            if not filterable or not set(
                JOURNAL_REQUIRED_FILTERABLE_ATTRIBUTES
            ).issubset(filterable):
                needs_settings = True

        except MeilisearchError:
            needs_creation = True
            needs_settings = True
            # creation sets primaryKey, so needs_primary_key stays False

        if needs_creation:
            # Index doesn't exist, create it
            logger.info("Creating journals search index", index_name=index_name)
            task = self.client.create_index(index_name, {"primaryKey": "id"})
            self.client.wait_for_task(task.task_uid)

        if needs_primary_key:
            logger.info("Setting primary key for existing index", index_name=index_name)
            index = self.client.index(index_name)
            task = index.update(primary_key="id")
            self.client.wait_for_task(task.task_uid)

        if needs_settings:
            # Configure the index settings
            logger.info(
                "Configuring journals search index settings", index_name=index_name
            )
            index = self.client.index(index_name)
            task = index.update_settings(JOURNAL_INDEX_SETTINGS)
            self.client.wait_for_task(task.task_uid)

            logger.info("Journals search index created", index_name=index_name)

        return needs_settings

    async def _fetch_complete_journal_data(
        self, journal_id: int
    ) -> dict[str, Any] | None:
        """
        Fetch complete journal data from the database for search indexing.

        Args:
            journal_id: ID of the journal to fetch

        Returns:
            Complete journal data dictionary or None if not found
        """
        if not self.db_connection:
            logger.warning("No database connection available for fetching journal data")
            return None

        try:
            # Fetch basic journal info
            journal_query = text("""
                SELECT id, user_id, title, content,
                       event_date_range_start, event_date_range_end,
                       parent_id, created_at, updated_at
                FROM journals
                WHERE id = :journal_id
            """)
            journal_result = await self.db_connection.execute(
                journal_query, {"journal_id": journal_id}
            )
            journal_row = journal_result.fetchone()

            if not journal_row:
                return None

            # The repository owns the (generated) type-detection query; NOTE is
            # indexed only for journals with no typed rows, matching the read
            # paths so a types=NOTE filter means the same thing everywhere.
            types = await SqlJournalRepository(self.db_connection).get_concrete_types(
                journal_id
            )

            # Fetch contact IDs
            contacts_query = text("""
                SELECT DISTINCT contact_id
                FROM journal_contact_relationships
                WHERE journal_id = :journal_id
            """)
            contacts_result = await self.db_connection.execute(
                contacts_query, {"journal_id": journal_id}
            )
            contacts_rows = contacts_result.fetchall()
            contact_ids = [row.contact_id for row in contacts_rows]

            # Fetch tag IDs
            tags_query = text("""
                SELECT DISTINCT tag_id
                FROM journal_tag_assignments
                WHERE journal_id = :journal_id
            """)
            tags_result = await self.db_connection.execute(
                tags_query, {"journal_id": journal_id}
            )
            tags_rows = tags_result.fetchall()
            tag_ids = [str(row.tag_id) for row in tags_rows]

            # Fetch calendar ID if EVENT type
            calendar_id = None
            if "EVENT" in types:
                calendar_query = text("""
                    SELECT calendar_id FROM journal_calendar_info
                    WHERE journal_id = :journal_id
                """)
                calendar_result = await self.db_connection.execute(
                    calendar_query, {"journal_id": journal_id}
                )
                calendar_row = calendar_result.fetchone()
                if calendar_row:
                    calendar_id = str(calendar_row.calendar_id)

            # Fetch location if EVENT type
            location = None
            if "EVENT" in types:
                location_query = text("""
                    SELECT location FROM journal_calendar_info
                    WHERE journal_id = :journal_id
                """)
                location_result = await self.db_connection.execute(
                    location_query, {"journal_id": journal_id}
                )
                location_row = location_result.fetchone()
                if location_row and location_row.location:
                    location = location_row.location

            return {
                "id": journal_row.id,
                "user_id": journal_row.user_id,
                "title": journal_row.title,
                "content": journal_row.content,
                "event_date_range_start": journal_row.event_date_range_start.isoformat()
                if journal_row.event_date_range_start
                else None,
                "event_date_range_end": journal_row.event_date_range_end.isoformat()
                if journal_row.event_date_range_end
                else None,
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
                "Failed to fetch complete journal data",
                journal_id=journal_id,
                error=str(e),
            )
            return None

    def _create_fallback_journal_data(
        self, journal_id: int, journal_data: dict[str, Any], event: OutboxEvent
    ) -> dict[str, Any]:
        """
        Create fallback journal data from event when database fetch fails.

        Args:
            journal_id: ID of the journal
            journal_data: Journal data from the event
            event: The outbox event

        Returns:
            Dictionary with fallback journal data for indexing
        """
        return {
            "id": journal_id,
            "user_id": journal_data.get("user_id", ""),
            "title": journal_data.get("title", ""),
            "content": journal_data.get("content", ""),
            "event_date_range_start": None,
            "event_date_range_end": None,
            "types": ["NOTE"],
            "contact_ids": [],
            "tag_ids": [],
            "calendar_id": None,
            "parent_id": None,
            "location": None,
            "entity_type": "journal",
            "created_at": event.occurred_at.isoformat() if event.occurred_at else None,
            "updated_at": event.occurred_at.isoformat() if event.occurred_at else None,
        }

    async def _index_journal_created(self, index_name: str, event: OutboxEvent) -> None:
        """
        Index a newly created journal.

        Args:
            index_name: Name of the search index
            event: Journal created event
        """
        journal_data = event.event_data
        journal_id = journal_data["journal_id"]

        # Fetch complete journal data from database
        complete_data = await self._fetch_complete_journal_data(journal_id)

        if not complete_data:
            # Fallback to basic data from event if database fetch fails
            logger.warning(
                "Could not fetch complete journal data, using event data",
                journal_id=journal_id,
            )
            complete_data = self._create_fallback_journal_data(
                journal_id, journal_data, event
            )

        index = self.client.index(index_name)
        task = index.add_documents([complete_data])
        self.client.wait_for_task(task.task_uid)

        logger.debug(
            "Journal indexed in search",
            journal_id=journal_id,
            index_name=index_name,
            fields_indexed=list(complete_data.keys()),
        )

    async def _index_journal_updated(self, index_name: str, event: OutboxEvent) -> None:
        """
        Update an existing journal in the search index.

        Args:
            index_name: Name of the search index
            event: Journal updated event
        """
        journal_data = event.event_data
        journal_id = journal_data["journal_id"]

        # For updates, try to fetch the complete current data to ensure consistency
        complete_data = await self._fetch_complete_journal_data(journal_id)

        if not complete_data:
            # Fallback to basic data from event if database fetch fails
            logger.warning(
                "Could not fetch complete journal data for update, using event data",
                journal_id=journal_id,
            )
            complete_data = self._create_fallback_journal_data(
                journal_id, journal_data, event
            )
        else:
            # Update the timestamp
            if event.occurred_at:
                complete_data["updated_at"] = event.occurred_at.isoformat()

        index = self.client.index(index_name)
        task = index.update_documents([complete_data])
        self.client.wait_for_task(task.task_uid)

        logger.debug(
            "Journal updated in search",
            journal_id=journal_id,
            index_name=index_name,
            fields_updated=list(complete_data.keys()),
        )

    async def _reindex_journal_for_tag_change(
        self, index_name: str, event: OutboxEvent
    ) -> None:
        """
        Rebuild a journal's document after the tags it carries changed.

        Differs from :meth:`_index_journal_updated` in two ways, both deliberate:

        * The document keeps the row's own ``updated_at``. A tag change does not
          touch ``journals.updated_at``, and ``updated_at`` is a sortable search
          attribute, so copying the event time would sort search results by a
          value no row holds.
        * There is no fallback document. A tag event carries no title or user id
          to build one from, and the expected reason for a missing journal is that
          it was deleted between the tag write and the relay — in which case its
          document has already been removed by ``JournalDeleted``. A fetch failure
          for any other reason is indistinguishable here, because
          ``_fetch_complete_journal_data`` reports both as ``None``.

        Args:
            index_name: Name of the search index
            event: Journal tag event naming the affected journal
        """
        journal_id = event.event_data["journal_id"]

        complete_data = await self._fetch_complete_journal_data(journal_id)

        if not complete_data:
            logger.warning(
                "Skipping tag re-index: could not fetch journal data",
                journal_id=journal_id,
                event_id=event.event_id,
                event_type=event.event_type,
            )
            return

        index = self.client.index(index_name)
        task = index.update_documents([complete_data])
        self.client.wait_for_task(task.task_uid)

        logger.debug(
            "Journal re-indexed after tag change",
            journal_id=journal_id,
            event_type=event.event_type,
            index_name=index_name,
            tag_ids=complete_data.get("tag_ids"),
        )

    def _index_journal_deleted(self, index_name: str, event: OutboxEvent) -> None:
        """
        Remove a deleted journal from the search index.

        Args:
            index_name: Name of the search index
            event: Journal deleted event
        """
        journal_data = event.event_data
        journal_id = journal_data["journal_id"]

        index = self.client.index(index_name)
        task = index.delete_document(journal_id)
        self.client.wait_for_task(task.task_uid)

        logger.debug(
            "Journal removed from search", journal_id=journal_id, index_name=index_name
        )


def ensure_journal_search_index(client: MeiliSearchClient | None = None) -> bool:
    """Create or reconfigure the journals index at application startup.

    Index settings used to be applied only when the next indexing event
    arrived, so a deployment that added a required filterable attribute (the
    ``id`` filter behind the MCP ``integration_source`` search) kept failing
    until a journal happened to change. Calling this from the app lifespan
    applies the settings immediately. Returns True when settings were
    (re)applied; existing documents then still carry the old schema (e.g. an
    incomplete ``types`` list) until ``POST /api/search/reindex`` is run, and
    a warning says so.
    """
    service = JournalIndexingService(client=client)
    index_name = get_index_name("journals")
    reconfigured = service._ensure_journals_index_exists(index_name)
    if reconfigured:
        logger.warning(
            "Journals search index settings were (re)applied; existing documents "
            "may predate the current schema. Run POST /api/search/reindex to "
            "backfill filterable attributes and full type lists.",
            index_name=index_name,
        )
    return reconfigured
