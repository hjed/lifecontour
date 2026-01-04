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

from app.infrastructure.events.outbox_repository import OutboxEvent
from app.infrastructure.search.meilisearch_client import (
    JOURNAL_INDEX_SETTINGS,
    get_index_name,
    get_meilisearch_client,
)

logger = structlog.get_logger()


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

    def _ensure_journals_index_exists(self, index_name: str) -> None:
        """
        Ensure the journals index exists with proper settings.

        Args:
            index_name: Name of the journals index
        """
        try:
            # Try to get the index
            index = self.client.index(index_name)
            index.get_stats()

        except MeilisearchError:
            # Index doesn't exist, create it
            logger.info("Creating journals search index", index_name=index_name)

            # Create the index
            task = self.client.create_index(index_name, {"primaryKey": "id"})
            self.client.wait_for_task(task.task_uid)

            # Configure the index settings
            index = self.client.index(index_name)
            task = index.update_settings(JOURNAL_INDEX_SETTINGS)
            self.client.wait_for_task(task.task_uid)

            logger.info("Journals search index created", index_name=index_name)

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

            # Fetch journal types using a single query with LEFT JOINs
            # This is more efficient than UNION ALL as it scans each table only once
            types_query = text("""
                SELECT
                    CASE WHEN jci.journal_id IS NOT NULL THEN 'EVENT' END as event_type,
                    CASE WHEN jmd.journal_id IS NOT NULL THEN 'MOOD_RATING' END as mood_type,
                    CASE WHEN jpd.journal_id IS NOT NULL THEN 'PLAN' END as plan_type,
                    CASE WHEN jtd.journal_id IS NOT NULL THEN 'TRAVEL' END as travel_type,
                    CASE WHEN jpad.journal_id IS NOT NULL THEN 'PHOTO_ALBUM' END as photo_type
                FROM journals j
                LEFT JOIN journal_calendar_info jci ON j.id = jci.journal_id
                LEFT JOIN journal_mood_data jmd ON j.id = jmd.journal_id
                LEFT JOIN journal_plan_data jpd ON j.id = jpd.journal_id
                LEFT JOIN journal_travel_data jtd ON j.id = jtd.journal_id
                LEFT JOIN journal_photo_album_data jpad ON j.id = jpad.journal_id
                WHERE j.id = :journal_id
            """)
            types_result = await self.db_connection.execute(
                types_query, {"journal_id": journal_id}
            )
            types_row = types_result.fetchone()

            # All journals are at least NOTE type
            types = ["NOTE"]
            if types_row:
                # Add non-null type values
                for type_value in [
                    types_row.event_type,
                    types_row.mood_type,
                    types_row.plan_type,
                    types_row.travel_type,
                    types_row.photo_type,
                ]:
                    if type_value:
                        types.append(type_value)

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

        except Exception as e:
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
