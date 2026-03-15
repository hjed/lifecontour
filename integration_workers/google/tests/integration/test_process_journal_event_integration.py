"""Integration tests for process_journal_event flow."""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from worker import process_journal_event


@pytest.mark.asyncio
class TestProcessJournalEventIntegration:
    """Integration test for process_journal_event flow handling."""

    async def test_process_journal_event_creates_external_link(self, db_session):
        """Test that process_journal_event fetches data, calls API, and updates link in DB."""
        user_id = str(uuid.uuid4())
        google_email = f"test_{uuid.uuid4().hex[:8]}@example.com"
        calendar_id = str(uuid.uuid4())

        # 1. Setup Data - Insert into user_google_integration
        await db_session.execute(
            text("""
            INSERT INTO user_google_integration (user_id, google_account_email, created_at, updated_at)
            VALUES (:user_id, :email, now(), now())
            """),
            {"user_id": user_id, "email": google_email},
        )

        # 2. Setup Data - Insert into calendars
        await db_session.execute(
            text("""
            INSERT INTO calendars (id, user_id, name, color, is_synced_to_google)
            VALUES (:id, :user_id, 'Test Cal', '#FF0000', true)
            """),
            {"id": calendar_id, "user_id": user_id},
        )

        # 3. Setup Data - Insert into journals
        event_start = datetime.now(UTC)
        event_end = event_start + timedelta(hours=1)
        result = await db_session.execute(
            text("""
            INSERT INTO journals (user_id, title, content, event_date_range_start, event_date_range_end)
            VALUES (:user_id, 'Integration Test', 'Content', :start, :end)
            RETURNING id
            """),
            {"user_id": user_id, "start": event_start, "end": event_end},
        )
        journal_id = result.scalar()

        # 4. Setup Data - Insert into journal_calendar_info
        await db_session.execute(
            text("""
            INSERT INTO journal_calendar_info (journal_id, calendar_id, is_all_day, location)
            VALUES (:journal_id, :calendar_id, false, 'Some Location')
            """),
            {"journal_id": journal_id, "calendar_id": calendar_id},
        )
        await db_session.commit()

        @asynccontextmanager
        async def mock_session_factory():
            yield db_session

        ctx = {
            "session_factory": mock_session_factory,
            "job_id": "test_job_123",
        }

        mock_auth_service = AsyncMock()
        mock_auth_service.get_access_token.return_value = "fake_token"

        mock_client = AsyncMock()
        mock_client.create_event.return_value = {
            "id": "google_event_123",
            "etag": "etag_123",
        }

        with (
            patch("worker.GoogleAuthService", return_value=mock_auth_service),
            patch("worker.GoogleAPIClient", return_value=mock_client),
        ):
            # Run the task
            result = await process_journal_event(
                ctx=ctx,
                event_type="JournalCreated",
                event_data={"journal_id": journal_id},
            )

            # Assert task successful
            assert result["status"] == "success"
            assert result["action"] == "create"
            assert result["external_event_id"] == "google_event_123"

            # Verify the database state was updated directly
            link_result = await db_session.execute(
                text("""
                SELECT external_event_id, external_version, sync_status
                FROM journal_external_event_links
                WHERE journal_id = :journal_id AND calendar_id = :calendar_id
                """),
                {"journal_id": journal_id, "calendar_id": calendar_id},
            )
            link = link_result.fetchone()
            assert link is not None
            assert link.external_event_id == "google_event_123"
            assert link.external_version == "etag_123"
            assert link.sync_status == "synced"

    async def test_process_journal_event_updates_existing_link(self, db_session):
        """Test that process_journal_event correctly handles an existing synced journal."""
        user_id = str(uuid.uuid4())
        google_email = f"test_{uuid.uuid4().hex[:8]}@example.com"
        calendar_id = str(uuid.uuid4())

        # 1. Setup Data - Insert into user_google_integration
        await db_session.execute(
            text("""
            INSERT INTO user_google_integration (user_id, google_account_email, created_at, updated_at)
            VALUES (:user_id, :email, now(), now())
            """),
            {"user_id": user_id, "email": google_email},
        )

        # 2. Setup Data - Insert into calendars
        await db_session.execute(
            text("""
            INSERT INTO calendars (id, user_id, name, color, is_synced_to_google)
            VALUES (:id, :user_id, 'Test Cal', '#FF0000', true)
            """),
            {"id": calendar_id, "user_id": user_id},
        )

        # 3. Setup Data - Insert into journals
        event_start = datetime.now(UTC)
        event_end = event_start + timedelta(hours=1)
        result = await db_session.execute(
            text("""
            INSERT INTO journals (user_id, title, content, event_date_range_start, event_date_range_end)
            VALUES (:user_id, 'Integration Test Update', 'Content', :start, :end)
            RETURNING id
            """),
            {"user_id": user_id, "start": event_start, "end": event_end},
        )
        journal_id = result.scalar()

        # 4. Setup Data - Insert into journal_calendar_info
        await db_session.execute(
            text("""
            INSERT INTO journal_calendar_info (journal_id, calendar_id, is_all_day, location)
            VALUES (:journal_id, :calendar_id, false, 'Some Location')
            """),
            {"journal_id": journal_id, "calendar_id": calendar_id},
        )

        # 5. Setup Data - Insert into journal_external_event_links
        await db_session.execute(
            text("""
            INSERT INTO journal_external_event_links (journal_id, calendar_id, external_event_id, external_version, sync_capability, sync_status, created_at, updated_at)
            VALUES (:journal_id, :calendar_id, 'existing_event_id_123', 'old_etag', 'outbound', 'synced', now(), now())
            """),
            {"journal_id": journal_id, "calendar_id": calendar_id},
        )
        await db_session.commit()

        @asynccontextmanager
        async def mock_session_factory():
            yield db_session

        ctx = {
            "session_factory": mock_session_factory,
            "job_id": "test_job_456",
        }

        mock_auth_service = AsyncMock()
        mock_auth_service.get_access_token.return_value = "fake_token"

        mock_client = AsyncMock()
        mock_client.update_event.return_value = {
            "id": "existing_event_id_123",
            "etag": "new_updated_etag",
        }

        with (
            patch("worker.GoogleAuthService", return_value=mock_auth_service),
            patch("worker.GoogleAPIClient", return_value=mock_client),
        ):
            # Run the task
            result = await process_journal_event(
                ctx=ctx,
                event_type="JournalUpdated",
                event_data={
                    "journal_id": journal_id,
                    "changed_fields": {
                        "title": (
                            "Integration Test Update",
                            "Integration Test Updated!",
                        )
                    },
                },
            )

            # Assert task successful
            assert result["status"] == "success"
            assert result["action"] == "update"
            assert result["external_event_id"] == "existing_event_id_123"

            # Verify API was called correctly
            mock_client.update_event.assert_called_once()

            # Verify the database state was updated directly
            link_result = await db_session.execute(
                text("""
                SELECT external_event_id, external_version, sync_status
                FROM journal_external_event_links
                WHERE journal_id = :journal_id AND calendar_id = :calendar_id
                """),
                {"journal_id": journal_id, "calendar_id": calendar_id},
            )
            link = link_result.fetchone()
            assert link is not None
            assert link.external_event_id == "existing_event_id_123"
            assert link.external_version == "new_updated_etag"
            assert link.sync_status == "synced"

    async def test_process_journal_event_deletes_external_link(self, db_session):
        """Test that process_journal_event correctly deletes an event in Google Calendar.

        When no google_calendar_id is provided in the event payload, the worker should
        fall back to the 'primary' calendar.
        """
        user_id = str(uuid.uuid4())
        google_email = f"test_{uuid.uuid4().hex[:8]}@example.com"
        external_event_id = "to_be_deleted_id_123"

        # 1. Setup Data - Insert into user_google_integration
        await db_session.execute(
            text("""
            INSERT INTO user_google_integration (user_id, google_account_email, created_at, updated_at)
            VALUES (:user_id, :email, now(), now())
            """),
            {"user_id": user_id, "email": google_email},
        )

        from worker import process_journal_event

        @asynccontextmanager
        async def mock_session_factory():
            yield db_session

        ctx = {
            "session_factory": mock_session_factory,
            "job_id": "test_job_delete",
        }

        # 2. Mock GoogleAPIClient and GoogleAuthService
        mock_google_client = AsyncMock()
        mock_google_auth_service = AsyncMock()
        mock_google_auth_service.get_access_token.return_value = "mock_access_token"

        with (
            patch("worker.GoogleAuthService", return_value=mock_google_auth_service),
            patch("worker.GoogleAPIClient", return_value=mock_google_client),
        ):
            # 3. Call process_journal_event with DELETED action (no google_calendar_id)
            result = await process_journal_event(
                ctx=ctx,
                event_type="JournalDeleted",
                event_data={
                    "journal_id": 99999,  # Doesn't matter, deleted from DB
                    "user_id": user_id,
                    "external_identifiers": {"google": [external_event_id]},
                },
            )

        # 4. Assertions
        assert result["status"] == "success"
        assert result["action"] == "delete"

        # Verify Google API was called with the fallback 'primary' calendar
        mock_google_client.delete_event.assert_called_once_with(
            external_event_id, "primary"
        )

    async def test_process_journal_event_deletes_with_explicit_calendar_id(
        self, db_session
    ):
        """Test that process_journal_event passes google_calendar_id when present."""
        user_id = str(uuid.uuid4())
        google_email = f"test_{uuid.uuid4().hex[:8]}@example.com"
        external_event_id = "to_be_deleted_id_456"
        google_calendar_id = "some_calendar@group.calendar.google.com"

        await db_session.execute(
            text("""
            INSERT INTO user_google_integration (user_id, google_account_email, created_at, updated_at)
            VALUES (:user_id, :email, now(), now())
            """),
            {"user_id": user_id, "email": google_email},
        )

        from worker import process_journal_event

        @asynccontextmanager
        async def mock_session_factory():
            yield db_session

        ctx = {
            "session_factory": mock_session_factory,
            "job_id": "test_job_delete_explicit_calendar",
        }

        mock_google_client = AsyncMock()
        mock_google_auth_service = AsyncMock()
        mock_google_auth_service.get_access_token.return_value = "mock_access_token"

        with (
            patch("worker.GoogleAuthService", return_value=mock_google_auth_service),
            patch("worker.GoogleAPIClient", return_value=mock_google_client),
        ):
            result = await process_journal_event(
                ctx=ctx,
                event_type="JournalDeleted",
                event_data={
                    "journal_id": 99998,
                    "user_id": user_id,
                    "google_calendar_id": google_calendar_id,
                    "external_identifiers": {"google": [external_event_id]},
                },
            )

        assert result["status"] == "success"
        assert result["action"] == "delete"

        # Verify the explicit calendar ID is passed through
        mock_google_client.delete_event.assert_called_once_with(
            external_event_id, google_calendar_id
        )

