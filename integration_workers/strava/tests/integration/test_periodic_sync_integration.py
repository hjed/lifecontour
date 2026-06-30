"""
Integration tests for Strava periodic sync.
"""

from __future__ import annotations

import datetime
import os
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.testing.integration import get_async_database_url
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

os.environ["STRAVA_CLIENT_ID"] = "test"
os.environ["STRAVA_CLIENT_SECRET"] = "test"
os.environ["ENCRYPTION_KEY"] = "dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdGtleXQ9"
os.environ["DATABASE_URL"] = get_async_database_url()

from worker import periodic_sync_all_strava_accounts


@pytest.mark.asyncio
async def test_periodic_sync_all_strava_accounts_integration(
    db_session: AsyncSession,
) -> None:
    """Test that periodic_sync reads from the actual user_strava_auth table."""

    # Insert test data
    insert_stmt = text("""
        INSERT INTO user_strava_auth (
            user_id, athlete_id, encrypted_access_token, encrypted_refresh_token,
            expires_at, needs_reauth, created_at, updated_at
        ) VALUES (
            :user_id, :athlete_id, :access_token, :refresh_token,
            :expires_at, :needs_reauth, now(), now()
        )
    """)

    await db_session.execute(
        insert_stmt,
        {
            "user_id": "test-integration-user-1",
            "athlete_id": 999111,
            "access_token": b"fake-access",
            "refresh_token": b"fake-refresh",
            "expires_at": datetime.datetime.now(datetime.UTC),
            "needs_reauth": False,
        },
    )

    await db_session.execute(
        insert_stmt,
        {
            "user_id": "test-integration-user-2",
            "athlete_id": 999222,
            "access_token": b"fake-access2",
            "refresh_token": b"fake-refresh2",
            "expires_at": datetime.datetime.now(datetime.UTC),
            "needs_reauth": False,
        },
    )

    await db_session.flush()

    # Create mock context
    @asynccontextmanager
    async def session_factory():
        # Yield the already-transactional db_session
        yield db_session

    mock_redis = AsyncMock()
    mock_job = MagicMock()
    mock_job.job_id = "test-job-id"
    mock_redis.enqueue_job = AsyncMock(return_value=mock_job)

    ctx: dict[str, Any] = {
        "session_factory": session_factory,
        "redis": mock_redis,
    }

    # Run the function
    result = await periodic_sync_all_strava_accounts(ctx)

    assert result["status"] == "success"
    # Depending on whether there was existing data in DB or just ours,
    # it should find at least 2 accounts
    assert result["accounts_found"] >= 2
    assert result["jobs_enqueued"] == result["accounts_found"]

    # Verify our specific users were enqueued
    enqueued_users = []
    for call in mock_redis.enqueue_job.call_args_list:
        assert call[0][0] == "sync_strava_activities"
        enqueued_users.append(call[0][1])
        assert call[0][2] == "smart"  # sync_type

    assert "test-integration-user-1" in enqueued_users
    assert "test-integration-user-2" in enqueued_users
