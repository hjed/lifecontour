"""Unit tests for ``TaskService.update_task`` — a list task's due date.

The specification's *Setting and changing a list task's date*:

- "A due date, when set, must be today or later."
- "Changing a date is a plain edit: no acknowledgement step, and it does not
  change status. A done or cancelled list task is reopened by changing its
  status, not its date."

and its invariants 4 ("a due date **or** a due journal, never both") and 5 ("a
due date may only be set on a task that is on a list").

What is under test:

- set, change and clear, each one save and one ``TaskUpdated`` carrying the
  ``(old, new)`` pair as ISO strings, with the status untouched in every status;
- "today" is the user's, read once; a clear or an unchanged date reads no clock;
- a resent past date on an overdue task is a no-op, not a refusal;
- the entity's invariants refuse a journal-only task and one due in a journal;
- the date travels with text, flag and icon as one write and one event.

Repositories are mocked; the SQL is covered by the integration suites.
"""

import datetime
from unittest.mock import AsyncMock

import pytest
from core_shared.models.history import Provenance
from core_shared.models.tasks import (
    Task,
    TaskDueDateInPastError,
    TaskIcon,
    TaskNotFoundError,
    TaskStatus,
    TaskValidationError,
)

from app.core.tasks.models.events import TaskUpdated
from app.core.tasks.services.task_service import TaskService
from app.shared.patch import UNSET, Unset
from tests.unit.tasks.task_doubles import (
    DUE_JOURNAL_ID,
    ORIGINAL_TEXT,
    TASK_ID,
    TASK_LIST_ID,
    UPDATED_TEXT,
    USER_ID,
    make_list_task,
    make_task,
    published_events,
)

pytestmark = pytest.mark.unit

SYDNEY = "Australia/Sydney"

# 2026-08-05 14:30 UTC is already 2026-08-06 00:30 in Sydney, so "today" depends
# on the zone: the instant a UTC-today rule would get wrong.
NOW = datetime.datetime(2026, 8, 5, 14, 30, tzinfo=datetime.UTC)
UTC_TODAY = datetime.date(2026, 8, 5)
SYDNEY_TODAY = datetime.date(2026, 8, 6)
LATER = datetime.date(2026, 9, 1)
LATER_STILL = datetime.date(2026, 9, 15)
LONG_AGO = datetime.date(2026, 7, 1)


def only_update(publisher: AsyncMock) -> TaskUpdated:
    """The one event published, which must be a ``TaskUpdated``."""
    events = published_events(publisher)
    assert len(events) == 1
    (event,) = events
    assert isinstance(event, TaskUpdated)
    return event


def changed_fields(publisher: AsyncMock) -> dict[str, object]:
    fields = only_update(publisher).event_data["changed_fields"]
    assert isinstance(fields, dict)
    return fields


def assert_nothing_written(repo: AsyncMock, publisher: AsyncMock) -> None:
    repo.save.assert_not_awaited()
    publisher.publish.assert_not_awaited()


async def set_due_date(
    service: TaskService,
    transaction: AsyncMock,
    due_date: datetime.date | None,
    *,
    text: str | None = None,
    flagged: bool | None = None,
    icon: TaskIcon | None | Unset = UNSET,
) -> Task:
    """Change the due date at ``NOW``, with any other fields the case names."""
    return await service.update_task(
        user_id=USER_ID,
        task_id=TASK_ID,
        due_date=due_date,
        text=text,
        flagged=flagged,
        icon=icon,
        transaction=transaction,
        now=NOW,
    )


