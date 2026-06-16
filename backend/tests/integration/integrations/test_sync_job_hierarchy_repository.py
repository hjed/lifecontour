"""Integration tests for SyncJobRepository fan-out hierarchy support.

These exercise the parent/child schema and the atomic child-counter increments
against real PostgreSQL via asyncpg. Mocked unit tests cannot verify that the
``UPDATE ... SET col = col + 1`` increments are atomic under concurrent
connections, nor that the self-referencing ``parent_job_id`` foreign key and the
``in_progress`` check-constraint value behave correctly; only a real round trip
does.
"""

from __future__ import annotations

import asyncio

import pytest
from core_shared.models.sync_job import SyncJobStatus
from core_shared.repositories.sync_job_repository import SyncJobRepository
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine


@pytest.mark.integration
class TestSyncJobHierarchyRepository:
    """Real-database tests for the SyncJob parent/child hierarchy."""

    @pytest.fixture
    def repo(self, clean_database: AsyncConnection) -> SyncJobRepository:
        """Create the repository with a real database connection."""
        return SyncJobRepository(clean_database)

    async def _create_parent(
        self, repo: SyncJobRepository, job_id: str = "parent-1"
    ) -> str:
        """Create a top-level (parent) sync job and return its job_id."""
        await repo.create(
            job_id=job_id,
            user_id="user-1",
            integration_source="immich",
            sync_type="full",
            status=SyncJobStatus.IN_PROGRESS.value,
        )
        return job_id

    @pytest.mark.asyncio
    async def test_in_progress_status_is_accepted_by_constraint(
        self, repo: SyncJobRepository
    ) -> None:
        """A job can be persisted with the new IN_PROGRESS status."""
        job = await repo.create(
            job_id="parent-status",
            user_id="user-1",
            integration_source="immich",
            sync_type="full",
            status=SyncJobStatus.IN_PROGRESS.value,
        )
        assert job.status == "in_progress"

        fetched = await repo.get_by_job_id("parent-status")
        assert fetched is not None
        assert fetched.status == "in_progress"

    @pytest.mark.asyncio
    async def test_create_children_and_list_by_parent(
        self, repo: SyncJobRepository
    ) -> None:
        """Children link to their parent and are queryable by parent_job_id."""
        parent_id = await self._create_parent(repo)
        # An unrelated top-level job that must be excluded from the result.
        await repo.create(
            job_id="other-top-level",
            user_id="user-1",
            integration_source="immich",
            sync_type="full",
        )

        for i in range(3):
            child = await repo.create(
                job_id=f"child-{i}",
                user_id="user-1",
                integration_source="immich",
                sync_type="full",
                parent_job_id=parent_id,
            )
            assert child.parent_job_id == parent_id

        children = await repo.list_children(parent_id)

        assert len(children) == 3
        assert {c.job_id for c in children} == {"child-0", "child-1", "child-2"}
        assert all(c.parent_job_id == parent_id for c in children)

    @pytest.mark.asyncio
    async def test_set_expected_children_persists(
        self, repo: SyncJobRepository
    ) -> None:
        """set_expected_children updates the parent and is durable."""
        parent_id = await self._create_parent(repo)

        updated = await repo.set_expected_children(parent_id, 7)
        assert updated is not None
        assert updated.expected_children == 7

        fetched = await repo.get_by_job_id(parent_id)
        assert fetched is not None
        assert fetched.expected_children == 7

    @pytest.mark.asyncio
    async def test_increment_counters_accumulate_independently(
        self, repo: SyncJobRepository
    ) -> None:
        """Sequential increments accumulate; completed/failed stay independent."""
        parent_id = await self._create_parent(repo)

        for _ in range(25):
            await repo.increment_completed_children(parent_id)
        for _ in range(4):
            await repo.increment_failed_children(parent_id)

        fetched = await repo.get_by_job_id(parent_id)
        assert fetched is not None
        assert fetched.completed_children == 25
        assert fetched.failed_children == 4

    @pytest.mark.asyncio
    async def test_aggregate_children_counts_by_status(
        self, repo: SyncJobRepository
    ) -> None:
        """aggregate_children reflects the actual child rows (authoritative)."""
        parent_id = await self._create_parent(repo)

        statuses = [
            SyncJobStatus.COMPLETED.value,
            SyncJobStatus.COMPLETED.value,
            SyncJobStatus.COMPLETED.value,
            SyncJobStatus.FAILED.value,
            SyncJobStatus.RUNNING.value,
        ]
        for i, status in enumerate(statuses):
            await repo.create(
                job_id=f"agg-child-{i}",
                user_id="user-1",
                integration_source="immich",
                sync_type="full",
                status=status,
                parent_job_id=parent_id,
            )

        counts = await repo.aggregate_children(parent_id)

        assert counts["total"] == 5
        assert counts["completed"] == 3
        assert counts["failed"] == 1

    @pytest.mark.asyncio
    async def test_aggregate_children_empty_parent(
        self, repo: SyncJobRepository
    ) -> None:
        """A parent with no children aggregates to zeroes."""
        parent_id = await self._create_parent(repo)

        counts = await repo.aggregate_children(parent_id)

        assert counts == {"total": 0, "completed": 0, "failed": 0}


@pytest.mark.integration
@pytest.mark.slow
class TestSyncJobCounterConcurrency:
    """Verify counter increments are atomic under genuine concurrency.

    A single asyncpg connection serializes statements, so true concurrency
    requires independent connections. These commit outside the test's savepoint
    isolation, so the test uses a uniquely-keyed parent and deletes everything it
    creates in a ``finally`` block.
    """

    @pytest.mark.asyncio
    async def test_concurrent_increments_have_no_lost_updates(
        self, async_engine: AsyncEngine
    ) -> None:
        parent_id = "concurrency-parent-iter14-003"
        increments = 50

        async def _setup() -> None:
            async with async_engine.begin() as conn:
                repo = SyncJobRepository(conn)
                await repo.create(
                    job_id=parent_id,
                    user_id="user-concurrency",
                    integration_source="immich",
                    sync_type="full",
                    status=SyncJobStatus.IN_PROGRESS.value,
                )

        async def _one_increment() -> None:
            async with async_engine.begin() as conn:
                repo = SyncJobRepository(conn)
                await repo.increment_completed_children(parent_id)

        async def _cleanup() -> None:
            async with async_engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM sync_jobs WHERE job_id = :job_id"),
                    {"job_id": parent_id},
                )

        await _cleanup()  # guard against a leaked row from a prior failed run
        try:
            await _setup()
            await asyncio.gather(*(_one_increment() for _ in range(increments)))

            async with async_engine.connect() as conn:
                repo = SyncJobRepository(conn)
                fetched = await repo.get_by_job_id(parent_id)
            assert fetched is not None
            assert fetched.completed_children == increments
        finally:
            await _cleanup()
