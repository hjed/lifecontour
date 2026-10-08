"""
Search indexer for MeiliSearch integration.

Processes domain events from the outbox and updates MeiliSearch indices
to keep search data synchronized with the database.
"""

from collections.abc import Sequence
from typing import Any

import structlog
from core_shared.models.contacts.entities import RelationshipType
from meilisearch.errors import MeilisearchError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_importance_repository import (
    SqlContactImportanceRepository,
)
from app.infrastructure.events.outbox_repository import OutboxEvent
from app.infrastructure.search.journal_indexing_service import JournalIndexingService
from app.infrastructure.search.meilisearch_client import (
    CONTACTS_INDEX_SETTINGS,
    get_index_name,
    get_meilisearch_client,
)

logger = structlog.get_logger()


def format_relationship(
    relationship_type: str, *, to_user: bool, other_name: str | None, incoming: bool
) -> str | None:
    """Render a relationship row as "<role>: <other party>" for the contact being indexed.

    A row's type is what its to-side is to its from-side, so an incoming row
    (the indexed contact is the to-side) is inverted. Returns None when the
    other contact's name is unknown.
    """
    rel_type = RelationshipType(relationship_type)
    if incoming:
        rel_type = rel_type.get_inverse_type()
    label = rel_type.value.replace("_", " ").title()
    if to_user:
        return f"{label}: the User"
    if other_name is None:
        return None
    return f"{label}: {other_name}"


# Contact-scoped events whose type does not start with "Contact". Kept as a
# named set because ``SearchIndexerConsumer`` subscribes to a list of event
# types, and a type subscribed but absent here is acknowledged and dropped -
# the document silently goes stale. ``test_search_indexer_consumer`` pins the
# two together in both directions.
CONTACT_SCOPED_EVENT_TYPES = frozenset(
    {
        "TagAssigned",
        "TagRemoved",
        "ImportantDateAdded",
        "ImportantDateUpdated",
        "ImportantDateDeleted",
    }
)

# Events that make a contact's indexed document stale and so re-index it whole.
CONTACT_REINDEX_EVENT_TYPES = frozenset(
    {
        "ContactUpdated",
        "ContactSummaryRefreshRequested",
        "ContactSummaryRefreshDue",
        "ImportantDateAdded",
        "ImportantDateUpdated",
        "ImportantDateDeleted",
    }
)


def primary_or_first_in_use(methods: Sequence[Any], method_type: str) -> str | None:
    """The contact's value of ``method_type`` a search document leads with.

    The primary one, or with none the first still in use: an archived value
    is kept for matching (it stays in ``emails`` / ``phones``) but never stands
    as the contact's current email or phone.
    """
    of_type = [m for m in methods if m.method_type == method_type]
    chosen = next((m for m in of_type if m.is_primary), None) or next(
        (m for m in of_type if not m.is_archived), None
    )
    return chosen.value if chosen is not None else None


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
            if (
                event.event_type.startswith("Contact")
                or event.event_type in CONTACT_SCOPED_EVENT_TYPES
            ):
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
            elif event.event_type in CONTACT_REINDEX_EVENT_TYPES:
                await self._index_contact_updated(contact_index_name, event)
            elif event.event_type == "ContactDeleted":
                self._index_contact_deleted(contact_index_name, event)
            elif event.event_type == "ContactMerged":
                self._index_contact_merged(contact_index_name, event)
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

        Settings are always re-applied so that new filterable/sortable/searchable
        attributes take effect on already-existing indices without requiring
        recreation.

        Args:
            index_name: Name of the contacts index
        """
        try:
            # Try to get the index
            index = self.client.index(index_name)
            index.get_stats()

            # Index exists — re-apply settings so new attributes are picked up
            task = index.update_settings(CONTACTS_INDEX_SETTINGS)
            self.client.wait_for_task(task.task_uid)

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
            # Fetch basic contact info. The importance signals — favourite, the
            # two recent counts and the last-activity instant — come from the
            # shared read below rather than from here, so that the home
            # dashboard ranks contacts by exactly what the index ranks them by.
            contact_query = text("""
                SELECT id, first_name, last_name, middle_name, nick_name,
                       company, job_title, created_at, updated_at
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
                SELECT method_type, value, label, is_primary, is_archived
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
            primary_email = primary_or_first_in_use(methods_rows, "email")
            primary_phone = primary_or_first_in_use(methods_rows, "phone")

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

            relationships_list = []
            for row in relationships_rows:
                name = (
                    f"{row.first_name} {row.last_name or ''}".strip()
                    if row.first_name
                    else None
                )
                formatted = format_relationship(
                    row.relationship_type,
                    to_user=row.to_user,
                    other_name=name,
                    incoming=row.direction == "incoming",
                )
                if formatted is not None:
                    relationships_list.append(formatted)

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

            # Fetch journal mentions. Titles are search *text*; the count of
            # recent journals is an importance signal and belongs to the shared
            # read, which is why this query no longer asks for dates.
            journals_query = text("""
                SELECT j.title
                FROM journals j
                JOIN journal_contact_relationships jc ON j.id = jc.journal_id
                WHERE jc.contact_id = :contact_id
            """)
            journals_result = await self.db_connection.execute(
                journals_query, {"contact_id": contact_id}
            )
            journal_mentions = [
                row.title for row in journals_result.fetchall() if row.title
            ]

            # The importance signals, from the read the home dashboard also uses
            # so that both surfaces rank a contact by the same numbers.
            importance_repository = SqlContactImportanceRepository(self.db_connection)
            importance = (await importance_repository.for_contacts([contact_id]))[
                contact_id
            ]
            last_activity_date = importance.last_activity_at

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
                "is_favourite": importance.is_favourite,
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
                "journal_count_30d": importance.journal_count_30d,
                "activity_count_30d": importance.activity_count_30d,
            }

        except Exception as e:  # noqa: BLE001
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

    def _index_contact_merged(self, index_name: str, event: OutboxEvent) -> None:
        """Remove the merged-away source contact from the search index.

        A merge deletes the source contact at the database level (its aggregate
        has been re-pointed onto the survivor), so its now-stale document must be
        dropped from search. Only the source is removed — the survivor keeps its
        identity and is re-indexed via its own ``ContactSummaryRefreshRequested``
        / ``ContactUpdated`` events. Unlike ``ContactDeleted``, ``ContactMerged``
        carries no remote-deletion semantics, so de-indexing here cannot trigger
        integration workers to delete a remote contact.

        Args:
            index_name: Name of the search index
            event: Contact merged event
        """
        contact_data = event.event_data
        source_contact_id = contact_data["source_contact_id"]

        index = self.client.index(index_name)
        task = index.delete_document(source_contact_id)
        self.client.wait_for_task(task.task_uid)

        logger.debug(
            "Merged source contact removed from search",
            source_contact_id=source_contact_id,
            survivor_contact_id=contact_data.get("survivor_contact_id"),
            index_name=index_name,
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
