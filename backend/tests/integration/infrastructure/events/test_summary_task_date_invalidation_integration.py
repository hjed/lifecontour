"""Task and important-date changes marking a daily summary stale, end to end.

The other half of ITER18-005 Phase 7's inputs, driven the way a real write
drives them:

    TaskService.update_task()
        -> OutboxEventPublisher (outbox_events row, same txn)
        -> OutboxRelay.relay_batch()        (-> pms:domain-events stream)
        -> SummaryInvalidationConsumer      (-> journal_daily_summaries PENDING)

Two of the phase's criteria are only assertable here, against real rows and a
real generator: **four ticks in a row cost one regeneration**, and a retarget
invalidates *both* the day that lost the task and the day that gained it.
"""

import json
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.models.contacts.entities import SummaryStatus
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)
from core_shared.models.journals.daily_summary import JournalDailySummary
from core_shared.models.tasks import Task, TaskStatus
from core_shared.stream_client import StreamClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.daily_summary_repository import (
    SqlJournalDailySummaryRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.daily_summary_models import DailySummaryInput
from app.core.journal.services.daily_summary_service import DailySummaryService
from app.core.journal.services.journal_date_resolver import today_in
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.settings.timezone_utils import resolve_timezone
from app.core.tasks.services.task_service import TaskService
from app.infrastructure.events.summary_invalidation_consumer import (
    SummaryInvalidationConsumer,
)
from tests.integration.infrastructure.events.consumer_harness import (
    BATCH_SIZE,
    patched_consumer_engine,
    relay_outbox,
)
from tests.integration.tasks.task_seeding import create_journal, service_on

USER_ID = "user-task-invalidation"
GROUP_NAME = "summary-invalidation"
CONSUMER_MODULE = "app.infrastructure.events.summary_invalidation_consumer"

GENERATED_AT = datetime(2026, 4, 26, 7, 0, tzinfo=UTC)


def _today() -> date:
    """The user's today, resolved the way every read in this phase resolves it.

    Anchored on the real clock rather than a fixed date because the *window* is
    what these tests exercise, and a task due "in three days" has to be three
    days from whatever today actually is when the suite runs.
    """
    return today_in(resolve_timezone(None))


@pytest.fixture
def summary_repo(async_connection: AsyncConnection) -> SqlJournalDailySummaryRepository:
    return SqlJournalDailySummaryRepository(async_connection)


@pytest.fixture
def journal_repository(async_connection: AsyncConnection) -> SqlJournalRepository:
    return SqlJournalRepository(async_connection)


@pytest.fixture
def task_service(async_connection: AsyncConnection) -> TaskService:
    return service_on(async_connection, SqlUserSettingsRepository(async_connection))


@pytest.fixture
def generation_counter() -> AsyncMock:
    """An input assembler that counts how often a summary was generated.

    It is awaited once per generation and never otherwise, so its call count is
    the number of AI calls the scenario paid for — which is the quantity the
    phase's laziness criterion is about.
    """
    assembler = AsyncMock()
    assembler.assemble.return_value = DailySummaryInput(
        user_id=USER_ID,
        summary_date=_today(),
        journals=[],
        journal_count=2,
        event_count=1,
        contact_names=["Alice"],
        mood_values=[7, 8],
    )
    return assembler


@pytest.fixture
def summary_service(
    async_connection: AsyncConnection, generation_counter: AsyncMock
) -> DailySummaryService:
    eligibility = MagicMock()
    eligibility.is_eligible.return_value = True
    prompt_builder = MagicMock()
    prompt_builder.build.return_value = "prompt"
    return DailySummaryService(
        input_assembler=generation_counter,
        eligibility_checker=eligibility,
        prompt_builder=prompt_builder,
        summary_repo=SqlJournalDailySummaryRepository(async_connection),
        gemini_api_key="test-key",
        gemini_model="gemini-2.5-pro",
        _gemini_response_override=json.dumps({"summary_text": "A productive day."}),
    )


def _created_id(task: Task) -> int:
    """The id a freshly created task must have.

    ``Task.id`` is optional on the model because an unsaved task has none;
    everything the service returns has been persisted, so the assertion is a
    statement about this test's setup rather than a defensive check.
    """
    assert task.id is not None
    return task.id


async def _seed_generated_summary(
    repo: SqlJournalDailySummaryRepository, day: date
) -> None:
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
    consumer_name: str = "test-task-invalidation",
) -> None:
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
class TestTickingTasksOff:
    """The phase's laziness criterion, counted rather than argued."""

    @pytest.mark.asyncio
    async def test_four_ticks_in_a_row_cost_one_regeneration(
        self,
        task_service: TaskService,
        journal_repository: SqlJournalRepository,
        summary_repo: SqlJournalDailySummaryRepository,
        summary_service: DailySummaryService,
        generation_counter: AsyncMock,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        test_stream_name: str,
    ) -> None:
        """Four status changes, one `PENDING` row, one generation on the read.

        Not four. The invalidation writes a marker and stops; the cost is paid
        once, by whoever next opens the day.
        """
        today = _today()
        await _seed_generated_summary(summary_repo, today)

        due_journal_id = await create_journal(
            journal_repository, days_offset=3, user_id=USER_ID
        )
        creating_journal_id = await create_journal(
            journal_repository, days_offset=0, user_id=USER_ID
        )
        task_ids = [
            _created_id(
                await task_service.create_task(
                    user_id=USER_ID,
                    creating_journal_id=creating_journal_id,
                    due_journal_id=due_journal_id,
                    text=f"commitment {index}",
                    transaction=async_connection,
                )
            )
            for index in range(4)
        ]
        for task_id in task_ids:
            await task_service.update_task(
                user_id=USER_ID,
                task_id=task_id,
                transaction=async_connection,
                status=TaskStatus.DONE,
            )

        await _relay_and_invalidate(stream_client, test_stream_name, async_connection)

        assert await _status_on(summary_repo, today) == SummaryStatus.PENDING
        generation_counter.assemble.assert_not_awaited()

        result = await summary_service.get_or_generate(USER_ID, today, async_connection)

        assert result is not None
        assert result.status == SummaryStatus.GENERATED
        assert generation_counter.assemble.await_count == 1

    @pytest.mark.asyncio
    async def test_an_explicit_regeneration_still_forces_one(
        self,
        summary_repo: SqlJournalDailySummaryRepository,
        summary_service: DailySummaryService,
        generation_counter: AsyncMock,
        async_connection: AsyncConnection,
    ) -> None:
        """The laziness is for *input* changes; a user asking still gets one.

        Nothing has been invalidated here — the row is `GENERATED` and fresh —
        and the regeneration happens anyway, which is what makes the Regenerate
        control mean something.
        """
        today = _today()
        await _seed_generated_summary(summary_repo, today)

        result = await summary_service.regenerate(USER_ID, today, async_connection)

        assert result is not None
        assert result.summary_text == "A productive day."
        assert generation_counter.assemble.await_count == 1


