"""The calendar pull sends each event's synced base, and honours a pending import.

#1899: the journal push leaves Google's value alone for a field local did not
change, records its own etag and marks the link ``pending_import``. The pull
must then still send the event, and every event it sends carries the keys of
Google's values for the backend to record as the base.
"""

import json
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from core_shared.calendar_sync_base import google_event_keys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from worker import sync_calendar_events

USER_ID = "22222222-2222-2222-2222-222222222222"
ETAG = '"etag-pushed"'
EVENT = {
    "id": "pushed-event-1",
    "summary": "Physio (moved in Google)",
    "description": "Bring referral",
    "location": "Clinic",
    "etag": ETAG,
    "status": "confirmed",
    "start": {"dateTime": "2026-11-20T10:00:00Z"},
    "end": {"dateTime": "2026-11-20T11:00:00Z"},
}


async def _seed_link(session: AsyncSession, reference_data: str | None) -> None:
    now = datetime.now(UTC)
    calendar_id = str(uuid.uuid4())
    await session.execute(
        text("""
            INSERT INTO calendars (id, user_id, name, color, created_at,
                                   updated_at, google_calendar_id,
                                   is_synced_to_google)
            VALUES (:id, :user_id, 'Cal', '#FF0000', :now, :now, 'primary', true)
        """),
        {"id": calendar_id, "user_id": USER_ID, "now": now},
    )
    await session.execute(
        text("""
            INSERT INTO journals (id, user_id, title, content,
                                  event_date_range_start, event_date_range_end,
                                  created_at, updated_at)
            VALUES (4300, :user_id, 'Physio', '', :now, :now, :now, :now)
        """),
        {"user_id": USER_ID, "now": now},
    )
    await session.execute(
        text("""
            INSERT INTO journal_external_event_links
                (journal_id, calendar_id, external_event_id, external_version,
                 reference_data, sync_capability, sync_status, created_at,
                 updated_at)
            VALUES (4300, :calendar_id, :event_id, :etag, :reference_data,
                    'bidirectional', 'synced', :now, :now)
        """),
        {
            "calendar_id": calendar_id,
            "event_id": EVENT["id"],
            "etag": ETAG,
            "reference_data": reference_data,
            "now": now,
        },
    )
    await session.commit()


async def _pull(session: AsyncSession) -> list[dict[str, Any]]:
    """Run the calendar pull over ``EVENT``; the journal events it published."""

    @asynccontextmanager
    async def session_factory() -> AsyncIterator[AsyncSession]:
        yield session

    factory: Callable[[], AbstractAsyncContextManager[AsyncSession]] = session_factory
    client = MagicMock()
    client.list_events = AsyncMock(
        return_value={"items": [EVENT], "nextSyncToken": "token"}
    )
    ctx = {"session_factory": factory, "redis": AsyncMock(), "job_id": "pull"}
    with patch("worker._create_google_client", return_value=client):
        result = await sync_calendar_events(ctx, "pull@example.com", USER_ID, "smart")
    assert result["status"] == "success"

    rows = await session.execute(
        text(
            "SELECT event_data FROM outbox_events"
            " WHERE event_type LIKE 'journal_event.%'"
        )
    )
    return [
        data if isinstance(data, dict) else json.loads(data)
        for (data,) in rows.fetchall()
    ]


@pytest.mark.asyncio
class TestCalendarPullSyncedBase:
    async def test_a_pending_import_sends_the_event_its_etag_unchanged(
        self, db_session: AsyncSession
    ) -> None:
        await _seed_link(db_session, json.dumps({"pending_import": True}))

        events = await _pull(db_session)

        assert [event["sync_action"] for event in events] == ["updated"]
        assert events[0]["synced_entries"] == {
            field: [key] for field, key in google_event_keys(EVENT).items()
        }

    async def test_an_unchanged_event_without_one_is_still_skipped(
        self, db_session: AsyncSession
    ) -> None:
        await _seed_link(db_session, json.dumps({"pending_import": False}))

        assert await _pull(db_session) == []

    async def test_before_the_migration_the_link_is_read_without_a_base(
        self, db_session: AsyncSession
    ) -> None:
        await _seed_link(db_session, json.dumps({"pending_import": True}))

        with patch("worker.link_reference_data_ready", AsyncMock(return_value=False)):
            events = await _pull(db_session)

        # Nothing a push could have marked: the unchanged etag is skipped.
        assert events == []
