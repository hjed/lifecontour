"""Integration tests for contact summary API endpoints."""

from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.main import create_app


@pytest_asyncio.fixture
async def integration_api_client(async_connection, clean_database, test_settings):  # noqa: ARG001
    """Create async test client for API integration tests with real database setup."""
    from dishka import Provider, Scope, make_async_container, provide
    from dishka.integrations.fastapi import FastapiProvider, setup_dishka

    from app.infrastructure.auth.models import SessionUser
    from app.infrastructure.di.contacts import ContactProvider
    from app.infrastructure.di.infrastructure import InfrastructureProvider
    from app.infrastructure.di.integrations import IntegrationProvider
    from app.infrastructure.di.journal import JournalProvider
    from app.infrastructure.di.settings import SettingsProvider
    from app.infrastructure.di.tasks import TaskProvider

    class TestDatabaseProvider(Provider):
        def __init__(self, connection: AsyncConnection):
            super().__init__()
            self.connection = connection

        @provide(scope=Scope.REQUEST)
        async def get_connection(self) -> AsyncConnection:
            return self.connection

        @provide(scope=Scope.REQUEST)
        def get_session_user(self) -> SessionUser:
            return SessionUser(
                id="test-user-123",
                email="test@example.com",
                name="Test User",
                avatar_url="https://example.com/avatar.jpg",
                provider="test",
            )

    app = create_app(settings=test_settings)

    await app.state.dishka_container.close()

    test_container = make_async_container(
        TestDatabaseProvider(async_connection),
        InfrastructureProvider(),
        ContactProvider(),
        JournalProvider(),
        TaskProvider(),
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

    await test_container.close()


async def _create_contact(client: AsyncClient) -> str:
    """Helper to create a contact and return its ID."""
    request_data = {
        "data": {
            "type": "contacts",
            "attributes": {
                "first_name": "Summary",
                "last_name": "Test",
                "contact_methods": [],
                "addresses": [],
                "notes": [],
            },
        }
    }
    response = await client.post("/api/contacts", json=request_data)
    assert response.status_code == 201
    contact_id: str = response.json()["data"]["id"]
    return contact_id


async def _get_contact_summary(
    client: AsyncClient, contact_id: str
) -> dict[str, Any] | None:
    """Helper to fetch a contact and return its summary attributes."""
    response = await client.get(f"/api/contacts/{contact_id}")
    assert response.status_code == 200
    result: dict[str, Any] | None = response.json()["data"]["attributes"]["summary"]
    return result


async def _count_refresh_due_events(
    connection: AsyncConnection, contact_id: str
) -> int:
    """Count ContactSummaryRefreshDue outbox events queued for a contact."""
    result = await connection.execute(
        text(
            "SELECT COUNT(*) FROM outbox_events "
            "WHERE event_type = 'ContactSummaryRefreshDue' "
            "AND aggregate_id = :contact_id"
        ),
        {"contact_id": int(contact_id)},
    )
    count: int = result.scalar_one()
    return count


@pytest.mark.integration
class TestContactSummaryRefreshEndpoint:
    """Integration tests for POST /api/contacts/{id}/summary/refresh."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_method(self, clean_database):  # noqa: ARG002
        """Ensure clean database for each test."""

    async def test_refresh_returns_202_accepted(self, integration_api_client):
        """Test refresh returns 202 Accepted with status body."""
        contact_id = await _create_contact(integration_api_client)

        response = await integration_api_client.post(
            f"/api/contacts/{contact_id}/summary/refresh"
        )

        assert response.status_code == 202
        assert response.json() == {"status": "accepted"}

    async def test_refresh_creates_pending_summary(self, integration_api_client):
        """Test refresh creates a summary record with PENDING status."""
        contact_id = await _create_contact(integration_api_client)

        await integration_api_client.post(f"/api/contacts/{contact_id}/summary/refresh")

        # Verify via GET
        summary = await _get_contact_summary(integration_api_client, contact_id)
        assert summary is not None
        assert summary["attributes"]["status"] == "pending"

    async def test_refresh_nonexistent_contact_returns_404(
        self, integration_api_client
    ):
        """Test refresh for non-existent contact returns 404."""
        response = await integration_api_client.post(
            "/api/contacts/999999/summary/refresh"
        )
        assert response.status_code == 404

    async def test_refresh_resets_generated_to_pending(self, integration_api_client):
        """Test refresh resets a previously generated summary to PENDING."""
        contact_id = await _create_contact(integration_api_client)

        # Create a summary with override text (to simulate generated state)
        patch_data = {
            "data": {
                "user_override_text": "Manual summary",
            }
        }
        patch_resp = await integration_api_client.patch(
            f"/api/contacts/{contact_id}/summary", json=patch_data
        )
        assert patch_resp.status_code == 200

        # Now refresh — should reset to PENDING
        response = await integration_api_client.post(
            f"/api/contacts/{contact_id}/summary/refresh"
        )
        assert response.status_code == 202

        # Verify via GET
        summary = await _get_contact_summary(integration_api_client, contact_id)
        assert summary is not None
        assert summary["attributes"]["status"] == "pending"

    async def test_refresh_disabled_summary_returns_error(self, integration_api_client):
        """Test refresh for a summary the user disabled returns validation error."""
        contact_id = await _create_contact(integration_api_client)

        # Disable the summary
        disable_data = {"data": {"is_disabled": True}}
        await integration_api_client.patch(
            f"/api/contacts/{contact_id}/summary", json=disable_data
        )

        # Refresh should be rejected
        response = await integration_api_client.post(
            f"/api/contacts/{contact_id}/summary/refresh"
        )
        assert response.status_code == 422

    async def test_refresh_publishes_outbox_event(
        self, integration_api_client, async_connection
    ):
        """Test that refresh publishes a ContactSummaryRefreshDue outbox event.

        Manual refresh bypasses the rolling-debounce buffer, so it publishes
        the generate-now Due event rather than the buffered Requested one.
        """
        from sqlalchemy import text

        contact_id = await _create_contact(integration_api_client)

        await integration_api_client.post(f"/api/contacts/{contact_id}/summary/refresh")

        # Verify outbox event was created
        result = await async_connection.execute(
            text(
                "SELECT event_type, event_data "
                "FROM outbox_events "
                "WHERE event_type = 'ContactSummaryRefreshDue' "
                "AND aggregate_id = :contact_id"
            ),
            {"contact_id": int(contact_id)},
        )
        rows = result.fetchall()
        assert len(rows) >= 1
        assert rows[0].event_type == "ContactSummaryRefreshDue"

    async def test_refresh_auto_paused_summary_is_accepted(
        self, integration_api_client, async_connection
    ):
        """A low-activity pause is refreshable: 202, still disabled, event queued."""
        from sqlalchemy import text

        contact_id = await _create_contact(integration_api_client)
        await async_connection.execute(
            text(
                """
                INSERT INTO contact_summaries
                    (contact_id, status, is_disabled, disabled_reason)
                VALUES (:contact_id, 'disabled', TRUE, 'low_activity')
                """
            ),
            {"contact_id": int(contact_id)},
        )

        response = await integration_api_client.post(
            f"/api/contacts/{contact_id}/summary/refresh"
        )

        assert response.status_code == 202
        summary = await _get_contact_summary(integration_api_client, contact_id)
        assert summary is not None
        assert summary["attributes"]["status"] == "disabled"
        assert summary["attributes"]["disabled_reason"] == "low_activity"
        assert await _count_refresh_due_events(async_connection, contact_id) == 1


@pytest.mark.integration
class TestContactSummaryPatchEndpoint:
    """Integration tests for PATCH /api/contacts/{id}/summary."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_method(self, clean_database):  # noqa: ARG002
        """Ensure clean database for each test."""

    async def test_patch_disable_summary(self, integration_api_client):
        """Test disabling a summary via PATCH."""
        contact_id = await _create_contact(integration_api_client)

        patch_data = {"data": {"is_disabled": True}}
        response = await integration_api_client.patch(
            f"/api/contacts/{contact_id}/summary", json=patch_data
        )

        assert response.status_code == 200
        summary = response.json()["data"]["attributes"]["summary"]
        assert summary["attributes"]["is_disabled"] is True
        assert summary["attributes"]["disabled_reason"] == "user"
        assert summary["attributes"]["status"] == "disabled"

    async def test_patch_reenable_summary(self, integration_api_client):
        """Test re-enabling a disabled summary resets status to PENDING."""
        contact_id = await _create_contact(integration_api_client)

        # Disable first
        await integration_api_client.patch(
            f"/api/contacts/{contact_id}/summary",
            json={"data": {"is_disabled": True}},
        )

        # Re-enable
        response = await integration_api_client.patch(
            f"/api/contacts/{contact_id}/summary",
            json={"data": {"is_disabled": False}},
        )

        assert response.status_code == 200
        summary = response.json()["data"]["attributes"]["summary"]
        assert summary["attributes"]["is_disabled"] is False
        assert summary["attributes"]["disabled_reason"] is None
        assert summary["attributes"]["status"] == "pending"

    async def test_patch_reenable_queues_generation(
        self, integration_api_client, async_connection
    ):
        """Re-enabling publishes one ContactSummaryRefreshDue; disabling publishes none."""
        contact_id = await _create_contact(integration_api_client)

        await integration_api_client.patch(
            f"/api/contacts/{contact_id}/summary",
            json={"data": {"is_disabled": True}},
        )
        assert await _count_refresh_due_events(async_connection, contact_id) == 0

        await integration_api_client.patch(
            f"/api/contacts/{contact_id}/summary",
            json={"data": {"is_disabled": False}},
        )
        assert await _count_refresh_due_events(async_connection, contact_id) == 1

    async def test_patch_set_user_override(self, integration_api_client):
        """Test setting user override text via PATCH."""
        contact_id = await _create_contact(integration_api_client)

        patch_data = {
            "data": {
                "user_override_text": "My custom summary for this contact.",
            }
        }
        response = await integration_api_client.patch(
            f"/api/contacts/{contact_id}/summary", json=patch_data
        )

        assert response.status_code == 200
        summary = response.json()["data"]["attributes"]["summary"]
        assert summary["attributes"]["is_user_override"] is True
        assert (
            summary["attributes"]["user_override_text"]
            == "My custom summary for this contact."
        )
        assert summary["attributes"]["status"] == "generated"

    async def test_patch_clear_user_override(self, integration_api_client):
        """Test clearing user override text resets status appropriately."""
        contact_id = await _create_contact(integration_api_client)

        # Set override first
        await integration_api_client.patch(
            f"/api/contacts/{contact_id}/summary",
            json={"data": {"user_override_text": "Override text"}},
        )

        # Clear override (explicit null)
        response = await integration_api_client.patch(
            f"/api/contacts/{contact_id}/summary",
            json={"data": {"user_override_text": None}},
        )

        assert response.status_code == 200
        summary = response.json()["data"]["attributes"]["summary"]
        assert summary["attributes"]["is_user_override"] is False
        assert summary["attributes"]["user_override_text"] is None
        # No AI text exists, so should be PENDING for regeneration
        assert summary["attributes"]["status"] == "pending"

    async def test_patch_nonexistent_contact_returns_404(self, integration_api_client):
        """Test PATCH for non-existent contact returns 404."""
        response = await integration_api_client.patch(
            "/api/contacts/999999/summary",
            json={"data": {"is_disabled": True}},
        )
        assert response.status_code == 404

    async def test_contact_get_includes_summary(self, integration_api_client):
        """Test that GET /contacts/{id} includes summary after it's been created."""
        contact_id = await _create_contact(integration_api_client)

        # Initially no summary
        summary = await _get_contact_summary(integration_api_client, contact_id)
        assert summary is None

        # Create summary via refresh
        await integration_api_client.post(f"/api/contacts/{contact_id}/summary/refresh")

        # Now GET should include summary
        summary = await _get_contact_summary(integration_api_client, contact_id)
        assert summary is not None
        assert summary["type"] == "contact_summaries"
        assert summary["attributes"]["status"] == "pending"

    async def test_patch_creates_summary_when_absent(self, integration_api_client):
        """Test PATCH creates summary record when none exists."""
        contact_id = await _create_contact(integration_api_client)

        # PATCH on contact with no summary should create one
        patch_data = {
            "data": {
                "user_override_text": "Created via patch",
            }
        }
        response = await integration_api_client.patch(
            f"/api/contacts/{contact_id}/summary", json=patch_data
        )

        assert response.status_code == 200
        summary = response.json()["data"]["attributes"]["summary"]
        assert summary is not None
        assert summary["attributes"]["user_override_text"] == "Created via patch"
        assert summary["attributes"]["is_user_override"] is True
