"""Unit tests for reading a journal's tasks in one pass.

``read_model`` assembles one task. This is the *list* half: every task linked to
a journal, in any role, assembled and grouped. It exists as a separate method
rather than a loop over the single read because the loop is precisely what the
phase forbids — the third acceptance criterion asks for "one query per
collection, not per task", and at journal scale an N+1 here is a correctness
concern rather than a performance note.

**The round-trip assertions are the point of this file.** A functional test
cannot see an N+1: the answer is right either way and only the number of reads
is wrong. So the tests below assert the *call counts* on the doubles, and they
do it at two fixture sizes — two tasks and six — because a fixed expected count
alone would also be satisfied by a loop that happened to run a fixed number of
times. The integration suite repeats the claim against real statements; this
one fails first and faster.

**Ownership has no separate check, and that is deliberate.** The journal the
caller names is resolved through the same owner-scoped journal fetch the read
models already need, so an unknown journal and another user's are the same
absence, and the surface costs no extra statement to be safe. The tests pin
both halves: the 404 and the absence of a second lookup.
"""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock

import pytest
from core_shared.models.journals import JournalNotFoundError
from core_shared.models.tasks import LapseReason, TaskLinkRole, TaskStatus

from app.core.tasks.services.task_read_service import TaskReadService
from tests.unit.tasks.read_service_doubles import (
    FAR_FUTURE,
    journal_repo_knowing,
    make_journal,
    make_task,
)
from tests.unit.tasks.task_doubles import OTHER_USER_ID, USER_ID

# The journal being viewed, plus the ones its tasks reach out to.
JOURNAL_ID = 100
ELSEWHERE_ID = 200
FURTHER_OUT_ID = 300

# The two dates this suite moves deliberately; ``FAR_FUTURE``, the default
# every other journal takes, is shared with the sibling suites.
NEARER_FUTURE = datetime.datetime(2029, 1, 1, tzinfo=datetime.UTC)
LONG_PAST = datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)


@pytest.fixture
def task_repo() -> AsyncMock:
    """A task repository holding one task due in the journal, with no links."""
    repo = AsyncMock()
    repo.find_tasks_for_journal.return_value = [
        make_task(1, creating_journal_id=ELSEWHERE_ID, due_journal_id=JOURNAL_ID)
    ]
    repo.list_intermediate_journal_ids_for_tasks.return_value = {}
    repo.list_contact_ids_for_tasks.return_value = {}
    return repo


@pytest.fixture
def journal_repo() -> AsyncMock:
    """A journal repository that knows every journal these tests name."""
    known = {
        JOURNAL_ID: make_journal(JOURNAL_ID, title="Tuesday"),
        ELSEWHERE_ID: make_journal(ELSEWHERE_ID, title="Monday Planning"),
        FURTHER_OUT_ID: make_journal(FURTHER_OUT_ID, title="Trip Prep"),
    }

    return journal_repo_knowing(known)


@pytest.fixture
def service(read_service: TaskReadService) -> TaskReadService:
    """This file's own name for the shared ``read_service`` fixture.

    An alias rather than a rename: the ports it wires up are defined once in
    ``conftest.py`` now, and keeping the local name spared ~50 test signatures
    a change that would have said nothing.
    """
    return read_service


def seed_many(task_repo: AsyncMock, count: int) -> None:
    """A journal with ``count`` tasks, each carrying a mention and a contact.

    Every task is created in the journal and due elsewhere, so the fixture
    exercises the anchor batch, the mention batch and the contact batch at once.
    """
    tasks = [
        make_task(
            task_id, creating_journal_id=JOURNAL_ID, due_journal_id=FURTHER_OUT_ID
        )
        for task_id in range(1, count + 1)
    ]
    task_repo.find_tasks_for_journal.return_value = tasks
    task_repo.list_intermediate_journal_ids_for_tasks.return_value = {
        task.id: [ELSEWHERE_ID] for task in tasks
    }
    task_repo.list_contact_ids_for_tasks.return_value = {task.id: [7] for task in tasks}


