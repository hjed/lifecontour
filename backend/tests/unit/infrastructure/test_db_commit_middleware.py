"""Unit tests for the commit-before-response backstop middleware (issue #945)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from starlette.types import Receive, Scope, Send

from app.infrastructure.db_commit_middleware import CommitOnResponseMiddleware
from app.infrastructure.unit_of_work import (
    EXTERNAL_TRANSACTION_MARKER,
    request_connection,
)


class _FakeConn:
    def __init__(self, *, in_txn: bool = True, external: bool = False) -> None:
        self.info: dict[str, Any] = (
            {EXTERNAL_TRANSACTION_MARKER: True} if external else {}
        )
        self._in_txn = in_txn
        self.commits = 0
        self.rollbacks = 0

    def in_transaction(self) -> bool:
        return self._in_txn

    async def commit(self) -> None:
        self.commits += 1
        self._in_txn = False

    async def rollback(self) -> None:
        self.rollbacks += 1
        self._in_txn = False


def _inner_app(status: int) -> Any:
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    return app


@asynccontextmanager
async def _published(conn: _FakeConn | None) -> AsyncIterator[None]:
    """Publish ``conn`` via the request_connection ContextVar, as the provider does."""
    token = request_connection.set(conn)  # type: ignore[arg-type]
    try:
        yield
    finally:
        request_connection.reset(token)


async def _run(mw: CommitOnResponseMiddleware, scope: dict[str, Any]) -> None:
    async def send(_message: Any) -> None:
        return None

    async def receive() -> dict[str, Any]:
        return {"type": "http.request"}

    await mw(scope, receive, send)


def _scope(method: str = "POST", path: str = "/api/x") -> dict[str, Any]:
    return {"type": "http", "method": method, "path": path, "state": {}}


@pytest.mark.asyncio
async def test_commits_successful_write() -> None:
    conn = _FakeConn(in_txn=True)
    mw = CommitOnResponseMiddleware(_inner_app(201))
    async with _published(conn):
        await _run(mw, _scope("POST"))
    assert conn.commits == 1
    assert conn.rollbacks == 0


@pytest.mark.asyncio
async def test_rolls_back_error_responses() -> None:
    conn = _FakeConn(in_txn=True)
    mw = CommitOnResponseMiddleware(_inner_app(500))
    async with _published(conn):
        await _run(mw, _scope("POST"))
    assert conn.commits == 0
    assert conn.rollbacks == 1  # error writes discarded, not left for teardown


@pytest.mark.asyncio
async def test_skips_get_requests() -> None:
    conn = _FakeConn(in_txn=True)
    mw = CommitOnResponseMiddleware(_inner_app(200))
    async with _published(conn):
        await _run(mw, _scope("GET"))
    assert conn.commits == 0
    assert conn.rollbacks == 0


@pytest.mark.asyncio
async def test_skips_when_no_connection_opened() -> None:
    # No connection published (request never touched the DB): nothing happens,
    # and no connection is force-created.
    mw = CommitOnResponseMiddleware(_inner_app(200))
    async with _published(None):
        await _run(mw, _scope("POST"))  # must not raise


@pytest.mark.asyncio
async def test_skips_when_external_transaction_marker_set() -> None:
    conn = _FakeConn(in_txn=True, external=True)
    mw = CommitOnResponseMiddleware(_inner_app(200))
    async with _published(conn):
        await _run(mw, _scope("POST"))
    assert conn.commits == 0  # test isolation preserved
    assert conn.rollbacks == 0  # connection left untouched


@pytest.mark.asyncio
async def test_no_commit_when_not_in_transaction() -> None:
    conn = _FakeConn(in_txn=False)
    mw = CommitOnResponseMiddleware(_inner_app(200))
    async with _published(conn):
        await _run(mw, _scope("POST"))
    assert conn.commits == 0


@pytest.mark.asyncio
async def test_skips_configured_path_prefix() -> None:
    conn = _FakeConn(in_txn=True)
    mw = CommitOnResponseMiddleware(_inner_app(200), skip_path_prefix="/mcp-server")
    async with _published(conn):
        await _run(mw, _scope("POST", path="/mcp-server/mcp"))
    assert conn.commits == 0
    assert conn.rollbacks == 0
