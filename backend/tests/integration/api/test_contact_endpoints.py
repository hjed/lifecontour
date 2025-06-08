"""Integration tests for contact API endpoints."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture
async def integration_api_client(
    async_connection, clean_database, test_user, test_settings
):  # noqa: ARG001
    """Create async test client for API integration tests with real database setup."""
    # Use the existing integration test fixtures for database setup
    # This ensures we use the same database configuration as other integration tests

    from app.api.auth.dependencies import require_authentication
    from app.api.dependencies import get_async_db_connection

    # Override the database dependency to use our test connection
    async def override_get_async_db_connection():
        yield async_connection

    # Override authentication to return a test user
    def override_require_authentication():
        return test_user

    app = create_app(settings=test_settings)
    app.dependency_overrides[get_async_db_connection] = override_get_async_db_connection
    app.dependency_overrides[require_authentication] = override_require_authentication

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client


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
