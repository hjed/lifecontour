"""
Strava worker configuration settings.

``StravaSettings`` subclasses the shared ``core_shared.BaseWorkerSettings`` so
the common worker surface (database/Redis connection, ARQ queue/stream identity,
logging, periodic-sync cadence and the OpenTelemetry block) is declared once.
Only Strava-specific fields and the per-worker identity defaults are declared
here. Secrets use ``SecretStr`` to keep them out of logs and tracebacks.
"""

from __future__ import annotations

from core_shared import BaseWorkerSettings
from pydantic import SecretStr


class StravaSettings(BaseWorkerSettings):
    """Configuration for the Strava integration worker."""

    # Strava API credentials.
    strava_client_id: str
    strava_client_secret: SecretStr

    # Encryption key for stored OAuth tokens (matches the main app).
    encryption_key: SecretStr

    # Per-worker identity overrides (see BaseWorkerSettings for the rest).
    worker_id: str = "strava-worker"
    otel_service_name: str = "strava-worker"

    # Fan-out reconciliation window — overrides the shared 30-minute default.
    # Strava's rate-limit handling defers a retrying batch by up to ~1 hour per
    # attempt (the daily-limit fallback in ``worker._rate_limit_defer``), during
    # which the parent's ``updated_at`` does not advance. A 30-minute staleness
    # window would mark an IN_PROGRESS parent FAILED while its children are still
    # legitimately deferred, so we widen it to 6 hours to clear a single
    # deferral plus several hourly daily-limit retries. A fan-out genuinely stuck
    # beyond this is still bounded (and its activities are imported idempotently
    # via the outbox regardless of the parent's final status). Env-overridable
    # via ``RECONCILIATION_STALE_AFTER_SECONDS`` for deployments that routinely
    # exhaust Strava's daily quota.
    reconciliation_stale_after_seconds: int = 6 * 60 * 60