@pytest.mark.unit
class TestOwnerScoping:
    """A journal the caller does not own is a journal that is not there."""

    async def test_an_unknown_journal_raises_journal_not_found(
        self,
        service: TaskReadService,
        task_repo: AsyncMock,
        journal_repo: AsyncMock,
    ) -> None:
        """Absent from the owner-scoped fetch means absent, full stop."""
        task_repo.find_tasks_for_journal.return_value = []
        journal_repo.find_by_ids_for_user.side_effect = None
        journal_repo.find_by_ids_for_user.return_value = []

        with pytest.raises(JournalNotFoundError):
            await service.read_models_for_journal(USER_ID, JOURNAL_ID)

    async def test_another_users_journal_is_reached_the_same_way(
        self,
        service: TaskReadService,
        task_repo: AsyncMock,
        journal_repo: AsyncMock,
    ) -> None:
        """Ownership is the query's, so a foreign journal is simply absent.

        The service passes the acting user through and never compares a
        ``user_id`` itself, which is what keeps "not yours" and "not there"
        indistinguishable — the same hedge the anchor 404 carries.
        """
        task_repo.find_tasks_for_journal.return_value = []
        journal_repo.find_by_ids_for_user.side_effect = None
        journal_repo.find_by_ids_for_user.return_value = []

        with pytest.raises(JournalNotFoundError):
            await service.read_models_for_journal(OTHER_USER_ID, JOURNAL_ID)

        task_repo.find_tasks_for_journal.assert_awaited_once_with(
            JOURNAL_ID, OTHER_USER_ID
        )

    async def test_an_owned_journal_with_no_tasks_answers_empty_groups(
        self, service: TaskReadService, task_repo: AsyncMock
    ) -> None:
        """An empty journal is a normal answer, not a 404.

        The distinction the ownership check buys: nothing linked here, versus
        nothing of yours here.
        """
        task_repo.find_tasks_for_journal.return_value = []

        groups = await service.read_models_for_journal(USER_ID, JOURNAL_ID)

        assert groups.journal_id == JOURNAL_ID
        assert groups.tasks == ()

    async def test_ownership_costs_no_second_journal_lookup(
        self, service: TaskReadService, journal_repo: AsyncMock
    ) -> None:
        """The journal is resolved by the fetch the read models already need."""
        await service.read_models_for_journal(USER_ID, JOURNAL_ID)

        journal_repo.find_by_ids_for_user.assert_awaited_once()
        _, requested = journal_repo.find_by_ids_for_user.await_args.args
        assert JOURNAL_ID in requested


@pytest.mark.unit
class TestOneReadPerCollection:
    """The third acceptance criterion, asserted where it fails fastest."""

    @pytest.mark.parametrize("task_count", [2, 6])
    async def test_each_collection_is_read_once_whatever_the_task_count(
        self,
        service: TaskReadService,
        task_repo: AsyncMock,
        journal_repo: AsyncMock,
        contact_repo: AsyncMock,
        calendar_info_repo: AsyncMock,
        settings_repo: AsyncMock,
        task_count: int,
    ) -> None:
        """Two tasks and six cost the same number of reads.

        The doubling is what makes the claim mean something: a fixed count on
        its own would also pass against a loop that ran a fixed number of times.
        """
        seed_many(task_repo, task_count)

        await service.read_models_for_journal(USER_ID, JOURNAL_ID)

        assert task_repo.find_tasks_for_journal.await_count == 1
        assert task_repo.list_intermediate_journal_ids_for_tasks.await_count == 1
        assert task_repo.list_contact_ids_for_tasks.await_count == 1
        assert journal_repo.find_by_ids_for_user.await_count == 1
        assert calendar_info_repo.find_cancelled_journal_ids.await_count == 1
        assert contact_repo.find_names_by_ids.await_count == 1
        assert settings_repo.get_timezone.await_count == 1

    async def test_the_per_task_link_reads_are_never_used(
        self, service: TaskReadService, task_repo: AsyncMock
    ) -> None:
        """The batch path must not fall back to the single-task methods.

        Those are what an N+1 would look like from the inside, so they are
        asserted untouched rather than merely counted.
        """
        seed_many(task_repo, 6)

        await service.read_models_for_journal(USER_ID, JOURNAL_ID)

        task_repo.list_intermediate_journal_ids.assert_not_awaited()
        task_repo.list_contact_ids.assert_not_awaited()

    async def test_every_journal_across_every_task_arrives_in_one_call(
        self, service: TaskReadService, task_repo: AsyncMock, journal_repo: AsyncMock
    ) -> None:
        """Anchors and mentions for the whole set, de-duplicated, in one query."""
        seed_many(task_repo, 6)

        await service.read_models_for_journal(USER_ID, JOURNAL_ID)

        _, requested = journal_repo.find_by_ids_for_user.await_args.args
        assert sorted(requested) == [JOURNAL_ID, ELSEWHERE_ID, FURTHER_OUT_ID]

    async def test_every_contact_across_every_task_arrives_in_one_call(
        self, service: TaskReadService, task_repo: AsyncMock, contact_repo: AsyncMock
    ) -> None:
        """One name lookup for the collection, de-duplicated across tasks."""
        seed_many(task_repo, 6)

        await service.read_models_for_journal(USER_ID, JOURNAL_ID)

        (requested,) = contact_repo.find_names_by_ids.await_args.args
        assert requested == [7]

    async def test_no_contact_lookup_when_no_task_references_anyone(
        self, service: TaskReadService, contact_repo: AsyncMock
    ) -> None:
        """A read nobody needs is a read nobody pays for."""
        await service.read_models_for_journal(USER_ID, JOURNAL_ID)

        contact_repo.find_names_by_ids.assert_not_awaited()

    async def test_the_batched_link_reads_are_scoped_to_the_acting_user(
        self, service: TaskReadService, task_repo: AsyncMock
    ) -> None:
        """Owner scoping is part of the port's contract, batch included."""
        seed_many(task_repo, 2)

        await service.read_models_for_journal(USER_ID, JOURNAL_ID)

        task_repo.list_intermediate_journal_ids_for_tasks.assert_awaited_once_with(
            [1, 2], USER_ID
        )
        task_repo.list_contact_ids_for_tasks.assert_awaited_once_with([1, 2], USER_ID)


