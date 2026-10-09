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

from datetime import datetime
from unittest.mock import AsyncMock
from uuid import uuid4

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
from app.core.journal.adapters.sql.journal_tag_repository import SqlJournalTagRepository
from app.core.journal.adapters.sql.mood_data_repository import SqlMoodDataRepository
from app.core.journal.adapters.sql.route_repository import SqlRouteRepository
from app.core.journal.models.journal_tag import JournalTag
from app.core.journal.services.journal_service import JournalService
from app.core.journal.services.journal_tag_hierarchy_service import (
    JournalTagHierarchyService,
)
from app.core.journal.services.journal_tag_service import JournalTagService
from app.core.journal.services.journal_write_service import JournalWriteService
from app.core.journal.services.route_service import RouteService
from app.core.journal.utils.route_edits import RouteEdit
from app.core.tasks.adapters.sql.task_anchor_repository import (
    SqlTaskAnchorRepository,
)
from app.infrastructure.events.history_projection_consumer import (
    HistoryProjectionConsumer,
)
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.events.outbox_relay import OutboxRelay
from tests.integration.infrastructure.events.projection_harness import (
    GROUP_NAME,
    patched_projection_engine,
    relay_and_project,
    replay_stream_through_projection,
)
from tests.integration.mcp.http_helpers import (
    call_mcp_tool,
)

# Owns the journals and tags below: a tag is only assigned to its owner's journals.
JOURNAL_OWNER = "user-e2e"


def _make_journal(title: str = "Original title") -> Journal:
    return Journal(
        id=None,
        user_id=JOURNAL_OWNER,
        title=title,
        content="c",
        event_date_range=EventDateRange(
            start=datetime(2024, 1, 1), end=datetime(2024, 1, 1)
        ),
    )


