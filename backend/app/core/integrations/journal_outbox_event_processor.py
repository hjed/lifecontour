"""
Journal Outbox Event Processor for handling inbound journal sync events.

Processes journal_event.created, journal_event.updated,
journal_event.conflicted, and journal_event.cancelled outbox events
from integration workers to create/update journals in the core system.
"""

from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import UUID

import structlog
from core_shared.models.history import Provenance
from core_shared.models.journal_external_event_link import (
    ExternalEventLinkSyncStatus,
)
from core_shared.models.journals import (
    AttendeeStatus,
    ContactEventRole,
    EventDateRange,
    FitnessData,
    Journal,
    JournalHasAnchoredTasksError,
)
from core_shared.models.journals.event_state import EventState
from core_shared.models.journals.gear_maintenance_data import GearMaintenanceData
from core_shared.models.journals.journal_contact_relationship import (
    JournalContactRelationship,
)
from core_shared.models.journals.journal_relationship_types import (
    JournalContactRelationshipType,
)
from core_shared.models.journals.journal_types import JournalType
from core_shared.models.journals.review_item import ReviewItem, ReviewReason
from core_shared.models.outbox import OutboxEvent
from core_shared.models.outbox_events import (
    JournalSeriesCancelledEventData,
    JournalStatusEventData,
    JournalSyncEventData,
)
from core_shared.models.route import Route
from core_shared.models.strava_athlete_mapping import StravaAthleteMapping
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_repository import SqlContactRepository
from app.core.integrations.adapters.sql.journal_event_link_repository import (
    SeriesLinkedJournal,
    SqlJournalEventLinkRepository,
)
from app.core.integrations.adapters.sql.strava_athlete_mapping_repository import (
    SqlStravaAthleteMappingRepository,
)
from app.core.integrations.adapters.sql.sync_metadata_repository import (
    SyncMetadataRepository,
)
from app.core.journal.adapters.sql import SqlFitnessDataRepository
from app.core.journal.adapters.sql.gear_maintenance_data_repository import (
    SqlGearMaintenanceDataRepository,
)
from app.core.journal.adapters.sql.journal_series_repository import (
    SqlJournalSeriesRepository,
)
from app.core.journal.adapters.sql.review_item_repository import (
    SqlReviewItemRepository,
)
from app.core.journal.adapters.sql.route_repository import SqlRouteRepository
from app.core.journal.services.journal_service import JournalService
from app.infrastructure.unit_of_work import savepoint

logger = structlog.get_logger()

# Event type constants
EVENT_TYPE_JOURNAL_EVENT_CREATED = "journal_event.created"
EVENT_TYPE_JOURNAL_EVENT_UPDATED = "journal_event.updated"
EVENT_TYPE_JOURNAL_EVENT_CONFLICTED = "journal_event.conflicted"
EVENT_TYPE_JOURNAL_EVENT_CANCELLED = "journal_event.cancelled"
EVENT_TYPE_JOURNAL_EVENT_SERIES_CANCELLED = "journal_event.series_cancelled"
EVENT_TYPE_JOURNAL_REVIEW_DETECT_MATCHES = "journal_review.detect_matches"

# Buffer around "now" for recurring-cancellation decisions, mirroring the
# worker's past-event skip buffer (all-day events are midnight-normalised).
_SERIES_DELETION_BUFFER = timedelta(days=1)

# Maps an inbound sync event's integration_source to the history Provenance
# recorded for the journal changes it produces.
_PROVENANCE_BY_INTEGRATION_SOURCE: dict[str, Provenance] = {
    "strava": Provenance.STRAVA,
    "google": Provenance.GOOGLE_CALENDAR,
}


def _provenance_for_source(integration_source: str | None) -> Provenance:
    """Resolve the history Provenance for an inbound integration source."""
    if not integration_source:
        return Provenance.SYSTEM
    return _PROVENANCE_BY_INTEGRATION_SOURCE.get(integration_source, Provenance.SYSTEM)


# Mapping from JournalType value to the database table name for types that
# need a default data row.  FITNESS is handled separately via
# SqlFitnessDataRepository, and EVENT/NOTE have no standalone data table.
_TYPE_DATA_TABLE_MAP: dict[str, str] = {
    JournalType.OUTDOOR_ACTIVITY.value: "journal_outdoor_activity_data",
    JournalType.BUSHWALKING.value: "journal_bushwalking_data",
    JournalType.JOGGING.value: "journal_jogging_data",
    JournalType.ABSEILING_TRIP.value: "journal_abseiling_data",
    JournalType.CANYONING.value: "journal_canyoning_data",
    JournalType.CLIMBING.value: "journal_climbing_data",
    JournalType.KAYAKING.value: "journal_kayaking_data",
    JournalType.CROSS_COUNTRY_SKIING.value: "journal_skiing_data",
    JournalType.CAVING.value: "journal_caving_data",
    JournalType.CANOEING.value: "journal_canoeing_data",
    JournalType.SNORKELLING.value: "journal_snorkelling_data",
    JournalType.DIVING.value: "journal_diving_data",
    JournalType.DOWNHILL_SKIING.value: "journal_downhill_skiing_data",
    JournalType.OUTDOOR_PLANNING.value: "journal_outdoor_planning_data",
    JournalType.OUTDOOR_TRAINING.value: "journal_outdoor_training_data",
}


class JournalOutboxEventProcessingError(Exception):
    """Raised when journal outbox event processing fails."""


class OutboxFitnessData(BaseModel):
    """Strongly-typed Pydantic model for fitness data in outbox event payloads.

    Validates the shape of ``fitness_data`` dicts from integration workers
    before persisting through the repository layer.
    """

    distance: int | None = Field(default=None, description="Distance in metres")
    elevation_gain: int | None = Field(
        default=None, description="Elevation gain in metres"
    )
    elevation_loss: int | None = Field(
        default=None, description="Elevation loss in metres"
    )
    duration: int | None = Field(default=None, description="Duration in seconds")
    calories: int | None = Field(default=None, description="Calories burned")
    heart_rate_avg: int | None = Field(
        default=None, description="Average heart rate BPM"
    )
    heart_rate_max: int | None = Field(default=None, description="Max heart rate BPM")
    strava_activity_id: str | None = Field(
        default=None, description="Strava activity ID"
    )


class OutboxRouteData(BaseModel):
    """Strongly-typed Pydantic model for GPX route data in outbox event payloads."""

    gpx_xml: str = Field(description="Raw GPX XML string")
    title: str = Field(
        default="Imported Route",
        max_length=200,
        description="Route name, usually derived from activity title",
    )


