"""Integration tests for attendance transition service and repository.

Tests the AttendanceTransitionService and the new repository methods
(update_status, find_attending_for_past_events) against a real database.
"""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from core_shared.models.journals import (
    JournalContactRelationship,
    JournalContactRelationshipType,
)
from core_shared.models.journals.attendee_status import AttendeeStatus
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.journal.services.attendance_transition_service import (
    AttendanceTransitionService,
)
from tests.integration.contact_seeding import seed_contact


@pytest_asyncio.fixture
async def rel_repo(
    async_connection: AsyncConnection,
) -> SqlJournalContactRelationshipRepository:
    """Create a relationship repository instance."""
    return SqlJournalContactRelationshipRepository(async_connection)


@pytest_asyncio.fixture
async def service(
    rel_repo: SqlJournalContactRelationshipRepository,
) -> AttendanceTransitionService:
    """Create an AttendanceTransitionService with a real repository."""
    return AttendanceTransitionService(rel_repo)


async def _create_contact(conn: AsyncConnection, name: str = "Test Contact") -> int:
    """Create a test contact and return its ID."""
    return await seed_contact(conn, first_name=name)


async def _create_journal(
    conn: AsyncConnection,
    title: str,
    event_start: datetime,
    event_end: datetime,
) -> int:
    """Create a test journal with event date range and return its ID."""
    result = await conn.execute(
        text(
            """
            INSERT INTO journals (
                user_id, title, content,
                event_date_range_start, event_date_range_end
            )
            VALUES (:user_id, :title, :content, :start, :end)
            RETURNING id
            """
        ),
        {
            "user_id": "test_user",
            "title": title,
            "content": "Test content",
            "start": event_start,
            "end": event_end,
        },
    )
    from typing import cast

    journal_id = cast(int, result.scalar())
    assert journal_id is not None
    return journal_id


async def _create_relationship(
    repo: SqlJournalContactRelationshipRepository,
    journal_id: int,
    contact_id: int,
    status: AttendeeStatus | None = None,
) -> JournalContactRelationship:
    """Create a journal-contact relationship with given status."""
    rel = JournalContactRelationship(
        journal_id=journal_id,
        contact_id=contact_id,
        relationship_type=JournalContactRelationshipType.PARTICIPANT,
        status=status,
    )
    return await repo.create(rel)


@pytest.mark.integration
class TestUpdateStatusIntegration:
    """Integration tests for the update_status repository method."""

    async def test_update_status_returns_updated_relationship(
        self,
        rel_repo: SqlJournalContactRelationshipRepository,
        async_connection: AsyncConnection,
    ):
        """update_status updates and returns the relationship."""
        now = datetime.now(UTC)
        journal_id = await _create_journal(
            async_connection, "Test Event", now - timedelta(days=1), now
        )
        contact_id = await _create_contact(async_connection)
        await _create_relationship(
            rel_repo, journal_id, contact_id, AttendeeStatus.ATTENDING
        )

        updated = await rel_repo.update_status(
            journal_id=journal_id,
            contact_id=contact_id,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
            status=AttendeeStatus.ATTENDED,
        )

        assert updated is not None
        assert updated.status == AttendeeStatus.ATTENDED
        assert updated.journal_id == journal_id
        assert updated.contact_id == contact_id

    async def test_update_status_nonexistent_returns_none(
        self,
        rel_repo: SqlJournalContactRelationshipRepository,
    ):
        """update_status returns None for nonexistent relationship."""
        result = await rel_repo.update_status(
            journal_id=99999,
            contact_id=99999,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
            status=AttendeeStatus.ATTENDED,
        )
        assert result is None


