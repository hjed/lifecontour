"""Integration tests for contact API endpoints."""

import asyncio

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
    from dishka.integrations.fastapi import FastapiProvider, setup_dishka
    from sqlalchemy.ext.asyncio import AsyncConnection

    from app.infrastructure.auth.models import SessionUser
    from app.infrastructure.di.contacts import ContactProvider
    from app.infrastructure.di.infrastructure import InfrastructureProvider
    from app.infrastructure.di.integrations import IntegrationProvider
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
        favourite_contact_one = {
            "data": {
                "type": "contact",
                "attributes": {
                    "first_name": "Alpha",
                    "last_name": "Favourite",
                    "is_favourite": True,
                },
            }
        }

        favourite_contact_two = {
            "data": {
                "type": "contact",
                "attributes": {
                    "first_name": "Beta",
                    "last_name": "Favourite",
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

        create_responses = await asyncio.gather(
            client.post("/api/contacts", json=favourite_contact_one),
            client.post("/api/contacts", json=favourite_contact_two),
            client.post("/api/contacts", json=regular_contact),
        )
        assert all(response.status_code == 201 for response in create_responses)

        # Test filtering by favourite=true with correct filtered metadata and links
        response = await client.get("/api/contacts?favourite=true&limit=1")
        assert response.status_code == 200

        data = response.json()
        assert len(data["data"]) == 1
        assert data["data"][0]["attributes"]["first_name"] == "Alpha"
        assert data["data"][0]["attributes"]["is_favourite"] is True
        assert data["meta"] == {
            "total_count": 2,
            "page_count": 2,
            "current_page": 1,
            "per_page": 1,
        }
        assert data["links"] == {
            "self": "http://testserver/api/contacts?page=1&limit=1&favourite=true",
            "first": "http://testserver/api/contacts?page=1&limit=1&favourite=true",
            "last": "http://testserver/api/contacts?page=2&limit=1&favourite=true",
            "prev": None,
            "next": "http://testserver/api/contacts?page=2&limit=1&favourite=true",
            "related": None,
        }

        # Test filtering by favourite=false
        response = await client.get("/api/contacts?favourite=false")
        assert response.status_code == 200

        data = response.json()
        assert len(data["data"]) == 1
        assert data["data"][0]["attributes"]["first_name"] == "Regular"
        assert data["data"][0]["attributes"]["is_favourite"] is False

    async def test_get_contact_journals(self, integration_api_client):
        """Test getting journals associated with a contact."""
        from datetime import UTC, datetime, timedelta

        # Create a contact
        contact_data = {
            "data": {
                "type": "contacts",
                "attributes": {
                    "first_name": "John",
                    "last_name": "Doe",
                    "contact_methods": [],
                    "addresses": [],
                    "notes": [],
                },
            }
        }
        contact_response = await integration_api_client.post(
            "/api/contacts", json=contact_data
        )
        assert contact_response.status_code == 201
        contact_id = int(contact_response.json()["data"]["id"])

        # Create journals directly in the database
        # We need to get the connection from the test setup
        # For now, we'll create journals via the API if available, or skip this test
        # Let's create journals using raw SQL through the test connection

        # Get the async_connection from the fixture
        # Since we can't easily access it here, let's create journals via API
        now = datetime.now(UTC)
        journal1_data = {
            "data": {
                "type": "journals",
                "attributes": {
                    "title": "Meeting with John",
                    "content": "Discussed project plans",
                    "event_date_range": {
                        "start": now.isoformat(),
                        "end": (now + timedelta(hours=1)).isoformat(),
                    },
                },
            }
        }
        journal1_response = await integration_api_client.post(
            "/api/journals", json=journal1_data
        )
        assert journal1_response.status_code == 201
        journal1_id = int(journal1_response.json()["data"]["id"])

        journal2_data = {
            "data": {
                "type": "journals",
                "attributes": {
                    "title": "Lunch with John",
                    "content": "Had a great conversation",
                    "event_date_range": {
                        "start": (now + timedelta(days=1)).isoformat(),
                        "end": (now + timedelta(days=1, hours=1)).isoformat(),
                    },
                },
            }
        }
        journal2_response = await integration_api_client.post(
            "/api/journals", json=journal2_data
        )
        assert journal2_response.status_code == 201
        journal2_id = int(journal2_response.json()["data"]["id"])

        # Add contact to journals
        # Add as PARTICIPANT to journal1
        add_contact1_data = {
            "data": {
                "type": "journal-contact-relationships",
                "attributes": {
                    "contact_id": str(contact_id),
                    "relationship_type": "PARTICIPANT",
                },
            }
        }
        response1 = await integration_api_client.post(
            f"/api/journals/{journal1_id}/relationships/contacts",
            json=add_contact1_data,
        )
        assert response1.status_code == 200

        # Add as MENTION to journal2
        add_contact2_data = {
            "data": {
                "type": "journal-contact-relationships",
                "attributes": {
                    "contact_id": str(contact_id),
                    "relationship_type": "MENTION",
                },
            }
        }
        response2 = await integration_api_client.post(
            f"/api/journals/{journal2_id}/relationships/contacts",
            json=add_contact2_data,
        )
        assert response2.status_code == 200

        # Test getting all journals for the contact
        response = await integration_api_client.get(
            f"/api/contacts/{contact_id}/journals"
        )
        assert response.status_code == 200

        data = response.json()
        assert "data" in data
        assert "meta" in data
        assert "links" in data

        # Should have 2 journals
        assert len(data["data"]) == 2
        assert data["meta"]["total_count"] == 2

        # Verify journal structure
        for journal in data["data"]:
            assert journal["type"] == "journals"
            assert "id" in journal
            assert "attributes" in journal
            assert "title" in journal["attributes"]
            assert "content" in journal["attributes"]

        # Test filtering by relationship type
        response = await integration_api_client.get(
            f"/api/contacts/{contact_id}/journals?relationship_type=PARTICIPANT"
        )
        assert response.status_code == 200

        data = response.json()
        assert len(data["data"]) == 1
        assert data["meta"]["total_count"] == 1

        # Test pagination
        response = await integration_api_client.get(
            f"/api/contacts/{contact_id}/journals?page=1&limit=1"
        )
        assert response.status_code == 200

        data = response.json()
        assert len(data["data"]) == 1
        assert data["meta"]["total_count"] == 2
        assert data["meta"]["page_count"] == 2

    async def test_get_contact_journals_includes_hierarchy_fields(
        self, integration_api_client
    ):
        """Test contact journals include parent summary and children_count.

        Also verifies that children of a related journal are returned even if the
        child journal itself has no direct relationship to the contact.
        """
        from datetime import UTC, datetime, timedelta

        # Create a contact
        contact_data = {
            "data": {
                "type": "contacts",
                "attributes": {
                    "first_name": "Hierarchy",
                    "last_name": "Test",
                    "contact_methods": [],
                    "addresses": [],
                    "notes": [],
                },
            }
        }
        contact_response = await integration_api_client.post(
            "/api/contacts", json=contact_data
        )
        assert contact_response.status_code == 201
        contact_id = int(contact_response.json()["data"]["id"])

        now = datetime.now(UTC)

        # Create a parent journal
        parent_journal_data = {
            "data": {
                "type": "journals",
                "attributes": {
                    "title": "Parent Journal",
                    "content": "Parent content",
                    "event_date_range": {
                        "start": now.isoformat(),
                        "end": (now + timedelta(hours=1)).isoformat(),
                    },
                },
            }
        }
        parent_resp = await integration_api_client.post(
            "/api/journals", json=parent_journal_data
        )
        assert parent_resp.status_code == 201
        parent_id = int(parent_resp.json()["data"]["id"])

        # Create a child journal linked via parent_id
        child_journal_data = {
            "data": {
                "type": "journals",
                "attributes": {
                    "title": "Child Journal",
                    "content": "Child content",
                    "event_date_range": {
                        "start": (now + timedelta(days=1)).isoformat(),
                        "end": (now + timedelta(days=1, hours=1)).isoformat(),
                    },
                    "parent_id": parent_id,
                },
            }
        }
        child_resp = await integration_api_client.post(
            "/api/journals", json=child_journal_data
        )
        assert child_resp.status_code == 201
        child_id = int(child_resp.json()["data"]["id"])

        # Add contact as PARTICIPANT to the parent journal ONLY
        add_contact_data = {
            "data": {
                "type": "journal-contact-relationships",
                "attributes": {
                    "contact_id": str(contact_id),
                    "relationship_type": "PARTICIPANT",
                },
            }
        }
        resp1 = await integration_api_client.post(
            f"/api/journals/{parent_id}/relationships/contacts",
            json=add_contact_data,
        )
        assert resp1.status_code == 200

        response = await integration_api_client.get(
            f"/api/contacts/{contact_id}/journals?relationship_type=PARTICIPANT"
        )
        assert response.status_code == 200
        payload = response.json()

        # Only 1 journal is directly related, but we expect the child to be included
        # as a descendant of the related parent.
        assert payload["meta"]["total_count"] == 1
        assert len(payload["data"]) == 2

        # Index returned journals by id for easy assertions
        by_id = {int(j["id"]): j for j in payload["data"]}
        assert parent_id in by_id
        assert child_id in by_id

        parent = by_id[parent_id]
        child = by_id[child_id]

        # Parent should have children_count=1 and no parent summary
        assert parent["attributes"].get("parent_id") is None
        assert parent["attributes"].get("parent") is None
        assert parent["attributes"].get("children_count") == 1

        # Child should include parent_id and embedded parent summary
        assert child["attributes"].get("parent_id") == parent_id
        assert child["attributes"].get("parent") == {
            "id": str(parent_id),
            "title": "Parent Journal",
        }
        assert child["attributes"].get("children_count") == 0

    async def test_get_contact_journals_not_found(self, integration_api_client):
        """Test getting journals for a non-existent contact."""
        response = await integration_api_client.get("/api/contacts/99999/journals")
        assert response.status_code == 404

    async def test_get_contact_journals_invalid_relationship_type(
        self, integration_api_client
    ):
        """Test getting journals with an invalid relationship type."""
        # Create a contact
        contact_data = {
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
        contact_response = await integration_api_client.post(
            "/api/contacts", json=contact_data
        )
        assert contact_response.status_code == 201
        contact_id = int(contact_response.json()["data"]["id"])

        # Try to get journals with invalid relationship type
        response = await integration_api_client.get(
            f"/api/contacts/{contact_id}/journals?relationship_type=INVALID"
        )
        assert response.status_code == 422  # Validation error
