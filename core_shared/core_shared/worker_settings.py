"""
Shared base settings for integration workers.

Provides ``BaseWorkerSettings`` — the canonical Pydantic ``BaseSettings`` model
holding every field common to the integration workers (database/redis
connection, ARQ queue/stream identity, logging, periodic-sync cadence, and the
OpenTelemetry block) — and ``redis_settings_from_url``, which derives ARQ
``RedisSettings`` from a ``redis://`` URL.

Workers subclass ``BaseWorkerSettings`` and add only integration-specific
fields, so the common surface is declared once. ``database_url`` (and any other
secret) is a ``SecretStr`` to keep secrets out of logs and tracebacks.

This module is additive: see the iteration-14 worker-standardisation plan. The
per-worker settings classes migrate onto this base in later phases, at which
point the duplicated ``_parse_redis_url`` helpers in the immich/snipeit workers
are replaced by ``redis_settings_from_url``.

``arq`` is intentionally **not** a hard runtime dependency of ``core_shared``:
``arq`` pins ``redis<6`` while ``core_shared`` requires ``redis>=8`` (reconciled
by ``[tool.uv] override-dependencies`` when ``core_shared`` is the resolution
root). Importing it lazily inside ``redis_settings_from_url`` keeps ``import
core_shared`` working in environments that install ``core_shared`` as a bare
dependency without that override (e.g. the shared ``python-base`` image used by
the backend, which never calls this helper). The integration workers that do
call it always depend on ``arq``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from arq.connections import RedisSettings


class BaseWorkerSettings(BaseSettings):
    """Common configuration shared by all integration workers.

    Loaded from the process environment or a ``.env`` file. Subclasses declare
    only integration-specific fields and override the per-worker defaults
    (``worker_id``, ``queue_name``, ``otel_service_name``) as needed.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database connection (required; SecretStr keeps the DSN out of logs).
    database_url: SecretStr

    # Redis connection used for the ARQ job queue and the event stream.
    redis_url: str = "redis://redis:6379"

    # Name of the shared domain-events Redis stream the worker consumes.
    stream_name: str = "pms:domain-events"

    # Per-worker identifier (override per worker, e.g. "immich-worker").
    worker_id: str = "worker"

    # ARQ queue name (defaults to arq's own default queue; override per worker).
    queue_name: str = "arq:queue"

    # Logging verbosity.
    log_level: str = "INFO"

    # Periodic full-sync scheduling (disabled by default).
    enable_periodic_sync: bool = False
    sync_interval_hours: int = 6

    # Fan-out reconciliation: how long an IN_PROGRESS parent may go without its
    # children progressing before the reconciler marks it FAILED (stuck/timeout).
    reconciliation_stale_after_seconds: int = 1800

    # OpenTelemetry / observability (disabled by default).
    enable_telemetry: bool = False
    otel_exporter_otlp_endpoint: str = ""
    otel_service_name: str = "worker"
    otel_resource_attributes: str = ""


def redis_settings_from_url(redis_url: str) -> RedisSettings:
    """Derive ARQ ``RedisSettings`` from a ``redis://`` URL.

    Wraps :meth:`arq.connections.RedisSettings.from_dsn`, handling the
    host/port/database/password forms. This is the single shared replacement for
    the duplicated ``_parse_redis_url`` helpers in the immich and snipeit
    workers.

    ``arq`` is imported lazily so that importing ``core_shared`` does not require
    it (see the module docstring); callers of this helper always depend on
    ``arq``.
    """
    from arq.connections import RedisSettings

    return RedisSettings.from_dsn(redis_url)
