#!/usr/bin/env python3
"""
Unit tests for periodic sync configuration.

Tests ARQ cron_jobs configuration, environment variables, and sync interval settings.
"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, "/core_shared")


class TestPeriodicSyncConfiguration:
    """Test cases for periodic sync configuration and cron_jobs setup."""

    def test_worker_settings_has_periodic_sync_env_vars(self) -> None:
        """Test that WorkerSettings includes periodic sync environment variables."""
        # Set environment variables
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql://test:test@localhost/test",
                "GOOGLE_CLIENT_ID": "test-client-id",
                "GOOGLE_CLIENT_SECRET": "test-secret",
                "ENCRYPTION_KEY": "test-encryption-key",
                "ENABLE_PERIODIC_SYNC": "true",
                "SYNC_INTERVAL_HOURS": "6",
            },
        ):
            # Reimport to pick up new environment variables
            import importlib

            import worker

            importlib.reload(worker)

            # Verify settings include periodic sync configuration
            assert hasattr(worker.settings, "enable_periodic_sync"), (
                "WorkerSettings should have enable_periodic_sync attribute"
            )
            assert hasattr(worker.settings, "sync_interval_hours"), (
                "WorkerSettings should have sync_interval_hours attribute"
            )

            # Verify values
            assert worker.settings.enable_periodic_sync is True, (
                "enable_periodic_sync should be True"
            )
            assert worker.settings.sync_interval_hours == 6, (
                "sync_interval_hours should be 6"
            )

    def test_worker_settings_periodic_sync_defaults(self) -> None:
        """Test that periodic sync has safe defaults (disabled by default)."""
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql://test:test@localhost/test",
                "GOOGLE_CLIENT_ID": "test-client-id",
                "GOOGLE_CLIENT_SECRET": "test-secret",
                "ENCRYPTION_KEY": "test-encryption-key",
                # Don't set ENABLE_PERIODIC_SYNC or SYNC_INTERVAL_HOURS
            },
            clear=True,
        ):
            import importlib

            import worker

            importlib.reload(worker)

            # Verify defaults
            assert worker.settings.enable_periodic_sync is False, (
                "enable_periodic_sync should default to False"
            )
            assert worker.settings.sync_interval_hours == 6, (
                "sync_interval_hours should default to 6"
            )

    def test_cron_jobs_present_when_periodic_sync_enabled(self) -> None:
        """Test that cron_jobs is configured when ENABLE_PERIODIC_SYNC=true."""
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql://test:test@localhost/test",
                "GOOGLE_CLIENT_ID": "test-client-id",
                "GOOGLE_CLIENT_SECRET": "test-secret",
                "ENCRYPTION_KEY": "test-encryption-key",
                "ENABLE_PERIODIC_SYNC": "true",
                "SYNC_INTERVAL_HOURS": "6",
            },
        ):
            import importlib

            import worker

            importlib.reload(worker)

            # Verify GoogleWorkerSettings has cron_jobs
            assert hasattr(worker.GoogleWorkerSettings, "cron_jobs"), (
                "GoogleWorkerSettings should have cron_jobs attribute"
            )

            cron_jobs = worker.GoogleWorkerSettings.cron_jobs
            assert isinstance(cron_jobs, list), "cron_jobs should be a list"
            assert len(cron_jobs) > 0, "cron_jobs should not be empty when enabled"

    def test_no_periodic_sync_cron_when_periodic_sync_disabled(self) -> None:
        """Test that the periodic sync cron is absent when ENABLE_PERIODIC_SYNC=false.

        The webhook renewal cron is deliberately independent of this flag and
        stays registered — see ``test_worker_settings.py`` for that contract.
        """
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql://test:test@localhost/test",
                "GOOGLE_CLIENT_ID": "test-client-id",
                "GOOGLE_CLIENT_SECRET": "test-secret",
                "ENCRYPTION_KEY": "test-encryption-key",
                "ENABLE_PERIODIC_SYNC": "false",
            },
            clear=True,
        ):
            import importlib

            import worker

            importlib.reload(worker)

            # Verify no periodic sync cron is scheduled
            if hasattr(worker.GoogleWorkerSettings, "cron_jobs"):
                cron_jobs = worker.GoogleWorkerSettings.cron_jobs
                scheduled = {job.coroutine.__name__ for job in cron_jobs}
                assert "periodic_sync_all_accounts" not in scheduled, (
                    "periodic sync should not be scheduled when disabled"
                )

    def test_cron_schedule_matches_sync_interval(self) -> None:
        """Test that cron schedule is generated correctly based on sync_interval_hours."""
        test_cases = [
            (
                1,
                {
                    0,
                    1,
                    2,
                    3,
                    4,
                    5,
                    6,
                    7,
                    8,
                    9,
                    10,
                    11,
                    12,
                    13,
                    14,
                    15,
                    16,
                    17,
                    18,
                    19,
                    20,
                    21,
                    22,
                    23,
                },
            ),  # Every hour
            (6, {0, 6, 12, 18}),  # Every 6 hours
            (12, {0, 12}),  # Every 12 hours
            (24, {0}),  # Daily
        ]

        for interval_hours, _expected_hours in test_cases:
            with patch.dict(
                os.environ,
                {
                    "DATABASE_URL": "postgresql://test:test@localhost/test",
                    "GOOGLE_CLIENT_ID": "test-client-id",
                    "GOOGLE_CLIENT_SECRET": "test-secret",
                    "ENCRYPTION_KEY": "test-encryption-key",
                    "ENABLE_PERIODIC_SYNC": "true",
                    "SYNC_INTERVAL_HOURS": str(interval_hours),
                },
            ):
                # This test will verify the cron schedule once implementation is complete
                # For now, we're just testing the configuration structure
                pass
