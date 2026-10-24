import uuid
from datetime import UTC, datetime

import pytest
from core_shared.integration_constants import SyntheticCalendar, synthetic_calendar_id
from core_shared.models.contacts.entities import Contact
from core_shared.models.journals.journal_relationship_types import (
    JournalContactRelationshipType,
)
from core_shared.models.outbox import OutboxEvent
from core_shared.models.strava_athlete_mapping import StravaAthleteMapping
from sqlalchemy import text
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
from app.core.tasks.adapters.sql.task_anchor_repository import (
    SqlTaskAnchorRepository,
)
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from tests.integration.contact_seeding import OTHER_USER_ID, seed_contact

# The Strava worker links each user's activities on their own calendar.
STRAVA_CALENDAR_ID = synthetic_calendar_id(SyntheticCalendar.STRAVA, "test-user-id")


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
        task_anchor_repo=SqlTaskAnchorRepository(connection),
    )
    contact_repo = SqlContactRepository(connection)
    mapping_repo = SqlStravaAthleteMappingRepository(connection)
    return JournalOutboxEventProcessor(
        journal_service=service,
        connection=connection,
        contact_repository=contact_repo,
        strava_athlete_mapping_repository=mapping_repo,
    )


async def _ensure_strava_calendar(connection: AsyncConnection) -> None:
    await connection.execute(
        text("""
            INSERT INTO calendars (id, user_id, google_calendar_id, name, color)
            VALUES (:id, 'test-user-id', 'strava-synthetic', 'Strava Activities', '#FC4C02')
            ON CONFLICT (id) DO NOTHING
        """),
        {"id": STRAVA_CALENDAR_ID},
    )


def _strava_activity_event(
    user_id: str, *, title: str, activity_id: str, athlete: dict[str, str]
) -> OutboxEvent:
    """A Strava activity arriving as a new journal, with one athlete on it."""
    return OutboxEvent(
        id=uuid.uuid4(),
        event_type=EVENT_TYPE_JOURNAL_EVENT_CREATED,
        aggregate_id=activity_id,
        event_data={
            "integration_source": "strava",
            "journal_data": {
                "user_id": user_id,
                "title": title,
                "strava_athletes": [athlete],
                "fitness_data": {"strava_activity_id": activity_id},
                "version_hash": f"hash-{activity_id}",
            },
            "calendar_info_data": {"calendar_id": STRAVA_CALENDAR_ID},
            "external_event_id": activity_id,
            "calendar_id": STRAVA_CALENDAR_ID,
            "sync_action": "created",
            "sync_timestamp": datetime.now(UTC).isoformat(),
            "contact_relationships": [],
        },
        occurred_at=datetime.now(UTC),
        retry_count=0,
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
        user_id=user_id,
        first_name="John",
        last_name="Doe",
    )
    saved_contact = await contact_repo.save(contact)
    assert saved_contact.id is not None

    event = _strava_activity_event(
        user_id,
        title="Morning Run",
        activity_id="999",
        athlete={"id": "12345", "name": "John Doe"},
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
        user_id=user_id,
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

    event = _strava_activity_event(
        user_id,
        title="Evening Ride",
        activity_id="888",
        athlete={"id": "54321", "name": "Jane S."},
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
    c1 = await contact_repo.save(
        Contact(user_id=user_id, first_name="Bob", last_name="Jones")
    )
    c2 = await contact_repo.save(
        Contact(user_id=user_id, first_name="Bob", last_name="Jones")
    )
    assert c1.id is not None
    assert c2.id is not None

    event = _strava_activity_event(
        user_id,
        title="Group Run",
        activity_id="777",
        athlete={"id": "111", "name": "Bob Jones"},
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


@pytest.mark.asyncio
async def test_participant_detection_ignores_another_users_contact(
    async_connection: AsyncConnection,
    clean_database: None,
) -> None:
    """Only the journal owner's contacts are matched by the athlete's name.

    Another user's contact with exactly that name is neither linked nor mapped;
    the athlete is recorded as unmatched, for the owner to map by hand.
    """
    await _ensure_strava_calendar(async_connection)
    processor = await _create_processor(async_connection)
    user_id = "test-user-id"
    await seed_contact(
        async_connection, user_id=OTHER_USER_ID, first_name="Ada", last_name="Byron"
    )
    event = _strava_activity_event(
        user_id,
        title="Hill Repeats",
        activity_id="666",
        athlete={"id": "222", "name": "Ada Byron"},
    )

    result = await processor.process_event(event)
    journal_id = result["journal_id"]

    relationships = await processor._get_relationships_by_type(
        journal_id, JournalContactRelationshipType.PARTICIPANT
    )
    assert relationships == []
    mapping_repo = SqlStravaAthleteMappingRepository(async_connection)
    assert await mapping_repo.get_by_strava_id(user_id, "222") is None
    unmatched = await async_connection.execute(
        text("""
            SELECT strava_athlete_id, strava_athlete_name
            FROM journal_unmatched_strava_athletes
            WHERE journal_id = :journal_id
        """),
        {"journal_id": journal_id},
    )
    assert [tuple(row) for row in unmatched.all()] == [("222", "Ada Byron")]
