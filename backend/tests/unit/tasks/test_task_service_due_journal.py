"""Unit tests for ``TaskService.update_task`` — a task's due journal.

The specification's *Setting and changing a list task's date*:

- "A due journal, when set, must be dated in the future."
- "Changing a date is a plain edit: no acknowledgement step, and it does not
  change status."
- "Whenever a due journal is replaced or cleared — by another journal, a due
  date, or nothing — the previous due journal becomes an intermediate journal."

and invariant 4 ("a due date **or** a due journal, never both").

A **list task**'s due journal is a plain edit: set, changed or cleared, its
status kept, the journal left retained as an intermediate journal, announced as
the link plus one ``TaskUpdated``.

A **journal-only task**'s due journal can be changed here too, under the
retarget's rules: it lands not done, a done task needs the acknowledgement, and
the journal cannot be cleared. A body that asks for two incompatible things — a
date and a journal, or a closed status and a retarget — is refused outright.

Repositories are mocked; the SQL and the lock order against real concurrent
writers are covered by the integration suites.
"""

import datetime
from unittest.mock import AsyncMock

import pytest
from core_shared.models.history import Provenance
from core_shared.models.journals import EventDateRange, Journal
from core_shared.models.tasks import (
    Task,
    TaskAnchorJournalNotFoundError,
    TaskDueJournalNotFutureError,
    TaskIcon,
    TaskReopenNotAcknowledgedError,
    TaskStatus,
    TaskValidationError,
)
from sqlalchemy.exc import IntegrityError

from app.core.tasks.models.events import DomainEvent
from app.core.tasks.services.task_service import TaskService
from app.shared.patch import UNSET, Unset
from tests.unit.tasks.task_doubles import (
    CREATING_JOURNAL_ID,
    DUE_JOURNAL_ID,
    NEW_DUE_JOURNAL_ID,
    ORIGINAL_TEXT,
    TASK_ID,
    UPDATED_TEXT,
    USER_ID,
    make_list_task,
    make_task,
    published_events,
)

pytestmark = pytest.mark.unit

SYDNEY = "Australia/Sydney"

# 2026-08-05 14:30 UTC is already 2026-08-06 00:30 in Sydney.
NOW = datetime.datetime(2026, 8, 5, 14, 30, tzinfo=datetime.UTC)
UTC_TODAY = datetime.date(2026, 8, 5)
SYDNEY_TODAY = datetime.date(2026, 8, 6)
LATER = datetime.date(2026, 9, 1)
FUTURE = datetime.datetime(2026, 9, 1, 9, 0, tzinfo=datetime.UTC)


def make_journal(journal_id: int, start: datetime.datetime = FUTURE) -> Journal:
    """An instantaneous journal of the acting user's."""
    return Journal(
        id=journal_id,
        user_id=USER_ID,
        title="A journal",
        content="content",
        event_date_range=EventDateRange(start=start, end=start),
    )


@pytest.fixture
def journals() -> dict[int, Journal]:
    """The user's journals, by id: both anchors' journals, in the future."""
    return {
        DUE_JOURNAL_ID: make_journal(DUE_JOURNAL_ID),
        NEW_DUE_JOURNAL_ID: make_journal(NEW_DUE_JOURNAL_ID),
    }


@pytest.fixture
def mock_journal_repo(journals: dict[int, Journal]) -> AsyncMock:
    """Answers the ordered locking read from ``journals``, owner-scoped."""
    repo = AsyncMock()

    async def lock(_user_id: str, journal_ids: list[int]) -> list[Journal]:
        return [journals[i] for i in journal_ids if i in journals]

    repo.find_and_lock_by_ids_for_user.side_effect = lock
    return repo


