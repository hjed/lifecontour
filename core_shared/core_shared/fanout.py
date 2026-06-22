"""Shared non-blocking fan-out helpers for integration workers.

An orchestrator persists one child ``sync_jobs`` row per batch (linked via
``parent_job_id``), records ``expected_children``, marks the parent
``in_progress`` and returns; each child updates its own row and atomically
increments the parent counters; the shared reconciler
(:mod:`core_shared.sync_reconciliation`) finalises the parent against the
authoritative child rows. These are the worker-agnostic pieces of that pattern,
shared so every fan-out worker (Immich, Strava, …) behaves identically.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from core_shared.logging import get_logger
from core_shared.repositories.sync_job_repository import SyncJobRepository
from core_shared.worker_arq import DEFAULT_MAX_TRIES

logger = get_logger(__name__)


def coerce_int(value: Any, default: int) -> int:
    """Best-effort int coercion, falling back to ``default`` for bad/missing values."""
    try:
        return int(value)
    except TypeError, ValueError:
        return default


def is_final_attempt(ctx: dict[str, Any]) -> bool:
    """Whether ARQ will give up on this job after the current attempt.

    Children only record a terminal ``failed`` row (and bump the parent's
    ``failed_children``) on the final attempt, so a transient failure that ARQ
    will retry does not prematurely fail the fan-out. ``job_try``/``max_tries``
    are coerced defensively so a missing/``None``/string value can never raise
    here and silently skip the failure recording; the shared ARQ default is the
    fallback when ARQ does not place ``max_tries`` in the context.
    """
    job_try = coerce_int(ctx.get("job_try"), 1)
    max_tries = coerce_int(ctx.get("max_tries"), DEFAULT_MAX_TRIES)
    return job_try >= max_tries


async def persist_fanout_children(
    repo: SyncJobRepository,
    *,
    parent_job_id: str,
    user_id: str,
    integration_source: str,
    sync_type: str,
    child_id_prefix: str,
    count: int,
) -> list[str]:
    """Persist linked child rows and finalise the parent's pre-dispatch state.

    Creates one ``queued`` child ``sync_jobs`` row per batch (linked via
    ``parent_job_id``), records ``expected_children``, and transitions the parent
    to ``in_progress`` — or straight to ``completed`` when there is nothing to
    fan out. Returns the deterministic child job ids in batch order.

    The caller commits this as a single unit of work *before* dispatching the
    children, so every child's row already exists when it updates itself and
    increments the parent counters.

    Idempotent across orchestrator retries: ARQ may re-run the orchestrator after
    a prior attempt already committed these rows (e.g. a crash or error during the
    post-commit dispatch loop). ``create`` is a plain ``INSERT`` (no
    ``ON CONFLICT``), so a child row that already exists is skipped rather than
    raising a duplicate-key error — the deterministic ids let a retry re-dispatch
    the same children safely.

    ``expected_children`` is set to the **authoritative** number of persisted
    child rows, not the fresh ``count``. Should a retry's drain yield a different
    page count than a prior attempt (e.g. items created/deleted in between), this
    keeps the parent's expected total consistent with the rows that actually
    exist, so the reconciler never under-counts and finalises against the
    authoritative child rows (a genuinely orphaned child is still bounded by the
    staleness window).
    """
    child_ids = [f"{child_id_prefix}{i + 1}" for i in range(count)]
    existing_child_ids = {
        child.job_id for child in await repo.list_children(parent_job_id)
    }
    for child_id in child_ids:
        if child_id in existing_child_ids:
            continue
        await repo.create(
            job_id=child_id,
            user_id=user_id,
            integration_source=integration_source,
            sync_type=sync_type,
            status="queued",
            parent_job_id=parent_job_id,
        )

    # The deterministic ids are a dense ``p1..pN`` prefix, so the persisted total
    # after the create loop is ``max(count, prior count)``. Expect against that —
    # never blindly the fresh count — so a drifting drain can't strand children.
    expected_children = max(count, len(existing_child_ids))
    if expected_children != count:
        logger.warning(
            "Fan-out child count drifted across attempts",
            parent_job_id=parent_job_id,
            integration_source=integration_source,
            drained_count=count,
            persisted_count=expected_children,
        )
    await repo.set_expected_children(parent_job_id, expected_children)

    if expected_children == 0:
        await repo.update_status(
            job_id=parent_job_id,
            status="completed",
            completed_at=datetime.now(UTC),
            progress=100,
        )
    else:
        await repo.update_status(job_id=parent_job_id, status="in_progress", progress=0)

    return child_ids


async def record_child_terminal(
    repo: SyncJobRepository,
    *,
    child_job_id: str,
    parent_job_id: str,
    status: str,
    error_message: str | None = None,
) -> None:
    """Mark a child row terminal and bump the matching parent counter.

    The parent counter is incremented **only when the child row update actually
    matched a row**, so a missing/incorrect ``child_job_id`` can never bump a
    parent's counters (and ``updated_at``) without a corresponding terminal child
    row — which would otherwise reset the reconciler's staleness window and skew
    the fast-path counts. Child rows remain reconciliation's source of truth.
    """
    updated = await repo.update_status(
        job_id=child_job_id,
        status=status,
        completed_at=datetime.now(UTC),
        error_message=error_message,
    )
    if updated is None:
        logger.warning(
            "Child sync job row not found; skipping parent counter increment",
            child_job_id=child_job_id,
            parent_job_id=parent_job_id,
            status=status,
        )
        return

    if status == "completed":
        await repo.increment_completed_children(parent_job_id)
    else:
        await repo.increment_failed_children(parent_job_id)
