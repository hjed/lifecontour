"""
Snipe-IT worker settings.

Pydantic settings model for the Snipe-IT integration worker. The common worker
surface (database/Redis connection, ARQ queue/stream identity, logging,
periodic-sync cadence and the OpenTelemetry block) is inherited from the shared
``core_shared.BaseWorkerSettings``; only the Snipe-IT-specific fields are
declared here. Environment variables are loaded from the shell environment or a
``.env`` file.
"""

from __future__ import annotations

from core_shared import BaseWorkerSettings
from pydantic import SecretStr


class SnipeItWorkerSettings(BaseWorkerSettings):
    """Configuration for the Snipe-IT integration worker."""

    # Encryption key for stored Snipe-IT API keys (matches the main app).
    encryption_key: SecretStr = SecretStr("")

    # Per-worker identity overrides (see BaseWorkerSettings for the rest).
    worker_id: str = "snipeit-worker"
    queue_name: str = "arq:snipeit"
    otel_service_name: str = "snipeit-worker"
