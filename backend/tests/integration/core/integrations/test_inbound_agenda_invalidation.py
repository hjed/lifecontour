"""The inbound sync paths that change a day's agenda without publishing.

ITER18-005 Phase 7 asks which of these paths announce an agenda change and
covers the ones that cannot. Two do not, and both are exercised here against
real rows, because what each writes is raw SQL that no unit test with a mocked
connection can prove landed:

- an **upstream cancellation**, which sets ``journal_calendar_info.event_state``
  and publishes nothing — and the agenda shows a cancelled event *marked as
  cancelled* rather than dropping it (**W18**), so the day's prose is wrong
  until the summary is regenerated;
- an inbound update where the journal's own fields did not move, so
  ``JournalService.update_journal`` is never called and no ``JournalUpdated``
  exists, though the calendar info and the attendees may have changed.

The cancellation case is seeded so it takes the branch that actually writes:
``_mark_journal_cancelled`` marks the *link* always but the journal only once no
calendar still holds the event, so a test with a second live link would pass
while asserting nothing.
"""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import pytest
from core_shared.models.contacts.entities import SummaryStatus
from core_shared.models.journals.daily_summary import JournalDailySummary
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.daily_summary_repository import (
    SqlJournalDailySummaryRepository,
)
from tests.integration.core.integrations.journal_sync_seeding import (
    USER_ID,
    build_processor,
    create_calendar,
    event_state,
    sync_event,
)

WHEN = datetime.now(UTC) + timedelta(days=3)


async def _seed_generated_summary(connection: AsyncConnection, day: date) -> None:
    await SqlJournalDailySummaryRepository(connection).upsert(
        JournalDailySummary(
            user_id=USER_ID,
            summary_date=day,
            summary_text="Physio at nine, as arranged.",
            status=SummaryStatus.GENERATED,
            generated_at=datetime.now(UTC) - timedelta(hours=2),
        )
    )


async def _status_on(connection: AsyncConnection, day: date) -> SummaryStatus | None:
    row = await SqlJournalDailySummaryRepository(connection).find_by_user_and_date(
        USER_ID, day
    )
    return row.status if row else None


async def _journal_day(connection: AsyncConnection, journal_id: int) -> date:
    """The journal's local day, read back from the row the sync wrote."""
    result = await connection.execute(
        text("SELECT event_date_range_start FROM journals WHERE id = :journal_id"),
        {"journal_id": journal_id},
    )
    starts_at: datetime = result.scalar_one()
    return starts_at.date()


@pytest.mark.integration
class TestAnUpstreamCancellation:
    """Cancelled in Google, and the day's summary still says it is happening."""

    @pytest.mark.asyncio
    async def test_the_day_is_marked_stale(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id="physio-1",
                start=WHEN,
            )
        )
        journal_id = created["journal_id"]
        day = await _journal_day(async_connection, journal_id)
        await _seed_generated_summary(async_connection, day)

        await processor.process_event(
            sync_event(
                "journal_event.cancelled",
                calendar_id=calendar_id,
                external_event_id="physio-1",
                existing_journal_id=journal_id,
                start=WHEN,
                etag='"etag-2"',
            )
        )

        # The branch that writes was actually taken, rather than the one that
        # leaves the journal alone because another calendar still holds it.
        assert await event_state(async_connection, journal_id) == "cancelled"
        assert await _status_on(async_connection, day) == SummaryStatus.PENDING


@pytest.mark.integration
class TestAnInboundUpdateThatChangesNoJournalField:
    """The same event again, with only the parts no domain event covers moving."""

    @pytest.mark.asyncio
    async def test_the_day_is_marked_stale(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id="physio-2",
                start=WHEN,
            )
        )
        journal_id = created["journal_id"]
        day = await _journal_day(async_connection, journal_id)
        await _seed_generated_summary(async_connection, day)

        # Same title, same content, same instants — so ``fields_changed`` is
        # false and no ``JournalUpdated`` is published — but a new etag, so the
        # idempotency guard lets it through as a real upstream change.
        await processor.process_event(
            sync_event(
                "journal_event.updated",
                calendar_id=calendar_id,
                external_event_id="physio-2",
                existing_journal_id=journal_id,
                start=WHEN,
                etag='"etag-moved"',
            )
        )

        assert await _status_on(async_connection, day) == SummaryStatus.PENDING

    @pytest.mark.asyncio
    async def test_a_day_with_no_summary_gains_none(
        self, async_connection: AsyncConnection
    ) -> None:
        """Invalidation creates no rows here either."""
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id="physio-3",
                start=WHEN,
            )
        )
        journal_id = created["journal_id"]
        day = await _journal_day(async_connection, journal_id)

        await processor.process_event(
            sync_event(
                "journal_event.updated",
                calendar_id=calendar_id,
                external_event_id="physio-3",
                existing_journal_id=journal_id,
                start=WHEN,
                etag='"etag-moved"',
            )
        )

        assert await _status_on(async_connection, day) is None


@pytest.mark.integration
class TestAFailedInvalidationDoesNotTakeTheSyncWithIt:
    """The helper is best-effort, and in PostgreSQL that needs a SAVEPOINT.

    A failed statement poisons its transaction, so catching the exception
    without rolling back to a savepoint would leave the enclosing unit of work
    aborted — and the inbound journal and calendar writes this helper exists to
    preserve would go down with it. Raised by review on the first cut, which
    caught the exception and returned.
    """

    @pytest.mark.asyncio
    async def test_the_journal_write_survives_a_broken_invalidation(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id="physio-4",
                start=WHEN,
            )
        )
        journal_id = created["journal_id"]
        day = await _journal_day(async_connection, journal_id)
        await _seed_generated_summary(async_connection, day)

        # A statement that fails the way a real one would — against the database,
        # inside the helper — rather than an exception raised in Python, which
        # would not poison anything and so would not test the fix.
        async def explode(*_args: object, **_kwargs: object) -> None:
            await async_connection.execute(text("SELECT no_such_column"))

        with patch(
            "app.core.journal.services.daily_summary_invalidation_service"
            ".invalidate_days_of_journal",
            side_effect=explode,
        ):
            await processor.process_event(
                sync_event(
                    "journal_event.updated",
                    calendar_id=calendar_id,
                    external_event_id="physio-4",
                    existing_journal_id=journal_id,
                    start=WHEN,
                    etag='"etag-moved"',
                )
            )

        # The transaction is still usable and the journal is still there, which
        # is the whole point: a stale summary is a worse day's prose, a failed
        # sync is a lost journal.
        assert await _journal_day(async_connection, journal_id) == day
        assert await _status_on(async_connection, day) == SummaryStatus.GENERATED
