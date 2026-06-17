"""
Integration tests for Strava GPX route persistence and sync metadata tracking.

Tests the end-to-end flow: outbox event → JournalOutboxEventProcessor →
Route + SyncMetadata rows in the database. Uses real PostgreSQL via the
test Docker containers and the standard integration test fixtures.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from core_shared.models.outbox import OutboxEvent
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_repository import SqlContactRepository
from app.core.integrations.adapters.sql.strava_athlete_mapping_repository import (
    SqlStravaAthleteMappingRepository,
)
from app.core.integrations.journal_outbox_event_processor import (
    JournalOutboxEventProcessor,
)

# Must match _STRAVA_SYNTHETIC_CALENDAR_ID in strava_sync_service.py
STRAVA_CALENDAR_ID = "00000000-0000-0000-0000-000000000001"

GPX_XML_SAMPLE = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<gpx version="1.1" creator="StravaGPXGenerator">'
    "<trk><name>Morning Run</name><trkseg>"
    '<trkpt lat="-33.8688" lon="151.2093">'
    "<ele>50.0</ele><time>2026-03-20T08:00:00Z</time>"
    "</trkpt>"
    '<trkpt lat="-33.8700" lon="151.2100">'
    "<ele>48.0</ele><time>2026-03-20T08:05:00Z</time>"
    "</trkpt>"
    "</trkseg></trk></gpx>"
)


def _make_strava_event_data(
    *,
    strava_activity_id: str = "12345",
    gpx_xml: str | None = GPX_XML_SAMPLE,
    version_hash: str = "a" * 64,
    existing_journal_id: int | None = None,
    title: str = "Morning Run",
    journal_types: list[str] | None = None,
    climbing_data: dict[str, Any] | None = None,
    sync_action: str = "created",
) -> dict[str, Any]:
    """Build a Strava-sourced outbox event payload."""
    journal_data: dict[str, Any] = {
        "title": title,
        "content": "Easy jog in the park",
        "event_date_range_start": "2026-03-20T08:00:00+00:00",
        "event_date_range_end": "2026-03-20T09:00:00+00:00",
        "user_id": "test-user-123",
        "fitness_data": {
            "distance": 10000,
            "elevation_gain": 150,
            "elevation_loss": 10,
            "duration": 3400,
            "calories": 500,
            "heart_rate_avg": 145,
            "heart_rate_max": 175,
            "strava_activity_id": strava_activity_id,
        },
        "journal_types": (
            journal_types if journal_types is not None else ["jogging", "fitness"]
        ),
        "gpx_xml": gpx_xml,
        "version_hash": version_hash,
    }
    if climbing_data is not None:
        journal_data["climbing_data"] = climbing_data
    return {
        "journal_data": journal_data,
        "calendar_info_data": {
            "calendar_id": STRAVA_CALENDAR_ID,
            "is_all_day": False,
            "location": None,
            "start_time": "08:00:00",
            "end_time": "09:00:00",
        },
        "integration_source": "strava",
        "external_event_id": f"strava:{strava_activity_id}",
        "calendar_id": STRAVA_CALENDAR_ID,
        "sync_action": sync_action,
        "sync_timestamp": datetime.now(UTC).isoformat(),
        "etag": None,
        "existing_journal_id": existing_journal_id,
        "contact_relationships": [],
    }


async def _create_processor(
    connection: AsyncConnection,
) -> JournalOutboxEventProcessor:
    """Create a real JournalOutboxEventProcessor backed by the test connection."""
    from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
        SqlJournalContactRelationshipRepository,
    )
    from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
    from app.core.journal.services.journal_service import JournalService
    from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher

    journal_repo = SqlJournalRepository(connection)
    event_publisher = OutboxEventPublisher(connection)
    contact_relationship_repo = SqlJournalContactRelationshipRepository(connection)
    service = JournalService(
        journal_repo=journal_repo,
        event_publisher=event_publisher,
        contact_relationship_repo=contact_relationship_repo,
    )
    return JournalOutboxEventProcessor(
        journal_service=service,
        connection=connection,
        contact_repository=SqlContactRepository(connection),
        strava_athlete_mapping_repository=SqlStravaAthleteMappingRepository(connection),
    )


async def _ensure_strava_calendar(connection: AsyncConnection) -> None:
    """Create the synthetic Strava calendar row if it doesn't already exist.

    The Strava sync pipeline uses a synthetic calendar ID to satisfy the
    processor's calendar_info_data + external_event_link FK requirements.
    """
    await connection.execute(
        text("""
            INSERT INTO calendars (id, user_id, google_calendar_id, name, color)
            VALUES (:id, 'test-user-123', 'strava-synthetic', 'Strava Activities', '#FC4C02')
            ON CONFLICT (id) DO NOTHING
        """),
        {"id": STRAVA_CALENDAR_ID},
    )


class TestStravaGPXRouteIntegration:
    """Integration tests for Strava GPX route and sync metadata persistence."""

    @pytest.mark.asyncio
    async def test_import_activity_with_gps_creates_route(
        self,
        async_connection: AsyncConnection,
    ) -> None:
        """Full import with gpx_xml creates a Route row linked to the journal."""
        await _ensure_strava_calendar(async_connection)
        processor = await _create_processor(async_connection)

        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.created",
            event_data=_make_strava_event_data(),
            created_at=datetime.now(UTC),
            retry_count=0,
        )

        result = await processor.process_event(event)
        assert result["status"] == "success"
        journal_id = result["journal_id"]

        # Verify route row exists
        route_result = await async_connection.execute(
            text(
                "SELECT name, gpx_data, journal_id FROM routes WHERE journal_id = :jid"
            ),
            {"jid": journal_id},
        )
        route_row = route_result.fetchone()
        assert route_row is not None, "Route row should exist for GPS-enabled activity"
        assert route_row.name == "Morning Run"
        assert "<trkpt" in route_row.gpx_data
        assert route_row.journal_id == journal_id

    @pytest.mark.asyncio
    async def test_import_activity_without_gps_no_route(
        self,
        async_connection: AsyncConnection,
    ) -> None:
        """Import without gpx_xml should not create a Route row."""
        await _ensure_strava_calendar(async_connection)
        processor = await _create_processor(async_connection)

        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.created",
            event_data=_make_strava_event_data(gpx_xml=None),
            created_at=datetime.now(UTC),
            retry_count=0,
        )

        result = await processor.process_event(event)
        assert result["status"] == "success"
        journal_id = result["journal_id"]

        route_result = await async_connection.execute(
            text("SELECT COUNT(*) FROM routes WHERE journal_id = :jid"),
            {"jid": journal_id},
        )
        assert route_result.scalar() == 0, "No route should exist for non-GPS activity"

    @pytest.mark.asyncio
    async def test_import_creates_sync_metadata_record(
        self,
        async_connection: AsyncConnection,
    ) -> None:
        """Import creates a SyncMetadata row with correct fields."""
        await _ensure_strava_calendar(async_connection)
        version_hash = "b" * 64
        processor = await _create_processor(async_connection)

        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.created",
            event_data=_make_strava_event_data(
                strava_activity_id="77777",
                version_hash=version_hash,
            ),
            created_at=datetime.now(UTC),
            retry_count=0,
        )

        result = await processor.process_event(event)
        assert result["status"] == "success"
        journal_id = result["journal_id"]

        sync_result = await async_connection.execute(
            text("""
                SELECT internal_id, integration_source, external_id,
                       version_hash, sync_status
                FROM sync_metadata
                WHERE integration_source = 'strava' AND external_id = '77777'
            """),
        )
        sync_row = sync_result.fetchone()
        assert sync_row is not None, "SyncMetadata row should exist"
        assert sync_row.internal_id == journal_id
        assert sync_row.integration_source == "strava"
        assert sync_row.external_id == "77777"
        assert sync_row.version_hash == version_hash
        assert sync_row.sync_status == "success"

    @pytest.mark.asyncio
    async def test_reimport_same_activity_updates_not_duplicates(
        self,
        async_connection: AsyncConnection,
    ) -> None:
        """Importing the same strava_activity_id twice should update, not duplicate."""
        await _ensure_strava_calendar(async_connection)
        processor = await _create_processor(async_connection)

        # First import
        event1 = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.created",
            event_data=_make_strava_event_data(
                strava_activity_id="55555",
                version_hash="1" * 64,
                title="First Title",
            ),
            created_at=datetime.now(UTC),
            retry_count=0,
        )
        result1 = await processor.process_event(event1)
        assert result1["status"] == "success"
        journal_id = result1["journal_id"]

        # Second import as update
        update_data = _make_strava_event_data(
            strava_activity_id="55555",
            version_hash="2" * 64,
            existing_journal_id=journal_id,
            title="Updated Title",
        )
        update_data["sync_action"] = "updated"
        event2 = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.updated",
            event_data=update_data,
            created_at=datetime.now(UTC),
            retry_count=0,
        )
        result2 = await processor.process_event(event2)
        assert result2["status"] == "success"

        # Verify only one route exists
        route_result = await async_connection.execute(
            text("SELECT COUNT(*) FROM routes WHERE journal_id = :jid"),
            {"jid": journal_id},
        )
        assert route_result.scalar() == 1, (
            "Should have exactly one route after re-import"
        )

        # Verify sync metadata was updated
        sync_result = await async_connection.execute(
            text("""
                SELECT version_hash
                FROM sync_metadata
                WHERE integration_source = 'strava' AND external_id = '55555'
            """),
        )
        sync_row = sync_result.fetchone()
        assert sync_row is not None
        assert sync_row.version_hash == "2" * 64, "Version hash should be updated"

    @pytest.mark.asyncio
    async def test_update_activity_updates_route_gpx(
        self,
        async_connection: AsyncConnection,
    ) -> None:
        """Updated event with new GPX data should update the existing route."""
        await _ensure_strava_calendar(async_connection)
        processor = await _create_processor(async_connection)

        # Create initial activity
        event1 = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.created",
            event_data=_make_strava_event_data(
                strava_activity_id="88888",
                title="Trail Run",
            ),
            created_at=datetime.now(UTC),
            retry_count=0,
        )
        result1 = await processor.process_event(event1)
        assert result1["status"] == "success"
        journal_id = result1["journal_id"]

        # Get original route data
        original = await async_connection.execute(
            text("SELECT gpx_data FROM routes WHERE journal_id = :jid"),
            {"jid": journal_id},
        )
        original_gpx = original.fetchone()
        assert original_gpx is not None

        # Update with new GPX
        new_gpx = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<gpx version="1.1" creator="StravaGPXGenerator">'
            "<trk><name>Trail Run</name><trkseg>"
            '<trkpt lat="-33.9" lon="151.3">'
            "<ele>100.0</ele><time>2026-03-20T08:00:00Z</time>"
            "</trkpt>"
            "</trkseg></trk></gpx>"
        )
        update_data = _make_strava_event_data(
            strava_activity_id="88888",
            gpx_xml=new_gpx,
            existing_journal_id=journal_id,
            title="Trail Run",
        )
        update_data["sync_action"] = "updated"
        event2 = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.updated",
            event_data=update_data,
            created_at=datetime.now(UTC),
            retry_count=0,
        )
        result2 = await processor.process_event(event2)
        assert result2["status"] == "success"

        # Verify route GPX was updated
        updated = await async_connection.execute(
            text("SELECT gpx_data FROM routes WHERE journal_id = :jid"),
            {"jid": journal_id},
        )
        updated_row = updated.fetchone()
        assert updated_row is not None
        assert 'lat="-33.9"' in updated_row.gpx_data

    @pytest.mark.asyncio
    async def test_fitness_data_elevation_loss_persisted(
        self,
        async_connection: AsyncConnection,
    ) -> None:
        """Elevation loss from the Strava altitude stream should be persisted."""
        await _ensure_strava_calendar(async_connection)
        processor = await _create_processor(async_connection)

        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.created",
            event_data=_make_strava_event_data(strava_activity_id="99999"),
            created_at=datetime.now(UTC),
            retry_count=0,
        )

        result = await processor.process_event(event)
        assert result["status"] == "success"
        journal_id = result["journal_id"]

        fitness_result = await async_connection.execute(
            text(
                "SELECT elevation_loss FROM journal_fitness_data WHERE journal_id = :jid"
            ),
            {"jid": journal_id},
        )
        fitness_row = fitness_result.fetchone()
        assert fitness_row is not None
        assert fitness_row.elevation_loss == 10, "Elevation loss should be persisted"


_CLIMBING_TYPES = ["climbing", "abseiling_trip", "outdoor_activity", "fitness"]
_SELECT_INDOOR_SQL = "SELECT indoor FROM journal_climbing_data WHERE journal_id = :jid"


@pytest.mark.integration
class TestStravaClimbingIndoorIntegration:
    """Indoor climbing flag persistence and re-sync toggling via the processor."""

    @pytest.mark.asyncio
    async def test_indoor_climbing_sets_indoor_true(
        self,
        async_connection: AsyncConnection,
    ) -> None:
        """A climbing import with indoor=True persists indoor on the climbing row."""
        await _ensure_strava_calendar(async_connection)
        processor = await _create_processor(async_connection)

        event = OutboxEvent(
            id=uuid4(),
            event_type="journal_event.created",
            event_data=_make_strava_event_data(
                strava_activity_id="climb-indoor-1",
                gpx_xml=None,
                journal_types=_CLIMBING_TYPES,
                climbing_data={"indoor": True},
            ),
            created_at=datetime.now(UTC),
            retry_count=0,
        )

        result = await processor.process_event(event)
        assert result["status"] == "success"
        journal_id = result["journal_id"]

        row = (
            await async_connection.execute(
                text(_SELECT_INDOOR_SQL),
                {"jid": journal_id},
            )
        ).fetchone()
        assert row is not None, "Climbing row should exist for a climbing import"
        assert row.indoor is True

    @pytest.mark.asyncio
    async def test_resync_toggles_indoor_flag(
        self,
        async_connection: AsyncConnection,
    ) -> None:
        """Re-syncing the same activity toggles indoor to reflect current state."""
        await _ensure_strava_calendar(async_connection)
        processor = await _create_processor(async_connection)

        created = await processor.process_event(
            OutboxEvent(
                id=uuid4(),
                event_type="journal_event.created",
                event_data=_make_strava_event_data(
                    strava_activity_id="climb-toggle-1",
                    gpx_xml=None,
                    journal_types=_CLIMBING_TYPES,
                    climbing_data={"indoor": True},
                ),
                created_at=datetime.now(UTC),
                retry_count=0,
            )
        )
        assert created["status"] == "success"
        journal_id = created["journal_id"]

        # Re-sync the same activity, now detected as outdoor (GPS present).
        updated = await processor.process_event(
            OutboxEvent(
                id=uuid4(),
                event_type="journal_event.updated",
                event_data=_make_strava_event_data(
                    strava_activity_id="climb-toggle-1",
                    gpx_xml=None,
                    journal_types=_CLIMBING_TYPES,
                    climbing_data={"indoor": False},
                    existing_journal_id=journal_id,
                    version_hash="c" * 64,
                    sync_action="updated",
                ),
                created_at=datetime.now(UTC),
                retry_count=0,
            )
        )
        assert updated["status"] == "success"

        row = (
            await async_connection.execute(
                text(_SELECT_INDOOR_SQL),
                {"jid": journal_id},
            )
        ).fetchone()
        assert row is not None
        assert row.indoor is False, "Re-sync should toggle indoor to False"

    @pytest.mark.asyncio
    async def test_non_boolean_indoor_is_ignored_not_coerced(
        self,
        async_connection: AsyncConnection,
    ) -> None:
        """A malformed indoor value is ignored, not coerced (bool('false') is True)."""
        await _ensure_strava_calendar(async_connection)
        processor = await _create_processor(async_connection)

        created = await processor.process_event(
            OutboxEvent(
                id=uuid4(),
                event_type="journal_event.created",
                event_data=_make_strava_event_data(
                    strava_activity_id="climb-malformed-1",
                    gpx_xml=None,
                    journal_types=_CLIMBING_TYPES,
                    climbing_data={"indoor": False},
                ),
                created_at=datetime.now(UTC),
                retry_count=0,
            )
        )
        assert created["status"] == "success"
        journal_id = created["journal_id"]

        # Re-sync with a non-boolean string. bool("false") would coerce to True;
        # the guard must leave the stored False untouched.
        updated = await processor.process_event(
            OutboxEvent(
                id=uuid4(),
                event_type="journal_event.updated",
                event_data=_make_strava_event_data(
                    strava_activity_id="climb-malformed-1",
                    gpx_xml=None,
                    journal_types=_CLIMBING_TYPES,
                    climbing_data={"indoor": "false"},
                    existing_journal_id=journal_id,
                    version_hash="d" * 64,
                    sync_action="updated",
                ),
                created_at=datetime.now(UTC),
                retry_count=0,
            )
        )
        assert updated["status"] == "success"

        row = (
            await async_connection.execute(
                text(_SELECT_INDOOR_SQL),
                {"jid": journal_id},
            )
        ).fetchone()
        assert row is not None
        assert row.indoor is False, "Malformed indoor must not flip the flag"
