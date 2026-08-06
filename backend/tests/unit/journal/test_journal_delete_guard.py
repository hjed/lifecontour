"""Unit tests for the journal delete guard and the rule behind it.

A task is anchored to exactly two journals by foreign keys declared
``ON DELETE RESTRICT``, so deleting an anchoring journal is refused by the
database whatever the service does. What this phase adds is the *explanation*:
which tasks block the deletion, and — for each — the journal the user can go to
in order to cancel, complete or retarget it.

Three things are tested here, in the order they compose:

- **the rule** — which anchors block, and which journal each blocking task can
  be actioned from. It is a pure function over one task's anchors, so it is
  tested without a database or a repository;
- **the error** — that it is a 409 and that its message names each blocking task
  and where to go, rather than reporting a constraint;
- **the guard** — that :meth:`JournalService.delete_journal` consults the
  repository once, refuses before touching anything, and still deletes when
  nothing is anchored.

The concurrent-insert backstop is tested here too: the guard is check-then-act,
so a task inserted between the check and the ``DELETE`` still trips the foreign
key, and the caller must get the same explanatory error rather than a raw
``IntegrityError``.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.models.journals import (
    BlockingTask,
    EventDateRange,
    Journal,
    JournalHasAnchoredTasksError,
    blocking_task_from_anchors,
    describe_roles,
)
from core_shared.models.tasks import TaskStatus
from sqlalchemy.exc import IntegrityError

from app.api.error_handlers import create_domain_error_response
from app.core.journal.services.journal_service import JournalService

DELETED = 10
OTHER = 20


def make_row(
    *,
    creating_journal_id: int,
    due_journal_id: int,
    task_id: int = 1,
    text: str = "print the permit",
    status: TaskStatus = TaskStatus.NOT_DONE,
    deleted_journal_id: int = DELETED,
) -> BlockingTask | None:
    """Run one task's anchors through the rule, as the SQL adapter does."""
    return blocking_task_from_anchors(
        deleted_journal_id=deleted_journal_id,
        task_id=task_id,
        text=text,
        status=status,
        creating_journal_id=creating_journal_id,
        creating_journal_title="Monday Planning",
        due_journal_id=due_journal_id,
        due_journal_title="Permit Meeting",
    )


def make_blocking_task(
    *,
    task_id: int = 1,
    text: str = "print the permit",
    roles: tuple[str, ...] = ("due",),
    action_journal_id: int = OTHER,
    action_journal_title: str = "Monday Planning",
) -> BlockingTask:
    """A ready-made blocker, for the tests that are not about the rule."""
    return BlockingTask(
        task_id=task_id,
        text=text,
        status=TaskStatus.NOT_DONE,
        blocking_roles=roles,  # type: ignore[arg-type]
        action_journal_id=action_journal_id,
        action_journal_title=action_journal_title,
    )


class TestBlockingRule:
    """Which anchors block, and where each blocking task can be actioned."""

    def test_a_task_created_in_the_journal_blocks_and_is_actioned_from_its_due_journal(
        self,
    ):
        blocker = make_row(creating_journal_id=DELETED, due_journal_id=OTHER)

        assert blocker is not None
        assert blocker.blocking_roles == ("creating",)
        assert blocker.action_journal_id == OTHER
        assert blocker.action_journal_title == "Permit Meeting"

    def test_a_task_due_in_the_journal_is_actioned_from_its_creating_journal(self):
        """The due journal is the one going away, so the creating journal is
        the only anchor left that can surface the task."""
        blocker = make_row(creating_journal_id=OTHER, due_journal_id=DELETED)

        assert blocker is not None
        assert blocker.blocking_roles == ("due",)
        assert blocker.action_journal_id == OTHER
        assert blocker.action_journal_title == "Monday Planning"

    def test_a_task_created_in_and_due_in_the_journal_is_actioned_from_that_journal(
        self,
    ):
        """The specification permits creating == due. Both anchors then point at
        the journal being deleted, and the action journal is that same journal —
        which is correct rather than a fallback failure: the delete was refused,
        so the journal is still there to be opened."""
        blocker = make_row(creating_journal_id=DELETED, due_journal_id=DELETED)

        assert blocker is not None
        assert blocker.blocking_roles == ("creating", "due")
        assert blocker.action_journal_id == DELETED

    def test_a_task_anchored_to_neither_does_not_block(self):
        """The rule is total, not a filter the query is trusted to have applied:
        a row for a task that only *mentions* the journal blocks nothing."""
        assert make_row(creating_journal_id=OTHER, due_journal_id=OTHER) is None

    @pytest.mark.parametrize(
        "status", [TaskStatus.NOT_DONE, TaskStatus.DONE, TaskStatus.CANCELLED]
    )
    def test_status_is_carried_and_never_consulted(self, status: TaskStatus):
        """A done task's link to the journal it was created in is part of the
        record, so status changes what the message says and never whether the
        deletion is refused."""
        blocker = make_row(
            creating_journal_id=DELETED, due_journal_id=OTHER, status=status
        )

        assert blocker is not None
        assert blocker.status == status


