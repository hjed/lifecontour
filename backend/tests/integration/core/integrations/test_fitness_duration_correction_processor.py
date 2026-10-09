"""The processor applying the Strava backfill's duration corrections.

Strava journals were synced with moving time as their duration; the worker's
backfill sends ``journal_event.fitness_duration_corrected`` with the durations
the sync could have written and the elapsed time to store instead. The
processor must apply it only while the stored duration is still one of those
values — anything else is a user's edit and is left alone.
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from core_shared.models.contacts.entities import SummaryStatus
from core_shared.models.journals import EventDateRange, FitnessData, Journal
from core_shared.models.journals.daily_summary import JournalDailySummary
from core_shared.models.outbox import OutboxEvent
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.daily_summary_repository import (
    SqlJournalDailySummaryRepository,
)
from app.core.journal.adapters.sql.fitness_data_repository import (
    SqlFitnessDataRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from tests.integration.core.integrations.journal_sync_seeding import build_processor

USER_ID = "duration-backfill-user"
# Noon UTC keeps the journal's day the same whatever zone resolves it.
STARTS_AT = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)


async def _seed_strava_journal(
    connection: AsyncConnection, *, duration: int | None, user_id: str = USER_ID
) -> int:
    journal = await SqlJournalRepository(connection).save(
        Journal(
            user_id=user_id,
            title="Morning Ride",
            content="",
            event_date_range=EventDateRange(
                start=STARTS_AT, end=STARTS_AT + timedelta(hours=1)
            ),
        )
    )
    assert journal.id is not None
    await SqlFitnessDataRepository(connection).save(
        FitnessData(
            journal_id=journal.id,
            distance=20000,
            duration=duration,
            strava_activity_id="111",
        )
    )
    return journal.id


async def _duration(connection: AsyncConnection, journal_id: int) -> int | None:
    fitness = await SqlFitnessDataRepository(connection).find_by_journal_id(journal_id)
    assert fitness is not None
    return fitness.duration


def _correction(
    journal_id: int,
    *,
    expected: list[int],
    corrected: int,
    user_id: str = USER_ID,
    activity_ids: list[str] | None = None,
) -> OutboxEvent:
    return OutboxEvent.create_fitness_duration_correction_event(
        journal_id=journal_id,
        user_id=user_id,
        expected_durations=expected,
        corrected_duration=corrected,
        strava_activity_ids=activity_ids or ["111"],
    )


async def _seed_generated_summary(connection: AsyncConnection, day: date) -> None:
    await SqlJournalDailySummaryRepository(connection).upsert(
        JournalDailySummary(
            user_id=USER_ID,
            summary_date=day,
            summary_text="A long ride.",
            status=SummaryStatus.GENERATED,
            generated_at=datetime.now(UTC) - timedelta(hours=2),
        )
    )


async def _summary_status(
    connection: AsyncConnection, day: date
) -> SummaryStatus | None:
    row = await SqlJournalDailySummaryRepository(connection).find_by_user_and_date(
        USER_ID, day
    )
    return row.status if row else None


@pytest.mark.integration
class TestFitnessDurationCorrection:
    @pytest.mark.asyncio
    async def test_a_synced_moving_time_is_corrected(
        self, async_connection: AsyncConnection
    ) -> None:
        journal_id = await _seed_strava_journal(async_connection, duration=3000)

        result = await build_processor(async_connection).process_event(
            _correction(journal_id, expected=[3000], corrected=3600)
        )

        assert result["status"] == "corrected"
        assert await _duration(async_connection, journal_id) == 3600

    @pytest.mark.asyncio
    async def test_a_merged_journals_summed_duration_is_corrected(
        self, async_connection: AsyncConnection
    ) -> None:
        """Two activities merged: moving 3000 + 1200, elapsed 3600 + 1500."""
        journal_id = await _seed_strava_journal(async_connection, duration=4200)

        await build_processor(async_connection).process_event(
            _correction(
                journal_id,
                expected=[4200, 4500, 4800],
                corrected=5100,
                activity_ids=["111", "222"],
            )
        )

        assert await _duration(async_connection, journal_id) == 5100

    @pytest.mark.asyncio
    async def test_an_edited_duration_is_left_alone(
        self, async_connection: AsyncConnection
    ) -> None:
        journal_id = await _seed_strava_journal(async_connection, duration=5400)

        result = await build_processor(async_connection).process_event(
            _correction(journal_id, expected=[3000], corrected=3600)
        )

        assert result["status"] == "skipped"
        assert result["reason"] == "no_matching_duration"
        assert await _duration(async_connection, journal_id) == 5400

    @pytest.mark.asyncio
    async def test_another_users_journal_is_left_alone(
        self, async_connection: AsyncConnection
    ) -> None:
        journal_id = await _seed_strava_journal(
            async_connection, duration=3000, user_id="someone-else"
        )

        result = await build_processor(async_connection).process_event(
            _correction(journal_id, expected=[3000], corrected=3600)
        )

        assert result["status"] == "skipped"
        assert await _duration(async_connection, journal_id) == 3000

    @pytest.mark.asyncio
    async def test_a_correction_marks_the_days_summary_stale(
        self, async_connection: AsyncConnection
    ) -> None:
        journal_id = await _seed_strava_journal(async_connection, duration=3000)
        await _seed_generated_summary(async_connection, STARTS_AT.date())

        await build_processor(async_connection).process_event(
            _correction(journal_id, expected=[3000], corrected=3600)
        )

        assert (
            await _summary_status(async_connection, STARTS_AT.date())
            == SummaryStatus.PENDING
        )

    @pytest.mark.asyncio
    async def test_a_skipped_correction_leaves_the_summary_alone(
        self, async_connection: AsyncConnection
    ) -> None:
        journal_id = await _seed_strava_journal(async_connection, duration=5400)
        await _seed_generated_summary(async_connection, STARTS_AT.date())

        await build_processor(async_connection).process_event(
            _correction(journal_id, expected=[3000], corrected=3600)
        )

        assert (
            await _summary_status(async_connection, STARTS_AT.date())
            == SummaryStatus.GENERATED
        )
