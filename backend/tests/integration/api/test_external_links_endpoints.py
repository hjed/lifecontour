"""Integration tests for external links API endpoints."""

import pytest
import pytest_asyncio
from sqlalchemy import text


@pytest.mark.integration
class TestJournalExternalLinks:
    """Integration tests for GET /api/journals/{id}/external-links."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_method(self, clean_database):  # noqa: ARG002
        """Ensure clean database for each test."""

    async def _create_journal(self, client, title="Test Journal"):
        """Helper to create a journal and return its id."""
        response = await client.post(
            "/api/journals",
            json={
                "data": {
                    "type": "journals",
                    "attributes": {
                        "title": title,
                        "content": "Test content",
                        "event_date_range": {
                            "start": "2024-01-15T00:00:00Z",
                            "end": "2024-01-15T00:00:00Z",
                        },
                    },
                }
            },
        )
        assert response.status_code == 201
        return int(response.json()["data"]["id"])

    async def test_returns_empty_when_no_external_links(self, integration_api_client):
        """External links endpoint returns empty list for a journal with no links."""
        journal_id = await self._create_journal(integration_api_client)

        response = await integration_api_client.get(
            f"/api/journals/{journal_id}/external-links"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["data"] == []

    async def test_returns_strava_link_from_fitness_data(
        self, integration_api_client, async_connection
    ):
        """External links endpoint returns Strava link when fitness_data has strava_activity_id."""
        journal_id = await self._create_journal(integration_api_client)

        # Add FITNESS type to journal
        await integration_api_client.post(
            f"/api/journals/{journal_id}/types",
            json={
                "data": {
                    "type": "journal-types",
                    "attributes": {"journal_type": "fitness"},
                }
            },
        )

        # Insert strava_activity_id into fitness_data
        await async_connection.execute(
            text(
                "UPDATE journal_fitness_data SET strava_activity_id = :strava_id "
                "WHERE journal_id = :journal_id"
            ),
            {"strava_id": "12345678", "journal_id": journal_id},
        )

        response = await integration_api_client.get(
            f"/api/journals/{journal_id}/external-links"
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 1
        link = data["data"][0]
        assert link["source"] == "strava"
        assert link["external_id"] == "12345678"
        assert link["url"] == "https://www.strava.com/activities/12345678"

    async def test_returns_google_calendar_link_from_external_event_link(
        self, integration_api_client, async_connection
    ):
        """External links endpoint returns Google Calendar link from JournalExternalEventLink."""
        journal_id = await self._create_journal(integration_api_client)

        # Create a calendar first
        calendar_response = await integration_api_client.post(
            "/api/calendars",
            json={
                "data": {
                    "type": "calendars",
                    "attributes": {"name": "Test Calendar"},
                }
            },
        )
        calendar_id = calendar_response.json()["data"]["id"]

        # Insert external event link directly
        await async_connection.execute(
            text(
                "INSERT INTO journal_external_event_links "
                "(journal_id, calendar_id, external_event_id, "
                "external_version, sync_capability, sync_status) "
                "VALUES (:journal_id, :calendar_id, :external_event_id, "
                "'etag-1', 'bidirectional', 'synced')"
            ),
            {
                "journal_id": journal_id,
                "calendar_id": calendar_id,
                "external_event_id": "google-event-abc",
            },
        )

        response = await integration_api_client.get(
            f"/api/journals/{journal_id}/external-links"
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 1
        link = data["data"][0]
        assert link["source"] == "google_calendar"
        assert link["external_id"] == "google-event-abc"
        assert "calendar.google.com" in link["url"]

    async def test_returns_both_strava_and_calendar_links(
        self, integration_api_client, async_connection
    ):
        """External links endpoint can return multiple links from different sources."""
        journal_id = await self._create_journal(integration_api_client)

        # Add FITNESS type
        await integration_api_client.post(
            f"/api/journals/{journal_id}/types",
            json={
                "data": {
                    "type": "journal-types",
                    "attributes": {"journal_type": "fitness"},
                }
            },
        )
        await async_connection.execute(
            text(
                "UPDATE journal_fitness_data SET strava_activity_id = :strava_id "
                "WHERE journal_id = :journal_id"
            ),
            {"strava_id": "99999", "journal_id": journal_id},
        )

        # Create calendar and external event link
        calendar_response = await integration_api_client.post(
            "/api/calendars",
            json={
                "data": {
                    "type": "calendars",
                    "attributes": {"name": "Mixed Calendar"},
                }
            },
        )
        calendar_id = calendar_response.json()["data"]["id"]

        await async_connection.execute(
            text(
                "INSERT INTO journal_external_event_links "
                "(journal_id, calendar_id, external_event_id, "
                "external_version, sync_capability, sync_status) "
                "VALUES (:journal_id, :calendar_id, :external_event_id, "
                "'etag-1', 'bidirectional', 'synced')"
            ),
            {
                "journal_id": journal_id,
                "calendar_id": calendar_id,
                "external_event_id": "google-mixed-evt",
            },
        )

        response = await integration_api_client.get(
            f"/api/journals/{journal_id}/external-links"
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 2
        sources = {link["source"] for link in data["data"]}
        assert sources == {"strava", "google_calendar"}

    async def test_returns_404_for_nonexistent_journal(self, integration_api_client):
        """External links endpoint returns 404 for a journal that doesn't exist."""
        response = await integration_api_client.get(
            "/api/journals/999999/external-links"
        )

        assert response.status_code == 404


@pytest.mark.integration
class TestContactExternalLinks:
    """Integration tests for GET /api/contacts/{id}/external-links."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_method(self, clean_database):  # noqa: ARG002
        """Ensure clean database for each test."""

    async def _create_contact(self, client, first_name="Test", last_name="Contact"):
        """Helper to create a contact and return its id."""
        response = await client.post(
            "/api/contacts",
            json={
                "data": {
                    "type": "contacts",
                    "attributes": {
                        "first_name": first_name,
                        "last_name": last_name,
                    },
                }
            },
        )
        assert response.status_code == 201
        return int(response.json()["data"]["id"])

    async def test_returns_empty_when_no_external_references(
        self, integration_api_client
    ):
        """External links endpoint returns empty list for a contact with no references."""
        contact_id = await self._create_contact(integration_api_client)

        response = await integration_api_client.get(
            f"/api/contacts/{contact_id}/external-links"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["data"] == []

    async def test_returns_google_contacts_link_from_external_reference(
        self, integration_api_client, async_connection
    ):
        """External links endpoint returns Google Contacts link from external_references."""
        contact_id = await self._create_contact(integration_api_client)

        # Insert external reference directly
        await async_connection.execute(
            text(
                "INSERT INTO external_references "
                "(internal_entity_type, internal_entity_id, "
                "external_system, external_entity_id, external_entity_type) "
                "VALUES ('contact', :contact_id, 'google', "
                ":external_id, 'person')"
            ),
            {
                "contact_id": contact_id,
                "external_id": "people/c123456",
            },
        )

        response = await integration_api_client.get(
            f"/api/contacts/{contact_id}/external-links"
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 1
        link = data["data"][0]
        assert link["source"] == "google_contacts"
        assert link["external_id"] == "people/c123456"
        assert "contacts.google.com" in link["url"]

    async def test_returns_404_for_nonexistent_contact(self, integration_api_client):
        """External links endpoint returns 404 for a contact that doesn't exist."""
        response = await integration_api_client.get(
            "/api/contacts/999999/external-links"
        )

        assert response.status_code == 404
