"""A list's associated journal, as the ``task_lists`` table stores it.

Migration 0149 adds ``associated_journal_id``: a list names at most one journal
(one nullable column), and a journal may hold several lists (no uniqueness). The
foreign key is ``ON DELETE RESTRICT``: journal delete and merge unassociate or
re-point a list themselves, each with a history event, before the journal row
goes, so the constraint is only the backstop that stops a path which forgot from
silently dropping the association.

Rows are inserted directly — the association is written by services in later
phases. Each expected violation gets its own test: a failed statement poisons
the surrounding transaction, so the test must end there and let the fixture roll
back.
"""

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.tasks.task_seeding import USER_ID

# Statements are built once at module level so that a ``pytest.raises`` block
# wraps only the execution under test, never the construction of its SQL.
_INSERT_JOURNAL = text(
    """
    INSERT INTO journals (title, content, user_id,
        event_date_range_start, event_date_range_end)
    VALUES ('Trip', '', :user_id, '2026-12-01', '2026-12-01')
    RETURNING id
    """
)
_INSERT_LIST = text(
    """
    INSERT INTO task_lists (user_id, name, position, associated_journal_id)
    VALUES (:user_id, :name, 0, :journal_id)
    RETURNING id
    """
)
_DELETE_JOURNAL = text("DELETE FROM journals WHERE id = :id")
_DELETE_LIST = text("DELETE FROM task_lists WHERE id = :id")
_COUNT_ASSOCIATED = text(
    "SELECT COUNT(*) FROM task_lists WHERE associated_journal_id = :journal_id"
)
_JOURNAL_EXISTS = text("SELECT EXISTS (SELECT 1 FROM journals WHERE id = :id)")

_FK = "fk_task_lists_associated_journal_id"
# SQLSTATEs asserted alongside the constraint name, rather than message text.
_FOREIGN_KEY_VIOLATION = "23503"
# ``ON DELETE RESTRICT`` raises restrict_violation, not foreign_key_violation.
_RESTRICT_VIOLATION = "23001"
# Larger than any id the session database will hand out.
_UNKNOWN_JOURNAL_ID = 2_000_000_000


@pytest_asyncio.fixture
async def journal_id(async_connection: AsyncConnection) -> int:
    """A journal for lists to name."""
    result = await async_connection.execute(_INSERT_JOURNAL, {"user_id": USER_ID})
    return int(result.scalar_one())


async def _insert_list(
    conn: AsyncConnection, journal_id: int | None, name: str = "Packing"
) -> int:
    result = await conn.execute(
        _INSERT_LIST, {"user_id": USER_ID, "name": name, "journal_id": journal_id}
    )
    return int(result.one().id)


@pytest.mark.integration
class TestTaskListAssociationColumn:
    """What the table allows. Storing and reading the association back is the
    repository's round trip (``TestAssociatedJournal``)."""

    async def test_a_journal_may_hold_several_lists(
        self, async_connection: AsyncConnection, journal_id: int
    ) -> None:
        await _insert_list(async_connection, journal_id, name="Packing")
        await _insert_list(async_connection, journal_id, name="Prep")

        count = (
            await async_connection.execute(
                _COUNT_ASSOCIATED, {"journal_id": journal_id}
            )
        ).scalar_one()

        assert count == 2

    async def test_deleting_a_list_leaves_its_journal(
        self, async_connection: AsyncConnection, journal_id: int
    ) -> None:
        list_id = await _insert_list(async_connection, journal_id)

        await async_connection.execute(_DELETE_LIST, {"id": list_id})

        exists = (
            await async_connection.execute(_JOURNAL_EXISTS, {"id": journal_id})
        ).scalar_one()
        assert exists is True


@pytest.mark.integration
class TestTaskListAssociationConstraints:
    """The foreign key's two refusals."""

    async def test_an_unknown_journal_is_refused(
        self, async_connection: AsyncConnection
    ) -> None:
        with pytest.raises(IntegrityError) as exc_info:
            await _insert_list(async_connection, _UNKNOWN_JOURNAL_ID)

        assert getattr(exc_info.value.orig, "sqlstate", None) == _FOREIGN_KEY_VIOLATION
        assert _FK in str(exc_info.value)

    async def test_deleting_an_associated_journal_is_refused(
        self, async_connection: AsyncConnection, journal_id: int
    ) -> None:
        """The backstop: the journal services unassociate first, so only a path
        that forgot to would reach this — and it fails rather than silently
        dropping the association with no history."""
        await _insert_list(async_connection, journal_id)

        with pytest.raises(IntegrityError) as exc_info:
            await async_connection.execute(_DELETE_JOURNAL, {"id": journal_id})

        assert getattr(exc_info.value.orig, "sqlstate", None) == _RESTRICT_VIOLATION
        assert _FK in str(exc_info.value)
