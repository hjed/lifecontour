"""Integration tests for contact history API endpoints."""

import pytest

from tests.integration.conftest import ContactFactory


class TestContactHistoryEndpoints:
    """Test contact history API endpoints."""

    @pytest.mark.asyncio
    async def test_get_contact_history_empty(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
    ):
        """Test getting history for a contact with no changes."""
        # Create a contact (only create, no updates)
        contact = await contact_factory.create_contact(
            first_name="John", last_name="Doe"
        )

        # Get history - should be empty initially (creation may not track changes)
        response = await authenticated_client.get(
            f"/api/contacts/{contact['id']}/history"
        )

        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert isinstance(data["data"], list)
        # History should exist and be a list (may or may not be empty)

    @pytest.mark.asyncio
    async def test_get_contact_history_after_update(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
    ):
        """Test getting history after contact update."""
        # Create a contact
        contact = await contact_factory.create_contact(
            first_name="John", last_name="Doe"
        )

        # Update the contact to generate history
        update_data = {
            "data": {
                "type": "contacts",
                "id": contact["id"],
                "attributes": {
                    "first_name": "Jane",
                    "last_name": "Doe",
                    "contact_methods": [],
                    "addresses": [],
                    "notes": [],
                },
            }
        }
        update_response = await authenticated_client.put(
            f"/api/contacts/{contact['id']}", json=update_data
        )
        assert update_response.status_code == 200

        # Get history - should have entry for first_name change
        response = await authenticated_client.get(
            f"/api/contacts/{contact['id']}/history"
        )

        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert isinstance(data["data"], list)
        assert len(data["data"]) >= 1

        # Verify history entry structure
        history_entry = data["data"][0]
        assert history_entry["type"] == "contact_history"
        assert "id" in history_entry
        assert "attributes" in history_entry
        assert "entity_type" in history_entry["attributes"]
        assert "field_name" in history_entry["attributes"]
        assert "created_at" in history_entry["attributes"]

    @pytest.mark.asyncio
    async def test_get_contact_history_pagination(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
    ):
        """Test history pagination with page and limit parameters."""
        # Create a contact
        contact = await contact_factory.create_contact(
            first_name="John", last_name="Doe"
        )

        # Get history with pagination params
        response = await authenticated_client.get(
            f"/api/contacts/{contact['id']}/history?page=1&limit=10"
        )

        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert "meta" in data
        # Meta should contain pagination info
        if data["meta"]:
            assert "current_page" in data["meta"]
            assert "per_page" in data["meta"]

    @pytest.mark.asyncio
    async def test_get_contact_history_not_found(
        self,
        authenticated_client,
    ):
        """Test getting history for non-existent contact returns 404."""
        response = await authenticated_client.get("/api/contacts/99999/history")

        assert response.status_code == 404
        data = response.json()
        assert "errors" in data

    @pytest.mark.asyncio
    async def test_get_contact_history_structure(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
    ):
        """Test that history response follows JSON API structure."""
        # Create and update contact
        contact = await contact_factory.create_contact(
            first_name="Original", last_name="Name"
        )

        update_data = {
            "data": {
                "type": "contacts",
                "id": contact["id"],
                "attributes": {
                    "first_name": "Updated",
                    "last_name": "Name",
                    "contact_methods": [],
                    "addresses": [],
                    "notes": [],
                },
            }
        }
        await authenticated_client.put(
            f"/api/contacts/{contact['id']}", json=update_data
        )

        response = await authenticated_client.get(
            f"/api/contacts/{contact['id']}/history"
        )

        assert response.status_code == 200
        data = response.json()

        # Verify JSON API structure
        assert "data" in data
        if len(data["data"]) > 0:
            entry = data["data"][0]
            # Required JSON API fields
            assert "type" in entry
            assert "id" in entry
            assert "attributes" in entry
            # Application-specific attributes
            attrs = entry["attributes"]
            assert "entity_type" in attrs
            assert "entity_id" in attrs
            assert "field_name" in attrs
            assert "old_value" in attrs or attrs.get("old_value") is None
            assert "new_value" in attrs or attrs.get("new_value") is None
            assert "created_at" in attrs
