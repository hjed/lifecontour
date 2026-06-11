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


@pytest.mark.asyncio
async def test_request_connection_has_active_transaction(test_settings) -> None:
    """The yielded request connection must already be in a transaction.

    Repositories such as ActivityTemplateRepository.save() assert this before
    issuing their first statement, so the provider must begin a transaction up
    front. Commit timing is owned by the service layer (mid-request), and the
    provider never commits at teardown — any still-open (e.g. read) transaction
    is rolled back when the connection closes.
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
            # Drive provider teardown (closes the connection, rolling back the
            # uncommitted read transaction — the provider commits nothing).
            with pytest.raises(StopAsyncIteration):
                await anext(it)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_teardown_discards_uncommitted_write(test_settings) -> None:
    """The provider never commits at teardown.

    A write made without a service-layer unit of work must be rolled back when
    the connection closes — not silently persisted. This is the key guarantee
    that replaced the old commit backstop, so a regression here would re-open
    the "response before commit" / accidental-commit hole.
    """
    provider = DatabaseProvider(test_settings)
    engine = provider.get_engine()
    table = "conn_provider_uncommitted_write_test"
    try:
        # Arrange: a throwaway table, created and committed out of band.
        async with engine.begin() as setup:
            await setup.execute(text(f"DROP TABLE IF EXISTS {table}"))
            await setup.execute(text(f"CREATE TABLE {table} (id integer)"))

        # Act: write a row through a provider connection WITHOUT a unit of work,
        # then drive teardown.
        it = aiter(provider.get_connection(engine))
        conn = await anext(it)
        await conn.execute(text(f"INSERT INTO {table} (id) VALUES (1)"))
        with pytest.raises(StopAsyncIteration):
            await anext(it)  # teardown closes/rolls back; it commits nothing

        # Assert: the write was discarded, not persisted.
        async with engine.connect() as check:
            count = (
                await check.execute(text(f"SELECT count(*) FROM {table}"))
            ).scalar()
        assert count == 0, "teardown must not commit an uncommitted write"
    finally:
        async with engine.begin() as cleanup:
            await cleanup.execute(text(f"DROP TABLE IF EXISTS {table}"))
        await engine.dispose()
