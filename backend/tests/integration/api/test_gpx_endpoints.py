"""
Integration tests for GPX track data API endpoint.

Tests the GET /api/journals/{id}/gpx endpoint which parses GPX XML from
fitness data and returns coordinates + statistics for map rendering.
"""

from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

# Sample GPX data with track points, elevation, and timestamps
SAMPLE_GPX_DATA = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test"
     xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <name>Sydney Harbour Walk</name>
    <trkseg>
      <trkpt lat="-33.8688" lon="151.2093">
        <ele>10</ele>
        <time>2024-01-15T10:00:00Z</time>
      </trkpt>
      <trkpt lat="-33.8700" lon="151.2100">
        <ele>25</ele>
        <time>2024-01-15T10:15:00Z</time>
      </trkpt>
      <trkpt lat="-33.8712" lon="151.2110">
        <ele>15</ele>
        <time>2024-01-15T10:30:00Z</time>
      </trkpt>
    </trkseg>
  </trk>
</gpx>"""


def _build_journal_create_request(title: str = "Test Journal") -> dict[str, Any]:
    """Build a minimal journal create request."""
    return {
        "data": {
            "type": "journals",
            "attributes": {
                "title": title,
                "content": "Test content",
                "event_date_range": {
                    "start": "2024-01-15T10:00:00Z",
                    "end": "2024-01-15T11:00:00Z",
                },
            },
        }
    }


async def _create_journal(client: AsyncClient, title: str = "Test Journal") -> int:
    """Create a journal and return its integer ID."""
    response = await client.post(
        "/api/journals", json=_build_journal_create_request(title)
    )
    assert response.status_code == 201, f"Failed to create journal: {response.json()}"
    return int(response.json()["data"]["id"])


async def _add_fitness_type_with_gpx(
    client: AsyncClient, journal_id: int, gpx_data: str
) -> None:
    """Add FITNESS type to a journal and set GPX track data."""
    # Add FITNESS type
    add_type_request = {
        "data": {
            "type": "journal-types",
            "attributes": {
                "journal_type": "fitness",
                "type_data": {},
            },
        }
    }
    response = await client.post(
        f"/api/journals/{journal_id}/types", json=add_type_request
    )
    assert response.status_code in [
        200,
        201,
    ], f"Failed to add FITNESS type: {response.json()}"

    # Update fitness data with GPX
    update_type_data_request = {
        "data": {
            "type": "journal-type-data",
            "attributes": {
                "gpx_track_data": gpx_data,
            },
        }
    }
    response = await client.put(
        f"/api/journals/{journal_id}/types/fitness/data",
        json=update_type_data_request,
    )
    assert response.status_code == 200, (
        f"Failed to update fitness data: {response.json()}"
    )


@pytest_asyncio.fixture
async def integration_api_client(async_connection, clean_database, test_settings):  # noqa: ARG001
    """Create async test client for API integration tests with real database setup."""
    from dishka import Provider, Scope, make_async_container, provide
    from dishka.integrations.fastapi import FastapiProvider, setup_dishka
    from sqlalchemy.ext.asyncio import AsyncConnection

    from app.infrastructure.auth.models import SessionUser
    from app.infrastructure.di.contacts import ContactProvider
    from app.infrastructure.di.infrastructure import InfrastructureProvider
    from app.infrastructure.di.integrations import IntegrationProvider
    from app.infrastructure.di.journal import JournalProvider

    class TestDatabaseProvider(Provider):
        """Test provider that uses the test database connection."""

        def __init__(self, connection: AsyncConnection):
            super().__init__()
            self.connection = connection

        @provide(scope=Scope.REQUEST)
        async def get_connection(self) -> AsyncConnection:
            return self.connection

        @provide(scope=Scope.REQUEST)
        def get_session_user(self) -> SessionUser:
            """Provide a test user for authentication."""
            return SessionUser(
                id="test-user-123",
                email="test@example.com",
                name="Test User",
                avatar_url="https://example.com/avatar.jpg",
                provider="test",
            )

    app = create_app(settings=test_settings)

    # Replace the Dishka container with our test container
    await app.state.dishka_container.close()

    test_container = make_async_container(
        TestDatabaseProvider(async_connection),
        InfrastructureProvider(),
        ContactProvider(),
        JournalProvider(),
        IntegrationProvider(),
        FastapiProvider(),
    )
    app.state.dishka_container = test_container
    setup_dishka(test_container, app)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client

    await test_container.close()


@pytest_asyncio.fixture
async def unauthenticated_client(test_settings):
    """Create async test client without authentication."""
    app = create_app(settings=test_settings)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client


@pytest.mark.integration
class TestGpxEndpoint:
    """Integration tests for GET /api/journals/{id}/gpx."""

    async def test_get_gpx_data_success(self, integration_api_client):
        """Test successfully retrieving parsed GPX data for a journal."""
        journal_id = await _create_journal(integration_api_client, "Bushwalk with GPX")
        await _add_fitness_type_with_gpx(
            integration_api_client, journal_id, SAMPLE_GPX_DATA
        )

        response = await integration_api_client.get(f"/api/journals/{journal_id}/gpx")

        assert response.status_code == 200
        data = response.json()

        # Verify JSON API structure
        assert data["data"]["type"] == "gpx-track-data"
        assert data["data"]["id"] == str(journal_id)

        # Verify coordinates
        coords = data["data"]["attributes"]["coordinates"]
        assert len(coords) == 3
        assert coords[0]["latitude"] == pytest.approx(-33.8688)
        assert coords[0]["longitude"] == pytest.approx(151.2093)
        assert coords[0]["elevation"] == pytest.approx(10.0)

        # Verify statistics
        stats = data["data"]["attributes"]["statistics"]
        assert stats["distance_2d"] > 0
        assert stats["distance_3d"] > 0
        assert stats["elevation_gain"] >= 0
        assert stats["elevation_loss"] >= 0
        # 30 minutes = 1800 seconds
        assert stats["duration_seconds"] == pytest.approx(1800.0)

    async def test_get_gpx_data_no_fitness_data(self, integration_api_client):
        """Test 404 when journal has no FITNESS type."""
        journal_id = await _create_journal(
            integration_api_client, "Journal without fitness"
        )

        response = await integration_api_client.get(f"/api/journals/{journal_id}/gpx")

        assert response.status_code == 404

    async def test_get_gpx_data_no_gpx_track(self, integration_api_client):
        """Test 404 when FITNESS journal has no gpx_track_data."""
        journal_id = await _create_journal(
            integration_api_client, "Fitness without GPX"
        )
        # Add FITNESS type without GPX data
        add_type_request = {
            "data": {
                "type": "journal-types",
                "attributes": {
                    "journal_type": "fitness",
                    "type_data": {},
                },
            }
        }
        response = await integration_api_client.post(
            f"/api/journals/{journal_id}/types", json=add_type_request
        )
        assert response.status_code in [200, 201]

        response = await integration_api_client.get(f"/api/journals/{journal_id}/gpx")

        assert response.status_code == 404

    async def test_get_gpx_data_journal_not_found(self, integration_api_client):
        """Test 404 for nonexistent journal ID."""
        response = await integration_api_client.get("/api/journals/999999/gpx")

        assert response.status_code == 404

    async def test_get_gpx_data_requires_auth(self, unauthenticated_client):
        """Test that the GPX endpoint requires authentication."""
        response = await unauthenticated_client.get("/api/journals/1/gpx")

        assert response.status_code == 401
