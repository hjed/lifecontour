"""The recurrence columns on ``tasks`` and the shapes the table accepts.

Migration 0150 gives a task an optional recurrence setting — a mode, an
interval for *interval after completion*, a series for *next journal in a
series* — and a "recurrence of" link to the task a copy came from (spec
*Recurring Tasks*). Invariant 6 puts recurrence on list tasks only.

Each refused row breaks exactly one constraint, so each test names the one that
refused it. Rows are inserted directly: nothing in the application writes these
columns yet.

Each expected violation gets its own test: a failed statement poisons the
surrounding transaction, so the test must end there and let the fixture roll back.
"""

from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import TextClause, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.tasks.task_seeding import USER_ID

pytestmark = pytest.mark.integration

# Statements are built once at module level so that a ``pytest.raises`` block
# wraps only the execution under test, never the construction of its SQL.
_INSERT_TASK = text(
    """
    INSERT INTO tasks (
        user_id, text, task_list_id, position,
        creating_journal_id, due_journal_id,
        recurrence_mode, recurrence_interval_count, recurrence_interval_unit,
        recurrence_series_id, recurrence_of_task_id
    )
    VALUES (
        :user_id, 'Water the plants', :task_list_id, :position,
        :creating_journal_id, :due_journal_id,
        :recurrence_mode, :recurrence_interval_count, :recurrence_interval_unit,
        :recurrence_series_id, :recurrence_of_task_id
    )
    RETURNING id, recurrence_mode, recurrence_interval_count,
              recurrence_interval_unit, recurrence_series_id, recurrence_of_task_id
    """
)
_INSERT_LIST = text(
    """
    INSERT INTO task_lists (user_id, name, position)
    VALUES (:user_id, 'Chores', 0)
    RETURNING id
    """
)
_INSERT_SERIES = text(
    """
    INSERT INTO journal_series (user_id, name)
    VALUES (:user_id, 'Weekly review')
    RETURNING id
    """
)
_POINT_AT_ITSELF = text("UPDATE tasks SET recurrence_of_task_id = id WHERE id = :id")
_TAKE_OFF_LIST = text(
    "UPDATE tasks SET task_list_id = NULL, position = NULL WHERE id = :id"
)
_DELETE_SERIES = text("DELETE FROM journal_series WHERE id = :id")
_DELETE_TASK = text("DELETE FROM tasks WHERE id = :id")
_RECURRENCE_OF = text("SELECT recurrence_of_task_id FROM tasks WHERE id = :id")

_CHECK_VIOLATION = "23514"
_FOREIGN_KEY_VIOLATION = "23503"
# ``ON DELETE RESTRICT`` raises restrict_violation, not foreign_key_violation.
_RESTRICT_VIOLATION = "23001"

_ONLY_ON_LIST = "ck_tasks_recurrence_only_on_list"
_MODE = "ck_tasks_recurrence_mode"
_INTERVAL_MATCHES_MODE = "ck_tasks_recurrence_interval_matches_mode"
_INTERVAL_UNIT = "ck_tasks_recurrence_interval_unit"
_INTERVAL_COUNT = "ck_tasks_recurrence_interval_count_positive"
_SERIES_MATCHES_MODE = "ck_tasks_recurrence_series_matches_mode"
_NOT_SELF = "ck_tasks_recurrence_of_not_self"


def _task(**overrides: Any) -> dict[str, Any]:
    """Parameters for a non-recurring task on no list; override what matters."""
    params: dict[str, Any] = {
        "user_id": USER_ID,
        "task_list_id": None,
        "position": None,
        "creating_journal_id": None,
        "due_journal_id": None,
        "recurrence_mode": None,
        "recurrence_interval_count": None,
        "recurrence_interval_unit": None,
        "recurrence_series_id": None,
        "recurrence_of_task_id": None,
    }
    params.update(overrides)
    return params


def _sqlstate(exc: pytest.ExceptionInfo[IntegrityError]) -> str | None:
    return getattr(exc.value.orig, "sqlstate", None)


def _assert_check_violation(
    exc: pytest.ExceptionInfo[IntegrityError], constraint: str
) -> None:
    assert _sqlstate(exc) == _CHECK_VIOLATION
    assert constraint in str(exc.value)


async def _refused(
    conn: AsyncConnection, statement: TextClause, params: dict[str, Any]
) -> pytest.ExceptionInfo[IntegrityError]:
    """Run a write the table must refuse, and return what refused it."""
    with pytest.raises(IntegrityError) as exc:
        await conn.execute(statement, params)
    return exc


@pytest_asyncio.fixture
async def list_id(async_connection: AsyncConnection) -> int:
    """A list owned by the test user."""
    return int(
        (
            await async_connection.execute(_INSERT_LIST, {"user_id": USER_ID})
        ).scalar_one()
    )


@pytest_asyncio.fixture
async def series_id(async_connection: AsyncConnection) -> UUID:
    """A series owned by the test user."""
    series: UUID = (
        await async_connection.execute(_INSERT_SERIES, {"user_id": USER_ID})
    ).scalar_one()
    return series


