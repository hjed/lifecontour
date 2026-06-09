"""
Service-layer unit-of-work helpers for explicit transaction management.

The request-scoped :class:`AsyncConnection` is provided in *commit-as-you-go*
mode (``engine.connect()`` in :mod:`app.infrastructure.di.database`). It does
**not** commit at request teardown, so writes must be committed explicitly
*inside* the request handler — before the HTTP response is sent — to avoid the
read-after-write race documented in issue #945.

Usage (service layer)::

    async with unit_of_work(transaction):
        await repo.save(entity)
        await event_publisher.publish(event)
    # committed here, before the response is returned

Rules of thumb:

* **Writes** wrap their unit of work in :func:`unit_of_work`. Only the
  outermost ``unit_of_work`` on a connection commits, so services may freely
  call other services that also open one.
* **Reads** run without any transaction helper. The autobegun read transaction
  is rolled back when the connection closes (a harmless no-op).
* **Controllers never open transactions** — that belongs in the service layer.
* **Batch loops** that must roll back a single item and continue use
  :func:`savepoint` (a SAVEPOINT) *inside* an enclosing :func:`unit_of_work`.
"""

import functools
import inspect
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncConnection

# Keys stored on ``AsyncConnection.info`` (a per-connection dict that lives for
# the lifetime of the connection).
_DEPTH_KEY = "uow_depth"

# Set by the integration test fixture on the single shared connection. When
# present, the connection is already wrapped in an outer transaction owned by
# the test (rolled back at teardown for isolation). Code that would normally
# commit/rollback the real transaction must instead leave it intact:
#   * the outermost unit of work emulates commit/rollback with a SAVEPOINT, and
#   * the commit backstops (middleware + connection provider) skip committing.
# Writes remain visible to later reads on the same connection within the test.
# See ``tests/integration/conftest.py``.
EXTERNAL_TRANSACTION_MARKER = "external_transaction"


def in_external_transaction(connection: AsyncConnection) -> bool:
    """Return True if the connection is inside a test-owned outer transaction."""
    return bool(connection.info.get(EXTERNAL_TRANSACTION_MARKER))


@asynccontextmanager
async def unit_of_work(connection: AsyncConnection) -> AsyncIterator[AsyncConnection]:
    """Explicit service-layer unit of work.

    Commits on success and rolls back on exception, running inside the request
    handler so the write is durable before the response is sent.

    Re-entrant: nested calls join the outer unit of work and only the outermost
    one commits. Nesting is tracked with a depth counter on ``connection.info``
    rather than :meth:`AsyncConnection.in_transaction`, because a read earlier
    in the same request autobegins a transaction and must not be mistaken for an
    already-open unit of work.
    """
    info = connection.info
    depth: int = info.get(_DEPTH_KEY, 0)
    is_outermost = depth == 0
    in_test = bool(info.get(EXTERNAL_TRANSACTION_MARKER))
    info[_DEPTH_KEY] = depth + 1
    try:
        if not is_outermost:
            # Nested unit of work: defer commit/rollback to the outermost scope.
            yield connection
        elif in_test:
            # Test isolation: a SAVEPOINT stands in for the real commit/rollback
            # so the surrounding test transaction survives to be rolled back at
            # teardown. Releasing the savepoint keeps writes visible to later
            # reads on the same connection (read-after-write within a test).
            nested = await connection.begin_nested()
            try:
                yield connection
            except BaseException:
                await nested.rollback()
                raise
            else:
                await nested.commit()
        else:
            # Production outermost unit of work: commit before the response.
            try:
                yield connection
            except BaseException:
                await connection.rollback()
                raise
            else:
                await connection.commit()
    finally:
        info[_DEPTH_KEY] = depth


def transactional[**P, R](
    func: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R]]:
    """Run an ``async`` service write method as a committed unit of work.

    The decorated method must accept a ``transaction: AsyncConnection``
    parameter (positionally or by keyword). The call is wrapped in
    :func:`unit_of_work`, so the write is committed before the response is sent
    and rolled back on error. Re-entrancy means decorated methods may call other
    decorated methods without committing early.

    This is the declaration-site equivalent of wrapping the whole method body in
    ``async with unit_of_work(transaction):`` — preferred for write methods that
    don't already funnel through a shared wrapper.
    """
    signature = inspect.signature(func)

    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        bound = signature.bind(*args, **kwargs)
        connection = bound.arguments.get("transaction")
        if not isinstance(connection, AsyncConnection):
            # No real connection (e.g. unit tests passing a mock or None): run
            # without managing a transaction. Production and integration tests
            # always inject a real AsyncConnection, which is wrapped below.
            return await func(*args, **kwargs)
        async with unit_of_work(connection):
            return await func(*args, **kwargs)

    return wrapper


@asynccontextmanager
async def savepoint(connection: AsyncConnection) -> AsyncIterator[AsyncConnection]:
    """Nested SAVEPOINT for per-item partial rollback inside a batch loop.

    Use within an enclosing :func:`unit_of_work` when individual items may fail
    but the loop should continue (e.g. journal auto-merge). On exception the
    savepoint is rolled back and the error propagates so the caller can decide
    whether to swallow it and continue; on success the savepoint is released.

    Does not affect the unit-of-work depth, so it never changes the outer commit
    decision.
    """
    nested = await connection.begin_nested()
    try:
        yield connection
    except BaseException:
        await nested.rollback()
        raise
    else:
        await nested.commit()
