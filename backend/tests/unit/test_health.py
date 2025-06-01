"""
Unit tests for health check endpoints.

Tests the basic health check functionality and API responses.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.mark.unit
def test_health_check(client: TestClient) -> None:
    """Test basic health check endpoint."""
    response = client.get("/api/health")

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "healthy"
    assert "timestamp" in data
    assert data["version"] == "0.1.0"
    assert "uptime" in data


@pytest.mark.unit
def test_liveness_check(client: TestClient) -> None:
    """Test Kubernetes liveness probe."""
    response = client.get("/api/health/live")

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "alive"


@pytest.mark.unit
def test_readiness_check(client: TestClient) -> None:
    """Test Kubernetes readiness probe."""
    response = client.get("/api/health/ready")

    # Should return 200 for in-memory database
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "ready"
