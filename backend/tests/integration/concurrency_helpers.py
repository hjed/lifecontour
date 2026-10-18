"""Helpers for overlapping two real transactions against PostgreSQL.

A lost update or a deadlock only exists between two connections, which the
savepoint fixture cannot give a test: its outer transaction is invisible to
every other connection. These tests commit their rows for real under a one-off
owner and delete them afterwards.

The overlap itself is arranged without sleeping on a guess: the first writer
holds its transaction open, the second is started, and the test waits until
PostgreSQL reports the second's own backend **waiting on a lock** before
letting the first commit. Whatever the code under test does, the second writer then reads and
writes strictly after the first has locked, which is the interleaving a lost
update needs.
"""

import asyncio
from collections.abc import Awaitable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

# Long enough that a slow container is not mistaken for a hang, short enough
# that a genuine one is reported rather than waited on.
TIMEOUT = 20.0


async def backend_pid(connection: AsyncConnection) -> int:
    """The PostgreSQL backend serving ``connection``, to watch it block.

    Read before the connection's work starts - one connection cannot run two
    statements at once - and the read's own transaction is ended, so the work
    begins a fresh one.
    """
    pid = (await connection.execute(text("SELECT pg_backend_pid()"))).scalar_one()
    await connection.rollback()
    return int(pid)


async def wait_until_blocked_on_a_lock(
    async_engine: AsyncEngine, pid: int, *, timeout: float = TIMEOUT
) -> None:
    """Return once backend ``pid`` - the test's second writer - waits on a lock.

    Only that backend counts: another session waiting on a lock elsewhere must
    not release the first writer early, which would let the second read after
    the commit and pass whether or not it took its lock.

    Raises:
        TimeoutError: If ``pid`` is not waiting within ``timeout`` seconds.
    """

    async def _poll() -> None:
        async with async_engine.connect() as observer:
            while True:
                waiting = (
                    await observer.execute(
                        text(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE pid = :pid AND wait_event_type = 'Lock'"
                        ),
                        {"pid": pid},
                    )
                ).scalar_one()
                await observer.rollback()
                if waiting:
                    return
                await asyncio.sleep(0.02)

    await asyncio.wait_for(_poll(), timeout)


async def bounded[T](operation: Awaitable[T], *, timeout: float = TIMEOUT) -> T:
    """Await ``operation``, failing rather than hanging if it never finishes."""
    return await asyncio.wait_for(operation, timeout)


async def settle(*tasks: asyncio.Task[object] | asyncio.Task[None] | None) -> None:
    """Cancel whichever of ``tasks`` are still running, and wait for them all.

    For a ``finally``: a test that times out must not leave a task holding
    database locks, or the clean-up after it waits on them forever instead of
    the timeout being reported.
    """
    running = [task for task in tasks if task is not None]
    for task in running:
        if not task.done():
            task.cancel()
    await asyncio.gather(*running, return_exceptions=True)
