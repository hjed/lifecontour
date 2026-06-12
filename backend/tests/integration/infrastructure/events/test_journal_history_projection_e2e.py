"""End-to-end backend integration test for journal history projection.

Exercises the full async chain a real journal mutation travels:

    JournalService.update_journal()
        -> OutboxEventPublisher (outbox_events row, same txn)
        -> OutboxRelay.relay_batch()  (-> pms:domain-events stream)
        -> HistoryProjectionConsumer  (-> field_history rows)

and asserts the change is retrievable, correctly grouped to the journal, with
the right old/new values and provenance. This is the closest backend equivalent
to a user-facing E2E for ITER12-002 Phase 1 (which has no UI surface yet).
"""

from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from core_shared.models import Route
from core_shared.models.history import Provenance
from core_shared.models.journals import (
    EventDateRange,
    Journal,
    JournalType,
    MoodData,
)
from core_shared.stream_client import StreamClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.history.adapters.sql.field_history_repository import (
    SqlFieldHistoryRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.mood_data_repository import SqlMoodDataRepository
from app.core.journal.adapters.sql.route_repository import SqlRouteRepository
from app.core.journal.services.journal_service import JournalService
from app.core.journal.services.journal_write_service import JournalWriteService
from app.core.journal.services.route_service import RouteService
from app.infrastructure.events.history_projection_consumer import (
    HistoryProjectionConsumer,
)
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.events.outbox_relay import OutboxRelay

GROUP_NAME = "history-projection"


def _make_journal(title: str = "Original title") -> Journal:
    return Journal(
        id=None,
        user_id="user-e2e",
        title=title,
        content="c",
        event_date_range=EventDateRange(
            start=datetime(2024, 1, 1), end=datetime(2024, 1, 1)
        ),
    )


async def _relay_and_project(
    stream_client: StreamClient,
    stream_name: str,
    async_connection: AsyncConnection,
    consumer_name: str,
) -> None:
    """Relay outbox events to the stream and run the projection consumer once.

    Both the relay and the consumer operate on the test ``async_connection`` (the
    consumer's engine is patched to yield it) so all writes share the test
    savepoint and roll back at teardown.
    """
    relay = OutboxRelay(
        stream_client=stream_client, stream_name=stream_name, batch_size=50
    )
    await relay.relay_batch(async_connection)

    consumer = HistoryProjectionConsumer(
        stream_client=stream_client,
        stream_name=stream_name,
        consumer_name=consumer_name,
        block_ms=100,
    )
    await stream_client.ensure_consumer_group(stream_name, GROUP_NAME)

    mock_engine = MagicMock()

    @asynccontextmanager
    async def mock_begin():
        yield async_connection

    mock_engine.begin = mock_begin

    with patch(
        "app.infrastructure.events.history_projection_consumer.get_async_database_engine",
        return_value=mock_engine,
    ):
        await consumer._process_batch()


def _mock_write_service_with_mood(
    mood_data_repo: SqlMoodDataRepository, event_publisher: OutboxEventPublisher
) -> JournalWriteService:
    """Build a JournalWriteService where only the MOOD_RATING path is real.

    ``update_type_data`` for MOOD_RATING touches only ``mood_data_repo`` and
    ``event_publisher``; every other dependency is mocked so the test can exercise
    the real type-data → event → outbox path without wiring 20+ repositories.
    """
    return JournalWriteService(
        journal_service=MagicMock(),
        journal_contact_service=MagicMock(),
        calendar_info_repo=MagicMock(),
        photo_album_data_repo=MagicMock(),
        mood_data_repo=mood_data_repo,
        plan_data_repo=MagicMock(),
        travel_data_repo=MagicMock(),
        fitness_data_repo=MagicMock(),
        outdoor_activity_data_repo=MagicMock(),
        bushwalking_data_repo=MagicMock(),
        jogging_data_repo=MagicMock(),
        abseiling_data_repo=MagicMock(),
        abseil_pitch_repo=MagicMock(),
        canyoning_data_repo=MagicMock(),
        caving_data_repo=MagicMock(),
        canoeing_data_repo=MagicMock(),
        climbing_data_repo=MagicMock(),
        kayaking_data_repo=MagicMock(),
        skiing_data_repo=MagicMock(),
        snorkelling_data_repo=MagicMock(),
        diving_data_repo=MagicMock(),
        downhill_skiing_data_repo=MagicMock(),
        outdoor_planning_data_repo=MagicMock(),
        outdoor_training_data_repo=MagicMock(),
        gear_maintenance_data_repo=MagicMock(),
        event_publisher=event_publisher,
    )


@pytest.mark.integration
class TestJournalHistoryProjectionE2E:
    @pytest.mark.asyncio
    async def test_journal_update_is_projected_to_retrievable_history(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        journal_service = JournalService(
            journal_repo=SqlJournalRepository(async_connection),
            event_publisher=OutboxEventPublisher(async_connection),
        )

        # 1. Create then update a journal through the real service (UI provenance).
        journal = Journal(
            id=None,
            user_id="user-e2e",
            title="Original title",
            content="c",
            event_date_range=EventDateRange(
                start=datetime(2024, 1, 1), end=datetime(2024, 1, 1)
            ),
        )
        created = await journal_service.create_journal(
            journal, async_connection, changed_by="ui", source=Provenance.UI
        )
        assert created.id is not None
        journal_id = created.id

        created.title = "Updated title"
        await journal_service.update_journal(
            created,
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
        )

        # 2. Relay the outbox events to the Redis stream.
        relay = OutboxRelay(
            stream_client=stream_client,
            stream_name=test_stream_name,
            batch_size=50,
        )
        relayed = await relay.relay_batch(async_connection)
        assert relayed >= 2  # JournalCreated + JournalUpdated

        # 3. Consume the stream and project into field_history.
        consumer = HistoryProjectionConsumer(
            stream_client=stream_client,
            stream_name=test_stream_name,
            consumer_name="test-history-e2e",
            block_ms=100,
        )
        await stream_client.ensure_consumer_group(test_stream_name, GROUP_NAME)

        mock_engine = MagicMock()

        @asynccontextmanager
        async def mock_begin():
            yield async_connection

        mock_engine.begin = mock_begin

        with patch(
            "app.infrastructure.events.history_projection_consumer.get_async_database_engine",
            return_value=mock_engine,
        ):
            await consumer._process_batch()

        # 4. History is retrievable via the journal aggregation strategy.
        history_repo = SqlFieldHistoryRepository(async_connection)
        entries = await history_repo.get_history_for_aggregate(
            "journal", journal_id, limit=50, offset=0
        )

        by_field = {e.field_name: e for e in entries}
        # The create marker and the title change are both present and grouped.
        assert "__created__" in by_field
        assert "title" in by_field

        title_entry = by_field["title"]
        assert title_entry.entity_type == "journal"
        assert title_entry.entity_id == journal_id
        assert title_entry.old_value == "Original title"
        assert title_entry.new_value == "Updated title"
        assert title_entry.source == Provenance.UI
        assert title_entry.changed_by == "ui"

        pending_info = await redis_client.xpending(test_stream_name, GROUP_NAME)
        assert pending_info["pending"] == 0

    @pytest.mark.asyncio
    async def test_type_specific_update_is_projected_to_journal_history(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """A MOOD_RATING type-data edit is projected and grouped to the journal."""
        publisher = OutboxEventPublisher(async_connection)
        journal_service = JournalService(
            journal_repo=SqlJournalRepository(async_connection),
            event_publisher=publisher,
        )
        created = await journal_service.create_journal(
            _make_journal("Mood journal"),
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
        )
        assert created.id is not None
        journal_id = created.id

        mood_repo = SqlMoodDataRepository(async_connection)
        await mood_repo.save(MoodData(journal_id=journal_id, mood_value=3))

        write_service = _mock_write_service_with_mood(mood_repo, publisher)
        await write_service.update_type_data(
            journal_id,
            JournalType.MOOD_RATING,
            {"mood_value": 8},
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
        )

        await _relay_and_project(
            stream_client, test_stream_name, async_connection, "test-typedata-e2e"
        )

        entries = await SqlFieldHistoryRepository(
            async_connection
        ).get_history_for_aggregate("journal", journal_id, limit=50, offset=0)
        by_field = {e.field_name: e for e in entries}

        assert "mood_value" in by_field
        mood_entry = by_field["mood_value"]
        assert mood_entry.entity_type == "journal"
        assert mood_entry.entity_id == journal_id
        assert mood_entry.old_value == "3"
        assert mood_entry.new_value == "8"
        assert mood_entry.source == Provenance.UI
        assert mood_entry.changed_by == "ui"

    @pytest.mark.asyncio
    async def test_route_update_is_projected_and_grouped_to_journal(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """A route edit is projected and grouped to its parent journal."""
        publisher = OutboxEventPublisher(async_connection)
        journal_service = JournalService(
            journal_repo=SqlJournalRepository(async_connection),
            event_publisher=publisher,
        )
        created = await journal_service.create_journal(
            _make_journal("Route journal"),
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
        )
        assert created.id is not None
        journal_id = created.id

        route_service = RouteService(
            route_repo=SqlRouteRepository(async_connection),
            event_publisher=publisher,
        )
        saved_route = await route_service.create_route(
            Route(journal_id=journal_id, name="Old Route"),
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
        )
        saved_route.name = "New Route"
        await route_service.update_route(
            saved_route,
            {"name": ("Old Route", "New Route")},
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
        )

        await _relay_and_project(
            stream_client, test_stream_name, async_connection, "test-route-e2e"
        )

        entries = await SqlFieldHistoryRepository(
            async_connection
        ).get_history_for_aggregate("journal", journal_id, limit=50, offset=0)
        by_field = {e.field_name: e for e in entries}

        route_field = f"route:{saved_route.id}:name"
        assert route_field in by_field
        route_entry = by_field[route_field]
        assert route_entry.entity_type == "journal"
        assert route_entry.entity_id == journal_id
        assert route_entry.old_value == "Old Route"
        assert route_entry.new_value == "New Route"
        assert route_entry.source == Provenance.UI
