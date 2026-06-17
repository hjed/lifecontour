"""Unit tests for the shared fan-out reconciliation logic.

Covers the pure transition-decision function (the authoritative completion rules
for an ``IN_PROGRESS`` parent), the repository-driven ``reconcile_parents`` loop,
and the ARQ ``reconcile_in_progress_parents`` entry point.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from core_shared.models.sync_job import SyncJobStatus
from core_shared.sync_reconciliation import (
    ReconcileDecision,
    decide_parent_outcome,
    reconcile_in_progress_parents,
    reconcile_parents,
)


def _aggregate(
    total: int, completed: int, failed: int, cancelled: int = 0
) -> dict[str, int]:
    return {
        "total": total,
        "completed": completed,
        "failed": failed,
        "cancelled": cancelled,
    }


class TestDecideParentOutcome:
    """The pure transition logic — child rows are authoritative."""

    def test_all_children_completed_marks_completed(self) -> None:
        decision = decide_parent_outcome(
            expected_children=3,
            aggregate=_aggregate(total=3, completed=3, failed=0),
            seconds_since_update=5.0,
            stale_after_seconds=1800.0,
        )
        assert decision == ReconcileDecision(SyncJobStatus.COMPLETED, None)

    def test_partial_failure_marks_failed_with_summary(self) -> None:
        decision = decide_parent_outcome(
            expected_children=3,
            aggregate=_aggregate(total=3, completed=2, failed=1),
            seconds_since_update=5.0,
            stale_after_seconds=1800.0,
        )
        assert decision.status is SyncJobStatus.FAILED
        assert decision.error_message is not None
        assert "1" in decision.error_message and "3" in decision.error_message

    def test_all_failure_marks_failed(self) -> None:
        decision = decide_parent_outcome(
            expected_children=2,
            aggregate=_aggregate(total=2, completed=0, failed=2),
            seconds_since_update=5.0,
            stale_after_seconds=1800.0,
        )
        assert decision.status is SyncJobStatus.FAILED
        assert decision.error_message is not None

    def test_cancelled_child_is_terminal_and_fails_parent(self) -> None:
        # A cancelled child is terminal (never progresses), so the parent is
        # finalised immediately as FAILED rather than stranded until staleness.
        decision = decide_parent_outcome(
            expected_children=3,
            aggregate=_aggregate(total=3, completed=2, failed=0, cancelled=1),
            seconds_since_update=5.0,
            stale_after_seconds=1800.0,
        )
        assert decision.status is SyncJobStatus.FAILED
        assert decision.error_message is not None
        assert "cancelled" in decision.error_message

    def test_failed_and_cancelled_are_both_reported(self) -> None:
        decision = decide_parent_outcome(
            expected_children=3,
            aggregate=_aggregate(total=3, completed=1, failed=1, cancelled=1),
            seconds_since_update=5.0,
            stale_after_seconds=1800.0,
        )
        assert decision.status is SyncJobStatus.FAILED
        assert decision.error_message is not None
        assert "failed" in decision.error_message
        assert "cancelled" in decision.error_message

    def test_in_progress_not_stale_is_left_unchanged(self) -> None:
        decision = decide_parent_outcome(
            expected_children=3,
            aggregate=_aggregate(total=3, completed=1, failed=0),
            seconds_since_update=10.0,
            stale_after_seconds=1800.0,
        )
        assert decision == ReconcileDecision(None, None)

    def test_in_progress_stale_marks_failed(self) -> None:
        decision = decide_parent_outcome(
            expected_children=3,
            aggregate=_aggregate(total=3, completed=1, failed=0),
            seconds_since_update=3600.0,
            stale_after_seconds=1800.0,
        )
        assert decision.status is SyncJobStatus.FAILED
        assert decision.error_message is not None

    def test_no_children_expected_marks_completed(self) -> None:
        decision = decide_parent_outcome(
            expected_children=0,
            aggregate=_aggregate(total=0, completed=0, failed=0),
            seconds_since_update=5.0,
            stale_after_seconds=1800.0,
        )
        assert decision == ReconcileDecision(SyncJobStatus.COMPLETED, None)

    def test_partial_aggregate_dict_defaults_missing_keys_to_zero(self) -> None:
        # An external caller passing only a subset of keys must not raise.
        decision = decide_parent_outcome(
            expected_children=0,
            aggregate={},
            seconds_since_update=5.0,
            stale_after_seconds=1800.0,
        )
        assert decision == ReconcileDecision(SyncJobStatus.COMPLETED, None)

    def test_children_not_all_persisted_yet_is_left_unchanged(self) -> None:
        # Only 2 of the 3 expected children exist; not stale → leave in progress.
        decision = decide_parent_outcome(
            expected_children=3,
            aggregate=_aggregate(total=2, completed=2, failed=0),
            seconds_since_update=10.0,
            stale_after_seconds=1800.0,
        )
        assert decision == ReconcileDecision(None, None)


def _parent(
    job_id: str,
    expected_children: int,
    *,
    updated_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        job_id=job_id,
        expected_children=expected_children,
        updated_at=updated_at or datetime.now(UTC),
    )


class TestReconcileParents:
    """The repository-driven loop over in-progress parents."""

    @pytest.mark.asyncio
    async def test_no_in_progress_parents_is_a_noop(self) -> None:
        repo = MagicMock()
        repo.list_in_progress_parents = AsyncMock(return_value=[])
        repo.update_status = AsyncMock()

        summary = await reconcile_parents(
            repo, now=datetime.now(UTC), stale_after_seconds=1800.0
        )

        assert summary == {
            "scanned": 0,
            "completed": 0,
            "failed": 0,
            "still_in_progress": 0,
        }
        repo.update_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_finalises_each_parent_by_its_children(self) -> None:
        now = datetime.now(UTC)
        parents = [
            _parent("done", 2),
            _parent("failed", 2),
            _parent("running", 2),
            _parent("stuck", 2, updated_at=now - timedelta(hours=2)),
        ]
        aggregates = {
            "done": _aggregate(2, 2, 0),
            "failed": _aggregate(2, 1, 1),
            "running": _aggregate(2, 1, 0),
            "stuck": _aggregate(2, 1, 0),
        }
        repo = MagicMock()
        repo.list_in_progress_parents = AsyncMock(return_value=parents)
        repo.aggregate_children = AsyncMock(
            side_effect=lambda job_id: aggregates[job_id]
        )
        repo.update_status = AsyncMock()

        summary = await reconcile_parents(repo, now=now, stale_after_seconds=1800.0)

        assert summary == {
            "scanned": 4,
            "completed": 1,
            "failed": 2,
            "still_in_progress": 1,
        }

        updated = {
            call.kwargs["job_id"]: call.kwargs
            for call in repo.update_status.await_args_list
        }
        assert set(updated) == {"done", "failed", "stuck"}
        assert updated["done"]["status"] == SyncJobStatus.COMPLETED.value
        assert updated["done"]["completed_at"] == now
        assert updated["failed"]["status"] == SyncJobStatus.FAILED.value
        assert updated["failed"]["error_message"]
        assert updated["stuck"]["status"] == SyncJobStatus.FAILED.value


class TestReconcileInProgressParentsEntryPoint:
    """The ARQ job wrapper: opens a session, reconciles, commits."""

    @pytest.mark.asyncio
    async def test_opens_session_reconciles_and_commits(self) -> None:
        session = AsyncMock()
        session.commit = AsyncMock()
        session.connection = AsyncMock(return_value=MagicMock())

        session_cm = MagicMock()
        session_cm.__aenter__ = AsyncMock(return_value=session)
        session_cm.__aexit__ = AsyncMock(return_value=False)
        session_factory = MagicMock(return_value=session_cm)

        ctx: dict[str, Any] = {
            "session_factory": session_factory,
            "settings": SimpleNamespace(reconciliation_stale_after_seconds=1800),
        }

        # No in-progress parents → clean no-op, but a session is still opened and
        # committed so the contract is exercised.
        from unittest.mock import patch

        with patch("core_shared.sync_reconciliation.SyncJobRepository") as repo_cls:
            repo = repo_cls.return_value
            repo.list_in_progress_parents = AsyncMock(return_value=[])

            summary = await reconcile_in_progress_parents(ctx)

        assert summary["scanned"] == 0
        session.commit.assert_awaited_once()
        session_cm.__aenter__.assert_awaited_once()
