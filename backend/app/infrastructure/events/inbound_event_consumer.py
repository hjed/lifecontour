"""
Inbound Event consumer for Redis Streams.

Processes contact sync events (contact.*), journal sync events (journal_event.*),
and match detection events (journal_review.*) from the pms:domain-events stream.
Runs as the 'inbound-processor' consumer group.

Reuses existing OutboxEventProcessor for contact events and
JournalOutboxEventProcessor / MatchDetectionEventProcessor for journal events,
maintaining exact behavioral parity with the legacy OutboxProcessor routing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from core_shared.stream_client import StreamClient, StreamEvent
from dishka import AsyncContainer

from app.infrastructure.config import Settings
from app.infrastructure.database import get_async_database_engine
from app.infrastructure.events.dead_letter_consumer_mixin import DeadLetterConsumerMixin
from app.infrastructure.events.stream_consumer import StreamConsumer
from app.infrastructure.events.stream_event_adapter import stream_event_to_outbox_event

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

    from app.infrastructure.events.outbox_repository import OutboxEvent

logger = structlog.get_logger()

# Event type patterns handled by this consumer (prefix match).
_INBOUND_EVENT_PATTERNS: list[str] = [
    "contact.",
    "journal_event.",
    "journal_review.",
    "immich_album.",
]


class InboundEventConsumer(DeadLetterConsumerMixin, StreamConsumer):
    """Stream consumer for inbound integration sync events.

    Listens to ``contact.*``, ``journal_event.*``, and ``journal_review.*``
    events on the ``pms:domain-events`` stream using the ``inbound-processor``
    consumer group.

    Delegates to the existing domain processors:
    - ``OutboxEventProcessor`` for contact sync events
    - ``JournalOutboxEventProcessor`` for journal sync events
    - ``MatchDetectionEventProcessor`` for match detection events
    """

    def __init__(
        self,
        stream_client: StreamClient,
        container: AsyncContainer,
        settings: Settings,
        stream_name: str = "pms:domain-events",
        consumer_name: str = "inbound-processor-1",
        batch_size: int = 10,
        block_ms: int = 5000,
    ) -> None:
        """Initialize the inbound event consumer.

        Args:
            stream_client: Redis Streams client
            container: Dishka AsyncContainer for dependency injection
            settings: Application settings (injected)
            stream_name: Name of the domain events stream
            consumer_name: Individual consumer name within the group
            batch_size: Maximum events to read per XREADGROUP call
            block_ms: Milliseconds to block waiting for new events
        """
        super().__init__(
            stream_client=stream_client,
            stream_name=stream_name,
            group_name="inbound-processor",
            consumer_name=consumer_name,
            event_type_patterns=_INBOUND_EVENT_PATTERNS,
            batch_size=batch_size,
            block_ms=block_ms,
        )
        self._container = container
        self._settings = settings

    async def _handle_event(self, event: StreamEvent) -> None:
        """Process an inbound sync event.

        Routes events to the appropriate domain processor based on event type:
        - ``contact.*`` → OutboxEventProcessor
        - ``journal_event.*`` → JournalOutboxEventProcessor
        - ``journal_review.*`` → MatchDetectionEventProcessor

        Args:
            event: The stream event to process
        """
        outbox_event = stream_event_to_outbox_event(event)

        engine = get_async_database_engine()
        async with engine.begin() as conn:
            if event.event_type.startswith("contact."):
                await self._process_contact_event(outbox_event, conn)
            elif event.event_type.startswith("journal_event."):
                await self._process_journal_sync_event(outbox_event, conn)
            elif event.event_type.startswith("journal_review."):
                await self._process_journal_review_event(outbox_event, conn)
            elif event.event_type.startswith("immich_album."):
                await self._process_immich_album_event(outbox_event, conn)

        logger.debug(
            "Inbound consumer processed event",
            event_id=event.event_id,
            event_type=event.event_type,
        )

    async def _process_contact_event(
        self, event: OutboxEvent, connection: AsyncConnection
    ) -> None:
        """Process contact sync events using OutboxEventProcessor.

        Replicates the dependency tree from
        OutboxProcessor._process_contact_event.

        Args:
            event: Adapted OutboxEvent
            connection: Database connection for transaction
        """
        from app.core.contacts.adapters.sql.contact_field_history_repository import (
            SqlContactFieldHistoryRepository,
        )
        from app.core.contacts.adapters.sql.contact_repository import (
            SqlContactRepository,
        )
        from app.core.contacts.adapters.sql.tag_repository import SqlTagRepository
        from app.core.contacts.services.address_validation_service import (
            AddressValidationService,
        )
        from app.core.contacts.services.contact_history_service import (
            ContactHistoryService,
        )
        from app.core.contacts.services.contact_service import ContactService
        from app.core.contacts.services.contact_validation_service import (
            ContactValidationService,
        )
        from app.core.contacts.services.tag_hierarchy_service import (
            TagHierarchyService,
        )
        from app.core.integrations.outbox_event_processor import OutboxEventProcessor
        from app.infrastructure.events.outbox_event_publisher import (
            OutboxEventPublisher,
        )

        # Create repositories
        contact_repository = SqlContactRepository(connection)
        tag_repository = SqlTagRepository(connection)
        history_repository = SqlContactFieldHistoryRepository(connection)
        event_publisher = OutboxEventPublisher(connection)

        # Create services
        address_validation_service = AddressValidationService()
        contact_validation_service = ContactValidationService(contact_repository)
        history_service = ContactHistoryService(history_repository)
        tag_hierarchy_service = TagHierarchyService(tag_repository)

        # Create contact service
        contact_service = ContactService(
            contact_repo=contact_repository,
            tag_repo=tag_repository,
            history_repo=history_repository,
            event_publisher=event_publisher,
            address_validation_service=address_validation_service,
            contact_validation_service=contact_validation_service,
            history_service=history_service,
            tag_hierarchy_service=tag_hierarchy_service,
        )

        # Create outbox event processor
        event_processor = OutboxEventProcessor(contact_service, connection)

        # Process the event
        result = await event_processor.process_event(event)  # type: ignore[arg-type]

        logger.info(
            "Processed contact sync event (stream consumer)",
            event_id=event.event_id,
            event_type=event.event_type,
            result=result,
        )

    async def _process_journal_sync_event(
        self, event: OutboxEvent, connection: AsyncConnection
    ) -> None:
        """Process inbound journal sync events using JournalOutboxEventProcessor.

        Replicates the dependency tree from
        OutboxProcessor._process_journal_sync_event for journal_event.* events.

        Args:
            event: Adapted OutboxEvent
            connection: Database connection for transaction
        """
        from app.core.integrations.journal_outbox_event_processor import (
            JournalOutboxEventProcessor,
        )
        from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
            SqlJournalContactRelationshipRepository,
        )
        from app.core.journal.adapters.sql.journal_repository import (
            SqlJournalRepository,
        )
        from app.core.journal.services.journal_service import JournalService
        from app.core.journal.services.match_candidate_detector import (
            MatchCandidateDetector,
        )
        from app.core.journal.services.title_similarity_assessor import (
            GeminiTitleSimilarityAssessor,
        )
        from app.infrastructure.events.outbox_event_publisher import (
            OutboxEventPublisher,
        )

        journal_repo = SqlJournalRepository(connection)
        event_publisher = OutboxEventPublisher(connection)
        contact_relationship_repo = SqlJournalContactRelationshipRepository(connection)
        journal_service = JournalService(
            journal_repo=journal_repo,
            event_publisher=event_publisher,
            contact_relationship_repo=contact_relationship_repo,
        )

        # Need optional detector for gating Phase 2 emission
        match_detector = None
        if self._settings.gemini_api_key:
            from app.core.settings.adapters.sql.user_settings_repository import (
                SqlUserSettingsRepository,
            )

            timezone = await SqlUserSettingsRepository(
                connection
            ).get_default_timezone()
            similarity_assessor = GeminiTitleSimilarityAssessor(
                api_key=self._settings.gemini_api_key,
                model=self._settings.gemini_model,
                timezone=timezone,
            )
            match_detector = MatchCandidateDetector(
                similarity_assessor=similarity_assessor,
            )

        from app.core.contacts.adapters.sql.contact_repository import (
            SqlContactRepository,
        )
        from app.core.integrations.adapters.sql.strava_athlete_mapping_repository import (
            SqlStravaAthleteMappingRepository,
        )

        contact_repository = SqlContactRepository(connection)
        strava_athlete_mapping_repository = SqlStravaAthleteMappingRepository(
            connection
        )

        outbox_processor = JournalOutboxEventProcessor(
            journal_service=journal_service,
            connection=connection,
            contact_repository=contact_repository,
            strava_athlete_mapping_repository=strava_athlete_mapping_repository,
            match_candidate_detector=match_detector,
        )
        result = await outbox_processor.process_event(event)  # type: ignore[arg-type]

        logger.info(
            "Processed journal sync event (stream consumer)",
            event_id=event.event_id,
            event_type=event.event_type,
            result=result,
        )

    async def _process_immich_album_event(
        self, event: OutboxEvent, connection: AsyncConnection
    ) -> None:
        """Process inbound Immich album sync events.

        Creates/updates PHOTO_ALBUM journals via
        ``ImmichAlbumOutboxEventProcessor`` for ``immich_album.*`` events.

        Args:
            event: Adapted OutboxEvent
            connection: Database connection for transaction
        """
        from core_shared.repositories.external_reference_repository import (
            ExternalReferenceRepository,
        )

        from app.core.integrations.immich_album_outbox_event_processor import (
            ImmichAlbumOutboxEventProcessor,
        )
        from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
            SqlJournalContactRelationshipRepository,
        )
        from app.core.journal.adapters.sql.journal_repository import (
            SqlJournalRepository,
        )
        from app.core.journal.services.journal_service import JournalService
        from app.infrastructure.events.outbox_event_publisher import (
            OutboxEventPublisher,
        )

        journal_repo = SqlJournalRepository(connection)
        event_publisher = OutboxEventPublisher(connection)
        contact_relationship_repo = SqlJournalContactRelationshipRepository(connection)
        journal_service = JournalService(
            journal_repo=journal_repo,
            event_publisher=event_publisher,
            contact_relationship_repo=contact_relationship_repo,
        )

        processor = ImmichAlbumOutboxEventProcessor(
            journal_service=journal_service,
            connection=connection,
            relationship_repo=contact_relationship_repo,
            ext_ref_repo=ExternalReferenceRepository(connection),
        )
        result = await processor.process_event(event)  # type: ignore[arg-type]

        logger.info(
            "Processed Immich album sync event (stream consumer)",
            event_id=event.event_id,
            event_type=event.event_type,
            result=result,
        )

    async def _process_journal_review_event(
        self, event: OutboxEvent, connection: AsyncConnection
    ) -> None:
        """Process journal review events using MatchDetectionEventProcessor.

        Replicates the dependency tree from
        OutboxProcessor._process_journal_sync_event for journal_review.* events.

        Args:
            event: Adapted OutboxEvent
            connection: Database connection for transaction
        """
        from app.core.integrations.match_detection_event_processor import (
            MatchDetectionEventProcessor,
        )
        from app.core.journal.adapters.sql.review_item_repository import (
            SqlReviewItemRepository,
        )
        from app.core.journal.services.match_candidate_detector import (
            MatchCandidateDetector,
        )
        from app.core.journal.services.title_similarity_assessor import (
            GeminiTitleSimilarityAssessor,
        )

        review_item_repo = SqlReviewItemRepository(connection)
        match_detector = None
        if self._settings.gemini_api_key:
            from app.core.settings.adapters.sql.user_settings_repository import (
                SqlUserSettingsRepository,
            )

            timezone = await SqlUserSettingsRepository(
                connection
            ).get_default_timezone()
            similarity_assessor = GeminiTitleSimilarityAssessor(
                api_key=self._settings.gemini_api_key,
                model=self._settings.gemini_model,
                timezone=timezone,
            )
            match_detector = MatchCandidateDetector(
                similarity_assessor=similarity_assessor,
            )

        processor = MatchDetectionEventProcessor(
            connection=connection,
            match_candidate_detector=match_detector,
            review_item_repository=review_item_repo,
        )
        result = await processor.process_event(event)  # type: ignore[arg-type]

        logger.info(
            "Processed journal review event (stream consumer)",
            event_id=event.event_id,
            event_type=event.event_type,
            result=result,
        )
