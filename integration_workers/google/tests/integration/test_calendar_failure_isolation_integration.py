"""One calendar failing must not stop the rest of an account's inbound sync.

Each calendar is its own unit of work: a failing one is rolled back and the
next carries on. These run against a real session because what they prove —
that the rollback keeps the calendars already synced, and leaves the session
usable after a database error — is exactly what a mocked session hides.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import split_adoption
import worker
from google_auth_service import TokenRevokedError
from worker import sync_calendar_events

USER_ID = "22222222-2222-2222-2222-222222222222"
ACCOUNT_EMAIL = "isolation@example.com"


async def _seed_calendars(
    session: AsyncSession, google_calendar_ids: list[str]
) -> dict[str, str]:
    """Seed one synced calendar per Google id, oldest first; map id -> row id."""
    base = datetime.now(UTC)
    rows: dict[str, str] = {}
    for offset, google_calendar_id in enumerate(google_calendar_ids):
        calendar_id = str(uuid.uuid4())
        created_at = base + timedelta(seconds=offset)
        await session.execute(
            text("""
                INSERT INTO calendars (id, user_id, name, color, created_at,
                                       updated_at, google_calendar_id,
                                       is_synced_to_google)
                VALUES (:id, :user_id, :name, '#FF0000', :created_at,
                        :created_at, :google_calendar_id, true)
            """),
            {
                "id": calendar_id,
                "user_id": USER_ID,
                "name": google_calendar_id,
                "created_at": created_at,
                "google_calendar_id": google_calendar_id,
            },
        )
        rows[google_calendar_id] = calendar_id
    await session.commit()
    return rows


def _client_failing_on(google_calendar_id: str, error: Exception) -> MagicMock:
    """A client whose ``events.list`` raises for one calendar only."""

    async def _list_events(**kwargs: Any) -> dict[str, Any]:
        if kwargs["calendar_id"] == google_calendar_id:
            raise error
        return {
            "items": [
                {
                    "id": f"event-{kwargs['calendar_id']}",
                    "summary": "Standup",
                    "etag": '"etag-1"',
                    "status": "confirmed",
                    "start": {"dateTime": "2026-03-20T10:00:00Z"},
                    "end": {"dateTime": "2026-03-20T11:00:00Z"},
                }
            ],
            "nextSyncToken": f"token-{kwargs['calendar_id']}",
        }

    client = MagicMock()
    client.list_events = AsyncMock(side_effect=_list_events)
    return client


async def _run_sync(session: AsyncSession, client: MagicMock) -> dict[str, Any]:
    @asynccontextmanager
    async def _session_factory() -> AsyncIterator[AsyncSession]:
        yield session

    ctx = {
        "session_factory": _session_factory,
        "redis": AsyncMock(),
        "job_id": "isolation-job",
    }
    with patch("worker._create_google_client", return_value=client):
        return await sync_calendar_events(ctx, ACCOUNT_EMAIL, USER_ID, "full")


async def _synced_calendar_ids(session: AsyncSession) -> set[str]:
    """Row ids of the calendars that produced an outbox event."""
    result = await session.execute(
        text("""
            SELECT DISTINCT event_data::jsonb->>'calendar_id'
            FROM outbox_events
            WHERE event_type = 'journal_event.created'
        """)
    )
    return {row[0] for row in result.fetchall()}


async def _calendars_with_tokens(session: AsyncSession) -> set[str]:
    result = await session.execute(
        text("""
            SELECT google_calendar_id FROM calendar_sync_tokens
            WHERE user_id = :user_id AND sync_token IS NOT NULL
        """),
        {"user_id": USER_ID},
    )
    return {row[0] for row in result.fetchall()}


@pytest.mark.asyncio
class TestCalendarFailureIsolation:
    async def test_an_unreadable_calendar_keeps_both_neighbours_synced(
        self, db_session: AsyncSession
    ) -> None:
        """Calendars synced before and after the failing one both persist."""
        calendars = await _seed_calendars(
            db_session, ["before@example.com", "gone@example.com", "after@example.com"]
        )
        not_found = HttpError(
            resp=MagicMock(status=404, reason="Not Found"),
            content=b'{"error": {"code": 404}}',
        )

        result = await _run_sync(
            db_session, _client_failing_on("gone@example.com", not_found)
        )

        assert result["status"] == "success"
        assert result["calendars_failed"] == 1
        assert await _synced_calendar_ids(db_session) == {
            calendars["before@example.com"],
            calendars["after@example.com"],
        }
        assert await _calendars_with_tokens(db_session) == {
            "before@example.com",
            "after@example.com",
        }

    async def test_a_database_error_in_one_calendar_leaves_the_session_usable(
        self, db_session: AsyncSession
    ) -> None:
        """An aborted transaction is rolled back so the next calendar can sync."""
        calendars = await _seed_calendars(
            db_session, ["broken@example.com", "after@example.com"]
        )
        real_find_split_pairing = split_adoption.find_split_pairing

        async def _pairing_that_breaks_one_calendar(
            session: AsyncSession, calendar_id: Any, *args: Any
        ) -> Any:
            if str(calendar_id) == calendars["broken@example.com"]:
                await session.execute(text("SELECT * FROM no_such_table"))
            return await real_find_split_pairing(session, calendar_id, *args)

        with patch(
            "split_adoption.find_split_pairing",
            side_effect=_pairing_that_breaks_one_calendar,
        ):
            result = await _run_sync(
                db_session, _client_failing_on("none", RuntimeError())
            )

        assert result["status"] == "success"
        assert result["calendars_failed"] == 1
        assert await _synced_calendar_ids(db_session) == {
            calendars["after@example.com"]
        }
        assert await _calendars_with_tokens(db_session) == {"after@example.com"}

    async def test_a_calendar_failing_after_queuing_events_keeps_none_of_them(
        self, db_session: AsyncSession
    ) -> None:
        """A failed token save discards the calendar's events, and their counts."""
        calendars = await _seed_calendars(
            db_session, ["unsaved@example.com", "after@example.com"]
        )
        real_save_token = worker._save_calendar_sync_token

        async def _save_failing_for_one(
            session: AsyncSession, token: str, *args: Any
        ) -> None:
            if args[-1] == "unsaved@example.com":
                raise RuntimeError("token save failed")
            await real_save_token(session, token, *args)

        with patch(
            "worker._save_calendar_sync_token", side_effect=_save_failing_for_one
        ):
            result = await _run_sync(
                db_session, _client_failing_on("none", RuntimeError())
            )

        assert result["status"] == "success"
        assert result["calendars_failed"] == 1
        assert result["events_created"] == 1
        assert await _synced_calendar_ids(db_session) == {
            calendars["after@example.com"]
        }
        assert await _calendars_with_tokens(db_session) == {"after@example.com"}

    @pytest.mark.parametrize(
        "account_error",
        [
            RefreshError("cannot refresh the access token"),
            TokenRevokedError("revoked"),
        ],
        ids=["refresh_rejected", "revoked"],
    )
    async def test_a_credential_failure_fails_the_sync_rather_than_one_calendar(
        self, db_session: AsyncSession, account_error: Exception
    ) -> None:
        """Lost credentials fail every calendar alike, so the task reports it."""
        await _seed_calendars(db_session, ["before@example.com", "denied@example.com"])

        result = await _run_sync(
            db_session, _client_failing_on("denied@example.com", account_error)
        )

        assert result["status"] == "error"
        assert result["error_type"] == type(account_error).__name__
