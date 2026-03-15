"""Integration tests for process_journal_event flow."""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text

from worker import process_journal_event


async def _setup_journal_event_test_data(
    db_session, user_id, google_email, calendar_id, title, include_existing_link=False
):
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
        VALUES (:user_id, :title, 'Content', :start, :end)
        RETURNING id
        """),
        {"user_id": user_id, "title": title, "start": event_start, "end": event_end},
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

    if include_existing_link:
        # 5. Setup Data - Insert into journal_external_event_links
        await db_session.execute(
            text("""
            INSERT INTO journal_external_event_links (journal_id, calendar_id, external_event_id, external_version, sync_capability, sync_status, created_at, updated_at)
            VALUES (:journal_id, :calendar_id, 'existing_event_id_123', 'old_etag', 'outbound', 'synced', now(), now())
            """),
            {"journal_id": journal_id, "calendar_id": calendar_id},
        )
    else:
        # 5. Setup Data - Ensure pending external link (like what DB migration or frontend does)
        await db_session.execute(
            text("""
            INSERT INTO journal_external_event_links (journal_id, calendar_id, external_event_id, external_version, sync_capability, sync_status, created_at, updated_at)
            VALUES (:journal_id, :calendar_id, NULL, NULL, 'outbound', 'pending', now(), now())
            """),
            {"journal_id": journal_id, "calendar_id": calendar_id},
        )

    await db_session.commit()
    return journal_id


@pytest.mark.asyncio
class TestProcessJournalEventIntegration:
    """Integration test for process_journal_event flow handling."""

    async def test_process_journal_event_creates_external_link(self, db_session):
        """Test that process_journal_event fetches data, calls API, and updates link in DB."""
        user_id = str(uuid.uuid4())
        google_email = f"test_{uuid.uuid4().hex[:8]}@example.com"
        calendar_id = str(uuid.uuid4())

        journal_id = await _setup_journal_event_test_data(
            db_session, user_id, google_email, calendar_id, "Integration Test", False
        )

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

        journal_id = await _setup_journal_event_test_data(
            db_session,
            user_id,
            google_email,
            calendar_id,
            "Integration Test Update",
            True,
        )

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

    async def test_process_journal_event_orphan_delete_fails_sets_errored(
        self, db_session
    ):
        """Test that if deleting an orphaned link fails with non-404, the link is marked errored."""
        user_id = str(uuid.uuid4())
        google_email = f"test_{uuid.uuid4().hex[:8]}@example.com"
        calendar_id_1 = str(uuid.uuid4())  # old calendar
        calendar_id_2 = str(uuid.uuid4())  # new calendar

        # Setup user and both calendars
        await db_session.execute(
            text(
                "INSERT INTO user_google_integration (user_id, google_account_email, created_at, updated_at) VALUES (:user_id, :email, now(), now())"
            ),
            {"user_id": user_id, "email": google_email},
        )
        await db_session.execute(
            text(
                "INSERT INTO calendars (id, user_id, name, color, is_synced_to_google) VALUES (:id, :user_id, 'Cal 1', '#FF0000', true)"
            ),
            {"id": calendar_id_1, "user_id": user_id},
        )
        await db_session.execute(
            text(
                "INSERT INTO calendars (id, user_id, name, color, is_synced_to_google) VALUES (:id, :user_id, 'Cal 2', '#00FF00', true)"
            ),
            {"id": calendar_id_2, "user_id": user_id},
        )

        # Setup journal
        event_start = datetime.now(UTC)
        event_end = event_start + timedelta(hours=1)
        result = await db_session.execute(
            text(
                "INSERT INTO journals (user_id, title, content, event_date_range_start, event_date_range_end) VALUES (:user_id, 'Title', 'Content', :start, :end) RETURNING id"
            ),
            {"user_id": user_id, "start": event_start, "end": event_end},
        )
        journal_id = result.scalar()

        # Current calendar is calendar 2
        await db_session.execute(
            text(
                "INSERT INTO journal_calendar_info (journal_id, calendar_id, is_all_day, location) VALUES (:journal_id, :calendar_id, false, 'Loc')"
            ),
            {"journal_id": journal_id, "calendar_id": calendar_id_2},
        )

        # Orphan link on calendar 1
        await db_session.execute(
            text(
                "INSERT INTO journal_external_event_links (journal_id, calendar_id, external_event_id, sync_capability, sync_status, created_at, updated_at) VALUES (:journal_id, :calendar_id, 'orphan_123', 'outbound', 'synced', now(), now())"
            ),
            {"journal_id": journal_id, "calendar_id": calendar_id_1},
        )
        await db_session.commit()

        from googleapiclient.errors import HttpError

        from worker import process_journal_event

        @asynccontextmanager
        async def mock_session_factory():
            yield db_session

        ctx = {"session_factory": mock_session_factory, "job_id": "test_orphan"}

        mock_google_client = AsyncMock()
        mock_google_auth_service = AsyncMock()
        mock_google_auth_service.get_access_token.return_value = "token"

        # Mock delete_event to raise a non-404 error
        mock_resp = MagicMock()
        mock_resp.status = 500
        mock_resp.reason = "Internal Server Error"

        mock_google_client.delete_event.side_effect = HttpError(
            resp=mock_resp, content=b"error"
        )

        # And mock create_event for the normal flow
        mock_google_client.create_event.return_value = {"id": "new_event_123"}

        with (
            patch("worker.GoogleAuthService", return_value=mock_google_auth_service),
            patch("worker.GoogleAPIClient", return_value=mock_google_client),
        ):
            result = await process_journal_event(
                ctx=ctx,
                event_type="JournalUpdated",
                event_data={
                    "journal_id": journal_id,
                    "changed_fields": {"title": ["Old", "New"]},
                },
            )

        # Check DB to see if orphan link is 'errored'
        result = await db_session.execute(
            text(
                "SELECT sync_status FROM journal_external_event_links WHERE journal_id = :journal_id AND calendar_id = :calendar_id"
            ),
            {"journal_id": journal_id, "calendar_id": calendar_id_1},
        )
        status = result.scalar()
        assert status == "errored"

    async def test_process_journal_event_concurrent_create_ignores_duplicate(
        self, db_session
    ):
        """Test that duplicate create jobs correctly abort if another job holds the lock."""
        user_id = str(uuid.uuid4())
        google_email = f"test_{uuid.uuid4().hex[:8]}@example.com"
        calendar_id = str(uuid.uuid4())

        journal_id = await _setup_journal_event_test_data(
            db_session, user_id, google_email, calendar_id, "Concurrent Test", False
        )

        # Insert a pending lock simulating another worker starting creation
        await db_session.execute(
            text(
                "INSERT INTO journal_external_event_links (journal_id, calendar_id, sync_capability, sync_status, created_at, updated_at) VALUES (:journal_id, :calendar_id, 'outbound', 'pending', now(), now())"
            ),
            {"journal_id": journal_id, "calendar_id": calendar_id},
        )
        await db_session.commit()

        from worker import process_journal_event

        @asynccontextmanager
        async def mock_session_factory():
            yield db_session

        ctx = {"session_factory": mock_session_factory, "job_id": "test_concurrent"}

        mock_google_client = AsyncMock()
        mock_google_auth_service = AsyncMock()

        with (
            patch("worker.GoogleAuthService", return_value=mock_google_auth_service),
            patch("worker.GoogleAPIClient", return_value=mock_google_client),
        ):
            result = await process_journal_event(
                ctx=ctx,
                event_type="JournalCreated",
                event_data={"journal_id": journal_id},
            )

        assert result["status"] == "ignored"
        assert result["reason"] == "concurrent_create"
        mock_google_client.create_event.assert_not_called()