def _mock_write_service(
    event_publisher: OutboxEventPublisher, **real_repos: object
) -> JournalWriteService:
    """Build a JournalWriteService with only the named repos real, rest mocked.

    A single-type `update_type_data` call touches only that type's data repo and
    the event publisher, so the test can exercise the real type-data → event →
    outbox path for any one type without wiring 20+ repositories. Pass the repos
    that type needs as keyword arguments (e.g. ``mood_data_repo=...``).

    The stand-ins are ``AsyncMock`` rather than ``MagicMock`` because the
    service awaits its collaborators — a plain ``MagicMock`` returns something
    that cannot be awaited, so any call the test does not care about still
    fails the test.
    """
    repo_names = (
        "journal_service",
        "journal_contact_service",
        "tag_service",
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
    kwargs: dict[str, object] = {name: AsyncMock() for name in repo_names}
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
            task_anchor_repo=SqlTaskAnchorRepository(async_connection),
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

        with patched_projection_engine(async_connection):
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
            task_anchor_repo=SqlTaskAnchorRepository(async_connection),
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

        await relay_and_project(
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
            task_anchor_repo=SqlTaskAnchorRepository(async_connection),
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

        await relay_and_project(
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
    async def test_plan_document_changes_are_projected_per_row(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """PLAN document add/edit/remove project per-row ``plan:doc:<id>:<field>``
        history, grouped to the journal (ITER12-002 Phase 4)."""
        import uuid

        from core_shared.models.journals import PlanData, PlanDocument

        from app.core.journal.adapters.sql.plan_data_repository import (
            SqlPlanDataRepository,
        )

        publisher = OutboxEventPublisher(async_connection)
        journal_service = JournalService(
            journal_repo=SqlJournalRepository(async_connection),
            event_publisher=publisher,
            task_anchor_repo=SqlTaskAnchorRepository(async_connection),
        )
        created = await journal_service.create_journal(
            _make_journal("Plan journal"),
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
        )
        assert created.id is not None
        journal_id = created.id

        plan_repo = SqlPlanDataRepository(async_connection)
        await plan_repo.save(PlanData(journal_id=journal_id))
        kept_id = uuid.uuid4()
        removed_id = uuid.uuid4()
        await plan_repo.save_document(
            PlanDocument(
                id=kept_id,
                journal_id=journal_id,
                url="https://kept",
                title="Old",
                order=0,
            )
        )
        await plan_repo.save_document(
            PlanDocument(
                id=removed_id,
                journal_id=journal_id,
                url="https://removed",
                title="Gone",
                order=1,
            )
        )

        write_service = _mock_write_service(publisher, plan_data_repo=plan_repo)
        # Edit the kept document's title (same url), drop the removed one, add a new.
        await write_service.update_type_data(
            journal_id,
            JournalType.PLAN,
            {
                "documents": [
                    {"url": "https://kept", "title": "New", "order": 0},
                    {"url": "https://added", "title": "Added", "order": 1},
                ]
            },
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
        )

        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-plan-e2e"
        )

        entries = await SqlFieldHistoryRepository(
            async_connection
        ).get_history_for_aggregate("journal", journal_id, limit=50, offset=0)
        by_field = {e.field_name: e for e in entries}

        # Edited document: a clean (old, new) title pair, grouped to the journal.
        edit_field = f"plan:doc:{kept_id}:title"
        assert edit_field in by_field
        assert by_field[edit_field].entity_type == "journal"
        assert by_field[edit_field].entity_id == journal_id
        assert by_field[edit_field].old_value == "Old"
        assert by_field[edit_field].new_value == "New"
        assert by_field[edit_field].source == Provenance.UI

        # Removed document: (old, None).
        removed_field = f"plan:doc:{removed_id}:title"
        assert by_field[removed_field].old_value == "Gone"
        assert by_field[removed_field].new_value is None

        # Added document: a created (None, value) title row exists.
        added = [
            e
            for k, e in by_field.items()
            if k.startswith("plan:doc:")
            and k.endswith(":title")
            and e.new_value == "Added"
        ]
        assert len(added) == 1
        assert added[0].old_value is None

    @pytest.mark.asyncio
    async def test_abseil_pitch_changes_are_projected_per_pitch(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """An ABSEIL pitch edit projects ``abseil:pitch:<n>:<field>`` history,
        keyed by pitch number and grouped to the journal (ITER12-002 Phase 4)."""
        from core_shared.models.journals import AbseilingData, AbseilPitch

        from app.core.journal.adapters.sql.abseil_pitch_repository import (
            SqlAbseilPitchRepository,
        )
        from app.core.journal.adapters.sql.abseiling_data_repository import (
            SqlAbseilingDataRepository,
        )

        publisher = OutboxEventPublisher(async_connection)
        journal_service = JournalService(
            journal_repo=SqlJournalRepository(async_connection),
            event_publisher=publisher,
            task_anchor_repo=SqlTaskAnchorRepository(async_connection),
        )
        created = await journal_service.create_journal(
            _make_journal("Abseil journal"),
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
        )
        assert created.id is not None
        journal_id = created.id

        abseiling_repo = SqlAbseilingDataRepository(async_connection)
        pitch_repo = SqlAbseilPitchRepository(async_connection)
        await abseiling_repo.save(AbseilingData(journal_id=journal_id))
        await pitch_repo.save(
            AbseilPitch(journal_id=journal_id, pitch_number=1, height=20)
        )

        write_service = _mock_write_service(
            publisher,
            abseiling_data_repo=abseiling_repo,
            abseil_pitch_repo=pitch_repo,
        )
        await write_service.update_type_data(
            journal_id,
            JournalType.ABSEILING_TRIP,
            {"pitches": [{"pitch_number": 1, "height": 35}]},
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
        )

        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-abseil-e2e"
        )

        entries = await SqlFieldHistoryRepository(
            async_connection
        ).get_history_for_aggregate("journal", journal_id, limit=50, offset=0)
        by_field = {e.field_name: e for e in entries}

        pitch_field = "abseil:pitch:1:height"
        assert pitch_field in by_field
        assert by_field[pitch_field].entity_type == "journal"
        assert by_field[pitch_field].entity_id == journal_id
        assert by_field[pitch_field].old_value == "20"
        assert by_field[pitch_field].new_value == "35"
        assert by_field[pitch_field].source == Provenance.UI

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
            task_anchor_repo=SqlTaskAnchorRepository(async_connection),
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
        assert saved_route.id is not None
        await route_service.update_route(
            saved_route.id,
            RouteEdit(name="New Route"),
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
        )

        await relay_and_project(
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

    @pytest.mark.asyncio
    async def test_immich_album_metadata_change_is_projected_with_immich_provenance(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """An Immich album metadata change (name/asset count) is projected to the
        PHOTO_ALBUM journal's history with ``Provenance.IMMICH`` (Phase 4)."""
        import uuid
        from datetime import UTC, datetime

        from core_shared.models.outbox import OutboxEvent

        from app.core.integrations.immich.album_outbox_event_processor import (
            EVENT_TYPE_IMMICH_ALBUM_CREATED,
            EVENT_TYPE_IMMICH_ALBUM_UPDATED,
            ImmichAlbumOutboxEventProcessor,
        )

        album_id = f"album-{uuid.uuid4().hex[:8]}"

        def _album_event(
            event_type: str, *, version_hash: str, title: str, asset_count: int
        ) -> OutboxEvent:
            return OutboxEvent(
                id=uuid.uuid4(),
                event_type=event_type,
                aggregate_id="0",
                event_data={
                    "integration_source": "immich_album",
                    "external_id": album_id,
                    "version_hash": version_hash,
                    "sync_action": event_type.split(".")[1],
                    "journal_data": {
                        "user_id": "immich-e2e-user",
                        "title": title,
                        "content": "",
                        "event_date_range_start": datetime(
                            2026, 1, 15, tzinfo=UTC
                        ).isoformat(),
                        "event_date_range_end": datetime(
                            2026, 1, 16, tzinfo=UTC
                        ).isoformat(),
                    },
                    "album_metadata": {
                        "album_name": title,
                        "asset_count": asset_count,
                    },
                    "sync_timestamp": datetime.now(UTC).isoformat(),
                },
                occurred_at=datetime.now(UTC),
                retry_count=0,
            )

        processor = ImmichAlbumOutboxEventProcessor(
            journal_service=JournalService(
                journal_repo=SqlJournalRepository(async_connection),
                event_publisher=OutboxEventPublisher(async_connection),
                task_anchor_repo=SqlTaskAnchorRepository(async_connection),
            ),
            connection=async_connection,
            event_publisher=OutboxEventPublisher(async_connection),
        )

        created = await processor.process_event(
            _album_event(
                EVENT_TYPE_IMMICH_ALBUM_CREATED,
                version_hash="v1",
                title="Summer Trip",
                asset_count=3,
            )
        )
        journal_id = created["journal_id"]

        # A later sync changes the album name and asset count.
        await processor.process_event(
            _album_event(
                EVENT_TYPE_IMMICH_ALBUM_UPDATED,
                version_hash="v2",
                title="Autumn Trip",
                asset_count=5,
            )
        )

        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-immich-e2e"
        )

        entries = await SqlFieldHistoryRepository(
            async_connection
        ).get_history_for_aggregate("journal", journal_id, limit=50, offset=0)
        by_field = {e.field_name: e for e in entries}

        assert "album_name" in by_field
        assert by_field["album_name"].old_value == "Summer Trip"
        assert by_field["album_name"].new_value == "Autumn Trip"
        assert by_field["album_name"].source == Provenance.IMMICH
        assert by_field["album_name"].changed_by == "immich_album"

        assert "asset_count" in by_field
        assert by_field["asset_count"].old_value == "3"
        assert by_field["asset_count"].new_value == "5"
        assert by_field["asset_count"].source == Provenance.IMMICH


@pytest.mark.integration
class TestJournalTagHistoryProjectionE2E:
    """Journal tag assignment, removal and rename reach journal history.

    Drives the real chain (``JournalTagService`` -> outbox -> relay -> projection)
    with real repositories, so the assertions cover the SQL that decides whether an
    event is published at all — and which journals it reaches — not just the event
    construction.
    """

    async def _tag_service(self, conn: AsyncConnection) -> JournalTagService:
        tag_repo = SqlJournalTagRepository(conn)
        return JournalTagService(
            tag_repo=tag_repo,
            hierarchy_service=JournalTagHierarchyService(tag_repo=tag_repo),
            event_publisher=OutboxEventPublisher(conn),
        )

    async def _journal_id(self, conn: AsyncConnection, title: str) -> int:
        saved = await SqlJournalRepository(conn).save(_make_journal(title))
        assert saved.id is not None
        return saved.id

    async def _tags_history(
        self, conn: AsyncConnection, journal_id: int
    ) -> list[tuple[str | None, str | None, Provenance, str | None]]:
        """The journal's ``tags`` history rows, most recent first."""
        entries = await SqlFieldHistoryRepository(conn).get_history_for_aggregate(
            "journal", journal_id, limit=50, offset=0
        )
        return [
            (e.old_value, e.new_value, e.source, e.changed_by)
            for e in entries
            if e.field_name == "tags"
        ]

    @pytest.mark.asyncio
    async def test_assignment_and_removal_are_projected_with_ui_provenance(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        tag_service = await self._tag_service(async_connection)
        journal_id = await self._journal_id(async_connection, "Tag history subject")
        tag = await SqlJournalTagRepository(async_connection).save(
            JournalTag(user_id=JOURNAL_OWNER, name=f"Hiking-{uuid4()}")
        )
        assert tag.id is not None

        await tag_service.assign_tag(
            journal_id,
            tag.id,
            async_connection,
            source=Provenance.UI,
            changed_by="ui",
            user_id=JOURNAL_OWNER,
        )
        await tag_service.remove_tag(
            journal_id,
            tag.id,
            async_connection,
            source=Provenance.UI,
            changed_by="ui",
            user_id=JOURNAL_OWNER,
        )

        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-journal-tags-e2e"
        )

        # Most recent first: the removal, then the assignment.
        assert await self._tags_history(async_connection, journal_id) == [
            (tag.name, None, Provenance.UI, "ui"),
            (None, tag.name, Provenance.UI, "ui"),
        ]

    @pytest.mark.asyncio
    async def test_replaying_the_stream_adds_no_duplicate_rows(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """Projection is idempotent, keyed on the originating ``event_id``.

        Redis Streams guarantee at-least-once delivery, so a consumer restart or a
        reclaimed pending message re-runs the projection. Duplicated tag entries in
        the feed would be as wrong as missing ones.
        """
        tag_service = await self._tag_service(async_connection)
        journal_id = await self._journal_id(async_connection, "Replay subject")
        tag = await SqlJournalTagRepository(async_connection).save(
            JournalTag(user_id=JOURNAL_OWNER, name=f"Replay-{uuid4()}")
        )
        assert tag.id is not None

        await tag_service.assign_tag(
            journal_id,
            tag.id,
            async_connection,
            source=Provenance.UI,
            changed_by="ui",
            user_id=JOURNAL_OWNER,
        )
        await tag_service.remove_tag(
            journal_id,
            tag.id,
            async_connection,
            source=Provenance.UI,
            changed_by="ui",
            user_id=JOURNAL_OWNER,
        )
        await relay_and_project(
            stream_client,
            test_stream_name,
            async_connection,
            "test-journal-tags-replay",
        )
        after_first = await self._tags_history(async_connection, journal_id)
        assert len(after_first) == 2

        await replay_stream_through_projection(
            stream_client, test_stream_name, async_connection, redis_client
        )

        assert await self._tags_history(async_connection, journal_id) == after_first

    @pytest.mark.asyncio
    async def test_mcp_tag_replace_projects_mcp_provenance_and_no_spurious_rows(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        """The MCP composite path records its own provenance and nothing more.

        Re-sending the identical tag list is the common shape of an MCP update that
        edits some other field. The pre-event implementation removed and re-added
        every tag, which would now write a bogus "Removed"/"Added" pair; the diff
        must leave the feed untouched.
        """
        publisher = OutboxEventPublisher(async_connection)
        tag_repo = SqlJournalTagRepository(async_connection)
        journal_service = JournalService(
            journal_repo=SqlJournalRepository(async_connection),
            event_publisher=publisher,
            task_anchor_repo=SqlTaskAnchorRepository(async_connection),
        )
        created = await journal_service.create_journal(
            _make_journal("MCP tag journal"),
            async_connection,
            changed_by="mcp",
            source=Provenance.MCP,
        )
        assert created.id is not None
        journal_id = created.id

        tag_name = f"McpTag-{uuid4()}"
        write_service = _mock_write_service(
            publisher,
            journal_service=journal_service,
            tag_service=await self._tag_service(async_connection),
            tag_repo=tag_repo,
        )

        await write_service.update_journal_composite(
            created,
            async_connection,
            tags=[tag_name],
            changed_by="mcp",
            source=Provenance.MCP,
        )
        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-mcp-tags-e2e"
        )

        assert await self._tags_history(async_connection, journal_id) == [
            (None, tag_name, Provenance.MCP, "mcp")
        ]

        # Re-send the same list: nothing changed, so nothing new may be recorded.
        await write_service.update_journal_composite(
            created,
            async_connection,
            tags=[tag_name],
            changed_by="mcp",
            source=Provenance.MCP,
        )
        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-mcp-tags-e2e"
        )

        assert await self._tags_history(async_connection, journal_id) == [
            (None, tag_name, Provenance.MCP, "mcp")
        ]

    @pytest.mark.asyncio
    async def test_rename_is_projected_onto_every_journal_carrying_the_tag(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        """One tag write fans out to a history row on each tagged journal.

        Two journals rather than one so the fan-out is observable, and a third
        journal without the tag pins that the rename does not reach journals it
        never touched.
        """
        tag_service = await self._tag_service(async_connection)
        tagged_ids = [
            await self._journal_id(async_connection, "Renamed subject 1"),
            await self._journal_id(async_connection, "Renamed subject 2"),
        ]
        untagged_id = await self._journal_id(async_connection, "Untagged bystander")
        old_name = f"Hiking-{uuid4()}"
        tag = await SqlJournalTagRepository(async_connection).save(
            JournalTag(user_id=JOURNAL_OWNER, name=old_name)
        )
        assert tag.id is not None
        for journal_id in tagged_ids:
            await tag_service.assign_tag(
                journal_id,
                tag.id,
                async_connection,
                source=Provenance.UI,
                changed_by="ui",
                user_id=JOURNAL_OWNER,
            )

        new_name = f"Trekking-{uuid4()}"
        await tag_service.update_tag(
            tag.id,
            async_connection,
            name=new_name,
            source=Provenance.UI,
            changed_by="ui",
            user_id=JOURNAL_OWNER,
        )

        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-tag-rename-e2e"
        )

        for journal_id in tagged_ids:
            # Most recent first: the rename, then the assignment that preceded it.
            assert await self._tags_history(async_connection, journal_id) == [
                (old_name, new_name, Provenance.UI, "ui"),
                (None, old_name, Provenance.UI, "ui"),
            ]
        assert await self._tags_history(async_connection, untagged_id) == []

    @pytest.mark.asyncio
    async def test_replaying_a_rename_adds_no_duplicate_rows(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """A redelivered rename must not double the entry in the feed.

        The fan-out gives every journal its own ``event_id``, which is what lets
        the dedup index key them independently on replay.
        """
        tag_service = await self._tag_service(async_connection)
        journal_id = await self._journal_id(async_connection, "Rename replay subject")
        old_name = f"ReplayRename-{uuid4()}"
        tag = await SqlJournalTagRepository(async_connection).save(
            JournalTag(user_id=JOURNAL_OWNER, name=old_name)
        )
        assert tag.id is not None
        await tag_service.assign_tag(
            journal_id,
            tag.id,
            async_connection,
            source=Provenance.UI,
            changed_by="ui",
            user_id=JOURNAL_OWNER,
        )
        await tag_service.update_tag(
            tag.id,
            async_connection,
            name=f"ReplayRenamed-{uuid4()}",
            source=Provenance.UI,
            changed_by="ui",
            user_id=JOURNAL_OWNER,
        )
        await relay_and_project(
            stream_client,
            test_stream_name,
            async_connection,
            "test-tag-rename-replay",
        )
        after_first = await self._tags_history(async_connection, journal_id)
        assert len(after_first) == 2

        await replay_stream_through_projection(
            stream_client, test_stream_name, async_connection, redis_client
        )

        assert await self._tags_history(async_connection, journal_id) == after_first

    @pytest.mark.asyncio
    async def test_delete_is_projected_onto_every_journal_carrying_the_tag(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        """Destroying a tag records it leaving each journal that carried it.

        Two journals so the fan-out is observable, and a third without the tag to
        pin that the delete does not reach journals it never touched. The rows are
        written from ids read *before* the delete — afterwards the cascade has
        taken the assignment rows with it.
        """
        tag_service = await self._tag_service(async_connection)
        tagged_ids = [
            await self._journal_id(async_connection, "Deleted subject 1"),
            await self._journal_id(async_connection, "Deleted subject 2"),
        ]
        untagged_id = await self._journal_id(async_connection, "Untagged bystander")
        tag_name = f"Doomed-{uuid4()}"
        tag = await SqlJournalTagRepository(async_connection).save(
            JournalTag(user_id=JOURNAL_OWNER, name=tag_name)
        )
        assert tag.id is not None
        for journal_id in tagged_ids:
            await tag_service.assign_tag(
                journal_id,
                tag.id,
                async_connection,
                source=Provenance.UI,
                changed_by="ui",
                user_id=JOURNAL_OWNER,
            )

        await tag_service.delete_tag(
            tag.id,
            async_connection,
            source=Provenance.UI,
            changed_by="ui",
            user_id=JOURNAL_OWNER,
        )

        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-tag-delete-e2e"
        )

        for journal_id in tagged_ids:
            # Most recent first: the delete, then the assignment that preceded it.
            assert await self._tags_history(async_connection, journal_id) == [
                (tag_name, None, Provenance.UI, "ui"),
                (None, tag_name, Provenance.UI, "ui"),
            ]
        assert await self._tags_history(async_connection, untagged_id) == []

    @pytest.mark.asyncio
    async def test_replaying_a_delete_adds_no_duplicate_rows(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """A redelivered delete must not double the entry in the feed."""
        tag_service = await self._tag_service(async_connection)
        journal_id = await self._journal_id(async_connection, "Delete replay subject")
        tag = await SqlJournalTagRepository(async_connection).save(
            JournalTag(user_id=JOURNAL_OWNER, name=f"ReplayDoomed-{uuid4()}")
        )
        assert tag.id is not None
        await tag_service.assign_tag(
            journal_id,
            tag.id,
            async_connection,
            source=Provenance.UI,
            changed_by="ui",
            user_id=JOURNAL_OWNER,
        )
        await tag_service.delete_tag(
            tag.id,
            async_connection,
            source=Provenance.UI,
            changed_by="ui",
            user_id=JOURNAL_OWNER,
        )
        await relay_and_project(
            stream_client,
            test_stream_name,
            async_connection,
            "test-tag-delete-replay",
        )
        after_first = await self._tags_history(async_connection, journal_id)
        assert len(after_first) == 2

        await replay_stream_through_projection(
            stream_client, test_stream_name, async_connection, redis_client
        )

        assert await self._tags_history(async_connection, journal_id) == after_first

    @pytest.mark.asyncio
    async def test_merge_projects_a_swap_or_a_removal_per_journal(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        """One merge reads two different ways depending on what a journal held.

        The journal carrying only the source swapped one tag for another. The
        journal that already carried the target gained nothing — the source
        simply left it — so claiming a swap there would record a change that did
        not occur.
        """
        tag_service = await self._tag_service(async_connection)
        source_only_id = await self._journal_id(async_connection, "Source only")
        both_id = await self._journal_id(async_connection, "Both tags")
        repo = SqlJournalTagRepository(async_connection)
        source_name = f"Hiking-{uuid4()}"
        target_name = f"Bushwalking-{uuid4()}"
        source_tag = await repo.save(
            JournalTag(user_id=JOURNAL_OWNER, name=source_name)
        )
        target_tag = await repo.save(
            JournalTag(user_id=JOURNAL_OWNER, name=target_name)
        )
        assert source_tag.id is not None
        assert target_tag.id is not None
        for journal_id in (source_only_id, both_id):
            await tag_service.assign_tag(
                journal_id,
                source_tag.id,
                async_connection,
                source=Provenance.UI,
                changed_by="ui",
                user_id=JOURNAL_OWNER,
            )
        await tag_service.assign_tag(
            both_id,
            target_tag.id,
            async_connection,
            source=Provenance.UI,
            changed_by="ui",
            user_id=JOURNAL_OWNER,
        )

        await tag_service.merge_tag(
            source_tag.id,
            target_tag.id,
            async_connection,
            source=Provenance.UI,
            changed_by="ui",
            user_id=JOURNAL_OWNER,
        )

        await relay_and_project(
            stream_client, test_stream_name, async_connection, "test-tag-merge-e2e"
        )

        # Most recent first: the merge, then the assignments that preceded it.
        assert await self._tags_history(async_connection, source_only_id) == [
            (source_name, target_name, Provenance.UI, "ui"),
            (None, source_name, Provenance.UI, "ui"),
        ]
        assert await self._tags_history(async_connection, both_id) == [
            (source_name, None, Provenance.UI, "ui"),
            (None, target_name, Provenance.UI, "ui"),
            (None, source_name, Provenance.UI, "ui"),
        ]

    @pytest.mark.asyncio
    async def test_replaying_a_merge_adds_no_duplicate_rows(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
    ) -> None:
        """A redelivered merge must not double the entry in the feed."""
        tag_service = await self._tag_service(async_connection)
        journal_id = await self._journal_id(async_connection, "Merge replay subject")
        repo = SqlJournalTagRepository(async_connection)
        source_tag = await repo.save(
            JournalTag(user_id=JOURNAL_OWNER, name=f"ReplaySource-{uuid4()}")
        )
        target_tag = await repo.save(
            JournalTag(user_id=JOURNAL_OWNER, name=f"ReplayTarget-{uuid4()}")
        )
        assert source_tag.id is not None
        assert target_tag.id is not None
        await tag_service.assign_tag(
            journal_id,
            source_tag.id,
            async_connection,
            source=Provenance.UI,
            changed_by="ui",
            user_id=JOURNAL_OWNER,
        )
        await tag_service.merge_tag(
            source_tag.id,
            target_tag.id,
            async_connection,
            source=Provenance.UI,
            changed_by="ui",
            user_id=JOURNAL_OWNER,
        )
        await relay_and_project(
            stream_client,
            test_stream_name,
            async_connection,
            "test-tag-merge-replay",
        )
        after_first = await self._tags_history(async_connection, journal_id)
        assert len(after_first) == 2

        await replay_stream_through_projection(
            stream_client, test_stream_name, async_connection, redis_client
        )

        assert await self._tags_history(async_connection, journal_id) == after_first


@pytest.mark.integration
class TestMcpTypeDataHistoryProjectionE2E:
    """ITER12-002 Phase 4: type-data writes through the MCP update tool produce
    journal history with ``Provenance.MCP``, retrievable via the history endpoint.

    Drives the real path the MCP tool follows over HTTP (DI-resolved
    ``JournalWriteService.update_type_data`` → outbox), then relays + projects on
    the shared test connection and reads the history endpoint as the same user.
    """

    async def _seed_mood_journal(self, conn: AsyncConnection) -> int:
        """Create a journal owned by the authenticated test user with a MOOD_RATING
        row (mood_value=3) ready to be edited via MCP."""
        from app.core.journal.adapters.sql.journal_repository import (
            SqlJournalRepository,
        )

        journal = Journal(
            id=None,
            user_id="test-user-123",
            title="MCP mood journal",
            content="c",
            event_date_range=EventDateRange(
                start=datetime(2024, 1, 1), end=datetime(2024, 1, 1)
            ),
        )
        saved = await SqlJournalRepository(conn).save(journal)
        assert saved.id is not None
        await SqlMoodDataRepository(conn).save(
            MoodData(journal_id=saved.id, mood_value=3)
        )
        return saved.id

    @pytest.mark.asyncio
    async def test_mcp_type_data_edit_is_projected_with_mcp_provenance(
        self,
        authenticated_lifespan_client,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        redis_client: Redis,
        test_stream_name: str,
    ) -> None:
        journal_id = await self._seed_mood_journal(async_connection)

        async with authenticated_lifespan_client() as client:
            # Edit the MOOD_RATING type data through the MCP update tool.
            payload = await call_mcp_tool(
                client,
                "update_journal_entry",
                {
                    "journal_id": journal_id,
                    "request": {"type_data": {"MOOD_RATING": {"mood_value": 8}}},
                },
            )
            assert "error" not in payload, payload

            # Relay the outbox JournalUpdated event and project it into history.
            await relay_and_project(
                stream_client, test_stream_name, async_connection, "test-mcp-typedata"
            )

            # The change is retrievable via the history endpoint as the same user.
            history_response = await client.get(f"/api/journals/{journal_id}/history")
            assert history_response.status_code == 200
            entries = history_response.json()["data"]

        by_field = {e["attributes"]["field_name"]: e["attributes"] for e in entries}
        assert "mood_value" in by_field
        mood = by_field["mood_value"]
        assert mood["old_value"] == "3"
        assert mood["new_value"] == "8"
        assert mood["source"] == "mcp"
        assert mood["changed_by"] == "mcp"
