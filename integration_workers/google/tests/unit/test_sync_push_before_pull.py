"""Unit tests for the outbound push that runs before the inbound pull.

LOCAL-177: ``push_local_contacts_to_google`` was registered as an ARQ function
but nothing ever enqueued it — ``periodic_sync_all_accounts`` schedules only
``sync_google_contacts`` (inbound) and ``sync_calendar_events``. Outbound sync
was therefore entirely event-driven with no reconciliation, so a push lost to a
worker restart or a Redis trim was never repaired, and the next pull overwrote
the local edit.

The push now runs at the start of ``sync_google_contacts``, before the pull.
Keeping both in one job is what makes the ordering structural: two ARQ jobs give
no ordering guarantee, so a pull could still land first and clobber.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _session_factory() -> MagicMock:
    """A session factory yielding an AsyncMock session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory


def _push_result(**overrides: Any) -> dict[str, Any]:
    """A successful push helper result."""
    result: dict[str, Any] = {
        "pushed_count": 2,
        "created_count": 1,
        "updated_count": 1,
        "error_count": 0,
        "conflict_count": 0,
    }
    result.update(overrides)
    return result


class TestPushRunsBeforePull:
    """The outbound push happens first, so a pull cannot clobber a local edit."""

    @pytest.mark.asyncio
    async def test_push_is_called_before_the_pull(self) -> None:
        """Ordering is asserted directly, not inferred from both being called."""
        from worker import sync_google_contacts

        call_order: list[str] = []

        async def record_push(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            call_order.append("push")
            return _push_result()

        async def record_pull(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            call_order.append("pull")
            return {"contacts_processed": 3}

        with (
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient"),
            patch("worker._update_sync_job_status", new_callable=AsyncMock),
            patch("worker._push_pending_local_contacts", side_effect=record_push),
            patch("worker._perform_full_sync", side_effect=record_pull),
        ):
            result = await sync_google_contacts(
                ctx={"session_factory": _session_factory()},
                google_account_email="test@example.com",
                user_id=1,
                sync_type="full",
            )

        assert result["status"] == "success"
        assert call_order == ["push", "pull"]

    @pytest.mark.asyncio
    async def test_push_runs_before_an_incremental_pull_too(self) -> None:
        """The incremental path is the one the cron usually takes."""
        from worker import sync_google_contacts

        call_order: list[str] = []

        async def record_push(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            call_order.append("push")
            return _push_result()

        async def record_pull(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            call_order.append("pull")
            return {"contacts_processed": 1}

        with (
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient"),
            patch("worker._update_sync_job_status", new_callable=AsyncMock),
            patch("worker._push_pending_local_contacts", side_effect=record_push),
            patch("worker._perform_incremental_sync", side_effect=record_pull),
        ):
            await sync_google_contacts(
                ctx={"session_factory": _session_factory()},
                google_account_email="test@example.com",
                user_id=1,
                sync_type="incremental",
            )

        assert call_order == ["push", "pull"]

    @pytest.mark.asyncio
    async def test_push_counts_are_reported_in_the_sync_metrics(self) -> None:
        """Push outcomes are visible on the sync job rather than lost."""
        from worker import sync_google_contacts

        with (
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient"),
            patch("worker._update_sync_job_status", new_callable=AsyncMock),
            patch(
                "worker._push_pending_local_contacts",
                new_callable=AsyncMock,
                return_value=_push_result(pushed_count=5, conflict_count=1),
            ),
            patch(
                "worker._perform_full_sync",
                new_callable=AsyncMock,
                return_value={"contacts_processed": 0},
            ),
        ):
            result = await sync_google_contacts(
                ctx={"session_factory": _session_factory()},
                google_account_email="test@example.com",
                user_id=1,
                sync_type="full",
            )

        assert result["pushed_count"] == 5
        assert result["push_conflict_count"] == 1


class TestPushFailureDoesNotBlockThePull:
    """A Google write outage must not stop inbound sync."""

    @pytest.mark.asyncio
    async def test_a_raising_push_still_lets_the_pull_run(self) -> None:
        """The pull is safe here: a failed push leaves Google's etag unchanged.

        The inbound idempotency check then skips that contact, so the local edit
        survives to be pushed on the next cycle.
        """
        from worker import sync_google_contacts

        with (
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient"),
            patch("worker._update_sync_job_status", new_callable=AsyncMock),
            patch(
                "worker._push_pending_local_contacts",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Google is down"),
            ),
            patch(
                "worker._perform_full_sync",
                new_callable=AsyncMock,
                return_value={"contacts_processed": 4},
            ) as mock_pull,
        ):
            result = await sync_google_contacts(
                ctx={"session_factory": _session_factory()},
                google_account_email="test@example.com",
                user_id=1,
                sync_type="full",
            )

        mock_pull.assert_awaited_once()
        assert result["status"] == "success"
        assert result["push_failed"] is True


class TestPushTaskStillDelegates:
    """``push_local_contacts_to_google`` keeps working as a standalone task."""

    @pytest.mark.asyncio
    async def test_arq_task_delegates_to_the_shared_helper(self) -> None:
        """The ARQ entry point is a thin wrapper over the extracted helper."""
        from worker import push_local_contacts_to_google

        with (
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient"),
            patch(
                "worker._push_pending_local_contacts",
                new_callable=AsyncMock,
                return_value=_push_result(),
            ) as mock_push,
        ):
            result = await push_local_contacts_to_google(
                ctx={"session_factory": _session_factory()},
                google_account_email="test@example.com",
                user_id=1,
            )

        mock_push.assert_awaited_once()
        assert result["status"] == "success"
        assert result["pushed_count"] == 2


class TestPushIsCommittedBeforeThePull:
    """Augment review of #1551: the push's etags must not ride on the pull."""

    @pytest.mark.asyncio
    async def test_successful_push_is_committed_before_the_pull_starts(
        self,
    ) -> None:
        """Google keeps a write once accepted, so its etag is committed at once."""
        from worker import _push_before_pull

        session = AsyncMock()
        with patch(
            "worker._push_pending_local_contacts",
            new_callable=AsyncMock,
            return_value=_push_result(),
        ):
            await _push_before_pull(
                session=session,
                client=AsyncMock(),
                google_account_email="test@example.com",
            )

        session.commit.assert_awaited_once()
        session.rollback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_failed_push_is_rolled_back_so_the_pull_gets_a_clean_session(
        self,
    ) -> None:
        """A push that died on a database error would poison the pull's session."""
        from worker import _push_before_pull

        session = AsyncMock()
        with patch(
            "worker._push_pending_local_contacts",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            result = await _push_before_pull(
                session=session,
                client=AsyncMock(),
                google_account_email="test@example.com",
            )

        assert result["push_failed"] is True
        session.rollback.assert_awaited_once()
        session.commit.assert_not_awaited()
