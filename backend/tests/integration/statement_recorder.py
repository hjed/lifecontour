"""Counting the statements a block of code actually sends to PostgreSQL.

An N+1 is invisible to a functional assertion: the answer is right either way,
and only the number of round trips is wrong. So the tests that care assert that
number, and they do it by listening to SQLAlchemy's ``before_cursor_execute``
rather than by patching ``AsyncConnection.execute`` — which cannot be patched,
and would be the weaker claim anyway, because a repository looping internally
would slip past a count of the calls its caller made.

It lives here rather than in one test file because three suites now need it: the
journal delete guard, the tasks read model, and the batch cancellation read the
latter depends on.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncConnection


@contextmanager
def recorded_statements(conn: AsyncConnection) -> Iterator[list[str]]:
    """Record every statement the connection sends while the block runs.

    Args:
        conn: The connection to listen on — the test's savepoint connection

    Yields:
        A list that fills with the SQL text of each statement, in order. It is
        populated as the block runs, so assert on it after the block exits.
    """
    statements: list[str] = []

    def record(
        _conn: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        statements.append(statement)

    sync_connection = conn.sync_connection
    assert sync_connection is not None
    event.listen(sync_connection, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(sync_connection, "before_cursor_execute", record)
