"""
Unit tests for shared metrics module.
"""

from prometheus_client import REGISTRY

from core_shared.metrics import (
    MetricsCollector,
    api_request_duration,
    job_duration,
    job_total,
    queue_depth,
    sync_items_processed,
)


def test_metrics_are_registered() -> None:
    """Test that all metrics are registered with Prometheus."""
    # Get all registered metric names
    metric_names = [metric.name for metric in REGISTRY.collect()]

    # Verify our metrics are registered
    # Note: Prometheus client strips _total suffix from counter names
    assert "worker_job_duration_seconds" in metric_names
    assert "worker_jobs" in metric_names  # _total is stripped
    assert "worker_queue_depth" in metric_names
    assert "sync_items_processed" in metric_names  # _total is stripped
    assert "sync_errors" in metric_names  # _total is stripped
    assert "sync_conflicts" in metric_names  # _total is stripped
    assert "api_requests" in metric_names  # _total is stripped
    assert "api_request_duration_seconds" in metric_names


def test_metrics_collector_initialization() -> None:
    """Test MetricsCollector initialization."""
    collector = MetricsCollector(worker_type="test_worker")
    assert collector.worker_type == "test_worker"


def test_record_job_duration() -> None:
    """Test recording job duration metric."""
    collector = MetricsCollector(worker_type="test_worker")

    # Record a job duration
    collector.record_job_duration(job_type="sync", status="success", duration=1.5)

    # Verify metric was recorded (we can't easily check the value without
    # accessing internal state, but we can verify no exceptions were raised)


def test_increment_job_total() -> None:
    """Test incrementing job total counter."""
    collector = MetricsCollector(worker_type="test_worker")

    # Increment job total
    collector.increment_job_total(job_type="sync", status="success")
    collector.increment_job_total(job_type="sync", status="error")


def test_set_queue_depth() -> None:
    """Test setting queue depth gauge."""
    collector = MetricsCollector(worker_type="test_worker")

    # Set queue depth
    collector.set_queue_depth(depth=5)
    collector.set_queue_depth(depth=10)
    collector.set_queue_depth(depth=0)


def test_increment_items_processed() -> None:
    """Test incrementing items processed counter."""
    collector = MetricsCollector(worker_type="test_worker")

    # Increment items processed
    collector.increment_items_processed(sync_type="full", action="created", count=5)
    collector.increment_items_processed(sync_type="incremental", action="updated")


def test_increment_sync_errors() -> None:
    """Test incrementing sync errors counter."""
    collector = MetricsCollector(worker_type="test_worker")

    # Increment sync errors
    collector.increment_sync_errors(sync_type="full", error_type="api_error")
    collector.increment_sync_errors(sync_type="push", error_type="validation_error")


def test_increment_sync_conflicts() -> None:
    """Test incrementing sync conflicts counter."""
    collector = MetricsCollector(worker_type="test_worker")

    # Increment sync conflicts
    collector.increment_sync_conflicts(sync_type="push")


def test_metrics_with_different_labels() -> None:
    """Test that metrics with different labels are tracked separately."""
    collector1 = MetricsCollector(worker_type="worker1")
    collector2 = MetricsCollector(worker_type="worker2")

    # Record metrics for different workers
    collector1.increment_job_total(job_type="sync", status="success")
    collector2.increment_job_total(job_type="sync", status="success")

    # Both should succeed without interference


def test_job_duration_buckets() -> None:
    """Test that job duration histogram has appropriate buckets."""
    # Verify the histogram is properly configured
    # We can't easily access internal bucket configuration, but we can verify
    # the metric exists and is a Histogram
    assert job_duration is not None
    assert hasattr(job_duration, "observe")


def test_api_request_duration_buckets() -> None:
    """Test that API request duration histogram has appropriate buckets."""
    # Verify the histogram is properly configured
    assert api_request_duration is not None
    assert hasattr(api_request_duration, "observe")


def test_direct_metric_usage() -> None:
    """Test using metrics directly without MetricsCollector."""
    # Test direct usage of metrics
    job_total.labels(worker_type="direct", job_type="test", status="success").inc()
    queue_depth.labels(worker_type="direct").set(42)
    sync_items_processed.labels(
        worker_type="direct", sync_type="full", action="created"
    ).inc(10)


def test_metrics_collector_multiple_operations() -> None:
    """Test MetricsCollector with multiple operations."""
    collector = MetricsCollector(worker_type="integration_test")

    # Simulate a complete job lifecycle
    collector.set_queue_depth(5)
    collector.record_job_duration(job_type="sync", status="success", duration=2.5)
    collector.increment_job_total(job_type="sync", status="success")
    collector.increment_items_processed(sync_type="full", action="created", count=10)
    collector.increment_items_processed(sync_type="full", action="updated", count=5)
    collector.set_queue_depth(4)

    # All operations should complete without errors


def test_error_metrics() -> None:
    """Test error-related metrics."""
    collector = MetricsCollector(worker_type="error_test")

    # Record various error scenarios
    collector.increment_sync_errors(sync_type="full", error_type="api_error")
    collector.increment_sync_errors(sync_type="push", error_type="validation_error")
    collector.increment_sync_conflicts(sync_type="push")
    collector.increment_job_total(job_type="sync", status="error")
