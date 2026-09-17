"""
Integration tests for health check endpoints.

Tests the health check endpoints with real database connectivity.
"""

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.infrastructure.events.outbox_rows import (
    insert_outbox_event,
    relay_everything,
)


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


@pytest.mark.integration
def test_consumer_lag_check_integration(integration_test_client: TestClient) -> None:
    """Test consumer lag health check endpoint."""
    response = integration_test_client.get("/api/health/consumer-lag")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.integration
def test_dead_letters_check_integration(integration_test_client: TestClient) -> None:
    """Test dead letters health check endpoint."""
    response = integration_test_client.get("/api/health/dead-letters")

    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert isinstance(data["items"], list)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_outbox_backlog_counts_the_events_not_yet_relayed(
    authenticated_client: AsyncClient, async_connection: AsyncConnection
) -> None:
    """The outbox backlog endpoint reports the events the relay has yet to publish."""
    await relay_everything(async_connection)
    await insert_outbox_event(async_connection)
    await insert_outbox_event(async_connection)

    response = await authenticated_client.get("/api/health/outbox-backlog")

    assert response.status_code == 200
    assert response.json() == {"unrelayed_count": 2}