async def change(
    service: TaskService,
    transaction: AsyncMock,
    due_journal_id: int | None | Unset = UNSET,
    *,
    status: TaskStatus | None = None,
    text: str | None = None,
    flagged: bool | None = None,
    icon: TaskIcon | None | Unset = UNSET,
    due_date: datetime.date | None | Unset = UNSET,
    acknowledge_reopen: bool = False,
) -> Task:
    """Call ``update_task`` at ``NOW`` with whatever the case names."""
    return await service.update_task(
        user_id=USER_ID,
        task_id=TASK_ID,
        due_journal_id=due_journal_id,
        status=status,
        text=text,
        flagged=flagged,
        icon=icon,
        due_date=due_date,
        acknowledge_reopen=acknowledge_reopen,
        transaction=transaction,
        now=NOW,
    )


def event_types(publisher: AsyncMock) -> list[str]:
    return [event.event_type for event in published_events(publisher)]


def last_event(publisher: AsyncMock) -> DomainEvent:
    return published_events(publisher)[-1]


def assert_nothing_written(repo: AsyncMock, publisher: AsyncMock) -> None:
    repo.save.assert_not_awaited()
    repo.add_intermediate_journal.assert_not_awaited()
    publisher.publish.assert_not_awaited()


def given(repo: AsyncMock, task: Task) -> None:
    """The task both of the change's reads find."""
    repo.find_by_id_for_update.return_value = task


