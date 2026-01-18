"""
Unit tests for health check endpoints.

Tests the basic health check functionality and API responses.
"""

from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from app.infrastructure.config import Settings
from app.infrastructure.database import get_database_session
from app.main import create_app


@pytest.fixture
def mock_db_session():
    """Mock database session for unit tests."""
    return Mock()


@pytest.fixture
def unit_test_client(mock_db_session):
    """Create test client with mocked database for unit tests."""
    # Create test settings that allow all hosts
    # Unit tests should not connect to any real database or Redis
    test_settings = Settings(
        debug=True,
        allowed_hosts=["*"],  # Allow all hosts for testing
        cors_origins=["*"],
        # Use a dummy PostgreSQL URL - it won't be used due to dependency override
        database_url="postgresql://dummy:dummy@localhost:5432/dummy",
        # Use a dummy Redis URL - will fail connection as expected in unit tests
        redis_url="redis://dummy:6379",
    )

    app = create_app(settings=test_settings)
    app.dependency_overrides[get_database_session] = lambda: mock_db_session
    return TestClient(app)


@pytest.mark.unit
def test_health_check(unit_test_client: TestClient) -> None:
    """Test basic health check endpoint."""
    response = unit_test_client.get("/api/health")

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "healthy"
    assert "timestamp" in data
    assert data["version"] == "0.1.0"
    assert "uptime" in data


@pytest.mark.unit
def test_liveness_check(unit_test_client: TestClient) -> None:
    """Test Kubernetes liveness probe."""
    response = unit_test_client.get("/api/health/live")

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "alive"


@pytest.mark.unit
@patch("app.api.health.check_database_connection")
def test_readiness_check_healthy(mock_db_check, unit_test_client: TestClient) -> None:
    """Test Kubernetes readiness probe when database is healthy."""
    # Mock database connection as healthy
    mock_db_check.return_value = True

    response = unit_test_client.get("/api/health/ready")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    mock_db_check.assert_called_once()


@pytest.mark.unit
@patch("app.api.health.check_database_connection")
def test_readiness_check_unhealthy(mock_db_check, unit_test_client: TestClient) -> None:
    """Test Kubernetes readiness probe when database is unhealthy."""
    # Mock database connection as unhealthy
    mock_db_check.return_value = False

    response = unit_test_client.get("/api/health/ready")

    assert response.status_code == 503
    mock_db_check.assert_called_once()


@pytest.mark.unit
def test_metrics_endpoint(unit_test_client: TestClient) -> None:
    """Test Prometheus metrics endpoint."""
    response = unit_test_client.get("/api/metrics")

    assert response.status_code == 200
    # Check content type starts with text/plain (version may vary)
    assert response.headers["content-type"].startswith("text/plain")
    assert "charset=utf-8" in response.headers["content-type"]

    # Verify metrics are in Prometheus format
    content = response.text
    assert "# HELP" in content or "# TYPE" in content  # Prometheus format markers


@pytest.mark.unit
def test_integration_health_check_components_importable() -> None:
    """Test that integration health check components can be imported (unit test safe)."""
    # Test core_shared package accessibility
    try:
        from core_shared.base_service import BaseIntegrationService, SyncResult
        from core_shared.models.external_reference import ExternalReference
        from core_shared.models.sync_metadata import SyncMetadata, SyncStatus

        # Verify enums work correctly
        _ = SyncStatus.SUCCESS
        _ = SyncResult.SUCCESS

        # Test that we can reference the classes
        available_models = [
            SyncMetadata.__name__,
            ExternalReference.__name__,
            BaseIntegrationService.__name__,
        ]
        assert len(available_models) == 3
        assert "SyncMetadata" in available_models
        assert "ExternalReference" in available_models
        assert "BaseIntegrationService" in available_models

    except Exception as e:
        pytest.fail(f"Core shared package import failed: {e}")

    # Test integration domain configuration
    try:
        from app.core.integrations.database import IntegrationDatabaseManager
        from app.core.integrations.exceptions import IntegrationError
        from app.core.integrations.task_queue import TaskQueueConfig

        # Verify configuration is accessible
        config = TaskQueueConfig()
        assert config.QUEUE_NAME == "integration_tasks"
        assert config.MAX_JOBS == 10
        assert config.JOB_TIMEOUT == 300
        assert config.MAX_TRIES == 3

        # Test that we can reference the classes
        available_components = [
            IntegrationError.__name__,
            IntegrationDatabaseManager.__name__,
        ]
        assert len(available_components) == 2
        assert "IntegrationError" in available_components
        assert "IntegrationDatabaseManager" in available_components

    except Exception as e:
        pytest.fail(f"Integration domain import failed: {e}")
