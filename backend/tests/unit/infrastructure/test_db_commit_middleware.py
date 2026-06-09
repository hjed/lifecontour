"""Unit tests for the commit-before-response backstop middleware (issue #945)."""

from typing import Any

import pytest
from starlette.types import Receive, Scope, Send

from app.infrastructure.db_commit_middleware import CommitOnResponseMiddleware
from app.infrastructure.unit_of_work import EXTERNAL_TRANSACTION_MARKER


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


class _FakeContainer:
    def __init__(self, conn: _FakeConn) -> None:
        self.conn = conn

    async def get(self, _type: object) -> _FakeConn:
        return self.conn


def _inner_app(status: int) -> Any:
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    return app


async def _receive() -> dict[str, Any]:
    return {"type": "http.request"}


async def _run(mw: CommitOnResponseMiddleware, scope: dict[str, Any]) -> None:
    async def send(_message: Any) -> None:
        return None

    await mw(scope, _receive, send)


def _scope(
    method: str = "POST", path: str = "/api/x", *, conn: Any = None
) -> dict[str, Any]:
    state = {"dishka_container": _FakeContainer(conn)} if conn is not None else {}
    return {"type": "http", "method": method, "path": path, "state": state}


@pytest.mark.asyncio
async def test_commits_successful_write() -> None:
    conn = _FakeConn(in_txn=True)
    mw = CommitOnResponseMiddleware(_inner_app(201))
    await _run(mw, _scope("POST", conn=conn))
    assert conn.commits == 1


@pytest.mark.asyncio
async def test_skips_get_requests() -> None:
    conn = _FakeConn(in_txn=True)
    mw = CommitOnResponseMiddleware(_inner_app(200))
    await _run(mw, _scope("GET", conn=conn))
    assert conn.commits == 0


@pytest.mark.asyncio
async def test_rolls_back_error_responses() -> None:
    conn = _FakeConn(in_txn=True)
    mw = CommitOnResponseMiddleware(_inner_app(500))
    await _run(mw, _scope("POST", conn=conn))
    assert conn.commits == 0
    assert conn.rollbacks == 1  # error writes discarded, not left for teardown


@pytest.mark.asyncio
async def test_skips_when_external_transaction_marker_set() -> None:
    conn = _FakeConn(in_txn=True, external=True)
    mw = CommitOnResponseMiddleware(_inner_app(200))
    await _run(mw, _scope("POST", conn=conn))
    assert conn.commits == 0  # test isolation preserved
    assert conn.rollbacks == 0  # connection left untouched


@pytest.mark.asyncio
async def test_no_commit_when_not_in_transaction() -> None:
    conn = _FakeConn(in_txn=False)
    mw = CommitOnResponseMiddleware(_inner_app(200))
    await _run(mw, _scope("POST", conn=conn))
    assert conn.commits == 0


@pytest.mark.asyncio
async def test_skips_configured_path_prefix() -> None:
    conn = _FakeConn(in_txn=True)
    mw = CommitOnResponseMiddleware(_inner_app(200), skip_path_prefix="/mcp-server")
    await _run(mw, _scope("POST", path="/mcp-server/mcp", conn=conn))
    assert conn.commits == 0
    assert conn.rollbacks == 0
