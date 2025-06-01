"""
Search indexer for MeiliSearch integration.

Processes domain events from the outbox and updates MeiliSearch indices
to keep search data synchronized with the database.
"""

from typing import Any

import structlog
from meilisearch.errors import MeilisearchError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.events.outbox_repository import OutboxEvent
from app.infrastructure.search.meilisearch_client import (
    CONTACTS_INDEX_SETTINGS,
    get_index_name,
    get_meilisearch_client,
)

logger = structlog.get_logger()


class SearchIndexer:
    """Handles MeiliSearch indexing based on domain events."""

    def __init__(self, db_connection: AsyncConnection | None = None) -> None:
        """Initialize the search indexer."""
        self.client = get_meilisearch_client()
        self.db_connection = db_connection

    async def process_event(self, event: OutboxEvent) -> None:
        """
        Process a single outbox event and update search indices.

        Args:
            event: Outbox event to process
        """
        try:
            if event.event_type.startswith("Contact") or event.event_type in [
                "TagAssigned",
                "TagRemoved",
            ]:
                await self._process_contact_event(event)
            else:
                logger.debug(
                    "Skipping unsupported event type",
                    event_type=event.event_type,
                    event_id=event.event_id,
                )

        except Exception as e:
            logger.error(
                "Failed to process event for search indexing",
                event_id=event.event_id,
                event_type=event.event_type,
                error=str(e),
            )
            raise

    async def _process_contact_event(self, event: OutboxEvent) -> None:
        """
        Process contact-related events.

        Args:
            event: Contact event to process
        """
        contact_index_name = get_index_name("contacts")

        try:
            # Ensure the contacts index exists with proper settings
            self._ensure_contacts_index_exists(contact_index_name)

            if event.event_type == "ContactCreated":
                await self._index_contact_created(contact_index_name, event)
            elif event.event_type == "ContactUpdated":
                await self._index_contact_updated(contact_index_name, event)
            elif event.event_type == "ContactDeleted":
                self._index_contact_deleted(contact_index_name, event)
            elif event.event_type in ["TagAssigned", "TagRemoved"]:
                await self._index_contact_tag_change(contact_index_name, event)
            else:
                logger.debug(
                    "Skipping unsupported contact event type",
                    event_type=event.event_type,
                    event_id=event.event_id,
                )

        except MeilisearchError as e:
            logger.error(
                "MeiliSearch error processing contact event",
                event_id=event.event_id,
                event_type=event.event_type,
                error=str(e),
            )
            raise

    def _ensure_contacts_index_exists(self, index_name: str) -> None:
        """
        Ensure the contacts index exists with proper settings.

        Args:
            index_name: Name of the contacts index
        """
        try:
            # Try to get the index
            index = self.client.index(index_name)
            index.get_stats()

        except MeilisearchError:
            # Index doesn't exist, create it
            logger.info("Creating contacts search index", index_name=index_name)

            # Create the index
            task = self.client.create_index(index_name, {"primaryKey": "id"})
            self.client.wait_for_task(task.task_uid)

            # Configure the index settings
            index = self.client.index(index_name)
            task = index.update_settings(CONTACTS_INDEX_SETTINGS)
            self.client.wait_for_task(task.task_uid)

            logger.info("Contacts search index created", index_name=index_name)

    async def _fetch_complete_contact_data(
        self, contact_id: int
    ) -> dict[str, Any] | None:
        """
        Fetch complete contact data from the database for search indexing.

        Args:
            contact_id: ID of the contact to fetch

        Returns:
            Complete contact data dictionary or None if not found
        """
        if not self.db_connection:
            logger.warning("No database connection available for fetching contact data")
            return None

        try:
            # Fetch basic contact info
            contact_query = text("""
                SELECT id, first_name, last_name, middle_name, nick_name,
                       created_at, updated_at
                FROM contacts
                WHERE id = :contact_id
            """)
            contact_result = await self.db_connection.execute(
                contact_query, {"contact_id": contact_id}
            )
            contact_row = contact_result.fetchone()

            if not contact_row:
                return None

            # Fetch contact methods (email, phone)
            methods_query = text("""
                SELECT method_type, value, label, is_primary
                FROM contact_methods
                WHERE contact_id = :contact_id
                ORDER BY is_primary DESC, created_at ASC
            """)
            methods_result = await self.db_connection.execute(
                methods_query, {"contact_id": contact_id}
            )
            methods_rows = methods_result.fetchall()

            # Fetch contact notes
            notes_query = text("""
                SELECT content
                FROM contact_notes
                WHERE contact_id = :contact_id
                ORDER BY created_at DESC
            """)
            notes_result = await self.db_connection.execute(
                notes_query, {"contact_id": contact_id}
            )
            notes_rows = notes_result.fetchall()

            # Fetch contact tags
            tags_query = text("""
                SELECT t.name
                FROM tags t
                JOIN contact_tags ct ON t.id = ct.tag_id
                WHERE ct.contact_id = :contact_id
                ORDER BY t.name
            """)
            tags_result = await self.db_connection.execute(
                tags_query, {"contact_id": contact_id}
            )
            tags_rows = tags_result.fetchall()

            # Build comprehensive contact document
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

            notes_content = " ".join([row.content for row in notes_rows])
            tags = [row.name for row in tags_rows]

            full_name = (
                f"{contact_row.first_name} {contact_row.last_name or ''}".strip()
            )

            return {
                "id": contact_row.id,
                "first_name": contact_row.first_name,
                "last_name": contact_row.last_name or "",
                "middle_name": contact_row.middle_name or "",
                "nick_name": contact_row.nick_name or "",
                "full_name": full_name,
                "email": primary_email,
                "emails": emails,
                "phone": primary_phone,
                "phones": phones,
                "notes_content": notes_content,
                "tags": tags,
                "entity_type": "contact",
                "created_at": contact_row.created_at.isoformat()
                if contact_row.created_at
                else None,
                "updated_at": contact_row.updated_at.isoformat()
                if contact_row.updated_at
                else None,
            }

        except Exception as e:
            logger.error(
                "Failed to fetch complete contact data",
                contact_id=contact_id,
                error=str(e),
            )
            return None

    async def _index_contact_created(self, index_name: str, event: OutboxEvent) -> None:
        """
        Index a newly created contact.

        Args:
            index_name: Name of the search index
            event: Contact created event
        """
        contact_data = event.event_data
        contact_id = contact_data["contact_id"]

        # Fetch complete contact data from database
        complete_data = await self._fetch_complete_contact_data(contact_id)

        if not complete_data:
            # Fallback to basic data from event if database fetch fails
            logger.warning(
                "Could not fetch complete contact data, using event data",
                contact_id=contact_id,
            )
            occurred_at_str = event.occurred_at.isoformat()

            complete_data = {
                "id": contact_id,
                "first_name": contact_data.get("first_name", ""),
                "last_name": contact_data.get("last_name", ""),
                "full_name": f"{contact_data.get('first_name', '')} {contact_data.get('last_name', '')}".strip(),
                "email": contact_data.get("email"),
                "phone": contact_data.get("phone"),
                "entity_type": "contact",
                "created_at": occurred_at_str,
                "updated_at": occurred_at_str,
                "tags": [],
                "notes_content": "",
            }

        index = self.client.index(index_name)
        task = index.add_documents([complete_data])
        self.client.wait_for_task(task.task_uid)

        logger.debug(
            "Contact indexed in search",
            contact_id=contact_id,
            index_name=index_name,
            fields_indexed=list(complete_data.keys()),
        )

    async def _index_contact_updated(self, index_name: str, event: OutboxEvent) -> None:
        """
        Update an existing contact in the search index.

        Args:
            index_name: Name of the search index
            event: Contact updated event
        """
        contact_data = event.event_data
        contact_id = contact_data["contact_id"]

        # For updates, always fetch the complete current data to ensure consistency
        complete_data = await self._fetch_complete_contact_data(contact_id)

        if not complete_data:
            logger.warning(
                "Could not fetch complete contact data for update",
                contact_id=contact_id,
            )
            return

        # Update the timestamp
        complete_data["updated_at"] = event.occurred_at.isoformat()

        index = self.client.index(index_name)
        task = index.update_documents([complete_data])
        self.client.wait_for_task(task.task_uid)

        logger.debug(
            "Contact updated in search",
            contact_id=contact_id,
            index_name=index_name,
            fields_updated=list(complete_data.keys()),
        )

    def _index_contact_deleted(self, index_name: str, event: OutboxEvent) -> None:
        """
        Remove a deleted contact from the search index.

        Args:
            index_name: Name of the search index
            event: Contact deleted event
        """
        contact_data = event.event_data
        contact_id = contact_data["contact_id"]

        index = self.client.index(index_name)
        task = index.delete_document(contact_id)
        self.client.wait_for_task(task.task_uid)

        logger.debug(
            "Contact removed from search", contact_id=contact_id, index_name=index_name
        )

    async def _index_contact_tag_change(
        self, index_name: str, event: OutboxEvent
    ) -> None:
        """
        Update contact tags in the search index.

        Args:
            index_name: Name of the search index
            event: Tag assignment/removal event
        """
        contact_data = event.event_data
        contact_id = contact_data["contact_id"]

        # Fetch complete contact data to get updated tag list
        complete_data = await self._fetch_complete_contact_data(contact_id)

        if not complete_data:
            logger.warning(
                "Could not fetch complete contact data for tag update",
                contact_id=contact_id,
            )
            return

        # Update the timestamp
        complete_data["updated_at"] = event.occurred_at.isoformat()

        index = self.client.index(index_name)
        task = index.update_documents([complete_data])
        self.client.wait_for_task(task.task_uid)

        logger.debug(
            "Contact tags updated in search",
            contact_id=contact_id,
            index_name=index_name,
            tags=complete_data.get("tags", []),
        )
