"""Unit tests for the shared ARQ worker helpers in ``core_shared.worker_arq``."""

from __future__ import annotations

from core_shared.worker_arq import generate_reconciliation_cron


async def _dummy_job(ctx: dict[str, object]) -> None:  # pragma: no cover - marker
    return None


class TestGenerateReconciliationCron:
    """The reconciliation cron-registration helper."""

    def test_schedules_at_the_expected_minute_set(self) -> None:
        jobs = generate_reconciliation_cron(_dummy_job, every_minutes=20)

        assert len(jobs) == 1
        assert jobs[0].minute == {0, 20, 40}
        assert jobs[0].unique is True

    def test_default_interval_is_five_minutes(self) -> None:
        jobs = generate_reconciliation_cron(_dummy_job)

        assert jobs[0].minute == set(range(0, 60, 5))

    def test_zero_interval_is_floored_to_one_minute(self) -> None:
        jobs = generate_reconciliation_cron(_dummy_job, every_minutes=0)

        assert jobs[0].minute == set(range(0, 60))

    def test_unique_flag_is_passed_through(self) -> None:
        jobs = generate_reconciliation_cron(_dummy_job, unique=False)

        assert jobs[0].unique is False
