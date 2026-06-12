"""Unit tests for the service-layer unit-of-work helpers (issue #945)."""

from typing import Any

import pytest

from app.infrastructure.unit_of_work import (
    EXTERNAL_TRANSACTION_MARKER,
    in_external_transaction,
    savepoint,
    transactional,
    unit_of_work,
)


class _FakeSavepoint:
    def __init__(self) -> None:
        self.committed = 0
        self.rolled_back = 0

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        self.rolled_back += 1


class _FakeConnection:
    """Minimal stand-in for AsyncConnection used by the UoW helpers."""

    def __init__(self) -> None:
        self.info: dict[str, Any] = {}
        self.commits = 0
        self.rollbacks = 0
        self.savepoints: list[_FakeSavepoint] = []

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def begin_nested(self) -> _FakeSavepoint:
        sp = _FakeSavepoint()
        self.savepoints.append(sp)
        return sp


def _conn() -> Any:
    """Return a fake connection typed as Any so it satisfies the helpers."""
    return _FakeConnection()


class _Boom(Exception):
    pass


@pytest.mark.asyncio
async def test_commits_on_success() -> None:
    conn = _conn()
    async with unit_of_work(conn):
        pass
    assert conn.commits == 1
    assert conn.rollbacks == 0
    assert conn.savepoints == []  # real commit, not a savepoint


@pytest.mark.asyncio
async def test_rolls_back_and_reraises_on_error() -> None:
    conn = _conn()
    with pytest.raises(_Boom):
        async with unit_of_work(conn):
            raise _Boom
    assert conn.commits == 0
    assert conn.rollbacks == 1


@pytest.mark.asyncio
async def test_reentrant_commits_exactly_once() -> None:
    conn = _conn()
    async with unit_of_work(conn):
        async with unit_of_work(conn):  # nested: joins outer unit of work
            pass
    assert conn.commits == 1  # only the outermost commits


@pytest.mark.asyncio
async def test_reentrant_inner_error_rolls_back_once_at_outer() -> None:
    conn = _conn()
    with pytest.raises(_Boom):
        async with unit_of_work(conn):
            async with unit_of_work(conn):
                raise _Boom
    assert conn.commits == 0
    assert conn.rollbacks == 1  # outermost rolls back; inner does not


@pytest.mark.asyncio
async def test_depth_restored_after_error_so_next_uow_is_outermost() -> None:
    conn = _conn()
    with pytest.raises(_Boom):
        async with unit_of_work(conn):
            raise _Boom
    assert conn.info.get("uow_depth", 0) == 0
    # A subsequent unit of work on the same connection still commits.
    async with unit_of_work(conn):
        pass
    assert conn.commits == 1


@pytest.mark.asyncio
async def test_external_transaction_uses_savepoint_not_real_commit() -> None:
    conn = _conn()
    conn.info[EXTERNAL_TRANSACTION_MARKER] = True
    async with unit_of_work(conn):
        pass
    assert conn.commits == 0  # never commits the test-owned outer transaction
    assert conn.rollbacks == 0
    assert len(conn.savepoints) == 1
    assert conn.savepoints[0].committed == 1  # savepoint released


@pytest.mark.asyncio
async def test_external_transaction_savepoint_rolls_back_on_error() -> None:
    conn = _conn()
    conn.info[EXTERNAL_TRANSACTION_MARKER] = True
    with pytest.raises(_Boom):
        async with unit_of_work(conn):
            raise _Boom
    assert conn.commits == 0
    assert conn.rollbacks == 0
    assert conn.savepoints[0].rolled_back == 1


@pytest.mark.asyncio
async def test_savepoint_helper_releases_on_success() -> None:
    conn = _conn()
    async with savepoint(conn):
        pass
    assert conn.savepoints[0].committed == 1
    assert conn.commits == 0  # savepoint does not touch the outer transaction


@pytest.mark.asyncio
async def test_savepoint_helper_rolls_back_and_reraises_on_error() -> None:
    conn = _conn()
    with pytest.raises(_Boom):
        async with savepoint(conn):
            raise _Boom
    assert conn.savepoints[0].rolled_back == 1


@pytest.mark.asyncio
async def test_savepoint_noop_when_connection_none() -> None:
    # The unit-test sentinel: no connection means no SAVEPOINT, so services can
    # wrap a write in savepoint() and still be unit-tested with transaction=None.
    async with savepoint(None) as yielded:
        assert yielded is None


def test_transactional_fails_fast_without_transaction_param() -> None:
    with pytest.raises(TypeError, match="requires a 'transaction' parameter"):

        @transactional
        async def writer(value: int) -> int:  # no `transaction` parameter
            return value


@pytest.mark.asyncio
async def test_transactional_skips_uow_for_non_connection_arg() -> None:
    conn = _conn()

    @transactional
    async def writer(transaction: Any) -> str:
        return "ok"

    # _FakeConnection is not an AsyncConnection, so the decorator skips the
    # unit of work (the unit-test path) and the method still runs cleanly.
    assert await writer(conn) == "ok"
    assert conn.commits == 0


def test_in_external_transaction_helper() -> None:
    conn = _conn()
    assert in_external_transaction(conn) is False
    conn.info[EXTERNAL_TRANSACTION_MARKER] = True
    assert in_external_transaction(conn) is True
