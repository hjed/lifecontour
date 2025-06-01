"""
Integration tests for health check endpoints.

Tests the health check endpoints with real database connectivity.
"""

import os

import pytest
from fastapi.testclient import TestClient

from app.infrastructure.config import get_settings
from app.infrastructure.database import get_database_engine
from app.main import create_app


@pytest.fixture
def integration_test_client():
    """Create test client for integration tests with real database setup."""
    # Set environment variables for test database and allowed hosts
    original_db_url = os.environ.get("DATABASE_URL")
    original_allowed_hosts = os.environ.get("ALLOWED_HOSTS")
    os.environ["DATABASE_URL"] = "postgresql://postgres:postgres@localhost:5433/personal_management_test"
    os.environ["ALLOWED_HOSTS"] = '["*"]'

    # Clear the cached settings and database engine
    get_settings.cache_clear()
    get_database_engine.cache_clear()

    try:
        app = create_app()
        yield TestClient(app)
    finally:
        # Restore original environment
        if original_db_url:
            os.environ["DATABASE_URL"] = original_db_url
        elif "DATABASE_URL" in os.environ:
            del os.environ["DATABASE_URL"]

        if original_allowed_hosts:
            os.environ["ALLOWED_HOSTS"] = original_allowed_hosts
        elif "ALLOWED_HOSTS" in os.environ:
            del os.environ["ALLOWED_HOSTS"]

        # Clear cache again to restore original settings
        get_settings.cache_clear()
        get_database_engine.cache_clear()


@pytest.mark.integration
def test_health_check_integration(integration_test_client: TestClient) -> None:
    """Test basic health check endpoint in integration environment."""
    response = integration_test_client.get("/api/health")

    if response.status_code != 200:
        print(f"Response status: {response.status_code}")
        print(f"Response content: {response.text}")

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
