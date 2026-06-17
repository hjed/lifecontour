"""Integration tests for the shared fan-out reconciliation job.

These exercise ``reconcile_parents`` against real PostgreSQL: seed ``IN_PROGRESS``
parents with various child states and verify each is finalised correctly, plus
the no-op case (no in-progress parents) and the ``list_in_progress_parents``
query. Mocked unit tests cover the pure decision logic; only a real round trip
verifies the SQL filters, the authoritative child-row aggregation, and that the
status transition is persisted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from core_shared.models.sync_job import SyncJobStatus
from core_shared.repositories.sync_job_repository import SyncJobRepository
from core_shared.sync_reconciliation import reconcile_parents
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@pytest.mark.integration
class TestSyncJobReconciliation:
    """Real-database tests for reconcile_parents over IN_PROGRESS parents."""

    @pytest.fixture
    def repo(self, clean_database: AsyncConnection) -> SyncJobRepository:
        return SyncJobRepository(clean_database)

    async def _create_parent(
        self, repo: SyncJobRepository, job_id: str, expected_children: int
    ) -> str:
        await repo.create(
            job_id=job_id,
            user_id="user-1",
            integration_source="immich",
            sync_type="full",
            status=SyncJobStatus.IN_PROGRESS.value,
        )
        await repo.set_expected_children(job_id, expected_children)
        return job_id

    async def _create_children(
        self,
        repo: SyncJobRepository,
        parent_id: str,
        statuses: list[str],
    ) -> None:
        for i, status in enumerate(statuses):
            await repo.create(
                job_id=f"{parent_id}-child-{i}",
                user_id="user-1",
                integration_source="immich",
                sync_type="full",
                status=status,
                parent_job_id=parent_id,
            )

    @pytest.mark.asyncio
    async def test_all_children_completed_marks_parent_completed(
        self, repo: SyncJobRepository
    ) -> None:
        parent_id = await self._create_parent(repo, "parent-ok", 3)
        await self._create_children(
            repo, parent_id, [SyncJobStatus.COMPLETED.value] * 3
        )

        summary = await reconcile_parents(
            repo, now=datetime.now(UTC), stale_after_seconds=1800.0
        )

        assert summary["completed"] == 1
        assert summary["failed"] == 0
        parent = await repo.get_by_job_id(parent_id)
        assert parent is not None
        assert parent.status == SyncJobStatus.COMPLETED.value
        assert parent.completed_at is not None

    @pytest.mark.asyncio
    async def test_partial_failure_marks_parent_failed_with_message(
        self, repo: SyncJobRepository
    ) -> None:
        parent_id = await self._create_parent(repo, "parent-partial", 3)
        await self._create_children(
            repo,
            parent_id,
            [
                SyncJobStatus.COMPLETED.value,
                SyncJobStatus.COMPLETED.value,
                SyncJobStatus.FAILED.value,
            ],
        )

        summary = await reconcile_parents(
            repo, now=datetime.now(UTC), stale_after_seconds=1800.0
        )

        assert summary["failed"] == 1
        parent = await repo.get_by_job_id(parent_id)
        assert parent is not None
        assert parent.status == SyncJobStatus.FAILED.value
        assert parent.error_message

    @pytest.mark.asyncio
    async def test_all_children_failed_marks_parent_failed(
        self, repo: SyncJobRepository
    ) -> None:
        parent_id = await self._create_parent(repo, "parent-allfail", 2)
        await self._create_children(repo, parent_id, [SyncJobStatus.FAILED.value] * 2)

        await reconcile_parents(repo, now=datetime.now(UTC), stale_after_seconds=1800.0)

        parent = await repo.get_by_job_id(parent_id)
        assert parent is not None
        assert parent.status == SyncJobStatus.FAILED.value

    @pytest.mark.asyncio
    async def test_cancelled_child_finalises_parent_as_failed(
        self, repo: SyncJobRepository
    ) -> None:
        # A cancelled child is terminal; the parent must not be stranded in
        # IN_PROGRESS waiting for it to progress.
        parent_id = await self._create_parent(repo, "parent-cancelled", 2)
        await self._create_children(
            repo,
            parent_id,
            [SyncJobStatus.COMPLETED.value, SyncJobStatus.CANCELLED.value],
        )

        summary = await reconcile_parents(
            repo, now=datetime.now(UTC), stale_after_seconds=1800.0
        )

        assert summary["failed"] == 1
        assert summary["still_in_progress"] == 0
        parent = await repo.get_by_job_id(parent_id)
        assert parent is not None
        assert parent.status == SyncJobStatus.FAILED.value
        assert parent.error_message and "cancelled" in parent.error_message

    @pytest.mark.asyncio
    async def test_running_children_leave_parent_in_progress(
        self, repo: SyncJobRepository
    ) -> None:
        parent_id = await self._create_parent(repo, "parent-running", 2)
        await self._create_children(
            repo,
            parent_id,
            [SyncJobStatus.COMPLETED.value, SyncJobStatus.RUNNING.value],
        )

        summary = await reconcile_parents(
            repo, now=datetime.now(UTC), stale_after_seconds=1800.0
        )

        assert summary["still_in_progress"] == 1
        assert summary["completed"] == 0
        assert summary["failed"] == 0
        parent = await repo.get_by_job_id(parent_id)
        assert parent is not None
        assert parent.status == SyncJobStatus.IN_PROGRESS.value

    @pytest.mark.asyncio
    async def test_stuck_parent_is_marked_failed(
        self, repo: SyncJobRepository, clean_database: AsyncConnection
    ) -> None:
        parent_id = await self._create_parent(repo, "parent-stuck", 3)
        await self._create_children(
            repo,
            parent_id,
            [SyncJobStatus.COMPLETED.value, SyncJobStatus.RUNNING.value],
        )
        # Backdate the parent's updated_at well beyond the staleness window so it
        # is treated as a stuck fan-out that never progressed.
        stale_time = datetime.now(UTC) - timedelta(hours=2)
        await clean_database.execute(
            text("UPDATE sync_jobs SET updated_at = :ts WHERE job_id = :job_id"),
            {"ts": stale_time, "job_id": parent_id},
        )

        summary = await reconcile_parents(
            repo, now=datetime.now(UTC), stale_after_seconds=1800.0
        )

        assert summary["failed"] == 1
        parent = await repo.get_by_job_id(parent_id)
        assert parent is not None
        assert parent.status == SyncJobStatus.FAILED.value
        assert parent.error_message

    @pytest.mark.asyncio
    async def test_no_in_progress_parents_is_a_noop(
        self, repo: SyncJobRepository
    ) -> None:
        # A completed top-level job that must not be touched.
        await repo.create(
            job_id="already-done",
            user_id="user-1",
            integration_source="immich",
            sync_type="full",
            status=SyncJobStatus.COMPLETED.value,
        )

        summary = await reconcile_parents(
            repo, now=datetime.now(UTC), stale_after_seconds=1800.0
        )

        assert summary == {
            "scanned": 0,
            "completed": 0,
            "failed": 0,
            "still_in_progress": 0,
        }
        untouched = await repo.get_by_job_id("already-done")
        assert untouched is not None
        assert untouched.status == SyncJobStatus.COMPLETED.value

    @pytest.mark.asyncio
    async def test_list_in_progress_parents_excludes_children_and_finished(
        self, repo: SyncJobRepository
    ) -> None:
        parent_id = await self._create_parent(repo, "parent-list", 1)
        # A child of the in-progress parent (must be excluded — has parent_job_id).
        await self._create_children(repo, parent_id, [SyncJobStatus.RUNNING.value])
        # A finished top-level parent (must be excluded — wrong status).
        await repo.create(
            job_id="finished-parent",
            user_id="user-1",
            integration_source="immich",
            sync_type="full",
            status=SyncJobStatus.COMPLETED.value,
        )

        parents = await repo.list_in_progress_parents()

        assert [p.job_id for p in parents] == [parent_id]
