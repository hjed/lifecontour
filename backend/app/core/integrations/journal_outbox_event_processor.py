"""
Journal Outbox Event Processor for handling inbound journal sync events.

Processes journal_event.created, journal_event.updated,
journal_event.conflicted, and journal_event.cancelled outbox events
from integration workers to create/update journals in the core system.
"""

from datetime import UTC, datetime, time
from typing import Any
from uuid import UUID

import structlog
from core_shared.models.journals import (
    AttendeeStatus,
    ContactEventRole,
    EventDateRange,
    Journal,
)
from core_shared.models.journals.journal_contact_relationship import (
    JournalContactRelationship,
)
from core_shared.models.journals.journal_relationship_types import (
    JournalContactRelationshipType,
)
from core_shared.models.outbox import OutboxEvent
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.services.journal_service import JournalService

logger = structlog.get_logger()

# Event type constants
EVENT_TYPE_JOURNAL_EVENT_CREATED = "journal_event.created"
EVENT_TYPE_JOURNAL_EVENT_UPDATED = "journal_event.updated"
EVENT_TYPE_JOURNAL_EVENT_CONFLICTED = "journal_event.conflicted"
EVENT_TYPE_JOURNAL_EVENT_CANCELLED = "journal_event.cancelled"
EVENT_TYPE_JOURNAL_REVIEW_DETECT_MATCHES = "journal_review.detect_matches"


class JournalOutboxEventProcessingError(Exception):
    """Raised when journal outbox event processing fails."""


class ContactResolver:
    """Resolves contact identifiers to contact IDs.

    Strategy pattern class for contact resolution, currently supporting
    email-based lookup. Designed for extensibility — future implementations
    can add name-based matching or other resolution strategies.
    """

    def __init__(self, connection: AsyncConnection) -> None:
        """Initialize with database connection."""
        self.connection = connection

    async def resolve_by_email(self, email: str) -> int | None:
        """Resolve a contact by email address.

        Args:
            email: Email address to search for

        Returns:
            Contact ID if found, None otherwise
        """
        result = await self.connection.execute(
            text("""
                SELECT c.id
                FROM contacts c
                JOIN contact_methods cm ON c.id = cm.contact_id
                WHERE cm.method_type = 'email'
                  AND cm.value = :email
                LIMIT 1
            """),
            {"email": email},
        )
        row = result.fetchone()
        return row.id if row else None


