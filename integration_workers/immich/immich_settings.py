"""
Immich worker settings.

Pydantic settings model for the Immich integration worker. The common worker
surface (database/Redis connection, ARQ queue/stream identity, logging,
periodic-sync cadence and the OpenTelemetry block) is inherited from the shared
``core_shared.BaseWorkerSettings``; only the Immich-specific fields are declared
here. Environment variables are loaded from the shell environment or a ``.env``
file.
"""

from __future__ import annotations

from core_shared import BaseWorkerSettings
from pydantic import SecretStr


class ImmichWorkerSettings(BaseWorkerSettings):
    """Configuration for the Immich integration worker."""

    # Encryption key for stored Immich API keys (matches the main app).
    encryption_key: SecretStr = SecretStr("")

    # Per-worker identity overrides (see BaseWorkerSettings for the rest).
    worker_id: str = "immich-worker"
    queue_name: str = "arq:immich"
    otel_service_name: str = "immich-worker"
