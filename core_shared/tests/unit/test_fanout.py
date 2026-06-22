"""Unit tests for the shared non-blocking fan-out helpers.

These cover the worker-agnostic pieces of the fan-out pattern that were
previously duplicated in each worker: defensive int coercion, the final-attempt
predicate, the child-terminal/counter update, and the idempotent child
persistence (with the authoritative ``expected_children`` accounting).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from core_shared.fanout import (
    coerce_int,
    is_final_attempt,
    persist_fanout_children,
    record_child_terminal,
)


def _make_repo(*, existing_children: list[Any] | None = None) -> MagicMock:
    repo = MagicMock()
    repo.create = AsyncMock()
    repo.set_expected_children = AsyncMock()
    repo.update_status = AsyncMock(return_value=MagicMock())
    repo.increment_completed_children = AsyncMock()
    repo.increment_failed_children = AsyncMock()
    repo.list_children = AsyncMock(return_value=existing_children or [])
    return repo


class TestCoerceInt:
    @pytest.mark.parametrize(
        ("value", "default", "expected"),
        [
            (5, 1, 5),
            ("5", 1, 5),
            (None, 7, 7),
            ("oops", 3, 3),
            (2.9, 1, 2),
        ],
    )
    def test_coerces(self, value: Any, default: int, expected: int) -> None:
        assert coerce_int(value, default) == expected


@pytest.mark.parametrize(
    ("ctx", "expected"),
    [
        ({"job_try": 5, "max_tries": 5}, True),
        ({"job_try": 1, "max_tries": 5}, False),
        ({}, False),  # both missing -> defaults (1 >= DEFAULT_MAX_TRIES is False)
        ({"job_try": None, "max_tries": None}, False),
        ({"job_try": "5", "max_tries": "5"}, True),
        ({"job_try": "oops"}, False),
    ],
)
def test_is_final_attempt(ctx: dict[str, Any], expected: bool) -> None:
    assert is_final_attempt(ctx) is expected


class TestRecordChildTerminal:
    @pytest.mark.asyncio
    async def test_completed_increments_completed(self) -> None:
        repo = _make_repo()
        await record_child_terminal(
            repo, child_job_id="c1", parent_job_id="p", status="completed"
        )
        repo.update_status.assert_awaited_once()
        assert repo.update_status.await_args.kwargs["status"] == "completed"
        repo.increment_completed_children.assert_awaited_once_with("p")
        repo.increment_failed_children.assert_not_called()

    @pytest.mark.asyncio
    async def test_failed_increments_failed(self) -> None:
        repo = _make_repo()
        await record_child_terminal(
            repo,
            child_job_id="c1",
            parent_job_id="p",
            status="failed",
            error_message="boom",
        )
        repo.increment_failed_children.assert_awaited_once_with("p")
        repo.increment_completed_children.assert_not_called()

    @pytest.mark.asyncio
    async def test_unmatched_row_skips_counter(self) -> None:
        repo = _make_repo()
        repo.update_status = AsyncMock(return_value=None)  # no row matched
        await record_child_terminal(
            repo, child_job_id="missing", parent_job_id="p", status="completed"
        )
        repo.increment_completed_children.assert_not_called()
        repo.increment_failed_children.assert_not_called()


class TestPersistFanoutChildren:
    @pytest.mark.asyncio
    async def test_creates_one_child_per_batch_and_marks_in_progress(self) -> None:
        repo = _make_repo()
        child_ids = await persist_fanout_children(
            repo,
            parent_job_id="p",
            user_id="u",
            integration_source="demo",
            sync_type="full",
            child_id_prefix="demo-p",
            count=3,
        )
        assert child_ids == ["demo-p1", "demo-p2", "demo-p3"]
        assert repo.create.await_count == 3
        for call in repo.create.await_args_list:
            assert call.kwargs["parent_job_id"] == "p"
            assert call.kwargs["integration_source"] == "demo"
            assert call.kwargs["status"] == "queued"
        repo.set_expected_children.assert_awaited_once_with("p", 3)
        statuses = [c.kwargs.get("status") for c in repo.update_status.await_args_list]
        assert "in_progress" in statuses
        assert "completed" not in statuses

    @pytest.mark.asyncio
    async def test_zero_batches_marks_completed(self) -> None:
        repo = _make_repo()
        await persist_fanout_children(
            repo,
            parent_job_id="p",
            user_id="u",
            integration_source="demo",
            sync_type="full",
            child_id_prefix="demo-p",
            count=0,
        )
        repo.create.assert_not_called()
        repo.set_expected_children.assert_awaited_once_with("p", 0)
        statuses = [c.kwargs.get("status") for c in repo.update_status.await_args_list]
        assert "completed" in statuses
        assert "in_progress" not in statuses

    @pytest.mark.asyncio
    async def test_idempotent_skips_existing_children(self) -> None:
        existing = [MagicMock(job_id="demo-p1"), MagicMock(job_id="demo-p2")]
        repo = _make_repo(existing_children=existing)
        child_ids = await persist_fanout_children(
            repo,
            parent_job_id="p",
            user_id="u",
            integration_source="demo",
            sync_type="full",
            child_id_prefix="demo-p",
            count=2,
        )
        assert child_ids == ["demo-p1", "demo-p2"]
        repo.create.assert_not_called()  # both already exist
        repo.set_expected_children.assert_awaited_once_with("p", 2)

    @pytest.mark.asyncio
    async def test_expected_children_is_authoritative_on_drift(self) -> None:
        # A retry whose drain yields fewer pages than were already persisted must
        # still expect against the authoritative persisted total.
        existing = [
            MagicMock(job_id="demo-p1"),
            MagicMock(job_id="demo-p2"),
            MagicMock(job_id="demo-p3"),
        ]
        repo = _make_repo(existing_children=existing)
        await persist_fanout_children(
            repo,
            parent_job_id="p",
            user_id="u",
            integration_source="demo",
            sync_type="full",
            child_id_prefix="demo-p",
            count=2,
        )
        repo.set_expected_children.assert_awaited_once_with("p", 3)