class TestJournalHasAnchoredTasksError:
    """The failure is explanatory, not opaque."""

    def test_it_is_a_conflict(self):
        error = JournalHasAnchoredTasksError(DELETED, (make_blocking_task(),))

        assert error.status_code == 409
        assert error.journal_id == DELETED

    def test_it_carries_its_own_response_code(self):
        """A caller that has to tell this refusal apart from the journal
        domain's other 409 needs more than the status. The payload listing the
        blockers is Phase 2's; the code is what makes that possible."""
        response = create_domain_error_response(
            JournalHasAnchoredTasksError(DELETED, (make_blocking_task(),))
        )

        assert response.errors[0].code == "JOURNAL_HAS_ANCHORED_TASKS"
        assert response.errors[0].status == "409"

    def test_a_role_that_cannot_happen_is_refused_rather_than_described(self):
        """Prose that guessed would put a wrong reason in front of the user."""
        with pytest.raises(ValueError):
            describe_roles(())

    def test_it_names_the_task_and_where_to_action_it(self):
        error = JournalHasAnchoredTasksError(DELETED, (make_blocking_task(),))

        assert "print the permit" in error.message
        # Title and id together, so a caller can name the link and follow it
        # without a second lookup.
        assert f'"Monday Planning" (journal {OTHER})' in error.message

    def test_it_steers_toward_cancelling_the_journal(self):
        """The specification asks the product to keep steering users toward
        cancelling a journal rather than deleting it, and this failure is
        exactly the moment to say so."""
        error = JournalHasAnchoredTasksError(DELETED, (make_blocking_task(),))

        assert "cancel" in error.message.lower()

    def test_it_names_every_blocker_in_order(self):
        blockers = tuple(
            make_blocking_task(task_id=i, text=f"task {i}") for i in (1, 2, 3)
        )

        error = JournalHasAnchoredTasksError(DELETED, blockers)

        assert error.blocking_tasks == blockers
        positions = [error.message.index(f"task {i}") for i in (1, 2, 3)]
        assert positions == sorted(positions)
        assert "3 tasks" in error.message

    def test_it_says_which_role_blocks(self):
        """Why a task blocks is part of the explanation: "you created this here"
        and "this is where it falls due" are different things to have to fix."""
        error = JournalHasAnchoredTasksError(
            DELETED,
            (
                make_blocking_task(text="due one", roles=("due",)),
                make_blocking_task(text="created one", roles=("creating",)),
                make_blocking_task(text="both", roles=("creating", "due")),
            ),
        )

        assert '"due one" (due in this journal)' in error.message
        assert '"created one" (created in this journal)' in error.message
        assert '"both" (created in and due in this journal)' in error.message


def make_journal(journal_id: int = DELETED) -> Journal:
    return Journal(
        id=journal_id,
        user_id="user123",
        title="Permit Meeting",
        content="content",
        event_date_range=EventDateRange(
            start=datetime(2024, 1, 1), end=datetime(2024, 1, 1)
        ),
    )


@pytest.fixture
def mock_journal_repo():
    repo = AsyncMock()
    repo.find_by_id.return_value = make_journal()
    return repo


@pytest.fixture
def mock_task_anchor_repo():
    repo = AsyncMock()
    repo.find_tasks_anchored_to_journal.return_value = []
    return repo


@pytest.fixture
def mock_event_publisher():
    return AsyncMock()


@pytest.fixture
def mock_transaction():
    """A transaction whose external-event-link query comes back empty."""
    transaction = AsyncMock()
    result = MagicMock()
    result.fetchall.return_value = []
    transaction.execute.return_value = result
    return transaction


@pytest.fixture
def journal_service(mock_journal_repo, mock_event_publisher, mock_task_anchor_repo):
    return JournalService(
        journal_repo=mock_journal_repo,
        event_publisher=mock_event_publisher,
        task_anchor_repo=mock_task_anchor_repo,
    )


