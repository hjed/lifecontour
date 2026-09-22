"""Integration tests for backfilling unmatched participant emails.

The backend only started recording attendee emails that match no contact once
``journal_unmatched_participant_emails`` existed. An ETag-unchanged event is
skipped, so events synced before then would never be recorded; the sync
promotes such an event to an update once, and stops once the backend has
recorded its unmatched emails.
"""

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from worker import sync_calendar_events

TEST_EMAIL = "unmatched_backfill@example.com"
TEST_USER = "33333333-3333-3333-3333-333333333333"
EVENT_ID = "unmatched-backfill-event"
ETAG = '"etag-unmatched-1"'


async def _seed_synced_event(db_session: AsyncSession) -> int:
    """A synced calendar and one journal linked to ``EVENT_ID`` at ``ETAG``."""
    now = datetime.now(UTC)
    calendar_uuid = str(uuid.uuid4())
    journal_id = int(now.timestamp() * 1000) % 1_000_000 + 7000

    await db_session.execute(
        text("""
            INSERT INTO calendars (id, user_id, name, color, created_at,
                updated_at, google_calendar_id, is_synced_to_google)
            VALUES (:cal_id, :user_id, 'Backfill Cal', '#00FF00', :now, :now,
                'primary', true)
        """),
        {"cal_id": calendar_uuid, "user_id": TEST_USER, "now": now},
    )
    await db_session.execute(
        text("""
            INSERT INTO journals (id, user_id, title, content,
                event_date_range_start, event_date_range_end,
                created_at, updated_at)
            VALUES (:journal_id, :user_id, 'Team sync', '', :now, :now,
                :now, :now)
        """),
        {"journal_id": journal_id, "user_id": TEST_USER, "now": now},
    )
    await db_session.execute(
        text("""
            INSERT INTO journal_external_event_links
            (journal_id, calendar_id, external_event_id, external_version,
             sync_capability, sync_status, created_at, updated_at)
            VALUES (:journal_id, :cal_id, :external_event_id, :etag,
                'bidirectional', 'synced', :now, :now)
        """),
        {
            "journal_id": journal_id,
            "cal_id": calendar_uuid,
            "external_event_id": EVENT_ID,
            "etag": ETAG,
            "now": now,
        },
    )
    await db_session.commit()
    return journal_id


def _unchanged_event(attendees: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": EVENT_ID,
        "summary": "Team sync",
        "etag": ETAG,
        "status": "confirmed",
        "start": {"dateTime": "2026-08-01T09:00:00Z"},
        "end": {"dateTime": "2026-08-01T10:00:00Z"},
        "attendees": attendees,
    }


async def _run_sync(db_session: AsyncSession, items: list[dict[str, Any]]) -> None:
    @asynccontextmanager
    async def session_factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    ctx = {
        "session_factory": session_factory,
        "redis": AsyncMock(),
        "job_id": "test_unmatched_backfill_job",
    }
    mock_client = MagicMock()
    mock_client.list_events = AsyncMock(
        return_value={"items": items, "nextSyncToken": "sync_token"}
    )
    with patch("worker._create_google_client", return_value=mock_client):
        result = await sync_calendar_events(ctx, TEST_EMAIL, TEST_USER, "smart")
    assert result["status"] == "success"


async def _updated_journal_ids(db_session: AsyncSession) -> list[int]:
    result = await db_session.execute(
        text(
            "SELECT event_data FROM outbox_events"
            " WHERE event_type = 'journal_event.updated'"
        )
    )
    ids: list[int] = []
    for row in result.fetchall():
        data = row.event_data
        if isinstance(data, str):
            data = json.loads(data)
        ids.append(data["existing_journal_id"])
    return ids


@pytest.mark.asyncio
class TestUnmatchedParticipantBackfill:
    async def test_unrecorded_unmatched_email_promotes_unchanged_event(
        self, db_session: AsyncSession
    ) -> None:
        journal_id = await _seed_synced_event(db_session)

        await _run_sync(
            db_session, [_unchanged_event([{"email": "Stranger@Example.com"}])]
        )

        assert await _updated_journal_ids(db_session) == [journal_id]

    async def test_recorded_unmatched_email_stays_skipped(
        self, db_session: AsyncSession
    ) -> None:
        journal_id = await _seed_synced_event(db_session)
        await db_session.execute(
            text("""
                INSERT INTO journal_unmatched_participant_emails
                    (journal_id, email, relationship_type)
                VALUES (:journal_id, 'stranger@example.com', 'INVITEE')
            """),
            {"journal_id": journal_id},
        )
        await db_session.commit()

        await _run_sync(
            db_session, [_unchanged_event([{"email": "Stranger@Example.com"}])]
        )

        assert await _updated_journal_ids(db_session) == []

    async def test_self_and_resource_attendees_do_not_promote(
        self, db_session: AsyncSession
    ) -> None:
        await _seed_synced_event(db_session)

        await _run_sync(
            db_session,
            [
                _unchanged_event(
                    [
                        {"email": "me@example.com", "self": True},
                        {"email": "room@resource.example.com", "resource": True},
                    ]
                )
            ],
        )

        assert await _updated_journal_ids(db_session) == []

    async def test_attendee_already_linked_to_a_contact_does_not_promote(
        self, db_session: AsyncSession
    ) -> None:
        journal_id = await _seed_synced_event(db_session)
        contact_id = (
            await db_session.execute(
                text("INSERT INTO contacts (first_name) VALUES ('Known') RETURNING id")
            )
        ).scalar_one()
        await db_session.execute(
            text("""
                INSERT INTO contact_methods (contact_id, method_type, value)
                VALUES (:contact_id, 'email', 'known@example.com')
            """),
            {"contact_id": contact_id},
        )
        await db_session.execute(
            text("""
                INSERT INTO journal_contact_relationships
                    (journal_id, contact_id, relationship_type)
                VALUES (:journal_id, :contact_id, 'INVITEE')
            """),
            {"journal_id": journal_id, "contact_id": contact_id},
        )
        await db_session.commit()

        await _run_sync(
            db_session, [_unchanged_event([{"email": "known@example.com"}])]
        )

        assert await _updated_journal_ids(db_session) == []
