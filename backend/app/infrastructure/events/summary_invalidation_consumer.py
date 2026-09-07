"""The consumer that owns daily summary freshness.

Runs as the ``summary-invalidation`` group on ``pms:domain-events`` and marks
stale the days each event changes. It never generates a summary: the next read
of a ``PENDING`` day does that, which is ITER18-005 Phase 7's laziness.

**Why it is not part of** ``SearchIndexerConsumer``, where the journal half of
this lived until now. That consumer's contract, recorded in
``docs/architecture/integration-architecture.md`` and pinned by tests at both
the consumer and the indexer, is that **task events are permanently ignored** —
and a task change is exactly what this phase has to react to. Rather than
contradict a documented contract, summary freshness moves to a group of its own
and the journal invalidation comes with it: two owners of one question is how it
came to be handled incidentally in the first place.

The group starts at the **latest** stream id rather than at ``0``. This stream
is not trimmed, so a new group taking the default would read every event ever
published on the deploy that introduces it and mark stale every summary any of
them touched. Starting at the latest id costs one deploy window of events, which
is much the smaller of the two.
"""

import structlog
from core_shared.stream_client import StreamClient, StreamEvent
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.services.daily_summary_invalidation_service import (
    HANDLED_EVENT_TYPES,
    DailySummaryInvalidationService,
)
from app.infrastructure.database import get_async_database_engine
from app.infrastructure.events.dead_letter_consumer_mixin import DeadLetterConsumerMixin
from app.infrastructure.events.stream_consumer import StreamConsumer

logger = structlog.get_logger()


class SummaryInvalidationConsumer(DeadLetterConsumerMixin, StreamConsumer):
    """Marks daily summaries stale when the days they describe change.

    The subscription is derived from
    :data:`~app.core.journal.services.daily_summary_invalidation_service.HANDLED_EVENT_TYPES`
    rather than written out here. A consumer whose list of types is its own is a
    second list to remember to extend, and this is precisely the domain that has
    been caught by one: the handler this replaces matched three journal events,
    so a type change, a deletion and a contact change each left the day's
    summary ``GENERATED`` with no way to notice.
    """

    def __init__(
        self,
        stream_client: StreamClient,
        stream_name: str = "pms:domain-events",
        consumer_name: str = "summary-invalidation-1",
        batch_size: int = 10,
        block_ms: int = 5000,
    ) -> None:
        """Initialize the summary invalidation consumer.

        Args:
            stream_client: Redis Streams client
            stream_name: Name of the domain events stream
            consumer_name: Individual consumer name within the group
            batch_size: Maximum events to read per XREADGROUP call
            block_ms: Milliseconds to block waiting for new events
        """
        super().__init__(
            stream_client=stream_client,
            stream_name=stream_name,
            group_name="summary-invalidation",
            consumer_name=consumer_name,
            event_type_patterns=sorted(HANDLED_EVENT_TYPES),
            batch_size=batch_size,
            block_ms=block_ms,
            group_start_id="$",
        )

    @staticmethod
    def _service_for(connection: AsyncConnection) -> DailySummaryInvalidationService:
        """Build the service on this event's connection.

        Imported here rather than at module scope for the reason the search
        indexer's handler gives: the adapters pull in the journal domain, and a
        consumer module that imports them at load time drags that graph into
        every process that merely mentions the consumer.
        """
        from app.core.journal.adapters.sql.daily_summary_repository import (
            SqlJournalDailySummaryRepository,
        )
        from app.core.journal.adapters.sql.journal_repository import (
            SqlJournalRepository,
        )
        from app.core.journal.services.journal_date_resolver import JournalDateResolver
        from app.core.settings.adapters.sql.user_settings_repository import (
            SqlUserSettingsRepository,
        )

        return DailySummaryInvalidationService(
            journal_repo=SqlJournalRepository(connection),
            date_resolver=JournalDateResolver(SqlUserSettingsRepository(connection)),
            summary_repo=SqlJournalDailySummaryRepository(connection),
        )

    async def _handle_event(self, event: StreamEvent) -> None:
        """Mark stale whatever days this event changed.

        One connection per event, committed by ``engine.begin()`` on exit — the
        shape the projection and indexer consumers already use. The service
        holds no unit of work of its own, so the transaction boundary is here
        and an event either invalidates everything it should or nothing at all.

        Args:
            event: The stream event to act on
        """
        engine = get_async_database_engine()
        async with engine.begin() as conn:
            await self._service_for(conn).invalidate_for_event(
                event.event_type, event.event_data
            )

        logger.debug(
            "Summary invalidation consumer processed event",
            event_id=event.event_id,
            event_type=event.event_type,
        )