class JournalOutboxEventProcessor:
    """
    Processes inbound journal sync events from integration workers.

    Handles journal_event.* outbox events by creating/updating journals,
    saving calendar info, managing external event links, and syncing
    contact relationships (e.g. invitees).
    """

    def __init__(
        self,
        journal_service: JournalService,
        connection: AsyncConnection,
        match_candidate_detector: Any = None,
    ) -> None:
        """
        Initialize the journal outbox event processor.

        Args:
            journal_service: Service for journal operations
            connection: Database connection for transactions
            match_candidate_detector: Optional detector for match candidates
        """
        self.journal_service = journal_service
        self.connection = connection
        self.contact_resolver = ContactResolver(connection)
        self.match_candidate_detector = match_candidate_detector

    async def process_event(self, event: OutboxEvent) -> dict[str, Any]:
        """
        Process a single journal outbox event.

        Args:
            event: Outbox event to process

        Returns:
            Processing result dictionary

        Raises:
            JournalOutboxEventProcessingError: If event processing fails
        """
        logger.info(
            "Processing journal outbox event",
            event_id=event.id,
            event_type=event.event_type,
        )

        if event.event_type == EVENT_TYPE_JOURNAL_EVENT_CREATED:
            return await self._process_journal_created(event)
        if event.event_type == EVENT_TYPE_JOURNAL_EVENT_UPDATED:
            return await self._process_journal_updated(event)
        if event.event_type == EVENT_TYPE_JOURNAL_EVENT_CONFLICTED:
            return await self._process_journal_conflicted(event)
        if event.event_type == EVENT_TYPE_JOURNAL_EVENT_CANCELLED:
            return await self._process_journal_cancelled(event)

        raise JournalOutboxEventProcessingError(
            f"Unknown journal event type: {event.event_type}"
        )

    async def _process_journal_created(self, event: OutboxEvent) -> dict[str, Any]:
        """
        Process a journal_event.created event.

        Creates a new journal, saves calendar info, creates an
        external event link, and syncs contact relationships.
        """
        event_data: dict[str, Any] = event.event_data  # type: ignore
        journal_data = event_data["journal_data"]
        calendar_info_data = event_data["calendar_info_data"]
        external_event_id = event_data["external_event_id"]
        calendar_id = event_data["calendar_id"]
        etag = event_data.get("etag")
        contact_relationships = event_data.get("contact_relationships", [])

        # Build the journal entity
        journal = self._build_journal_from_data(journal_data)

        # Create the journal via service
        created_journal = await self.journal_service.create_journal(
            journal, self.connection
        )

        if created_journal.id is None:
            raise JournalOutboxEventProcessingError("Created journal has no ID")

        # Save calendar info
        await self._save_calendar_info(created_journal.id, calendar_info_data)

        # Create external event link
        await self._create_external_event_link(
            journal_id=created_journal.id,
            calendar_id=UUID(calendar_id),
            external_event_id=external_event_id,
            etag=etag,
        )

        # Sync contact relationships (e.g. invitees)
        await self._sync_contact_relationships(
            journal_id=created_journal.id,
            contact_relationships=contact_relationships,
        )

        # Emit match detection event for the outbox to process asynchronously.
        # We only do this if the match detection dependency is wired (i.e., Gemini is configured).
        if (
            created_journal.event_date_range
            and self.match_candidate_detector is not None
        ):
            detection_event = OutboxEvent.create_match_detection_event(
                journal_id=created_journal.id,
                user_id=created_journal.user_id,
                journal_title=created_journal.title,
                journal_content=created_journal.content or "",
                event_date_range_start=created_journal.event_date_range.start.isoformat(),
                event_date_range_end=created_journal.event_date_range.end.isoformat(),
            )
            await self._save_outbox_event(detection_event)
            logger.info(
                "Emitted match detection event for new journal",
                journal_id=created_journal.id,
            )

        logger.info(
            "Created journal from inbound sync event",
            journal_id=created_journal.id,
            external_event_id=external_event_id,
        )

        return {
            "status": "success",
            "event_type": EVENT_TYPE_JOURNAL_EVENT_CREATED,
            "journal_id": created_journal.id,
            "external_event_id": external_event_id,
        }

    async def _process_journal_updated(self, event: OutboxEvent) -> dict[str, Any]:
        """
        Process a journal_event.updated event.

        Looks up the existing journal, checks for ETag-based idempotency,
        applies InboundFieldMerger to protect local edits, updates the
        journal fields, and updates the external event link.
        """
        event_data: dict[str, Any] = event.event_data  # type: ignore
        journal_data = event_data["journal_data"]
        calendar_info_data = event_data["calendar_info_data"]
        external_event_id = event_data["external_event_id"]
        calendar_id = event_data["calendar_id"]
        etag = event_data.get("etag")
        existing_journal_id = event_data.get("existing_journal_id")
        contact_relationships = event_data.get("contact_relationships", [])

        if existing_journal_id is None:
            raise JournalOutboxEventProcessingError(
                "journal_event.updated requires existing_journal_id"
            )

        # Fetch existing journal
        existing_journal = await self._find_journal_by_id(existing_journal_id)
        if existing_journal is None:
            raise JournalOutboxEventProcessingError(
                f"Journal {existing_journal_id} not found for update"
            )

        # ETag idempotency check — only skip when etag is non-null
        existing_link = await self._find_external_event_link(
            calendar_id=UUID(calendar_id),
            external_event_id=external_event_id,
        )
        if (
            etag is not None
            and existing_link is not None
            and existing_link.external_version == etag
        ):
            logger.info(
                "Journal update skipped - ETag unchanged",
                journal_id=existing_journal_id,
                etag=etag,
            )
            return {
                "status": "skipped",
                "reason": "etag_unchanged",
                "event_type": EVENT_TYPE_JOURNAL_EVENT_UPDATED,
                "journal_id": existing_journal_id,
            }

        # If no external link exists, create one to make ETag tracking
        # and idempotency work on subsequent runs
        if existing_link is None:
            logger.info(
                "No external event link found during update, creating one",
                journal_id=existing_journal_id,
                external_event_id=external_event_id,
            )
            await self._create_external_event_link(
                journal_id=existing_journal_id,
                calendar_id=UUID(calendar_id),
                external_event_id=external_event_id,
                etag=etag,
            )
            # Refetch the link so merge logic sees the correct updated_at
            existing_link = await self._find_external_event_link(
                calendar_id=UUID(calendar_id),
                external_event_id=external_event_id,
            )

        # Apply InboundFieldMerger for protected local edits
        inbound_data = {
            "title": journal_data.get("title", ""),
            "content": journal_data.get("content", ""),
            "event_date_range_start": journal_data.get("event_date_range_start"),
            "event_date_range_end": journal_data.get("event_date_range_end"),
        }

        merged_data = self._merge_fields_with_protection(
            existing_journal=existing_journal,
            inbound_data=inbound_data,
            link_updated_at=existing_link.updated_at if existing_link else None,
        )

        # Build updated journal from merged data
        merged_journal_data = dict(journal_data)
        merged_journal_data["title"] = merged_data["title"]
        merged_journal_data["content"] = merged_data["content"]
        merged_journal_data["event_date_range_start"] = merged_data[
            "event_date_range_start"
        ]
        merged_journal_data["event_date_range_end"] = merged_data[
            "event_date_range_end"
        ]

        updated_journal = self._build_journal_from_data(
            merged_journal_data,
            journal_id=existing_journal_id,
            parent_id=existing_journal.parent_id,
            order=existing_journal.order,
        )

        # Calculate changed fields (including event_date_range)
        changed_fields: dict[str, Any] = {}
        if updated_journal.title != existing_journal.title:
            changed_fields["title"] = (existing_journal.title, updated_journal.title)
        if updated_journal.content != existing_journal.content:
            changed_fields["content"] = (
                existing_journal.content,
                updated_journal.content,
            )
        if updated_journal.event_date_range != existing_journal.event_date_range:
            changed_fields["event_date_range"] = (
                {
                    "start": existing_journal.event_date_range.start.isoformat(),
                    "end": existing_journal.event_date_range.end.isoformat(),
                },
                {
                    "start": updated_journal.event_date_range.start.isoformat(),
                    "end": updated_journal.event_date_range.end.isoformat(),
                },
            )

        # Update via journal service (only if fields actually changed)
        if changed_fields:
            saved_journal = await self.journal_service.update_journal(
                updated_journal, changed_fields, self.connection
            )
        else:
            saved_journal = existing_journal

        # Update calendar info
        if saved_journal.id is not None:
            await self._save_calendar_info(saved_journal.id, calendar_info_data)

        # Update external event link ETag
        await self._update_external_event_link_etag(
            calendar_id=UUID(calendar_id),
            external_event_id=external_event_id,
            etag=etag,
        )

        # Sync contact relationships (e.g. invitees)
        await self._sync_contact_relationships(
            journal_id=existing_journal_id,
            contact_relationships=contact_relationships,
        )

        logger.info(
            "Updated journal from inbound sync event",
            journal_id=saved_journal.id,
            external_event_id=external_event_id,
            changed_fields=list(changed_fields.keys()),
        )

        return {
            "status": "success",
            "event_type": EVENT_TYPE_JOURNAL_EVENT_UPDATED,
            "journal_id": saved_journal.id,
            "external_event_id": external_event_id,
        }

    async def _process_journal_conflicted(self, event: OutboxEvent) -> dict[str, Any]:
        """
        Process a journal_event.conflicted event.

        Marks the external event link as conflicted so users can resolve.
        """
        event_data: dict[str, Any] = event.event_data  # type: ignore
        external_event_id = event_data["external_event_id"]
        calendar_id = event_data["calendar_id"]

        # Mark link as conflicted
        await self.connection.execute(
            text("""
                UPDATE journal_external_event_links
                SET sync_status = 'conflicted',
                    updated_at = :now
                WHERE calendar_id = :calendar_id
                  AND external_event_id = :external_event_id
            """),
            {
                "calendar_id": UUID(calendar_id),
                "external_event_id": external_event_id,
                "now": datetime.now(UTC),
            },
        )

        logger.info(
            "Marked journal event link as conflicted",
            external_event_id=external_event_id,
            calendar_id=calendar_id,
        )

        return {
            "status": "success",
            "event_type": EVENT_TYPE_JOURNAL_EVENT_CONFLICTED,
            "external_event_id": external_event_id,
        }

    async def _process_journal_cancelled(self, event: OutboxEvent) -> dict[str, Any]:
        """
        Process a journal_event.cancelled event.

        Marks the external event link as cancelled and sets the journal's
        event_state to 'cancelled'. Does NOT delete the journal (cancellation-first
        approach per AC2).
        """
        event_data: dict[str, Any] = event.event_data  # type: ignore
        external_event_id = event_data["external_event_id"]
        calendar_id = event_data["calendar_id"]
        existing_journal_id = event_data.get("existing_journal_id")

        if existing_journal_id is None:
            logger.warning(
                "Cancelled event has no existing_journal_id, skipping",
                external_event_id=external_event_id,
            )
            return {
                "status": "skipped",
                "event_type": EVENT_TYPE_JOURNAL_EVENT_CANCELLED,
                "reason": "no_existing_journal_id",
            }

        # Mark link as cancelled
        await self.connection.execute(
            text("""
                UPDATE journal_external_event_links
                SET sync_status = 'cancelled',
                    updated_at = :now
                WHERE calendar_id = :calendar_id
                  AND external_event_id = :external_event_id
            """),
            {
                "calendar_id": UUID(calendar_id),
                "external_event_id": external_event_id,
                "now": datetime.now(UTC),
            },
        )

        # Set journal event_state to cancelled
        await self.connection.execute(
            text("""
                UPDATE journal_calendar_info
                SET event_state = 'cancelled',
                    updated_at = :now
                WHERE journal_id = :journal_id
            """),
            {
                "journal_id": existing_journal_id,
                "now": datetime.now(UTC),
            },
        )

        logger.info(
            "Processed journal cancellation",
            journal_id=existing_journal_id,
            external_event_id=external_event_id,
            calendar_id=calendar_id,
        )

        return {
            "status": "success",
            "event_type": EVENT_TYPE_JOURNAL_EVENT_CANCELLED,
            "journal_id": existing_journal_id,
            "external_event_id": external_event_id,
        }

    # ── Helper methods ──────────────────────────────────────────────────

    @staticmethod
    def _build_journal_from_data(
        journal_data: dict[str, Any],
        journal_id: int | None = None,
        parent_id: int | None = None,
        order: int | None = None,
    ) -> Journal:
        """Build a Journal entity from outbox event payload data."""
        start_str = journal_data.get("event_date_range_start")
        end_str = journal_data.get("event_date_range_end")

        start = datetime.fromisoformat(start_str) if start_str else datetime.now(UTC)
        end = datetime.fromisoformat(end_str) if end_str else start

        return Journal(
            id=journal_id,
            user_id=journal_data["user_id"],
            title=journal_data.get("title", ""),
            content=journal_data.get("content", ""),
            event_date_range=EventDateRange(start=start, end=end),
            parent_id=parent_id,
            order=order,
        )

    @staticmethod
    def _merge_fields_with_protection(
        existing_journal: Journal,
        inbound_data: dict[str, Any],
        link_updated_at: datetime | None,
    ) -> dict[str, Any]:
        """Apply InboundFieldMerger logic: protect local edits.

        If the journal's updated_at is more recent than the link's
        updated_at (used as last_synced_at proxy), then title and content
        are considered locally edited and are preserved. Time fields
        always take inbound values.

        Args:
            existing_journal: Current journal from database
            inbound_data: Inbound data from external event
            link_updated_at: Link's updated_at timestamp (last sync time proxy)

        Returns:
            Merged data dictionary
        """
        # Always-update fields (time fields always take inbound values)
        always_update = {"event_date_range_start", "event_date_range_end"}
        # Protected fields when local edits detected
        protected = {"title", "content"}

        has_local_edits = (
            link_updated_at is not None
            and existing_journal.updated_at is not None
            and existing_journal.updated_at > link_updated_at
        )

        merged: dict[str, Any] = {}

        for key, value in inbound_data.items():
            if key in always_update:
                merged[key] = value
            elif has_local_edits and key in protected:
                # Preserve existing local values
                merged[key] = getattr(existing_journal, key, value)
            else:
                merged[key] = value

        return merged

    async def _save_calendar_info(
        self, journal_id: int, calendar_info_data: dict[str, Any]
    ) -> None:
        """Save calendar info for a journal using raw SQL."""
        calendar_id = UUID(calendar_info_data["calendar_id"])

        start_time = self._parse_time(calendar_info_data.get("start_time"))
        end_time = self._parse_time(calendar_info_data.get("end_time"))
        event_state = calendar_info_data.get("event_state") or "confirmed"

        await self.connection.execute(
            text("""
                INSERT INTO journal_calendar_info
                    (journal_id, calendar_id, is_all_day, location,
                     start_time, end_time, event_state)
                VALUES
                    (:journal_id, :calendar_id, :is_all_day, :location,
                     :start_time, :end_time, :event_state)
                ON CONFLICT (journal_id) DO UPDATE SET
                    calendar_id = :calendar_id,
                    is_all_day = :is_all_day,
                    location = :location,
                    start_time = :start_time,
                    end_time = :end_time,
                    event_state = :event_state,
                    updated_at = :now
            """),
            {
                "journal_id": journal_id,
                "calendar_id": calendar_id,
                "is_all_day": calendar_info_data.get("is_all_day", False),
                "location": calendar_info_data.get("location"),
                "start_time": start_time,
                "end_time": end_time,
                "event_state": event_state,
                "now": datetime.now(UTC),
            },
        )

    @staticmethod
    def _parse_time(value: str | time | None) -> time | None:
        """Parse a time string (HH:MM:SS) into a datetime.time object."""
        if value is None:
            return None
        if isinstance(value, time):
            return value
        return time.fromisoformat(value)

    async def _create_external_event_link(
        self,
        journal_id: int,
        calendar_id: UUID,
        external_event_id: str,
        etag: str | None,
    ) -> None:
        """Create an external event link for tracking sync state.

        Uses ON CONFLICT DO UPDATE so retries of journal_event.created
        don't fail on the composite PK (journal_id, calendar_id).
        """
        now = datetime.now(UTC)
        await self.connection.execute(
            text("""
                INSERT INTO journal_external_event_links
                    (journal_id, calendar_id, external_event_id,
                     external_version,
                     sync_capability, sync_status,
                     created_at, updated_at)
                VALUES
                    (:journal_id, :calendar_id, :external_event_id,
                     :etag,
                     'bidirectional', 'synced',
                     :now, :now)
                ON CONFLICT (journal_id, calendar_id) DO UPDATE SET
                    external_event_id = :external_event_id,
                    external_version = :etag,
                    sync_status = 'synced',
                    updated_at = :now
            """),
            {
                "journal_id": journal_id,
                "calendar_id": calendar_id,
                "external_event_id": external_event_id,
                "etag": etag,
                "now": now,
            },
        )

    async def _find_journal_by_id(self, journal_id: int) -> Journal | None:
        """Find a journal by its ID using raw SQL."""
        result = await self.connection.execute(
            text("""
                SELECT id, user_id, title, content,
                       event_date_range_start, event_date_range_end,
                       parent_id, "order", created_at, updated_at
                FROM journals
                WHERE id = :journal_id
            """),
            {"journal_id": journal_id},
        )
        row = result.fetchone()
        if row is None:
            return None

        return Journal(
            id=row.id,
            user_id=row.user_id,
            title=row.title,
            content=row.content,
            event_date_range=EventDateRange(
                start=row.event_date_range_start,
                end=row.event_date_range_end,
            ),
            parent_id=row.parent_id,
            order=row.order,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def _find_external_event_link(
        self,
        calendar_id: UUID,
        external_event_id: str,
    ) -> Any | None:
        """Find an existing external event link."""
        result = await self.connection.execute(
            text("""
                SELECT external_version, journal_id, sync_capability,
                       sync_status, updated_at
                FROM journal_external_event_links
                WHERE calendar_id = :calendar_id
                  AND external_event_id = :external_event_id
            """),
            {
                "calendar_id": calendar_id,
                "external_event_id": external_event_id,
            },
        )
        return result.fetchone()

    async def _update_external_event_link_etag(
        self,
        calendar_id: UUID,
        external_event_id: str,
        etag: str | None,
    ) -> None:
        """Update the ETag on an external event link after successful sync."""
        await self.connection.execute(
            text("""
                UPDATE journal_external_event_links
                SET external_version = :etag,
                    updated_at = :now,
                    sync_status = 'synced'
                WHERE calendar_id = :calendar_id
                  AND external_event_id = :external_event_id
            """),
            {
                "etag": etag,
                "calendar_id": calendar_id,
                "external_event_id": external_event_id,
                "now": datetime.now(UTC),
            },
        )

    @staticmethod
    def _group_relationships_by_type(
        contact_relationships: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        """Group contact relationship entries by type, filtering missing emails."""
        by_type: dict[str, list[dict[str, Any]]] = {}
        for rel in contact_relationships:
            rel_type = rel.get("relationship_type", "")
            email = rel.get("email", "")
            if rel_type and email:
                by_type.setdefault(rel_type, []).append(rel)
        return by_type

    async def _resolve_emails_to_contact_ids(
        self,
        emails: list[str],
        journal_id: int,
    ) -> dict[str, int]:
        """Resolve a list of emails to contact IDs, skipping unknown emails."""
        resolved: dict[str, int] = {}
        for email in emails:
            contact_id = await self.contact_resolver.resolve_by_email(email)
            if contact_id is not None:
                resolved[email] = contact_id
            else:
                logger.debug(
                    "Invitee email not matched to contact, skipping",
                    email=email,
                    journal_id=journal_id,
                )
        return resolved

    async def _sync_contact_relationships(
        self,
        journal_id: int,
        contact_relationships: list[dict[str, Any]],
    ) -> None:
        """Sync contact relationships for a journal from inbound data.

        For each relationship type in the inbound list, resolves emails to
        contact IDs, then diffs against existing relationships of that type.
        Creates missing relationships and deletes removed ones. Also updates
        status and role fields if they have changed, while respecting manual
        roles. Only mutates the specific relationship_type from the inbound
        data — other types (e.g. PARTICIPANT) are left intact.

        Args:
            journal_id: ID of the journal to sync relationships for
            contact_relationships: List of dicts with 'email',
                'relationship_type', and optional 'status', 'role'
        """
        if contact_relationships is None:
            return

        by_type = self._group_relationships_by_type(contact_relationships)

        for rel_type_str, payloads in by_type.items():
            try:
                rel_type = JournalContactRelationshipType(rel_type_str)
            except ValueError:
                logger.warning(
                    "Unknown relationship type in inbound sync, skipping",
                    relationship_type=rel_type_str,
                    journal_id=journal_id,
                )
                continue

            emails = [p["email"] for p in payloads]
            resolved_contact_ids = await self._resolve_emails_to_contact_ids(
                emails, journal_id
            )

            # Diff against existing relationships of this type
            existing = await self._get_relationships_by_type(journal_id, rel_type)
            existing_by_contact_id = {r.contact_id: r for r in existing}

            # Prepare operations
            to_create: list[tuple[int, str | None, str | None]] = []
            to_update: list[tuple[int, str | None, str | None]] = []

            resolved_contact_id_set = set(resolved_contact_ids.values())
            to_delete = set(existing_by_contact_id.keys()) - resolved_contact_id_set

            for inbound_payload in payloads:
                email = inbound_payload["email"]
                if email not in resolved_contact_ids:
                    continue

                contact_id = resolved_contact_ids[email]
                inbound_status = inbound_payload.get("status")
                inbound_role = inbound_payload.get("role")

                existing_rel = existing_by_contact_id.get(contact_id)
                if not existing_rel:
                    to_create.append((contact_id, inbound_status, inbound_role))
                else:
                    changed = False

                    # Compute new status
                    new_status = (
                        existing_rel.status.value if existing_rel.status else None
                    )
                    if inbound_status and new_status != inbound_status:
                        new_status = inbound_status
                        changed = True

                    # Compute new role
                    new_role = existing_rel.role.value if existing_rel.role else None
                    if inbound_role:
                        if new_role != inbound_role:
                            new_role = inbound_role
                            changed = True
                    elif (
                        inbound_role is None
                        and new_role == ContactEventRole.ORGANISER.value
                    ):
                        # If inbound has None, but existing has ORGANISER, we demote.
                        # This ensures that if the Google user is no longer organizer, it resets.
                        new_role = None
                        changed = True

                    if changed:
                        to_update.append((contact_id, new_status, new_role))

            for contact_id, status, role in to_create:
                await self._create_contact_relationship(
                    journal_id, contact_id, rel_type, status, role
                )

            for contact_id, status, role in to_update:
                await self._update_contact_relationship(
                    journal_id, contact_id, rel_type, status, role
                )

            for contact_id in to_delete:
                await self._delete_contact_relationship(
                    journal_id, contact_id, rel_type
                )

            if to_create or to_update or to_delete:
                logger.info(
                    "Synced contact relationships",
                    journal_id=journal_id,
                    relationship_type=rel_type_str,
                    created=len(to_create),
                    updated=len(to_update),
                    deleted=len(to_delete),
                )

    async def _get_relationships_by_type(
        self,
        journal_id: int,
        relationship_type: JournalContactRelationshipType,
    ) -> list[JournalContactRelationship]:
        """Get all relationships of a specific type for a journal."""
        result = await self.connection.execute(
            text("""
                SELECT journal_id, contact_id, relationship_type, created_at, status, role
                FROM journal_contact_relationships
                WHERE journal_id = :journal_id
                  AND relationship_type = :relationship_type
            """),
            {
                "journal_id": journal_id,
                "relationship_type": relationship_type.value,
            },
        )
        return [
            JournalContactRelationship(
                journal_id=row.journal_id,
                contact_id=row.contact_id,
                relationship_type=JournalContactRelationshipType(row.relationship_type),
                status=AttendeeStatus(row.status) if row.status else None,
                role=ContactEventRole(row.role) if row.role else None,
                created_at=row.created_at,
            )
            for row in result.fetchall()
        ]

    async def _create_contact_relationship(
        self,
        journal_id: int,
        contact_id: int,
        relationship_type: JournalContactRelationshipType,
        status: str | None = None,
        role: str | None = None,
    ) -> None:
        """Create a journal-contact relationship."""
        await self.connection.execute(
            text("""
                INSERT INTO journal_contact_relationships
                    (journal_id, contact_id, relationship_type, status, role)
                VALUES
                    (:journal_id, :contact_id, :relationship_type, :status, :role)
                ON CONFLICT DO NOTHING
            """),
            {
                "journal_id": journal_id,
                "contact_id": contact_id,
                "relationship_type": relationship_type.value,
                "status": status,
                "role": role,
            },
        )

    async def _update_contact_relationship(
        self,
        journal_id: int,
        contact_id: int,
        relationship_type: JournalContactRelationshipType,
        status: str | None = None,
        role: str | None = None,
    ) -> None:
        """Update an existing journal-contact relationship's status and role."""
        await self.connection.execute(
            text("""
                UPDATE journal_contact_relationships
                SET status = :status,
                    role = :role
                WHERE journal_id = :journal_id
                  AND contact_id = :contact_id
                  AND relationship_type = :relationship_type
            """),
            {
                "journal_id": journal_id,
                "contact_id": contact_id,
                "relationship_type": relationship_type.value,
                "status": status,
                "role": role,
            },
        )

    async def _delete_contact_relationship(
        self,
        journal_id: int,
        contact_id: int,
        relationship_type: JournalContactRelationshipType,
    ) -> None:
        """Delete a journal-contact relationship."""
        await self.connection.execute(
            text("""
                DELETE FROM journal_contact_relationships
                WHERE journal_id = :journal_id
                  AND contact_id = :contact_id
                  AND relationship_type = :relationship_type
            """),
            {
                "journal_id": journal_id,
                "contact_id": contact_id,
                "relationship_type": relationship_type.value,
            },
        )

    async def _save_outbox_event(self, event: OutboxEvent) -> None:
        """Save a new outbox event within the current transaction.

        Detection event is handled in MatchDetectionEventProcessor.
        This ensures the match detection event is committed atomically
        with the journal creation.

        Args:
            event: OutboxEvent to persist
        """
        import json
        from datetime import datetime
        from uuid import uuid4

        now = datetime.utcnow()
        await self.connection.execute(
            text("""
                INSERT INTO outbox_events
                (event_id, event_type, aggregate_id, event_data, occurred_at, retry_count, created_at)
                VALUES (:event_id, :event_type, :aggregate_id, :event_data, :occurred_at, :retry_count, :created_at)
            """),
            {
                "event_id": str(uuid4()),
                "event_type": event.event_type,
                "aggregate_id": event.aggregate_id,
                "event_data": json.dumps(event.event_data),
                "occurred_at": now,
                "retry_count": 0,
                "created_at": now,
            },
        )
