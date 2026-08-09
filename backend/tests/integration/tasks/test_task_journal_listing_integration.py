"""Integration tests for reading a journal's tasks against PostgreSQL.

The unit suite proves the grouping rule and the service's call counts against
doubles. This proves the same claims against real rows, where three things can
be wrong that a double cannot show.

**The link tables carry no ``user_id``.** Owner scoping on the batched reads
lives entirely in a join back to ``tasks``, so a double that simply returned
what it was given would keep passing while the SQL leaked another user's links.

**Cancellation is a row in a third table.** ``journal_calendar_info`` is what
makes a journal an event and what says it was called off, and the lapse rule
reads it in batch. Only a real row proves the batch lookup and the derivation
still meet.

**Statement counts are the acceptance criterion.** "One query per collection,
not per task" cannot be observed from the answer, which is right either way. The
recorder listens to what actually reached the driver, at two fixture sizes, so a
per-task loop fails whatever number it happens to run to.
"""

from datetime import UTC, datetime

import pytest
from core_shared.models.journals import JournalNotFoundError
from core_shared.models.journals.event_state import EventState
from core_shared.models.tasks import (
    LapseReason,
    TaskLinkRole,
    TaskReadModel,
    TaskStatus,
)
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.settings.models import UserSettings
from app.core.tasks.adapters.sql.task_repository import SqlTaskRepository
from app.core.tasks.services.task_read_service import TaskReadService
from tests.integration.statement_recorder import recorded_statements
from tests.integration.tasks.task_seeding import (
    OTHER_USER_ID,
    USER_ID,
    create_contact,
    create_journal,
    create_task,
    link_contact,
    link_intermediate_journal,
    mark_journal_as_event,
)

pytestmark = pytest.mark.integration


async def seed_viewed_journal(journal_repository: SqlJournalRepository) -> int:
    """The journal whose detail view is being rendered.

    Dated in the past, because that is what the journal a user is reading
    usually is — and because it must not accidentally be the thing that decides
    whether anything lapsed.
    """
    return await create_journal(journal_repository, title="Tuesday", days_offset=-3)


def task_ids(models: tuple[TaskReadModel, ...]) -> list[int | None]:
    """The ids in a group, in the order the group hands them out."""
    return [model.task.id for model in models]


