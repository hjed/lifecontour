"""Integration tests for recurring-series handling in sync_calendar_events.

Covers the whole-series deletion signal (a single cancelled master event)
emitting a journal_event.series_cancelled outbox event, and the backfill
promotion of ETag-unchanged instances whose link predates the series feature.
"""

import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text

from worker import sync_calendar_events


def _as_dict(event_data: object) -> dict:
    """Normalize a raw outbox event_data column value to a dict."""
    if isinstance(event_data, str):
        return json.loads(event_data)
    assert isinstance(event_data, dict)
    return event_data


TEST_EMAIL = "series_sync_test@example.com"
TEST_USER = "22222222-2222-2222-2222-222222222222"
MASTER_ID = "recurring-master-abc"
ETAG = '"etag-series-1"'


async def _seed_calendar_with_recurring_instance(
    db_session,
    *,
    link_recurring_event_id: str | None,
) -> tuple[str, int]:
    """Seed a synced calendar plus one journal linked to a recurring instance."""
    now = datetime.now(UTC)
    calendar_uuid = str(uuid.uuid4())
    journal_id = int(datetime.now(UTC).timestamp() * 1000) % 1_000_000 + 5000

    await db_session.execute(
        text("""
            INSERT INTO calendars (id, user_id, name, color, created_at,
                updated_at, google_calendar_id, is_synced_to_google)
            VALUES (:cal_id, :user_id, 'Series Cal', '#00FF00', :now, :now,
                'primary', true)
        """),
        {"cal_id": calendar_uuid, "user_id": TEST_USER, "now": now},
    )
    await db_session.execute(
        text("""
            INSERT INTO journals (id, user_id, title, content,
                event_date_range_start, event_date_range_end,
                created_at, updated_at)
            VALUES (:journal_id, :user_id, 'Recurring Instance', '', :now,
                :now, :now, :now)
        """),
        {"journal_id": journal_id, "user_id": TEST_USER, "now": now},
    )
    await db_session.execute(
        text("""
            INSERT INTO journal_external_event_links
            (journal_id, calendar_id, external_event_id, external_version,
             recurring_event_id, sync_capability, sync_status,
             created_at, updated_at)
            VALUES (:journal_id, :cal_id, :external_event_id, :etag,
                :recurring_event_id, 'bidirectional', 'synced', :now, :now)
        """),
        {
            "journal_id": journal_id,
            "cal_id": calendar_uuid,
            "external_event_id": f"{MASTER_ID}_20260801T090000Z",
            "etag": ETAG,
            "recurring_event_id": link_recurring_event_id,
            "now": now,
        },
    )
    await db_session.commit()
    return calendar_uuid, journal_id


def _ctx(db_session) -> dict:
    @asynccontextmanager
    async def mock_session_factory():
        yield db_session

    return {
        "session_factory": mock_session_factory,
        "redis": AsyncMock(),
        "job_id": "test_series_job",
    }


async def _run_sync(db_session, items: list[dict]) -> dict:
    mock_client = MagicMock()
    mock_client.list_events = AsyncMock(
        return_value={"items": items, "nextSyncToken": "sync_token"}
    )
    with patch("worker._create_google_client", return_value=mock_client):
        return await sync_calendar_events(
            _ctx(db_session), TEST_EMAIL, TEST_USER, "smart"
        )


@pytest.mark.asyncio
class TestRecurringSeriesSyncIntegration:
    async def test_series_deletion_creates_series_cancelled_outbox_event(
        self, db_session
    ) -> None:
        """A cancelled master id with linked instances emits a series event."""
        calendar_uuid, _ = await _seed_calendar_with_recurring_instance(
            db_session, link_recurring_event_id=MASTER_ID
        )

        result = await _run_sync(
            db_session,
            [{"id": MASTER_ID, "status": "cancelled", "etag": '"etag-cancelled"'}],
        )

        assert result["status"] == "success"
        assert result.get("series_cancellations") == 1

        outbox = await db_session.execute(
            text("""
                SELECT event_data FROM outbox_events
                WHERE event_type = 'journal_event.series_cancelled'
            """)
        )
        rows = outbox.fetchall()
        assert len(rows) == 1
        event_data = _as_dict(rows[0].event_data)
        assert event_data["recurring_event_id"] == MASTER_ID
        assert event_data["calendar_id"] == calendar_uuid

    async def test_unchanged_instance_backfills_recurring_id_via_update(
        self, db_session
    ) -> None:
        """An ETag-unchanged instance with an unbackfilled link is promoted."""
        _, journal_id = await _seed_calendar_with_recurring_instance(
            db_session, link_recurring_event_id=None
        )

        result = await _run_sync(
            db_session,
            [
                {
                    "id": f"{MASTER_ID}_20260801T090000Z",
                    "summary": "Recurring Instance",
                    "etag": ETAG,  # unchanged
                    "status": "confirmed",
                    "recurringEventId": MASTER_ID,
                    "start": {"dateTime": "2026-08-01T09:00:00Z"},
                    "end": {"dateTime": "2026-08-01T10:00:00Z"},
                }
            ],
        )

        assert result["status"] == "success"

        outbox = await db_session.execute(
            text("""
                SELECT event_data FROM outbox_events
                WHERE event_type = 'journal_event.updated'
            """)
        )
        rows = outbox.fetchall()
        assert len(rows) == 1
        event_data = _as_dict(rows[0].event_data)
        assert event_data["recurring_event_id"] == MASTER_ID
        assert event_data["existing_journal_id"] == journal_id

    async def test_backfilled_unchanged_instance_stays_skipped(
        self, db_session
    ) -> None:
        """Once backfilled, unchanged instances create no further events."""
        await _seed_calendar_with_recurring_instance(
            db_session, link_recurring_event_id=MASTER_ID
        )

        result = await _run_sync(
            db_session,
            [
                {
                    "id": f"{MASTER_ID}_20260801T090000Z",
                    "summary": "Recurring Instance",
                    "etag": ETAG,  # unchanged
                    "status": "confirmed",
                    "recurringEventId": MASTER_ID,
                    "start": {"dateTime": "2026-08-01T09:00:00Z"},
                    "end": {"dateTime": "2026-08-01T10:00:00Z"},
                }
            ],
        )

        assert result["status"] == "success"
        assert result["events_skipped"] >= 1

        outbox = await db_session.execute(
            text(
                "SELECT count(*) FROM outbox_events WHERE event_type LIKE 'journal_event.%'"
            )
        )
        assert outbox.scalar() == 0
