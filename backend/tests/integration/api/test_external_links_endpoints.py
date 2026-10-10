"""Integration tests for external links API endpoints."""

import json
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_TEST_USER_ID = "test-user-123"
_IMMICH_SERVER_URL = "https://immich.example.com"


async def _connect_immich(async_connection, server_url=_IMMICH_SERVER_URL):
    """Seed a user_immich_auth row so the user has a configured server URL."""
    await async_connection.execute(
        text(
            "INSERT INTO user_immich_auth "
            "(user_id, server_url, encrypted_api_key) "
            "VALUES (:user_id, :server_url, :api_key)"
        ),
        {
            "user_id": _TEST_USER_ID,
            "server_url": server_url,
            "api_key": b"encrypted-placeholder",
        },
    )


async def _link_immich_album(
    async_connection, journal_id, album_id, *, shared_link_url=None
):
    """Seed an Immich album link in sync_metadata only (the canonical store).

    Album display data lives in ``sync_metadata.reference_data`` (mirrored there
    by dual-write); the read path no longer joins ``external_references``.
    """
    reference_data = {"album_id": album_id, "album_name": "Holiday"}
    if shared_link_url is not None:
        reference_data["shared_link_url"] = shared_link_url
    await async_connection.execute(
        text(
            "INSERT INTO sync_metadata "
            "(user_id, internal_id, integration_source, external_id, last_synced_at, "
            "version_hash, sync_status, internal_entity_type, external_entity_type, "
            "reference_data) "
            "VALUES ((SELECT user_id FROM journals WHERE id = :journal_id), "
            ":journal_id, 'immich_album', :album_id, now(), "
            "'hash-1', 'success', 'journal', 'album', :reference_data)"
        ),
        {
            "journal_id": journal_id,
            "album_id": album_id,
            "reference_data": json.dumps(reference_data),
        },
    )


async def _link_strava_activity(async_connection, journal_id, activity_id):
    """Seed a Strava activity link for a journal in the canonical link store."""
    await async_connection.execute(
        text(
            "INSERT INTO sync_metadata "
            "(user_id, internal_id, integration_source, external_id, last_synced_at, "
            "version_hash, sync_status, internal_entity_type, external_entity_type) "
            "VALUES ((SELECT user_id FROM journals WHERE id = :journal_id), "
            ":journal_id, 'strava', :activity_id, now(), "
            "'hash-1', 'success', 'journal', 'activity')"
        ),
        {"journal_id": journal_id, "activity_id": activity_id},
    )