class TestAListTaskIsSetChangedAndCleared:
    @pytest.mark.asyncio
    async def test_an_undated_task_is_given_a_journal_with_nothing_to_retain(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_journal_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        given(mock_task_repo, make_list_task())

        result = await change(service, mock_transaction, NEW_DUE_JOURNAL_ID)

        assert result.due_journal_id == NEW_DUE_JOURNAL_ID
        assert mock_task_repo.save.await_args.args[0].due_journal_id == (
            NEW_DUE_JOURNAL_ID
        )
        mock_journal_repo.find_and_lock_by_ids_for_user.assert_awaited_once_with(
            USER_ID, [NEW_DUE_JOURNAL_ID]
        )
        mock_task_repo.add_intermediate_journal.assert_not_awaited()
        assert event_types(mock_event_publisher) == ["TaskUpdated"]
        assert last_event(mock_event_publisher).event_data["changed_fields"] == {
            "due_journal_id": (None, NEW_DUE_JOURNAL_ID)
        }

    @pytest.mark.asyncio
    async def test_a_changed_journal_retains_the_one_left_then_announces(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_journal_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        given(mock_task_repo, make_list_task(due_journal_id=DUE_JOURNAL_ID))

        await change(service, mock_transaction, NEW_DUE_JOURNAL_ID)

        mock_journal_repo.find_and_lock_by_ids_for_user.assert_awaited_once_with(
            USER_ID, [DUE_JOURNAL_ID, NEW_DUE_JOURNAL_ID]
        )
        mock_task_repo.add_intermediate_journal.assert_awaited_once_with(
            TASK_ID, DUE_JOURNAL_ID, USER_ID
        )
        events = published_events(mock_event_publisher)
        assert [event.event_type for event in events] == [
            "TaskJournalLinked",
            "TaskUpdated",
        ]
        assert events[0].event_data["journal_id"] == DUE_JOURNAL_ID
        assert events[0].event_data["origin"] == "retarget"
        assert events[1].event_data["changed_fields"] == {
            "due_journal_id": (DUE_JOURNAL_ID, NEW_DUE_JOURNAL_ID)
        }

    @pytest.mark.asyncio
    async def test_a_cleared_journal_is_retained_and_no_clock_is_read(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_journal_repo: AsyncMock,
        mock_settings_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        given(mock_task_repo, make_list_task(due_journal_id=DUE_JOURNAL_ID))

        result = await change(service, mock_transaction, None)

        assert result.due_journal_id is None
        mock_journal_repo.find_and_lock_by_ids_for_user.assert_awaited_once_with(
            USER_ID, [DUE_JOURNAL_ID]
        )
        mock_task_repo.add_intermediate_journal.assert_awaited_once_with(
            TASK_ID, DUE_JOURNAL_ID, USER_ID
        )
        assert event_types(mock_event_publisher) == ["TaskJournalLinked", "TaskUpdated"]
        assert last_event(mock_event_publisher).event_data["changed_fields"] == {
            "due_journal_id": (DUE_JOURNAL_ID, None)
        }
        mock_settings_repo.get_timezone.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_journal_already_linked_publishes_no_second_link(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The add is idempotent; no row written means no "linked" history row."""
        given(mock_task_repo, make_list_task(due_journal_id=DUE_JOURNAL_ID))
        mock_task_repo.add_intermediate_journal.return_value = False

        await change(service, mock_transaction, NEW_DUE_JOURNAL_ID)

        assert event_types(mock_event_publisher) == ["TaskUpdated"]


class TestAListTaskKeepsItsStatus:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", list(TaskStatus))
    @pytest.mark.parametrize("acknowledge_reopen", [False, True])
    async def test_in_every_status_with_or_without_the_acknowledgement(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
        status: TaskStatus,
        acknowledge_reopen: bool,
    ) -> None:
        given(mock_task_repo, make_list_task(status, due_journal_id=DUE_JOURNAL_ID))

        result = await change(
            service,
            mock_transaction,
            NEW_DUE_JOURNAL_ID,
            acknowledge_reopen=acknowledge_reopen,
        )

        assert result.status is status
        assert (
            "status"
            not in last_event(mock_event_publisher).event_data["changed_fields"]
        )

    @pytest.mark.asyncio
    async def test_a_dated_task_given_a_journal_loses_its_date_in_the_same_write(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        given(mock_task_repo, make_list_task(due_date=LATER))

        result = await change(service, mock_transaction, NEW_DUE_JOURNAL_ID)

        assert (result.due_journal_id, result.due_date) == (NEW_DUE_JOURNAL_ID, None)
        assert mock_task_repo.save.await_count == 1
        assert event_types(mock_event_publisher) == ["TaskUpdated"]
        assert last_event(mock_event_publisher).event_data["changed_fields"] == {
            "due_journal_id": (None, NEW_DUE_JOURNAL_ID),
            "due_date": ("2026-09-01", None),
        }

    @pytest.mark.asyncio
    async def test_a_status_and_a_journal_together_are_both_applied(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The status is the list task's own field, so there is no clash."""
        given(
            mock_task_repo,
            make_list_task(TaskStatus.DONE, due_journal_id=DUE_JOURNAL_ID),
        )

        result = await change(
            service, mock_transaction, NEW_DUE_JOURNAL_ID, status=TaskStatus.NOT_DONE
        )

        assert (result.status, result.due_journal_id) == (
            TaskStatus.NOT_DONE,
            NEW_DUE_JOURNAL_ID,
        )
        assert mock_task_repo.save.await_count == 1
        assert event_types(mock_event_publisher) == ["TaskJournalLinked", "TaskUpdated"]
        assert last_event(mock_event_publisher).event_data["changed_fields"] == {
            "status": ("done", "not_done"),
            "due_journal_id": (DUE_JOURNAL_ID, NEW_DUE_JOURNAL_ID),
        }


class TestAJournalOnlyTaskIsRetargeted:
    @pytest.mark.asyncio
    async def test_a_not_done_task_moves_as_a_retarget_does(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        given(mock_task_repo, make_task())

        result = await change(service, mock_transaction, NEW_DUE_JOURNAL_ID)

        assert (result.due_journal_id, result.status) == (
            NEW_DUE_JOURNAL_ID,
            TaskStatus.NOT_DONE,
        )
        assert result.creating_journal_id == CREATING_JOURNAL_ID
        mock_task_repo.add_intermediate_journal.assert_awaited_once_with(
            TASK_ID, DUE_JOURNAL_ID, USER_ID
        )
        assert event_types(mock_event_publisher) == [
            "TaskJournalLinked",
            "TaskDueJournalRetargeted",
        ]
        assert last_event(mock_event_publisher).event_data["changed_fields"] == {
            "due_journal_id": (DUE_JOURNAL_ID, NEW_DUE_JOURNAL_ID)
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "status", [None, TaskStatus.NOT_DONE], ids=["no-status", "not-done"]
    )
    async def test_a_cancelled_task_is_revived_with_one_status_change(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
        status: TaskStatus | None,
    ) -> None:
        """``not_done`` beside it agrees with the retarget, so it is no transition."""
        given(mock_task_repo, make_task(TaskStatus.CANCELLED))

        result = await change(
            service, mock_transaction, NEW_DUE_JOURNAL_ID, status=status
        )

        assert result.status is TaskStatus.NOT_DONE
        assert event_types(mock_event_publisher) == [
            "TaskJournalLinked",
            "TaskDueJournalRetargeted",
        ]
        assert last_event(mock_event_publisher).event_data["changed_fields"] == {
            "due_journal_id": (DUE_JOURNAL_ID, NEW_DUE_JOURNAL_ID),
            "status": ("cancelled", "not_done"),
        }

    @pytest.mark.asyncio
    async def test_a_done_task_needs_the_acknowledgement(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        given(mock_task_repo, make_task(TaskStatus.DONE))

        with pytest.raises(TaskReopenNotAcknowledgedError):
            await change(service, mock_transaction, NEW_DUE_JOURNAL_ID)

        assert_nothing_written(mock_task_repo, mock_event_publisher)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("acknowledge_reopen", "status"),
        [(True, None), (False, TaskStatus.NOT_DONE)],
        ids=["acknowledged", "status-not-done"],
    )
    async def test_a_done_task_is_reopened_when_the_body_asks_for_it(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
        acknowledge_reopen: bool,
        status: TaskStatus | None,
    ) -> None:
        """Naming ``not_done`` asks for the reopen in so many words."""
        given(mock_task_repo, make_task(TaskStatus.DONE))

        result = await change(
            service,
            mock_transaction,
            NEW_DUE_JOURNAL_ID,
            status=status,
            acknowledge_reopen=acknowledge_reopen,
        )

        assert result.status is TaskStatus.NOT_DONE
        assert event_types(mock_event_publisher) == [
            "TaskJournalLinked",
            "TaskDueJournalRetargeted",
        ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [TaskStatus.DONE, TaskStatus.CANCELLED])
    async def test_a_closed_status_beside_a_new_journal_clashes(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_journal_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
        status: TaskStatus,
    ) -> None:
        """A retarget lands the task not done, so the body has two answers."""
        given(mock_task_repo, make_task())

        with pytest.raises(TaskValidationError) as raised:
            await change(service, mock_transaction, NEW_DUE_JOURNAL_ID, status=status)

        assert raised.value.field == "status"
        mock_journal_repo.find_and_lock_by_ids_for_user.assert_not_awaited()
        mock_task_repo.find_by_id_for_update.assert_not_awaited()
        assert_nothing_written(mock_task_repo, mock_event_publisher)

    @pytest.mark.asyncio
    async def test_the_same_journal_with_a_status_is_a_plain_status_change(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_journal_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        given(mock_task_repo, make_task())

        result = await change(
            service, mock_transaction, DUE_JOURNAL_ID, status=TaskStatus.DONE
        )

        assert result.status is TaskStatus.DONE
        mock_journal_repo.find_and_lock_by_ids_for_user.assert_not_awaited()
        assert event_types(mock_event_publisher) == ["TaskUpdated"]
        assert last_event(mock_event_publisher).event_data["changed_fields"] == {
            "status": ("not_done", "done")
        }

    @pytest.mark.asyncio
    async def test_its_due_journal_cannot_be_cleared(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_journal_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        given(mock_task_repo, make_task())

        with pytest.raises(TaskValidationError) as raised:
            await change(service, mock_transaction, None)

        assert raised.value.field == "due_journal_id"
        mock_journal_repo.find_and_lock_by_ids_for_user.assert_not_awaited()
        assert_nothing_written(mock_task_repo, mock_event_publisher)

    @pytest.mark.asyncio
    async def test_a_reword_beside_it_is_announced_on_its_own(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        given(mock_task_repo, make_task(TaskStatus.CANCELLED))

        result = await change(
            service, mock_transaction, NEW_DUE_JOURNAL_ID, text=UPDATED_TEXT
        )

        assert (result.text, result.due_journal_id) == (
            UPDATED_TEXT,
            NEW_DUE_JOURNAL_ID,
        )
        assert mock_task_repo.save.await_count == 1
        assert event_types(mock_event_publisher) == [
            "TaskJournalLinked",
            "TaskDueJournalRetargeted",
            "TaskUpdated",
        ]
        assert last_event(mock_event_publisher).event_data["changed_fields"] == {
            "text": (ORIGINAL_TEXT, UPDATED_TEXT)
        }


class TestNoOps:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "task",
        [make_list_task(due_journal_id=DUE_JOURNAL_ID), make_task()],
        ids=["list-task", "journal-only"],
    )
    async def test_resending_the_journal_it_has_writes_and_locks_nothing(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_journal_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
        task: Task,
    ) -> None:
        given(mock_task_repo, task)

        result = await change(service, mock_transaction, DUE_JOURNAL_ID)

        assert result == task
        mock_journal_repo.find_and_lock_by_ids_for_user.assert_not_awaited()
        assert_nothing_written(mock_task_repo, mock_event_publisher)

    @pytest.mark.asyncio
    async def test_clearing_a_journal_a_list_task_does_not_have(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_journal_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        given(mock_task_repo, make_list_task())

        await change(service, mock_transaction, None)

        mock_journal_repo.find_and_lock_by_ids_for_user.assert_not_awaited()
        assert_nothing_written(mock_task_repo, mock_event_publisher)


class TestRefusals:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("timezone", "start", "journal_day", "today"),
        [
            (
                SYDNEY,
                datetime.datetime(2026, 8, 6, 9, 0, tzinfo=datetime.UTC),
                SYDNEY_TODAY,
                SYDNEY_TODAY,
            ),
            (
                None,
                datetime.datetime(2026, 8, 5, 9, 0, tzinfo=datetime.UTC),
                UTC_TODAY,
                UTC_TODAY,
            ),
        ],
        ids=["sydney", "utc-fallback"],
    )
    async def test_a_journal_dated_today_is_not_future(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_settings_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
        journals: dict[int, Journal],
        timezone: str | None,
        start: datetime.datetime,
        journal_day: datetime.date,
        today: datetime.date,
    ) -> None:
        """ "Today" is the user's own day, as for every date rule."""
        mock_settings_repo.get_timezone.return_value = timezone
        journals[NEW_DUE_JOURNAL_ID] = make_journal(NEW_DUE_JOURNAL_ID, start)
        given(mock_task_repo, make_list_task(TaskStatus.DONE))

        with pytest.raises(TaskDueJournalNotFutureError) as raised:
            await change(service, mock_transaction, NEW_DUE_JOURNAL_ID)

        assert (raised.value.journal_date, raised.value.today) == (journal_day, today)
        assert_nothing_written(mock_task_repo, mock_event_publisher)

    @pytest.mark.asyncio
    async def test_an_unknown_or_foreign_journal_is_not_found(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
        journals: dict[int, Journal],
    ) -> None:
        """Owner-scoped: another user's journal is absent, exactly like none."""
        del journals[NEW_DUE_JOURNAL_ID]
        given(mock_task_repo, make_list_task(due_journal_id=DUE_JOURNAL_ID))

        with pytest.raises(TaskAnchorJournalNotFoundError) as raised:
            await change(service, mock_transaction, NEW_DUE_JOURNAL_ID)

        assert (raised.value.anchor, raised.value.journal_id) == (
            "due",
            NEW_DUE_JOURNAL_ID,
        )
        assert_nothing_written(mock_task_repo, mock_event_publisher)

    @pytest.mark.asyncio
    async def test_a_date_and_a_journal_together_are_refused_before_any_read(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Invariant 4: the body asks for both anchors, so it has no answer."""
        with pytest.raises(TaskValidationError) as raised:
            await change(service, mock_transaction, NEW_DUE_JOURNAL_ID, due_date=LATER)

        assert raised.value.field == "due_date"
        mock_task_repo.find_by_id.assert_not_awaited()
        mock_task_repo.find_by_id_for_update.assert_not_awaited()
        assert_nothing_written(mock_task_repo, mock_event_publisher)

    @pytest.mark.asyncio
    async def test_a_cleared_date_beside_a_journal_is_one_answer(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        given(mock_task_repo, make_list_task(due_date=LATER))

        result = await change(
            service, mock_transaction, NEW_DUE_JOURNAL_ID, due_date=None
        )

        assert (result.due_journal_id, result.due_date) == (NEW_DUE_JOURNAL_ID, None)


class TestLocksAndReads:
    @pytest.mark.asyncio
    async def test_the_journals_are_locked_before_the_task(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
        journals: dict[int, Journal],
    ) -> None:
        """The order a merge and a journal delete take the same rows in."""
        order: list[str] = []
        task = make_list_task(due_journal_id=DUE_JOURNAL_ID)

        async def lock_journals(_user_id: str, ids: list[int]) -> list[Journal]:
            order.append("journals")
            return [journals[i] for i in ids]

        async def lock_task(*_: object) -> Task:
            order.append("task")
            return task

        mock_task_repo.find_by_id.side_effect = None
        mock_task_repo.find_by_id.return_value = task
        mock_journal_repo.find_and_lock_by_ids_for_user.side_effect = lock_journals
        mock_task_repo.find_by_id_for_update.side_effect = lock_task

        await change(service, mock_transaction, NEW_DUE_JOURNAL_ID)

        assert order == ["journals", "task"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "edit",
        [
            {"text": UPDATED_TEXT},
            {"flagged": True},
            {"icon": TaskIcon.TENT},
            {"status": TaskStatus.DONE},
            {"due_date": None},
        ],
        ids=["text", "flag", "icon", "status", "cleared-date"],
    )
    async def test_an_edit_naming_no_journal_takes_no_peek_and_no_journal_lock(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
        edit: dict[str, object],
    ) -> None:
        given(mock_task_repo, make_list_task(due_journal_id=DUE_JOURNAL_ID))

        await service.update_task(
            user_id=USER_ID,
            task_id=TASK_ID,
            transaction=mock_transaction,
            now=NOW,
            **edit,  # type: ignore[arg-type]
        )

        mock_task_repo.find_by_id.assert_not_awaited()
        mock_journal_repo.find_and_lock_by_ids_for_user.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_date_on_an_undated_task_locks_no_journal(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        given(mock_task_repo, make_list_task())

        await change(service, mock_transaction, due_date=LATER)

        mock_journal_repo.find_and_lock_by_ids_for_user.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_task_detached_while_it_waited_gains_the_journal(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """A journal delete committed between the peek and the lock."""
        mock_task_repo.find_by_id.side_effect = None
        mock_task_repo.find_by_id.return_value = make_list_task(
            due_journal_id=DUE_JOURNAL_ID
        )
        mock_task_repo.find_by_id_for_update.return_value = make_list_task()

        result = await change(service, mock_transaction, NEW_DUE_JOURNAL_ID)

        assert result.due_journal_id == NEW_DUE_JOURNAL_ID
        mock_task_repo.add_intermediate_journal.assert_not_awaited()
        assert last_event(mock_event_publisher).event_data["changed_fields"] == {
            "due_journal_id": (None, NEW_DUE_JOURNAL_ID)
        }

    @pytest.mark.asyncio
    async def test_a_task_moved_onto_a_list_while_it_waited_gets_list_rules(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Decided from the locked read: a done list task stays done, no ack."""
        mock_task_repo.find_by_id.side_effect = None
        mock_task_repo.find_by_id.return_value = make_task(TaskStatus.DONE)
        mock_task_repo.find_by_id_for_update.return_value = make_list_task(
            TaskStatus.DONE,
            creating_journal_id=CREATING_JOURNAL_ID,
            due_journal_id=DUE_JOURNAL_ID,
        )

        result = await change(service, mock_transaction, NEW_DUE_JOURNAL_ID)

        assert result.status is TaskStatus.DONE
        assert event_types(mock_event_publisher) == ["TaskJournalLinked", "TaskUpdated"]

    @pytest.mark.asyncio
    async def test_a_resend_that_became_a_change_while_it_waited_is_applied(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_journal_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The peek saw the journal asked for; a write moved it before the lock.

        The request is not dropped: the journal it names is locked after the
        task row — the stated residual window — and the task moves back to it.
        """
        mock_task_repo.find_by_id.side_effect = None
        mock_task_repo.find_by_id.return_value = make_list_task(
            due_journal_id=DUE_JOURNAL_ID
        )
        mock_task_repo.find_by_id_for_update.return_value = make_list_task(
            due_journal_id=NEW_DUE_JOURNAL_ID
        )

        result = await change(service, mock_transaction, DUE_JOURNAL_ID)

        assert result.due_journal_id == DUE_JOURNAL_ID
        mock_journal_repo.find_and_lock_by_ids_for_user.assert_awaited_once_with(
            USER_ID, [DUE_JOURNAL_ID]
        )
        mock_task_repo.add_intermediate_journal.assert_awaited_once_with(
            TASK_ID, NEW_DUE_JOURNAL_ID, USER_ID
        )
        assert last_event(mock_event_publisher).event_data["changed_fields"] == {
            "due_journal_id": (NEW_DUE_JOURNAL_ID, DUE_JOURNAL_ID)
        }

    @pytest.mark.asyncio
    async def test_a_clear_of_a_journal_gained_while_it_waited_is_applied(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        mock_task_repo.find_by_id.side_effect = None
        mock_task_repo.find_by_id.return_value = make_list_task()
        mock_task_repo.find_by_id_for_update.return_value = make_list_task(
            due_journal_id=DUE_JOURNAL_ID
        )

        result = await change(service, mock_transaction, None)

        assert result.due_journal_id is None
        mock_task_repo.add_intermediate_journal.assert_awaited_once_with(
            TASK_ID, DUE_JOURNAL_ID, USER_ID
        )
        assert last_event(mock_event_publisher).event_data["changed_fields"] == {
            "due_journal_id": (DUE_JOURNAL_ID, None)
        }

    @pytest.mark.asyncio
    async def test_a_journal_vanishing_under_the_write_is_not_found(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The foreign key's violation is mapped, not surfaced as a 500."""
        given(mock_task_repo, make_list_task())
        mock_task_repo.save.side_effect = IntegrityError(
            "UPDATE tasks SET due_journal_id = $1 WHERE id = $2",
            {},
            Exception(
                'insert or update on table "tasks" violates foreign key '
                'constraint "tasks_due_journal_id_fkey"'
            ),
        )

        with pytest.raises(TaskAnchorJournalNotFoundError) as raised:
            await change(service, mock_transaction, NEW_DUE_JOURNAL_ID)

        assert raised.value.journal_id == NEW_DUE_JOURNAL_ID


class TestTheTrailWrapper:
    @pytest.mark.asyncio
    async def test_forwards_the_journal_the_acknowledgement_and_the_provenance(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        given(mock_task_repo, make_task(TaskStatus.DONE))
        mock_task_repo.list_intermediate_journal_ids.return_value = [DUE_JOURNAL_ID]

        updated, trail = await service.update_task_with_trail(
            user_id=USER_ID,
            task_id=TASK_ID,
            due_journal_id=NEW_DUE_JOURNAL_ID,
            acknowledge_reopen=True,
            transaction=mock_transaction,
            source=Provenance.MCP,
            changed_by="mcp",
            now=NOW,
        )

        assert (updated.due_journal_id, updated.status) == (
            NEW_DUE_JOURNAL_ID,
            TaskStatus.NOT_DONE,
        )
        assert trail == [DUE_JOURNAL_ID]
        data = last_event(mock_event_publisher).event_data
        assert (data["source"], data["changed_by"]) == ("mcp", "mcp")