class OutboxSyncData(BaseModel):
    """Strongly-typed Pydantic model for Sync Metadata in outbox event payloads."""

    strava_activity_id: str = Field(
        min_length=1, description="Strava activity ID used as external_id"
    )
    version_hash: str = Field(
        min_length=1,
        max_length=255,
        description="Hash of mutable fields for change detection",
    )


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
        contact_repository: SqlContactRepository,
        strava_athlete_mapping_repository: SqlStravaAthleteMappingRepository,
        match_candidate_detector: Any = None,
    ) -> None:
        """
        Initialize the journal outbox event processor.

        Args:
            journal_service: Service for journal operations
            connection: Database connection for transactions
            contact_repository: Repository for contacts
            strava_athlete_mapping_repository: Repository for strava mappings
            match_candidate_detector: Optional detector for match candidates
        """
        self.journal_service = journal_service
        self.connection = connection
        self.contact_repository = contact_repository
        self.strava_athlete_mapping_repository = strava_athlete_mapping_repository
        self.contact_resolver = ContactResolver(connection)
        self.match_candidate_detector = match_candidate_detector
        self.link_repo = SqlJournalEventLinkRepository(connection)
        self.series_repo = SqlJournalSeriesRepository(connection)
        self.review_item_repo = SqlReviewItemRepository(connection)

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
        if event.event_type == EVENT_TYPE_JOURNAL_EVENT_SERIES_CANCELLED:
            return await self._process_journal_series_cancelled(event)

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
        payload = JournalSyncEventData.model_validate(event_data)
        journal_data = payload.journal_data
        calendar_info_data = payload.calendar_info_data
        external_event_id = payload.external_event_id
        calendar_id = payload.calendar_id
        etag = payload.etag
        contact_relationships = payload.contact_relationships

        # Ensure the calendar row exists (e.g. synthetic Strava calendar)
        await self._ensure_calendar_exists(
            calendar_id=UUID(calendar_id),
            user_id=journal_data["user_id"],
            integration_source=payload.integration_source,
        )

        # Check for existing link to prevent duplicates (e.g. from retries)
        existing_link = await self._find_external_event_link(
            calendar_id=UUID(calendar_id),
            external_event_id=external_event_id,
        )
        if existing_link is not None:
            logger.info(
                "External event link already exists for CREATE, treating as UPDATE",
                external_event_id=external_event_id,
                calendar_id=calendar_id,
                existing_journal_id=existing_link.journal_id,
            )
            event.event_data["existing_journal_id"] = existing_link.journal_id
            return await self._process_journal_updated(event)

        # The same real-world event can reach us from more than one calendar
        # — one calendar invites another, and each returns its own copy under
        # its own event id, so the lookup above cannot match them. The source
        # tells us they are the same thing by giving both copies one
        # identity token; a journal already carrying it is this event's
        # journal, and this calendar wants a link to it rather than a
        # duplicate of it.
        #
        # The worker normally spots this and sends an update, so reaching
        # here means the two copies were emitted before either was
        # processed — the first sync, where neither had a link yet. This is
        # what makes that race converge on one journal.
        journal_id_for_identity = await self._find_journal_by_external_identity(
            user_id=journal_data["user_id"],
            external_identity=payload.external_identity,
        )
        if journal_id_for_identity is not None:
            logger.info(
                "Event already journalled under another calendar, "
                "linking instead of duplicating",
                external_event_id=external_event_id,
                calendar_id=calendar_id,
                existing_journal_id=journal_id_for_identity,
            )
            event.event_data["existing_journal_id"] = journal_id_for_identity
            return await self._process_journal_updated(event)

        # Build the journal entity
        journal = self._build_journal_from_data(journal_data)

        # Create the journal via service
        provenance = _provenance_for_source(payload.integration_source)
        created_journal = await self.journal_service.create_journal(
            journal,
            self.connection,
            changed_by=payload.integration_source or "system",
            source=provenance,
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
            recurring_event_id=payload.recurring_event_id,
            external_identity=payload.external_identity,
        )

        # Auto-link recurring instances into a journal series
        await self._ensure_series_membership(
            journal_id=created_journal.id,
            user_id=created_journal.user_id,
            calendar_id=UUID(calendar_id),
            recurring_event_id=payload.recurring_event_id,
            series_name=created_journal.title,
        )

        # Sync contact relationships (e.g. invitees)
        await self._sync_contact_relationships(
            journal_id=created_journal.id,
            contact_relationships=contact_relationships,
        )

        # Save fitness data and journal types if present (Strava-sourced events)
        await self._persist_fitness_and_types(created_journal.id, journal_data)

        # Save GPX route if present (Strava-sourced events with GPS data)
        await self._persist_route_from_gpx(created_journal.id, journal_data)

        # Update Strava athletes if present
        await self._persist_strava_athletes(
            created_journal.id, created_journal.user_id, journal_data
        )

        # Save sync metadata for integration tracking (Strava-sourced events)
        await self._persist_sync_metadata(
            journal_id=created_journal.id,
            event_data=payload.model_dump(),
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
        payload = JournalSyncEventData.model_validate(event_data)
        journal_data = payload.journal_data
        calendar_info_data = payload.calendar_info_data
        external_event_id = payload.external_event_id
        calendar_id = payload.calendar_id
        etag = payload.etag
        existing_journal_id = payload.existing_journal_id
        contact_relationships = payload.contact_relationships

        if existing_journal_id is None:
            raise JournalOutboxEventProcessingError(
                "journal_event.updated requires existing_journal_id"
            )

        # Ensure the calendar row exists (e.g. synthetic Strava calendar)
        await self._ensure_calendar_exists(
            calendar_id=UUID(calendar_id),
            user_id=journal_data["user_id"],
            integration_source=payload.integration_source,
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
            # Backfill promotion: the worker re-sends unchanged events whose
            # link predates the series feature, carrying the SAME etag. The
            # recurring id and series membership must persist before the skip
            # or the worker re-promotes the instance on every sync, forever.
            if payload.recurring_event_id and existing_link.recurring_event_id is None:
                await self._update_external_event_link_etag(
                    calendar_id=UUID(calendar_id),
                    external_event_id=external_event_id,
                    etag=etag,
                    recurring_event_id=payload.recurring_event_id,
                )
                await self._ensure_series_membership(
                    journal_id=existing_journal_id,
                    user_id=existing_journal.user_id,
                    calendar_id=UUID(calendar_id),
                    recurring_event_id=payload.recurring_event_id,
                    series_name=existing_journal.title,
                )
                logger.info(
                    "Backfilled recurring id on unchanged event",
                    journal_id=existing_journal_id,
                    recurring_event_id=payload.recurring_event_id,
                )
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
                recurring_event_id=payload.recurring_event_id,
                external_identity=payload.external_identity,
            )
            # Refetch the link so merge logic sees the correct updated_at
            existing_link = await self._find_external_event_link(
                calendar_id=UUID(calendar_id),
                external_event_id=external_event_id,
            )

        # Apply InboundFieldMerger for protected local edits
        inbound_data: dict[str, Any] = {
            "title": journal_data.get("title", ""),
            "event_date_range_start": journal_data.get("event_date_range_start"),
            "event_date_range_end": journal_data.get("event_date_range_end"),
        }
        if "content" in journal_data:
            inbound_data["content"] = journal_data["content"]

        # When private_description is enabled, block inbound content changes
        # to prevent external calendar descriptions overwriting local journal notes.
        # We replace the inbound value with the existing journal content (rather than
        # removing the key) so that merged_data always contains "content".
        existing_calendar_info = await self._find_calendar_info(existing_journal_id)
        if existing_calendar_info and existing_calendar_info.private_description:
            inbound_data["content"] = existing_journal.content or ""
            logger.debug(
                "Blocking inbound content update due to private_description",
                journal_id=existing_journal_id,
            )

        merged_data = self._merge_fields_with_protection(
            existing_journal=existing_journal,
            inbound_data=inbound_data,
            link_updated_at=existing_link.updated_at if existing_link else None,
        )

        # Build updated journal from merged data
        merged_journal_data = dict(journal_data)
        merged_journal_data["title"] = merged_data.get("title", existing_journal.title)
        merged_journal_data["content"] = merged_data.get(
            "content", existing_journal.content or ""
        )
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

        # Skip a no-op inbound sync entirely so it produces no event/history;
        # when something changed, JournalService computes the field-level
        # changed_fields by diffing the persisted journal against updated_journal.
        fields_changed = (
            updated_journal.title != existing_journal.title
            or updated_journal.content != existing_journal.content
            or updated_journal.event_date_range != existing_journal.event_date_range
        )
        if fields_changed:
            provenance = _provenance_for_source(payload.integration_source)
            saved_journal = await self.journal_service.update_journal(
                updated_journal,
                self.connection,
                changed_by=payload.integration_source or "system",
                source=provenance,
            )
        else:
            saved_journal = existing_journal

        # Update calendar info
        if saved_journal.id is not None:
            await self._save_calendar_info(saved_journal.id, calendar_info_data)

        # Update external event link ETag (and backfill the recurring id)
        await self._update_external_event_link_etag(
            calendar_id=UUID(calendar_id),
            external_event_id=external_event_id,
            etag=etag,
            recurring_event_id=payload.recurring_event_id,
            external_identity=payload.external_identity,
        )

        # Surface any journal that turns out to describe the same event
        await self._flag_duplicate_journals(
            journal_id=existing_journal_id,
            user_id=existing_journal.user_id,
            external_identity=payload.external_identity,
        )

        # Auto-link recurring instances into a journal series (backfill path)
        await self._ensure_series_membership(
            journal_id=existing_journal_id,
            user_id=existing_journal.user_id,
            calendar_id=UUID(calendar_id),
            recurring_event_id=payload.recurring_event_id,
            series_name=saved_journal.title,
        )

        # Sync contact relationships (e.g. invitees)
        await self._sync_contact_relationships(
            journal_id=existing_journal_id,
            contact_relationships=contact_relationships,
        )

        # Update fitness data and journal types if present (Strava-sourced events)
        await self._persist_fitness_and_types(existing_journal_id, journal_data)

        # Update GPX route if present (Strava-sourced events with GPS data)
        await self._persist_route_from_gpx(existing_journal_id, journal_data)

        # Update Strava athletes if present
        user_id = existing_journal.user_id
        await self._persist_strava_athletes(existing_journal_id, user_id, journal_data)

        # Update sync metadata for integration tracking (Strava-sourced events)
        await self._persist_sync_metadata(
            journal_id=existing_journal_id,
            event_data=payload.model_dump(),
        )

        logger.info(
            "Updated journal from inbound sync event",
            journal_id=saved_journal.id,
            external_event_id=external_event_id,
            fields_changed=fields_changed,
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
        payload = JournalStatusEventData.model_validate(event_data)
        external_event_id = payload.external_event_id
        calendar_id = payload.calendar_id

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

        Far-future instances of a recurring series are deleted outright when
        untouched locally (unbounded series shouldn't leave stale journals
        behind). Everything else keeps the cancellation-first approach per AC2:
        the link is marked cancelled and the journal's event_state set to
        'cancelled' without deleting the journal.
        """
        event_data: dict[str, Any] = event.event_data  # type: ignore
        payload = JournalStatusEventData.model_validate(event_data)
        external_event_id = payload.external_event_id
        calendar_id = payload.calendar_id
        existing_journal_id = payload.existing_journal_id

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

        # Recurring-instance deletion path: the payload's recurring id (new
        # worker) or the backfilled link column (old payloads) marks the
        # instance as part of a series.
        linked = await self.link_repo.find_by_external_event(
            calendar_id=UUID(calendar_id),
            external_event_id=external_event_id,
        )
        recurring_event_id = payload.recurring_event_id or (
            linked.recurring_event_id if linked else None
        )
        if (
            linked is not None
            and recurring_event_id
            and await self._should_delete_cancelled_instance(linked)
        ):
            # A task anchored to the instance refuses the deletion. Falling
            # through to the marking below is the right answer and not a
            # failure — it is what an instance the protection facts protect
            # already gets, and failing here would retry the event forever over
            # a state that is not going to change. The SAVEPOINT takes back the
            # external links the attempt removed on its way.
            deleted = True
            try:
                async with savepoint(self.connection):
                    await self._delete_cancelled_instance(
                        linked, integration_source=payload.integration_source
                    )
            except JournalHasAnchoredTasksError:
                deleted = False
                logger.info(
                    "Cancelled instance kept: tasks are anchored to it",
                    journal_id=existing_journal_id,
                    external_event_id=external_event_id,
                )

            if deleted:
                return {
                    "status": "success",
                    "event_type": EVENT_TYPE_JOURNAL_EVENT_CANCELLED,
                    "journal_id": existing_journal_id,
                    "external_event_id": external_event_id,
                    "action": "deleted",
                }

        await self._mark_journal_cancelled(
            journal_id=existing_journal_id,
            calendar_id=UUID(calendar_id),
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

    async def _process_journal_series_cancelled(
        self, event: OutboxEvent
    ) -> dict[str, Any]:
        """
        Process a journal_event.series_cancelled event.

        Emitted when a whole recurring series is deleted upstream (Google
        reports a single cancelled event carrying the master id). Fans out
        over every journal linked to the series: far-future untouched
        instances are deleted, near/current ones are marked cancelled, and
        already-finished ones are left alone. One failing journal doesn't
        poison the rest.
        """
        event_data: dict[str, Any] = event.event_data  # type: ignore
        payload = JournalSeriesCancelledEventData.model_validate(event_data)
        calendar_id = UUID(payload.calendar_id)
        now = datetime.now(UTC)

        linked_journals = await self.link_repo.find_journals_for_series(
            calendar_id=calendar_id,
            recurring_event_id=payload.recurring_event_id,
        )

        deleted = 0
        cancelled = 0
        skipped_past = 0
        errors = 0
        for linked in linked_journals:
            try:
                # Already happened — mirrors the worker's past-event skip.
                # Falls back to the start when the end date is missing.
                range_end = linked.event_date_range_end or linked.event_date_range_start
                if range_end is not None and range_end < now - _SERIES_DELETION_BUFFER:
                    skipped_past += 1
                    continue
                # SAVEPOINT per item so a failure mid-item (e.g. after the
                # link deletion but before the journal delete) rolls back
                # cleanly and the loop continues with the rest.
                async with savepoint(self.connection):
                    if await self._should_delete_cancelled_instance(linked):
                        await self._delete_cancelled_instance(
                            linked, integration_source=payload.integration_source
                        )
                        deleted += 1
                    else:
                        await self._mark_journal_cancelled(
                            journal_id=linked.journal_id,
                            calendar_id=calendar_id,
                        )
                        cancelled += 1
            except JournalHasAnchoredTasksError:
                # A far-future instance is exactly the profile of a task's due
                # journal, and a user's commitment outranks a sync tidy-up. The
                # instance is marked cancelled instead — the same outcome as a
                # journal the deletion heuristics protect, and the very escape
                # hatch the delete guard steers users toward. The savepoint
                # rolled the attempt back, so its external links are intact.
                logger.info(
                    "Series-cancelled instance kept: tasks are anchored to it",
                    journal_id=linked.journal_id,
                    recurring_event_id=payload.recurring_event_id,
                )
                async with savepoint(self.connection):
                    await self._mark_journal_cancelled(
                        journal_id=linked.journal_id,
                        calendar_id=calendar_id,
                    )
                cancelled += 1
            except Exception:
                errors += 1
                logger.exception(
                    "Failed to process series-cancelled journal, continuing",
                    journal_id=linked.journal_id,
                    recurring_event_id=payload.recurring_event_id,
                )

        logger.info(
            "Processed series cancellation",
            calendar_id=payload.calendar_id,
            recurring_event_id=payload.recurring_event_id,
            deleted=deleted,
            cancelled=cancelled,
            skipped_past=skipped_past,
            errors=errors,
        )

        # Every item was attempted (failed ones rolled back to their
        # savepoints); fail the event so the consumer retries it — the whole
        # fan-out is idempotent, and a success ack would silently drop the
        # journals that errored.
        if errors:
            raise JournalOutboxEventProcessingError(
                f"Series cancellation for {payload.recurring_event_id}: "
                f"{errors} of {len(linked_journals)} journals failed; "
                "failing the event for retry"
            )

        return {
            "status": "success",
            "event_type": EVENT_TYPE_JOURNAL_EVENT_SERIES_CANCELLED,
            "deleted": deleted,
            "cancelled": cancelled,
            "skipped_past": skipped_past,
            "errors": errors,
        }

    async def _should_delete_cancelled_instance(
        self, linked: SeriesLinkedJournal
    ) -> bool:
        """Whether a cancelled recurring instance should be deleted outright.

        Only instances starting more than a day ahead qualify, and any local
        additions (edits after the last sync, children, tags, type data,
        routes, or non-invitee contact links) protect the journal — it falls
        back to mark-cancelled.

        A link already marked cancelled keeps its earlier keep decision:
        _mark_journal_cancelled bumps the link's updated_at, erasing the
        edit-protection signal, so re-evaluating on event redelivery (or a
        repeated upstream cancellation) could delete a journal that was
        protected the first time.
        """
        if linked.link_sync_status == ExternalEventLinkSyncStatus.CANCELLED.value:
            return False
        # A de-duplicated event is one journal several calendars link to.
        # Deleting it because one calendar dropped the instance would take
        # the other calendars' links with it (ON DELETE CASCADE) and lose an
        # event they still hold.
        if await self._has_other_live_links(linked.journal_id, linked.calendar_id):
            return False
        if linked.event_date_range_start is None:
            return False
        if linked.event_date_range_start <= datetime.now(UTC) + _SERIES_DELETION_BUFFER:
            return False
        if linked.link_updated_at is None or linked.journal_updated_at is None:
            return False
        if linked.journal_updated_at > linked.link_updated_at:
            return False
        facts = await self.link_repo.get_deletion_protection_facts(linked.journal_id)
        return not facts.is_protected

    async def _delete_cancelled_instance(
        self,
        linked: SeriesLinkedJournal,
        integration_source: str | None,
    ) -> None:
        """Delete a far-future recurring instance whose series was cancelled.

        The external event links are removed first so the JournalDeleted event
        carries no external identifiers — the upstream event is already gone,
        and an outbound deletion attempt would only fail.
        """
        await self.link_repo.delete_links_for_journal(linked.journal_id)
        await self.journal_service.delete_journal(
            linked.journal_id,
            self.connection,
            changed_by=integration_source or "system",
            source=_provenance_for_source(integration_source),
        )
        logger.info(
            "Deleted far-future recurring instance from cancelled series",
            journal_id=linked.journal_id,
            external_event_id=linked.external_event_id,
        )

    async def _mark_journal_cancelled(
        self,
        journal_id: int,
        calendar_id: UUID,
    ) -> None:
        """Mark a journal's link and calendar info as cancelled (no deletion).

        The link UPDATE keys on the composite PK (journal_id, calendar_id) —
        never on external_event_id, which is nullable (NULL = NULL is false
        in SQL and would silently leave the link 'synced').

        **Both states are bound from their enums**, because both are read back
        to decide something and a literal that drifted would change behaviour
        with nothing failing:

        - ``event_state`` is what ``find_cancelled_journal_ids`` matches on, so
          a drifted write would un-lapse every task whose due journal was
          cancelled, silently.
        - ``sync_status`` is what ``_should_delete_cancelled_instance`` checks
          first — a link already ``cancelled`` keeps its earlier keep decision,
          because this method bumps ``updated_at`` and erases the
          edit-protection signal. A drifted write would let a redelivered
          cancellation delete a journal that was protected on the first pass.

        The ``'synced'`` writes elsewhere in this processor are still literals;
        converting those is a tidy-up of its own and no cancellation decision
        reads them.

        **The journal is only cancelled once no calendar still holds the
        event.** A de-duplicated event is one journal linked to several
        calendars, so removing it from one of them says nothing about the
        others — declining a meeting on a personal calendar must not cancel
        the copy still sitting on a work calendar. The link is always marked;
        the journal follows only when the last one goes.
        """
        await self.connection.execute(
            text("""
                UPDATE journal_external_event_links
                SET sync_status = :sync_status,
                    updated_at = :now
                WHERE journal_id = :journal_id
                  AND calendar_id = :calendar_id
            """),
            {
                "journal_id": journal_id,
                "calendar_id": calendar_id,
                "sync_status": ExternalEventLinkSyncStatus.CANCELLED.value,
                "now": datetime.now(UTC),
            },
        )

        if await self._has_live_links(journal_id):
            logger.info(
                "Link cancelled but the event lives on in another calendar",
                journal_id=journal_id,
                calendar_id=str(calendar_id),
            )
            return

        await self.connection.execute(
            text("""
                UPDATE journal_calendar_info
                SET event_state = :event_state,
                    updated_at = :now
                WHERE journal_id = :journal_id
            """),
            {
                "journal_id": journal_id,
                "event_state": EventState.CANCELLED.value,
                "now": datetime.now(UTC),
            },
        )

    async def _has_other_live_links(self, journal_id: int, calendar_id: UUID) -> bool:
        """Whether a calendar *other than this one* still holds the event.

        Asked before the cancelled link has been marked, so this one is
        excluded explicitly rather than by its status.
        """
        result = await self.connection.execute(
            text("""
                SELECT 1
                FROM journal_external_event_links
                WHERE journal_id = :journal_id
                  AND calendar_id <> :calendar_id
                  AND sync_status <> :cancelled
                LIMIT 1
            """),
            {
                "journal_id": journal_id,
                "calendar_id": calendar_id,
                "cancelled": ExternalEventLinkSyncStatus.CANCELLED.value,
            },
        )
        return result.fetchone() is not None

    async def _has_live_links(self, journal_id: int) -> bool:
        """Whether any calendar still holds this event.

        Read after the cancelled link has been marked, so a lone link that
        was just cancelled correctly reports nothing live.
        """
        result = await self.connection.execute(
            text("""
                SELECT 1
                FROM journal_external_event_links
                WHERE journal_id = :journal_id
                  AND sync_status <> :cancelled
                LIMIT 1
            """),
            {
                "journal_id": journal_id,
                "cancelled": ExternalEventLinkSyncStatus.CANCELLED.value,
            },
        )
        return result.fetchone() is not None

    async def _is_display_calendar(self, journal_id: int, calendar_id: UUID) -> bool:
        """Whether this is the calendar the journal is displayed in.

        A journal holds exactly one ``journal_calendar_info`` row; the other
        calendars linked to it hold the same event but do not own the
        journal.
        """
        result = await self.connection.execute(
            text("""
                SELECT 1
                FROM journal_calendar_info
                WHERE journal_id = :journal_id
                  AND calendar_id = :calendar_id
            """),
            {"journal_id": journal_id, "calendar_id": calendar_id},
        )
        return result.fetchone() is not None

    async def _ensure_series_membership(
        self,
        journal_id: int,
        user_id: str,
        calendar_id: UUID,
        recurring_event_id: str | None,
        series_name: str,
    ) -> None:
        """Link a synced recurring instance into its journal series.

        Get-or-creates the series keyed by (calendar_id, recurring_event_id) —
        named after the event on first creation, never renamed by sync — and
        adds the journal as a member (idempotent). No-op for non-recurring
        events.

        **Only the journal's display calendar establishes a series.** A
        recurring event held by two calendars is one journal per instance,
        but each calendar names the series after its own master id — so
        letting the second one through would key a second series on
        ``(its calendar, its master id)`` and leave the user two series for
        one weekly meeting, both listing the same journals. Same rule as the
        calendar assignment itself: the calendar the journal is displayed in
        owns it, and the others contribute a link and nothing more.
        """
        if not recurring_event_id:
            return
        if not await self._is_display_calendar(journal_id, calendar_id):
            logger.info(
                "Skipping series membership: not the journal's calendar",
                journal_id=journal_id,
                calendar_id=str(calendar_id),
            )
            return
        series = await self.series_repo.get_or_create_by_recurrence(
            user_id=user_id,
            calendar_id=calendar_id,
            recurring_event_id=recurring_event_id,
            name=series_name,
        )
        if series.id is not None:
            await self.series_repo.add_member(series.id, journal_id)

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

    async def _persist_fitness_and_types(
        self, journal_id: int, journal_data: dict[str, Any]
    ) -> None:
        """Persist fitness data and journal types from outbox event payload.

        Shared by both ``_process_journal_created`` and
        ``_process_journal_updated`` to ensure Strava-sourced events always
        refresh fitness metrics and types regardless of create/update path.

        Safely skips malformed payloads (non-dict ``fitness_data``, non-list
        ``journal_types``) and logs validation errors rather than raising,
        preventing poison-pill retry loops.

        Args:
            journal_id: ID of the journal to persist data for.
            journal_data: The ``journal_data`` dict from the outbox event.
        """
        # Save fitness data if present (Strava-sourced events)
        raw_fitness = journal_data.get("fitness_data")
        if raw_fitness and isinstance(raw_fitness, dict):
            try:
                validated = OutboxFitnessData.model_validate(raw_fitness)
            except ValidationError:
                logger.warning(
                    "Malformed fitness_data in outbox event, skipping",
                    journal_id=journal_id,
                    fitness_data_keys=list(raw_fitness.keys()),
                )
                return
            fitness_repo = SqlFitnessDataRepository(self.connection)
            await fitness_repo.save(
                FitnessData(
                    journal_id=journal_id,
                    distance=validated.distance,
                    elevation_gain=validated.elevation_gain,
                    elevation_loss=validated.elevation_loss,
                    duration=validated.duration,
                    calories=validated.calories,
                    heart_rate_avg=validated.heart_rate_avg,
                    heart_rate_max=validated.heart_rate_max,
                    strava_activity_id=validated.strava_activity_id,
                )
            )
            logger.info(
                "Saved fitness data for journal via repository",
                journal_id=journal_id,
                strava_activity_id=validated.strava_activity_id,
            )

        # Add journal types if present (Strava-sourced events)
        raw_types = journal_data.get("journal_types")
        if raw_types and isinstance(raw_types, list):
            for type_str in raw_types:
                try:
                    journal_type = JournalType(type_str)
                    # journal_types are only present on Strava-sourced events.
                    await self.journal_service.add_type_to_journal(
                        journal_id=journal_id,
                        journal_type=journal_type,
                        transaction=self.connection,
                        changed_by="strava",
                        source=Provenance.STRAVA,
                    )
                except ValueError:
                    logger.warning(
                        "Unknown journal type in outbox event, skipping",
                        journal_type=type_str,
                        journal_id=journal_id,
                    )

            # Create type-specific data rows for types that need them.
            # add_type_to_journal only publishes domain events — the actual
            # data table rows must be inserted separately.  FITNESS is
            # already handled above via SqlFitnessDataRepository.
            await self._ensure_type_data_rows(journal_id, raw_types)

            # Apply climbing-specific data (e.g. indoor flag inferred from
            # Strava). Runs after the row exists so create and re-sync both
            # set/toggle the value.
            await self._persist_climbing_data(journal_id, journal_data, raw_types)

        # Save gear maintenance data if present (Snipe-IT maintenance events)
        await self._persist_gear_maintenance_data(journal_id, journal_data)

    async def _ensure_type_data_rows(
        self, journal_id: int, type_strings: list[str]
    ) -> None:
        """Create default data-table rows for the given journal types.

        Each journal type that maps to a standalone data table (see
        ``_TYPE_DATA_TABLE_MAP``) gets an ``INSERT … ON CONFLICT DO NOTHING``
        so the row is only created if it doesn't already exist.

        FITNESS is **not** covered here because it is persisted with actual
        field values earlier in ``_persist_fitness_and_types``.  EVENT and
        NOTE have no standalone data table.

        Args:
            journal_id: ID of the journal to create rows for.
            type_strings: Raw type value strings from the outbox event.
        """
        for type_str in type_strings:
            table_name = _TYPE_DATA_TABLE_MAP.get(type_str)
            if table_name is None:
                # FITNESS, GEAR_MAINTENANCE, EVENT, NOTE, or unknown — handled
                # elsewhere or no table
                continue

            await self.connection.execute(
                text(
                    f"INSERT INTO {table_name} (journal_id) "  # noqa: S608
                    f"VALUES (:journal_id) "
                    f"ON CONFLICT (journal_id) DO NOTHING"
                ),
                {"journal_id": journal_id},
            )
            logger.debug(
                "Ensured type data row exists",
                journal_id=journal_id,
                type=type_str,
                table=table_name,
            )

    async def _persist_climbing_data(
        self, journal_id: int, journal_data: dict[str, Any], type_strings: list[str]
    ) -> None:
        """Persist climbing-specific data from the outbox event payload.

        Currently only the ``indoor`` flag (inferred by the Strava worker from
        the absence of GPS coordinates). The climbing row is guaranteed to exist
        by ``_ensure_type_data_rows``; this updates it so that every (re)sync
        sets/toggles ``indoor`` to reflect the current Strava state.
        """
        if JournalType.CLIMBING.value not in type_strings:
            return

        climbing_data = journal_data.get("climbing_data")
        if not isinstance(climbing_data, dict) or "indoor" not in climbing_data:
            return

        # Only persist a genuine boolean. A malformed payload (e.g. the string
        # "false") must not silently flip the flag, so ignore it instead of
        # coercing with bool().
        indoor = climbing_data["indoor"]
        if not isinstance(indoor, bool):
            logger.warning(
                "Ignoring non-boolean climbing indoor flag in outbox event",
                journal_id=journal_id,
                indoor=indoor,
            )
            return

        await self.connection.execute(
            text(
                "UPDATE journal_climbing_data "
                "SET indoor = :indoor, updated_at = now() "
                "WHERE journal_id = :journal_id"
            ),
            {"indoor": indoor, "journal_id": journal_id},
        )
        logger.debug(
            "Applied climbing indoor flag from outbox event",
            journal_id=journal_id,
            indoor=indoor,
        )

    async def _persist_gear_maintenance_data(
        self, journal_id: int, journal_data: dict[str, Any]
    ) -> None:
        """Persist gear maintenance data from outbox event payload.

        Called from ``_persist_fitness_and_types`` when the journal_data
        contains a ``gear_maintenance_data`` dict (Snipe-IT maintenance sync).

        Safely skips malformed payloads and logs validation errors rather
        than raising, preventing poison-pill retry loops.

        Args:
            journal_id: ID of the journal to persist data for.
            journal_data: The ``journal_data`` dict from the outbox event.
        """
        raw_maintenance = journal_data.get("gear_maintenance_data")
        if not raw_maintenance or not isinstance(raw_maintenance, dict):
            return

        gear_item_id = raw_maintenance.get("gear_item_id")
        maintenance_type = raw_maintenance.get("maintenance_type")

        if not gear_item_id or not maintenance_type:
            logger.warning(
                "Malformed gear_maintenance_data in outbox event, skipping",
                journal_id=journal_id,
                raw_keys=list(raw_maintenance.keys()),
            )
            return

        try:
            from uuid import UUID as _UUID

            gear_maintenance = GearMaintenanceData(
                journal_id=journal_id,
                gear_item_id=_UUID(str(gear_item_id)),
                maintenance_type=maintenance_type,
                activity_types=raw_maintenance.get("activity_types"),
                retirement_reason=raw_maintenance.get("retirement_reason"),
            )
        except ValueError, ValidationError:
            logger.warning(
                "Failed to validate gear_maintenance_data, skipping",
                journal_id=journal_id,
                exc_info=True,
            )
            return

        repo = SqlGearMaintenanceDataRepository(self.connection)
        await repo.save(gear_maintenance)
        logger.info(
            "Saved gear maintenance data for journal",
            journal_id=journal_id,
            gear_item_id=str(gear_item_id),
            maintenance_type=maintenance_type,
        )

    async def _resolve_strava_athlete_to_contact(
        self, user_id: str, athlete_id: str, athlete_name: str | None
    ) -> int | None:
        """Resolve a Strava athlete to a contact ID using mappings or exact name match."""
        mapping = await self.strava_athlete_mapping_repository.get_by_strava_id(
            user_id, athlete_id
        )
        if mapping:
            return mapping.contact_id

        if not athlete_name:
            return None

        contacts = await self.contact_repository.search(athlete_name, limit=10)
        exact_matches = [
            c
            for c in contacts
            if (
                c.first_name
                and c.last_name
                and f"{c.first_name} {c.last_name}".lower() == athlete_name.lower()
            )
            or (
                c.first_name
                and not c.last_name
                and c.first_name.lower() == athlete_name.lower()
            )
        ]

        if len(exact_matches) == 1 and exact_matches[0].id is not None:
            contact_id = exact_matches[0].id
            new_mapping = StravaAthleteMapping(
                user_id=user_id,
                strava_athlete_id=athlete_id,
                strava_athlete_name=athlete_name,
                contact_id=contact_id,
            )
            await self.strava_athlete_mapping_repository.save(new_mapping)
            return contact_id

        return None

    async def _record_unmatched_strava_athlete(
        self, journal_id: int, athlete_id: str, athlete_name: str | None
    ) -> None:
        safe_athlete_name = athlete_name or ""
        await self.connection.execute(
            text("""
                INSERT INTO journal_unmatched_strava_athletes
                    (journal_id, strava_athlete_id, strava_athlete_name)
                VALUES
                    (:journal_id, :strava_athlete_id, :strava_athlete_name)
                ON CONFLICT (journal_id, strava_athlete_id) DO UPDATE SET
                    strava_athlete_name = EXCLUDED.strava_athlete_name
            """),
            {
                "journal_id": journal_id,
                "strava_athlete_id": athlete_id,
                "strava_athlete_name": safe_athlete_name,
            },
        )

    async def _persist_strava_athletes(
        self, journal_id: int, user_id: str, journal_data: dict[str, Any]
    ) -> None:
        """Resolve Strava athletes to contacts and add them as PARTICIPANTS.

        Args:
            journal_id: ID of the journal.
            user_id: ID of the user.
            journal_data: The ``journal_data`` dict from the outbox event.
        """
        strava_athletes = journal_data.get("strava_athletes")
        if not strava_athletes or not isinstance(strava_athletes, list):
            return

        for athlete in strava_athletes:
            if not isinstance(athlete, dict):
                continue

            athlete_id = str(athlete.get("id", ""))
            if not athlete_id or athlete_id == "None":
                continue

            athlete_name = athlete.get("name")
            if not isinstance(athlete_name, str):
                athlete_name = None

            contact_id = await self._resolve_strava_athlete_to_contact(
                user_id, athlete_id, athlete_name
            )

            if contact_id is not None:
                await self._create_contact_relationship(
                    journal_id=journal_id,
                    contact_id=contact_id,
                    relationship_type=JournalContactRelationshipType.PARTICIPANT,
                    status=AttendeeStatus.ATTENDED.value,
                )
                await self._clear_unmatched_strava_athlete(journal_id, athlete_id)
            else:
                await self._record_unmatched_strava_athlete(
                    journal_id, athlete_id, athlete_name
                )

    async def _clear_unmatched_strava_athlete(
        self, journal_id: int, athlete_id: str
    ) -> None:
        """Clear an unmatched Strava athlete record for a journal.

        This ensures UI consistency when an athlete is successfully matched to a contact.
        """
        await self.connection.execute(
            text("""
                DELETE FROM journal_unmatched_strava_athletes
                WHERE journal_id = :journal_id AND strava_athlete_id = :strava_athlete_id
            """),
            {
                "journal_id": journal_id,
                "strava_athlete_id": athlete_id,
            },
        )

    # ── Integration source → calendar display name/color ────────────
    _INTEGRATION_CALENDAR_DEFAULTS: dict[str, tuple[str, str]] = {
        "strava": ("Strava Activities", "#FC4C02"),
        "google": ("Google Calendar", "#4285F4"),
    }

    async def _ensure_calendar_exists(
        self,
        calendar_id: UUID,
        user_id: str,
        integration_source: str,
    ) -> None:
        """Ensure the calendar row exists for the given calendar_id.

        Non-calendar integrations (e.g. Strava) use a synthetic
        calendar_id that may not exist in the ``calendars`` table yet.
        This creates it on-demand using ``ON CONFLICT DO NOTHING`` so
        that subsequent FK-dependent inserts into
        ``journal_calendar_info`` and ``journal_external_event_links``
        succeed.
        """
        name, color = self._INTEGRATION_CALENDAR_DEFAULTS.get(
            integration_source, (f"{integration_source.title()} Calendar", "#808080")
        )
        await self.connection.execute(
            text("""
                INSERT INTO calendars (id, user_id, name, color)
                VALUES (:id, :user_id, :name, :color)
                ON CONFLICT (id) DO NOTHING
            """),
            {
                "id": calendar_id,
                "user_id": user_id,
                "name": name,
                "color": color,
            },
        )

    async def _save_calendar_info(
        self, journal_id: int, calendar_info_data: dict[str, Any]
    ) -> None:
        """Save calendar info for a journal using raw SQL.

        The journal's calendar is set when the row is first written and
        never reassigned afterwards. A journal holds exactly one
        ``journal_calendar_info`` row — the calendar it is displayed in —
        but since events are de-duplicated across calendars it may be linked
        to several. Letting each sync write the calendar it came from would
        make a shared event flip between calendars depending on which one
        synced last. First calendar to see the event keeps it; the others
        contribute a link and nothing more.

        Deliberately does **not** mark the journal as changed, even though this
        alters what a read of it returns. ``journals.updated_at`` is also the
        merge-protection signal — an inbound sync compares it against the
        link's anchor to decide whether the user edited the journal since the
        last sync — so writing it from inside a sync would mix "the user
        changed this" with "the sync changed this". See the Conditional Writes
        docs for the trade-off.
        """
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
        recurring_event_id: str | None = None,
        external_identity: str | None = None,
    ) -> None:
        """Create an external event link for tracking sync state.

        Uses ON CONFLICT DO UPDATE so retries of journal_event.created
        don't fail on the composite PK (journal_id, calendar_id).
        COALESCE keeps an already-stored recurring id — and identity —
        when a payload omits it.
        """
        now = datetime.now(UTC)
        await self.connection.execute(
            text("""
                INSERT INTO journal_external_event_links
                    (journal_id, calendar_id, external_event_id,
                     external_version, recurring_event_id, external_identity,
                     sync_capability, sync_status,
                     created_at, updated_at)
                VALUES
                    (:journal_id, :calendar_id, :external_event_id,
                     :etag, :recurring_event_id, :external_identity,
                     'bidirectional', 'synced',
                     :now, :now)
                ON CONFLICT (journal_id, calendar_id) DO UPDATE SET
                    external_event_id = :external_event_id,
                    external_version = :etag,
                    recurring_event_id = COALESCE(
                        :recurring_event_id,
                        journal_external_event_links.recurring_event_id
                    ),
                    external_identity = COALESCE(
                        :external_identity,
                        journal_external_event_links.external_identity
                    ),
                    sync_status = 'synced',
                    updated_at = :now
            """),
            {
                "journal_id": journal_id,
                "calendar_id": calendar_id,
                "external_event_id": external_event_id,
                "etag": etag,
                "recurring_event_id": recurring_event_id,
                "external_identity": external_identity,
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

    async def _find_calendar_info(self, journal_id: int) -> Any | None:
        """Find calendar info for a journal by its ID.

        Returns the raw row or None if no calendar info exists.
        Used to check private_description during inbound sync.
        """
        result = await self.connection.execute(
            text("""
                SELECT private_description
                FROM journal_calendar_info
                WHERE journal_id = :journal_id
            """),
            {"journal_id": journal_id},
        )
        return result.fetchone()

    async def _find_external_event_link(
        self,
        calendar_id: UUID,
        external_event_id: str,
    ) -> Any | None:
        """Find an existing external event link."""
        result = await self.connection.execute(
            text("""
                SELECT external_version, journal_id, sync_capability,
                       sync_status, updated_at, recurring_event_id
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

    async def _flag_duplicate_journals(
        self,
        journal_id: int,
        user_id: str,
        external_identity: str | None,
    ) -> None:
        """Send any journal describing this same event to the review queue.

        De-duplication prevents *new* duplicates; it cannot retroactively
        join two journals that already exist, because merging them means
        choosing whose title, content and tags survive — the user's call,
        not the sync's. What it can do is say with certainty that the pair
        is one event, which is what the review queue is for.

        The pair reaches this state through the identity backfill: two
        journals synced before tokens existed each acquire the same token
        on their next sync, and the second one to do so finds the first.

        The journal ids are ordered before being recorded. The queue's
        uniqueness is on the ordered pair, so flagging (A, B) on one sync
        and (B, A) on the next would leave two rows describing one
        duplicate — and which journal syncs first is not something this
        controls.
        """
        if not external_identity:
            return

        result = await self.connection.execute(
            text("""
                SELECT DISTINCT l.journal_id
                FROM journal_external_event_links l
                JOIN journals j ON j.id = l.journal_id
                WHERE j.user_id = :user_id
                  AND l.external_identity = :external_identity
                  AND l.journal_id <> :journal_id
            """),
            {
                "user_id": str(user_id),
                "external_identity": external_identity,
                "journal_id": journal_id,
            },
        )

        for row in result.fetchall():
            source_id, candidate_id = sorted((journal_id, int(row.journal_id)))
            _, created = await self.review_item_repo.create(
                ReviewItem(
                    user_id=str(user_id),
                    source_journal_id=source_id,
                    candidate_journal_id=candidate_id,
                    reason=ReviewReason.EXTERNAL_LINK_MATCH,
                    confidence_score=1.0,
                    details={
                        "external_identity": external_identity,
                        "detected_by": "cross_calendar_identity",
                    },
                )
            )
            if created:
                logger.info(
                    "Flagged two journals as one external event for review",
                    source_journal_id=source_id,
                    candidate_journal_id=candidate_id,
                )

    async def _find_journal_by_external_identity(
        self,
        user_id: str,
        external_identity: str | None,
    ) -> int | None:
        """Find the journal already linked to this same real-world thing.

        ``external_identity`` is opaque here: it is compared for equality
        and never interpreted. Whatever the source packed into it, two links
        carrying the same token describe one thing, so they belong to one
        journal.

        Scoped to the user, because a token only means something within one
        person's own calendars — two people invited to the same meeting hold
        their own copies, and their journals must stay their own. A null
        token matches nothing: "no identity" is not an identity to share.
        """
        if not external_identity:
            return None

        result = await self.connection.execute(
            text("""
                SELECT l.journal_id
                FROM journal_external_event_links l
                JOIN journals j ON j.id = l.journal_id
                WHERE j.user_id = :user_id
                  AND l.external_identity = :external_identity
                ORDER BY l.created_at, l.journal_id
                LIMIT 1
            """),
            {
                "user_id": str(user_id),
                "external_identity": external_identity,
            },
        )
        row = result.fetchone()
        return int(row.journal_id) if row else None

    async def _update_external_event_link_etag(
        self,
        calendar_id: UUID,
        external_event_id: str,
        etag: str | None,
        recurring_event_id: str | None = None,
        external_identity: str | None = None,
    ) -> None:
        """Update the ETag on an external event link after successful sync.

        Also backfills the recurring id; COALESCE keeps a stored value when
        the inbound payload omits it.
        """
        await self.connection.execute(
            text("""
                UPDATE journal_external_event_links
                SET external_version = :etag,
                    updated_at = :now,
                    recurring_event_id = COALESCE(
                        :recurring_event_id, recurring_event_id
                    ),
                    external_identity = COALESCE(
                        :external_identity, external_identity
                    ),
                    sync_status = 'synced'
                WHERE calendar_id = :calendar_id
                  AND external_event_id = :external_event_id
            """),
            {
                "etag": etag,
                "calendar_id": calendar_id,
                "external_event_id": external_event_id,
                "recurring_event_id": recurring_event_id,
                "external_identity": external_identity,
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

    def _parse_inbound_status(
        self, raw_status: str | None, journal_id: int
    ) -> str | None:
        if not raw_status:
            return None
        try:
            return AttendeeStatus(raw_status).value
        except ValueError:
            logger.warning(
                "Invalid inbound status in sync, treating as None",
                status=raw_status,
                journal_id=journal_id,
            )
            return None

    def _parse_inbound_role(self, raw_role: str | None, journal_id: int) -> str | None:
        if not raw_role:
            return None
        try:
            return ContactEventRole(raw_role).value
        except ValueError:
            logger.warning(
                "Invalid inbound role in sync, treating as None",
                role=raw_role,
                journal_id=journal_id,
            )
            return None

    def _compute_updated_relationship(
        self,
        existing_rel: Any,
        valid_inbound_status: str | None,
        valid_inbound_role: str | None,
    ) -> tuple[bool, str | None, str | None]:
        changed = False
        new_status = existing_rel.status.value if existing_rel.status else None
        if new_status != AttendeeStatus.ATTENDED.value:
            if valid_inbound_status and new_status != valid_inbound_status:
                new_status = valid_inbound_status
                changed = True

        new_role = existing_rel.role.value if existing_rel.role else None
        if new_role != ContactEventRole.FACILITATOR_HELPER.value:
            if valid_inbound_role:
                if new_role != valid_inbound_role:
                    new_role = valid_inbound_role
                    changed = True
            elif (
                valid_inbound_role is None
                and new_role == ContactEventRole.ORGANISER.value
            ):
                new_role = None
                changed = True
        return changed, new_status, new_role

    async def _sync_contact_relationships(
        self,
        journal_id: int,
        contact_relationships: list[dict[str, Any]],
    ) -> None:
        """Sync contact relationships for a journal from inbound data."""
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

            existing = await self._get_relationships_by_type(journal_id, rel_type)
            existing_by_contact_id = {r.contact_id: r for r in existing}

            to_create: list[tuple[int, str | None, str | None]] = []
            to_update: list[tuple[int, str | None, str | None]] = []

            resolved_contact_id_set = set(resolved_contact_ids.values())
            to_delete = set(existing_by_contact_id.keys()) - resolved_contact_id_set

            for inbound_payload in payloads:
                email = inbound_payload["email"]
                if email not in resolved_contact_ids:
                    continue

                contact_id = resolved_contact_ids[email]
                valid_status = self._parse_inbound_status(
                    inbound_payload.get("status"), journal_id
                )
                valid_role = self._parse_inbound_role(
                    inbound_payload.get("role"), journal_id
                )

                existing_rel = existing_by_contact_id.get(contact_id)
                if not existing_rel:
                    to_create.append((contact_id, valid_status, valid_role))
                else:
                    changed, new_status, new_role = self._compute_updated_relationship(
                        existing_rel, valid_status, valid_role
                    )
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
        from datetime import UTC, datetime
        from uuid import uuid4

        now = datetime.now(UTC).replace(tzinfo=None)
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

    async def _persist_route_from_gpx(
        self,
        journal_id: int,
        journal_data: dict[str, Any],
    ) -> None:
        """Create or update a Route from GPX XML in the outbox event payload.

        When a Strava activity includes GPS track data, the worker generates
        GPX XML and includes it in the outbox event. This method persists
        that GPX as a Route entity linked to the journal.

        For Strava-sourced events there is exactly one route per journal.
        If a route already exists for this journal we update it in-place
        (including the name, which may change if the activity title was
        edited on Strava). If no route exists we insert a new one.

        Args:
            journal_id: ID of the journal to attach the route to.
            journal_data: The ``journal_data`` dict from the outbox event.
        """
        if "gpx_xml" not in journal_data or not journal_data["gpx_xml"]:
            return

        try:
            route_data = OutboxRouteData.model_validate(journal_data)
        except ValidationError as e:
            logger.warning(
                "Malformed route data in outbox payload, skipping",
                journal_id=journal_id,
                errors=e.errors(),
            )
            return

        route_repo = SqlRouteRepository(self.connection)

        try:
            # Check if a route already exists for this journal
            existing = await route_repo.find_by_journal_id(journal_id)

            if existing:
                existing_route = existing[0]
                existing_route.name = route_data.title
                existing_route.gpx_data = route_data.gpx_xml
                # Manually trigger validation on update since dataclasses don't auto-validate on assignment
                existing_route.__post_init__()
                await route_repo.save(existing_route)
            else:
                new_route = Route(
                    journal_id=journal_id,
                    name=route_data.title,
                    gpx_data=route_data.gpx_xml,
                )
                await route_repo.save(new_route)

            logger.info(
                "Persisted GPX route for journal",
                journal_id=journal_id,
                route_name=route_data.title,
            )
        except ValueError as e:
            logger.warning(
                "Invalid route or GPX data, skipping route persistence",
                journal_id=journal_id,
                error=str(e),
            )
            return

    async def _persist_sync_metadata(
        self,
        journal_id: int,
        event_data: dict[str, Any],
    ) -> None:
        """Create or update SyncMetadata for Strava-sourced events.

        Only applies to events with ``integration_source == 'strava'``.
        Uses the ``strava_activity_id`` from fitness_data as the external_id
        and the ``version_hash`` from journal_data for change detection.

        Args:
            journal_id: ID of the journal linked to this sync record.
            event_data: The full outbox event data dict.
        """
        integration_source = event_data.get("integration_source")
        if integration_source != "strava":
            return

        journal_data = event_data.get("journal_data", {})
        fitness_data = journal_data.get("fitness_data", {})

        # Need strava_activity_id from fitness_data and version_hash from journal_data
        sync_payload = {
            "strava_activity_id": fitness_data.get("strava_activity_id")
            if isinstance(fitness_data, dict)
            else None,
            "version_hash": journal_data.get("version_hash", ""),
        }

        try:
            sync_data = OutboxSyncData.model_validate(sync_payload)
        except ValidationError as e:
            logger.warning(
                "Strava event missing valid sync data, skipping sync metadata",
                journal_id=journal_id,
                errors=e.errors(),
            )
            return

        sync_metadata_repo = SyncMetadataRepository(self.connection)

        await sync_metadata_repo.upsert(
            internal_id=journal_id,
            integration_source="strava",
            external_id=sync_data.strava_activity_id,
            version_hash=sync_data.version_hash,
            internal_entity_type="journal",
            external_entity_type="activity",
        )

        logger.info(
            "Persisted sync metadata for Strava activity",
            journal_id=journal_id,
            strava_activity_id=sync_data.strava_activity_id,
            version_hash=str(sync_data.version_hash)[:16] + "...",
        )
