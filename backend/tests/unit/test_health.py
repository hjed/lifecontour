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
    test_settings = Settings(
        debug=True,
        allowed_hosts=["*"],  # Allow all hosts for testing
        cors_origins=["*"],
        database_url="sqlite:///:memory:",  # Use in-memory SQLite for unit tests
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
