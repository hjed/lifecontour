"""
Integration tests for route API endpoints.

Tests all CRUD operations, pagination, filtering, and error cases for routes API.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

# Constants
FAKE_UUID = "00000000-0000-0000-0000-000000000000"


# Helper functions
def build_route_request(
    name: str, description: str | None = None, gpx_data: str | None = None
) -> dict[str, dict[str, str | dict[str, str | None]]]:
    """Build a route create/update request payload."""
    attributes: dict[str, str | None] = {"name": name}
    if description is not None:
        attributes["description"] = description
    if gpx_data is not None:
        attributes["gpx_data"] = gpx_data

    return {
        "data": {
            "type": "routes",
            "attributes": attributes,
        }
    }


def build_route_update_request(
    route_id: str,
    name: str,
    description: str | None = None,
    gpx_data: str | None = None,
) -> dict[str, dict[str, str | dict[str, str | None]]]:
    """Build a route update request payload with ID."""
    request = build_route_request(name, description, gpx_data)
    request["data"]["id"] = route_id
    return request


async def create_route(
    client: AsyncClient,
    name: str,
    description: str | None = None,
    gpx_data: str | None = None,
) -> str:
    """Helper to create a route and return its ID."""
    request_data = build_route_request(name, description, gpx_data)
    response = await client.post("/api/routes", json=request_data)
    assert response.status_code == 201
    route_id: str = response.json()["data"]["id"]
    return route_id


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
    await app.state.dishka_container.close()  # Close the original container

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

    # Clean up the test container
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
class TestRouteEndpoints:
    """Integration tests for route CRUD operations."""

    async def test_create_route_minimal(self, integration_api_client):
        """Test creating a route with minimal data."""
        request_data = build_route_request("Mount Kosciuszko Summit Track")

        response = await integration_api_client.post("/api/routes", json=request_data)

        assert response.status_code == 201
        data = response.json()
        assert data["data"]["type"] == "routes"
        assert data["data"]["attributes"]["name"] == "Mount Kosciuszko Summit Track"
        assert data["data"]["attributes"]["description"] is None
        assert data["data"]["attributes"]["gpx_data"] is None
        assert "id" in data["data"]
        assert "created_at" in data["data"]["attributes"]
        assert "updated_at" in data["data"]["attributes"]

    async def test_create_route_with_description(self, integration_api_client):
        """Test creating a route with description."""
        request_data = build_route_request(
            "Blue Mountains Grand Canyon",
            description="A challenging canyon walk with stunning views",
        )

        response = await integration_api_client.post("/api/routes", json=request_data)

        assert response.status_code == 201
        data = response.json()
        assert data["data"]["attributes"]["name"] == "Blue Mountains Grand Canyon"
        assert (
            data["data"]["attributes"]["description"]
            == "A challenging canyon walk with stunning views"
        )

    async def test_create_route_with_gpx_data(self, integration_api_client):
        """Test creating a route with GPX data."""
        gpx_data = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Test">
  <trk>
    <name>Test Track</name>
    <trkseg>
      <trkpt lat="-33.8688" lon="151.2093">
        <ele>10</ele>
      </trkpt>
    </trkseg>
  </trk>
</gpx>"""

        request_data = build_route_request(
            "Sydney Harbour Walk",
            description="Coastal walk around Sydney Harbour",
            gpx_data=gpx_data,
        )

        response = await integration_api_client.post("/api/routes", json=request_data)

        assert response.status_code == 201
        data = response.json()
        assert data["data"]["attributes"]["name"] == "Sydney Harbour Walk"
        assert data["data"]["attributes"]["gpx_data"] == gpx_data

    async def test_get_route(self, integration_api_client):
        """Test getting a single route by ID."""
        # Create a route first
        route_id = await create_route(
            integration_api_client, "Test Route", description="Test description"
        )

        # Get the route
        response = await integration_api_client.get(f"/api/routes/{route_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["id"] == route_id
        assert data["data"]["attributes"]["name"] == "Test Route"
        assert data["data"]["attributes"]["description"] == "Test description"

    async def test_list_routes_empty(self, integration_api_client):
        """Test listing routes when none exist."""
        response = await integration_api_client.get("/api/routes")

        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert "meta" in data
        assert "links" in data
        assert isinstance(data["data"], list)

    async def test_list_routes_with_data(self, integration_api_client):
        """Test listing routes with pagination."""
        # Create multiple routes
        for i in range(5):
            await create_route(integration_api_client, f"Route {i + 1}")

        # List routes
        response = await integration_api_client.get("/api/routes")

        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 5
        assert data["meta"]["total_count"] == 5
        assert data["meta"]["current_page"] == 1

    async def test_list_routes_pagination(self, integration_api_client):
        """Test route pagination."""
        # Create 25 routes
        for i in range(25):
            await create_route(integration_api_client, f"Route {i + 1}")

        # Get first page
        response = await integration_api_client.get("/api/routes?page=1&limit=10")
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 10
        assert data["meta"]["total_count"] == 25
        assert data["meta"]["current_page"] == 1
        assert data["meta"]["page_count"] == 3

        # Get second page
        response = await integration_api_client.get("/api/routes?page=2&limit=10")
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 10
        assert data["meta"]["current_page"] == 2

        # Get third page
        response = await integration_api_client.get("/api/routes?page=3&limit=10")
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 5
        assert data["meta"]["current_page"] == 3

    async def test_update_route(self, integration_api_client):
        """Test updating a route."""
        # Create a route
        route_id = await create_route(
            integration_api_client, "Original Name", description="Original description"
        )

        # Update the route
        update_data = build_route_update_request(
            route_id, "Updated Name", description="Updated description"
        )

        response = await integration_api_client.put(
            f"/api/routes/{route_id}", json=update_data
        )

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["id"] == route_id
        assert data["data"]["attributes"]["name"] == "Updated Name"
        assert data["data"]["attributes"]["description"] == "Updated description"

    async def test_update_route_add_gpx_data(self, integration_api_client):
        """Test adding GPX data to an existing route."""
        # Create a route without GPX
        route_id = await create_route(integration_api_client, "Route Without GPX")

        # Add GPX data
        gpx_data = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Test">
  <trk>
    <name>Test Track</name>
  </trk>
</gpx>"""

        update_data = build_route_update_request(
            route_id, "Route Without GPX", gpx_data=gpx_data
        )

        response = await integration_api_client.put(
            f"/api/routes/{route_id}", json=update_data
        )

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["attributes"]["gpx_data"] == gpx_data

    async def test_delete_route(self, integration_api_client):
        """Test deleting a route."""
        # Create a route
        route_id = await create_route(integration_api_client, "Route to Delete")

        # Delete the route
        response = await integration_api_client.delete(f"/api/routes/{route_id}")

        assert response.status_code == 204

        # Verify route is deleted
        get_response = await integration_api_client.get(f"/api/routes/{route_id}")
        assert get_response.status_code == 404


@pytest.mark.integration
class TestRouteErrorHandling:
    """Integration tests for route error handling."""

    async def test_get_nonexistent_route(self, integration_api_client):
        """Test getting a route that doesn't exist."""
        response = await integration_api_client.get(f"/api/routes/{FAKE_UUID}")
        assert response.status_code == 404

    async def test_get_route_invalid_uuid(self, integration_api_client):
        """Test getting a route with invalid UUID format."""
        response = await integration_api_client.get("/api/routes/invalid-uuid")
        assert response.status_code == 404

    async def test_update_nonexistent_route(self, integration_api_client):
        """Test updating a route that doesn't exist."""
        update_data = build_route_update_request(FAKE_UUID, "Updated Name")

        response = await integration_api_client.put(
            f"/api/routes/{FAKE_UUID}", json=update_data
        )

        assert response.status_code == 404

    async def test_update_route_id_mismatch(self, integration_api_client):
        """Test that update ignores body ID and uses path ID (security check)."""
        # Create a route
        route_id = await create_route(integration_api_client, "Original Route")

        # Try to update with a different ID in the body
        update_data = build_route_update_request(
            FAKE_UUID,  # Different from actual route_id
            "Updated Name",
        )

        # The update should succeed because we ignore the body ID
        # and use the path ID (which is the correct route)
        response = await integration_api_client.put(
            f"/api/routes/{route_id}", json=update_data
        )

        assert response.status_code == 200
        data = response.json()
        # Verify the correct route was updated (using path ID, not body ID)
        assert data["data"]["id"] == route_id
        assert data["data"]["attributes"]["name"] == "Updated Name"

    async def test_delete_nonexistent_route(self, integration_api_client):
        """Test deleting a route that doesn't exist."""
        response = await integration_api_client.delete(f"/api/routes/{FAKE_UUID}")
        assert response.status_code == 404

    async def test_create_route_missing_name(self, integration_api_client):
        """Test creating a route without required name field."""
        # Manually build request without name field
        request_data = {
            "data": {
                "type": "routes",
                "attributes": {
                    "description": "Route without name",
                },
            }
        }

        response = await integration_api_client.post("/api/routes", json=request_data)
        assert response.status_code == 400  # Validation error (Pydantic returns 400)

    async def test_create_route_name_too_long(self, integration_api_client):
        """Test creating a route with name exceeding max length."""
        request_data = build_route_request("x" * 201)  # Max is 200

        response = await integration_api_client.post("/api/routes", json=request_data)
        # Should fail with validation error (422) or bad request (400)
        assert response.status_code in [400, 422]

    async def test_create_route_invalid_gpx_data(self, integration_api_client):
        """Test creating a route with invalid GPX data."""
        request_data = build_route_request(
            "Route with Invalid GPX", gpx_data="This is not valid XML"
        )

        response = await integration_api_client.post("/api/routes", json=request_data)
        # Should fail with validation error
        assert response.status_code in [400, 422]

    async def test_create_route_gpx_without_gpx_root(self, integration_api_client):
        """Test creating a route with XML that's not GPX format."""
        request_data = build_route_request(
            "Route with Non-GPX XML",
            gpx_data='<?xml version="1.0"?><root><data>test</data></root>',
        )

        response = await integration_api_client.post("/api/routes", json=request_data)
        # Should fail with validation error
        assert response.status_code in [400, 422]


@pytest.mark.integration
class TestRouteAuthenticationRequirements:
    """Test that route endpoints require authentication."""

    async def test_list_routes_requires_auth(self, unauthenticated_client):
        """Test that listing routes requires authentication."""
        response = await unauthenticated_client.get("/api/routes")
        assert response.status_code == 401

    async def test_get_route_requires_auth(self, unauthenticated_client):
        """Test that getting a route requires authentication."""
        response = await unauthenticated_client.get(f"/api/routes/{FAKE_UUID}")
        assert response.status_code == 401

    async def test_create_route_requires_auth(self, unauthenticated_client):
        """Test that creating a route requires authentication."""
        request_data = build_route_request("Test Route")
        response = await unauthenticated_client.post("/api/routes", json=request_data)
        assert response.status_code == 401

    async def test_update_route_requires_auth(self, unauthenticated_client):
        """Test that updating a route requires authentication."""
        update_data = build_route_update_request(FAKE_UUID, "Updated Name")
        response = await unauthenticated_client.put(
            f"/api/routes/{FAKE_UUID}", json=update_data
        )
        assert response.status_code == 401

    async def test_delete_route_requires_auth(self, unauthenticated_client):
        """Test that deleting a route requires authentication."""
        response = await unauthenticated_client.delete(f"/api/routes/{FAKE_UUID}")
        assert response.status_code == 401
