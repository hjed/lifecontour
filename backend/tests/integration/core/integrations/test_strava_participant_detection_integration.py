import uuid
from datetime import UTC, datetime

import pytest
from core_shared.models.contacts.entities import Contact
from core_shared.models.journals.journal_relationship_types import (
    JournalContactRelationshipType,
)
from core_shared.models.outbox import OutboxEvent
from core_shared.models.strava_athlete_mapping import StravaAthleteMapping
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_repository import SqlContactRepository
from app.core.integrations.adapters.sql.strava_athlete_mapping_repository import (
    SqlStravaAthleteMappingRepository,
)
from app.core.integrations.journal_outbox_event_processor import (
    EVENT_TYPE_JOURNAL_EVENT_CREATED,
    JournalOutboxEventProcessor,
)
from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_service import JournalService
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher


async def _create_processor(
    connection: AsyncConnection,
) -> JournalOutboxEventProcessor:
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
    )


async def _ensure_strava_calendar(connection: AsyncConnection) -> None:
    from sqlalchemy import text

    await connection.execute(
        text("""
            INSERT INTO calendars (id, user_id, google_calendar_id, name, color)
            VALUES (:id, 'test-user-id', 'strava-synthetic', 'Strava Activities', '#FC4C02')
            ON CONFLICT (id) DO NOTHING
        """),
        {"id": "00000000-0000-0000-0000-000000000001"},
    )


@pytest.mark.asyncio
async def test_participant_detection_by_exact_name(
    async_connection: AsyncConnection,
    clean_database: None,
) -> None:
    """Test that a Strava athlete is matched by exact name and added as a participant."""
    await _ensure_strava_calendar(async_connection)
    processor = await _create_processor(async_connection)
    user_id = "test-user-id"
    # Create contact with exact name
    contact_repo = SqlContactRepository(async_connection)
    contact = Contact(
        first_name="John",
        last_name="Doe",
    )
    saved_contact = await contact_repo.save(contact)
    assert saved_contact.id is not None

    # Create event
    journal_data = {
        "user_id": user_id,
        "title": "Morning Run",
        "strava_athletes": [{"id": "12345", "name": "John Doe"}],
        "fitness_data": {
            "strava_activity_id": "999",
        },
        "version_hash": "hash123",
    }

    event = OutboxEvent(
        id=uuid.uuid4(),
        event_type=EVENT_TYPE_JOURNAL_EVENT_CREATED,
        aggregate_id="999",
        event_data={
            "integration_source": "strava",
            "journal_data": journal_data,
            "calendar_info_data": {
                "calendar_id": "00000000-0000-0000-0000-000000000001"
            },
            "external_event_id": "999",
            "calendar_id": "00000000-0000-0000-0000-000000000001",
        },
        occurred_at=datetime.now(UTC),
        retry_count=0,
    )

    # Process event
    result = await processor.process_event(event)
    journal_id = result["journal_id"]

    # Verify participant relationship was created
    relationships = await processor._get_relationships_by_type(
        journal_id, JournalContactRelationshipType.PARTICIPANT
    )

    assert len(relationships) == 1
    assert relationships[0].contact_id == saved_contact.id

    # Verify mapping was saved
    mapping_repo = SqlStravaAthleteMappingRepository(async_connection)
    mapping = await mapping_repo.get_by_strava_id(user_id, "12345")
    assert mapping is not None
    assert mapping.contact_id == saved_contact.id


@pytest.mark.asyncio
async def test_participant_detection_uses_existing_mapping(
    async_connection: AsyncConnection,
    clean_database: None,
) -> None:
    """Test that participant detection uses existing mapping."""
    await _ensure_strava_calendar(async_connection)
    processor = await _create_processor(async_connection)
    user_id = "test-user-id"

    # Create contact
    contact_repo = SqlContactRepository(async_connection)
    contact = Contact(
        first_name="Jane",
        last_name="Smith",
    )
    saved_contact = await contact_repo.save(contact)
    assert saved_contact.id is not None

    # Create mapping
    mapping_repo = SqlStravaAthleteMappingRepository(async_connection)
    mapping = StravaAthleteMapping(
        user_id=user_id,
        strava_athlete_id="54321",
        strava_athlete_name="Jane S.",
        contact_id=saved_contact.id,
    )
    await mapping_repo.save(mapping)

    # Create event
    journal_data = {
        "user_id": user_id,
        "title": "Evening Ride",
        "strava_athletes": [{"id": "54321", "name": "Jane S."}],
        "fitness_data": {
            "strava_activity_id": "888",
        },
        "version_hash": "hash456",
    }

    event = OutboxEvent(
        id=uuid.uuid4(),
        event_type=EVENT_TYPE_JOURNAL_EVENT_CREATED,
        aggregate_id="888",
        event_data={
            "integration_source": "strava",
            "journal_data": journal_data,
            "calendar_info_data": {
                "calendar_id": "00000000-0000-0000-0000-000000000001"
            },
            "external_event_id": "888",
            "calendar_id": "00000000-0000-0000-0000-000000000001",
        },
        occurred_at=datetime.now(UTC),
        retry_count=0,
    )

    # Process event
    result = await processor.process_event(event)
    journal_id = result["journal_id"]

    # Verify participant relationship was created using the mapped contact
    relationships = await processor._get_relationships_by_type(
        journal_id, JournalContactRelationshipType.PARTICIPANT
    )

    assert len(relationships) == 1
    assert relationships[0].contact_id == saved_contact.id


@pytest.mark.asyncio
async def test_participant_detection_skips_ambiguous_names(
    async_connection: AsyncConnection,
    clean_database: None,
) -> None:
    """Test that an ambiguous name match does not create a participant or mapping."""
    await _ensure_strava_calendar(async_connection)
    processor = await _create_processor(async_connection)
    user_id = "test-user-id"

    # Create two contacts with the same name
    contact_repo = SqlContactRepository(async_connection)
    c1 = await contact_repo.save(Contact(first_name="Bob", last_name="Jones"))
    c2 = await contact_repo.save(Contact(first_name="Bob", last_name="Jones"))
    assert c1.id is not None
    assert c2.id is not None

    # Create event
    journal_data = {
        "user_id": user_id,
        "title": "Group Run",
        "strava_athletes": [{"id": "111", "name": "Bob Jones"}],
        "fitness_data": {
            "strava_activity_id": "777",
        },
        "version_hash": "hash789",
    }

    event = OutboxEvent(
        id=uuid.uuid4(),
        event_type=EVENT_TYPE_JOURNAL_EVENT_CREATED,
        aggregate_id="777",
        event_data={
            "integration_source": "strava",
            "journal_data": journal_data,
            "calendar_info_data": {
                "calendar_id": "00000000-0000-0000-0000-000000000001"
            },
            "external_event_id": "777",
            "calendar_id": "00000000-0000-0000-0000-000000000001",
        },
        occurred_at=datetime.now(UTC),
        retry_count=0,
    )

    # Process event
    result = await processor.process_event(event)
    journal_id = result["journal_id"]

    # Verify NO participant relationship was created
    relationships = await processor._get_relationships_by_type(
        journal_id, JournalContactRelationshipType.PARTICIPANT
    )

    assert len(relationships) == 0

    # Verify NO mapping was saved
    mapping_repo = SqlStravaAthleteMappingRepository(async_connection)
    mapping = await mapping_repo.get_by_strava_id(user_id, "111")
    assert mapping is None
