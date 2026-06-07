"""Integration tests for journal-contact relationship update (PATCH) endpoint.

Tests the manual override API for updating attendance status on
journal-contact relationships.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


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
    from app.infrastructure.di.settings import SettingsProvider

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
        SettingsProvider(),
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


def _create_journal_request(
    title: str = "Test Event",
) -> dict[str, Any]:
    """Create a journal request payload."""
    now = datetime.now(UTC)
    return {
        "data": {
            "type": "journals",
            "attributes": {
                "title": title,
                "content": "Test content",
                "event_date_range": {
                    "start": now.isoformat(),
                    "end": now.isoformat(),
                },
            },
        }
    }


def _create_contact_request(first_name: str = "Override") -> dict[str, Any]:
    """Create a contact request payload."""
    return {
        "data": {
            "type": "contacts",
            "attributes": {
                "first_name": first_name,
                "last_name": "Test",
                "contact_methods": [],
                "addresses": [],
                "notes": [],
            },
        }
    }


async def _setup_journal_with_attending_contact(
    client: AsyncClient,
) -> tuple[str, str]:
    """Create a journal and contact with ATTENDING status. Returns (journal_id, contact_id)."""
    # Create journal
    journal_response = await client.post(
        "/api/journals", json=_create_journal_request()
    )
    assert journal_response.status_code == 201
    journal_id = journal_response.json()["data"]["id"]

    # Create contact
    contact_response = await client.post(
        "/api/contacts", json=_create_contact_request()
    )
    assert contact_response.status_code == 201
    contact_id = contact_response.json()["data"]["id"]

    # Add contact relationship with ATTENDING status
    rel_data = {
        "data": {
            "type": "journal-contact-relationships",
            "attributes": {
                "contact_id": str(contact_id),
                "relationship_type": "PARTICIPANT",
                "status": "ATTENDING",
            },
        }
    }
    rel_response = await client.post(
        f"/api/journals/{journal_id}/relationships/contacts", json=rel_data
    )
    assert rel_response.status_code == 200

    return journal_id, contact_id


@pytest.mark.integration
class TestJournalContactRelationshipUpdateEndpoint:
    """Integration tests for PATCH journal contact relationship status."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_method(self, clean_database):  # noqa: ARG002
        """Ensure clean database for each test."""
        pass

    async def test_manual_override_attending_to_declined(
        self, integration_api_client: AsyncClient
    ):
        """PATCH status from ATTENDING to DECLINED succeeds."""
        journal_id, contact_id = await _setup_journal_with_attending_contact(
            integration_api_client
        )

        update_data = {
            "data": {
                "type": "journal-contact-relationships",
                "attributes": {"status": "DECLINED"},
            }
        }

        response = await integration_api_client.patch(
            f"/api/journals/{journal_id}/relationships/contacts"
            f"/{contact_id}/PARTICIPANT",
            json=update_data,
        )

        assert response.status_code == 200
        contacts = response.json()["data"]["attributes"]["contacts"]
        match = [c for c in contacts if c["id"] == str(contact_id)]
        assert len(match) == 1
        assert match[0]["status"] == "DECLINED"

    async def test_manual_override_attended_back_to_attending(
        self, integration_api_client: AsyncClient
    ):
        """PATCH status from ATTENDED back to ATTENDING is allowed."""
        journal_id, contact_id = await _setup_journal_with_attending_contact(
            integration_api_client
        )

        # First transition to ATTENDED
        await integration_api_client.patch(
            f"/api/journals/{journal_id}/relationships/contacts"
            f"/{contact_id}/PARTICIPANT",
            json={
                "data": {
                    "type": "journal-contact-relationships",
                    "attributes": {"status": "ATTENDED"},
                }
            },
        )

        # Now override back to ATTENDING
        response = await integration_api_client.patch(
            f"/api/journals/{journal_id}/relationships/contacts"
            f"/{contact_id}/PARTICIPANT",
            json={
                "data": {
                    "type": "journal-contact-relationships",
                    "attributes": {"status": "ATTENDING"},
                }
            },
        )

        assert response.status_code == 200
        contacts = response.json()["data"]["attributes"]["contacts"]
        match = [c for c in contacts if c["id"] == str(contact_id)]
        assert len(match) == 1
        assert match[0]["status"] == "ATTENDING"

    async def test_invalid_status_rejected(self, integration_api_client: AsyncClient):
        """PATCH with invalid status returns 400."""
        journal_id, contact_id = await _setup_journal_with_attending_contact(
            integration_api_client
        )

        update_data = {
            "data": {
                "type": "journal-contact-relationships",
                "attributes": {"status": "INVALID_STATUS"},
            }
        }

        response = await integration_api_client.patch(
            f"/api/journals/{journal_id}/relationships/contacts"
            f"/{contact_id}/PARTICIPANT",
            json=update_data,
        )

        assert response.status_code == 400
