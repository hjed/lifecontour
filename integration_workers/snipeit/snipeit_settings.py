"""
Snipe-IT worker settings.

Pydantic settings model for the Snipe-IT integration worker.
Environment variables are loaded from the shell environment or a ``.env`` file.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class SnipeItWorkerSettings(BaseSettings):
    """Configuration for the Snipe-IT integration worker."""

    database_url: str
    redis_url: str = "redis://localhost:6379"
    stream_name: str = "pms:domain-events"
    encryption_key: str = ""
    log_level: str = "INFO"
    worker_id: str = "snipeit-worker"

    model_config = {"env_file": ".env", "extra": "ignore"}
