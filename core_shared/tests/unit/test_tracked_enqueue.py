"""Unit tests for ``enqueue_tracked_job``.

A tracked job's ``sync_jobs`` row must be committed before the job is queued,
so a worker that picks the job up at once always finds it; a job that is not
queued must fail its row rather than leave it ``queued`` for ever.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from core_shared.models.sync_job import SyncJobStatus
from core_shared.tracked_enqueue import JobNotEnqueuedError, enqueue_tracked_job

pytestmark = pytest.mark.asyncio


class _Recorder:
    """A session, repository and redis whose calls land in one ordered list."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.session = MagicMock()
        self.session.connection = AsyncMock(return_value=MagicMock())
        self.session.commit = AsyncMock(side_effect=self._record("commit"))
        self.session.rollback = AsyncMock(side_effect=self._record("rollback"))
        self.repo = MagicMock()
        self.repo.create = AsyncMock(side_effect=self._record("create"))
        self.repo.fail_if_queued = AsyncMock(side_effect=self._record("fail_if_queued"))
        self.redis = MagicMock()
        self.redis.enqueue_job = AsyncMock(side_effect=self._record("enqueue_job"))
        self.enqueue_result: Any = MagicMock()

    def _record(self, name: str) -> Any:
        def side_effect(*_args: Any, **_kwargs: Any) -> Any:
            self.calls.append(name)
            return self.enqueue_result if name == "enqueue_job" else None

        return side_effect


@pytest.fixture
def recorder() -> Iterator[_Recorder]:
    rec = _Recorder()
    with patch("core_shared.tracked_enqueue.SyncJobRepository", return_value=rec.repo):
        yield rec


async def _enqueue(rec: _Recorder, **job_kwargs: Any) -> str:
    return await enqueue_tracked_job(
        rec.session,
        rec.redis,
        "sync_things",
        "user-1",
        "smart",
        queue_name="arq:things",
        user_id="user-1",
        integration_source="things",
        sync_type="smart",
        **job_kwargs,
    )


async def test_commits_the_queued_row_before_enqueueing(recorder: _Recorder) -> None:
    await _enqueue(recorder)

    assert recorder.calls == ["create", "commit", "enqueue_job"]
    recorder.repo.create.assert_awaited_once_with(
        job_id=ANY,
        user_id="user-1",
        integration_source="things",
        sync_type="smart",
        status=SyncJobStatus.QUEUED.value,
    )


async def test_enqueues_under_the_row_job_id_and_returns_it(
    recorder: _Recorder,
) -> None:
    job_id = await _enqueue(recorder, otel_carrier={"a": "b"}, _defer_until=None)

    row_job_id = recorder.repo.create.await_args.kwargs["job_id"]
    assert job_id == row_job_id
    assert len(job_id) == 32
    recorder.redis.enqueue_job.assert_awaited_once_with(
        "sync_things",
        "user-1",
        "smart",
        otel_carrier={"a": "b"},
        _defer_until=None,
        _job_id=row_job_id,
        _queue_name="arq:things",
    )


async def test_each_job_gets_a_fresh_id(recorder: _Recorder) -> None:
    first = await _enqueue(recorder)
    second = await _enqueue(recorder)

    assert first != second


async def test_job_not_returned_fails_the_row(recorder: _Recorder) -> None:
    recorder.enqueue_result = None

    with pytest.raises(JobNotEnqueuedError):
        await _enqueue(recorder)

    row_job_id = recorder.repo.create.await_args.kwargs["job_id"]
    recorder.repo.fail_if_queued.assert_awaited_once_with(
        job_id=row_job_id,
        completed_at=ANY,
        error_message="Job was not enqueued",
    )
    assert recorder.calls[-2:] == ["fail_if_queued", "commit"]


async def test_enqueue_error_fails_the_row_and_is_re_raised(
    recorder: _Recorder,
) -> None:
    recorder.redis.enqueue_job.side_effect = ConnectionError("redis down")

    with pytest.raises(ConnectionError, match="redis down"):
        await _enqueue(recorder)

    recorder.repo.fail_if_queued.assert_awaited_once_with(
        job_id=recorder.repo.create.await_args.kwargs["job_id"],
        completed_at=ANY,
        error_message="redis down",
    )
    recorder.session.commit.assert_awaited()


async def test_row_insert_failure_rolls_back_and_queues_nothing(
    recorder: _Recorder,
) -> None:
    recorder.repo.create.side_effect = RuntimeError("db down")

    with pytest.raises(RuntimeError, match="db down"):
        await _enqueue(recorder)

    recorder.session.rollback.assert_awaited_once()
    recorder.redis.enqueue_job.assert_not_awaited()


async def test_failing_to_fail_the_row_still_raises_the_enqueue_error(
    recorder: _Recorder,
) -> None:
    recorder.redis.enqueue_job.side_effect = ConnectionError("redis down")
    recorder.repo.fail_if_queued.side_effect = RuntimeError("db down")

    with pytest.raises(ConnectionError, match="redis down"):
        await _enqueue(recorder)

    recorder.session.rollback.assert_awaited_once()


async def test_cancelled_enqueue_fails_the_row_and_stays_cancelled(
    recorder: _Recorder,
) -> None:
    """A cancellation mid-enqueue must not strand the committed row as queued."""
    recorder.redis.enqueue_job.side_effect = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await _enqueue(recorder)

    recorder.repo.fail_if_queued.assert_awaited_once_with(
        job_id=recorder.repo.create.await_args.kwargs["job_id"],
        completed_at=ANY,
        error_message="CancelledError",
    )
