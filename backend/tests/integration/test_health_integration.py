"""
Integration tests for health check endpoints.

Tests the health check endpoints with real database connectivity.
"""

import pytest
from fastapi.testclient import TestClient

from app.infrastructure.config import Settings
from app.main import create_app


@pytest.fixture
def integration_test_client():
    """Create test client for integration tests with real database setup."""
    # Create test settings for integration tests
    test_settings = Settings(
        debug=True,
        allowed_hosts=["*"],  # Allow all hosts for testing
        cors_origins=["*"],
        database_url="postgresql+asyncpg://postgres:postgres@localhost:5433/personal_management_test",
    )

    app = create_app(settings=test_settings)
    return TestClient(app)


@pytest.mark.integration
def test_health_check_integration(integration_test_client: TestClient) -> None:
    """Test basic health check endpoint in integration environment."""
    response = integration_test_client.get("/api/health")

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "healthy"
    assert "timestamp" in data
    assert data["version"] == "0.1.0"
    assert "uptime" in data


@pytest.mark.integration
def test_liveness_check_integration(integration_test_client: TestClient) -> None:
    """Test Kubernetes liveness probe in integration environment."""
    response = integration_test_client.get("/api/health/live")

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "alive"


@pytest.mark.integration
def test_readiness_check_integration(integration_test_client: TestClient) -> None:
    """Test Kubernetes readiness probe with real database connectivity."""
    response = integration_test_client.get("/api/health/ready")

    # Should return 200 when database is available
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"


@pytest.mark.integration
def test_detailed_health_check_integration(integration_test_client: TestClient) -> None:
    """Test detailed health check endpoint with real database connectivity."""
    response = integration_test_client.get("/api/health/detailed")

    assert response.status_code == 200
    data = response.json()

    assert data["status"] in ["healthy", "degraded"]  # Could be degraded if DB is slow
    assert "timestamp" in data
    assert data["version"] == "0.1.0"
    assert "uptime" in data
    assert "services" in data
    assert "database" in data["services"]
    assert data["services"]["database"]["type"] == "postgresql"
    assert data["services"]["database"]["status"] in ["healthy", "unhealthy"]
