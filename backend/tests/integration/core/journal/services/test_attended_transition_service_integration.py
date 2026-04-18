"""
Integration tests for the attended transition background job.
"""

from datetime import UTC, datetime, timedelta

import pytest
from core_shared.models.journals import (
    AttendeeStatus,
    JournalContactRelationshipType,
)

from app.core.journal.services.attended_transition_service import (
    transition_attending_to_attended,
)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_background_transition_job(clean_database, async_connection):
    """Test that the background transition job correctly updates statuses."""
    from sqlalchemy import text

    from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
        SqlJournalContactRelationshipRepository,
    )

    # 1. Setup Data directly in the DB using the connection
    # We will insert two journals: one past event (should transition), one future event (shouldn't transition)
    # Both with contacts having ATTENDING status.

    conn = async_connection

    # Create contacts
    await conn.execute(
        text(
            """
            INSERT INTO contacts (id, first_name, last_name, created_at, updated_at)
            VALUES
            (1, 'Contact', 'Past', now(), now()),
            (2, 'Contact', 'Future', now(), now())
            """
        )
    )

    # Create Calendars
    await conn.execute(
        text(
            """
            INSERT INTO calendars (id, user_id, name, color)
            VALUES ('00000000-0000-0000-0000-000000000001', 'usr_1', 'Test Calendar', '#FF0000')
            """
        )
    )

    now = datetime.now(UTC)
    past_start = now - timedelta(days=2)
    past_end = now - timedelta(days=1)

    future_start = now + timedelta(days=1)
    future_end = now + timedelta(days=2)

    # Create Journals
    await conn.execute(
        text(
            """
            INSERT INTO journals (id, user_id, title, content, event_date_range_start, event_date_range_end, "order", created_at, updated_at)
            VALUES
            (1, 'usr_1', 'Past Event', 'Content', :p_start, :p_end, 1, now(), now()),
            (2, 'usr_1', 'Future Event', 'Content', :f_start, :f_end, 2, now(), now())
            """
        ),
        {
            "p_start": past_start,
            "p_end": past_end,
            "f_start": future_start,
            "f_end": future_end,
        },
    )

    # Create Calendar Info (making them events)
    await conn.execute(
        text(
            """
            INSERT INTO journal_calendar_info (journal_id, calendar_id, is_all_day)
            VALUES
            (1, '00000000-0000-0000-0000-000000000001', false),
            (2, '00000000-0000-0000-0000-000000000001', false)
            """
        )
    )

    # Add Relationships
    await conn.execute(
        text(
            """
            INSERT INTO journal_contact_relationships (journal_id, contact_id, relationship_type, status, role, created_at)
            VALUES
            (1, 1, 'PARTICIPANT', 'ATTENDING', 'ORGANISER', now()),
            (2, 2, 'PARTICIPANT', 'ATTENDING', 'ORGANISER', now())
            """
        )
    )

    # 2. Run the transition job

    repo = SqlJournalContactRelationshipRepository(conn)
    result = await transition_attending_to_attended(repo)

    # Should transition exactly 1 relationship
    assert result.transitioned_count == 1

    # 3. Verify the transition
    past_rels = await repo.get_by_journal_and_type(
        1, JournalContactRelationshipType.PARTICIPANT
    )
    assert len(past_rels) == 1
    assert past_rels[0].status == AttendeeStatus.ATTENDED

    future_rels = await repo.get_by_journal_and_type(
        2, JournalContactRelationshipType.PARTICIPANT
    )
    assert len(future_rels) == 1
    assert future_rels[0].status == AttendeeStatus.ATTENDING
