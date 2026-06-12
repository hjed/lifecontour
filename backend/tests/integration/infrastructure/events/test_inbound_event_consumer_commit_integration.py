"""Real-commit integration tests for InboundEventConsumer.

Unlike ``test_inbound_event_consumer_integration.py`` — which injects the shared
``async_connection`` (savepoint-isolated, ``EXTERNAL_TRANSACTION_MARKER``) and
mocks the domain processor — these tests exercise the *real* connection
lifecycle: the consumer opens and CLOSES its own connection, and we verify
persisted state on a SEPARATE fresh connection (the same pattern as
``test_connection_provider.py``).

This is the only place the production commit semantics of ``_handle_event`` are
covered. The regression they lock in (issue: v0.19.5 duplicates): when
``create_journal`` became ``@transactional`` it commits as the outermost unit of
work; under the consumer's old ``engine.begin()`` block it committed *early*,
orphaning every write made after it in ``_process_journal_created`` — the
``journal_external_event_links`` row and the ``journal_review.detect_matches``
outbox event — so those were rolled back when the connection closed. That caused
duplicate journals on the next sync (the link lookup missed) and stopped
auto-dedupe (the detect-matches event never persisted).
"""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from core_shared.stream_client import StreamEvent
from sqlalchemy import text

from app.infrastructure.config import Settings
from app.infrastructure.di.database import DatabaseProvider
from app.infrastructure.events.inbound_event_consumer import InboundEventConsumer


def _make_consumer() -> InboundEventConsumer:
    """Build a consumer whose only live dependencies are settings + engine.

    ``_handle_event`` uses ``self._settings`` and ``get_async_database_engine``;
    the stream client and DI container are not touched on this path, so mocks
    suffice. ``gemini_api_key`` is set so the match-detection (auto-dedupe)
    outbox event is emitted.
    """
    consumer_settings = MagicMock(spec=Settings)
    consumer_settings.gemini_api_key = "test-dummy-gemini-key"
    consumer_settings.gemini_model = "gemini-2.5-flash"
    return InboundEventConsumer(
        stream_client=MagicMock(),
        container=MagicMock(),
        settings=consumer_settings,
        stream_name="pms:domain-events",
        consumer_name="test-inbound-commit",
        block_ms=100,
    )


def _journal_created_event(
    *, calendar_id: str, external_event_id: str, user_id: str, title: str
) -> StreamEvent:
    """Build a complete ``journal_event.created`` StreamEvent.

    The payload must satisfy ``JournalSyncEventData.model_validate`` and include
    an event date range so the match-detection (auto-dedupe) outbox event is
    emitted.
    """
    return StreamEvent(
        message_id="0-0",
        event_id=f"evt-{uuid4().hex[:8]}",
        event_type="journal_event.created",
        aggregate_id=0,
        event_data={
            "integration_source": "google",
            "external_event_id": external_event_id,
            "calendar_id": calendar_id,
            "journal_data": {
                "user_id": user_id,
                "title": title,
                "content": "",
                "event_date_range_start": "2026-06-12T10:00:00+00:00",
                "event_date_range_end": "2026-06-12T11:00:00+00:00",
            },
            "calendar_info_data": {
                "calendar_id": calendar_id,
                "is_all_day": False,
                "location": None,
                "start_time": "10:00:00",
                "end_time": "11:00:00",
                "event_state": "confirmed",
            },
            "sync_timestamp": "2026-06-12T10:00:00Z",
            "sync_action": "created",
            "etag": "etag-1",
            "contact_relationships": [],
        },
        occurred_at="2026-06-12T10:00:00Z",
    )