@pytest.mark.integration
@pytest.mark.usefixtures("clean_database")
class TestJournalExternalLinks:
    """Integration tests for GET /api/journals/{id}/external-links."""

    async def _google_synced_calendar(
        self, client: Any, connection: AsyncConnection, name: str
    ) -> str:
        """A calendar synced with Google: only its events open in Google Calendar."""
        response = await client.post(
            "/api/calendars",
            json={"data": {"type": "calendars", "attributes": {"name": name}}},
        )
        calendar_id: str = response.json()["data"]["id"]
        await connection.execute(
            text(
                "UPDATE calendars SET google_calendar_id = :google_id "
                "WHERE id = :calendar_id"
            ),
            {
                "google_id": f"{name}@group.calendar.google.com",
                "calendar_id": calendar_id,
            },
        )
        return calendar_id

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
        assert link["type"] == "external_links"
        assert "id" in link
        assert link["attributes"]["source"] == "strava"
        assert link["attributes"]["external_id"] == "12345678"
        assert link["attributes"]["url"] == "https://www.strava.com/activities/12345678"

    async def test_returns_every_strava_activity_linked_to_the_journal(
        self, integration_api_client, async_connection
    ):
        """An additively merged journal shows a link per Strava activity.

        Only one activity id fits in ``journal_fitness_data``; the rest live in
        ``sync_metadata``, and all of them belong on the journal.
        """
        journal_id = await self._create_journal(integration_api_client)

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
            {"strava_id": "111", "journal_id": journal_id},
        )
        for activity_id in ("111", "222"):
            await _link_strava_activity(async_connection, journal_id, activity_id)

        response = await integration_api_client.get(
            f"/api/journals/{journal_id}/external-links"
        )

        assert response.status_code == 200
        strava_links = [
            link["attributes"]
            for link in response.json()["data"]
            if link["attributes"]["source"] == "strava"
        ]
        # The activity named by both stores is listed once, not twice.
        assert sorted(link["external_id"] for link in strava_links) == ["111", "222"]
        assert sorted(link["url"] for link in strava_links) == [
            "https://www.strava.com/activities/111",
            "https://www.strava.com/activities/222",
        ]

    async def test_returns_google_calendar_link_from_external_event_link(
        self, integration_api_client, async_connection
    ):
        """External links endpoint returns Google Calendar link from JournalExternalEventLink."""
        journal_id = await self._create_journal(integration_api_client)

        # Create a calendar first
        calendar_id = await self._google_synced_calendar(
            integration_api_client, async_connection, "Test Calendar"
        )

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
        assert link["type"] == "external_links"
        assert "id" in link
        assert link["attributes"]["source"] == "google_calendar"
        assert link["attributes"]["external_id"] == "google-event-abc"
        assert "calendar.google.com" in link["attributes"]["url"]

    async def test_omits_event_links_that_cannot_open_in_google_calendar(
        self, integration_api_client, async_connection
    ):
        """A blank event id, or a calendar with no Google id, is not a link.

        Neither can be opened in Google Calendar, so REST omits both rather
        than return a ``google_calendar`` link with a null url — the same rule
        the MCP journal tools apply.
        """
        journal_id = await self._create_journal(integration_api_client)
        google_calendar_id = await self._google_synced_calendar(
            integration_api_client, async_connection, "Synced"
        )
        response = await integration_api_client.post(
            "/api/calendars",
            json={"data": {"type": "calendars", "attributes": {"name": "Local"}}},
        )
        local_calendar_id = response.json()["data"]["id"]
        for calendar_id, external_event_id in (
            (google_calendar_id, "  "),
            (local_calendar_id, "local-event-1"),
        ):
            await async_connection.execute(
                text(
                    "INSERT INTO journal_external_event_links "
                    "(journal_id, calendar_id, external_event_id, "
                    "sync_capability, sync_status) "
                    "VALUES (:journal_id, :calendar_id, :external_event_id, "
                    "'bidirectional', 'synced')"
                ),
                {
                    "journal_id": journal_id,
                    "calendar_id": calendar_id,
                    "external_event_id": external_event_id,
                },
            )

        response = await integration_api_client.get(
            f"/api/journals/{journal_id}/external-links"
        )

        assert response.status_code == 200
        assert response.json()["data"] == []

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
        calendar_id = await self._google_synced_calendar(
            integration_api_client, async_connection, "Mixed Calendar"
        )

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
        sources = {link["attributes"]["source"] for link in data["data"]}
        assert sources == {"strava", "google_calendar"}

    async def test_returns_immich_album_link_with_shared_link(
        self, integration_api_client, async_connection
    ):
        """Album with a public shared link returns immich_album and immich_shared."""
        journal_id = await self._create_journal(integration_api_client)
        await _connect_immich(async_connection)
        await _link_immich_album(
            async_connection,
            journal_id,
            "album-uuid-1",
            shared_link_url="https://immich.example.com/share/tok123",
        )

        response = await integration_api_client.get(
            f"/api/journals/{journal_id}/external-links"
        )

        assert response.status_code == 200
        data = response.json()
        by_source = {
            link["attributes"]["source"]: link["attributes"] for link in data["data"]
        }
        assert set(by_source) == {"immich_album", "immich_shared"}
        assert by_source["immich_album"]["external_id"] == "album-uuid-1"
        assert (
            by_source["immich_album"]["url"]
            == "https://immich.example.com/albums/album-uuid-1"
        )
        assert (
            by_source["immich_shared"]["url"]
            == "https://immich.example.com/share/tok123"
        )

    async def test_returns_immich_album_link_without_shared_link(
        self, integration_api_client, async_connection
    ):
        """Album without a shared link returns only the immich_album link."""
        journal_id = await self._create_journal(integration_api_client)
        await _connect_immich(async_connection)
        await _link_immich_album(async_connection, journal_id, "album-uuid-2")

        response = await integration_api_client.get(
            f"/api/journals/{journal_id}/external-links"
        )

        assert response.status_code == 200
        data = response.json()
        sources = [link["attributes"]["source"] for link in data["data"]]
        assert sources == ["immich_album"]
        assert (
            data["data"][0]["attributes"]["url"]
            == "https://immich.example.com/albums/album-uuid-2"
        )

    async def test_returns_404_for_nonexistent_journal(self, integration_api_client):
        """External links endpoint returns 404 for a journal that doesn't exist."""
        response = await integration_api_client.get(
            "/api/journals/999999/external-links"
        )

        assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.usefixtures("clean_database")
class TestContactExternalLinks:
    """Integration tests for GET /api/contacts/{id}/external-links."""

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

        # Seed the canonical link in sync_metadata (the read path's source).
        await async_connection.execute(
            text(
                "INSERT INTO sync_metadata "
                "(user_id, internal_id, integration_source, external_id, "
                "last_synced_at, version_hash, sync_status, internal_entity_type, "
                "external_entity_type) "
                "VALUES ((SELECT user_id FROM contacts WHERE id = :contact_id), "
                ":contact_id, 'google', :external_id, now(), 'h', "
                "'success', 'contact', 'person')"
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
        assert link["type"] == "external_links"
        assert "id" in link
        assert link["attributes"]["source"] == "google_contacts"
        assert link["attributes"]["external_id"] == "people/c123456"
        assert "contacts.google.com" in link["attributes"]["url"]

    async def test_returns_immich_person_link_from_external_reference(
        self, integration_api_client, async_connection
    ):
        """External links endpoint returns an Immich person link with a person URL."""
        contact_id = await self._create_contact(integration_api_client)
        await _connect_immich(async_connection)
        await async_connection.execute(
            text(
                "INSERT INTO sync_metadata "
                "(user_id, internal_id, integration_source, external_id, "
                "last_synced_at, version_hash, sync_status, internal_entity_type, "
                "external_entity_type) "
                "VALUES ((SELECT user_id FROM contacts WHERE id = :contact_id), "
                ":contact_id, 'immich', :external_id, now(), 'h', "
                "'success', 'contact', 'person')"
            ),
            {"contact_id": contact_id, "external_id": "person-uuid-1"},
        )

        response = await integration_api_client.get(
            f"/api/contacts/{contact_id}/external-links"
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 1
        link = data["data"][0]
        assert link["attributes"]["source"] == "immich"
        assert link["attributes"]["external_id"] == "person-uuid-1"
        assert (
            link["attributes"]["url"]
            == "https://immich.example.com/people/person-uuid-1"
        )

    async def test_returns_404_for_nonexistent_contact(self, integration_api_client):
        """External links endpoint returns 404 for a contact that doesn't exist."""
        response = await integration_api_client.get(
            "/api/contacts/999999/external-links"
        )

        assert response.status_code == 404
