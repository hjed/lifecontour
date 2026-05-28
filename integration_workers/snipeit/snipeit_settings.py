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
    queue_name: str = "arq:snipeit"

    # Observability
    enable_telemetry: bool = False
    otel_exporter_otlp_endpoint: str = ""
    otel_service_name: str = "snipeit-worker"
    otel_resource_attributes: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}
