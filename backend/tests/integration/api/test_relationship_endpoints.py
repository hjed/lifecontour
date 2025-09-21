"""Integration tests for contact relationship API endpoints."""

import pytest

from app.core.contacts.models.entities import RelationshipType
from tests.integration.conftest import ContactFactory


class TestContactRelationshipEndpoints:
    """Test contact relationship CRUD endpoints."""

    @pytest.mark.asyncio
    async def test_create_relationship_success(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
    ):
        """Test successful relationship creation."""
        # Create two contacts
        contact1 = await contact_factory.create_contact(
            first_name="John", last_name="Doe"
        )
        contact2 = await contact_factory.create_contact(
            first_name="Jane", last_name="Smith"
        )

        # Create relationship
        relationship_data = {
            "data": {
                "type": "contact_relationships",
                "attributes": {
                    "relationship_type": "friend",
                    "from_contact_id": int(contact1["id"]),
                    "to_contact_id": int(contact2["id"]),
                },
            }
        }

        response = await authenticated_client.post(
            f"/api/contacts/{contact1['id']}/relationships", json=relationship_data
        )

        assert response.status_code == 201
        data = response.json()
        assert data["data"]["type"] == "contact_relationships"
        assert data["data"]["attributes"]["relationship_type"] == "friend"
        assert data["data"]["attributes"]["from_contact_id"] == int(contact1["id"])
        assert data["data"]["attributes"]["to_contact_id"] == int(contact2["id"])

    @pytest.mark.asyncio
    async def test_create_relationship_invalid_from_contact_id(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
    ):
        """Test relationship creation with mismatched from_contact_id."""
        contact1 = await contact_factory.create_contact(
            first_name="John", last_name="Doe"
        )
        contact2 = await contact_factory.create_contact(
            first_name="Jane", last_name="Smith"
        )

        # Try to create relationship with wrong from_contact_id
        relationship_data = {
            "data": {
                "type": "contact_relationships",
                "attributes": {
                    "relationship_type": "friend",
                    "from_contact_id": int(contact2["id"]),  # Wrong ID
                    "to_contact_id": int(contact2["id"]),
                },
            }
        }

        response = await authenticated_client.post(
            f"/api/contacts/{contact1['id']}/relationships", json=relationship_data
        )

        assert response.status_code == 422
        data = response.json()
        assert "from_contact_id in request body" in data["errors"][0]["detail"]

    @pytest.mark.asyncio
    async def test_create_relationship_self_relationship(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
    ):
        """Test that self-relationships are prevented."""
        contact = await contact_factory.create_contact(
            first_name="John", last_name="Doe"
        )

        relationship_data = {
            "data": {
                "type": "contact_relationships",
                "attributes": {
                    "relationship_type": "friend",
                    "from_contact_id": int(contact["id"]),
                    "to_contact_id": int(contact["id"]),
                },
            }
        }

        response = await authenticated_client.post(
            f"/api/contacts/{contact['id']}/relationships", json=relationship_data
        )

        assert response.status_code == 422
        data = response.json()
        assert "cannot have a relationship with itself" in data["errors"][0]["detail"]

    @pytest.mark.asyncio
    async def test_get_contact_relationships(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
    ):
        """Test getting all relationships for a contact."""
        # Create contacts and relationship
        contact1 = await contact_factory.create_contact(
            first_name="John", last_name="Doe"
        )
        contact2 = await contact_factory.create_contact(
            first_name="Jane", last_name="Smith"
        )

        relationship = await contact_factory.create_relationship(
            from_contact_id=int(contact1["id"]),
            to_contact_id=int(contact2["id"]),
            relationship_type=RelationshipType.FRIEND,
        )

        response = await authenticated_client.get(
            f"/api/contacts/{contact1['id']}/relationships"
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 1
        assert data["data"][0]["id"] == str(relationship["id"])
        assert data["data"][0]["attributes"]["relationship_type"] == "friend"

    @pytest.mark.asyncio
    async def test_get_specific_relationship(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
    ):
        """Test getting a specific relationship by ID."""
        contact1 = await contact_factory.create_contact(
            first_name="John", last_name="Doe"
        )
        contact2 = await contact_factory.create_contact(
            first_name="Jane", last_name="Smith"
        )

        relationship = await contact_factory.create_relationship(
            from_contact_id=int(contact1["id"]),
            to_contact_id=int(contact2["id"]),
            relationship_type=RelationshipType.COLLEAGUE,
        )

        response = await authenticated_client.get(
            f"/api/contacts/{contact1['id']}/relationships/{relationship['id']}"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["id"] == str(relationship["id"])
        assert data["data"]["attributes"]["relationship_type"] == "colleague"

    @pytest.mark.asyncio
    async def test_get_relationship_wrong_contact(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
    ):
        """Test getting a relationship that doesn't belong to the specified contact."""
        contact1 = await contact_factory.create_contact(
            first_name="John", last_name="Doe"
        )
        contact2 = await contact_factory.create_contact(
            first_name="Jane", last_name="Smith"
        )
        contact3 = await contact_factory.create_contact(
            first_name="Bob", last_name="Wilson"
        )

        relationship = await contact_factory.create_relationship(
            from_contact_id=int(contact1["id"]),
            to_contact_id=int(contact2["id"]),
            relationship_type=RelationshipType.FRIEND,
        )

        # Try to access the relationship through contact3
        response = await authenticated_client.get(
            f"/api/contacts/{contact3['id']}/relationships/{relationship['id']}"
        )

        assert response.status_code == 422
        data = response.json()
        assert "does not belong to contact" in data["errors"][0]["detail"]

    @pytest.mark.asyncio
    async def test_update_relationship(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
    ):
        """Test updating a relationship."""
        contact1 = await contact_factory.create_contact(
            first_name="John", last_name="Doe"
        )
        contact2 = await contact_factory.create_contact(
            first_name="Jane", last_name="Smith"
        )

        relationship = await contact_factory.create_relationship(
            from_contact_id=int(contact1["id"]),
            to_contact_id=int(contact2["id"]),
            relationship_type=RelationshipType.FRIEND,
        )

        update_data = {
            "data": {
                "type": "contact_relationships",
                "id": str(relationship["id"]),
                "attributes": {
                    "relationship_type": "colleague",
                    "from_contact_id": int(contact1["id"]),
                    "to_contact_id": int(contact2["id"]),
                },
            }
        }

        response = await authenticated_client.put(
            f"/api/contacts/{contact1['id']}/relationships/{relationship['id']}",
            json=update_data,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["attributes"]["relationship_type"] == "colleague"

    @pytest.mark.asyncio
    async def test_delete_relationship(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
    ):
        """Test deleting a relationship."""
        contact1 = await contact_factory.create_contact(
            first_name="John", last_name="Doe"
        )
        contact2 = await contact_factory.create_contact(
            first_name="Jane", last_name="Smith"
        )

        relationship = await contact_factory.create_relationship(
            from_contact_id=int(contact1["id"]),
            to_contact_id=int(contact2["id"]),
            relationship_type=RelationshipType.FRIEND,
        )

        response = await authenticated_client.delete(
            f"/api/contacts/{contact1['id']}/relationships/{relationship['id']}"
        )

        assert response.status_code == 204

        # Verify relationship is deleted
        get_response = await authenticated_client.get(
            f"/api/contacts/{contact1['id']}/relationships/{relationship['id']}"
        )
        assert get_response.status_code == 422

    @pytest.mark.asyncio
    async def test_relationship_not_found(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
    ):
        """Test accessing non-existent relationship."""
        contact = await contact_factory.create_contact(
            first_name="John", last_name="Doe"
        )

        response = await authenticated_client.get(
            f"/api/contacts/{contact['id']}/relationships/999"
        )

        assert response.status_code == 422
        data = response.json()
        assert "Relationship with ID 999 not found" in data["errors"][0]["detail"]
