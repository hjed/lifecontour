"""Integration tests for Activity Template API endpoints."""

import pytest
import pytest_asyncio


@pytest.mark.integration
class TestActivityTemplateEndpoints:
    """Integration tests for activity template endpoints."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_method(self, clean_database):  # noqa: ARG002
        """Setup method to ensure clean database for each test."""
        pass

    async def test_create_template(self, authenticated_client):
        """Test creating an activity template."""
        data = {
            "data": {
                "type": "activity-templates",
                "attributes": {
                    "name": "Test Canyon",
                    "template_type": "canyoning",
                    "region": "Blue Mountains",
                    "description": "Test description",
                    "french_grade": "v3a2IV",
                    "canyon_type": "vertical",
                    "water_gauge_name": "Megalong Creek",
                    "pitches": [
                        {
                            "pitch_number": 1,
                            "height": 15,
                            "anchor_location": "TR",
                            "anchor_type": "double bolt",
                        }
                    ],
                },
            }
        }

        response = await authenticated_client.post("/api/templates", json=data)
        assert response.status_code == 201, response.json()

        response_json = response.json()
        assert response_json["data"]["type"] == "activity-templates"
        assert response_json["data"]["attributes"]["name"] == "Test Canyon"
        assert response_json["data"]["attributes"]["template_type"] == "canyoning"
        assert response_json["data"]["attributes"]["region"] == "Blue Mountains"
        assert response_json["data"]["attributes"]["french_grade"] == "v3a2IV"
        assert len(response_json["data"]["attributes"]["pitches"]) == 1
        assert response_json["data"]["attributes"]["pitches"][0]["height"] == 15

    async def test_get_templates(self, authenticated_client):
        """Test getting a list of activity templates."""
        # Create some templates
        for i in range(2):
            await authenticated_client.post(
                "/api/templates",
                json={
                    "data": {
                        "type": "activity-templates",
                        "attributes": {
                            "name": f"Canyon {i}",
                            "template_type": "canyoning",
                            "pitches": [
                                {
                                    "pitch_number": 1,
                                    "height": 10 + i,
                                }
                            ],
                        },
                    }
                },
            )

        await authenticated_client.post(
            "/api/templates",
            json={
                "data": {
                    "type": "activity-templates",
                    "attributes": {"name": "Cave 1", "template_type": "caving"},
                }
            },
        )

        # Get all templates
        response = await authenticated_client.get("/api/templates")
        assert response.status_code == 200

        data = response.json()
        assert len(data["data"]) == 3

        # Verify pitches are hydrated
        canyon_templates = [
            t for t in data["data"] if t["attributes"]["template_type"] == "canyoning"
        ]
        assert len(canyon_templates) == 2
        for t in canyon_templates:
            assert len(t["attributes"]["pitches"]) == 1
            assert t["attributes"]["pitches"][0]["pitch_number"] == 1

        # Filter by type
        response = await authenticated_client.get("/api/templates?template_type=caving")
        assert response.status_code == 200

        data = response.json()
        assert len(data["data"]) == 1
        assert data["data"][0]["attributes"]["name"] == "Cave 1"

    async def test_get_template(self, authenticated_client):
        """Test getting a specific template."""
        # Create a template
        create_response = await authenticated_client.post(
            "/api/templates",
            json={
                "data": {
                    "type": "activity-templates",
                    "attributes": {
                        "name": "To Get",
                        "template_type": "climbing",
                        "grade": 18,
                    },
                }
            },
        )
        template_id = create_response.json()["data"]["id"]

        # Get the template
        response = await authenticated_client.get(f"/api/templates/{template_id}")
        assert response.status_code == 200

        data = response.json()
        assert data["data"]["id"] == template_id
        assert data["data"]["attributes"]["name"] == "To Get"
        assert data["data"]["attributes"]["grade"] == 18

    async def test_update_template(self, authenticated_client):
        """Test updating a template."""
        # Create a template
        create_response = await authenticated_client.post(
            "/api/templates",
            json={
                "data": {
                    "type": "activity-templates",
                    "attributes": {
                        "name": "Original Name",
                        "template_type": "canyoning",
                        "french_grade": "v1",
                    },
                }
            },
        )
        template_id = create_response.json()["data"]["id"]

        # Update the template
        update_data = {
            "data": {
                "type": "activity-templates",
                "id": template_id,
                "attributes": {"name": "Updated Name", "french_grade": "v3"},
            }
        }

        response = await authenticated_client.put(
            f"/api/templates/{template_id}", json=update_data
        )
        assert response.status_code == 200

        data = response.json()
        assert data["data"]["attributes"]["name"] == "Updated Name"
        assert data["data"]["attributes"]["french_grade"] == "v3"
        assert data["data"]["attributes"]["template_type"] == "canyoning"  # Unchanged

    async def test_template_pitch_notes_round_trip(self, authenticated_client):
        """Pitch notes must survive template create, read, and update."""
        create_response = await authenticated_client.post(
            "/api/templates",
            json={
                "data": {
                    "type": "activity-templates",
                    "attributes": {
                        "name": "Notes Canyon",
                        "template_type": "canyoning",
                        "pitches": [
                            {
                                "pitch_number": 1,
                                "height": 15,
                                "notes": "Awkward start over the chockstone",
                            },
                            {"pitch_number": 2, "height": 25},
                        ],
                    },
                }
            },
        )
        assert create_response.status_code == 201, create_response.json()
        template_id = create_response.json()["data"]["id"]
        created_pitches = create_response.json()["data"]["attributes"]["pitches"]
        assert created_pitches[0]["notes"] == "Awkward start over the chockstone"
        assert created_pitches[1].get("notes") is None

        get_response = await authenticated_client.get(f"/api/templates/{template_id}")
        assert get_response.status_code == 200
        pitches = get_response.json()["data"]["attributes"]["pitches"]
        assert pitches[0]["notes"] == "Awkward start over the chockstone"

        update_response = await authenticated_client.put(
            f"/api/templates/{template_id}",
            json={
                "data": {
                    "type": "activity-templates",
                    "id": template_id,
                    "attributes": {
                        "pitches": [
                            {
                                "pitch_number": 1,
                                "height": 15,
                                "notes": "Rebolted in 2026",
                            }
                        ]
                    },
                }
            },
        )
        assert update_response.status_code == 200, update_response.json()
        updated_pitches = update_response.json()["data"]["attributes"]["pitches"]
        assert len(updated_pitches) == 1
        assert updated_pitches[0]["notes"] == "Rebolted in 2026"

    async def test_delete_template(self, authenticated_client):
        """Test deleting a template."""
        # Create a template
        create_response = await authenticated_client.post(
            "/api/templates",
            json={
                "data": {
                    "type": "activity-templates",
                    "attributes": {"name": "To Delete", "template_type": "canyoning"},
                }
            },
        )
        template_id = create_response.json()["data"]["id"]

        # Delete the template
        response = await authenticated_client.delete(f"/api/templates/{template_id}")
        assert response.status_code == 204

        # Verify it's gone
        get_response = await authenticated_client.get(f"/api/templates/{template_id}")
        assert get_response.status_code == 404
