"""Column defaults and constraints of the ``task_lists`` table.

The ``TaskList`` entity is the first gate on every write; these constraints are
the database's own last line of defence for the same rules, so a raw write that
skips the entity still cannot store a list with no owner, a blank name or a
negative position. The icon has no CHECK by design: the set is add-only and is
gated by the ``TaskIcon`` enum (see ``database-design.md`` *Task lists*).

Rows are inserted directly — the repository lands in the next phase.

Each expected violation gets its own test: a failed statement poisons the
surrounding transaction, so the test must end there and let the fixture roll back.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from core_shared.models.tasks import MAX_TASK_LIST_NAME_LENGTH, TaskIcon
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.tasks.task_seeding import OTHER_USER_ID, USER_ID

# Statements are built once at module level so that a ``pytest.raises`` block
# wraps only the execution under test, never the construction of its SQL.
_INSERT_LIST = text(
    """
    INSERT INTO task_lists (user_id, name, position)
    VALUES (:user_id, :name, :position)
    RETURNING id, icon, archived_at, created_at, updated_at
    """
)
_INSERT_FULL_LIST = text(
    """
    INSERT INTO task_lists (user_id, name, icon, position, archived_at)
    VALUES (:user_id, :name, :icon, :position, :archived_at)
    RETURNING id
    """
)
_SELECT_LIST = text(
    "SELECT user_id, name, icon, position, archived_at FROM task_lists WHERE id = :id"
)
# SQLSTATEs asserted instead of PostgreSQL's (localisable) message text.
_STRING_TOO_LONG = "22001"
_NOT_NULL_VIOLATION = "23502"
_COUNT_NAMED = text(
    "SELECT COUNT(*) FROM task_lists WHERE name = :name AND position = :position"
)


def _list_params(**overrides: Any) -> dict[str, Any]:
    params: dict[str, Any] = {"user_id": USER_ID, "name": "Packing", "position": 0}
    params.update(overrides)
    return params


@pytest.mark.integration
class TestTaskListColumns:
    """What a stored list holds."""

    async def test_a_minimal_list_is_unarchived_with_no_icon(
        self, async_connection: AsyncConnection
    ) -> None:
        row = (await async_connection.execute(_INSERT_LIST, _list_params())).one()

        assert row.icon is None
        assert row.archived_at is None
        assert row.created_at is not None
        assert row.updated_at is not None

    async def test_icon_and_archive_time_are_stored(
        self, async_connection: AsyncConnection
    ) -> None:
        archived_at = datetime(2026, 11, 1, 9, 30, tzinfo=UTC)
        list_id = (
            await async_connection.execute(
                _INSERT_FULL_LIST,
                _list_params(
                    icon=TaskIcon.LUGGAGE.value, position=4, archived_at=archived_at
                ),
            )
        ).scalar_one()

        row = (await async_connection.execute(_SELECT_LIST, {"id": list_id})).one()

        assert row.user_id == USER_ID
        assert row.name == "Packing"
        assert TaskIcon(row.icon) is TaskIcon.LUGGAGE
        assert row.position == 4
        assert row.archived_at == archived_at

    async def test_two_owners_may_hold_the_same_name_and_position(
        self, async_connection: AsyncConnection
    ) -> None:
        """Neither the name nor the position is unique, across or within owners."""
        await async_connection.execute(_INSERT_LIST, _list_params())
        await async_connection.execute(_INSERT_LIST, _list_params())
        await async_connection.execute(
            _INSERT_LIST, _list_params(user_id=OTHER_USER_ID)
        )

        count = (
            await async_connection.execute(
                _COUNT_NAMED, {"name": "Packing", "position": 0}
            )
        ).scalar_one()

        assert count == 3


@pytest.mark.integration
class TestTaskListConstraints:
    """Each rule the entity enforces, enforced again by the table."""

    async def test_a_space_only_name_is_refused(
        self, async_connection: AsyncConnection
    ) -> None:
        with pytest.raises(IntegrityError) as exc_info:
            await async_connection.execute(_INSERT_LIST, _list_params(name="   "))

        assert "ck_task_lists_name_not_blank" in str(exc_info.value)

    async def test_a_name_over_the_bound_is_refused(
        self, async_connection: AsyncConnection
    ) -> None:
        """A varchar overflow is SQLSTATE 22001, not an integrity error.

        asyncpg's truncation error reaches SQLAlchemy as a bare ``DBAPIError``
        rather than its ``DataError`` subclass, so the test asserts the
        SQLSTATE the driver reports instead of the wrapper's class.
        """
        with pytest.raises(DBAPIError) as exc_info:
            await async_connection.execute(
                _INSERT_LIST,
                _list_params(name="x" * (MAX_TASK_LIST_NAME_LENGTH + 1)),
            )

        assert getattr(exc_info.value.orig, "sqlstate", None) == _STRING_TOO_LONG

    async def test_a_negative_position_is_refused(
        self, async_connection: AsyncConnection
    ) -> None:
        with pytest.raises(IntegrityError) as exc_info:
            await async_connection.execute(_INSERT_LIST, _list_params(position=-1))

        assert "ck_task_lists_position_non_negative" in str(exc_info.value)

    async def test_a_list_without_an_owner_is_refused(
        self, async_connection: AsyncConnection
    ) -> None:
        with pytest.raises(IntegrityError) as exc_info:
            await async_connection.execute(_INSERT_LIST, _list_params(user_id=None))

        assert getattr(exc_info.value.orig, "sqlstate", None) == _NOT_NULL_VIOLATION
        assert '"user_id"' in str(exc_info.value)

    async def test_a_list_without_a_position_is_refused(
        self, async_connection: AsyncConnection
    ) -> None:
        with pytest.raises(IntegrityError) as exc_info:
            await async_connection.execute(_INSERT_LIST, _list_params(position=None))

        assert getattr(exc_info.value.orig, "sqlstate", None) == _NOT_NULL_VIOLATION
        assert '"position"' in str(exc_info.value)
