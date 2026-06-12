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
    ClimbingData,
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
from app.core.journal.adapters.sql.climbing_data_repository import (
    SqlClimbingDataRepository,
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


def _mock_write_service(
    event_publisher: OutboxEventPublisher, **real_repos: object
) -> JournalWriteService:
    """Build a JournalWriteService with only the named repos real, rest mocked.

    A single-type `update_type_data` call touches only that type's data repo and
    the event publisher, so the test can exercise the real type-data → event →
    outbox path for any one type without wiring 20+ repositories. Pass the repos
    that type needs as keyword arguments (e.g. ``mood_data_repo=...``).
    """
    repo_names = (
        "journal_service",
        "journal_contact_service",
        "calendar_info_repo",
        "photo_album_data_repo",
        "mood_data_repo",
        "plan_data_repo",
        "travel_data_repo",
        "fitness_data_repo",
        "outdoor_activity_data_repo",
        "bushwalking_data_repo",
        "jogging_data_repo",
        "abseiling_data_repo",
        "abseil_pitch_repo",
        "canyoning_data_repo",
        "caving_data_repo",
        "canoeing_data_repo",
        "climbing_data_repo",
        "kayaking_data_repo",
        "skiing_data_repo",
        "snorkelling_data_repo",
        "diving_data_repo",
        "downhill_skiing_data_repo",
        "outdoor_planning_data_repo",
        "outdoor_training_data_repo",
        "gear_maintenance_data_repo",
        "gear_usage_data_repo",
        "tag_repo",
    )
    kwargs: dict[str, object] = {name: MagicMock() for name in repo_names}
    kwargs.update(real_repos)
    return JournalWriteService(event_publisher=event_publisher, **kwargs)  # type: ignore[arg-type]


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

        write_service = _mock_write_service(publisher, mood_data_repo=mood_repo)
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
    async def test_newly_covered_type_is_projected_to_journal_history(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """A CLIMBING edit (a type added to the registry) is projected to history.

        Proves the registry expansion (all editable outdoor subtypes) works
        through the real service → outbox → relay → consumer path, not just in the
        unit-level coverage guard.
        """
        publisher = OutboxEventPublisher(async_connection)
        journal_service = JournalService(
            journal_repo=SqlJournalRepository(async_connection),
            event_publisher=publisher,
        )
        created = await journal_service.create_journal(
            _make_journal("Climbing journal"),
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
        )
        assert created.id is not None
        journal_id = created.id

        climbing_repo = SqlClimbingDataRepository(async_connection)
        await climbing_repo.save(ClimbingData(journal_id=journal_id, grade=15))

        write_service = _mock_write_service(publisher, climbing_data_repo=climbing_repo)
        await write_service.update_type_data(
            journal_id,
            JournalType.CLIMBING,
            {"grade": 21},
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
        )

        await _relay_and_project(
            stream_client, test_stream_name, async_connection, "test-climbing-e2e"
        )

        entries = await SqlFieldHistoryRepository(
            async_connection
        ).get_history_for_aggregate("journal", journal_id, limit=50, offset=0)
        by_field = {e.field_name: e for e in entries}

        assert "grade" in by_field
        grade_entry = by_field["grade"]
        assert grade_entry.entity_id == journal_id
        assert grade_entry.old_value == "15"
        assert grade_entry.new_value == "21"
        assert grade_entry.source == Provenance.UI

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
