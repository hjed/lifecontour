"""
Integration tests for the Snipe-IT periodic asset and maintenance sync.

Verifies that ``periodic_sync_all_snipeit_accounts`` reads the real
``snipeit_settings`` / ``user_snipe_it_auth`` tables, enqueues a smart asset and
maintenance sync for every account a sync can run for, and records a
``sync_jobs`` row for each enqueued job.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession


async def _insert_auth(
    async_connection: AsyncConnection, user_id: str, *, needs_reauth: bool = False
) -> None:
    await async_connection.execute(
        text("""
            INSERT INTO user_snipe_it_auth (
                user_id, encrypted_api_key, needs_reauth, created_at, updated_at
            ) VALUES (:user_id, 'enc-api-key', :needs_reauth, now(), now())
        """),
        {"user_id": user_id, "needs_reauth": needs_reauth},
    )


async def _insert_settings(async_connection: AsyncConnection, user_id: str) -> None:
    await async_connection.execute(
        text("""
            INSERT INTO snipeit_settings (
                user_id, base_url, snipeit_user_id, webhook_token,
                created_at, updated_at
            ) VALUES (
                :user_id, 'https://snipeit.example.com', '1', :webhook_token,
                now(), now()
            )
        """),
        {"user_id": user_id, "webhook_token": f"webhook-token-{user_id}"},
    )


class _RecordingRedis:
    """Records enqueued jobs and answers each with a job named after it."""

    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def enqueue_job(self, function: str, *args: Any, **kwargs: Any) -> Any:
        self.jobs.append((function, args, kwargs))
        return MagicMock(job_id=f"{function}:{args[0]}")


@pytest.mark.asyncio
async def test_periodic_sync_enqueues_and_records_jobs_for_usable_accounts(
    async_connection: AsyncConnection,
) -> None:
    """Only accounts with settings and working auth are synced, each twice over:
    once for assets and once for maintenance records, both recorded as queued."""
    from core_shared.integration_constants import SNIPEIT_ARQ_QUEUE_NAME

    from worker import periodic_sync_all_snipeit_accounts

    prefix = f"periodic-{uuid4().hex[:8]}"
    ready_a = f"{prefix}-a"
    ready_b = f"{prefix}-b"
    needs_reauth = f"{prefix}-reauth"
    no_settings = f"{prefix}-no-settings"

    for user_id in (ready_a, ready_b, needs_reauth):
        await _insert_settings(async_connection, user_id)
    await _insert_auth(async_connection, ready_a)
    await _insert_auth(async_connection, ready_b)
    await _insert_auth(async_connection, needs_reauth, needs_reauth=True)
    await _insert_auth(async_connection, no_settings)

    @asynccontextmanager
    async def session_factory() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(
            async_connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ) as session:
            yield session

    redis = _RecordingRedis()
    result = await periodic_sync_all_snipeit_accounts(
        {"session_factory": session_factory, "redis": redis}
    )

    ours = [job for job in redis.jobs if job[1][0].startswith(prefix)]
    assert [(function, args) for function, args, _ in ours] == [
        ("sync_snipeit_assets", (ready_a, "smart")),
        ("sync_snipeit_maintenances", (ready_a, "smart")),
        ("sync_snipeit_assets", (ready_b, "smart")),
        ("sync_snipeit_maintenances", (ready_b, "smart")),
    ]
    assert all(kwargs["_queue_name"] == SNIPEIT_ARQ_QUEUE_NAME for *_, kwargs in ours)
    assert result["errors"] == []
    assert result["jobs_enqueued"] == 2 * result["accounts_found"]

    rows = (
        await async_connection.execute(
            text("""
                SELECT job_id, user_id, integration_source, sync_type, status
                FROM sync_jobs
                WHERE user_id LIKE :prefix
                ORDER BY user_id, job_id
            """),
            {"prefix": f"{prefix}%"},
        )
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        (f"sync_snipeit_assets:{ready_a}", ready_a, "snipeit", "smart", "queued"),
        (
            f"sync_snipeit_maintenances:{ready_a}",
            ready_a,
            "snipeit",
            "smart",
            "queued",
        ),
        (f"sync_snipeit_assets:{ready_b}", ready_b, "snipeit", "smart", "queued"),
        (
            f"sync_snipeit_maintenances:{ready_b}",
            ready_b,
            "snipeit",
            "smart",
            "queued",
        ),
    ]
