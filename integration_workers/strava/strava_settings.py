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