def _on_list(list_id: int, **overrides: Any) -> dict[str, Any]:
    return _task(task_list_id=list_id, position=0, **overrides)


def _interval(list_id: int, **overrides: Any) -> dict[str, Any]:
    params: dict[str, Any] = {
        "recurrence_mode": "interval",
        "recurrence_interval_count": 2,
        "recurrence_interval_unit": "week",
    }
    params.update(overrides)
    return _on_list(list_id, **params)


async def _insert(conn: AsyncConnection, params: dict[str, Any]) -> Any:
    return (await conn.execute(_INSERT_TASK, params)).one()


class TestRecurrenceShapesAreAccepted:
    """Every shape a recurrence setting may take is storable on a list task."""

    async def test_a_task_need_not_recur(
        self, async_connection: AsyncConnection, list_id: int
    ) -> None:
        row = await _insert(async_connection, _on_list(list_id))

        assert row.recurrence_mode is None
        assert row.recurrence_interval_count is None
        assert row.recurrence_interval_unit is None
        assert row.recurrence_series_id is None
        assert row.recurrence_of_task_id is None

    async def test_no_date_mode_carries_nothing_else(
        self, async_connection: AsyncConnection, list_id: int
    ) -> None:
        row = await _insert(
            async_connection, _on_list(list_id, recurrence_mode="no_date")
        )

        assert row.recurrence_mode == "no_date"

    @pytest.mark.parametrize("unit", ["day", "week", "month", "year"])
    async def test_interval_mode_takes_each_unit(
        self, async_connection: AsyncConnection, list_id: int, unit: str
    ) -> None:
        row = await _insert(
            async_connection, _interval(list_id, recurrence_interval_unit=unit)
        )

        assert (row.recurrence_interval_count, row.recurrence_interval_unit) == (
            2,
            unit,
        )

    async def test_series_mode_names_a_series(
        self, async_connection: AsyncConnection, list_id: int, series_id: UUID
    ) -> None:
        row = await _insert(
            async_connection,
            _on_list(list_id, recurrence_mode="series", recurrence_series_id=series_id),
        )

        assert row.recurrence_series_id == series_id

    async def test_a_copy_records_the_task_it_came_from(
        self, async_connection: AsyncConnection, list_id: int
    ) -> None:
        original = await _insert(async_connection, _interval(list_id))

        copy = await _insert(
            async_connection,
            _interval(list_id, recurrence_of_task_id=original.id),
        )

        assert copy.recurrence_of_task_id == original.id


class TestRecurrenceIsOnlyOnAListTask:
    """Invariant 6: a journal-only task cannot recur."""

    async def test_a_journal_only_task_cannot_recur(
        self, async_connection: AsyncConnection, task_anchors: tuple[int, int]
    ) -> None:
        creating_id, due_id = task_anchors

        exc = await _refused(
            async_connection,
            _INSERT_TASK,
            _task(
                creating_journal_id=creating_id,
                due_journal_id=due_id,
                recurrence_mode="no_date",
            ),
        )

        _assert_check_violation(exc, _ONLY_ON_LIST)

    async def test_a_recurring_task_cannot_leave_its_list_alone(
        self,
        async_connection: AsyncConnection,
        list_id: int,
        task_anchors: tuple[int, int],
    ) -> None:
        """A write taking a task off its list must clear recurrence too."""
        creating_id, due_id = task_anchors
        task = await _insert(
            async_connection,
            _on_list(
                list_id,
                creating_journal_id=creating_id,
                due_journal_id=due_id,
                recurrence_mode="no_date",
            ),
        )

        exc = await _refused(async_connection, _TAKE_OFF_LIST, {"id": task.id})

        _assert_check_violation(exc, _ONLY_ON_LIST)


