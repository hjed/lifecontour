"""Integration tests for Gear Item API endpoints."""

import pytest
import pytest_asyncio


@pytest.mark.integration
class TestGearItemEndpoints:
    """Integration tests for gear item endpoints."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_method(self, clean_database):  # noqa: ARG002
        """Setup method to ensure clean database for each test."""
        pass

    async def test_create_gear_item(self, authenticated_client):
        """Test creating a gear item."""
        data = {
            "data": {
                "type": "gear-items",
                "attributes": {
                    "name": "Climbing Rope 60m",
                    "model": "Beal Stinger III",
                    "serial_number": "SN-12345",
                    "purchase_date": "2025-06-15",
                    "manufacturer": "Beal",
                },
            }
        }

        response = await authenticated_client.post("/api/gear-items", json=data)
        assert response.status_code == 201, response.json()

        response_json = response.json()
        assert response_json["data"]["type"] == "gear-items"
        assert response_json["data"]["attributes"]["name"] == "Climbing Rope 60m"
        assert response_json["data"]["attributes"]["model"] == "Beal Stinger III"
        assert response_json["data"]["attributes"]["serial_number"] == "SN-12345"
        assert response_json["data"]["attributes"]["purchase_date"] == "2025-06-15"
        assert response_json["data"]["attributes"]["manufacturer"] == "Beal"
        assert response_json["data"]["id"] is not None

    async def test_create_gear_item_minimal(self, authenticated_client):
        """Test creating a gear item with only required fields."""
        data = {
            "data": {
                "type": "gear-items",
                "attributes": {
                    "name": "Harness",
                },
            }
        }

        response = await authenticated_client.post("/api/gear-items", json=data)
        assert response.status_code == 201, response.json()

        response_json = response.json()
        assert response_json["data"]["attributes"]["name"] == "Harness"
        assert response_json["data"]["attributes"]["model"] is None
        assert response_json["data"]["attributes"]["serial_number"] is None
        assert response_json["data"]["attributes"]["manufacturer"] is None

    async def test_create_gear_item_missing_name(self, authenticated_client):
        """Test creating a gear item without name returns 422."""
        data = {
            "data": {
                "type": "gear-items",
                "attributes": {
                    "model": "Some Model",
                },
            }
        }

        response = await authenticated_client.post("/api/gear-items", json=data)
        assert response.status_code == 400  # Validation error

    async def test_get_gear_items_list(self, authenticated_client):
        """Test getting a list of gear items."""
        # Create some items
        for name in ["Rope", "Harness", "Helmet"]:
            await authenticated_client.post(
                "/api/gear-items",
                json={
                    "data": {
                        "type": "gear-items",
                        "attributes": {"name": name},
                    }
                },
            )

        response = await authenticated_client.get("/api/gear-items")
        assert response.status_code == 200

        data = response.json()
        assert len(data["data"]) == 3
        # Should be ordered alphabetically
        names = [item["attributes"]["name"] for item in data["data"]]
        assert names == ["Harness", "Helmet", "Rope"]

    async def test_get_gear_items_filter_by_name(self, authenticated_client):
        """Test filtering gear items by name query parameter."""
        await authenticated_client.post(
            "/api/gear-items",
            json={
                "data": {
                    "type": "gear-items",
                    "attributes": {"name": "Climbing Rope"},
                }
            },
        )
        await authenticated_client.post(
            "/api/gear-items",
            json={
                "data": {
                    "type": "gear-items",
                    "attributes": {"name": "Climbing Harness"},
                }
            },
        )
        await authenticated_client.post(
            "/api/gear-items",
            json={
                "data": {
                    "type": "gear-items",
                    "attributes": {"name": "Helmet"},
                }
            },
        )

        response = await authenticated_client.get("/api/gear-items?name=climbing")
        assert response.status_code == 200

        data = response.json()
        assert len(data["data"]) == 2

    async def test_get_specific_gear_item(self, authenticated_client):
        """Test getting a specific gear item by ID."""
        create_response = await authenticated_client.post(
            "/api/gear-items",
            json={
                "data": {
                    "type": "gear-items",
                    "attributes": {
                        "name": "Test Rope",
                        "manufacturer": "Petzl",
                    },
                }
            },
        )
        item_id = create_response.json()["data"]["id"]

        response = await authenticated_client.get(f"/api/gear-items/{item_id}")
        assert response.status_code == 200

        data = response.json()
        assert data["data"]["id"] == item_id
        assert data["data"]["attributes"]["name"] == "Test Rope"
        assert data["data"]["attributes"]["manufacturer"] == "Petzl"

    async def test_get_nonexistent_gear_item(self, authenticated_client):
        """Test getting a non-existent gear item returns 404."""
        response = await authenticated_client.get(
            "/api/gear-items/550e8400-e29b-41d4-a716-446655440000"
        )
        assert response.status_code == 404

    async def test_update_gear_item(self, authenticated_client):
        """Test updating a gear item."""
        create_response = await authenticated_client.post(
            "/api/gear-items",
            json={
                "data": {
                    "type": "gear-items",
                    "attributes": {
                        "name": "Original Name",
                        "model": "Model A",
                    },
                }
            },
        )
        item_id = create_response.json()["data"]["id"]

        update_data = {
            "data": {
                "type": "gear-items",
                "id": item_id,
                "attributes": {
                    "name": "Updated Name",
                    "manufacturer": "DMM",
                },
            }
        }

        response = await authenticated_client.put(
            f"/api/gear-items/{item_id}", json=update_data
        )
        assert response.status_code == 200

        data = response.json()
        assert data["data"]["attributes"]["name"] == "Updated Name"
        assert data["data"]["attributes"]["model"] == "Model A"  # Unchanged
        assert data["data"]["attributes"]["manufacturer"] == "DMM"

    async def test_delete_gear_item(self, authenticated_client):
        """Test deleting a gear item."""
        create_response = await authenticated_client.post(
            "/api/gear-items",
            json={
                "data": {
                    "type": "gear-items",
                    "attributes": {"name": "To Delete"},
                }
            },
        )
        item_id = create_response.json()["data"]["id"]

        response = await authenticated_client.delete(f"/api/gear-items/{item_id}")
        assert response.status_code == 204

        # Verify it's gone
        get_response = await authenticated_client.get(f"/api/gear-items/{item_id}")
        assert get_response.status_code == 404
