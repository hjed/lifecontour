"""
Search indexer for MeiliSearch integration.

Processes domain events from the outbox and updates MeiliSearch indices
to keep search data synchronized with the database.
"""

from datetime import UTC
from typing import Any

import structlog
from meilisearch.errors import MeilisearchError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.events.outbox_repository import OutboxEvent
from app.infrastructure.search.journal_indexing_service import JournalIndexingService
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
                "ImportantDateAdded",
                "ImportantDateUpdated",
                "ImportantDateDeleted",
            ]:
                await self._process_contact_event(event)
            elif event.event_type.startswith("Journal"):
                journal_indexer = JournalIndexingService(
                    db_connection=self.db_connection
                )
                await journal_indexer.process_event(event)
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
            elif event.event_type in [
                "ContactUpdated",
                "ContactSummaryRefreshRequested",
                "ImportantDateAdded",
                "ImportantDateUpdated",
                "ImportantDateDeleted",
            ]:
                await self._index_contact_updated(contact_index_name, event)
            elif event.event_type == "ContactDeleted":
                self._index_contact_deleted(contact_index_name, event)
            elif event.event_type in ["TagAssigned", "TagRemoved"]:
                await self._index_contact_tag_change(contact_index_name, event)
            elif event.event_type in [
                "ContactRelationshipCreated",
                "ContactRelationshipUpdated",
                "ContactRelationshipDeleted",
            ]:
                await self._index_contact_relationship_change(contact_index_name, event)
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
            from datetime import datetime, timedelta

            # Fetch basic contact info
            contact_query = text("""
                SELECT id, first_name, last_name, middle_name, nick_name,
                       company, job_title, is_favourite, created_at, updated_at
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

            # Fetch contact relationships (both outgoing and incoming)
            relationships_query = text("""
                SELECT
                    cr.relationship_type,
                    cr.to_user,
                    c.first_name,
                    c.last_name,
                    'outgoing' as direction
                FROM contact_relationships cr
                LEFT JOIN contacts c ON cr.to_contact_id = c.id
                WHERE cr.from_contact_id = :contact_id
                UNION ALL
                SELECT
                    cr.relationship_type,
                    cr.to_user,
                    c.first_name,
                    c.last_name,
                    'incoming' as direction
                FROM contact_relationships cr
                LEFT JOIN contacts c ON cr.from_contact_id = c.id
                WHERE cr.to_contact_id = :contact_id
            """)
            relationships_result = await self.db_connection.execute(
                relationships_query, {"contact_id": contact_id}
            )
            relationships_rows = relationships_result.fetchall()

            # Inverse mapping for incoming relationships
            inverse_map = {
                "parent": "child",
                "child": "parent",
                "partner": "partner",
                "sibling": "sibling",
                "friend": "friend",
                "colleague": "colleague",
                "family": "family",
                "other": "other",
            }

            # Format relationships
            relationships_list = []
            for row in relationships_rows:
                if row.to_user:
                    rel_type = row.relationship_type.replace("_", " ").title()
                    relationships_list.append(f"{rel_type} of the User")
                elif row.first_name:
                    name = f"{row.first_name} {row.last_name or ''}".strip()
                    if row.direction == "incoming":
                        inv = inverse_map.get(
                            row.relationship_type, row.relationship_type
                        )
                        rel_type = inv.replace("_", " ").title()
                    else:
                        rel_type = row.relationship_type.replace("_", " ").title()
                    relationships_list.append(f"{rel_type} of {name}")

            # Fetch contact summaries
            summary_query = text("""
                SELECT summary_text, is_disabled
                FROM contact_summaries
                WHERE contact_id = :contact_id
            """)
            summary_result = await self.db_connection.execute(
                summary_query, {"contact_id": contact_id}
            )
            summary_row = summary_result.fetchone()
            summary_text = None
            has_summary = False
            if summary_row and not summary_row.is_disabled:
                summary_text = summary_row.summary_text
                has_summary = bool(summary_text)

            # Fetch important dates
            dates_query = text("""
                SELECT cid.date_type, cid.precision, cid.year, cid.month, cid.day, cdt.name as custom_name
                FROM contact_important_dates cid
                LEFT JOIN custom_date_types cdt ON cid.custom_date_type_id = cdt.id
                WHERE cid.contact_id = :contact_id
            """)
            dates_result = await self.db_connection.execute(
                dates_query, {"contact_id": contact_id}
            )
            dates_rows = dates_result.fetchall()
            important_dates_list = []

            import calendar

            for row in dates_rows:
                parts = []
                # Name part
                if row.date_type == "custom" and row.custom_name:
                    parts.append(row.custom_name)
                else:
                    parts.append(row.date_type.replace("_", " ").title())

                # Date part
                date_str = ""
                if row.precision == "full":
                    month_name = calendar.month_name[row.month] if row.month else ""
                    date_str = f"{month_name} {row.day}, {row.year}"
                elif row.precision == "day_month":
                    month_name = calendar.month_name[row.month] if row.month else ""
                    date_str = f"{month_name} {row.day}"
                elif row.precision == "year":
                    date_str = str(row.year)

                if date_str:
                    important_dates_list.append(f"{parts[0]} ({date_str})")

            # Fetch journal mentions
            journals_query = text("""
                SELECT j.title, j.created_at
                FROM journals j
                JOIN journal_contact_relationships jc ON j.id = jc.journal_id
                WHERE jc.contact_id = :contact_id
            """)
            journals_result = await self.db_connection.execute(
                journals_query, {"contact_id": contact_id}
            )
            journals_rows = journals_result.fetchall()

            journal_mentions = []
            journal_count_30d = 0
            now = datetime.now(UTC)
            thirty_days_ago = now - timedelta(days=30)

            latest_journal_date = None
            for row in journals_rows:
                if row.title:
                    journal_mentions.append(row.title)

                # created_at is naive or aware, we handle properly in PG but python needs aware for comparison
                row_dt = row.created_at
                if row_dt and row_dt.tzinfo is None:
                    row_dt = row_dt.replace(tzinfo=UTC)

                if row_dt:
                    if row_dt >= thirty_days_ago:
                        journal_count_30d += 1
                    if not latest_journal_date or row_dt > latest_journal_date:
                        latest_journal_date = row_dt

            # Fetch activities (history)
            history_query = text("""
                SELECT created_at
                FROM contact_field_history
                WHERE entity_id = :contact_id AND entity_type = 'contact'
            """)
            history_result = await self.db_connection.execute(
                history_query, {"contact_id": contact_id}
            )
            history_rows = history_result.fetchall()

            activity_count_30d = 0
            latest_activity_date = None
            for row in history_rows:
                row_dt = row.created_at
                if row_dt and row_dt.tzinfo is None:
                    row_dt = row_dt.replace(tzinfo=UTC)

                if row_dt:
                    if row_dt >= thirty_days_ago:
                        activity_count_30d += 1
                    if not latest_activity_date or row_dt > latest_activity_date:
                        latest_activity_date = row_dt

            # Calculate last activity date
            last_activity_date = contact_row.updated_at
            if last_activity_date and last_activity_date.tzinfo is None:
                last_activity_date = last_activity_date.replace(tzinfo=UTC)

            if latest_journal_date and (
                not last_activity_date or latest_journal_date > last_activity_date
            ):
                last_activity_date = latest_journal_date
            if latest_activity_date and (
                not last_activity_date or latest_activity_date > last_activity_date
            ):
                last_activity_date = latest_activity_date

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
                "notes_content": notes_content,
                "tags": tags,
                "relationships": relationships_list,
                "entity_type": "contact",
                "is_favourite": contact_row.is_favourite,
                "created_at": contact_row.created_at.isoformat()
                if contact_row.created_at
                else None,
                "updated_at": contact_row.updated_at.isoformat()
                if contact_row.updated_at
                else None,
                "summary_text": summary_text,
                "important_dates": important_dates_list,
                "journal_mentions": journal_mentions,
                "has_summary": has_summary,
                "last_activity_date": last_activity_date.isoformat()
                if last_activity_date
                else None,
                "journal_count_30d": journal_count_30d,
                "activity_count_30d": activity_count_30d,
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

            first_name = contact_data.get("first_name", "")
            last_name = contact_data.get("last_name", "")
            full_name = f"{first_name} {last_name}".strip()

            complete_data = {
                "id": contact_id,
                "first_name": first_name,
                "last_name": last_name,
                "full_name": full_name,
                "email": contact_data.get("email"),
                "phone": contact_data.get("phone"),
                "entity_type": "contact",
                "is_favourite": contact_data.get("is_favourite", False),
                "created_at": occurred_at_str,
                "updated_at": occurred_at_str,
                "tags": [],
                "relationships": [],
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

    async def _index_contact_relationship_change(
        self, index_name: str, event: OutboxEvent
    ) -> None:
        """
        Update contact relationships in the search index.

        Args:
            index_name: Name of the search index
            event: Relationship event
        """
        contact_data = event.event_data

        # We need to reindex both contacts involved in the relationship
        contact_ids = set()
        if "from_contact_id" in contact_data and contact_data["from_contact_id"]:
            contact_ids.add(contact_data["from_contact_id"])
        if "to_contact_id" in contact_data and contact_data["to_contact_id"]:
            contact_ids.add(contact_data["to_contact_id"])

        for contact_id in contact_ids:
            # Fetch complete contact data to get updated relationships list
            complete_data = await self._fetch_complete_contact_data(contact_id)

            if not complete_data:
                logger.warning(
                    "Could not fetch complete contact data for relationship update",
                    contact_id=contact_id,
                )
                continue

            # Update the timestamp
            complete_data["updated_at"] = event.occurred_at.isoformat()

            index = self.client.index(index_name)
            task = index.update_documents([complete_data])
            self.client.wait_for_task(task.task_uid)

            logger.debug(
                "Contact relationships updated in search",
                contact_id=contact_id,
                index_name=index_name,
                relationships=complete_data.get("relationships", []),
            )
