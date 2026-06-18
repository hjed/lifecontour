"""Shared reconciliation for non-blocking fan-out (orchestrator) jobs.

An orchestrator job dispatches its child batch jobs, persists them linked via
``parent_job_id``, marks itself ``IN_PROGRESS`` and returns immediately (it no
longer blocks on ``asyncio.gather``). Parent completion is therefore decided
out-of-band by this reconciliation job, which any fan-out worker schedules on a
cron (see :func:`core_shared.worker_arq.generate_reconciliation_cron`).

The reconciler scans ``IN_PROGRESS`` parents and, for each, decides the final
status from the **actual child rows** (the source of truth) — the parent's child
counters are only a fast path, so a missed counter increment cannot strand a
parent. A parent whose children have not progressed within a configured window
is treated as stuck and marked ``FAILED`` rather than left ``IN_PROGRESS``
forever.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from core_shared.logging import get_logger
from core_shared.models.sync_job import SyncJobStatus
from core_shared.repositories.sync_job_repository import SyncJobRepository

logger = get_logger(__name__)

# Default staleness window when a worker does not configure one (30 minutes).
DEFAULT_RECONCILIATION_STALE_AFTER_SECONDS = 1800


@dataclass(frozen=True)
class ReconcileDecision:
    """The outcome of reconciling a single parent.

    ``status`` is the status to transition the parent to, or ``None`` to leave it
    ``IN_PROGRESS`` (children still running and not yet stuck).
    """

    status: SyncJobStatus | None
    error_message: str | None = None


def decide_parent_outcome(
    *,
    expected_children: int,
    aggregate: dict[str, int],
    seconds_since_update: float,
    stale_after_seconds: float,
) -> ReconcileDecision:
    """Decide the final status for an ``IN_PROGRESS`` parent (pure).

    Child rows are authoritative: ``aggregate`` is the child-row status count
    from :meth:`SyncJobRepository.aggregate_children`. The recognised keys —
    ``total``, ``completed``, ``failed`` and ``cancelled`` — are each optional
    and default to 0, so a partial dict never raises (``cancelled`` is treated as
    terminal-but-unsuccessful, so a cancelled child finalises the parent as
    ``FAILED`` rather than stranding it until the staleness window).

    Args:
        expected_children: Number of children the orchestrator dispatched.
        aggregate: Authoritative child-row status counts (missing keys → 0).
        seconds_since_update: Seconds since the parent last progressed
            (its ``updated_at``, which bumps on each child counter increment).
        stale_after_seconds: Staleness window before a non-terminal fan-out is
            considered stuck.

    Returns:
        A :class:`ReconcileDecision`.
    """
    total = aggregate.get("total", 0)
    completed = aggregate.get("completed", 0)
    failed = aggregate.get("failed", 0)
    cancelled = aggregate.get("cancelled", 0)
    # A cancelled child is terminal (it will never progress) but did not succeed,
    # so it counts toward "done" and fails the parent under the fail-if-any policy.
    unsuccessful = failed + cancelled
    terminal = completed + unsuccessful

    # Done only when every expected child both exists and has reached a terminal
    # state. ``expected_children == 0`` (no children) is trivially done.
    all_persisted = total >= expected_children
    all_terminal = terminal >= total
    done = all_persisted and all_terminal

    if done:
        if unsuccessful > 0:
            return ReconcileDecision(
                SyncJobStatus.FAILED,
                _failure_summary(total=total, failed=failed, cancelled=cancelled),
            )
        return ReconcileDecision(SyncJobStatus.COMPLETED, None)

    if seconds_since_update > stale_after_seconds:
        unfinished = max(total, expected_children) - terminal
        return ReconcileDecision(
            SyncJobStatus.FAILED,
            (
                f"Stuck fan-out: {terminal} of {expected_children} child job(s) "
                f"finished before the {stale_after_seconds:.0f}s staleness window "
                f"elapsed ({unfinished} never finished)"
            ),
        )

    return ReconcileDecision(None, None)


def _failure_summary(*, total: int, failed: int, cancelled: int) -> str:
    """Build a parent failure summary from the unsuccessful child counts."""
    parts = []
    if failed:
        parts.append(f"{failed} failed")
    if cancelled:
        parts.append(f"{cancelled} cancelled")
    return f"{' and '.join(parts)} of {total} child job(s)"


def _seconds_since(timestamp: datetime, now: datetime) -> float:
    """Seconds between ``timestamp`` and ``now`` (treating naive as UTC).

    Both operands are normalised to timezone-aware UTC so a naive ``now`` passed
    by a non-ARQ caller cannot raise on the subtraction.
    """
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return (now - timestamp).total_seconds()


async def reconcile_parents(
    repo: SyncJobRepository,
    *,
    now: datetime,
    stale_after_seconds: float,
) -> dict[str, int]:
    """Finalise every ``IN_PROGRESS`` parent against its child rows.

    Args:
        repo: Repository bound to the active connection.
        now: Reference time (used for staleness and ``completed_at``).
        stale_after_seconds: Staleness window for stuck-fan-out detection.

    Returns:
        Summary counts: ``scanned``, ``completed``, ``failed``,
        ``still_in_progress``.
    """
    summary = {"scanned": 0, "completed": 0, "failed": 0, "still_in_progress": 0}

    for parent in await repo.list_in_progress_parents():
        summary["scanned"] += 1
        aggregate = await repo.aggregate_children(parent.job_id)
        decision = decide_parent_outcome(
            expected_children=parent.expected_children,
            aggregate=aggregate,
            seconds_since_update=_seconds_since(parent.updated_at, now),
            stale_after_seconds=stale_after_seconds,
        )

        if decision.status is None:
            summary["still_in_progress"] += 1
            continue

        await repo.update_status(
            job_id=parent.job_id,
            status=decision.status.value,
            completed_at=now,
            error_message=decision.error_message,
        )

        if decision.status is SyncJobStatus.COMPLETED:
            summary["completed"] += 1
        else:
            summary["failed"] += 1

    return summary


async def reconcile_in_progress_parents(ctx: dict[str, Any]) -> dict[str, int]:
    """ARQ entry point: reconcile in-progress fan-out parents.

    Reads the session factory and (optional) worker settings from the ARQ
    context, opens a session, finalises in-progress parents, and commits. Safe to
    run on a cron in any fan-out worker — a no-op when there are no in-progress
    parents.
    """
    session_factory = ctx["session_factory"]
    settings = ctx.get("settings")
    stale_after_seconds = getattr(
        settings,
        "reconciliation_stale_after_seconds",
        DEFAULT_RECONCILIATION_STALE_AFTER_SECONDS,
    )
    now = datetime.now(UTC)

    async with session_factory() as session:
        conn = await session.connection()
        repo = SyncJobRepository(conn)
        summary = await reconcile_parents(
            repo, now=now, stale_after_seconds=stale_after_seconds
        )
        await session.commit()

    logger.info("Reconciled in-progress fan-out parents", **summary)
    return summary