@pytest.mark.unit
class TestAssembly:
    """What the models carry once the pieces are in."""

    async def test_the_groups_carry_the_assembled_read_models(
        self, service: TaskReadService, task_repo: AsyncMock
    ) -> None:
        """Grouped by role, with the journal refs resolved."""
        task_repo.find_tasks_for_journal.return_value = [
            make_task(1, creating_journal_id=ELSEWHERE_ID, due_journal_id=JOURNAL_ID)
        ]

        groups = await service.read_models_for_journal(USER_ID, JOURNAL_ID)

        (model,) = groups.due
        assert model.task.id == 1
        assert model.due_journal.id == JOURNAL_ID
        assert model.due_journal.title == "Tuesday"
        assert model.creating_journal.id == ELSEWHERE_ID

    async def test_mentions_are_attached_to_the_task_that_owns_them(
        self, service: TaskReadService, task_repo: AsyncMock
    ) -> None:
        """The batch is keyed by task id, so links cannot cross tasks."""
        task_repo.find_tasks_for_journal.return_value = [
            make_task(1, creating_journal_id=JOURNAL_ID, due_journal_id=ELSEWHERE_ID),
            make_task(2, creating_journal_id=JOURNAL_ID, due_journal_id=ELSEWHERE_ID),
        ]
        task_repo.list_intermediate_journal_ids_for_tasks.return_value = {
            2: [FURTHER_OUT_ID]
        }

        groups = await service.read_models_for_journal(USER_ID, JOURNAL_ID)
        by_id = {model.task.id: model for model in groups.tasks}

        assert by_id[1].intermediate_journals == ()
        assert [ref.id for ref in by_id[2].intermediate_journals] == [FURTHER_OUT_ID]

    async def test_contacts_are_attached_to_the_task_that_references_them(
        self, service: TaskReadService, task_repo: AsyncMock, contact_repo: AsyncMock
    ) -> None:
        """The same keying, for the other link table."""
        task_repo.find_tasks_for_journal.return_value = [
            make_task(1, creating_journal_id=JOURNAL_ID, due_journal_id=ELSEWHERE_ID),
            make_task(2, creating_journal_id=JOURNAL_ID, due_journal_id=ELSEWHERE_ID),
        ]
        task_repo.list_contact_ids_for_tasks.return_value = {2: [7]}
        contact_repo.find_names_by_ids.return_value = {
            7: ("Sarah", "Chen", "https://example.test/sarah.jpg")
        }

        groups = await service.read_models_for_journal(USER_ID, JOURNAL_ID)
        by_id = {model.task.id: model for model in groups.tasks}

        assert by_id[1].contacts == ()
        assert [contact.display_name for contact in by_id[2].contacts] == ["Sarah Chen"]

    async def test_a_mention_whose_journal_is_missing_is_dropped(
        self, service: TaskReadService, task_repo: AsyncMock
    ) -> None:
        """A task the user can still open beats one showing every mention.

        The same asymmetry the single read takes, kept through the batch: a
        missing mention loses a mention, and nothing else.
        """
        task_repo.find_tasks_for_journal.return_value = [
            make_task(1, creating_journal_id=JOURNAL_ID, due_journal_id=ELSEWHERE_ID)
        ]
        task_repo.list_intermediate_journal_ids_for_tasks.return_value = {1: [999]}

        groups = await service.read_models_for_journal(USER_ID, JOURNAL_ID)

        assert groups.created[0].intermediate_journals == ()

    async def test_a_missing_anchor_still_fails_loudly(
        self, service: TaskReadService, task_repo: AsyncMock
    ) -> None:
        """The due journal is what the lapse rule reads, so losing it is fatal.

        Unreachable in practice — both anchors are ``ON DELETE RESTRICT`` — and
        asserted because inventing a lapse verdict would be worse than failing.
        """
        task_repo.find_tasks_for_journal.return_value = [
            make_task(1, creating_journal_id=JOURNAL_ID, due_journal_id=999)
        ]

        with pytest.raises(JournalNotFoundError):
            await service.read_models_for_journal(USER_ID, JOURNAL_ID)


