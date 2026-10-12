"""Migration test for 0136 (queue a tidy of every cancelled recurrence).

Before the keep-next rule, a recurrence Google truncated left every upcoming
occurrence behind as a cancelled journal. 0136 queues one
``journal_event.recurrence_tidy`` outbox event per (calendar, recurrence) that
still has a cancelled, not-yet-started linked journal, and the processor
applies the rule to each when it consumes them.

Runs against an isolated throwaway database so the shared session DB is
untouched.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

_PREVIOUS_REVISION = "0135"
_REVISION = "0136"

USER_ID = "user-recurrence-tidy"
CALENDAR_ID = UUID("00000000-0000-4000-8000-000000000136")


async def _seed(url: str, links: list[tuple[int, str | None, str, timedelta]]) -> None:
    """Journals linked as (id, recurring id, sync status, start from now)."""
    now = datetime.now(UTC)
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO calendars (id, user_id, name, color)"
                    " VALUES (:id, :user_id, 'Work', '#ffffff')"
                ),
                {"id": CALENDAR_ID, "user_id": USER_ID},
            )
            for journal_id, recurring_event_id, status, offset in links:
                await conn.execute(
                    text("""
                        INSERT INTO journals (id, user_id, title, content,
                            event_date_range_start, event_date_range_end)
                        VALUES (:id, :user_id, 'Pilates', '', :start, :start)
                    """),
                    {"id": journal_id, "user_id": USER_ID, "start": now + offset},
                )
                await conn.execute(
                    text("""
                        INSERT INTO journal_external_event_links
                            (journal_id, calendar_id, external_event_id,
                             recurring_event_id, sync_capability, sync_status,
                             created_at, updated_at)
                        VALUES (:id, :calendar_id, :external_id,
                                :recurring_event_id, 'bidirectional', :status,
                                now(), now())
                    """),
                    {
                        "id": journal_id,
                        "calendar_id": CALENDAR_ID,
                        "external_id": f"event-{journal_id}",
                        "recurring_event_id": recurring_event_id,
                        "status": status,
                    },
                )
    finally:
        await engine.dispose()


async def _queued(url: str) -> list[dict[str, object]]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT event_data FROM outbox_events"
                    " WHERE event_type = 'journal_event.recurrence_tidy'"
                )
            )
            events = [
                row.event_data
                if isinstance(row.event_data, dict)
                else json.loads(row.event_data)
                for row in rows
            ]
            return sorted(events, key=lambda event: str(event["recurring_event_id"]))
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.slow
class TestQueueRecurrenceTidyMigration:
    async def test_one_tidy_per_recurrence_with_upcoming_cancellations(
        self,
        throwaway_database: URL,
        run_alembic: Callable[[str, str, str], None],
    ) -> None:
        url = throwaway_database.render_as_string(hide_password=False)
        run_alembic(url, "upgrade", _PREVIOUS_REVISION)
        week = timedelta(days=7)
        await _seed(
            url,
            [
                # A truncated recurrence: three upcoming cancellations.
                (1, "pilates", "cancelled", week),
                (2, "pilates", "cancelled", 2 * week),
                (3, "pilates", "cancelled", 3 * week),
                # Cancelled, but every occurrence is already over.
                (4, "old-course", "cancelled", -week),
                # Live and upcoming: nothing to tidy.
                (5, "standup", "synced", week),
                # A legacy link without a recurring id: not plannable.
                (6, None, "cancelled", week),
            ],
        )

        run_alembic(url, "upgrade", _REVISION)

        queued = await _queued(url)
        assert [
            (event["calendar_id"], event["recurring_event_id"]) for event in queued
        ] == [(str(CALENDAR_ID), "pilates")]
        assert queued[0]["integration_source"] == "google"