class TestSetChangeAndClear:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("before", "after", "pair"),
        [
            (None, LATER, (None, "2026-09-01")),
            (LATER, LATER_STILL, ("2026-09-01", "2026-09-15")),
            (LATER, None, ("2026-09-01", None)),
        ],
        ids=["set", "changed", "cleared"],
    )
    async def test_the_date_is_saved_and_announced_as_iso_strings(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
        before: datetime.date | None,
        after: datetime.date | None,
        pair: tuple[str | None, str | None],
    ) -> None:
        mock_task_repo.find_by_id_for_update.return_value = make_list_task(
            due_date=before
        )

        result = await set_due_date(service, mock_transaction, after)

        assert mock_task_repo.save.await_count == 1
        assert mock_task_repo.save.await_args.args[0].due_date == after
        assert result.due_date == after
        fields = changed_fields(mock_event_publisher)
        assert fields == {"due_date": pair}
        # Plain strings on the wire, never ``date`` objects the outbox's JSON
        # encoding would refuse.
        due_pair = fields["due_date"]
        assert isinstance(due_pair, tuple)
        assert tuple(map(type, due_pair)) == tuple(map(type, pair))

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", list(TaskStatus))
    async def test_the_status_is_kept_in_every_status(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
        status: TaskStatus,
    ) -> None:
        """A plain edit: a done or cancelled task is re-dated, not reopened."""
        mock_task_repo.find_by_id_for_update.return_value = make_list_task(status)

        await set_due_date(service, mock_transaction, LATER)

        saved = mock_task_repo.save.await_args.args[0]
        assert saved.status == status
        assert (saved.task_list_id, saved.position) == (TASK_LIST_ID, 0)
        assert saved.text == ORIGINAL_TEXT
        assert set(changed_fields(mock_event_publisher)) == {"due_date"}

    @pytest.mark.asyncio
    async def test_no_journal_is_read_or_locked(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        mock_task_repo.find_by_id_for_update.return_value = make_list_task()

        await set_due_date(service, mock_transaction, LATER)

        assert mock_journal_repo.mock_calls == []


class TestTodayIsTheUsers:
    @pytest.mark.asyncio
    async def test_today_in_the_users_timezone_is_accepted(
        self,
        service: TaskService,
        mock_settings_repo: AsyncMock,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        mock_settings_repo.get_timezone.return_value = SYDNEY
        mock_task_repo.find_by_id_for_update.return_value = make_list_task()

        result = await set_due_date(service, mock_transaction, SYDNEY_TODAY)

        assert result.due_date == SYDNEY_TODAY

    @pytest.mark.asyncio
    async def test_yesterday_in_the_users_timezone_is_refused_naming_both_days(
        self,
        service: TaskService,
        mock_settings_repo: AsyncMock,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """UTC's today is already yesterday in Sydney at this instant."""
        mock_settings_repo.get_timezone.return_value = SYDNEY
        mock_task_repo.find_by_id_for_update.return_value = make_list_task()

        with pytest.raises(TaskDueDateInPastError) as raised:
            await set_due_date(service, mock_transaction, UTC_TODAY)

        assert raised.value.due_date == UTC_TODAY
        assert raised.value.today == SYDNEY_TODAY
        assert_nothing_written(mock_task_repo, mock_event_publisher)

    @pytest.mark.asyncio
    async def test_without_a_timezone_today_is_utcs(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        mock_task_repo.find_by_id_for_update.return_value = make_list_task()

        result = await set_due_date(service, mock_transaction, UTC_TODAY)

        assert result.due_date == UTC_TODAY

    @pytest.mark.asyncio
    async def test_clearing_reads_no_timezone(
        self,
        service: TaskService,
        mock_settings_repo: AsyncMock,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Clearing a passed date is how an overdue task is un-dated."""
        mock_task_repo.find_by_id_for_update.return_value = make_list_task(
            due_date=LONG_AGO
        )

        await set_due_date(service, mock_transaction, None)

        mock_settings_repo.get_timezone.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_absent_date_reads_no_timezone(
        self,
        service: TaskService,
        mock_settings_repo: AsyncMock,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        mock_task_repo.find_by_id_for_update.return_value = make_list_task(
            due_date=LATER
        )

        result = await service.update_task(
            user_id=USER_ID, task_id=TASK_ID, flagged=True, transaction=mock_transaction
        )

        assert result.due_date == LATER
        mock_settings_repo.get_timezone.assert_not_awaited()


class TestNoOps:
    @pytest.mark.asyncio
    async def test_resending_an_overdue_tasks_past_date_writes_nothing(
        self,
        service: TaskService,
        mock_settings_repo: AsyncMock,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The rule is about *setting* a date; an unchanged one is not set."""
        stored = make_list_task(due_date=LONG_AGO)
        mock_task_repo.find_by_id_for_update.return_value = stored

        result = await set_due_date(service, mock_transaction, LONG_AGO)

        assert result is stored
        assert_nothing_written(mock_task_repo, mock_event_publisher)
        mock_settings_repo.get_timezone.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_clearing_an_undated_task_writes_nothing(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        mock_task_repo.find_by_id_for_update.return_value = make_list_task()

        await set_due_date(service, mock_transaction, None)

        assert_nothing_written(mock_task_repo, mock_event_publisher)


class TestTheInvariants:
    @pytest.mark.asyncio
    async def test_a_journal_only_task_takes_no_due_date(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Invariant 5: a due date only on a task that is on a list."""
        mock_task_repo.find_by_id_for_update.return_value = make_task()

        with pytest.raises(TaskValidationError) as raised:
            await set_due_date(service, mock_transaction, LATER)

        assert raised.value.field == "due_date"
        assert_nothing_written(mock_task_repo, mock_event_publisher)

    @pytest.mark.asyncio
    async def test_a_task_due_in_a_journal_takes_no_due_date(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Invariant 4. Replacing the journal with a date is Phase 23's."""
        mock_task_repo.find_by_id_for_update.return_value = make_list_task(
            due_journal_id=DUE_JOURNAL_ID
        )

        with pytest.raises(TaskValidationError) as raised:
            await set_due_date(service, mock_transaction, LATER)

        assert raised.value.field == "due_date"
        assert_nothing_written(mock_task_repo, mock_event_publisher)

    @pytest.mark.asyncio
    async def test_the_invariant_is_checked_before_the_clock(
        self,
        service: TaskService,
        mock_settings_repo: AsyncMock,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """A date that could never be set is wrong outright, whatever the day."""
        mock_task_repo.find_by_id_for_update.return_value = make_task()

        with pytest.raises(TaskValidationError):
            await set_due_date(service, mock_transaction, LONG_AGO)

        mock_settings_repo.get_timezone.assert_not_awaited()


class TestOneWriteOneEvent:
    @pytest.mark.asyncio
    async def test_the_date_with_text_flag_and_icon_is_one_save_and_one_event(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        mock_task_repo.find_by_id_for_update.return_value = make_list_task()

        await set_due_date(
            service,
            mock_transaction,
            LATER,
            text=UPDATED_TEXT,
            flagged=True,
            icon=TaskIcon.TENT,
        )

        assert mock_task_repo.save.await_count == 1
        assert changed_fields(mock_event_publisher) == {
            "text": (ORIGINAL_TEXT, UPDATED_TEXT),
            "flagged": (False, True),
            "icon": (None, "tent"),
            "due_date": (None, "2026-09-01"),
        }

    @pytest.mark.asyncio
    async def test_a_refused_date_refuses_the_whole_change(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        mock_task_repo.find_by_id_for_update.return_value = make_list_task()

        with pytest.raises(TaskDueDateInPastError):
            await set_due_date(service, mock_transaction, LONG_AGO, flagged=True)

        assert_nothing_written(mock_task_repo, mock_event_publisher)


class TestNotFoundAndProvenance:
    @pytest.mark.asyncio
    async def test_an_unknown_or_foreign_task_is_not_found(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        mock_task_repo.find_by_id_for_update.return_value = None

        with pytest.raises(TaskNotFoundError):
            await set_due_date(service, mock_transaction, LATER)

        assert_nothing_written(mock_task_repo, mock_event_publisher)

    @pytest.mark.asyncio
    async def test_the_trail_wrapper_forwards_the_date_and_the_provenance(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        mock_task_repo.find_by_id_for_update.return_value = make_list_task()
        mock_task_repo.list_intermediate_journal_ids.return_value = []

        updated, _trail = await service.update_task_with_trail(
            user_id=USER_ID,
            task_id=TASK_ID,
            due_date=LATER,
            transaction=mock_transaction,
            source=Provenance.MCP,
            changed_by="mcp",
            now=NOW,
        )

        assert updated.due_date == LATER
        data = only_update(mock_event_publisher).event_data
        assert data["changed_fields"] == {"due_date": (None, "2026-09-01")}
        assert (data["source"], data["changed_by"]) == ("mcp", "mcp")