@pytest.mark.unit
class TestLapseThroughTheBatch:
    """The derivation survives the batched path unchanged."""

    async def test_a_task_due_in_a_passed_journal_is_lapsed(
        self, service: TaskReadService, task_repo: AsyncMock, journal_repo: AsyncMock
    ) -> None:
        """The ordinary lapse, read through the list surface."""
        task_repo.find_tasks_for_journal.return_value = [
            make_task(1, creating_journal_id=JOURNAL_ID, due_journal_id=ELSEWHERE_ID)
        ]
        journal_repo.find_by_ids_for_user.side_effect = None
        journal_repo.find_by_ids_for_user.return_value = [
            make_journal(JOURNAL_ID),
            make_journal(ELSEWHERE_ID, LONG_PAST),
        ]

        groups = await service.read_models_for_journal(USER_ID, JOURNAL_ID)

        assert groups.created[0].lapse_reason is LapseReason.DATE_PASSED

    async def test_a_cancelled_due_journal_lapses_its_task(
        self,
        service: TaskReadService,
        task_repo: AsyncMock,
        calendar_info_repo: AsyncMock,
    ) -> None:
        """Cancellation is read for the whole set in one statement."""
        task_repo.find_tasks_for_journal.return_value = [
            make_task(1, creating_journal_id=JOURNAL_ID, due_journal_id=ELSEWHERE_ID)
        ]
        calendar_info_repo.find_cancelled_journal_ids.return_value = {ELSEWHERE_ID}

        groups = await service.read_models_for_journal(USER_ID, JOURNAL_ID)

        assert groups.created[0].lapse_reason is LapseReason.DUE_JOURNAL_CANCELLED

    async def test_a_done_task_is_never_lapsed(
        self, service: TaskReadService, task_repo: AsyncMock, journal_repo: AsyncMock
    ) -> None:
        """The status gate holds through the batch as well."""
        task_repo.find_tasks_for_journal.return_value = [
            make_task(
                1,
                creating_journal_id=JOURNAL_ID,
                due_journal_id=ELSEWHERE_ID,
                status=TaskStatus.DONE,
            )
        ]
        journal_repo.find_by_ids_for_user.side_effect = None
        journal_repo.find_by_ids_for_user.return_value = [
            make_journal(JOURNAL_ID),
            make_journal(ELSEWHERE_ID, LONG_PAST),
        ]

        groups = await service.read_models_for_journal(USER_ID, JOURNAL_ID)

        assert groups.created[0].lapse_reason is None

    async def test_done_and_cancelled_tasks_are_still_listed(
        self, service: TaskReadService, task_repo: AsyncMock
    ) -> None:
        """A journal shows the tasks it is linked to, whatever their status.

        The dashboard hides done, cancelled and lapsed tasks; a journal does
        not. The specification keeps lapsed tasks "visible on every journal they
        are linked to", and a done task's link to the journal it was created in
        is part of the record.
        """
        task_repo.find_tasks_for_journal.return_value = [
            make_task(
                1,
                creating_journal_id=JOURNAL_ID,
                due_journal_id=ELSEWHERE_ID,
                status=TaskStatus.DONE,
            ),
            make_task(
                2,
                creating_journal_id=JOURNAL_ID,
                due_journal_id=ELSEWHERE_ID,
                status=TaskStatus.CANCELLED,
            ),
        ]

        groups = await service.read_models_for_journal(USER_ID, JOURNAL_ID)

        assert [model.task.id for model in groups.created] == [1, 2]