@pytest.mark.integration
class TestGroupingAgainstRealLinkRows:
    """Which group each real link puts a task in."""

    async def test_the_three_roles_come_back_apart(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """One task per role, from three genuinely different link shapes."""
        viewed = await seed_viewed_journal(journal_repository)
        elsewhere = await create_journal(
            journal_repository, title="Elsewhere", days_offset=7
        )

        due_here = await create_task(
            async_connection, creating_journal_id=elsewhere, due_journal_id=viewed
        )
        created_here = await create_task(
            async_connection, creating_journal_id=viewed, due_journal_id=elsewhere
        )
        mentioned_here = await create_task(
            async_connection, creating_journal_id=elsewhere, due_journal_id=elsewhere
        )
        await link_intermediate_journal(
            async_connection, task_id=mentioned_here, journal_id=viewed
        )

        groups = await read_service.read_models_for_journal(USER_ID, viewed)

        assert task_ids(groups.due) == [due_here]
        assert task_ids(groups.created) == [created_here]
        assert task_ids(groups.mentioned) == [mentioned_here]

    async def test_a_journal_that_is_both_anchors_lists_the_task_twice(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Invariant 6, read back: created here *and* due here."""
        viewed = await seed_viewed_journal(journal_repository)
        task_id = await create_task(
            async_connection, creating_journal_id=viewed, due_journal_id=viewed
        )

        groups = await read_service.read_models_for_journal(USER_ID, viewed)

        assert task_ids(groups.due) == [task_id]
        assert task_ids(groups.created) == [task_id]
        assert task_ids(groups.tasks) == [task_id]

    async def test_a_retarget_onto_a_mentioned_journal_is_due_and_mentioned(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The intermediate row survives the retarget, so both links are real."""
        viewed = await seed_viewed_journal(journal_repository)
        elsewhere = await create_journal(journal_repository, days_offset=7)

        task_id = await create_task(
            async_connection, creating_journal_id=elsewhere, due_journal_id=viewed
        )
        await link_intermediate_journal(
            async_connection, task_id=task_id, journal_id=viewed
        )

        groups = await read_service.read_models_for_journal(USER_ID, viewed)

        assert task_ids(groups.due) == [task_id]
        assert task_ids(groups.mentioned) == [task_id]
        assert groups.roles_for(task_id) == (
            TaskLinkRole.DUE,
            TaskLinkRole.MENTIONED,
        )

    async def test_a_task_linked_to_another_journal_is_not_listed(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The query returns links, not the user's tasks."""
        viewed = await seed_viewed_journal(journal_repository)
        elsewhere = await create_journal(journal_repository, days_offset=7)
        await create_task(
            async_connection, creating_journal_id=elsewhere, due_journal_id=elsewhere
        )

        groups = await read_service.read_models_for_journal(USER_ID, viewed)

        assert groups.tasks == ()


@pytest.mark.integration
class TestOwnerScoping:
    """The link tables carry no owner, so the join has to."""

    async def test_another_users_journal_is_not_found(
        self,
        read_service: TaskReadService,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """A real journal, really owned by somebody else, answers as absent."""
        theirs = await create_journal(
            journal_repository, title="Theirs", user_id=OTHER_USER_ID
        )

        with pytest.raises(JournalNotFoundError):
            await read_service.read_models_for_journal(USER_ID, theirs)

    async def test_an_unknown_journal_is_not_found(
        self, read_service: TaskReadService
    ) -> None:
        """Indistinguishable from another user's, which is the point."""
        with pytest.raises(JournalNotFoundError):
            await read_service.read_models_for_journal(USER_ID, 2_000_000_000)

    async def test_another_users_task_anchored_nearby_is_never_listed(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Their task, their journal, and none of it in this answer.

        Constructed rather than assumed: both users get a journal and a task,
        and only the acting user's comes back.
        """
        viewed = await seed_viewed_journal(journal_repository)
        mine = await create_task(
            async_connection, creating_journal_id=viewed, due_journal_id=viewed
        )
        theirs_journal = await create_journal(
            journal_repository, title="Theirs", user_id=OTHER_USER_ID
        )
        await create_task(
            async_connection,
            creating_journal_id=theirs_journal,
            due_journal_id=theirs_journal,
            user_id=OTHER_USER_ID,
        )

        groups = await read_service.read_models_for_journal(USER_ID, viewed)

        assert task_ids(groups.tasks) == [mine]

    async def test_an_owned_journal_with_no_tasks_answers_empty(
        self,
        read_service: TaskReadService,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Nothing linked here is a different answer from nothing of yours."""
        viewed = await seed_viewed_journal(journal_repository)

        groups = await read_service.read_models_for_journal(USER_ID, viewed)

        assert groups.journal_id == viewed
        assert groups.tasks == ()


@pytest.mark.integration
class TestLapseAgainstRealJournals:
    """The derivation, through the batched path, against real rows."""

    async def test_a_task_due_in_a_cancelled_event_journal_is_lapsed(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The cause a forward-dated journal can still have.

        The due journal is a week away, so nothing about its *date* lapses the
        task — only the ``journal_calendar_info`` row saying the event was
        called off, read in batch alongside every other journal here.
        """
        viewed = await seed_viewed_journal(journal_repository)
        due = await create_journal(journal_repository, title="Cancelled", days_offset=7)
        await mark_journal_as_event(
            async_connection, due, event_state=EventState.CANCELLED
        )
        task_id = await create_task(
            async_connection, creating_journal_id=viewed, due_journal_id=due
        )

        groups = await read_service.read_models_for_journal(USER_ID, viewed)

        (model,) = groups.created
        assert model.task.id == task_id
        assert model.lapsed is True
        assert model.lapse_reason is LapseReason.DUE_JOURNAL_CANCELLED
        assert model.due_journal.cancelled is True

    async def test_a_confirmed_event_journal_lapses_nothing(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Being an event is not being cancelled."""
        viewed = await seed_viewed_journal(journal_repository)
        due = await create_journal(journal_repository, days_offset=7)
        await mark_journal_as_event(
            async_connection, due, event_state=EventState.CONFIRMED
        )
        await create_task(
            async_connection, creating_journal_id=viewed, due_journal_id=due
        )

        groups = await read_service.read_models_for_journal(USER_ID, viewed)

        assert groups.created[0].lapse_reason is None
        assert groups.created[0].due_journal.cancelled is False

    async def test_a_task_due_in_a_passed_journal_is_lapsed(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The ordinary lapse, from a journal whose day has gone."""
        viewed = await seed_viewed_journal(journal_repository)
        due = await create_journal(journal_repository, days_offset=-1)
        await create_task(
            async_connection, creating_journal_id=viewed, due_journal_id=due
        )

        groups = await read_service.read_models_for_journal(USER_ID, viewed)

        assert groups.created[0].lapse_reason is LapseReason.DATE_PASSED

    @pytest.mark.parametrize("status", [TaskStatus.DONE, TaskStatus.CANCELLED])
    async def test_a_finished_task_is_never_lapsed(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        status: TaskStatus,
    ) -> None:
        """A commitment met or called off cannot then be let slide."""
        viewed = await seed_viewed_journal(journal_repository)
        due = await create_journal(journal_repository, days_offset=-1)
        await create_task(
            async_connection,
            creating_journal_id=viewed,
            due_journal_id=due,
            status=status,
        )

        groups = await read_service.read_models_for_journal(USER_ID, viewed)

        assert groups.created[0].lapse_reason is None

    @pytest.mark.parametrize("status", [TaskStatus.DONE, TaskStatus.CANCELLED])
    async def test_finished_tasks_are_still_listed_on_the_journal(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        status: TaskStatus,
    ) -> None:
        """A journal shows what it is linked to, whatever the status.

        The dashboard's tasks section hides done, cancelled and lapsed tasks;
        this surface does not. A done task's link to the journal it was created
        in is part of the record.
        """
        viewed = await seed_viewed_journal(journal_repository)
        due = await create_journal(journal_repository, days_offset=7)
        task_id = await create_task(
            async_connection,
            creating_journal_id=viewed,
            due_journal_id=due,
            status=status,
        )

        groups = await read_service.read_models_for_journal(USER_ID, viewed)

        assert task_ids(groups.created) == [task_id]

    async def test_a_lapsed_task_is_still_listed_on_the_journal(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """ "They remain visible on every journal they are linked to."""
        viewed = await seed_viewed_journal(journal_repository)
        due = await create_journal(journal_repository, days_offset=-1)
        task_id = await create_task(
            async_connection, creating_journal_id=viewed, due_journal_id=due
        )

        groups = await read_service.read_models_for_journal(USER_ID, viewed)

        assert task_ids(groups.created) == [task_id]
        assert groups.created[0].lapsed is True


@pytest.mark.integration
class TestOrdering:
    """The total order the surface promises, over rows that genuinely tie."""

    async def test_a_group_is_ordered_by_due_date_then_task_id(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Soonest first, and the tie broken by id rather than by insert order.

        Every task here is created in the viewed journal and inserted in an
        order that disagrees with the promised one, so a listing that simply
        returned rows as the database found them would fail.
        """
        viewed = await seed_viewed_journal(journal_repository)
        far = await create_journal(journal_repository, title="Far", days_offset=30)
        near = await create_journal(journal_repository, title="Near", days_offset=2)

        far_second = await create_task(
            async_connection, creating_journal_id=viewed, due_journal_id=far
        )
        far_first = await create_task(
            async_connection, creating_journal_id=viewed, due_journal_id=far
        )
        near_task = await create_task(
            async_connection, creating_journal_id=viewed, due_journal_id=near
        )

        groups = await read_service.read_models_for_journal(USER_ID, viewed)

        assert task_ids(groups.created) == [
            near_task,
            min(far_first, far_second),
            max(far_first, far_second),
        ]

    async def test_the_due_group_is_ordered_by_task_id(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Every task due here shares this journal's date, so the tie is total.

        This is the group where the date half of the order does nothing at all,
        which is exactly why the id tie-break is not decoration: without it the
        order would be whatever PostgreSQL returned.
        """
        viewed = await seed_viewed_journal(journal_repository)
        elsewhere = await create_journal(journal_repository, days_offset=7)
        ids = [
            await create_task(
                async_connection,
                creating_journal_id=elsewhere,
                due_journal_id=viewed,
            )
            for _ in range(4)
        ]

        groups = await read_service.read_models_for_journal(USER_ID, viewed)

        assert task_ids(groups.due) == sorted(ids)

    async def test_a_tasks_mentions_are_ordered_by_journal_id_when_they_tie(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The tie Phase 10 recorded, closed rather than described.

        ``created_at`` defaults to ``transaction_timestamp()``, and every row a
        test writes shares one transaction — so these three links tie exactly as
        links written in one request do. They are attached in descending id
        order so a query relying on ``created_at`` alone would return them that
        way.
        """
        viewed = await seed_viewed_journal(journal_repository)
        task_id = await create_task(
            async_connection, creating_journal_id=viewed, due_journal_id=viewed
        )
        mentions = [
            await create_journal(journal_repository, title=f"Mention {index}")
            for index in range(3)
        ]
        for journal_id in reversed(mentions):
            await link_intermediate_journal(
                async_connection, task_id=task_id, journal_id=journal_id
            )

        groups = await read_service.read_models_for_journal(USER_ID, viewed)

        (model,) = groups.due
        assert [ref.id for ref in model.intermediate_journals] == sorted(mentions)

    async def test_a_tasks_contacts_are_ordered_by_contact_id_when_they_tie(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The same tie on the other link table, closed the same way."""
        viewed = await seed_viewed_journal(journal_repository)
        task_id = await create_task(
            async_connection, creating_journal_id=viewed, due_journal_id=viewed
        )
        contacts = [
            await create_contact(async_connection, first_name=f"Person{index}")
            for index in range(3)
        ]
        for contact_id in reversed(contacts):
            await link_contact(async_connection, task_id=task_id, contact_id=contact_id)

        groups = await read_service.read_models_for_journal(USER_ID, viewed)

        (model,) = groups.due
        assert [contact.id for contact in model.contacts] == sorted(contacts)


@pytest.mark.integration
class TestOneQueryPerCollection:
    """The third acceptance criterion, counted at the driver."""

    async def seed_tasks(
        self,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        viewed: int,
        count: int,
    ) -> None:
        """``count`` tasks on the journal, each with a mention and a contact."""
        due = await create_journal(journal_repository, title="Due", days_offset=7)
        mention = await create_journal(journal_repository, title="Mention")
        for index in range(count):
            task_id = await create_task(
                async_connection,
                creating_journal_id=viewed,
                due_journal_id=due,
                text=f"task {index}",
            )
            await link_intermediate_journal(
                async_connection, task_id=task_id, journal_id=mention
            )
            contact = await create_contact(
                async_connection, first_name=f"Person{index}"
            )
            await link_contact(async_connection, task_id=task_id, contact_id=contact)

    async def test_two_tasks_cost_one_statement_per_collection(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Seven: the tasks, their mentions, their contacts, the timezone, the
        journals for every role together, the cancellation lookup, and the
        contact names. One per thing that has to be known, and nothing repeated.
        """
        viewed = await seed_viewed_journal(journal_repository)
        await self.seed_tasks(async_connection, journal_repository, viewed, 2)

        with recorded_statements(async_connection) as statements:
            groups = await read_service.read_models_for_journal(USER_ID, viewed)

        assert len(groups.created) == 2
        assert len(statements) == 7

    async def test_more_tasks_cost_no_more_statements(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The claim that matters: the cost does not grow with the task count.

        A fixed number on its own would also pass against a loop that ran a
        fixed number of times, so the fixture triples.
        """
        viewed = await seed_viewed_journal(journal_repository)
        await self.seed_tasks(async_connection, journal_repository, viewed, 6)

        with recorded_statements(async_connection) as statements:
            groups = await read_service.read_models_for_journal(USER_ID, viewed)

        assert len(groups.created) == 6
        assert len(statements) == 7

    async def test_the_single_task_read_still_costs_seven(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The batched path must not make the single read more expensive.

        ``read_model`` is refactored onto the same assembly here, so its cost is
        re-asserted where the change could break it.
        """
        viewed = await seed_viewed_journal(journal_repository)
        await self.seed_tasks(async_connection, journal_repository, viewed, 1)
        groups = await read_service.read_models_for_journal(USER_ID, viewed)
        task_id = groups.created[0].task.id
        assert task_id is not None

        with recorded_statements(async_connection) as statements:
            await read_service.read_model(USER_ID, task_id)

        assert len(statements) == 7


@pytest.mark.integration
class TestRoleFilter:
    """Narrowing to one role, against real links."""

    @pytest.mark.parametrize(
        "role", [TaskLinkRole.DUE, TaskLinkRole.CREATED, TaskLinkRole.MENTIONED]
    )
    async def test_filtering_returns_only_that_role(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        role: TaskLinkRole,
    ) -> None:
        """One task in each role; asking for one gets exactly one."""
        viewed = await seed_viewed_journal(journal_repository)
        elsewhere = await create_journal(journal_repository, days_offset=7)
        expected = {
            TaskLinkRole.DUE: await create_task(
                async_connection,
                creating_journal_id=elsewhere,
                due_journal_id=viewed,
            ),
            TaskLinkRole.CREATED: await create_task(
                async_connection,
                creating_journal_id=viewed,
                due_journal_id=elsewhere,
            ),
        }
        mentioned = await create_task(
            async_connection, creating_journal_id=elsewhere, due_journal_id=elsewhere
        )
        await link_intermediate_journal(
            async_connection, task_id=mentioned, journal_id=viewed
        )
        expected[TaskLinkRole.MENTIONED] = mentioned

        groups = await read_service.read_models_for_journal(USER_ID, viewed, role=role)

        assert task_ids(groups.for_role(role)) == [expected[role]]
        assert task_ids(groups.tasks) == [expected[role]]


@pytest.mark.integration
class TestTimezoneAnchoring:
    """Whose day the whole list is judged against."""

    async def test_the_lapse_is_judged_in_the_users_timezone(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        user_settings_repository: SqlUserSettingsRepository,
    ) -> None:
        """Sydney has turned the page while UTC has not.

        The due journal sits at 13:00Z on 9 August — 23:00 on the 9th in
        Sydney — and ``now`` is 14:30Z the same day, already 00:30 on the 10th
        there. UTC would call the task outstanding; Sydney calls it lapsed, and
        the list resolves the zone once for every task in it.
        """
        viewed = await seed_viewed_journal(journal_repository)
        due = await create_journal(
            journal_repository,
            title="Sydney evening",
            start=datetime(2026, 8, 9, 13, 0, tzinfo=UTC),
        )
        await create_task(
            async_connection, creating_journal_id=viewed, due_journal_id=due
        )
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone="Australia/Sydney")
        )

        groups = await read_service.read_models_for_journal(
            USER_ID,
            viewed,
            now=datetime(2026, 8, 9, 14, 30, tzinfo=UTC),
        )

        assert groups.created[0].lapse_reason is LapseReason.DATE_PASSED

    async def test_the_same_instant_in_utc_leaves_the_task_outstanding(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The other half of the pair, without which the case proves nothing."""
        viewed = await seed_viewed_journal(journal_repository)
        due = await create_journal(
            journal_repository,
            title="Sydney evening",
            start=datetime(2026, 8, 9, 13, 0, tzinfo=UTC),
        )
        await create_task(
            async_connection, creating_journal_id=viewed, due_journal_id=due
        )

        groups = await read_service.read_models_for_journal(
            USER_ID,
            viewed,
            now=datetime(2026, 8, 9, 14, 30, tzinfo=UTC),
        )

        assert groups.created[0].lapse_reason is None


@pytest.mark.integration
class TestBatchedLinkReads:
    """The repository methods the batch is built on, on their own terms."""

    async def test_mentions_come_back_keyed_by_task(
        self,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Two tasks, different mentions, and no crossing between them."""
        viewed = await seed_viewed_journal(journal_repository)
        first_mention = await create_journal(journal_repository, title="First")
        second_mention = await create_journal(journal_repository, title="Second")
        first = await create_task(
            async_connection, creating_journal_id=viewed, due_journal_id=viewed
        )
        second = await create_task(
            async_connection, creating_journal_id=viewed, due_journal_id=viewed
        )
        await link_intermediate_journal(
            async_connection, task_id=first, journal_id=first_mention
        )
        await link_intermediate_journal(
            async_connection, task_id=second, journal_id=second_mention
        )

        by_task = await task_repository.list_intermediate_journal_ids_for_tasks(
            [first, second], USER_ID
        )

        assert by_task == {first: [first_mention], second: [second_mention]}

    async def test_a_task_with_no_links_is_absent_rather_than_empty(
        self,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The caller reads through ``.get(task_id, [])``, so absence is enough.

        A row per linkless task would cost the query an outer join for nothing.
        """
        viewed = await seed_viewed_journal(journal_repository)
        task_id = await create_task(
            async_connection, creating_journal_id=viewed, due_journal_id=viewed
        )

        assert (
            await task_repository.list_intermediate_journal_ids_for_tasks(
                [task_id], USER_ID
            )
            == {}
        )

    async def test_another_users_links_are_never_returned(
        self,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Owner scoping lives in the join, because the link table has no owner.

        Their task id is supplied deliberately: a batch that trusted its input
        would hand back links the caller may not see.
        """
        theirs_journal = await create_journal(
            journal_repository, title="Theirs", user_id=OTHER_USER_ID
        )
        theirs = await create_task(
            async_connection,
            creating_journal_id=theirs_journal,
            due_journal_id=theirs_journal,
            user_id=OTHER_USER_ID,
        )
        await link_intermediate_journal(
            async_connection, task_id=theirs, journal_id=theirs_journal
        )
        contact = await create_contact(async_connection)
        await link_contact(async_connection, task_id=theirs, contact_id=contact)

        assert (
            await task_repository.list_intermediate_journal_ids_for_tasks(
                [theirs], USER_ID
            )
            == {}
        )
        assert await task_repository.list_contact_ids_for_tasks([theirs], USER_ID) == {}

    async def test_an_empty_id_list_reads_nothing(
        self,
        task_repository: SqlTaskRepository,
    ) -> None:
        """A journal with no tasks asks for no links at all."""
        assert (
            await task_repository.list_intermediate_journal_ids_for_tasks([], USER_ID)
            == {}
        )
        assert await task_repository.list_contact_ids_for_tasks([], USER_ID) == {}

    async def test_the_journal_query_returns_every_linked_role_once(
        self,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """A task linked three ways is one row, not three.

        The query unions three link shapes, so without a distinct the two-role
        tasks would arrive duplicated and be assembled twice.
        """
        viewed = await seed_viewed_journal(journal_repository)
        task_id = await create_task(
            async_connection, creating_journal_id=viewed, due_journal_id=viewed
        )
        await link_intermediate_journal(
            async_connection, task_id=task_id, journal_id=viewed
        )

        tasks = await task_repository.find_tasks_for_journal(viewed, USER_ID)

        assert [task.id for task in tasks] == [task_id]


@pytest.mark.integration
class TestJournalDatesAreResolvedOnce:
    """A journal shared by many tasks is fetched, and dated, once."""

    async def test_every_task_sees_the_same_journal_object_values(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The shared due journal reads identically on every task."""
        viewed = await seed_viewed_journal(journal_repository)
        due = await create_journal(
            journal_repository, title="Shared deadline", days_offset=5
        )
        for _ in range(3):
            await create_task(
                async_connection, creating_journal_id=viewed, due_journal_id=due
            )

        groups = await read_service.read_models_for_journal(USER_ID, viewed)

        dates = {model.due_journal.date for model in groups.created}
        titles = {model.due_journal.title for model in groups.created}
        assert len(groups.created) == 3
        assert len(dates) == 1
        assert titles == {"Shared deadline"}