@pytest.mark.integration
class TestFindAttendingForPastEventsIntegration:
    """Integration tests for find_attending_for_past_events repository method."""

    async def test_finds_attending_contacts_on_past_events(
        self,
        rel_repo: SqlJournalContactRelationshipRepository,
        async_connection: AsyncConnection,
    ):
        """Returns ATTENDING contacts on events that have ended."""
        now = datetime.now(UTC)
        past_event_end = now - timedelta(hours=2)
        journal_id = await _create_journal(
            async_connection,
            "Past Event",
            past_event_end - timedelta(hours=1),
            past_event_end,
        )
        contact_id = await _create_contact(async_connection)
        await _create_relationship(
            rel_repo, journal_id, contact_id, AttendeeStatus.ATTENDING
        )

        results = await rel_repo.find_attending_for_past_events(
            cutoff_time=now, batch_size=100
        )

        assert len(results) == 1
        assert results[0].journal_id == journal_id
        assert results[0].status == AttendeeStatus.ATTENDING

    async def test_excludes_future_events(
        self,
        rel_repo: SqlJournalContactRelationshipRepository,
        async_connection: AsyncConnection,
    ):
        """ATTENDING contacts on future events are excluded."""
        now = datetime.now(UTC)
        future_end = now + timedelta(days=1)
        journal_id = await _create_journal(
            async_connection,
            "Future Event",
            now + timedelta(hours=1),
            future_end,
        )
        contact_id = await _create_contact(async_connection)
        await _create_relationship(
            rel_repo, journal_id, contact_id, AttendeeStatus.ATTENDING
        )

        results = await rel_repo.find_attending_for_past_events(
            cutoff_time=now, batch_size=100
        )

        assert len(results) == 0

    async def test_excludes_non_attending_statuses(
        self,
        rel_repo: SqlJournalContactRelationshipRepository,
        async_connection: AsyncConnection,
    ):
        """Only ATTENDING contacts are returned, not MAYBE/DECLINED/etc."""
        now = datetime.now(UTC)
        past_end = now - timedelta(hours=2)
        journal_id = await _create_journal(
            async_connection, "Past Event", past_end - timedelta(hours=1), past_end
        )

        contact_maybe = await _create_contact(async_connection, "Maybe Contact")
        contact_declined = await _create_contact(async_connection, "Declined Contact")
        contact_attended = await _create_contact(async_connection, "Attended Contact")

        await _create_relationship(
            rel_repo, journal_id, contact_maybe, AttendeeStatus.MAYBE
        )
        await _create_relationship(
            rel_repo, journal_id, contact_declined, AttendeeStatus.DECLINED
        )
        await _create_relationship(
            rel_repo, journal_id, contact_attended, AttendeeStatus.ATTENDED
        )

        results = await rel_repo.find_attending_for_past_events(
            cutoff_time=now, batch_size=100
        )

        assert len(results) == 0

    async def test_respects_batch_size(
        self,
        rel_repo: SqlJournalContactRelationshipRepository,
        async_connection: AsyncConnection,
    ):
        """Only batch_size number of results are returned."""
        now = datetime.now(UTC)
        past_end = now - timedelta(hours=2)
        journal_id = await _create_journal(
            async_connection, "Past Event", past_end - timedelta(hours=1), past_end
        )

        # Create 3 ATTENDING contacts
        for i in range(3):
            contact_id = await _create_contact(async_connection, f"Contact {i}")
            await _create_relationship(
                rel_repo, journal_id, contact_id, AttendeeStatus.ATTENDING
            )

        results = await rel_repo.find_attending_for_past_events(
            cutoff_time=now, batch_size=2
        )

        assert len(results) == 2


