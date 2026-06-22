"""
Core shared package for Personal Management System integrations.

This package contains shared models, database utilities, and common patterns
used across the main application and integration workers.
"""

__version__ = "0.1.0"

from core_shared.base_service import (
    BaseIntegrationService,
    IntegrationError,
    SyncDirection,
    SyncError,
    SyncResult,
    TransformationError,
)
from core_shared.contact_name_matcher import ContactNameMatcher

# Only import what's available to avoid circular imports
from core_shared.database.engine import (
    create_async_engine_from_url,
    create_session_factory,
)
from core_shared.fanout import (
    coerce_int,
    is_final_attempt,
    persist_fanout_children,
    record_child_terminal,
)
from core_shared.logging import (
    clear_context,
    configure_logging,
    get_logger,
    job_id_var,
    set_job_id,
    set_trace_id,
    set_worker_id,
    trace_id_var,
    worker_id_var,
)
from core_shared.metrics import (
    MetricsCollector,
    api_request_duration,
    api_requests_total,
    job_duration,
    job_total,
    queue_depth,
    sync_conflicts,
    sync_errors,
    sync_items_processed,
)
from core_shared.models import (
    Base,
    ExternalEventLinkSyncCapability,
    ExternalEventLinkSyncStatus,
    JournalExternalEventLink,
    PendingEntityMapping,
    SyncMetadata,
    SyncStatus,
)
from core_shared.sync_reconciliation import (
    reconcile_in_progress_parents,
    reconcile_parents,
)
from core_shared.worker_arq import (
    DEFAULT_HEALTH_CHECK_INTERVAL,
    DEFAULT_JOB_TIMEOUT,
    DEFAULT_KEEP_RESULT,
    DEFAULT_MAX_TRIES,
    SharedARQWorkerSettings,
    build_worker_lifecycle,
    default_retry_delay,
    generate_cron_jobs,
    generate_reconciliation_cron,
)
from core_shared.worker_settings import (
    BaseWorkerSettings,
    redis_settings_from_url,
)

__all__ = [
    "Base",
    "ContactNameMatcher",
    "PendingEntityMapping",
    "SyncMetadata",
    "SyncStatus",
    "JournalExternalEventLink",
    "ExternalEventLinkSyncCapability",
    "ExternalEventLinkSyncStatus",
    "create_async_engine_from_url",
    "create_session_factory",
    "BaseIntegrationService",
    "SyncResult",
    "SyncDirection",
    "IntegrationError",
    "SyncError",
    "TransformationError",
    # Logging
    "configure_logging",
    "get_logger",
    "set_trace_id",
    "set_job_id",
    "set_worker_id",
    "clear_context",
    "trace_id_var",
    "job_id_var",
    "worker_id_var",
    # Metrics
    "job_duration",
    "job_total",
    "queue_depth",
    "sync_items_processed",
    "sync_errors",
    "sync_conflicts",
    "api_requests_total",
    "api_request_duration",
    "MetricsCollector",
    # Worker settings
    "BaseWorkerSettings",
    "redis_settings_from_url",
    # Shared ARQ toolkit
    "SharedARQWorkerSettings",
    "default_retry_delay",
    "generate_cron_jobs",
    "generate_reconciliation_cron",
    "build_worker_lifecycle",
    "DEFAULT_JOB_TIMEOUT",
    "DEFAULT_KEEP_RESULT",
    "DEFAULT_MAX_TRIES",
    "DEFAULT_HEALTH_CHECK_INTERVAL",
    # Fan-out reconciliation
    "reconcile_in_progress_parents",
    "reconcile_parents",
    # Fan-out helpers
    "coerce_int",
    "is_final_attempt",
    "persist_fanout_children",
    "record_child_terminal",
]
