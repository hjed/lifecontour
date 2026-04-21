"""Integration tests for contact relationship API endpoints."""

import pytest
from core_shared.models.contacts.entities import RelationshipType

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
    async def test_get_inverse_relationship_perspective(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
    ):
        """Test getting a relationship from the perspective of the target contact (inverse type)."""
        # Create contacts
        contact1 = await contact_factory.create_contact(
            first_name="Parent", last_name="Contact"
        )
        contact2 = await contact_factory.create_contact(
            first_name="Child", last_name="Contact"
        )

        # Create relationship: Parent -> Child (type=PARENT)
        await contact_factory.create_relationship(
            from_contact_id=int(contact1["id"]),
            to_contact_id=int(contact2["id"]),
            relationship_type=RelationshipType.PARENT,
        )

        # Get relationships from the 'from' contact (Parent)
        response1 = await authenticated_client.get(
            f"/api/contacts/{contact1['id']}/relationships"
        )
        assert response1.status_code == 200
        data1 = response1.json()
        assert len(data1["data"]) == 1
        assert data1["data"][0]["attributes"]["relationship_type"] == "parent"
        assert data1["data"][0]["attributes"]["from_contact_id"] == int(contact1["id"])
        assert data1["data"][0]["attributes"]["to_contact_id"] == int(contact2["id"])

        # Get relationships from the 'to' contact (Child)
        response2 = await authenticated_client.get(
            f"/api/contacts/{contact2['id']}/relationships"
        )
        assert response2.status_code == 200
        data2 = response2.json()
        assert len(data2["data"]) == 1
        # The relationship should be inverted from the child's perspective
        assert data2["data"][0]["attributes"]["relationship_type"] == "child"
        assert data2["data"][0]["attributes"]["from_contact_id"] == int(contact2["id"])
        assert data2["data"][0]["attributes"]["to_contact_id"] == int(contact1["id"])

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
    async def test_update_relationship_inverse_perspective(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
    ):
        """Test updating a relationship from the perspective of the target contact."""
        contact1 = await contact_factory.create_contact(
            first_name="Parent", last_name="Contact"
        )
        contact2 = await contact_factory.create_contact(
            first_name="Child", last_name="Contact"
        )

        relationship = await contact_factory.create_relationship(
            from_contact_id=int(contact1["id"]),
            to_contact_id=int(contact2["id"]),
            relationship_type=RelationshipType.PARENT,
        )

        # Child updates the relationship. They see "child", but change it back to "parent"
        # (meaning Child is now PARENT of Parent)
        update_data = {
            "data": {
                "type": "contact_relationships",
                "id": str(relationship["id"]),
                "attributes": {
                    "relationship_type": "parent",
                    "from_contact_id": int(contact2["id"]),
                    "to_contact_id": int(contact1["id"]),
                },
            }
        }

        response = await authenticated_client.put(
            f"/api/contacts/{contact2['id']}/relationships/{relationship['id']}",
            json=update_data,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["attributes"]["relationship_type"] == "parent"

        # Verify the underlying original relationship was correctly inverted
        get_response = await authenticated_client.get(
            f"/api/contacts/{contact1['id']}/relationships/{relationship['id']}"
        )
        assert get_response.status_code == 200
        # If Child is PARENT of Parent, then Parent is CHILD of Child.
        # So from Parent's perspective, they should see "child"
        assert get_response.json()["data"]["attributes"]["relationship_type"] == "child"

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


class TestUserTargetedRelationshipEndpoints:
    """Test user-targeted relationship API endpoints."""

    @pytest.mark.asyncio
    async def test_create_user_targeted_relationship_success(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
    ):
        """Test creating a user-targeted relationship (to_user=True, to_contact_id=None)."""
        contact = await contact_factory.create_contact(
            first_name="Alice", last_name="User-Rel"
        )

        request_data = {
            "data": {
                "type": "contact_relationships",
                "attributes": {
                    "relationship_type": "friend",
                    "from_contact_id": int(contact["id"]),
                    "to_user": True,
                },
            }
        }

        response = await authenticated_client.post(
            f"/api/contacts/{contact['id']}/relationships", json=request_data
        )

        assert response.status_code == 201
        data = response.json()
        attrs = data["data"]["attributes"]
        assert attrs["relationship_type"] == "friend"
        assert attrs["from_contact_id"] == int(contact["id"])
        assert attrs["to_contact_id"] is None
        assert attrs["to_user"] is True
        assert attrs["to_contact_name"] == "You"

    @pytest.mark.asyncio
    async def test_create_user_targeted_with_to_contact_id_fails(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
    ):
        """Test that to_user=True + to_contact_id set is rejected."""
        contact1 = await contact_factory.create_contact(
            first_name="Conflicting", last_name="Target"
        )
        contact2 = await contact_factory.create_contact(
            first_name="Other", last_name="Contact"
        )

        request_data = {
            "data": {
                "type": "contact_relationships",
                "attributes": {
                    "relationship_type": "friend",
                    "from_contact_id": int(contact1["id"]),
                    "to_contact_id": int(contact2["id"]),
                    "to_user": True,
                },
            }
        }

        response = await authenticated_client.post(
            f"/api/contacts/{contact1['id']}/relationships", json=request_data
        )

        assert response.status_code == 422
        data = response.json()
        assert "to_contact_id must not be provided" in data["errors"][0]["detail"]

    @pytest.mark.asyncio
    async def test_list_relationships_includes_user_targeted(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
    ):
        """Test that listing relationships returns both contact-targeted and user-targeted."""
        contact1 = await contact_factory.create_contact(
            first_name="ListTest", last_name="Contact"
        )
        contact2 = await contact_factory.create_contact(
            first_name="ListTest", last_name="Other"
        )

        # Create a contact-to-contact relationship
        await contact_factory.create_relationship(
            int(contact1["id"]),
            int(contact2["id"]),
            RelationshipType.COLLEAGUE,
        )

        # Create a user-targeted relationship
        await contact_factory.create_relationship(
            int(contact1["id"]),
            None,
            RelationshipType.FRIEND,
            to_user=True,
        )

        # List all relationships
        response = await authenticated_client.get(
            f"/api/contacts/{contact1['id']}/relationships"
        )

        assert response.status_code == 200
        data = response.json()
        relationships = data["data"]
        assert len(relationships) == 2

        # Find the user-targeted one
        user_rels = [r for r in relationships if r["attributes"]["to_user"] is True]
        contact_rels = [r for r in relationships if r["attributes"]["to_user"] is False]
        assert len(user_rels) == 1
        assert len(contact_rels) == 1
        assert user_rels[0]["attributes"]["to_contact_name"] == "You"

    @pytest.mark.asyncio
    async def test_user_targeted_relationship_shows_user_name(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
    ):
        """Test that user-targeted relationship has to_contact_name='You'."""
        contact = await contact_factory.create_contact(
            first_name="NameTest", last_name="Contact"
        )

        rel_data = await contact_factory.create_relationship(
            int(contact["id"]),
            None,
            RelationshipType.PARTNER,
            to_user=True,
        )

        # Get the specific relationship
        response = await authenticated_client.get(
            f"/api/contacts/{contact['id']}/relationships/{rel_data['id']}"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["attributes"]["to_contact_name"] == "You"
        assert data["data"]["attributes"]["to_user"] is True

    @pytest.mark.asyncio
    async def test_delete_user_targeted_relationship(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
    ):
        """Test deleting a user-targeted relationship."""
        contact = await contact_factory.create_contact(
            first_name="DeleteTest", last_name="UserRel"
        )

        rel_data = await contact_factory.create_relationship(
            int(contact["id"]),
            None,
            RelationshipType.FAMILY,
            to_user=True,
        )

        # Delete it
        delete_response = await authenticated_client.delete(
            f"/api/contacts/{contact['id']}/relationships/{rel_data['id']}"
        )
        assert delete_response.status_code == 204

        # Verify it's gone
        get_response = await authenticated_client.get(
            f"/api/contacts/{contact['id']}/relationships/{rel_data['id']}"
        )
        assert get_response.status_code == 422

    @pytest.mark.asyncio
    async def test_update_user_targeted_relationship_type(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
    ):
        """Test updating the type of a user-targeted relationship."""
        contact = await contact_factory.create_contact(
            first_name="UpdateTest", last_name="UserRel"
        )

        rel_data = await contact_factory.create_relationship(
            int(contact["id"]),
            None,
            RelationshipType.FRIEND,
            to_user=True,
        )

        # Update the relationship type
        update_data = {
            "data": {
                "type": "contact_relationships",
                "id": rel_data["id"],
                "attributes": {
                    "relationship_type": "colleague",
                    "from_contact_id": int(contact["id"]),
                    "to_user": True,
                },
            }
        }

        response = await authenticated_client.put(
            f"/api/contacts/{contact['id']}/relationships/{rel_data['id']}",
            json=update_data,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["attributes"]["relationship_type"] == "colleague"
        assert data["data"]["attributes"]["to_user"] is True

    @pytest.mark.asyncio
    async def test_duplicate_user_targeted_relationship_rejected(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
    ):
        """Test that duplicate user-targeted relationships (same from_contact + type) are rejected."""
        contact = await contact_factory.create_contact(
            first_name="DupeTest", last_name="UserRel"
        )

        # Create first user-targeted relationship
        await contact_factory.create_relationship(
            int(contact["id"]),
            None,
            RelationshipType.FRIEND,
            to_user=True,
        )

        # Try creating duplicate
        request_data = {
            "data": {
                "type": "contact_relationships",
                "attributes": {
                    "relationship_type": "friend",
                    "from_contact_id": int(contact["id"]),
                    "to_user": True,
                },
            }
        }

        response = await authenticated_client.post(
            f"/api/contacts/{contact['id']}/relationships", json=request_data
        )

        assert response.status_code == 422
        data = response.json()
        assert "already exists" in data["errors"][0]["detail"]

    @pytest.mark.asyncio
    async def test_existing_contact_to_contact_still_works(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
    ):
        """Regression test: existing contact-to-contact relationships still work."""
        contact1 = await contact_factory.create_contact(
            first_name="Regression", last_name="ContactA"
        )
        contact2 = await contact_factory.create_contact(
            first_name="Regression", last_name="ContactB"
        )

        rel_data = await contact_factory.create_relationship(
            int(contact1["id"]),
            int(contact2["id"]),
            RelationshipType.SIBLING,
        )

        # Verify it was created correctly
        assert rel_data["attributes"]["relationship_type"] == "sibling"
        assert rel_data["attributes"]["to_contact_id"] == int(contact2["id"])
        assert rel_data["attributes"]["to_user"] is False

        # Verify list works
        list_response = await authenticated_client.get(
            f"/api/contacts/{contact1['id']}/relationships"
        )
        assert list_response.status_code == 200
        assert len(list_response.json()["data"]) == 1

    @pytest.mark.asyncio
    async def test_contact_targeted_without_to_contact_id_fails(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
    ):
        """Test that to_user=False without to_contact_id is rejected."""
        contact = await contact_factory.create_contact(
            first_name="MissingTarget", last_name="Test"
        )

        request_data = {
            "data": {
                "type": "contact_relationships",
                "attributes": {
                    "relationship_type": "friend",
                    "from_contact_id": int(contact["id"]),
                    "to_user": False,
                },
            }
        }

        response = await authenticated_client.post(
            f"/api/contacts/{contact['id']}/relationships", json=request_data
        )

        assert response.status_code == 422
        data = response.json()
        assert "to_contact_id is required" in data["errors"][0]["detail"]
