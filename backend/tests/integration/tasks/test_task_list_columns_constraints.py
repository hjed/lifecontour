"""The list columns on ``tasks`` and the core invariants the table enforces.

Migration 0146 lets a task live on a list and makes both journal anchors
nullable. The CHECKs it adds are what keep that relaxation from weakening
journal-only tasks (spec *Core invariants*):

- ``ck_tasks_journal_only_has_both_anchors`` — invariants 1 and 2: a task with
  no list must hold both a creating and a due journal (which implies it has a
  list or a due journal);
- ``ck_tasks_due_date_only_on_list_without_due_journal`` — invariants 4 and 5:
  a due date only on a list task, and never beside a due journal;
- ``ck_tasks_position_only_on_list`` / ``ck_tasks_position_non_negative`` — a
  position exactly when the task is on a list, and never negative.

Each refused row breaks exactly one of these, so each test names the constraint
that refused it. Rows are inserted directly — the entity and repository learn
these columns in later phases.

Each expected violation gets its own test: a failed statement poisons the
surrounding transaction, so the test must end there and let the fixture roll back.
"""

from datetime import date
from typing import Any

import pytest
import pytest_asyncio
from core_shared.models.tasks import TaskIcon
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.tasks.task_seeding import USER_ID

# Statements are built once at module level so that a ``pytest.raises`` block
# wraps only the execution under test, never the construction of its SQL.
_INSERT_TASK = text(
    """
    INSERT INTO tasks (
        user_id, text, task_list_id, position,
        creating_journal_id, due_journal_id, due_date
    )
    VALUES (
        :user_id, 'Pack the tent', :task_list_id, :position,
        :creating_journal_id, :due_journal_id, :due_date
    )
    RETURNING id, task_list_id, position, due_date, flagged, icon,
              creating_journal_id, due_journal_id
    """
)
_INSERT_LIST = text(
    """
    INSERT INTO task_lists (user_id, name, position)
    VALUES (:user_id, 'Packing', 0)
    RETURNING id
    """
)
_SET_FLAG_AND_ICON = text(
    """
    UPDATE tasks SET flagged = true, icon = :icon
    WHERE id = :id
    RETURNING flagged, icon
    """
)
_DELETE_LIST = text("DELETE FROM task_lists WHERE id = :id")

# SQLSTATEs asserted alongside the constraint name, rather than message text.
_CHECK_VIOLATION = "23514"
_FOREIGN_KEY_VIOLATION = "23503"
# ``ON DELETE RESTRICT`` raises restrict_violation, not foreign_key_violation.
_RESTRICT_VIOLATION = "23001"

_BOTH_ANCHORS = "ck_tasks_journal_only_has_both_anchors"
_DUE_DATE = "ck_tasks_due_date_only_on_list_without_due_journal"
_POSITION_ON_LIST = "ck_tasks_position_only_on_list"
_POSITION_NON_NEGATIVE = "ck_tasks_position_non_negative"

# A fixed date: the table does not judge whether a due date is in the future
# (that is a domain rule in the user's timezone), so no clock is needed.
_DUE_DATE_VALUE = date(2026, 12, 24)


def _task(**overrides: Any) -> dict[str, Any]:
    """Parameters for a task on no list with no journals; override what matters."""
    params: dict[str, Any] = {
        "user_id": USER_ID,
        "task_list_id": None,
        "position": None,
        "creating_journal_id": None,
        "due_journal_id": None,
        "due_date": None,
    }
    params.update(overrides)
    return params


def _assert_check_violation(exc: IntegrityError, constraint: str) -> None:
    assert getattr(exc.orig, "sqlstate", None) == _CHECK_VIOLATION
    assert constraint in str(exc)


@pytest_asyncio.fixture
async def list_id(async_connection: AsyncConnection) -> int:
    """A list owned by the test user."""
    return int(
        (
            await async_connection.execute(_INSERT_LIST, {"user_id": USER_ID})
        ).scalar_one()
    )


