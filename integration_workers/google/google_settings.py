"""
Google Contacts worker configuration settings.

``GoogleSettings`` subclasses the shared ``core_shared.BaseWorkerSettings`` so
the common worker surface (database/Redis connection, ARQ queue/stream identity,
logging, periodic-sync cadence and the OpenTelemetry block) is declared once.
Only Google-specific fields and the per-worker identity defaults are declared
here. Secrets use ``SecretStr`` to keep them out of logs and tracebacks.
"""

from __future__ import annotations

from core_shared import BaseWorkerSettings
from pydantic import SecretStr


class GoogleSettings(BaseWorkerSettings):
    """Configuration for the Google Contacts worker."""

    # Google API credentials.
    google_client_id: str
    google_client_secret: SecretStr

    # Encryption key for stored OAuth tokens (matches the main app).
    encryption_key: SecretStr

    # Maximum number of jobs the ARQ worker runs concurrently.
    max_concurrent_jobs: int = 5

    # Reserved Google groups to ignore (by default just ``myContacts``).
    google_reserved_groups: list[str] = ["myContacts"]

    # Public HTTPS URL for webhook callbacks. Push notifications are disabled
    # entirely while this is unset.
    webhook_base_url: str = ""

    # How far ahead of a watch channel's expiry to re-register it. Channels
    # live for 7 days, so the default renews roughly every 5 days while
    # leaving enough slack to survive the worker being down for a day.
    webhook_renewal_threshold_hours: int = 48

    # Per-worker identity overrides (see BaseWorkerSettings for the rest).
    worker_id: str = "google-worker"
    otel_service_name: str = "google-worker"
