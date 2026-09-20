"""Integration tests for process_journal_event flow."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from googleapiclient.errors import HttpError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from worker import process_journal_event


async def _setup_journal_event_test_data(
    db_session, user_id, google_email, calendar_id, title, include_existing_link=False
):
    # 1. Setup Data - Insert into user_google_auth
    await db_session.execute(
        text("""
        INSERT INTO user_google_auth (user_id, google_account_email, encrypted_access_token, encrypted_refresh_token, expires_at, created_at, updated_at)
        VALUES (:user_id, :email, :token, :refresh, now() + interval '1 hour', now(), now())
        """),
        {
            "user_id": user_id,
            "email": google_email,
            "token": b"fake_token",
            "refresh": b"fake_refresh",
        },
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


async def _connect_calendar_to_google(
    db_session: AsyncConnection,
    calendar_id: str,
    google_calendar_id: str,
    access_role: str | None,
) -> None:
    """Point a seeded calendar at a Google calendar with a stored role."""
    await db_session.execute(
        text("""
            UPDATE calendars
            SET google_calendar_id = :google_calendar_id, access_role = :access_role
            WHERE id = :id
        """),
        {
            "id": calendar_id,
            "google_calendar_id": google_calendar_id,
            "access_role": access_role,
        },
    )
    await db_session.commit()


async def _read_calendar_user_id(db_session: AsyncConnection, calendar_id: str) -> str:
    result = await db_session.execute(
        text("SELECT user_id FROM calendars WHERE id = :id"),
        {"id": calendar_id},
    )
    return str(result.scalar())


async def _read_access_role(
    db_session: AsyncConnection, calendar_id: str
) -> str | None:
    result = await db_session.execute(
        text("SELECT access_role FROM calendars WHERE id = :id"),
        {"id": calendar_id},
    )
    return result.scalar()


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

        # 1. Setup Data - Insert into user_google_auth
        await db_session.execute(
            text("""
            INSERT INTO user_google_auth (user_id, google_account_email, encrypted_access_token, encrypted_refresh_token, expires_at, created_at, updated_at)
            VALUES (:user_id, :email, :token, :refresh, now() + interval '1 hour', now(), now())
            """),
            {
                "user_id": user_id,
                "email": google_email,
                "token": b"fake_token",
                "refresh": b"fake_refresh",
            },
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
            INSERT INTO user_google_auth (user_id, google_account_email, encrypted_access_token, encrypted_refresh_token, expires_at, created_at, updated_at)
            VALUES (:user_id, :email, :token, :refresh, now() + interval '1 hour', now(), now())
            """),
            {
                "user_id": user_id,
                "email": google_email,
                "token": b"fake_token",
                "refresh": b"fake_refresh",
            },
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
                "INSERT INTO user_google_auth (user_id, google_account_email, encrypted_access_token, encrypted_refresh_token, expires_at, created_at, updated_at) VALUES (:user_id, :email, :token, :refresh, now() + interval '1 hour', now(), now())"
            ),
            {
                "user_id": user_id,
                "email": google_email,
                "token": b"fake_token",
                "refresh": b"fake_refresh",
            },
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

        # Update to 'syncing' simulating another worker holding the lock
        await db_session.execute(
            text(
                "UPDATE journal_external_event_links SET sync_status = 'syncing', updated_at = now() WHERE journal_id = :journal_id AND calendar_id = :calendar_id"
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


@pytest.mark.asyncio
class TestOutboundPushKeepsDeDuplicatedLinks:
    """A journal linked to two calendars is not a journal that moved.

    The outbound push prunes links pointing at a calendar other than the
    journal's own — the trace a journal leaves when a user moves it between
    calendars — by deleting the event from that calendar in Google. Since
    de-duplication, a second link can instead mean the event genuinely lives
    in that calendar too, because one calendar invited the other. Pruning
    that one would delete a real event off the user's other calendar.
    """

    async def _seed(
        self,
        db_session,
        *,
        second_link_identity: str | None,
        display_identity: str | None = "widget-7f3a::instance-0",
        second_link_capability: str = "bidirectional",
    ):
        """A journal displayed in Cal 2, with a second link on Cal 1."""
        user_id = str(uuid.uuid4())
        google_email = f"test_{uuid.uuid4().hex[:8]}@example.com"
        other_calendar = str(uuid.uuid4())
        display_calendar = str(uuid.uuid4())

        await db_session.execute(
            text(
                "INSERT INTO user_google_auth (user_id, google_account_email,"
                " encrypted_access_token, encrypted_refresh_token, expires_at,"
                " created_at, updated_at) VALUES (:user_id, :email, :token,"
                " :refresh, now() + interval '1 hour', now(), now())"
            ),
            {
                "user_id": user_id,
                "email": google_email,
                "token": b"fake_token",
                "refresh": b"fake_refresh",
            },
        )
        for calendar_id, name in (
            (other_calendar, "Personal"),
            (display_calendar, "Work"),
        ):
            await db_session.execute(
                text(
                    "INSERT INTO calendars (id, user_id, name, color,"
                    " is_synced_to_google) VALUES (:id, :user_id, :name,"
                    " '#FF0000', true)"
                ),
                {"id": calendar_id, "user_id": user_id, "name": name},
            )

        event_start = datetime.now(UTC)
        result = await db_session.execute(
            text(
                "INSERT INTO journals (user_id, title, content,"
                " event_date_range_start, event_date_range_end)"
                " VALUES (:user_id, 'Physio', 'Content', :start, :end)"
                " RETURNING id"
            ),
            {
                "user_id": user_id,
                "start": event_start,
                "end": event_start + timedelta(hours=1),
            },
        )
        journal_id = result.scalar()

        await db_session.execute(
            text(
                "INSERT INTO journal_calendar_info (journal_id, calendar_id,"
                " is_all_day, location) VALUES (:journal_id, :calendar_id,"
                " false, 'Loc')"
            ),
            {"journal_id": journal_id, "calendar_id": display_calendar},
        )
        for calendar_id, external_event_id, identity, capability in (
            (display_calendar, "work-copy-1", display_identity, "bidirectional"),
            (
                other_calendar,
                "personal-copy-9",
                second_link_identity,
                second_link_capability,
            ),
        ):
            await db_session.execute(
                text(
                    "INSERT INTO journal_external_event_links (journal_id,"
                    " calendar_id, external_event_id, external_identity,"
                    " sync_capability, sync_status, created_at, updated_at)"
                    " VALUES (:journal_id, :calendar_id, :external_event_id,"
                    " :identity, :capability, 'synced', now(), now())"
                ),
                {
                    "journal_id": journal_id,
                    "calendar_id": calendar_id,
                    "external_event_id": external_event_id,
                    "identity": identity,
                    "capability": capability,
                },
            )
        await db_session.commit()
        return journal_id, other_calendar, google_email

    async def _push_update(self, db_session, journal_id):
        from worker import process_journal_event

        @asynccontextmanager
        async def mock_session_factory():
            yield db_session

        mock_google_client = AsyncMock()
        mock_google_auth_service = AsyncMock()
        mock_google_auth_service.get_access_token.return_value = "token"
        mock_google_client.update_event.return_value = {"id": "work-copy-1"}
        mock_google_client.create_event.return_value = {"id": "work-copy-1"}

        with (
            patch("worker.GoogleAuthService", return_value=mock_google_auth_service),
            patch("worker.GoogleAPIClient", return_value=mock_google_client),
        ):
            await process_journal_event(
                ctx={
                    "session_factory": mock_session_factory,
                    "job_id": "test_dedupe_push",
                },
                event_type="JournalUpdated",
                event_data={
                    "journal_id": journal_id,
                    "changed_fields": {"title": ["Old", "New"]},
                },
            )
        return mock_google_client

    async def _link_exists(self, db_session, journal_id, calendar_id) -> bool:
        result = await db_session.execute(
            text(
                "SELECT 1 FROM journal_external_event_links"
                " WHERE journal_id = :journal_id AND calendar_id = :calendar_id"
            ),
            {"journal_id": journal_id, "calendar_id": calendar_id},
        )
        return result.fetchone() is not None

    async def test_the_other_calendars_event_is_not_deleted_from_google(
        self, db_session
    ):
        """Editing a shared event must not remove it from the other calendar."""
        journal_id, other_calendar, _ = await self._seed(
            db_session, second_link_identity="widget-7f3a::instance-0"
        )

        client = await self._push_update(db_session, journal_id)

        client.delete_event.assert_not_called()
        assert await self._link_exists(db_session, journal_id, other_calendar)

    async def test_a_link_this_push_created_is_still_pruned(self, db_session):
        """A journal genuinely moved between calendars still tidies up.

        An outbound link with no token is an event this push put there and
        no inbound sync has ever seen: exactly what pruning is for.
        """
        journal_id, other_calendar, _ = await self._seed(
            db_session,
            second_link_identity=None,
            second_link_capability="outbound",
        )

        client = await self._push_update(db_session, journal_id)

        client.delete_event.assert_called_once()
        assert not await self._link_exists(db_session, journal_id, other_calendar)

    async def test_a_tokenless_inbound_link_is_not_deleted(self, db_session):
        """A link the sync created before tokens existed is still real.

        Tokens arrive by backfill on a calendar's next poll, and an event
        with no iCalUID never gets one at all — so "no token" cannot mean
        "not confirmed upstream". A bidirectional link is the sync's own
        record that the calendar returned this event, whatever its token
        says, and deleting it would destroy something real.
        """
        journal_id, other_calendar, _ = await self._seed(
            db_session,
            second_link_identity=None,
            second_link_capability="bidirectional",
        )

        client = await self._push_update(db_session, journal_id)

        client.delete_event.assert_not_called()
        assert await self._link_exists(db_session, journal_id, other_calendar)

    async def test_a_link_the_sync_vouched_for_is_never_deleted(self, db_session):
        """A token is evidence the calendar really holds an event.

        Only the inbound sync sets one, and it does so by matching the link
        to an event the calendar actually returned. Whatever the journal has
        since done, deleting that event would destroy something real — so a
        different token protects the link just as a matching one does.
        """
        journal_id, other_calendar, _ = await self._seed(
            db_session, second_link_identity="widget-7f3a::instance-1"
        )

        client = await self._push_update(db_session, journal_id)

        client.delete_event.assert_not_called()
        assert await self._link_exists(db_session, journal_id, other_calendar)

    async def test_the_shared_event_survives_the_journal_moving_calendars(
        self, db_session
    ):
        """Moving the journal must not delete the event off a third calendar.

        Reassigning a journal's calendar deletes the *old* calendar's link —
        and that was the link carrying the token its de-duplicated sibling
        was recognised by. A rule that protected a link only by comparing it
        against its siblings would lose the sibling and the protection in the
        same move, and delete a real event off the user's other calendar.
        """
        journal_id, other_calendar, _ = await self._seed(
            db_session, second_link_identity="widget-7f3a::instance-0"
        )
        # The move: the display calendar's link goes, as
        # CalendarInfoRepository.save does when the calendar changes.
        await db_session.execute(
            text(
                "DELETE FROM journal_external_event_links"
                " WHERE journal_id = :journal_id AND external_event_id ="
                " 'work-copy-1'"
            ),
            {"journal_id": journal_id},
        )
        await db_session.commit()

        client = await self._push_update(db_session, journal_id)

        client.delete_event.assert_not_called()
        assert await self._link_exists(db_session, journal_id, other_calendar)


@pytest.mark.asyncio
class TestProcessJournalEventTimezoneIntegration:
    """An all-day event is pushed on the user's local date, not the UTC date."""

    async def test_all_day_event_is_pushed_on_the_users_local_date(self, db_session):
        user_id = str(uuid.uuid4())
        google_email = f"test_{uuid.uuid4().hex[:8]}@example.com"
        calendar_id = str(uuid.uuid4())

        journal_id = await _setup_journal_event_test_data(
            db_session, user_id, google_email, calendar_id, "Birthday", False
        )

        # The create form stores local midnight as an instant: midnight on
        # 5 Sept in Sydney (UTC+10) is 14:00 UTC on 4 Sept. The user has no
        # per-event timezone (all-day events never carry one), only their
        # configured setting.
        sydney_midnight_5_sept = datetime(2026, 9, 4, 14, 0, tzinfo=UTC)
        await db_session.execute(
            text("""
            UPDATE journals
            SET event_date_range_start = :at, event_date_range_end = :at
            WHERE id = :journal_id
            """),
            {"at": sydney_midnight_5_sept, "journal_id": journal_id},
        )
        await db_session.execute(
            text("""
            UPDATE journal_calendar_info
            SET is_all_day = true, timezone = NULL
            WHERE journal_id = :journal_id
            """),
            {"journal_id": journal_id},
        )
        await db_session.execute(
            text("""
            INSERT INTO user_settings (user_id, timezone)
            VALUES (:user_id, 'Australia/Sydney')
            """),
            {"user_id": user_id},
        )
        await db_session.commit()

        @asynccontextmanager
        async def mock_session_factory():
            yield db_session

        mock_client = AsyncMock()
        mock_client.create_event.return_value = {"id": "google_event_tz", "etag": "e"}

        with (
            patch("worker.GoogleAuthService", return_value=AsyncMock()),
            patch("worker.GoogleAPIClient", return_value=mock_client),
        ):
            result = await process_journal_event(
                ctx={"session_factory": mock_session_factory, "job_id": "tz_job"},
                event_type="JournalCreated",
                event_data={"journal_id": journal_id},
            )

        assert result["status"] == "success"
        payload = mock_client.create_event.call_args[0][0]
        assert payload["start"] == {"date": "2026-09-05"}
        assert payload["end"] == {"date": "2026-09-06"}


@pytest.mark.asyncio
class TestProcessJournalEventSkipsIntegration:
    """The ways an outbound push declines to write, proved against the DB.

    Both decisions are about what is *committed* on the link row afterwards,
    which is the part a mocked session cannot demonstrate.
    """

    @staticmethod
    @asynccontextmanager
    async def _factory(db_session: AsyncConnection) -> AsyncIterator[AsyncConnection]:
        yield db_session

    async def _seed(self, db_session: AsyncConnection) -> tuple[int, str]:
        user_id = str(uuid.uuid4())
        calendar_id = str(uuid.uuid4())
        journal_id = await _setup_journal_event_test_data(
            db_session,
            user_id,
            f"test_{uuid.uuid4().hex[:8]}@example.com",
            calendar_id,
            "Birthday",
            True,
        )
        return journal_id, calendar_id

    @staticmethod
    async def _link(
        db_session: AsyncConnection, journal_id: int, calendar_id: str
    ) -> Any:
        result = await db_session.execute(
            text("""
                SELECT external_event_id, external_version, sync_status
                FROM journal_external_event_links
                WHERE journal_id = :journal_id AND calendar_id = :calendar_id
            """),
            {"journal_id": journal_id, "calendar_id": calendar_id},
        )
        return result.fetchone()

    async def _run(
        self,
        db_session: AsyncConnection,
        journal_id: int,
        mock_client: AsyncMock,
        event_data: dict[str, Any],
    ) -> dict[str, Any]:
        with (
            patch("worker.GoogleAuthService", return_value=AsyncMock()),
            patch("worker.GoogleAPIClient", return_value=mock_client),
        ):
            return await process_journal_event(
                ctx={
                    "session_factory": lambda: self._factory(db_session),
                    "job_id": "test_skip",
                },
                event_type="JournalUpdated",
                event_data={"journal_id": journal_id, **event_data},
            )

    @staticmethod
    def _refusing_client() -> AsyncMock:
        """A Google that refuses the write and reports the calendar read-only."""
        client = AsyncMock()
        client.update_event.side_effect = HttpError(
            resp=MagicMock(status=403, reason="Forbidden"),
            content=(
                b'{"error": {"code": 403, "errors": [{"domain": "global", '
                b'"reason": "forbidden", "message": "Forbidden"}]}}'
            ),
        )
        client.list_calendars.return_value = {
            "items": [{"id": "shared@example.com", "accessRole": "reader"}]
        }
        return client

    async def test_restricted_event_type_commits_the_divergence(
        self, db_session, event_type_restriction_error
    ) -> None:
        """Google refuses the write, so the link records that it did not land —
        and the task returns rather than raising it back to the stream."""
        journal_id, calendar_id = await self._seed(db_session)

        mock_client = AsyncMock()
        mock_client.update_event.side_effect = event_type_restriction_error

        result = await self._run(
            db_session,
            journal_id,
            mock_client,
            {"changed_fields": {"title": ("Old", "New")}, "source": "ui"},
        )

        assert result["status"] == "ignored"
        assert result["reason"] == "event_type_not_modifiable"

        link = await self._link(db_session, journal_id, calendar_id)
        assert link.sync_status == "errored"
        # The event id survives: the journal is still that Google event's,
        # it is just no longer in step with it.
        assert link.external_event_id == "existing_event_id_123"

    async def test_inbound_sync_echo_leaves_the_link_untouched(
        self, db_session
    ) -> None:
        """A journal the inbound sync applied is already in step with Google,
        so the push must neither call the API nor disturb the link."""
        journal_id, calendar_id = await self._seed(db_session)
        before = await self._link(db_session, journal_id, calendar_id)

        mock_client = AsyncMock()

        result = await self._run(
            db_session,
            journal_id,
            mock_client,
            {
                "changed_fields": {"title": ("Old", "New")},
                "source": "google_calendar",
            },
        )

        assert result == {"status": "ignored", "reason": "inbound_sync_echo"}
        mock_client.update_event.assert_not_called()
        mock_client.create_event.assert_not_called()

        after = await self._link(db_session, journal_id, calendar_id)
        assert after == before

    async def test_a_read_only_calendar_is_never_written_to(self, db_session) -> None:
        """The stored role stops the push before Google is called at all."""
        journal_id, calendar_id = await self._seed(db_session)
        await _connect_calendar_to_google(
            db_session, calendar_id, "shared@example.com", "reader"
        )
        before = await self._link(db_session, journal_id, calendar_id)

        mock_client = AsyncMock()

        result = await self._run(
            db_session,
            journal_id,
            mock_client,
            {"changed_fields": {"title": ("Old", "New")}, "source": "ui"},
        )

        assert result["reason"] == "read_only_calendar"
        mock_client.update_event.assert_not_called()
        assert await self._link(db_session, journal_id, calendar_id) == before

    async def test_a_read_only_calendar_is_never_deleted_from(self, db_session) -> None:
        """Deletion is a write too: it reads the roles rather than trying it."""
        journal_id, calendar_id = await self._seed(db_session)
        await _connect_calendar_to_google(
            db_session, calendar_id, "shared@example.com", "freeBusyReader"
        )

        mock_client = AsyncMock()

        with (
            patch("worker.GoogleAuthService", return_value=AsyncMock()),
            patch("worker.GoogleAPIClient", return_value=mock_client),
        ):
            result = await process_journal_event(
                ctx={
                    "session_factory": lambda: self._factory(db_session),
                    "job_id": "test_skip_delete",
                },
                event_type="JournalDeleted",
                event_data={
                    "journal_id": journal_id,
                    "user_id": await _read_calendar_user_id(db_session, calendar_id),
                    "external_identifiers": {
                        "google": [
                            {
                                "external_event_id": "existing_event_id_123",
                                "google_calendar_id": "shared@example.com",
                            }
                        ]
                    },
                },
            )

        assert result["read_only_event_ids"] == ["existing_event_id_123"]
        mock_client.delete_event.assert_not_called()

    async def test_a_refused_push_is_not_reported_as_a_failure(
        self, db_session
    ) -> None:
        """Raising here would retry a refusal the stream consumer cannot fix."""
        journal_id, calendar_id = await self._seed(db_session)
        await _connect_calendar_to_google(
            db_session, calendar_id, "shared@example.com", "writer"
        )

        result = await self._run(
            db_session,
            journal_id,
            self._refusing_client(),
            {"changed_fields": {"title": ("Old", "New")}, "source": "ui"},
        )

        assert result["status"] == "ignored"
        assert result["reason"] == "forbidden"

    async def test_a_refused_push_marks_the_link_errored(self, db_session) -> None:
        journal_id, calendar_id = await self._seed(db_session)
        await _connect_calendar_to_google(
            db_session, calendar_id, "shared@example.com", "writer"
        )

        await self._run(
            db_session,
            journal_id,
            self._refusing_client(),
            {"changed_fields": {"title": ("Old", "New")}, "source": "ui"},
        )

        link = await self._link(db_session, journal_id, calendar_id)
        assert link.sync_status == "errored"

    async def test_a_refused_push_corrects_the_stored_access_role(
        self, db_session
    ) -> None:
        """The stale "writer" is why the push was attempted at all."""
        journal_id, calendar_id = await self._seed(db_session)
        await _connect_calendar_to_google(
            db_session, calendar_id, "shared@example.com", "writer"
        )

        await self._run(
            db_session,
            journal_id,
            self._refusing_client(),
            {"changed_fields": {"title": ("Old", "New")}, "source": "ui"},
        )

        assert await _read_access_role(db_session, calendar_id) == "reader"


@pytest.mark.asyncio
class TestRefreshCalendarAccessRolesIntegration:
    """Storing Google's current access roles against real calendar rows."""

    @staticmethod
    async def _seed_calendar(
        db_session: AsyncConnection,
        user_id: str,
        google_calendar_id: str,
        access_role: str | None,
    ) -> str:
        calendar_id = str(uuid.uuid4())
        await db_session.execute(
            text("""
                INSERT INTO calendars (
                    id, user_id, name, color, is_synced_to_google,
                    google_calendar_id, access_role
                )
                VALUES (
                    :id, :user_id, 'Work', '#FF0000', true,
                    :google_calendar_id, :access_role
                )
            """),
            {
                "id": calendar_id,
                "user_id": user_id,
                "google_calendar_id": google_calendar_id,
                "access_role": access_role,
            },
        )
        await db_session.commit()
        return calendar_id

    @staticmethod
    def _client(*calendars: tuple[str, str]) -> AsyncMock:
        client = AsyncMock()
        client.list_calendars.return_value = {
            "items": [
                {"id": google_calendar_id, "accessRole": access_role}
                for google_calendar_id, access_role in calendars
            ]
        }
        return client

    async def test_a_downgraded_role_is_stored(self, db_session) -> None:
        from worker import _refresh_calendar_access_roles

        user_id = str(uuid.uuid4())
        calendar_id = await self._seed_calendar(
            db_session, user_id, "shared@example.com", "writer"
        )

        changed = await _refresh_calendar_access_roles(
            db_session, self._client(("shared@example.com", "reader")), user_id
        )

        assert changed == 1
        assert await _read_access_role(db_session, calendar_id) == "reader"

    async def test_a_role_that_was_never_captured_is_filled_in(
        self, db_session
    ) -> None:
        """Every calendar connected before this existed has a NULL role."""
        from worker import _refresh_calendar_access_roles

        user_id = str(uuid.uuid4())
        calendar_id = await self._seed_calendar(
            db_session, user_id, "shared@example.com", None
        )

        await _refresh_calendar_access_roles(
            db_session, self._client(("shared@example.com", "owner")), user_id
        )

        assert await _read_access_role(db_session, calendar_id) == "owner"

    async def test_another_users_calendar_is_left_alone(self, db_session) -> None:
        """Two accounts can hold the same shared Google calendar."""
        from worker import _refresh_calendar_access_roles

        user_id = str(uuid.uuid4())
        other_user_id = str(uuid.uuid4())
        await self._seed_calendar(db_session, user_id, "shared@example.com", "writer")
        other_calendar_id = await self._seed_calendar(
            db_session, other_user_id, "shared@example.com", "owner"
        )

        await _refresh_calendar_access_roles(
            db_session, self._client(("shared@example.com", "reader")), user_id
        )

        assert await _read_access_role(db_session, other_calendar_id) == "owner"

    async def test_an_unchanged_role_is_not_rewritten(self, db_session) -> None:
        from worker import _refresh_calendar_access_roles

        user_id = str(uuid.uuid4())
        await self._seed_calendar(db_session, user_id, "shared@example.com", "owner")

        changed = await _refresh_calendar_access_roles(
            db_session, self._client(("shared@example.com", "owner")), user_id
        )

        assert changed == 0

    @staticmethod
    async def _connect_account(db_session: AsyncConnection, user_id: str) -> None:
        """One connected Google account, which is what the sweep requires."""
        await db_session.execute(
            text("""
                INSERT INTO user_google_auth (
                    user_id, google_account_email, encrypted_access_token,
                    encrypted_refresh_token, expires_at, created_at, updated_at
                )
                VALUES (
                    :user_id, :email, :token, :refresh,
                    now() + interval '1 hour', now(), now()
                )
            """),
            {
                "user_id": user_id,
                "email": f"test_{uuid.uuid4().hex[:8]}@example.com",
                "token": b"fake_token",
                "refresh": b"fake_refresh",
            },
        )
        await db_session.commit()

    async def test_a_calendar_that_left_the_list_is_marked_unreachable(
        self, db_session
    ) -> None:
        """Revoking a share removes the calendar instead of downgrading it."""
        from worker import _refresh_calendar_access_roles

        user_id = str(uuid.uuid4())
        await self._connect_account(db_session, user_id)
        revoked = await self._seed_calendar(
            db_session, user_id, "gone@example.com", "writer"
        )
        kept = await self._seed_calendar(
            db_session, user_id, "mine@example.com", "owner"
        )

        await _refresh_calendar_access_roles(
            db_session, self._client(("mine@example.com", "owner")), user_id
        )

        assert await _read_access_role(db_session, revoked) == "none"
        assert await _read_access_role(db_session, kept) == "owner"

    async def test_a_vanished_calendar_is_then_never_written_to(
        self, db_session
    ) -> None:
        """Which is the point: the refusals stop instead of repeating."""
        from worker import is_read_only_calendar

        user_id = str(uuid.uuid4())
        await self._connect_account(db_session, user_id)
        revoked = await self._seed_calendar(
            db_session, user_id, "gone@example.com", "writer"
        )

        from worker import _refresh_calendar_access_roles

        await _refresh_calendar_access_roles(
            db_session, self._client(("mine@example.com", "owner")), user_id
        )

        assert is_read_only_calendar(await _read_access_role(db_session, revoked))

    async def test_another_connected_account_holds_the_sweep_back(
        self, db_session
    ) -> None:
        """A second account's list cannot speak for the first's calendars."""
        from worker import _refresh_calendar_access_roles

        user_id = str(uuid.uuid4())
        await self._connect_account(db_session, user_id)
        await self._connect_account(db_session, user_id)
        absent = await self._seed_calendar(
            db_session, user_id, "gone@example.com", "writer"
        )

        await _refresh_calendar_access_roles(
            db_session, self._client(("mine@example.com", "owner")), user_id
        )

        assert await _read_access_role(db_session, absent) == "writer"
