"""Integration tests for the request connection provider (issue #945).

These exercise the *real* ``DatabaseProvider.get_connection`` (commit-as-you-go),
not the savepoint test fixture — which is the only place the production
connection lifecycle is covered. A regression here (no active transaction at
request start) broke repositories that assert ``conn.in_transaction()``, e.g.
``ActivityTemplateRepository.save``, on the real backend while integration tests
(whose fixture begins a transaction) still passed.
"""

import pytest
from sqlalchemy import text

from app.infrastructure.di.database import DatabaseProvider
from app.infrastructure.unit_of_work import request_connection


@pytest.mark.asyncio
async def test_request_connection_has_active_transaction(test_settings) -> None:
    """The yielded request connection must already be in a transaction.

    Repositories such as ActivityTemplateRepository.save() assert this before
    issuing their first statement, so the provider must begin a transaction up
    front (commit timing is still mid-request, not at teardown).
    """
    provider = DatabaseProvider(test_settings)
    engine = provider.get_engine()
    try:
        it = aiter(provider.get_connection(engine))
        conn = await anext(it)
        try:
            assert conn.in_transaction(), (
                "request connection must have an active transaction at yield"
            )
            # And it is usable for a real statement.
            result = await conn.execute(text("SELECT 1"))
            assert result.scalar() == 1
        finally:
            # Drive provider teardown (commits the read transaction as the net).
            with pytest.raises(StopAsyncIteration):
                await anext(it)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_provider_publishes_request_connection_contextvar(test_settings) -> None:
    """The provider publishes the live connection for the commit middleware,
    and resets it on teardown (so non-DB requests never expose a stale one)."""
    assert request_connection.get() is None
    provider = DatabaseProvider(test_settings)
    engine = provider.get_engine()
    try:
        it = aiter(provider.get_connection(engine))
        conn = await anext(it)
        assert request_connection.get() is conn
        with pytest.raises(StopAsyncIteration):
            await anext(it)
        assert request_connection.get() is None  # reset on teardown
    finally:
        await engine.dispose()