class TestRefusedRecurrenceShapes:
    """One refused row per constraint, each naming the one that refused it."""

    async def test_an_unknown_mode_is_refused(
        self, async_connection: AsyncConnection, list_id: int
    ) -> None:
        exc = await _refused(
            async_connection,
            _INSERT_TASK,
            _on_list(list_id, recurrence_mode="weekly"),
        )

        _assert_check_violation(exc, _MODE)

    async def test_interval_mode_needs_an_interval(
        self, async_connection: AsyncConnection, list_id: int
    ) -> None:
        exc = await _refused(
            async_connection,
            _INSERT_TASK,
            _on_list(list_id, recurrence_mode="interval"),
        )

        _assert_check_violation(exc, _INTERVAL_MATCHES_MODE)

    async def test_an_interval_needs_its_unit(
        self, async_connection: AsyncConnection, list_id: int
    ) -> None:
        exc = await _refused(
            async_connection,
            _INSERT_TASK,
            _interval(list_id, recurrence_interval_unit=None),
        )

        _assert_check_violation(exc, _INTERVAL_MATCHES_MODE)

    async def test_another_mode_cannot_carry_an_interval(
        self, async_connection: AsyncConnection, list_id: int
    ) -> None:
        exc = await _refused(
            async_connection,
            _INSERT_TASK,
            _interval(list_id, recurrence_mode="no_date"),
        )

        _assert_check_violation(exc, _INTERVAL_MATCHES_MODE)

    async def test_an_interval_needs_its_count(
        self, async_connection: AsyncConnection, list_id: int
    ) -> None:
        exc = await _refused(
            async_connection,
            _INSERT_TASK,
            _interval(list_id, recurrence_interval_count=None),
        )

        _assert_check_violation(exc, _INTERVAL_MATCHES_MODE)

    async def test_a_task_that_does_not_recur_cannot_carry_an_interval(
        self, async_connection: AsyncConnection, list_id: int
    ) -> None:
        """A NULL mode is not ``interval``: the comparison must not go NULL."""
        exc = await _refused(
            async_connection,
            _INSERT_TASK,
            _interval(list_id, recurrence_mode=None),
        )

        _assert_check_violation(exc, _INTERVAL_MATCHES_MODE)

    async def test_an_unknown_unit_is_refused(
        self, async_connection: AsyncConnection, list_id: int
    ) -> None:
        exc = await _refused(
            async_connection,
            _INSERT_TASK,
            _interval(list_id, recurrence_interval_unit="fortnight"),
        )

        _assert_check_violation(exc, _INTERVAL_UNIT)

    @pytest.mark.parametrize("count", [0, -1])
    async def test_an_interval_count_must_be_positive(
        self, async_connection: AsyncConnection, list_id: int, count: int
    ) -> None:
        exc = await _refused(
            async_connection,
            _INSERT_TASK,
            _interval(list_id, recurrence_interval_count=count),
        )

        _assert_check_violation(exc, _INTERVAL_COUNT)

    async def test_series_mode_needs_a_series(
        self, async_connection: AsyncConnection, list_id: int
    ) -> None:
        exc = await _refused(
            async_connection,
            _INSERT_TASK,
            _on_list(list_id, recurrence_mode="series"),
        )

        _assert_check_violation(exc, _SERIES_MATCHES_MODE)

    async def test_another_mode_cannot_carry_a_series(
        self, async_connection: AsyncConnection, list_id: int, series_id: UUID
    ) -> None:
        exc = await _refused(
            async_connection,
            _INSERT_TASK,
            _on_list(
                list_id, recurrence_mode="no_date", recurrence_series_id=series_id
            ),
        )

        _assert_check_violation(exc, _SERIES_MATCHES_MODE)

    async def test_a_task_that_does_not_recur_cannot_carry_a_series(
        self, async_connection: AsyncConnection, list_id: int, series_id: UUID
    ) -> None:
        """A NULL mode is not ``series``: the comparison must not go NULL."""
        exc = await _refused(
            async_connection,
            _INSERT_TASK,
            _on_list(list_id, recurrence_series_id=series_id),
        )

        _assert_check_violation(exc, _SERIES_MATCHES_MODE)

    async def test_a_task_is_never_a_copy_of_itself(
        self, async_connection: AsyncConnection, list_id: int
    ) -> None:
        task = await _insert(async_connection, _on_list(list_id))

        exc = await _refused(async_connection, _POINT_AT_ITSELF, {"id": task.id})

        _assert_check_violation(exc, _NOT_SELF)


class TestRecurrenceForeignKeys:
    """The series must exist and cannot vanish; a copy outlives its original."""

    async def test_an_unknown_series_is_refused(
        self, async_connection: AsyncConnection, list_id: int
    ) -> None:
        exc = await _refused(
            async_connection,
            _INSERT_TASK,
            _on_list(list_id, recurrence_mode="series", recurrence_series_id=uuid4()),
        )

        assert _sqlstate(exc) == _FOREIGN_KEY_VIOLATION

    async def test_an_unknown_original_is_refused(
        self, async_connection: AsyncConnection, list_id: int
    ) -> None:
        exc = await _refused(
            async_connection,
            _INSERT_TASK,
            _on_list(list_id, recurrence_of_task_id=2_000_000_000),
        )

        assert _sqlstate(exc) == _FOREIGN_KEY_VIOLATION

    async def test_a_series_a_task_recurs_in_cannot_be_deleted(
        self, async_connection: AsyncConnection, list_id: int, series_id: UUID
    ) -> None:
        """Falling back to *no date* is the series-delete service's job."""
        await _insert(
            async_connection,
            _on_list(list_id, recurrence_mode="series", recurrence_series_id=series_id),
        )

        exc = await _refused(async_connection, _DELETE_SERIES, {"id": series_id})

        assert _sqlstate(exc) == _RESTRICT_VIOLATION

    async def test_deleting_the_original_keeps_the_copy_unlinked(
        self, async_connection: AsyncConnection, list_id: int
    ) -> None:
        original = await _insert(async_connection, _interval(list_id))
        copy = await _insert(
            async_connection, _interval(list_id, recurrence_of_task_id=original.id)
        )

        await async_connection.execute(_DELETE_TASK, {"id": original.id})

        assert (
            await async_connection.execute(_RECURRENCE_OF, {"id": copy.id})
        ).one() == (None,)
