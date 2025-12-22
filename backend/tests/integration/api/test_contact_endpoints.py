"""Integration tests for contact API endpoints."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture
async def integration_api_client(async_connection, clean_database, test_settings):  # noqa: ARG001
    """Create async test client for API integration tests with real database setup."""
    # Use the existing integration test fixtures for database setup
    # This ensures we use the same database configuration as other integration tests

    from dishka import Provider, Scope, make_async_container, provide
    from dishka.integrations.fastapi import setup_dishka
    from sqlalchemy.ext.asyncio import AsyncConnection

    from app.infrastructure.auth.models import SessionUser
    from app.infrastructure.di.contacts import ContactProvider
    from app.infrastructure.di.journal import JournalProvider

    # Create a test provider that uses our test connection
    class TestDatabaseProvider(Provider):
        def __init__(self, connection: AsyncConnection):
            super().__init__()
            self.connection = connection

        @provide(scope=Scope.REQUEST)
        async def get_connection(self) -> AsyncConnection:
            return self.connection

        @provide(scope=Scope.REQUEST)
        def get_session_user(self) -> SessionUser:
            # Provide a test user for authenticated endpoints
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
        ContactProvider(),
        JournalProvider(),
    )
    app.state.dishka_container = test_container
    setup_dishka(test_container, app)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client

    # Clean up the test container
    await test_container.close()


@pytest.mark.integration
class TestContactEndpoints:
    """Integration tests for contact API endpoints."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_method(self, clean_database):  # noqa: ARG002
        """Setup method to ensure clean database for each test."""
        pass

    async def test_create_contact_minimal(self, integration_api_client):
        """Test creating a contact with minimal data."""
        request_data = {
            "data": {
                "type": "contacts",
                "attributes": {
                    "first_name": "John",
                    "contact_methods": [],
                    "addresses": [],
                    "notes": [],
                },
            }
        }

        response = await integration_api_client.post("/api/contacts", json=request_data)

        assert response.status_code == 201
        data = response.json()
        assert data["data"]["type"] == "contacts"
        assert data["data"]["attributes"]["first_name"] == "John"
        assert "id" in data["data"]

    async def test_create_contact_full(self, integration_api_client):
        """Test creating a contact with full data including methods, addresses, and notes."""
        request_data = {
            "data": {
                "type": "contacts",
                "attributes": {
                    "first_name": "Jane",
                    "last_name": "Smith",
                    "middle_name": "Marie",
                    "nick_name": "Janie",
                    "contact_methods": [
                        {
                            "type": "contact_methods",
                            "attributes": {
                                "method_type": "email",
                                "value": "jane.smith@example.com",
                                "label": "Work",
                                "is_primary": True,
                            },
                        },
                        {
                            "type": "contact_methods",
                            "attributes": {
                                "method_type": "phone",
                                "value": "+61-2-9876-5432",
                                "label": "Mobile",
                                "is_primary": False,
                            },
                        },
                    ],
                    "addresses": [
                        {
                            "type": "contact_addresses",
                            "attributes": {
                                "street_line_1": "123 Collins Street",
                                "street_line_2": "Suite 456",
                                "locality": "Melbourne",
                                "region": "VIC",
                                "postal_code": "3000",
                                "country_code": "AU",
                                "label": "Work",
                                "is_primary": True,
                            },
                        }
                    ],
                    "notes": [
                        {
                            "type": "contact_notes",
                            "attributes": {
                                "content": "Met at tech conference 2024. Interested in collaboration.",
                            },
                        }
                    ],
                },
            }
        }

        response = await integration_api_client.post("/api/contacts", json=request_data)

        assert response.status_code == 201
        data = response.json()

        # Verify contact data
        assert data["data"]["type"] == "contacts"
        assert data["data"]["attributes"]["first_name"] == "Jane"
        assert data["data"]["attributes"]["last_name"] == "Smith"
        assert data["data"]["attributes"]["middle_name"] == "Marie"
        assert data["data"]["attributes"]["nick_name"] == "Janie"
        assert "id" in data["data"]

        # Verify contact methods
        contact_methods = data["data"]["attributes"]["contact_methods"]
        assert len(contact_methods) == 2

        email_method = next(
            m for m in contact_methods if m["attributes"]["method_type"] == "email"
        )
        assert email_method["attributes"]["value"] == "jane.smith@example.com"
        assert email_method["attributes"]["label"] == "Work"
        assert email_method["attributes"]["is_primary"] is True

        phone_method = next(
            m for m in contact_methods if m["attributes"]["method_type"] == "phone"
        )
        assert phone_method["attributes"]["value"] == "+61-2-9876-5432"
        assert phone_method["attributes"]["label"] == "Mobile"
        assert phone_method["attributes"]["is_primary"] is False

        # Verify addresses
        addresses = data["data"]["attributes"]["addresses"]
        assert len(addresses) == 1
        address = addresses[0]
        assert address["attributes"]["street_line_1"] == "123 Collins Street"
        assert address["attributes"]["street_line_2"] == "Suite 456"
        assert address["attributes"]["locality"] == "Melbourne"
        assert address["attributes"]["region"] == "VIC"
        assert address["attributes"]["postal_code"] == "3000"
        assert address["attributes"]["country_code"] == "AU"
        assert address["attributes"]["label"] == "Work"
        assert address["attributes"]["is_primary"] is True

        # Verify notes
        notes = data["data"]["attributes"]["notes"]
        assert len(notes) == 1
        note = notes[0]
        assert (
            note["attributes"]["content"]
            == "Met at tech conference 2024. Interested in collaboration."
        )

    async def test_update_contact_with_methods_and_notes(self, integration_api_client):
        """Test updating a contact with new methods, addresses, and notes."""
        # First, create a contact with initial data
        create_request = {
            "data": {
                "type": "contacts",
                "attributes": {
                    "first_name": "Bob",
                    "last_name": "Wilson",
                    "contact_methods": [
                        {
                            "type": "contact_methods",
                            "attributes": {
                                "method_type": "email",
                                "value": "bob.wilson@oldcompany.com",
                                "label": "Work",
                                "is_primary": True,
                            },
                        }
                    ],
                    "addresses": [],
                    "notes": [
                        {
                            "type": "contact_notes",
                            "attributes": {
                                "content": "Original note",
                            },
                        }
                    ],
                },
            }
        }

        create_response = await integration_api_client.post(
            "/api/contacts", json=create_request
        )
        assert create_response.status_code == 201
        created_contact = create_response.json()
        contact_id = created_contact["data"]["id"]

        # Now update the contact with new methods, addresses, and notes
        update_request = {
            "data": {
                "type": "contacts",
                "id": contact_id,
                "attributes": {
                    "first_name": "Robert",  # Changed name
                    "last_name": "Wilson",
                    "contact_methods": [
                        {
                            "type": "contact_methods",
                            "attributes": {
                                "method_type": "email",
                                "value": "robert.wilson@newcompany.com",  # New email
                                "label": "Work",
                                "is_primary": True,
                            },
                        },
                        {
                            "type": "contact_methods",
                            "attributes": {
                                "method_type": "phone",
                                "value": "+61-3-1234-5678",  # New phone
                                "label": "Mobile",
                                "is_primary": False,
                            },
                        },
                    ],
                    "addresses": [
                        {
                            "type": "contact_addresses",
                            "attributes": {
                                "street_line_1": "456 New Street",  # New address
                                "locality": "Sydney",
                                "region": "NSW",
                                "postal_code": "2000",
                                "country_code": "AU",
                                "label": "Office",
                                "is_primary": True,
                            },
                        }
                    ],
                    "notes": [
                        {
                            "type": "contact_notes",
                            "attributes": {
                                "content": "Updated note - moved to new company",  # New note
                            },
                        },
                        {
                            "type": "contact_notes",
                            "attributes": {
                                "content": "Additional note about project collaboration",  # Additional note
                            },
                        },
                    ],
                },
            }
        }

        update_response = await integration_api_client.put(
            f"/api/contacts/{contact_id}", json=update_request
        )
        assert update_response.status_code == 200
        updated_data = update_response.json()

        # Verify the contact was updated correctly
        assert updated_data["data"]["id"] == contact_id
        assert updated_data["data"]["attributes"]["first_name"] == "Robert"
        assert updated_data["data"]["attributes"]["last_name"] == "Wilson"

        # Verify contact methods were updated (should have 2 methods now)
        contact_methods = updated_data["data"]["attributes"]["contact_methods"]
        assert len(contact_methods) == 2

        email_method = next(
            m for m in contact_methods if m["attributes"]["method_type"] == "email"
        )
        assert email_method["attributes"]["value"] == "robert.wilson@newcompany.com"
        assert email_method["attributes"]["is_primary"] is True

        phone_method = next(
            m for m in contact_methods if m["attributes"]["method_type"] == "phone"
        )
        assert phone_method["attributes"]["value"] == "+61-3-1234-5678"
        assert phone_method["attributes"]["is_primary"] is False

        # Verify addresses were updated (should have 1 address now)
        addresses = updated_data["data"]["attributes"]["addresses"]
        assert len(addresses) == 1
        address = addresses[0]
        assert address["attributes"]["street_line_1"] == "456 New Street"
        assert address["attributes"]["locality"] == "Sydney"
        assert address["attributes"]["region"] == "NSW"

        # Verify notes were updated (should have 2 notes now)
        notes = updated_data["data"]["attributes"]["notes"]
        assert len(notes) == 2
        note_contents = [note["attributes"]["content"] for note in notes]
        assert "Updated note - moved to new company" in note_contents
        assert "Additional note about project collaboration" in note_contents

        # Verify the changes persist by fetching the contact again
        get_response = await integration_api_client.get(f"/api/contacts/{contact_id}")
        assert get_response.status_code == 200
        fetched_data = get_response.json()

        # Verify the fetched data matches the updated data
        assert fetched_data["data"]["attributes"]["first_name"] == "Robert"
        assert len(fetched_data["data"]["attributes"]["contact_methods"]) == 2
        assert len(fetched_data["data"]["attributes"]["addresses"]) == 1
        assert len(fetched_data["data"]["attributes"]["notes"]) == 2

    async def test_update_contact_replace_methods_strategy(
        self, integration_api_client
    ):
        """Test that updating contact methods uses replacement strategy (not additive)."""
        # Create a contact with 2 methods
        create_request = {
            "data": {
                "type": "contacts",
                "attributes": {
                    "first_name": "Alice",
                    "last_name": "Johnson",
                    "contact_methods": [
                        {
                            "type": "contact_methods",
                            "attributes": {
                                "method_type": "email",
                                "value": "alice@oldcompany.com",
                                "is_primary": True,
                            },
                        },
                        {
                            "type": "contact_methods",
                            "attributes": {
                                "method_type": "phone",
                                "value": "+61-2-1111-1111",
                                "is_primary": False,
                            },
                        },
                    ],
                    "addresses": [],
                    "notes": [],
                },
            }
        }

        create_response = await integration_api_client.post(
            "/api/contacts", json=create_request
        )
        assert create_response.status_code == 201
        contact_id = create_response.json()["data"]["id"]

        # Update with only 1 method (should replace, not add)
        update_request = {
            "data": {
                "type": "contacts",
                "id": contact_id,
                "attributes": {
                    "first_name": "Alice",
                    "last_name": "Johnson",
                    "contact_methods": [
                        {
                            "type": "contact_methods",
                            "attributes": {
                                "method_type": "email",
                                "value": "alice@newcompany.com",  # Different email
                                "is_primary": True,
                            },
                        }
                        # Note: No phone method in update - should be removed
                    ],
                    "addresses": [],
                    "notes": [],
                },
            }
        }

        update_response = await integration_api_client.put(
            f"/api/contacts/{contact_id}", json=update_request
        )
        assert update_response.status_code == 200
        updated_data = update_response.json()

        # Verify only 1 method remains (replacement strategy)
        contact_methods = updated_data["data"]["attributes"]["contact_methods"]
        assert len(contact_methods) == 1
        assert contact_methods[0]["attributes"]["method_type"] == "email"
        assert contact_methods[0]["attributes"]["value"] == "alice@newcompany.com"

    # Phase 3 Tests: Favourite functionality and filtering
    async def test_toggle_contact_favourite_success(self, integration_api_client):
        """Test successful contact favourite toggle."""
        client = integration_api_client

        # Create a contact first
        contact_data = {
            "data": {
                "type": "contact",
                "attributes": {
                    "first_name": "John",
                    "last_name": "Doe",
                    "is_favourite": False,
                },
            }
        }

        create_response = await client.post("/api/contacts", json=contact_data)
        assert create_response.status_code == 201
        contact_id = create_response.json()["data"]["id"]

        # Toggle favourite to True
        toggle_response = await client.post(f"/api/contacts/{contact_id}/favourite")
        assert toggle_response.status_code == 200

        toggle_data = toggle_response.json()
        assert toggle_data["data"]["attributes"]["is_favourite"] is True

        # Toggle favourite back to False
        toggle_response2 = await client.post(f"/api/contacts/{contact_id}/favourite")
        assert toggle_response2.status_code == 200

        toggle_data2 = toggle_response2.json()
        assert toggle_data2["data"]["attributes"]["is_favourite"] is False

    async def test_toggle_contact_favourite_not_found(self, integration_api_client):
        """Test toggle favourite for non-existent contact."""
        client = integration_api_client

        response = await client.post("/api/contacts/999/favourite")
        assert response.status_code == 404

    async def test_list_contacts_with_favourite_filter(self, integration_api_client):
        """Test listing contacts with favourite filter."""
        client = integration_api_client

        # Create favourite and non-favourite contacts
        favourite_contact = {
            "data": {
                "type": "contact",
                "attributes": {
                    "first_name": "Favourite",
                    "last_name": "User",
                    "is_favourite": True,
                },
            }
        }

        regular_contact = {
            "data": {
                "type": "contact",
                "attributes": {
                    "first_name": "Regular",
                    "last_name": "User",
                    "is_favourite": False,
                },
            }
        }

        await client.post("/api/contacts", json=favourite_contact)
        await client.post("/api/contacts", json=regular_contact)

        # Test filtering by favourite=true
        response = await client.get("/api/contacts?favourite=true")
        assert response.status_code == 200

        data = response.json()
        assert len(data["data"]) == 1
        assert data["data"][0]["attributes"]["first_name"] == "Favourite"
        assert data["data"][0]["attributes"]["is_favourite"] is True

        # Test filtering by favourite=false
        response = await client.get("/api/contacts?favourite=false")
        assert response.status_code == 200

        data = response.json()
        # Should have at least the regular contact we created
        regular_contacts = [
            c for c in data["data"] if c["attributes"]["first_name"] == "Regular"
        ]
        assert len(regular_contacts) == 1
        assert regular_contacts[0]["attributes"]["is_favourite"] is False
