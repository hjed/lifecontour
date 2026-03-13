"""
Shared Prometheus metrics for Personal Management System.

Provides golden signal metrics (latency, traffic, errors, saturation) for
integration workers and backend services.
"""

from prometheus_client import Counter, Gauge, Histogram

# Job processing metrics (golden signals)

job_duration = Histogram(
    "worker_job_duration_seconds",
    "Time spent processing jobs",
    ["worker_type", "job_type", "status"],
    buckets=(
        0.1,
        0.5,
        1.0,
        2.5,
        5.0,
        10.0,
        30.0,
        60.0,
        120.0,
        300.0,
        600.0,
        float("inf"),
    ),
)

job_total = Counter(
    "worker_jobs_total",
    "Total number of jobs processed",
    ["worker_type", "job_type", "status"],
)

queue_depth = Gauge(
    "worker_queue_depth",
    "Number of jobs waiting in queue",
    ["worker_type"],
)

# Sync-specific metrics

sync_items_processed = Counter(
    "sync_items_processed_total",
    "Total number of items processed during sync",
    ["worker_type", "sync_type", "action"],
)

sync_errors = Counter(
    "sync_errors_total",
    "Total number of sync errors",
    ["worker_type", "sync_type", "error_type"],
)

sync_conflicts = Counter(
    "sync_conflicts_total",
    "Total number of sync conflicts detected",
    ["worker_type", "sync_type"],
)

# API metrics

api_requests_total = Counter(
    "api_requests_total",
    "Total number of API requests",
    ["method", "endpoint", "status"],
)

api_request_duration = Histogram(
    "api_request_duration_seconds",
    "API request duration",
    ["method", "endpoint"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf")),
)


class MetricsCollector:
    """
    Helper class for collecting metrics with consistent labels.

    Provides convenience methods for recording common metric patterns.
    """

    def __init__(self, worker_type: str):
        """
        Initialize metrics collector.

        Args:
            worker_type: Type of worker (e.g., 'google', 'strava')
        """
        self.worker_type = worker_type

    def record_job_duration(self, job_type: str, status: str, duration: float) -> None:
        """
        Record job duration metric.

        Args:
            job_type: Type of job (e.g., 'sync', 'push')
            status: Job status ('success', 'error', 'cancelled')
            duration: Duration in seconds
        """
        job_duration.labels(
            worker_type=self.worker_type, job_type=job_type, status=status
        ).observe(duration)

    def increment_job_total(self, job_type: str, status: str) -> None:
        """
        Increment job total counter.

        Args:
            job_type: Type of job (e.g., 'sync', 'push')
            status: Job status ('success', 'error', 'cancelled')
        """
        job_total.labels(
            worker_type=self.worker_type, job_type=job_type, status=status
        ).inc()

    def set_queue_depth(self, depth: int) -> None:
        """
        Set current queue depth.

        Args:
            depth: Number of jobs in queue
        """
        queue_depth.labels(worker_type=self.worker_type).set(depth)

    def increment_items_processed(
        self, sync_type: str, action: str, count: int = 1
    ) -> None:
        """
        Increment items processed counter.

        Args:
            sync_type: Type of sync ('full', 'incremental', 'push')
            action: Action taken ('created', 'updated', 'deleted', 'skipped')
            count: Number of items (default: 1)
        """
        sync_items_processed.labels(
            worker_type=self.worker_type, sync_type=sync_type, action=action
        ).inc(count)

    def increment_sync_errors(self, sync_type: str, error_type: str) -> None:
        """
        Increment sync errors counter.

        Args:
            sync_type: Type of sync ('full', 'incremental', 'push')
            error_type: Type of error ('api_error', 'validation_error', 'conflict')
        """
        sync_errors.labels(
            worker_type=self.worker_type, sync_type=sync_type, error_type=error_type
        ).inc()

    def increment_sync_conflicts(self, sync_type: str) -> None:
        """
        Increment sync conflicts counter.

        Args:
            sync_type: Type of sync ('full', 'incremental', 'push')
        """
        sync_conflicts.labels(worker_type=self.worker_type, sync_type=sync_type).inc()


__all__ = [
    "job_duration",
    "job_total",
    "queue_depth",
    "sync_items_processed",
    "sync_errors",
    "sync_conflicts",
    "api_requests_total",
    "api_request_duration",
    "MetricsCollector",
]