@pytest.mark.unit
class TestTimezoneAnchoring:
    """Whose day the dates belong to, decided once for the whole list."""

    async def test_today_is_anchored_in_the_users_timezone(
        self, service: TaskReadService, task_repo: AsyncMock, settings_repo: AsyncMock
    ) -> None:
        """Sydney has turned the page while UTC has not.

        A journal at 13:00Z on 9 August is 23:00 on the 9th in Sydney; ``now``
        at 14:30Z the same day is already 00:30 on the **10th** there. So Sydney
        says the task lapsed and UTC says it did not, which is the only way to
        prove which zone the derivation used.
        """
        settings_repo.get_timezone.return_value = "Australia/Sydney"
        task_repo.find_tasks_for_journal.return_value = [
            make_task(1, creating_journal_id=JOURNAL_ID, due_journal_id=ELSEWHERE_ID)
        ]

        groups = await service.read_models_for_journal(
            USER_ID,
            JOURNAL_ID,
            now=datetime.datetime(2026, 8, 9, 14, 30, tzinfo=datetime.UTC),
        )

        assert groups.created[0].lapse_reason is LapseReason.DATE_PASSED

    @pytest.fixture(autouse=True)
    def _journals_dated_on_the_boundary(self, journal_repo: AsyncMock) -> None:
        """Both journals sit at 13:00Z on 9 August for the case above."""
        boundary = datetime.datetime(2026, 8, 9, 13, 0, tzinfo=datetime.UTC)
        journal_repo.find_by_ids_for_user.side_effect = None
        journal_repo.find_by_ids_for_user.return_value = [
            make_journal(JOURNAL_ID, boundary),
            make_journal(ELSEWHERE_ID, boundary),
        ]


@pytest.mark.unit
class TestRoleFilterReachesTheGrouping:
    """The service hands the filter through rather than re-implementing it."""

    async def test_filtering_to_one_role_narrows_the_answer(
        self, service: TaskReadService, task_repo: AsyncMock
    ) -> None:
        """One task in each role; asking for one gets one."""
        task_repo.find_tasks_for_journal.return_value = [
            make_task(1, creating_journal_id=ELSEWHERE_ID, due_journal_id=JOURNAL_ID),
            make_task(2, creating_journal_id=JOURNAL_ID, due_journal_id=ELSEWHERE_ID),
        ]

        groups = await service.read_models_for_journal(
            USER_ID, JOURNAL_ID, role=TaskLinkRole.CREATED
        )

        assert [model.task.id for model in groups.created] == [2]
        assert groups.due == ()

    async def test_the_filter_does_not_narrow_the_fetch(
        self, service: TaskReadService, task_repo: AsyncMock
    ) -> None:
        """Filtering happens in the grouping, not in the query.

        A role is derived from anchors and mentions the read model already
        carries, so pushing the filter into SQL would mean two definitions of
        what "mentioned here" means, and the query would still have to fetch
        the anchors to answer it.
        """
        seed_many(task_repo, 6)

        await service.read_models_for_journal(
            USER_ID, JOURNAL_ID, role=TaskLinkRole.DUE
        )

        task_repo.find_tasks_for_journal.assert_awaited_once_with(JOURNAL_ID, USER_ID)


@pytest.mark.unit
class TestOrdering:
    """The order the surface promises, decided before the transport sees it."""

    async def test_a_group_is_ordered_by_due_date_then_task_id(
        self, service: TaskReadService, task_repo: AsyncMock, journal_repo: AsyncMock
    ) -> None:
        """Soonest first; ties broken by id so the answer never reshuffles."""
        task_repo.find_tasks_for_journal.return_value = [
            make_task(3, creating_journal_id=JOURNAL_ID, due_journal_id=FURTHER_OUT_ID),
            make_task(2, creating_journal_id=JOURNAL_ID, due_journal_id=FURTHER_OUT_ID),
            make_task(1, creating_journal_id=JOURNAL_ID, due_journal_id=ELSEWHERE_ID),
        ]
        journal_repo.find_by_ids_for_user.side_effect = None
        journal_repo.find_by_ids_for_user.return_value = [
            make_journal(JOURNAL_ID),
            make_journal(ELSEWHERE_ID, FAR_FUTURE),
            make_journal(FURTHER_OUT_ID, NEARER_FUTURE),
        ]

        groups = await service.read_models_for_journal(USER_ID, JOURNAL_ID)

        assert [model.task.id for model in groups.created] == [2, 3, 1]
