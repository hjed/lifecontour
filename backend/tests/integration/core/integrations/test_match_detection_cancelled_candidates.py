"""Integration tests for which same-day journals match detection compares.

A cancelled calendar event is not a duplicate of anything: it is what is left
of an occurrence that is no longer on. Offering it as a match candidate is
how a split recurrence's new occurrences each raised a review item against
the old, cancelled one.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from core_shared.models.outbox import OutboxEvent
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.match_detection_event_processor import (
    MatchDetectionEventProcessor,
)
from app.core.journal.adapters.sql.review_item_repository import (
    SqlReviewItemRepository,
)
from app.core.journal.services.match_candidate_detector import CandidateJournalData
from tests.integration.core.integrations.journal_sync_seeding import (
    USER_ID,
    build_processor,
    create_calendar,
    sync_event,
)


class _RecordingDetector:
    """Records the candidates it was offered and matches none of them."""

    def __init__(self) -> None:
        self.offered: list[int] = []

    async def detect_candidates(
        self, *, existing_journals: list[CandidateJournalData], **_: Any
    ) -> list[Any]:
        self.offered = [j.id for j in existing_journals]
        return []


def _detect_matches_event(journal_id: int, start: datetime) -> OutboxEvent:
    return OutboxEvent(
        id=uuid.uuid4(),
        event_type="journal_review.detect_matches",
        aggregate_id=str(journal_id),
        event_data={
            "journal_id": journal_id,
            "user_id": USER_ID,
            "journal_title": "Pilates",
            "journal_content": "",
            "event_date_range_start": start.isoformat(),
            "event_date_range_end": (start + timedelta(hours=1)).isoformat(),
            "created_at": datetime.now(UTC).isoformat(),
        },
        occurred_at=datetime.now(UTC),
        retry_count=0,
    )


@pytest.mark.integration
class TestCancelledEventsAreNotCandidates:
    async def test_only_live_and_non_event_journals_are_offered(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        start = datetime.now(UTC).replace(hour=1, minute=10) + timedelta(days=4)

        cancelled = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id="old-instance",
                title="Pilates",
                start=start,
            )
        )
        await processor.process_event(
            sync_event(
                "journal_event.cancelled",
                calendar_id=calendar_id,
                external_event_id="old-instance",
                existing_journal_id=cancelled["journal_id"],
            )
        )
        live = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id="other-event",
                title="Pilates",
                start=start + timedelta(minutes=5),
            )
        )
        note_id: int = (
            await async_connection.execute(
                text("""
                    INSERT INTO journals
                        (user_id, title, content,
                         event_date_range_start, event_date_range_end)
                    VALUES (:user_id, 'Pilates notes', '', :start, :start)
                    RETURNING id
                """),
                {"user_id": USER_ID, "start": start + timedelta(minutes=30)},
            )
        ).scalar_one()
        incoming = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id="new-instance",
                title="Pilates",
                start=start + timedelta(minutes=10),
            )
        )
        detector = _RecordingDetector()
        match_processor = MatchDetectionEventProcessor(
            connection=async_connection,
            match_candidate_detector=detector,  # type: ignore[arg-type]
            review_item_repository=SqlReviewItemRepository(async_connection),
        )

        await match_processor.process_event(
            _detect_matches_event(incoming["journal_id"], start)
        )

        assert sorted(detector.offered) == sorted([live["journal_id"], note_id])