@pytest.mark.integration
class TestRetargetingATask:
    """The criterion in its own words: both the day that lost it and the one that gained it."""

    @pytest.mark.asyncio
    async def test_the_day_that_lost_it_and_the_day_that_gained_it(
        self,
        task_service: TaskService,
        journal_repository: SqlJournalRepository,
        summary_repo: SqlJournalDailySummaryRepository,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        test_stream_name: str,
    ) -> None:
        """Both are the same day here — today — and that is not a weaker test.

        A task can only be retargeted to a *future* journal, and today's prompt
        is where the whole week ahead is rendered, so both journals resolve to
        today's summary. What the test pins is that the retarget is answered at
        all: before this phase a task moving between two future days changed the
        week's list with nothing marking it stale.
        """
        today = _today()
        await _seed_generated_summary(summary_repo, today)

        creating_journal_id = await create_journal(
            journal_repository, days_offset=0, user_id=USER_ID
        )
        first_due = await create_journal(
            journal_repository, days_offset=2, user_id=USER_ID
        )
        second_due = await create_journal(
            journal_repository, days_offset=5, user_id=USER_ID
        )
        task = await task_service.create_task(
            user_id=USER_ID,
            creating_journal_id=creating_journal_id,
            due_journal_id=first_due,
            text="book the venue",
            transaction=async_connection,
        )
        await _relay_and_invalidate(
            stream_client, test_stream_name, async_connection, "drain-create"
        )
        await _seed_generated_summary(summary_repo, today)

        await task_service.retarget_due_journal(
            user_id=USER_ID,
            task_id=_created_id(task),
            due_journal_id=second_due,
            transaction=async_connection,
        )
        await _relay_and_invalidate(
            stream_client, test_stream_name, async_connection, "test-retarget"
        )

        assert await _status_on(summary_repo, today) == SummaryStatus.PENDING

    @pytest.mark.asyncio
    async def test_a_task_due_beyond_the_week_leaves_today_alone(
        self,
        task_service: TaskService,
        journal_repository: SqlJournalRepository,
        summary_repo: SqlJournalDailySummaryRepository,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        test_stream_name: str,
    ) -> None:
        """No prompt names it, so a regeneration would produce the same prose."""
        today = _today()
        await _seed_generated_summary(summary_repo, today)

        creating_journal_id = await create_journal(
            journal_repository, days_offset=0, user_id=USER_ID
        )
        far_off = await create_journal(
            journal_repository, days_offset=30, user_id=USER_ID
        )
        await task_service.create_task(
            user_id=USER_ID,
            creating_journal_id=creating_journal_id,
            due_journal_id=far_off,
            text="renew the passport",
            transaction=async_connection,
        )
        await _relay_and_invalidate(stream_client, test_stream_name, async_connection)

        assert await _status_on(summary_repo, today) == SummaryStatus.GENERATED


