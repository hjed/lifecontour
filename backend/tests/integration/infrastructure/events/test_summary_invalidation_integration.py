"""End-to-end backend integration test for input-driven summary invalidation.

Exercises the whole async chain a real journal write travels:

    JournalService.update_journal()
        -> OutboxEventPublisher (outbox_events row, same txn)
        -> OutboxRelay.relay_batch()        (-> pms:domain-events stream)
        -> SummaryInvalidationConsumer      (-> journal_daily_summaries PENDING)

and asserts two things at once, because ITER18-005 Phase 7 is as much about what
does *not* happen: the right days are marked stale, and **no summary is
generated** doing it. The regeneration happens on the next read, which is the
phase's laziness requirement and the reason a user acting on the dashboard never
has prose change underneath them.

The three journal defects ITER18-004 Phase 4f recorded against the handler this
replaces are each asserted here against real rows, since each was invisible to
the unit tests of the code that had them.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from core_shared.models.contacts.entities import SummaryStatus
from core_shared.models.history import Provenance
from core_shared.models.journals import (
    EventDateRange,
    Journal,
    JournalContactRelationship,
    JournalContactRelationshipType,
    JournalType,
)
from core_shared.models.journals.daily_summary import JournalDailySummary
from core_shared.stream_client import StreamClient
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_repository import SqlContactRepository
from app.core.journal.adapters.sql.daily_summary_repository import (
    SqlJournalDailySummaryRepository,
)
from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_contact_service import JournalContactService
from app.core.journal.services.journal_service import JournalService
from app.core.tasks.adapters.sql.task_anchor_repository import SqlTaskAnchorRepository
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.events.summary_invalidation_consumer import (
    SummaryInvalidationConsumer,
)
from tests.integration.contact_seeding import seed_contact
from tests.integration.infrastructure.events.consumer_harness import (
    BATCH_SIZE,
    patched_consumer_engine,
    relay_outbox,
)

USER_ID = "user-summary-invalidation"
GROUP_NAME = "summary-invalidation"
CONSUMER_MODULE = "app.infrastructure.events.summary_invalidation_consumer"

GENERATED_AT = datetime(2026, 4, 26, 7, 0, tzinfo=UTC)
THE_DAY = date(2026, 4, 27)


def _instant(day: int, hour: int = 9) -> datetime:
    return datetime(2026, 4, day, hour, 0, tzinfo=UTC)


def _journal(
    *, start: datetime | None = None, end: datetime | None = None, title: str = "A day"
) -> Journal:
    return Journal(
        id=None,
        user_id=USER_ID,
        title=title,
        content="something happened",
        event_date_range=EventDateRange(
            start=start or _instant(27), end=end or _instant(27, 10)
        ),
    )


@pytest.fixture
def journal_service(async_connection: AsyncConnection) -> JournalService:
    return JournalService(
        journal_repo=SqlJournalRepository(async_connection),
        event_publisher=OutboxEventPublisher(async_connection),
        task_anchor_repo=SqlTaskAnchorRepository(async_connection),
    )


@pytest.fixture
def summary_repo(async_connection: AsyncConnection) -> SqlJournalDailySummaryRepository:
    return SqlJournalDailySummaryRepository(async_connection)


async def _seed_generated_summary(
    repo: SqlJournalDailySummaryRepository, day: date
) -> None:
    """A day the user has already had a summary for.

    Invalidation only ever touches rows that exist, so a day with no summary
    proves nothing either way — every assertion below needs a row to move.
    """
    await repo.upsert(
        JournalDailySummary(
            user_id=USER_ID,
            summary_date=day,
            summary_text="The prose the user is looking at.",
            journal_count=2,
            status=SummaryStatus.GENERATED,
            generated_at=GENERATED_AT,
        )
    )


async def _relay_and_invalidate(
    stream_client: StreamClient,
    stream_name: str,
    async_connection: AsyncConnection,
    consumer_name: str = "test-invalidation",
) -> None:
    """Relay the outbox and run one batch of the invalidation consumer.

    The group is created at ``"0"`` here, unlike production's ``"$"``: the test
    publishes *before* the consumer exists, and a group starting at the latest
    id would begin after the very events it is meant to read. The production
    start id is asserted where it belongs, in the consumer's unit tests.
    """
    await relay_outbox(stream_client, stream_name, async_connection)

    consumer = SummaryInvalidationConsumer(
        stream_client=stream_client,
        stream_name=stream_name,
        consumer_name=consumer_name,
        block_ms=100,
        batch_size=BATCH_SIZE,
    )
    await stream_client.ensure_consumer_group(stream_name, GROUP_NAME)

    with patched_consumer_engine(CONSUMER_MODULE, async_connection):
        await consumer._process_batch()


async def _status_on(
    repo: SqlJournalDailySummaryRepository, day: date
) -> SummaryStatus | None:
    row = await repo.find_by_user_and_date(USER_ID, day)
    return row.status if row else None


@pytest.mark.integration
class TestAJournalChangeMarksItsDaysStale:
    """The days a journal is part of, and nothing else, and no generation."""

    @pytest.mark.asyncio
    async def test_a_write_marks_the_day_stale_without_regenerating_it(
        self,
        journal_service: JournalService,
        summary_repo: SqlJournalDailySummaryRepository,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        test_stream_name: str,
    ) -> None:
        """The heart of the phase: stale, and the old prose still standing.

        A ``PENDING`` row keeps its text and its ``generated_at``, so the
        dashboard can go on showing the previous summary while knowing it is
        stale — and nothing has cost an AI call.
        """
        await _seed_generated_summary(summary_repo, THE_DAY)

        await journal_service.create_journal(
            _journal(), async_connection, changed_by="ui", source=Provenance.UI
        )
        await _relay_and_invalidate(stream_client, test_stream_name, async_connection)

        row = await summary_repo.find_by_user_and_date(USER_ID, THE_DAY)
        assert row is not None
        assert row.status == SummaryStatus.PENDING
        assert row.summary_text == "The prose the user is looking at."
        assert row.generated_at == GENERATED_AT

    @pytest.mark.asyncio
    async def test_a_multi_day_journal_marks_every_day_it_covers(
        self,
        journal_service: JournalService,
        summary_repo: SqlJournalDailySummaryRepository,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        test_stream_name: str,
    ) -> None:
        """A trip is in three days' summaries because the day query overlaps.

        The handler this replaces mapped it to its start date alone, so the
        second and third days kept counters that included it.
        """
        for day in (date(2026, 4, 24), date(2026, 4, 25), date(2026, 4, 26)):
            await _seed_generated_summary(summary_repo, day)

        await journal_service.create_journal(
            _journal(start=_instant(24, 18), end=_instant(26, 8), title="A long trip"),
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
        )
        await _relay_and_invalidate(stream_client, test_stream_name, async_connection)

        for day in (date(2026, 4, 24), date(2026, 4, 25), date(2026, 4, 26)):
            assert await _status_on(summary_repo, day) == SummaryStatus.PENDING

    @pytest.mark.asyncio
    async def test_a_journal_moved_to_another_day_marks_both(
        self,
        journal_service: JournalService,
        summary_repo: SqlJournalDailySummaryRepository,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        test_stream_name: str,
    ) -> None:
        """Defect 1 of the four ITER18-004 Phase 4f recorded.

        The day the journal *left* is the one that goes on describing an event
        that is no longer on it, and it was invisible to the previous handler,
        which reloaded the row and read its new date.
        """
        was, now = date(2026, 4, 20), THE_DAY
        for day in (was, now):
            await _seed_generated_summary(summary_repo, day)

        created = await journal_service.create_journal(
            _journal(start=_instant(20), end=_instant(20, 10)),
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
        )
        # Drain the creation so only the move's own event is under test.
        await _relay_and_invalidate(
            stream_client, test_stream_name, async_connection, "drain-create"
        )
        await _seed_generated_summary(summary_repo, was)
        await _seed_generated_summary(summary_repo, now)

        created.event_date_range = EventDateRange(
            start=_instant(27), end=_instant(27, 10)
        )
        await journal_service.update_journal(
            created, async_connection, changed_by="ui", source=Provenance.UI
        )
        await _relay_and_invalidate(
            stream_client, test_stream_name, async_connection, "test-move"
        )

        assert await _status_on(summary_repo, was) == SummaryStatus.PENDING
        assert await _status_on(summary_repo, now) == SummaryStatus.PENDING

    @pytest.mark.asyncio
    async def test_a_deleted_journal_marks_the_day_it_was_on(
        self,
        journal_service: JournalService,
        summary_repo: SqlJournalDailySummaryRepository,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        test_stream_name: str,
    ) -> None:
        """Defect 2: this invalidated nothing at all before.

        The handler reloaded the journal to find its date and the row was gone,
        so it logged and returned; the day kept its pre-delete counters
        indefinitely. The days now travel on the event.
        """
        created = await journal_service.create_journal(
            _journal(), async_connection, changed_by="ui", source=Provenance.UI
        )
        await _relay_and_invalidate(
            stream_client, test_stream_name, async_connection, "drain-create"
        )
        await _seed_generated_summary(summary_repo, THE_DAY)

        assert created.id is not None
        await journal_service.delete_journal(
            created.id, async_connection, changed_by="ui", source=Provenance.UI
        )
        await _relay_and_invalidate(
            stream_client, test_stream_name, async_connection, "test-delete"
        )

        assert await _status_on(summary_repo, THE_DAY) == SummaryStatus.PENDING

    @pytest.mark.asyncio
    async def test_a_day_the_journal_never_touched_is_left_alone(
        self,
        journal_service: JournalService,
        summary_repo: SqlJournalDailySummaryRepository,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        test_stream_name: str,
    ) -> None:
        """Every invalidation costs a regeneration, so the bound is the point."""
        bystander = date(2026, 4, 15)
        await _seed_generated_summary(summary_repo, THE_DAY)
        await _seed_generated_summary(summary_repo, bystander)

        await journal_service.create_journal(
            _journal(), async_connection, changed_by="ui", source=Provenance.UI
        )
        await _relay_and_invalidate(stream_client, test_stream_name, async_connection)

        assert await _status_on(summary_repo, bystander) == SummaryStatus.GENERATED


@pytest.mark.integration
class TestTheOtherWaysADayChanges:
    """The events the previous handler's three-type set left out."""

    @pytest.mark.asyncio
    async def test_a_contact_added_to_a_journal_marks_the_day_stale(
        self,
        journal_service: JournalService,
        summary_repo: SqlJournalDailySummaryRepository,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        test_stream_name: str,
    ) -> None:
        """Defect 3: ``contact_count`` could be wrong with nothing to correct it.

        The relationship write publishes ``ContactSummaryRefreshRequested`` and
        nothing else, and the summary's contact names and count come from
        exactly those rows — so the journal now travels on that payload.
        """
        created = await journal_service.create_journal(
            _journal(), async_connection, changed_by="ui", source=Provenance.UI
        )
        await _relay_and_invalidate(
            stream_client, test_stream_name, async_connection, "drain-create"
        )
        await _seed_generated_summary(summary_repo, THE_DAY)

        contact_id = await seed_contact(
            async_connection,
            user_id=USER_ID,
            first_name="Ada",
            last_name=f"Lovelace-{uuid.uuid4().hex[:6]}",
        )

        assert created.id is not None
        contact_service = JournalContactService(
            contact_relationship_repo=SqlJournalContactRelationshipRepository(
                async_connection
            ),
            event_publisher=OutboxEventPublisher(async_connection),
            contact_repo=SqlContactRepository(async_connection),
        )
        await contact_service.add_contact_to_journal(
            JournalContactRelationship(
                journal_id=created.id,
                contact_id=contact_id,
                relationship_type=JournalContactRelationshipType.PARTICIPANT,
            ),
            user_id=USER_ID,
            transaction=async_connection,
        )
        await _relay_and_invalidate(
            stream_client, test_stream_name, async_connection, "test-contact"
        )

        assert await _status_on(summary_repo, THE_DAY) == SummaryStatus.PENDING

    @pytest.mark.asyncio
    async def test_a_type_added_to_a_journal_marks_the_day_stale(
        self,
        journal_service: JournalService,
        summary_repo: SqlJournalDailySummaryRepository,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        test_stream_name: str,
    ) -> None:
        """``event_count`` is derived from types, and EVENT *is* the agenda."""
        created = await journal_service.create_journal(
            _journal(), async_connection, changed_by="ui", source=Provenance.UI
        )
        await _relay_and_invalidate(
            stream_client, test_stream_name, async_connection, "drain-create"
        )
        await _seed_generated_summary(summary_repo, THE_DAY)

        assert created.id is not None
        await journal_service.add_type_to_journal(
            created.id,
            JournalType.NOTE,
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
        )
        await _relay_and_invalidate(
            stream_client, test_stream_name, async_connection, "test-type"
        )

        assert await _status_on(summary_repo, THE_DAY) == SummaryStatus.PENDING


