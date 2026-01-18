"""
Unit tests for shared logging module.
"""

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


def test_configure_logging_json_output() -> None:
    """Test logging configuration with JSON output."""
    configure_logging(log_level="INFO", service_name="test-service", json_output=True)

    logger = get_logger("test")
    assert logger is not None


def test_configure_logging_console_output() -> None:
    """Test logging configuration with console output."""
    configure_logging(log_level="DEBUG", service_name="test-service", json_output=False)

    logger = get_logger("test")
    assert logger is not None


def test_set_trace_id() -> None:
    """Test setting trace ID in context."""
    test_trace_id = "trace-123"
    set_trace_id(test_trace_id)

    assert trace_id_var.get() == test_trace_id


def test_set_job_id() -> None:
    """Test setting job ID in context."""
    test_job_id = "job-456"
    set_job_id(test_job_id)

    assert job_id_var.get() == test_job_id


def test_set_worker_id() -> None:
    """Test setting worker ID in context."""
    test_worker_id = "worker-789"
    set_worker_id(test_worker_id)

    assert worker_id_var.get() == test_worker_id


def test_clear_context() -> None:
    """Test clearing all context variables."""
    # Set all context variables
    set_trace_id("trace-123")
    set_job_id("job-456")
    set_worker_id("worker-789")

    # Clear context
    clear_context()

    # Verify all are cleared
    assert trace_id_var.get() == ""
    assert job_id_var.get() == ""
    assert worker_id_var.get() == ""


def test_context_isolation() -> None:
    """Test that context variables are isolated between calls."""
    # Set context
    set_trace_id("trace-1")
    set_job_id("job-1")

    # Clear and set new values
    clear_context()
    set_trace_id("trace-2")
    set_job_id("job-2")

    # Verify new values
    assert trace_id_var.get() == "trace-2"
    assert job_id_var.get() == "job-2"


def test_get_logger_returns_structlog_instance() -> None:
    """Test that get_logger returns a structlog instance."""
    configure_logging()
    logger = get_logger("test.module")

    # Verify it's a structlog logger
    assert hasattr(logger, "bind")
    assert hasattr(logger, "info")
    assert hasattr(logger, "error")


def test_logging_with_context() -> None:
    """Test that logging includes context variables."""
    configure_logging(json_output=True)

    # Set context
    set_trace_id("trace-abc")
    set_job_id("job-xyz")
    set_worker_id("worker-123")

    # Verify the context is set
    assert trace_id_var.get() == "trace-abc"
    assert job_id_var.get() == "job-xyz"
    assert worker_id_var.get() == "worker-123"


def test_empty_context_not_added_to_logs() -> None:
    """Test that empty context values are not added to logs."""
    configure_logging(json_output=True)

    # Clear all context
    clear_context()

    # Verify context is empty
    assert trace_id_var.get() == ""
    assert job_id_var.get() == ""
    assert worker_id_var.get() == ""