async def _cleanup(engine, *, user_id: str, calendar_id: str) -> None:
    """Remove rows committed by a test (no rollback fixture on this path).

    Deleting the journal cascades to every journal-child row (external-event
    link, calendar info, type/fitness data, ...) — they all FK to ``journals.id``
    ``ON DELETE CASCADE`` — so this stays correct as new write paths are added to
    the processor. ``outbox_events`` has no FK to journals, so it is cleared
    first (by the journal ids) while the journals still exist. The per-test
    ``user_id``/``calendar_id`` are unique (uuid4), so any residual row cannot
    collide with another test even if a delete is missed.
    """
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "DELETE FROM outbox_events WHERE aggregate_id IN "
                "(SELECT id FROM journals WHERE user_id = :user_id)"
            ),
            {"user_id": user_id},
        )
        await conn.execute(
            text("DELETE FROM journals WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        await conn.execute(
            text("DELETE FROM calendars WHERE id = :cid"), {"cid": calendar_id}
        )


@pytest.mark.asyncio
async def test_journal_created_persists_link_and_match_event(
    test_settings, monkeypatch
) -> None:
    """A journal_event.created must commit ALL of its writes atomically.

    The journal, its external-event link, and the detect-matches outbox event
    must all survive the consumer connection closing. Before the fix the link
    and the outbox event were orphaned in a transaction discarded on close.
    """
    provider = DatabaseProvider(test_settings)
    engine = provider.get_engine()
    user_id = f"commit-test-{uuid4().hex}"
    calendar_id = str(uuid4())
    external_event_id = f"ext-{uuid4().hex[:8]}"

    monkeypatch.setattr(
        "app.infrastructure.events.inbound_event_consumer.get_async_database_engine",
        lambda: engine,
    )

    try:
        consumer = _make_consumer()
        await consumer._handle_event(
            _journal_created_event(
                calendar_id=calendar_id,
                external_event_id=external_event_id,
                user_id=user_id,
                title="Synced Event",
            )
        )

        # Verify on a SEPARATE fresh connection — the consumer's connection has
        # already closed, so only committed rows are visible here.
        async with engine.connect() as check:
            journal_count = (
                await check.execute(
                    text("SELECT count(*) FROM journals WHERE user_id = :u"),
                    {"u": user_id},
                )
            ).scalar()
            link_count = (
                await check.execute(
                    text(
                        "SELECT count(*) FROM journal_external_event_links "
                        "WHERE calendar_id = :cid AND external_event_id = :eid"
                    ),
                    {"cid": calendar_id, "eid": external_event_id},
                )
            ).scalar()
            match_event_count = (
                await check.execute(
                    text(
                        "SELECT count(*) FROM outbox_events "
                        "WHERE event_type = 'journal_review.detect_matches' "
                        "AND aggregate_id IN "
                        "(SELECT id FROM journals WHERE user_id = :u)"
                    ),
                    {"u": user_id},
                )
            ).scalar()

        assert journal_count == 1, "journal must be persisted"
        assert link_count == 1, (
            "external-event link must be committed atomically with the journal "
            "(orphaned link causes duplicate journals on the next sync)"
        )
        assert match_event_count == 1, (
            "detect-matches outbox event must be committed atomically with the "
            "journal (orphaned event disables auto-dedupe)"
        )
    finally:
        await _cleanup(engine, user_id=user_id, calendar_id=calendar_id)
        await engine.dispose()


@pytest.mark.asyncio
async def test_journal_created_twice_is_idempotent(test_settings, monkeypatch) -> None:
    """Re-processing the same external event must not create a duplicate journal.

    The second create finds the committed external-event link and routes to an
    update. Before the fix the link was never persisted, so the second run took
    the create path again and produced a duplicate journal.
    """
    provider = DatabaseProvider(test_settings)
    engine = provider.get_engine()
    user_id = f"commit-test-{uuid4().hex}"
    calendar_id = str(uuid4())
    external_event_id = f"ext-{uuid4().hex[:8]}"

    monkeypatch.setattr(
        "app.infrastructure.events.inbound_event_consumer.get_async_database_engine",
        lambda: engine,
    )

    try:
        consumer = _make_consumer()
        for _ in range(2):
            await consumer._handle_event(
                _journal_created_event(
                    calendar_id=calendar_id,
                    external_event_id=external_event_id,
                    user_id=user_id,
                    title="Synced Event",
                )
            )

        async with engine.connect() as check:
            journal_count = (
                await check.execute(
                    text("SELECT count(*) FROM journals WHERE user_id = :u"),
                    {"u": user_id},
                )
            ).scalar()

        assert journal_count == 1, (
            "syncing the same external event twice must not duplicate the journal"
        )
    finally:
        await _cleanup(engine, user_id=user_id, calendar_id=calendar_id)
        await engine.dispose()
