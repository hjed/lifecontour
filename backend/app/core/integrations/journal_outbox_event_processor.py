"""
Journal Outbox Event Processor for handling inbound journal sync events.

Processes journal_event.created, journal_event.updated,
journal_event.conflicted, and journal_event.cancelled outbox events
from integration workers to create/update journals in the core system.
"""

from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING, Any
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
)
from core_shared.models.journals.event_state import EventState
from core_shared.models.journals.exceptions import GearMaintenanceDataValidationError
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
    FitnessDurationCorrectedData,
    JournalRecurrenceTidyEventData,
    JournalSeriesCancelledEventData,
    JournalStatusEventData,
    JournalSyncEventData,
)
from core_shared.models.participant_email import (
    MAX_PARTICIPANT_DISPLAY_NAME_LENGTH,
    is_recordable_participant_email,
    normalise_participant_email,
)
from core_shared.models.route import Route
from core_shared.models.strava_athlete_mapping import StravaAthleteMapping
from core_shared.repositories.merged_alias_repository import (
    MergedAlias,
    MergedAliasRepository,
)
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_repository import SqlContactRepository
from app.core.integrations.adapters.sql.journal_event_link_repository import (
    SqlJournalEventLinkRepository,
)
from app.core.integrations.adapters.sql.strava_athlete_mapping_repository import (
    SqlStravaAthleteMappingRepository,
)
from app.core.integrations.adapters.sql.sync_metadata_repository import (
    SyncMetadataRepository,
)
from app.core.integrations.adapters.sql.unmatched_participant_email_repository import (
    SqlUnmatchedParticipantEmailRepository,
)
from app.core.integrations.cancelled_recurrence_tidier import (
    CancelledRecurrenceTidier,
)
from app.core.integrations.models.unmatched_participant import (
    UnmatchedParticipantEmail,
)
from app.core.integrations.split_adoption import (
    SplitAdopter,
    adopted_journal_data,
    find_split_predecessor,
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

if TYPE_CHECKING:
    from app.core.journal.services.journal_date_resolver import JournalDateResolver

logger = structlog.get_logger()

# Event type constants
EVENT_TYPE_JOURNAL_EVENT_CREATED = "journal_event.created"
EVENT_TYPE_JOURNAL_EVENT_UPDATED = "journal_event.updated"
EVENT_TYPE_JOURNAL_EVENT_CONFLICTED = "journal_event.conflicted"
EVENT_TYPE_JOURNAL_EVENT_CANCELLED = "journal_event.cancelled"
EVENT_TYPE_JOURNAL_EVENT_SERIES_CANCELLED = "journal_event.series_cancelled"
EVENT_TYPE_JOURNAL_EVENT_RECURRENCE_TIDY = "journal_event.recurrence_tidy"
EVENT_TYPE_JOURNAL_EVENT_FITNESS_DURATION_CORRECTED = (
    "journal_event.fitness_duration_corrected"
)
EVENT_TYPE_JOURNAL_REVIEW_DETECT_MATCHES = "journal_review.detect_matches"

# Buffer around "now" for recurring-cancellation decisions, mirroring the
# worker's past-event skip buffer (all-day events are midnight-normalised).
_SERIES_DELETION_BUFFER = timedelta(days=1)

# Integration source of Snipe-IT maintenance imports. Must equal
# ``INBOUND_SYNC_CHANGED_BY`` in the Snipe-IT worker.
_SNIPEIT_MAINTENANCE_SOURCE = "snipeit_maintenance"

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

    async def resolve_by_email(self, email: str, *, user_id: str) -> int | None:
        """Resolve one of ``user_id``'s contacts by email, ignoring case and whitespace.

        Args:
            email: Email address to search for
            user_id: The journal's owner; only their contacts can match

        Returns:
            Contact ID if found, None otherwise (including when only another
            user's contact holds the address)
        """
        result = await self.connection.execute(
            text("""
                SELECT c.id
                FROM contacts c
                JOIN contact_methods cm ON c.id = cm.contact_id
                WHERE cm.method_type = 'email'
                  AND LOWER(BTRIM(cm.value)) = :email
                  AND c.user_id = :user_id
                LIMIT 1
            """),
            {"email": normalise_participant_email(email), "user_id": user_id},
        )
        row = result.fetchone()
        return row.id if row else None


def _skipped_as_merged(
    event_type: str, alias: MergedAlias, external_event_id: str
) -> dict[str, Any]:
    """The result for an event a merge absorbed: nothing was written."""
    logger.info(
        "Sync event skipped - a merge absorbed this record",
        event_type=event_type,
        external_event_id=external_event_id,
        merged_into_journal_id=alias.journal_id,
    )
    return {
        "status": "skipped",
        "reason": "merged_alias",
        "event_type": event_type,
        "journal_id": alias.journal_id,
        "external_event_id": external_event_id,
    }


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
        self.recurrence_tidier = CancelledRecurrenceTidier(
            connection, self.link_repo, journal_service
        )
        self.series_repo = SqlJournalSeriesRepository(connection)
        self.split_adopter = SplitAdopter(
            self.link_repo, self.series_repo, self.recurrence_tidier
        )
        self.review_item_repo = SqlReviewItemRepository(connection)
        self.unmatched_participant_repo = SqlUnmatchedParticipantEmailRepository(
            connection
        )
        self.merged_alias_repo = MergedAliasRepository(connection)

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

        if event.event_type in (
            EVENT_TYPE_JOURNAL_EVENT_CREATED,
            EVENT_TYPE_JOURNAL_EVENT_UPDATED,
        ) and await self._is_superseded_snipeit_maintenance(event):
            # Terminal, not an error: raising would only have the stream
            # redeliver an event that can never become the latest again.
            return {
                "status": "skipped",
                "reason": "superseded",
                "event_type": event.event_type,
            }

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
        if event.event_type == EVENT_TYPE_JOURNAL_EVENT_RECURRENCE_TIDY:
            return await self._process_journal_recurrence_tidy(event)
        if event.event_type == EVENT_TYPE_JOURNAL_EVENT_FITNESS_DURATION_CORRECTED:
            return await self._process_fitness_duration_corrected(event)

        raise JournalOutboxEventProcessingError(
            f"Unknown journal event type: {event.event_type}"
        )

    async def _is_superseded_snipeit_maintenance(self, event: OutboxEvent) -> bool:
        """Has a newer event for this Snipe-IT maintenance replaced ``event``?

        The Snipe-IT worker records every maintenance event's ``version_hash``
        on the record's sync row, in the same transaction it enqueues the event
        — so the row always names the latest event sent for the record. The
        stream cannot promise to deliver them in that order: an event delivered
        and not acknowledged before its consumer died waits in the pending list,
        and the consumer reads new events before it reclaims pending ones.
        Applying such an event late would put the record's older state over the
        journal, and nothing would correct it, since the row already says the
        journal is current.

        An event is therefore applied only while the row still records its
        hash. With no row at all, the record was deleted after the event was
        sent, and applying it would bring back a journal for a record that is
        no longer there.

        Other sources return ``False``: Strava also sends a ``version_hash``
        but keys its sync rows differently, so the row would not be found.
        """
        payload = JournalSyncEventData.model_validate(event.event_data)
        if payload.integration_source != _SNIPEIT_MAINTENANCE_SOURCE:
            return False

        # Snipe-IT ids are per instance, so only the owner's row speaks for the
        # event; one naming no owner cannot be matched to anyone's.
        owner = payload.journal_data.get("user_id")
        if not owner:
            raise JournalOutboxEventProcessingError(
                f"Snipe-IT maintenance event {payload.external_event_id!r} "
                "names no owner (user_id)"
            )
        result = await self.connection.execute(
            text("""
                SELECT version_hash
                FROM sync_metadata
                WHERE user_id = :user_id
                  AND integration_source = :integration_source
                  AND external_id = :external_id
            """),
            {
                "user_id": str(owner),
                "integration_source": _SNIPEIT_MAINTENANCE_SOURCE,
                "external_id": payload.external_event_id,
            },
        )
        row = result.fetchone()
        sent_hash = payload.journal_data.get("version_hash")
        if row is not None and row.version_hash == sent_hash:
            return False

        logger.info(
            "Skipping a Snipe-IT maintenance event a newer one has replaced",
            event_id=event.id,
            event_type=event.event_type,
            external_event_id=payload.external_event_id,
            sent_hash=sent_hash,
            recorded_hash=row.version_hash if row is not None else None,
        )
        return True

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

        # A merge absorbed this event into another journal. Creating it again
        # would undo the merge; this is the last place that can stop it, since
        # a merge can land between the worker's check and this write. Asked
        # last, after every lookup that could still find a journal, so a merge
        # committing between those lookups and here — taking the absorbed
        # event's link with it — has already recorded the alias. The record's
        # lock, which the merge also takes, closes the last gap: a merge
        # aliasing it either committed before this read or waits until the
        # journal below exists.
        await self.merged_alias_repo.lock_record(
            user_id=payload.journal_data["user_id"],
            payload_source=payload.integration_source,
            external_id=external_event_id,
            external_identity=payload.external_identity,
        )
        merged_alias = await self._merged_alias_for(payload)
        if merged_alias is not None:
            return _skipped_as_merged(
                EVENT_TYPE_JOURNAL_EVENT_CREATED, merged_alias, external_event_id
            )

        # A recurrence split under an unrelated id whose halves arrived in
        # different syncs: the old recurrence's cancellations left a cancelled
        # journal on this day, which this instance adopts rather than doubles.
        predecessor = await find_split_predecessor(
            self.link_repo, self._date_resolver(), payload
        )
        if predecessor is not None:
            # Lock the old recurrence and look again: another create may have
            # adopted this journal between the lookup and the lock, and adopting
            # it twice would re-point its link away from that event.
            await self.link_repo.lock_recurrence(
                UUID(calendar_id), predecessor.old_recurring_event_id
            )
            predecessor = await find_split_predecessor(
                self.link_repo, self._date_resolver(), payload
            )
        if predecessor is not None:
            logger.info(
                "New recurrence instance adopts a cancelled journal it split from",
                external_event_id=external_event_id,
                existing_journal_id=predecessor.journal_id,
            )
            event.event_data["existing_journal_id"] = predecessor.journal_id
            event.event_data["split_adopted_from"] = predecessor.adopted_from
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
            series_recurring_event_id=payload.series_recurring_event_id,
            series_name=created_journal.title,
        )

        # Sync contact relationships (e.g. invitees)
        await self._sync_contact_relationships(
            journal_id=created_journal.id,
            contact_relationships=contact_relationships,
            user_id=created_journal.user_id,
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
            user_id=created_journal.user_id,
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

    async def _merged_alias_for(
        self, payload: JournalSyncEventData
    ) -> MergedAlias | None:
        """The alias of this event, if a merge absorbed it into another journal."""
        return await self.merged_alias_repo.find_alias(
            user_id=payload.journal_data["user_id"],
            payload_source=payload.integration_source,
            external_id=payload.external_event_id,
            external_identity=payload.external_identity,
        )

    async def _process_journal_updated(self, event: OutboxEvent) -> dict[str, Any]:
        """
        Process a journal_event.updated event.

        Looks up the existing journal, checks for ETag-based idempotency,
        applies InboundFieldMerger to protect local edits, updates the
        journal fields, and updates the external event link.

        The merge and the journal it builds are made inside
        ``JournalService.modify_journal``, from the journal as read under its
        row lock, so a local edit committed meanwhile is protected rather than
        overwritten.
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
            # An update queued for a journal a merge has since absorbed.
            merged_alias = await self._merged_alias_for(payload)
            if merged_alias is not None:
                return _skipped_as_merged(
                    EVENT_TYPE_JOURNAL_EVENT_UPDATED, merged_alias, external_event_id
                )
            if payload.split_adopted_from is not None:
                return await self._create_instead_of_adopting(event)
            raise JournalOutboxEventProcessingError(
                f"Journal {existing_journal_id} not found for update"
            )

        # A split-off recurrence adopting this journal (see ``split_adoption``)
        split_adoption = None
        if payload.split_adopted_from is not None:
            if await self.split_adopter.is_superseded(
                journal_id=existing_journal_id,
                calendar_id=UUID(calendar_id),
                payload=payload,
            ):
                logger.info(
                    "Adoption skipped - the journal has since moved on",
                    journal_id=existing_journal_id,
                    external_event_id=external_event_id,
                )
                return {
                    "status": "skipped",
                    "event_type": EVENT_TYPE_JOURNAL_EVENT_UPDATED,
                    "reason": "adoption_superseded",
                    "journal_id": existing_journal_id,
                }
            split_adoption = await self.split_adopter.begin(
                journal=existing_journal,
                calendar_id=UUID(calendar_id),
                payload=payload,
            )
            journal_data = adopted_journal_data(journal_data, existing_journal)

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
            # link predates a feature, carrying the SAME etag. Whatever the
            # link is missing must persist before the skip or the worker
            # re-promotes the event on every sync, forever.
            #
            # Two things arrive this way, and neither can wait for the event
            # to change — an event nobody edits would wait forever:
            # the recurring id that makes an instance part of a series, and
            # the identity token that makes one event in two calendars one
            # journal. Both are additions to the link, not edits to the
            # journal, so they belong on this side of the guard: the skip
            # still spares the journal a no-op update and its history a
            # no-op entry.
            needs_recurring_id = (
                payload.recurring_event_id is not None
                and existing_link.recurring_event_id is None
            )
            needs_identity = (
                payload.external_identity is not None
                and existing_link.external_identity is None
            )
            if needs_recurring_id or needs_identity:
                await self._backfill_external_event_link_metadata(
                    calendar_id=UUID(calendar_id),
                    external_event_id=external_event_id,
                    recurring_event_id=payload.recurring_event_id,
                    external_identity=payload.external_identity,
                )
            if needs_recurring_id:
                await self._ensure_series_membership(
                    journal_id=existing_journal_id,
                    user_id=existing_journal.user_id,
                    calendar_id=UUID(calendar_id),
                    recurring_event_id=payload.recurring_event_id,
                    series_recurring_event_id=payload.series_recurring_event_id,
                    series_name=existing_journal.title,
                )
                logger.info(
                    "Backfilled recurring id on unchanged event",
                    journal_id=existing_journal_id,
                    recurring_event_id=payload.recurring_event_id,
                )
            if needs_identity:
                await self._flag_duplicate_journals(
                    journal_id=existing_journal_id,
                    user_id=existing_journal.user_id,
                    external_identity=payload.external_identity,
                )
                logger.info(
                    "Backfilled external identity on unchanged event",
                    journal_id=existing_journal_id,
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

        # An event a merge absorbed has no link of its own, and must not be
        # given one: the journal's one link in this calendar is the survivor's
        # own event, which the link upsert below would overwrite. Nor may it
        # edit the survivor.
        if existing_link is None:
            merged_alias = await self._merged_alias_for(payload)
            if merged_alias is not None:
                return _skipped_as_merged(
                    EVENT_TYPE_JOURNAL_EVENT_UPDATED, merged_alias, external_event_id
                )

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

        # When private_description is enabled, block inbound content changes
        # to prevent external calendar descriptions overwriting local journal notes.
        existing_calendar_info = await self._find_calendar_info(existing_journal_id)
        private_description = bool(
            existing_calendar_info and existing_calendar_info.private_description
        )
        if private_description:
            logger.debug(
                "Blocking inbound content update due to private_description",
                journal_id=existing_journal_id,
            )
        link_updated_at = existing_link.updated_at if existing_link else None
        adopting = split_adoption is not None

        def _merged(stored: Journal) -> Journal | None:
            return self._merged_journal(
                stored,
                adopted_journal_data(journal_data, stored)
                if adopting
                else journal_data,
                private_description=private_description,
                link_updated_at=link_updated_at,
            )

        # Skip a no-op inbound sync entirely so it produces no event/history.
        # Judged first on the unlocked read: writing nothing cannot revert a
        # concurrent edit, and it keeps a no-op sync off the journal's lock,
        # which would otherwise be taken ahead of the series locks below - the
        # opposite order to a split adoption.
        saved_journal = existing_journal
        fields_changed = False
        if _merged(existing_journal) is not None:
            locked_journal = existing_journal

            async def _merge_inbound(stored: Journal) -> Journal | None:
                # Merged again from the journal read under its row lock, so a
                # local edit committed since the read above is what the
                # protection check compares - and what the save keeps (#1813).
                nonlocal locked_journal
                locked_journal = stored
                return _merged(stored)

            written = await self.journal_service.modify_journal(
                existing_journal_id,
                _merge_inbound,
                self.connection,
                changed_by=payload.integration_source or "system",
                source=_provenance_for_source(payload.integration_source),
            )
            fields_changed = written is not None
            saved_journal = written if written is not None else locked_journal

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
            series_recurring_event_id=payload.series_recurring_event_id,
            series_name=saved_journal.title,
        )

        # Sync contact relationships (e.g. invitees)
        await self._sync_contact_relationships(
            journal_id=existing_journal_id,
            contact_relationships=contact_relationships,
            user_id=existing_journal.user_id,
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
            user_id=existing_journal.user_id,
            event_data=payload.model_dump(),
        )

        # The journal's own fields did not move, so no ``JournalUpdated`` was
        # published — but the calendar info and the attendees above may have,
        # and the current day's summary is grounded in both. Nothing else will
        # say so, so this does.
        if not fields_changed:
            await self._invalidate_summary_for_journal(existing_journal_id)

        if split_adoption is not None:
            tidied = await self.split_adopter.finish(
                split_adoption,
                source=_provenance_for_source(payload.integration_source),
                changed_by=payload.integration_source or "system",
            )
            if tidied is not None and tidied.errors:
                # Retried whole: adoption and tidy are both idempotent.
                raise JournalOutboxEventProcessingError(
                    f"Re-planning the recurrence journal {existing_journal_id} "
                    "left failed; failing for retry"
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

    async def _link_moved_on(
        self, journal_id: int, calendar_id: UUID, external_event_id: str
    ) -> bool:
        """Whether the journal's link in this calendar names another event."""
        current = await self.link_repo.find_by_journal(journal_id, calendar_id)
        return (
            current is not None
            and current.external_event_id is not None
            and current.external_event_id != external_event_id
        )

    def _date_resolver(self) -> JournalDateResolver:
        """Local-day arithmetic in the user's zone, over this connection."""
        from app.core.journal.services.journal_date_resolver import (
            JournalDateResolver,
        )
        from app.core.settings.adapters.sql.user_settings_repository import (
            SqlUserSettingsRepository,
        )

        return JournalDateResolver(SqlUserSettingsRepository(self.connection))

    async def _create_instead_of_adopting(self, event: OutboxEvent) -> dict[str, Any]:
        """Create the instance whose adoption target was deleted meanwhile.

        The worker has already moved past this event, so failing it would lose
        the occurrence for good; it is created as the worker would have sent
        it had there been nothing to adopt.
        """
        event_data: dict[str, Any] = dict(event.event_data)
        payload = JournalSyncEventData.model_validate(event_data)
        new_key = payload.series_recurring_event_id or payload.recurring_event_id
        if new_key and payload.split_adopted_from:
            # The old series survives the deleted journal: the new recurrence
            # still belongs in it.
            await self.series_repo.adopt_recurrence(
                user_id=str(payload.journal_data["user_id"]),
                calendar_id=UUID(payload.calendar_id),
                recurring_event_id=new_key,
                into_recurring_event_id=payload.split_adopted_from,
            )
        event_data.update(
            existing_journal_id=None,
            split_adopted_from=None,
            sync_action="created",
        )
        logger.info(
            "Adoption target gone, creating the instance instead",
            external_event_id=event_data.get("external_event_id"),
        )
        return await self._process_journal_created(
            OutboxEvent(
                event_type=EVENT_TYPE_JOURNAL_EVENT_CREATED,
                event_data=event_data,
                aggregate_id=0,
            )
        )

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

    async def _process_fitness_duration_corrected(
        self, event: OutboxEvent
    ) -> dict[str, Any]:
        """
        Process a journal_event.fitness_duration_corrected event.

        Strava journals were once synced with moving time as their duration;
        the worker's backfill sends the elapsed time to store instead. The
        write is a compare-and-set against the durations the sync could have
        written, so a duration the user has edited — or a journal they don't
        own — is left alone. Like every inbound fitness write it publishes no
        journal event, so the day's summary is invalidated directly.
        """
        event_data: dict[str, Any] = event.event_data  # type: ignore
        payload = FitnessDurationCorrectedData.model_validate(event_data)

        changed = await SqlFitnessDataRepository(
            self.connection
        ).set_duration_if_unchanged(
            journal_id=payload.journal_id,
            user_id=payload.user_id,
            expected=payload.expected_durations,
            corrected=payload.corrected_duration,
        )
        if not changed:
            logger.info(
                "Fitness duration is not a synced value, skipping correction",
                journal_id=payload.journal_id,
                strava_activity_ids=payload.strava_activity_ids,
            )
            return {
                "status": "skipped",
                "event_type": EVENT_TYPE_JOURNAL_EVENT_FITNESS_DURATION_CORRECTED,
                "reason": "no_matching_duration",
                "journal_id": payload.journal_id,
            }

        await self._invalidate_summary_for_journal(payload.journal_id)
        logger.info(
            "Corrected fitness duration to elapsed time",
            journal_id=payload.journal_id,
            corrected_duration=payload.corrected_duration,
            strava_activity_ids=payload.strava_activity_ids,
        )
        return {
            "status": "corrected",
            "event_type": EVENT_TYPE_JOURNAL_EVENT_FITNESS_DURATION_CORRECTED,
            "journal_id": payload.journal_id,
        }

    async def _process_journal_cancelled(self, event: OutboxEvent) -> dict[str, Any]:
        """
        Process a journal_event.cancelled event.

        The link is marked cancelled, and the journal's event_state with it
        once no calendar still holds the event. A recurring instance then has
        the keep-next rule applied to its recurrence (see
        ``cancelled_recurrence``): the first upcoming occurrence of a cancelled
        run stays, and later ones the user hasn't added to are deleted.
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

        # A recurring instance has the keep-next rule applied to its recurrence.
        # The payload's recurring id (new worker) or the link column (old
        # payloads) names it. The recurrence is locked before the mark below
        # row-locks this link, so concurrent cancellations of one recurrence
        # take their locks in the same order and cannot deadlock.
        linked = await self.link_repo.find_by_external_event(
            calendar_id=UUID(calendar_id),
            external_event_id=external_event_id,
        )
        recurring_event_id = payload.recurring_event_id or (
            linked.recurring_event_id if linked else None
        )
        if recurring_event_id:
            await self.link_repo.lock_recurrence(UUID(calendar_id), recurring_event_id)
            # Read again under the lock: an adoption of this journal that was
            # still uncommitted a moment ago has now landed or not.
            linked = await self.link_repo.find_by_external_event(
                calendar_id=UUID(calendar_id),
                external_event_id=external_event_id,
            )
        if linked is None and await self._link_moved_on(
            existing_journal_id, UUID(calendar_id), external_event_id
        ):
            # The journal's link in this calendar now names another event: a
            # split's new recurrence adopted it after this cancellation was
            # queued. Marking by journal and calendar would cancel the adopted,
            # live event.
            logger.info(
                "Stale cancellation skipped - the journal now links another event",
                journal_id=existing_journal_id,
                external_event_id=external_event_id,
            )
            return {
                "status": "skipped",
                "event_type": EVENT_TYPE_JOURNAL_EVENT_CANCELLED,
                "reason": "link_moved_on",
                "journal_id": existing_journal_id,
            }

        await self._mark_journal_cancelled(
            journal_id=existing_journal_id,
            calendar_id=UUID(calendar_id),
        )

        if linked is not None and recurring_event_id:
            outcome = await self.recurrence_tidier.tidy(
                calendar_id=UUID(calendar_id),
                recurring_event_id=recurring_event_id,
                source=_provenance_for_source(payload.integration_source),
                changed_by=payload.integration_source or "system",
                cancelled_journal_id=existing_journal_id,
            )
            if outcome.errors:
                # Retried whole: the mark and the tidy are both idempotent.
                raise JournalOutboxEventProcessingError(
                    f"Tidying recurrence {recurring_event_id} after cancelling "
                    f"journal {existing_journal_id} failed; failing for retry"
                )
            if existing_journal_id in outcome.deleted:
                return {
                    "status": "success",
                    "event_type": EVENT_TYPE_JOURNAL_EVENT_CANCELLED,
                    "journal_id": existing_journal_id,
                    "external_event_id": external_event_id,
                    "action": "deleted",
                }

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
        reports a single cancelled event carrying the master id). Every
        journal linked to the series is marked cancelled except those already
        finished, then the keep-next rule deletes every continuation, keeping
        the earliest upcoming occurrence. One failing journal doesn't poison
        the rest.
        """
        event_data: dict[str, Any] = event.event_data  # type: ignore
        payload = JournalSeriesCancelledEventData.model_validate(event_data)
        calendar_id = UUID(payload.calendar_id)
        now = datetime.now(UTC)

        # Locked before any link is marked: see _process_journal_cancelled.
        await self.link_repo.lock_recurrence(calendar_id, payload.recurring_event_id)
        linked_journals = await self.link_repo.find_journals_for_series(
            calendar_id=calendar_id,
            recurring_event_id=payload.recurring_event_id,
        )

        cancelled = 0
        skipped_past = 0
        errors = 0
        for linked in linked_journals:
            # Already happened — mirrors the worker's past-event skip.
            # Falls back to the start when the end date is missing.
            range_end = linked.event_date_range_end or linked.event_date_range_start
            if range_end is not None and range_end < now - _SERIES_DELETION_BUFFER:
                skipped_past += 1
                continue
            try:
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

        outcome = await self.recurrence_tidier.tidy(
            calendar_id=calendar_id,
            recurring_event_id=payload.recurring_event_id,
            source=_provenance_for_source(payload.integration_source),
            changed_by=payload.integration_source or "system",
        )
        deleted = len(outcome.deleted)
        cancelled -= deleted
        errors += outcome.errors

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

    async def _process_journal_recurrence_tidy(
        self, event: OutboxEvent
    ) -> dict[str, Any]:
        """Process a journal_event.recurrence_tidy event.

        Queued by migration 0136 for recurrences cancelled before the
        keep-next rule existed, whose every upcoming occurrence was left behind
        as a cancelled journal. Applies the rule to the whole recurrence. The
        links are already marked, so nothing else is written first; the lock
        is still taken before the tidy reads, as every writer of a recurrence
        takes it.
        """
        event_data: dict[str, Any] = event.event_data  # type: ignore
        payload = JournalRecurrenceTidyEventData.model_validate(event_data)
        calendar_id = UUID(payload.calendar_id)
        await self.link_repo.lock_recurrence(calendar_id, payload.recurring_event_id)
        outcome = await self.recurrence_tidier.tidy(
            calendar_id=calendar_id,
            recurring_event_id=payload.recurring_event_id,
            source=_provenance_for_source(payload.integration_source),
            changed_by=payload.integration_source,
        )
        logger.info(
            "Tidied a cancelled recurrence",
            calendar_id=payload.calendar_id,
            recurring_event_id=payload.recurring_event_id,
            deleted=len(outcome.deleted),
            errors=outcome.errors,
        )
        if outcome.errors:
            raise JournalOutboxEventProcessingError(
                f"Tidying recurrence {payload.recurring_event_id}: "
                f"{outcome.errors} deletions failed; failing the event for retry"
            )
        return {
            "status": "success",
            "event_type": EVENT_TYPE_JOURNAL_EVENT_RECURRENCE_TIDY,
            "deleted": len(outcome.deleted),
        }

    async def _invalidate_summary_for_journal(self, journal_id: int) -> None:
        """Mark the journal's days stale, for a change that publishes nothing.

        Three inbound paths change what a day's agenda says without publishing a
        journal event: an update where only the **calendar info** moved (a time,
        a location, an all-day flag), one where only the **attendees** did, and
        an upstream **cancellation**, which writes ``event_state`` in raw SQL.
        Each leaves ``JournalService`` uncalled, so the consumer that owns
        summary freshness never hears about it and the day goes on describing an
        agenda that has changed.

        Publishing ``JournalUpdated`` here would be tidier and is deliberately
        not done: the Google worker consumes that event to sync a journal *out*,
        so announcing an inbound change would echo it straight back upstream.

        Failure is logged and swallowed **inside a SAVEPOINT**, which is what
        makes swallowing it possible at all: a failed statement poisons its
        transaction in PostgreSQL, so catching the exception without rolling
        back to a savepoint would leave the enclosing unit of work aborted and
        take the inbound journal and calendar writes down with it — the exact
        harm this best-effort helper exists to avoid. Raised by review, which is
        also where ``JournalService.delete_journal`` learned it.

        A summary left stale is a worse day's prose; a failed sync leaves the
        journal unwritten, which is worse than that.
        """
        from app.core.journal.adapters.sql.daily_summary_repository import (
            SqlJournalDailySummaryRepository,
        )
        from app.core.journal.adapters.sql.journal_repository import (
            SqlJournalRepository,
        )
        from app.core.journal.services.daily_summary_invalidation_service import (
            invalidate_days_of_journal,
        )
        from app.core.journal.services.journal_date_resolver import JournalDateResolver
        from app.core.settings.adapters.sql.user_settings_repository import (
            SqlUserSettingsRepository,
        )

        try:
            async with savepoint(self.connection):
                journal = await SqlJournalRepository(self.connection).find_by_id(
                    journal_id
                )
                if journal is None:
                    return
                await invalidate_days_of_journal(
                    journal,
                    date_resolver=JournalDateResolver(
                        SqlUserSettingsRepository(self.connection)
                    ),
                    summary_repo=SqlJournalDailySummaryRepository(self.connection),
                )
        except Exception:  # noqa: BLE001 — a stale summary must not fail a sync
            logger.warning(
                "Could not mark the daily summary stale for an inbound change",
                journal_id=journal_id,
                exc_info=True,
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
        - ``sync_status`` is what the keep-next rule reads to tell a cancelled
          occurrence from a live one, so a drifted write would end every
          cancelled run early and leave its continuations behind.

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

        # The agenda shows a cancelled event *marked as cancelled* rather than
        # dropping it (**W18**), so the day's prose is wrong until the summary
        # is regenerated — and this write publishes nothing.
        await self._invalidate_summary_for_journal(journal_id)

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
        series_recurring_event_id: str | None,
        series_name: str,
    ) -> None:
        """Link a synced recurring instance into its journal series.

        Get-or-creates the series keyed by (calendar_id, series key) — named
        after the event on first creation, never renamed by sync — and adds
        the journal as a member (idempotent). No-op for non-recurring events.

        The series key is ``series_recurring_event_id``: the integration folds
        a split recurrence (Google's "this and following" edits) back to the
        one it split from, so every split shares a series. Payloads sent
        before it did carry only ``recurring_event_id``, which is then the
        key; migration 0122 aliased every folded split's id to its survivor,
        so those still land in the right series. A split keeps its own id as
        well, because a split the user merged into another series must keep
        following that merge.

        **Only the journal's display calendar establishes a series.** A
        recurring event held by two calendars is one journal per instance,
        but each calendar names the series after its own master id — so
        letting the second one through would key a second series on
        ``(its calendar, its master id)`` and leave the user two series for
        one weekly meeting, both listing the same journals. Same rule as the
        calendar assignment itself: the calendar the journal is displayed in
        owns it, and the others contribute a link and nothing more.
        """
        series_key = series_recurring_event_id or recurring_event_id
        if not series_key:
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
            recurring_event_id=series_key,
            name=series_name,
            split_recurring_event_id=(
                recurring_event_id if recurring_event_id != series_key else None
            ),
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

    @classmethod
    def _merged_journal(
        cls,
        stored: Journal,
        journal_data: dict[str, Any],
        *,
        private_description: bool,
        link_updated_at: datetime | None,
    ) -> Journal | None:
        """The journal an inbound update would save over ``stored``, if any.

        Merges the inbound fields with protection against ``stored`` and
        builds the whole journal to save from it, keeping ``stored``'s place
        in the hierarchy. ``None`` when that journal changes none of the
        fields an inbound sync writes.

        Under ``private_description`` the inbound content is replaced with the
        stored content (rather than dropped), so the merge always has one.
        """
        inbound_data: dict[str, Any] = {
            "title": journal_data.get("title", ""),
            "event_date_range_start": journal_data.get("event_date_range_start"),
            "event_date_range_end": journal_data.get("event_date_range_end"),
        }
        if "content" in journal_data:
            inbound_data["content"] = journal_data["content"]
        if private_description:
            inbound_data["content"] = stored.content or ""

        merged_data = cls._merge_fields_with_protection(
            existing_journal=stored,
            inbound_data=inbound_data,
            link_updated_at=link_updated_at,
        )

        merged_journal_data = dict(journal_data)
        merged_journal_data["title"] = merged_data.get("title", stored.title)
        merged_journal_data["content"] = merged_data.get(
            "content", stored.content or ""
        )
        merged_journal_data["event_date_range_start"] = merged_data[
            "event_date_range_start"
        ]
        merged_journal_data["event_date_range_end"] = merged_data[
            "event_date_range_end"
        ]

        updated_journal = cls._build_journal_from_data(
            merged_journal_data,
            journal_id=stored.id,
            parent_id=stored.parent_id,
            order=stored.order,
        )
        fields_changed = (
            updated_journal.title != stored.title
            or updated_journal.content != stored.content
            or updated_journal.event_date_range != stored.event_date_range
        )
        return updated_journal if fields_changed else None

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

        ``activity_types`` and ``retirement_reason`` are the journal's own: an
        integration that does not send one (Snipe-IT records neither) leaves the
        stored value alone. A key that is sent, ``None`` included, replaces it.

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

        repo = SqlGearMaintenanceDataRepository(self.connection)
        stored = await repo.find_by_journal_id(journal_id)
        activity_types = raw_maintenance.get(
            "activity_types", stored.activity_types if stored else None
        )
        retirement_reason = raw_maintenance.get(
            "retirement_reason", stored.retirement_reason if stored else None
        )

        try:
            from uuid import UUID as _UUID

            gear_maintenance = GearMaintenanceData(
                journal_id=journal_id,
                gear_item_id=_UUID(str(gear_item_id)),
                maintenance_type=maintenance_type,
                activity_types=activity_types,
                retirement_reason=retirement_reason,
            )
        except ValueError, ValidationError, GearMaintenanceDataValidationError:
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

        contacts = await self.contact_repository.search(
            athlete_name, limit=10, user_id=user_id
        )
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
        "snipeit_maintenance": ("Snipe-IT Maintenance", "#808080"),
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

        The source is recorded on the row because this is where it is known.
        Deleting a journal reads it back to tell each worker which of the
        identifiers it carries are that worker's own. An existing row is left
        alone except to fill that in: a calendar created before the column
        existed, or by a path that does not know the source, is classified the
        first time an event for it arrives, while one already classified keeps
        what it has.
        """
        name, color = self._INTEGRATION_CALENDAR_DEFAULTS.get(
            integration_source, (f"{integration_source.title()} Calendar", "#808080")
        )
        await self.connection.execute(
            text("""
                INSERT INTO calendars (id, user_id, name, color, integration_source)
                VALUES (:id, :user_id, :name, :color, :integration_source)
                ON CONFLICT (id) DO UPDATE
                    SET integration_source = EXCLUDED.integration_source
                    WHERE calendars.integration_source IS NULL
            """),
            {
                "id": calendar_id,
                "user_id": user_id,
                "name": name,
                "color": color,
                "integration_source": integration_source,
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
                     start_time, end_time, timezone, event_state)
                VALUES
                    (:journal_id, :calendar_id, :is_all_day, :location,
                     :start_time, :end_time, :timezone, :event_state)
                ON CONFLICT (journal_id) DO UPDATE SET
                    is_all_day = :is_all_day,
                    location = :location,
                    start_time = :start_time,
                    end_time = :end_time,
                    timezone = :timezone,
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
                # The zone the clock times are local to (the Google event's for
                # a timed event, the user's for an all-day one); the outbound
                # push anchors the times only in a zone the row records.
                "timezone": calendar_info_data.get("timezone"),
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
                       sync_status, updated_at, recurring_event_id,
                       external_identity
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

        The journal ids are ordered before being recorded, newest first.
        Two things ride on that order. The queue's uniqueness is on the
        ordered pair, so flagging (A, B) on one sync and (B, A) on the next
        would leave two rows describing one duplicate — and which journal
        syncs first is not something this controls. And the queue's merge
        deletes the *source*, so the source has to be the newer journal, as
        match detection already records it; ordering the other way would
        quietly destroy the older journal and the history it carries.

        Ordering alone is not enough, because this is not the only thing
        that queues a pair: match detection records the incoming journal
        as the source, in whatever order the two were created. That is the
        same pair this flags — one event means one day and one title,
        which is exactly what an AI guess is drawn to — so the pair is
        looked up in either order first, and an existing item, however the
        user has since dealt with it, stands.
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
            other_journal_id = int(row.journal_id)
            already_queued = await self.review_item_repo.find_by_journal_pair(
                journal_id, other_journal_id, str(user_id)
            )
            if already_queued is not None:
                continue

            candidate_id, source_id = sorted((journal_id, other_journal_id))
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

    async def _backfill_external_event_link_metadata(
        self,
        calendar_id: UUID,
        external_event_id: str,
        recurring_event_id: str | None = None,
        external_identity: str | None = None,
    ) -> None:
        """Give a link metadata it predates, and change nothing else.

        This runs for an event that has *not* changed, so it must not
        pretend a sync happened. Writing ``sync_status`` would clear an
        unresolved conflict the user still has to deal with, and bumping
        ``updated_at`` would tell the field-protection merge that the link
        is newer than a local edit it should be protecting. The etag is
        already what the payload carries — that is why this event was
        skipped — so there is nothing to write there either.

        COALESCE keeps a stored value when the payload omits one.
        """
        await self.connection.execute(
            text("""
                UPDATE journal_external_event_links
                SET recurring_event_id = COALESCE(
                        :recurring_event_id, recurring_event_id
                    ),
                    external_identity = COALESCE(
                        :external_identity, external_identity
                    )
                WHERE calendar_id = :calendar_id
                  AND external_event_id = :external_event_id
            """),
            {
                "calendar_id": calendar_id,
                "external_event_id": external_event_id,
                "recurring_event_id": recurring_event_id,
                "external_identity": external_identity,
            },
        )

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
        *,
        user_id: str,
    ) -> dict[str, int]:
        """Resolve emails to ``user_id``'s contact IDs, skipping unknown emails."""
        resolved: dict[str, int] = {}
        for email in emails:
            contact_id = await self.contact_resolver.resolve_by_email(
                email, user_id=user_id
            )
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
        *,
        user_id: str,
    ) -> None:
        """Sync contact relationships for a journal from inbound data.

        Emails resolve within ``user_id``'s contacts only, the journal's owner:
        a journal's people are its owner's contacts. Emails that resolve to no
        contact — including one only another user's contact holds — are
        recorded as the journal's unmatched participants (see
        ``_unmatched_entries``), replacing whatever the previous sync recorded.
        """
        if contact_relationships is None:
            return

        by_type = self._group_relationships_by_type(contact_relationships)
        unmatched: dict[str, UnmatchedParticipantEmail] = {}

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
                emails, journal_id, user_id=user_id
            )
            for entry in self._unmatched_entries(
                journal_id, rel_type, payloads, resolved_contact_ids
            ):
                unmatched.setdefault(entry.email, entry)

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

        await self.unmatched_participant_repo.replace_for_journal(
            journal_id, list(unmatched.values())
        )

    def _unmatched_entries(
        self,
        journal_id: int,
        rel_type: JournalContactRelationshipType,
        payloads: list[dict[str, Any]],
        resolved_contact_ids: dict[str, int],
    ) -> list[UnmatchedParticipantEmail]:
        """The payloads' emails that resolved to no contact, as unmatched rows.

        The account owner's own address (``is_self``) is never a participant
        worth suggesting, so it is left out, as is an address too long to be
        one. The integration's display name is external text of any length,
        so it is truncated to what the column holds rather than failing the
        sync.
        """
        entries: list[UnmatchedParticipantEmail] = []
        for payload in payloads:
            if payload["email"] in resolved_contact_ids or payload.get("is_self"):
                continue
            email = normalise_participant_email(payload["email"])
            if not is_recordable_participant_email(email):
                continue
            status = self._parse_inbound_status(payload.get("status"), journal_id)
            role = self._parse_inbound_role(payload.get("role"), journal_id)
            display_name = payload.get("display_name")
            entries.append(
                UnmatchedParticipantEmail(
                    journal_id=journal_id,
                    email=email,
                    relationship_type=rel_type,
                    display_name=display_name[:MAX_PARTICIPANT_DISPLAY_NAME_LENGTH]
                    if isinstance(display_name, str)
                    else None,
                    status=AttendeeStatus(status) if status else None,
                    role=ContactEventRole(role) if role else None,
                )
            )
        return entries

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
        user_id: str,
        event_data: dict[str, Any],
    ) -> None:
        """Create or update SyncMetadata for Strava-sourced events.

        Only applies to events with ``integration_source == 'strava'``.
        Uses the ``strava_activity_id`` from fitness_data as the external_id
        and the ``version_hash`` from journal_data for change detection.

        Args:
            journal_id: ID of the journal linked to this sync record.
            user_id: The journal's owner, who owns the link.
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
            user_id=user_id,
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