@pytest.mark.integration
class TestAttendanceTransitionServiceIntegration:
    """Integration tests for AttendanceTransitionService with real database."""

    async def test_happy_path_transitions_attending_to_attended(
        self,
        service: AttendanceTransitionService,
        rel_repo: SqlJournalContactRelationshipRepository,
        async_connection: AsyncConnection,
    ):
        """ATTENDING contacts on past events are transitioned to ATTENDED."""
        now = datetime.now(UTC)
        past_end = now - timedelta(hours=2)
        journal_id = await _create_journal(
            async_connection, "Past Event", past_end - timedelta(hours=1), past_end
        )
        contact_id = await _create_contact(async_connection)
        await _create_relationship(
            rel_repo, journal_id, contact_id, AttendeeStatus.ATTENDING
        )

        result = await service.transition_past_event_attendees(now)

        assert result.transitioned_count == 1

        # Verify in database
        rels = await rel_repo.get_by_journal(journal_id)
        assert len(rels) == 1
        assert rels[0].status == AttendeeStatus.ATTENDED

    async def test_mixed_statuses_only_attending_transitions(
        self,
        service: AttendanceTransitionService,
        rel_repo: SqlJournalContactRelationshipRepository,
        async_connection: AsyncConnection,
    ):
        """Only ATTENDING contacts transition, others remain unchanged."""
        now = datetime.now(UTC)
        past_end = now - timedelta(hours=2)
        journal_id = await _create_journal(
            async_connection, "Past Event", past_end - timedelta(hours=1), past_end
        )

        attending = await _create_contact(async_connection, "Attending")
        maybe = await _create_contact(async_connection, "Maybe")
        declined = await _create_contact(async_connection, "Declined")
        no_reply = await _create_contact(async_connection, "No Reply")

        await _create_relationship(
            rel_repo, journal_id, attending, AttendeeStatus.ATTENDING
        )
        await _create_relationship(rel_repo, journal_id, maybe, AttendeeStatus.MAYBE)
        await _create_relationship(
            rel_repo, journal_id, declined, AttendeeStatus.DECLINED
        )
        await _create_relationship(
            rel_repo, journal_id, no_reply, AttendeeStatus.NO_REPLY
        )

        result = await service.transition_past_event_attendees(now)

        assert result.transitioned_count == 1

        # Verify each contact's status
        rels = await rel_repo.get_by_journal(journal_id)
        status_map = {r.contact_id: r.status for r in rels}
        assert status_map[attending] == AttendeeStatus.ATTENDED
        assert status_map[maybe] == AttendeeStatus.MAYBE
        assert status_map[declined] == AttendeeStatus.DECLINED
        assert status_map[no_reply] == AttendeeStatus.NO_REPLY

    async def test_future_event_contacts_unchanged(
        self,
        service: AttendanceTransitionService,
        rel_repo: SqlJournalContactRelationshipRepository,
        async_connection: AsyncConnection,
    ):
        """ATTENDING contacts on future events remain ATTENDING."""
        now = datetime.now(UTC)
        future_end = now + timedelta(days=1)
        journal_id = await _create_journal(
            async_connection,
            "Future Event",
            now + timedelta(hours=1),
            future_end,
        )
        contact_id = await _create_contact(async_connection)
        await _create_relationship(
            rel_repo, journal_id, contact_id, AttendeeStatus.ATTENDING
        )

        result = await service.transition_past_event_attendees(now)

        assert result.transitioned_count == 0

        # Verify contact remains ATTENDING
        rels = await rel_repo.get_by_journal(journal_id)
        assert len(rels) == 1
        assert rels[0].status == AttendeeStatus.ATTENDING

    async def test_idempotency_second_run_zero_transitions(
        self,
        service: AttendanceTransitionService,
        rel_repo: SqlJournalContactRelationshipRepository,
        async_connection: AsyncConnection,
    ):
        """Running the transition twice produces 0 transitions on second run."""
        now = datetime.now(UTC)
        past_end = now - timedelta(hours=2)
        journal_id = await _create_journal(
            async_connection, "Past Event", past_end - timedelta(hours=1), past_end
        )
        contact_id = await _create_contact(async_connection)
        await _create_relationship(
            rel_repo, journal_id, contact_id, AttendeeStatus.ATTENDING
        )

        # First run
        result1 = await service.transition_past_event_attendees(now)
        assert result1.transitioned_count == 1

        # Second run (idempotent)
        result2 = await service.transition_past_event_attendees(now)
        assert result2.transitioned_count == 0

    async def test_multiple_past_journals(
        self,
        service: AttendanceTransitionService,
        rel_repo: SqlJournalContactRelationshipRepository,
        async_connection: AsyncConnection,
    ):
        """Multiple past journals with ATTENDING contacts are all transitioned."""
        now = datetime.now(UTC)

        # Create two past events with ATTENDING contacts
        for i in range(2):
            past_end = now - timedelta(hours=i + 1)
            journal_id = await _create_journal(
                async_connection,
                f"Past Event {i}",
                past_end - timedelta(hours=1),
                past_end,
            )
            contact_id = await _create_contact(async_connection, f"Contact {i}")
            await _create_relationship(
                rel_repo, journal_id, contact_id, AttendeeStatus.ATTENDING
            )

        result = await service.transition_past_event_attendees(now)

        assert result.transitioned_count == 2