@pytest.mark.integration
class TestAnImportantDateChanging:
    """The current day, and no other."""

    async def _seed_contact_with_date(
        self, async_connection: AsyncConnection, *, days_ahead: int
    ) -> tuple[int, int]:
        occurrence = _today() + timedelta(days=days_ahead)
        contact_id = (
            await async_connection.execute(
                text(
                    "INSERT INTO contacts (first_name, last_name) "
                    "VALUES ('Ada', 'Lovelace') RETURNING id"
                )
            )
        ).scalar_one()
        date_id = (
            await async_connection.execute(
                text(
                    "INSERT INTO contact_important_dates "
                    "(contact_id, date_type, precision, year, month, day) "
                    "VALUES (:contact_id, :date_type, :precision, :year, "
                    ":month, :day) RETURNING id"
                ),
                {
                    "contact_id": contact_id,
                    "date_type": ImportantDateType.BIRTHDAY.value,
                    "precision": DatePrecision.FULL.value,
                    "year": 1990,
                    "month": occurrence.month,
                    "day": occurrence.day,
                },
            )
        ).scalar_one()
        return int(contact_id), int(date_id)

    async def _publish(
        self,
        async_connection: AsyncConnection,
        *,
        contact_id: int,
        date_id: int,
    ) -> None:
        """Publish the event the app's own save path publishes for a date."""
        from app.core.contacts.models.events import ImportantDateAdded
        from app.infrastructure.events.outbox_event_publisher import (
            OutboxEventPublisher,
        )

        await OutboxEventPublisher(async_connection).publish(
            ImportantDateAdded(
                contact_id,
                date_id,
                ImportantDateType.BIRTHDAY.value,
                transaction=async_connection,
            )
        )

    @pytest.mark.asyncio
    async def test_a_date_in_the_week_marks_today_and_no_past_day(
        self,
        summary_repo: SqlJournalDailySummaryRepository,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        test_stream_name: str,
    ) -> None:
        """Upcoming dates are current-day material; a past day never showed them."""
        today = _today()
        yesterday = today - timedelta(days=1)
        await _seed_generated_summary(summary_repo, today)
        await _seed_generated_summary(summary_repo, yesterday)

        contact_id, date_id = await self._seed_contact_with_date(
            async_connection, days_ahead=2
        )
        await self._publish(async_connection, contact_id=contact_id, date_id=date_id)
        await _relay_and_invalidate(stream_client, test_stream_name, async_connection)

        assert await _status_on(summary_repo, today) == SummaryStatus.PENDING
        assert await _status_on(summary_repo, yesterday) == SummaryStatus.GENERATED

    @pytest.mark.asyncio
    async def test_a_date_outside_the_week_marks_nothing(
        self,
        summary_repo: SqlJournalDailySummaryRepository,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        test_stream_name: str,
    ) -> None:
        """Saving a contact re-adds every date, so this is the common case.

        Without the window test, editing a phone number would cost an AI call
        for a birthday six months away.
        """
        today = _today()
        await _seed_generated_summary(summary_repo, today)

        contact_id, date_id = await self._seed_contact_with_date(
            async_connection, days_ahead=90
        )
        await self._publish(async_connection, contact_id=contact_id, date_id=date_id)
        await _relay_and_invalidate(stream_client, test_stream_name, async_connection)

        assert await _status_on(summary_repo, today) == SummaryStatus.GENERATED
