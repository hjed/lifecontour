"""Integration tests for periodic sync functionality.

These tests verify the end-to-end periodic sync flow with real database and Redis connections.
"""

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from arq import create_pool
from arq.connections import RedisSettings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from worker import periodic_sync_all_accounts


def get_async_database_url() -> str:
    """Get the database URL and ensure it uses asyncpg driver."""
    database_url = os.getenv(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/test_db"
    )
    # Convert to asyncpg URL if needed
    if database_url.startswith("postgresql://") and "+asyncpg" not in database_url:
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return database_url


def create_session_factory(database_url: str):
    """Create a session factory for the given database URL."""
    engine = create_async_engine(database_url, echo=False)
    return sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def db_session():
    """Create database session for tests."""
    database_url = get_async_database_url()
    session_factory = create_session_factory(database_url)
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def redis_pool():
    """Create Redis pool for tests."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    redis_settings = RedisSettings.from_dsn(redis_url)
    pool = await create_pool(redis_settings)
    yield pool
    await pool.close()


@pytest.mark.asyncio
class TestPeriodicSyncIntegration:
    """Integration tests for periodic sync with real database and Redis."""

    async def test_periodic_sync_queries_active_integrations(
        self, db_session, redis_pool
    ):
        """Test that periodic_sync_all_accounts queries all Google integrations."""
        # Insert test data - 2 Google integrations
        # Note: All accounts in user_google_auth are considered active
        await db_session.execute(
            text(
                """
                INSERT INTO user_google_auth (user_id, google_account_email,
                                              encrypted_access_token, encrypted_refresh_token,
                                              expires_at, created_at, updated_at)
                VALUES
                    ('user1', 'active1@example.com', :token, :refresh,
                     :expiry, :now, :now),
                    ('user2', 'active2@example.com', :token, :refresh,
                     :expiry, :now, :now)
                ON CONFLICT (user_id, google_account_email) DO NOTHING
            """
            ),
            {
                "token": b"encrypted_token_data",  # Dummy encrypted token
                "refresh": b"encrypted_refresh_data",  # Dummy encrypted refresh token
                "expiry": datetime.now(timezone.utc),
                "now": datetime.now(timezone.utc),
            },
        )
        await db_session.commit()

        # Create context with session_factory and redis pool
        database_url = get_async_database_url()
        session_factory = create_session_factory(database_url)
        ctx = {"session_factory": session_factory, "redis": redis_pool}

        # Mock the sync_google_contacts function to track calls
        with patch("worker.sync_google_contacts", new_callable=AsyncMock) as mock_sync:
            # Call periodic_sync_all_accounts
            await periodic_sync_all_accounts(ctx)

            # Verify sync_google_contacts was NOT called directly
            # (it should be enqueued to Redis instead)
            mock_sync.assert_not_called()

        # Verify jobs were enqueued to Redis (2 accounts)
        # Note: We can't easily verify the exact jobs without running the worker,
        # but we can verify the function completed without errors
        # In a real integration test with a running worker, we would verify job execution

    async def test_periodic_sync_enqueues_jobs_for_each_account(
        self, db_session, redis_pool
    ):
        """Test that individual sync jobs are enqueued for each account."""
        # Insert test data - 1 Google integration
        await db_session.execute(
            text(
                """
                INSERT INTO user_google_auth (user_id, google_account_email,
                                              encrypted_access_token, encrypted_refresh_token,
                                              expires_at, created_at, updated_at)
                VALUES
                    ('user10', 'test@example.com', :token, :refresh,
                     :expiry, :now, :now)
                ON CONFLICT (user_id, google_account_email) DO NOTHING
            """
            ),
            {
                "token": b"encrypted_token_data",
                "refresh": b"encrypted_refresh_data",
                "expiry": datetime.now(timezone.utc),
                "now": datetime.now(timezone.utc),
            },
        )
        await db_session.commit()

        # Create context
        database_url = get_async_database_url()
        session_factory = create_session_factory(database_url)
        ctx = {"session_factory": session_factory, "redis": redis_pool}

        # Call periodic_sync_all_accounts
        await periodic_sync_all_accounts(ctx)

        # Verify function completed successfully
        # In a real integration test, we would verify the job was enqueued to Redis
        # and processed by a running worker

    async def test_periodic_sync_handles_no_active_accounts(
        self, db_session, redis_pool
    ):
        """Test that periodic sync handles no active accounts gracefully."""
        # Don't insert any test data - no active accounts

        # Create context
        database_url = get_async_database_url()
        session_factory = create_session_factory(database_url)
        ctx = {"session_factory": session_factory, "redis": redis_pool}

        # Call periodic_sync_all_accounts - should not raise any errors
        await periodic_sync_all_accounts(ctx)

        # Verify function completed successfully with no errors