@pytest.mark.integration
class TestListTasksAreAccepted:
    """Every shape a list task may take is storable."""

    async def test_a_list_task_needs_no_journal(
        self, async_connection: AsyncConnection, list_id: int
    ) -> None:
        row = (
            await async_connection.execute(
                _INSERT_TASK, _task(task_list_id=list_id, position=0)
            )
        ).one()

        assert row.task_list_id == list_id
        assert row.position == 0
        assert row.creating_journal_id is None
        assert row.due_journal_id is None
        assert row.due_date is None
        assert row.flagged is False
        assert row.icon is None

    async def test_a_list_task_may_have_a_due_date(
        self, async_connection: AsyncConnection, list_id: int
    ) -> None:
        row = (
            await async_connection.execute(
                _INSERT_TASK,
                _task(task_list_id=list_id, position=0, due_date=_DUE_DATE_VALUE),
            )
        ).one()

        assert row.due_date == _DUE_DATE_VALUE

    async def test_a_list_task_may_have_a_due_journal(
        self,
        async_connection: AsyncConnection,
        list_id: int,
        task_anchors: tuple[int, int],
    ) -> None:
        _, due_id = task_anchors

        row = (
            await async_connection.execute(
                _INSERT_TASK,
                _task(task_list_id=list_id, position=0, due_journal_id=due_id),
            )
        ).one()

        assert row.due_journal_id == due_id
        assert row.creating_journal_id is None

    async def test_a_list_task_may_have_only_a_creating_journal(
        self,
        async_connection: AsyncConnection,
        list_id: int,
        task_anchors: tuple[int, int],
    ) -> None:
        creating_id, _ = task_anchors

        row = (
            await async_connection.execute(
                _INSERT_TASK,
                _task(
                    task_list_id=list_id, position=0, creating_journal_id=creating_id
                ),
            )
        ).one()

        assert row.creating_journal_id == creating_id
        assert row.due_journal_id is None

    async def test_a_list_task_may_hold_both_journals(
        self,
        async_connection: AsyncConnection,
        list_id: int,
        task_anchors: tuple[int, int],
    ) -> None:
        """The row a journal-only task becomes when it is added to a list."""
        creating_id, due_id = task_anchors

        row = (
            await async_connection.execute(
                _INSERT_TASK,
                _task(
                    task_list_id=list_id,
                    position=0,
                    creating_journal_id=creating_id,
                    due_journal_id=due_id,
                ),
            )
        ).one()

        assert row.task_list_id == list_id
        assert row.creating_journal_id == creating_id
        assert row.due_journal_id == due_id

    async def test_a_list_task_may_have_a_creating_journal_and_a_due_date(
        self,
        async_connection: AsyncConnection,
        list_id: int,
        task_anchors: tuple[int, int],
    ) -> None:
        """A due date excludes only a due journal, not the creating one."""
        creating_id, _ = task_anchors

        row = (
            await async_connection.execute(
                _INSERT_TASK,
                _task(
                    task_list_id=list_id,
                    position=0,
                    creating_journal_id=creating_id,
                    due_date=_DUE_DATE_VALUE,
                ),
            )
        ).one()

        assert row.creating_journal_id == creating_id
        assert row.due_date == _DUE_DATE_VALUE

    async def test_a_list_task_may_be_flagged_with_an_icon(
        self, async_connection: AsyncConnection, list_id: int
    ) -> None:
        task_id = (
            (
                await async_connection.execute(
                    _INSERT_TASK, _task(task_list_id=list_id, position=0)
                )
            )
            .one()
            .id
        )

        row = (
            await async_connection.execute(
                _SET_FLAG_AND_ICON, {"id": task_id, "icon": TaskIcon.LUGGAGE.value}
            )
        ).one()

        assert row.flagged is True
        assert TaskIcon(row.icon) is TaskIcon.LUGGAGE

    async def test_a_journal_only_task_may_be_flagged_with_an_icon(
        self, async_connection: AsyncConnection, task_anchors: tuple[int, int]
    ) -> None:
        """Flag and icon apply to every task, not only list tasks."""
        creating_id, due_id = task_anchors
        row = (
            await async_connection.execute(
                _INSERT_TASK,
                _task(creating_journal_id=creating_id, due_journal_id=due_id),
            )
        ).one()
        assert row.task_list_id is None
        assert row.position is None

        flagged = (
            await async_connection.execute(
                _SET_FLAG_AND_ICON, {"id": row.id, "icon": TaskIcon.LUGGAGE.value}
            )
        ).one()

        assert flagged.flagged is True
        assert TaskIcon(flagged.icon) is TaskIcon.LUGGAGE


@pytest.mark.integration
class TestJournalOnlyTasksKeepBothAnchors:
    """Invariants 1 and 2: with no list, both journals are required."""

    async def test_a_task_with_no_list_and_no_journal_is_refused(
        self, async_connection: AsyncConnection
    ) -> None:
        """Invariant 1 — neither a list nor a due journal."""
        with pytest.raises(IntegrityError) as exc_info:
            await async_connection.execute(_INSERT_TASK, _task())

        _assert_check_violation(exc_info.value, _BOTH_ANCHORS)

    async def test_a_task_with_no_list_and_no_creating_journal_is_refused(
        self, async_connection: AsyncConnection, task_anchors: tuple[int, int]
    ) -> None:
        _, due_id = task_anchors

        with pytest.raises(IntegrityError) as exc_info:
            await async_connection.execute(_INSERT_TASK, _task(due_journal_id=due_id))

        _assert_check_violation(exc_info.value, _BOTH_ANCHORS)

    async def test_a_task_with_no_list_and_no_due_journal_is_refused(
        self, async_connection: AsyncConnection, task_anchors: tuple[int, int]
    ) -> None:
        creating_id, _ = task_anchors

        with pytest.raises(IntegrityError) as exc_info:
            await async_connection.execute(
                _INSERT_TASK, _task(creating_journal_id=creating_id)
            )

        _assert_check_violation(exc_info.value, _BOTH_ANCHORS)


