"""Unit tests for ``TaskService.update_task`` — a task's flag and icon.

The specification's *Flag and icon*: the flag is "a single on/off marker",
the icon "an optional icon chosen from a fixed set", and "both apply to every
task, including journal-only tasks, and are editable wherever a task can be
edited". The flag "does not reorder a list".

What is under test:

- the flag is set and cleared, and the icon set, changed and cleared, each
  carried on the one ``TaskUpdated`` as an ``(old, new)`` pair;
- journal-only tasks are included, in every status — a lapsed task included,
  because no journal is read;
- the flag never moves the task: list, position, anchors and status are carried
  through unchanged;
- a resent value is a no-op, and flag, icon and text in one call are one write
  and one event;
- an absent icon is "leave it", which is not the same as ``None`` ("clear it").

Repositories are mocked; the SQL is covered by the integration suites.
"""

from unittest.mock import AsyncMock

import pytest
from core_shared.models.history import Provenance
from core_shared.models.tasks import (
    Task,
    TaskIcon,
    TaskNotFoundError,
    TaskStatus,
)

from app.core.tasks.models.events import TaskUpdated
from app.core.tasks.services.task_service import TaskService
from tests.unit.tasks.task_doubles import (
    CREATING_JOURNAL_ID,
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


def with_marks(task: Task, *, flagged: bool, icon: TaskIcon | None) -> Task:
    """``task`` as stored with the given flag and icon."""
    return Task(
        id=task.id,
        user_id=task.user_id,
        text=task.text,
        task_list_id=task.task_list_id,
        position=task.position,
        creating_journal_id=task.creating_journal_id,
        due_journal_id=task.due_journal_id,
        due_date=task.due_date,
        status=task.status,
        flagged=flagged,
        icon=icon,
    )


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


class TestTheFlag:
    @pytest.mark.asyncio
    async def test_flagging_a_journal_only_task_saves_and_announces_it(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        mock_task_repo.find_by_id_for_update.return_value = make_task()

        result = await service.update_task(
            user_id=USER_ID, task_id=TASK_ID, flagged=True, transaction=mock_transaction
        )

        assert mock_task_repo.save.await_args.args[0].flagged is True
        assert result.flagged is True
        assert changed_fields(mock_event_publisher) == {"flagged": (False, True)}

    @pytest.mark.asyncio
    async def test_unflagging_is_the_reverse_pair(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        mock_task_repo.find_by_id_for_update.return_value = with_marks(
            make_task(), flagged=True, icon=None
        )

        result = await service.update_task(
            user_id=USER_ID,
            task_id=TASK_ID,
            flagged=False,
            transaction=mock_transaction,
        )

        assert result.flagged is False
        assert changed_fields(mock_event_publisher) == {"flagged": (True, False)}


class TestTheIcon:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("before", "after", "pair"),
        [
            (None, TaskIcon.SHOPPING_CART, (None, "shopping-cart")),
            (TaskIcon.SHOPPING_CART, TaskIcon.TENT, ("shopping-cart", "tent")),
            (TaskIcon.SHOPPING_CART, None, ("shopping-cart", None)),
        ],
        ids=["set", "changed", "cleared"],
    )
    async def test_the_icon_change_is_saved_and_announced_by_its_key(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
        before: TaskIcon | None,
        after: TaskIcon | None,
        pair: tuple[str | None, str | None],
    ) -> None:
        """The pair carries the plain key, as ``TaskListUpdated`` does."""
        mock_task_repo.find_by_id_for_update.return_value = with_marks(
            make_task(), flagged=False, icon=before
        )

        result = await service.update_task(
            user_id=USER_ID, task_id=TASK_ID, icon=after, transaction=mock_transaction
        )

        assert mock_task_repo.save.await_args.args[0].icon == after
        assert result.icon == after
        fields = changed_fields(mock_event_publisher)
        assert fields == {"icon": pair}
        # A plain ``str``, not the member: ``TaskIcon`` is a ``StrEnum`` and
        # would compare equal either way.
        icon_pair = fields["icon"]
        assert isinstance(icon_pair, tuple)
        assert tuple(map(type, icon_pair)) == tuple(map(type, pair))

    @pytest.mark.asyncio
    async def test_an_absent_icon_is_left_alone_not_cleared(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        mock_task_repo.find_by_id_for_update.return_value = with_marks(
            make_task(), flagged=False, icon=TaskIcon.TENT
        )

        result = await service.update_task(
            user_id=USER_ID, task_id=TASK_ID, flagged=True, transaction=mock_transaction
        )

        assert result.icon == TaskIcon.TENT
        assert changed_fields(mock_event_publisher) == {"flagged": (False, True)}


class TestOneWriteOneEvent:
    @pytest.mark.asyncio
    async def test_flag_icon_and_text_together_are_one_save_and_one_event(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        mock_task_repo.find_by_id_for_update.return_value = make_task()

        await service.update_task(
            user_id=USER_ID,
            task_id=TASK_ID,
            text=UPDATED_TEXT,
            flagged=True,
            icon=TaskIcon.TENT,
            transaction=mock_transaction,
        )

        assert mock_task_repo.save.await_count == 1
        assert changed_fields(mock_event_publisher) == {
            "text": (ORIGINAL_TEXT, UPDATED_TEXT),
            "flagged": (False, True),
            "icon": (None, "tent"),
        }

    @pytest.mark.asyncio
    async def test_resending_the_flag_and_icon_it_has_writes_nothing(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        stored = with_marks(make_task(), flagged=True, icon=TaskIcon.TENT)
        mock_task_repo.find_by_id_for_update.return_value = stored

        result = await service.update_task(
            user_id=USER_ID,
            task_id=TASK_ID,
            flagged=True,
            icon=TaskIcon.TENT,
            transaction=mock_transaction,
        )

        assert result is stored
        mock_task_repo.save.assert_not_awaited()
        mock_event_publisher.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_clearing_an_icon_the_task_does_not_have_writes_nothing(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        mock_task_repo.find_by_id_for_update.return_value = make_task()

        await service.update_task(
            user_id=USER_ID, task_id=TASK_ID, icon=None, transaction=mock_transaction
        )

        mock_task_repo.save.assert_not_awaited()
        mock_event_publisher.publish.assert_not_awaited()


class TestAnyTaskInAnyStatus:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", list(TaskStatus))
    async def test_a_journal_only_task_takes_both_and_keeps_everything_else(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
        status: TaskStatus,
    ) -> None:
        """No journal is read, so a lapsed task is as editable as any other."""
        mock_task_repo.find_by_id_for_update.return_value = make_task(status)

        await service.update_task(
            user_id=USER_ID,
            task_id=TASK_ID,
            flagged=True,
            icon=TaskIcon.STAR,
            transaction=mock_transaction,
        )

        saved = mock_task_repo.save.await_args.args[0]
        assert (saved.flagged, saved.icon) == (True, TaskIcon.STAR)
        assert saved.status == status
        assert saved.text == ORIGINAL_TEXT
        assert (saved.creating_journal_id, saved.due_journal_id) == (
            CREATING_JOURNAL_ID,
            DUE_JOURNAL_ID,
        )
        assert saved.task_list_id is None
        assert mock_journal_repo.mock_calls == []

    @pytest.mark.asyncio
    async def test_flagging_a_list_task_does_not_move_it(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The flag "does not reorder a list"."""
        mock_task_repo.find_by_id_for_update.return_value = make_list_task()

        await service.update_task(
            user_id=USER_ID, task_id=TASK_ID, flagged=True, transaction=mock_transaction
        )

        saved = mock_task_repo.save.await_args.args[0]
        assert (saved.task_list_id, saved.position) == (TASK_LIST_ID, 0)
        assert saved.flagged is True


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
            await service.update_task(
                user_id=USER_ID,
                task_id=TASK_ID,
                flagged=True,
                transaction=mock_transaction,
            )

        mock_task_repo.save.assert_not_awaited()
        mock_event_publisher.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_trail_wrapper_forwards_the_marks_and_the_provenance(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        mock_task_repo.find_by_id_for_update.return_value = make_task()
        mock_task_repo.list_intermediate_journal_ids.return_value = []

        updated, _trail = await service.update_task_with_trail(
            user_id=USER_ID,
            task_id=TASK_ID,
            flagged=True,
            icon=TaskIcon.TENT,
            transaction=mock_transaction,
            source=Provenance.MCP,
            changed_by="mcp",
        )

        assert (updated.flagged, updated.icon) == (True, TaskIcon.TENT)
        data = only_update(mock_event_publisher).event_data
        assert data["changed_fields"] == {
            "flagged": (False, True),
            "icon": (None, "tent"),
        }
        assert (data["source"], data["changed_by"]) == ("mcp", "mcp")
