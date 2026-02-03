"""
Integration tests for periodic sync functionality.

Tests the complete periodic sync flow including:
- Database queries for active Google integrations
- Job enqueueing for each account
- Metrics tracking and error handling
"""

import asyncio
import os
import sys
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from arq import create_pool
from arq.connections import RedisSettings

sys.path.insert(0, "/core_shared")

from core_shared.database.engine import create_session_factory
from sqlalchemy import text


@pytest.fixture(scope="module")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def redis_pool():
    """Create Redis pool for ARQ."""
    redis_host = os.getenv("REDIS_HOST", "localhost")
    settings = RedisSettings(host=redis_host, port=6379)
    pool = await create_pool(settings)
    yield pool
    await pool.close()


@pytest_asyncio.fixture
async def db_session():
    """Create database session for tests."""
    database_url = os.getenv(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/test_db"
    )
    session_factory = create_session_factory(database_url)

    async with session_factory() as session:
        yield session


@pytest.mark.integration
class TestPeriodicSyncIntegration:
    """Integration tests for periodic sync functionality."""

    @pytest.mark.asyncio
    async def test_periodic_sync_queries_active_integrations(
        self, db_session, redis_pool
    ):
        """Test that periodic_sync_all_accounts queries active Google integrations."""
        import worker

        # Insert test data: 2 active integrations, 1 inactive
        await db_session.execute(
            text("""
                INSERT INTO user_google_auth (user_id, google_account_email, is_active, access_token, refresh_token, token_expiry)
                VALUES
                    (1, 'active1@example.com', true, 'token1', 'refresh1', :expiry),
                    (2, 'active2@example.com', true, 'token2', 'refresh2', :expiry),
                    (3, 'inactive@example.com', false, 'token3', 'refresh3', :expiry)
                ON CONFLICT (user_id, google_account_email) DO UPDATE
                SET is_active = EXCLUDED.is_active
            """),
            {"expiry": datetime.now(UTC)},
        )
        await db_session.commit()

        # Create context with session_factory
        session_factory = create_session_factory(
            os.getenv(
                "DATABASE_URL",
                "postgresql://postgres:postgres@localhost:5432/test_db",
            )
        )
        ctx = {"redis": redis_pool, "session_factory": session_factory}

        # Call periodic sync
        result = await worker.periodic_sync_all_accounts(ctx)

        # Verify result
        assert result["status"] == "success"
        assert result["accounts_found"] == 2  # Only active accounts
        assert result["jobs_enqueued"] == 2
        assert len(result["errors"]) == 0

    @pytest.mark.asyncio
    async def test_periodic_sync_enqueues_jobs_for_each_account(
        self, db_session, redis_pool
    ):
        """Test that periodic sync enqueues individual sync jobs."""
        import worker

        # Insert test data
        await db_session.execute(
            text("""
                INSERT INTO user_google_auth (user_id, google_account_email, is_active, access_token, refresh_token, token_expiry)
                VALUES
                    (10, 'test1@example.com', true, 'token1', 'refresh1', :expiry),
                    (11, 'test2@example.com', true, 'token2', 'refresh2', :expiry)
                ON CONFLICT (user_id, google_account_email) DO UPDATE
                SET is_active = EXCLUDED.is_active
            """),
            {"expiry": datetime.now(UTC)},
        )
        await db_session.commit()

        # Create context
        session_factory = create_session_factory(
            os.getenv(
                "DATABASE_URL",
                "postgresql://postgres:postgres@localhost:5432/test_db",
            )
        )
        ctx = {"redis": redis_pool, "session_factory": session_factory}

        # Call periodic sync
        result = await worker.periodic_sync_all_accounts(ctx)

        # Verify jobs were enqueued
        assert result["jobs_enqueued"] == 2

        # Note: We can't easily verify the actual jobs in Redis without
        # starting the worker, but we've verified the enqueue calls succeeded

    @pytest.mark.asyncio
    async def test_periodic_sync_handles_no_active_accounts(
        self, db_session, redis_pool
    ):
        """Test periodic sync when no active accounts exist."""
        import worker

        # Ensure no active accounts (set all to inactive)
        await db_session.execute(
            text("""
                UPDATE user_google_auth
                SET is_active = false
            """)
        )
        await db_session.commit()

        # Create context
        session_factory = create_session_factory(
            os.getenv(
                "DATABASE_URL",
                "postgresql://postgres:postgres@localhost:5432/test_db",
            )
        )
        ctx = {"redis": redis_pool, "session_factory": session_factory}

        # Call periodic sync
        result = await worker.periodic_sync_all_accounts(ctx)

        # Verify result
        assert result["status"] == "success"
        assert result["accounts_found"] == 0
        assert result["jobs_enqueued"] == 0
        assert len(result["errors"]) == 0

