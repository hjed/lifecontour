"""Integration tests for sync_calendar_events ARQ task."""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text

from worker import sync_calendar_events


@pytest.mark.asyncio
class TestSyncCalendarEventsIntegration:
    """Integration test for sync_calendar_events behavior."""

    async def test_sync_calendar_events_retroactive_contact_link(self, db_session):
        """Test that an unchanged event correctly creates an outbox event if a contact match is found."""
        now = datetime.now(UTC)
        test_email = "calendar_sync_test@example.com"
        # Must be a valid UUID for user_id to avoid DB type errors
        test_user = "11111111-1111-1111-1111-111111111111"
        test_contact_email = "new_attendee@example.com"
        test_calendar_uuid = str(uuid.uuid4())
        test_journal_id = 4200
        test_contact_id = 9900
        etag = '"etag-abc"'



        # Insert synced calendar
        await db_session.execute(
            text("""
                INSERT INTO calendars (id, user_id, name, color, created_at, updated_at, google_calendar_id, is_synced_to_google)
                VALUES (:cal_id, :user_id, 'Test Cal', '#FF0000', :now, :now, 'primary', true)
            """),
            {"cal_id": test_calendar_uuid, "user_id": test_user, "now": now},
        )

        # Insert journal
        await db_session.execute(
            text("""
                INSERT INTO journals (id, user_id, title, content, event_date_range_start, event_date_range_end, created_at, updated_at)
                VALUES (:journal_id, :user_id, 'Event Journal', 'Test Content', :now, :now, :now, :now)
            """),
            {"journal_id": test_journal_id, "user_id": test_user, "now": now},
        )

        # Insert external event link for the calendar
        await db_session.execute(
            text("""
                INSERT INTO journal_external_event_links
                (journal_id, calendar_id, external_event_id, external_version, sync_capability, sync_status, created_at, updated_at)
                VALUES (:journal_id, :cal_id, 'google-event-1', :etag, 'bidirectional', 'synced', :now, :now)
            """),
            {"journal_id": test_journal_id, "cal_id": test_calendar_uuid, "etag": etag, "now": now},
        )

        # Insert new contact matching the attendee email
        await db_session.execute(
            text("""
                INSERT INTO contacts (id, user_id, first_name, created_at, updated_at)
                VALUES (:contact_id, :user_id, 'Test', :now, :now)
            """),
            {"contact_id": test_contact_id, "user_id": test_user, "now": now},
        )

        # Insert contact method
        await db_session.execute(
            text("""
                INSERT INTO contact_methods (contact_id, method_type, value, created_at, updated_at)
                VALUES (:contact_id, 'email', :contact_email, :now, :now)
            """),
            {
                "contact_id": test_contact_id,
                "contact_email": test_contact_email,
                "now": now,
            },
        )

        await db_session.commit()

        @asynccontextmanager
        async def mock_session_factory():
            yield db_session

        ctx = {
            "session_factory": mock_session_factory,
            "redis": AsyncMock(),
            "job_id": "test_calendar_job",
        }

        # Mock Google API returning the same ETag and an attendee matching the new contact
        google_event_dict = {
            "id": "google-event-1",
            "summary": "Team Meeting",
            "description": "Weekly sync",
            "etag": etag,
            "status": "confirmed",
            "start": {"dateTime": "2026-03-20T10:00:00Z"},
            "end": {"dateTime": "2026-03-20T11:00:00Z"},
            "attendees": [{"email": test_contact_email}],
        }

        mock_client = MagicMock()
        mock_client.list_events = AsyncMock(
            return_value={"items": [google_event_dict], "nextSyncToken": "sync_token"}
        )

        with patch("worker._create_google_client", return_value=mock_client):
            result = await sync_calendar_events(ctx, test_email, test_user, "smart")

        assert result["status"] == "success"

        # We expect an outbox event to be created because the contact method exists but journal_contacts does not
        result_outbox = await db_session.execute(
            text(
                "SELECT count(*) FROM outbox_events WHERE event_type = 'journal_event.updated'"
            )
        )
        outbox_count = result_outbox.scalar()
        assert outbox_count >= 1