@pytest.mark.integration
class TestNothingIsGeneratedByAnEvent:
    """The laziness, asserted where it is observable rather than argued."""

    @pytest.mark.asyncio
    async def test_four_writes_in_a_row_leave_one_stale_row_and_no_generations(
        self,
        journal_service: JournalService,
        summary_repo: SqlJournalDailySummaryRepository,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        test_stream_name: str,
    ) -> None:
        """Four changes to a day cost four ``UPDATE``\\ s and nothing else.

        The regeneration is paid once, by whoever next reads the day. This is
        the journal-shaped half of the phase's four-ticks criterion; the task
        half lands with the task events.
        """
        await _seed_generated_summary(summary_repo, THE_DAY)

        created = await journal_service.create_journal(
            _journal(), async_connection, changed_by="ui", source=Provenance.UI
        )
        for index in range(3):
            created.title = f"Retitled {index}"
            await journal_service.update_journal(
                created, async_connection, changed_by="ui", source=Provenance.UI
            )
        await _relay_and_invalidate(stream_client, test_stream_name, async_connection)

        row = await summary_repo.find_by_user_and_date(USER_ID, THE_DAY)
        assert row is not None
        assert row.status == SummaryStatus.PENDING
        # Untouched by any of the four: nothing generated, so nothing replaced
        # the prose or moved the timestamp.
        assert row.summary_text == "The prose the user is looking at."
        assert row.generated_at == GENERATED_AT

    @pytest.mark.asyncio
    async def test_a_future_day_the_user_has_no_summary_for_gains_none(
        self,
        journal_service: JournalService,
        summary_repo: SqlJournalDailySummaryRepository,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        test_stream_name: str,
    ) -> None:
        """Invalidation creates no rows, so it cannot manufacture a summary."""
        day_with_no_row = THE_DAY + timedelta(days=30)

        await journal_service.create_journal(
            _journal(
                start=datetime.combine(
                    day_with_no_row, datetime.min.time(), tzinfo=UTC
                ),
                end=datetime.combine(day_with_no_row, datetime.min.time(), tzinfo=UTC),
            ),
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
        )
        await _relay_and_invalidate(stream_client, test_stream_name, async_connection)

        assert (
            await summary_repo.find_by_user_and_date(USER_ID, day_with_no_row) is None
        )
