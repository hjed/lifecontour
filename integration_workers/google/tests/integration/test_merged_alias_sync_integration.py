"""A calendar sync leaves an event a merge absorbed alone.

The backend refuses to re-import an aliased event whatever the worker sends,
so this check is advisory: it spares a full sync from emitting a create for
every event a merge ever absorbed, and keeps the metrics honest about why
those events produced nothing.
"""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from core_shared.repositories.merged_alias_repository import (
    ExternalRecord,
    MergedAliasRepository,
)
from sqlalchemy import text

from calendar_models import GoogleEvent
from event_identity import build_event_identity
from worker import sync_calendar_events

TEST_EMAIL = "merged_alias_sync@example.com"
TEST_USER = "33333333-3333-3333-3333-333333333333"


async def _seed_merged_journal(db_session) -> str:
    """A synced calendar whose journal absorbed ``dm1q`` by merging."""
    now = datetime.now(UTC)
    calendar_id = str(uuid.uuid4())
    journal_id = int(now.timestamp() * 1000) % 1_000_000 + 7000
    await db_session.execute(
        text("""
            INSERT INTO calendars (id, user_id, name, color, created_at,
                updated_at, google_calendar_id, is_synced_to_google)
            VALUES (:id, :user_id, 'Work', '#00FF00', :now, :now, 'primary', true)
        """),
        {"id": calendar_id, "user_id": TEST_USER, "now": now},
    )
    await db_session.execute(
        text("""
            INSERT INTO journals (id, user_id, title, content,
                event_date_range_start, event_date_range_end, created_at, updated_at)
            VALUES (:id, :user_id, 'Pilates', '', :now, :now, :now, :now)
        """),
        {"id": journal_id, "user_id": TEST_USER, "now": now},
    )
    await MergedAliasRepository(db_session).record_aliases(
        journal_id=journal_id,
        user_id=TEST_USER,
        records=[
            ExternalRecord(
                integration_source="google_calendar",
                external_id="dm1q_20260904T021500Z",
                calendar_id=uuid.UUID(calendar_id),
                external_identity=_ABSORBED_IDENTITY,
            )
        ],
    )
    await db_session.commit()
    return calendar_id


async def _run_sync(db_session, items: list[dict]) -> dict:
    @asynccontextmanager
    async def session_factory():
        yield db_session

    client = MagicMock()
    client.list_events = AsyncMock(
        return_value={"items": items, "nextSyncToken": "sync_token"}
    )
    with patch("worker._create_google_client", return_value=client):
        return await sync_calendar_events(
            {
                "session_factory": session_factory,
                "redis": AsyncMock(),
                "job_id": "merged_alias_job",
            },
            TEST_EMAIL,
            TEST_USER,
            "smart",
        )


def _absorbed_copy(event_id: str) -> dict:
    """An instance of the absorbed ``dm1q`` series, as any calendar reports it."""
    return _event(
        event_id,
        iCalUID="dm1q@google.com",
        recurringEventId="dm1q",
        originalStartTime={"dateTime": "2026-09-04T02:15:00Z"},
    )


def _event(event_id: str, **extra: object) -> dict:
    return {
        "id": event_id,
        "status": "confirmed",
        "etag": '"etag-1"',
        "summary": "Pilates",
        "start": {"dateTime": "2026-09-04T12:15:00+10:00"},
        "end": {"dateTime": "2026-09-04T13:15:00+10:00"},
        **extra,
    }


_ABSORBED_IDENTITY = build_event_identity(
    GoogleEvent.from_api_response(_absorbed_copy("dm1q_20260904T021500Z"))
)


async def _journal_events(db_session) -> list[str]:
    result = await db_session.execute(
        text("""
            SELECT event_type FROM outbox_events
            WHERE event_type LIKE 'journal_event.%'
        """)
    )
    return [row.event_type for row in result]


@pytest.mark.asyncio
class TestMergedAliasSync:
    async def test_an_absorbed_event_is_not_sent_to_be_created(
        self, db_session
    ) -> None:
        await _seed_merged_journal(db_session)

        result = await _run_sync(db_session, [_event("dm1q_20260904T021500Z")])

        assert result["status"] == "success"
        assert result.get("events_skipped_merged") == 1
        assert await _journal_events(db_session) == []

    async def test_a_copy_of_an_absorbed_event_is_recognised_by_identity(
        self, db_session
    ) -> None:
        """Another id for the same instance — its iCalUID and original start."""
        await _seed_merged_journal(db_session)

        result = await _run_sync(
            db_session,
            [_absorbed_copy("other-copy-of-dm1q")],
        )

        assert result.get("events_skipped_merged") == 1
        assert await _journal_events(db_session) == []

    async def test_an_unrelated_event_is_still_created(self, db_session) -> None:
        await _seed_merged_journal(db_session)

        await _run_sync(db_session, [_event("brand-new-event")])

        assert await _journal_events(db_session) == ["journal_event.created"]