@pytest.mark.integration
class TestDueDateRules:
    """Invariants 4 and 5: a due date only on a list task, never with a due journal."""

    async def test_a_due_date_beside_a_due_journal_is_refused(
        self,
        async_connection: AsyncConnection,
        list_id: int,
        task_anchors: tuple[int, int],
    ) -> None:
        """Invariant 4 — on a list, so only the due-date rule can refuse it."""
        _, due_id = task_anchors

        with pytest.raises(IntegrityError) as exc_info:
            await async_connection.execute(
                _INSERT_TASK,
                _task(
                    task_list_id=list_id,
                    position=0,
                    due_journal_id=due_id,
                    due_date=_DUE_DATE_VALUE,
                ),
            )

        _assert_check_violation(exc_info.value, _DUE_DATE)

    async def test_a_due_date_on_a_journal_only_task_is_refused(
        self, async_connection: AsyncConnection, task_anchors: tuple[int, int]
    ) -> None:
        """Invariant 5 — both anchors held, so only the due-date rule can refuse it."""
        creating_id, due_id = task_anchors

        with pytest.raises(IntegrityError) as exc_info:
            await async_connection.execute(
                _INSERT_TASK,
                _task(
                    creating_journal_id=creating_id,
                    due_journal_id=due_id,
                    due_date=_DUE_DATE_VALUE,
                ),
            )

        _assert_check_violation(exc_info.value, _DUE_DATE)


@pytest.mark.integration
class TestPositionRules:
    """A position exactly when on a list, and never negative."""

    async def test_a_position_without_a_list_is_refused(
        self, async_connection: AsyncConnection, task_anchors: tuple[int, int]
    ) -> None:
        creating_id, due_id = task_anchors

        with pytest.raises(IntegrityError) as exc_info:
            await async_connection.execute(
                _INSERT_TASK,
                _task(
                    creating_journal_id=creating_id,
                    due_journal_id=due_id,
                    position=0,
                ),
            )

        _assert_check_violation(exc_info.value, _POSITION_ON_LIST)

    async def test_a_list_without_a_position_is_refused(
        self, async_connection: AsyncConnection, list_id: int
    ) -> None:
        with pytest.raises(IntegrityError) as exc_info:
            await async_connection.execute(_INSERT_TASK, _task(task_list_id=list_id))

        _assert_check_violation(exc_info.value, _POSITION_ON_LIST)

    async def test_a_negative_position_is_refused(
        self, async_connection: AsyncConnection, list_id: int
    ) -> None:
        with pytest.raises(IntegrityError) as exc_info:
            await async_connection.execute(
                _INSERT_TASK, _task(task_list_id=list_id, position=-1)
            )

        _assert_check_violation(exc_info.value, _POSITION_NON_NEGATIVE)


@pytest.mark.integration
class TestListForeignKey:
    """A task's list must exist, and a list holding tasks cannot vanish silently."""

    async def test_an_unknown_list_is_refused(
        self, async_connection: AsyncConnection
    ) -> None:
        with pytest.raises(IntegrityError) as exc_info:
            await async_connection.execute(
                _INSERT_TASK, _task(task_list_id=2_000_000_000, position=0)
            )

        assert getattr(exc_info.value.orig, "sqlstate", None) == (
            _FOREIGN_KEY_VIOLATION
        )
        assert "tasks_task_list_id_fkey" in str(exc_info.value)

    async def test_deleting_a_list_that_holds_a_task_is_refused(
        self, async_connection: AsyncConnection, list_id: int
    ) -> None:
        """RESTRICT: the list-delete service decides each task's fate, never a cascade."""
        await async_connection.execute(
            _INSERT_TASK, _task(task_list_id=list_id, position=0)
        )

        with pytest.raises(IntegrityError) as exc_info:
            await async_connection.execute(_DELETE_LIST, {"id": list_id})

        assert getattr(exc_info.value.orig, "sqlstate", None) == _RESTRICT_VIOLATION
        assert "tasks_task_list_id_fkey" in str(exc_info.value)
