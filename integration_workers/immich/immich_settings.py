"""
Immich worker settings.

Pydantic settings model for the Immich integration worker.
Environment variables are loaded from the shell environment or a ``.env`` file.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class ImmichWorkerSettings(BaseSettings):
    """Configuration for the Immich integration worker."""

    database_url: str
    redis_url: str = "redis://localhost:6379"
    stream_name: str = "pms:domain-events"
    encryption_key: str = ""
    log_level: str = "INFO"
    worker_id: str = "immich-worker"
    queue_name: str = "arq:immich"

    model_config = {"env_file": ".env", "extra": "ignore"}