def integrity_error() -> IntegrityError:
    """The violation PostgreSQL raises for the ON DELETE RESTRICT anchors."""
    return IntegrityError(
        "DELETE FROM journals WHERE id = 10",
        {},
        Exception(
            'update or delete on table "journals" violates foreign key constraint '
            '"tasks_due_journal_id_fkey" on table "tasks"'
        ),
    )


class TestDeleteGuard:
    """What ``delete_journal`` does with what the repository returns."""

    @pytest.mark.asyncio
    async def test_it_refuses_before_deleting_anything(
        self,
        journal_service,
        mock_journal_repo,
        mock_event_publisher,
        mock_task_anchor_repo,
        mock_transaction,
    ):
        mock_task_anchor_repo.find_tasks_anchored_to_journal.return_value = [
            make_blocking_task()
        ]

        with pytest.raises(JournalHasAnchoredTasksError) as exc_info:
            await journal_service.delete_journal(DELETED, mock_transaction)

        assert exc_info.value.blocking_tasks[0].text == "print the permit"
        mock_journal_repo.delete.assert_not_called()
        mock_event_publisher.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_it_asks_the_repository_once_for_the_journal_being_deleted(
        self, journal_service, mock_task_anchor_repo, mock_transaction
    ):
        """One query, not one per task — the tasks arrive already carrying their
        action journals."""
        await journal_service.delete_journal(DELETED, mock_transaction)

        mock_task_anchor_repo.find_tasks_anchored_to_journal.assert_awaited_once_with(
            DELETED
        )

    @pytest.mark.asyncio
    async def test_a_journal_nothing_is_anchored_to_still_deletes(
        self, journal_service, mock_journal_repo, mock_event_publisher, mock_transaction
    ):
        await journal_service.delete_journal(DELETED, mock_transaction)

        mock_journal_repo.delete.assert_awaited_once_with(DELETED)
        mock_event_publisher.publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_a_task_inserted_after_the_check_still_gets_the_explanation(
        self,
        journal_service,
        mock_journal_repo,
        mock_task_anchor_repo,
        mock_transaction,
    ):
        """The guard is check-then-act. Under READ COMMITTED a task anchored to
        this journal can commit in the window, and the foreign key then refuses
        the delete — so the violation is turned back into the same explanatory
        error rather than escaping as a 500."""
        mock_journal_repo.delete.side_effect = integrity_error()
        mock_task_anchor_repo.find_tasks_anchored_to_journal.side_effect = [
            [],
            [make_blocking_task()],
        ]

        with pytest.raises(JournalHasAnchoredTasksError) as exc_info:
            await journal_service.delete_journal(DELETED, mock_transaction)

        assert exc_info.value.blocking_tasks[0].text == "print the permit"

    @pytest.mark.asyncio
    async def test_a_blocker_that_vanishes_lets_the_delete_through(
        self,
        journal_service,
        mock_journal_repo,
        mock_event_publisher,
        mock_task_anchor_repo,
        mock_transaction,
    ):
        """The racing task can lose the race twice: anchored when the foreign
        key fires, gone by the time the guard looks. Nothing blocks the journal
        any more, so the caller gets the deletion they asked for rather than a
        500 about a row that no longer exists."""
        mock_journal_repo.delete.side_effect = [integrity_error(), None]
        mock_task_anchor_repo.find_tasks_anchored_to_journal.side_effect = [[], []]

        await journal_service.delete_journal(DELETED, mock_transaction)

        assert mock_journal_repo.delete.await_count == 2
        mock_event_publisher.publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_an_unrelated_violation_is_re_raised_untouched(
        self,
        journal_service,
        mock_journal_repo,
        mock_event_publisher,
        mock_task_anchor_repo,
        mock_transaction,
    ):
        """Only a violation the guard can *explain* becomes a domain error, and
        only one that has *gone* is retried. A constraint that keeps failing
        with no task in sight is neither: it surfaces as itself, and the journal
        is not reported deleted."""
        original = integrity_error()
        mock_journal_repo.delete.side_effect = original
        mock_task_anchor_repo.find_tasks_anchored_to_journal.side_effect = [[], []]

        with pytest.raises(IntegrityError) as exc_info:
            await journal_service.delete_journal(DELETED, mock_transaction)

        assert exc_info.value is original
        assert mock_journal_repo.delete.await_count == 2
        mock_event_publisher.publish.assert_not_called()
