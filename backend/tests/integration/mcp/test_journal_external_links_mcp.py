"""
Integration tests for journal MCP external links and integration source filtering.

Tests the full MCP journal tools with real database integration for:
- External links in get_journal responses (Strava, Google Calendar, combined)
- Integration source filtering in search_journals
- Fitness data completeness verification

ITER5-006 Phase 1.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.mcp.http_helpers import (
    extract_mcp_json_payload,
    initialize_mcp_session,
    mcp_headers,
)


class TestJournalExternalLinksMCP:
    """Integration tests for external links in MCP journal responses."""

    @pytest_asyncio.fixture
    async def journal_with_strava(self, clean_database: AsyncConnection) -> int:
        """Create a journal with Strava fitness data and return its ID."""
        now = datetime.now(UTC)
        result = await clean_database.execute(
            text("""
                INSERT INTO journals (user_id, title, content, event_date_range_start, event_date_range_end)
                VALUES (:user_id, :title, :content, :start, :end)
                RETURNING id
            """),
            {
                "user_id": "test-user-123",
                "title": "Morning Run",
                "content": "Strava-imported morning run",
                "start": now,
                "end": now + timedelta(hours=1),
            },
        )
        row = result.fetchone()
        assert row is not None
        journal_id = int(row[0])

        # Add fitness data with strava_activity_id
        await clean_database.execute(
            text("""
                INSERT INTO journal_fitness_data
                    (journal_id, distance, elevation_gain, elevation_loss,
                     duration, calories, heart_rate_avg, heart_rate_max,
                     strava_activity_id)
                VALUES (:journal_id, 10500, 120, 115,
                        3600, 550, 145, 175,
                        '12345678')
            """),
            {"journal_id": journal_id},
        )

        return journal_id

    @pytest_asyncio.fixture
    async def journal_with_google_calendar(
        self, clean_database: AsyncConnection
    ) -> int:
        """Create a journal with a Google Calendar external event link."""
        now = datetime.now(UTC)
        calendar_id = str(uuid4())

        # Create calendar
        await clean_database.execute(
            text("""
                INSERT INTO calendars (id, name, color, user_id, google_calendar_id)
                VALUES (:id, :name, :color, :user_id, :google_calendar_id)
            """),
            {
                "id": calendar_id,
                "name": "Work Calendar",
                "color": "#3B82F6",
                "user_id": "test-user-123",
                "google_calendar_id": "work@gmail.com",
            },
        )

        # Create journal
        result = await clean_database.execute(
            text("""
                INSERT INTO journals (user_id, title, content, event_date_range_start, event_date_range_end)
                VALUES (:user_id, :title, :content, :start, :end)
                RETURNING id
            """),
            {
                "user_id": "test-user-123",
                "title": "Team Meeting",
                "content": "Weekly sync",
                "start": now,
                "end": now + timedelta(hours=1),
            },
        )
        row = result.fetchone()
        assert row is not None
        journal_id = int(row[0])

        # Add calendar info
        await clean_database.execute(
            text("""
                INSERT INTO journal_calendar_info
                    (journal_id, calendar_id, is_all_day, event_state)
                VALUES (:journal_id, :calendar_id, false, 'confirmed')
            """),
            {"journal_id": journal_id, "calendar_id": calendar_id},
        )

        # Add external event link with Google Calendar event ID
        await clean_database.execute(
            text("""
                INSERT INTO journal_external_event_links
                    (journal_id, calendar_id, external_event_id,
                     sync_capability, sync_status)
                VALUES (:journal_id, :calendar_id, :external_event_id,
                        'bidirectional', 'synced')
            """),
            {
                "journal_id": journal_id,
                "calendar_id": calendar_id,
                "external_event_id": "gcal_event_abc123",
            },
        )

        return journal_id

    @pytest_asyncio.fixture
    async def journal_with_multiple_links(self, clean_database: AsyncConnection) -> int:
        """Create a journal with both Strava and Google Calendar links."""
        now = datetime.now(UTC)
        calendar_id = str(uuid4())

        # Create calendar
        await clean_database.execute(
            text("""
                INSERT INTO calendars (id, name, color, user_id, google_calendar_id)
                VALUES (:id, :name, :color, :user_id, :google_calendar_id)
            """),
            {
                "id": calendar_id,
                "name": "Fitness Calendar",
                "color": "#10B981",
                "user_id": "test-user-123",
                "google_calendar_id": "fitness@gmail.com",
            },
        )

        # Create journal
        result = await clean_database.execute(
            text("""
                INSERT INTO journals (user_id, title, content, event_date_range_start, event_date_range_end)
                VALUES (:user_id, :title, :content, :start, :end)
                RETURNING id
            """),
            {
                "user_id": "test-user-123",
                "title": "Trail Run",
                "content": "Imported from Strava and synced to calendar",
                "start": now,
                "end": now + timedelta(hours=2),
            },
        )
        row = result.fetchone()
        assert row is not None
        journal_id = int(row[0])

        # Add fitness data with strava_activity_id
        await clean_database.execute(
            text("""
                INSERT INTO journal_fitness_data
                    (journal_id, distance, duration, strava_activity_id)
                VALUES (:journal_id, 15000, 5400, '99887766')
            """),
            {"journal_id": journal_id},
        )

        # Add calendar info
        await clean_database.execute(
            text("""
                INSERT INTO journal_calendar_info
                    (journal_id, calendar_id, is_all_day, event_state)
                VALUES (:journal_id, :calendar_id, false, 'confirmed')
            """),
            {"journal_id": journal_id, "calendar_id": calendar_id},
        )

        # Add external event link
        await clean_database.execute(
            text("""
                INSERT INTO journal_external_event_links
                    (journal_id, calendar_id, external_event_id,
                     sync_capability, sync_status)
                VALUES (:journal_id, :calendar_id, :external_event_id,
                        'bidirectional', 'synced')
            """),
            {
                "journal_id": journal_id,
                "calendar_id": calendar_id,
                "external_event_id": "gcal_trail_run_xyz",
            },
        )

        return journal_id

    @pytest_asyncio.fixture
    async def journal_without_links(self, clean_database: AsyncConnection) -> int:
        """Create a plain journal with no external links."""
        now = datetime.now(UTC)
        result = await clean_database.execute(
            text("""
                INSERT INTO journals (user_id, title, content, event_date_range_start, event_date_range_end)
                VALUES (:user_id, :title, :content, :start, :end)
                RETURNING id
            """),
            {
                "user_id": "test-user-123",
                "title": "Daily Note",
                "content": "Just a regular journal entry",
                "start": now,
                "end": now + timedelta(hours=1),
            },
        )
        row = result.fetchone()
        assert row is not None
        return int(row[0])

    @pytest_asyncio.fixture
    async def journal_with_pending_google_link(
        self, clean_database: AsyncConnection
    ) -> int:
        """Create a journal with a pending Google Calendar external event link (NULL external_event_id)."""
        now = datetime.now(UTC)
        calendar_id = str(uuid4())

        # Create calendar
        await clean_database.execute(
            text("""
                INSERT INTO calendars (id, name, color, user_id, google_calendar_id)
                VALUES (:id, :name, :color, :user_id, :google_calendar_id)
            """),
            {
                "id": calendar_id,
                "name": "Pending Calendar",
                "color": "#F59E0B",
                "user_id": "test-user-123",
                "google_calendar_id": "pending@gmail.com",
            },
        )

        # Create journal
        result = await clean_database.execute(
            text("""
                INSERT INTO journals (user_id, title, content, event_date_range_start, event_date_range_end)
                VALUES (:user_id, :title, :content, :start, :end)
                RETURNING id
            """),
            {
                "user_id": "test-user-123",
                "title": "Pending Meeting",
                "content": "Not yet synced",
                "start": now,
                "end": now + timedelta(hours=1),
            },
        )
        row = result.fetchone()
        assert row is not None
        journal_id = int(row[0])

        # Add calendar info
        await clean_database.execute(
            text("""
                INSERT INTO journal_calendar_info
                    (journal_id, calendar_id, is_all_day, event_state)
                VALUES (:journal_id, :calendar_id, false, 'confirmed')
            """),
            {"journal_id": journal_id, "calendar_id": calendar_id},
        )

        # Add external event link with NULL Google Calendar event ID
        await clean_database.execute(
            text("""
                INSERT INTO journal_external_event_links
                    (journal_id, calendar_id, external_event_id,
                     sync_capability, sync_status)
                VALUES (:journal_id, :calendar_id, NULL,
                        'outbound', 'pending')
            """),
            {
                "journal_id": journal_id,
                "calendar_id": calendar_id,
            },
        )

        return journal_id

    @pytest.mark.asyncio
    async def test_get_journal_with_strava_link(
        self, authenticated_lifespan_client, journal_with_strava: int
    ) -> None:
        """get_journal returns Strava external link with correct URL."""
        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            response = await client.post(
                "/mcp-server/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "get_journal",
                        "arguments": {"journal_id": journal_with_strava},
                    },
                },
                headers=mcp_headers(session_id),
            )

            assert response.status_code == 200
            payload = extract_mcp_json_payload(response.text)

            assert "error" not in payload
            assert "external_links" in payload
            links = payload["external_links"]
            assert len(links) == 1

            strava_link = links[0]
            assert strava_link["source"] == "strava"
            assert strava_link["external_id"] == "12345678"
            assert strava_link["url"] == "https://www.strava.com/activities/12345678"

    @pytest.mark.asyncio
    async def test_get_journal_with_google_calendar_link(
        self,
        authenticated_lifespan_client,
        journal_with_google_calendar: int,
    ) -> None:
        """get_journal returns Google Calendar external link."""
        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            response = await client.post(
                "/mcp-server/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "get_journal",
                        "arguments": {"journal_id": journal_with_google_calendar},
                    },
                },
                headers=mcp_headers(session_id),
            )

            assert response.status_code == 200
            payload = extract_mcp_json_payload(response.text)

            assert "error" not in payload
            assert "external_links" in payload
            links = payload["external_links"]
            assert len(links) == 1

            gcal_link = links[0]
            assert gcal_link["source"] == "google_calendar"
            assert gcal_link["external_id"] == "gcal_event_abc123"
            assert gcal_link["url"] is not None
            assert "calendar.google.com" in gcal_link["url"]

    @pytest.mark.asyncio
    async def test_get_journal_with_multiple_links(
        self,
        authenticated_lifespan_client,
        journal_with_multiple_links: int,
    ) -> None:
        """get_journal returns both Strava and Google Calendar links."""
        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            response = await client.post(
                "/mcp-server/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "get_journal",
                        "arguments": {"journal_id": journal_with_multiple_links},
                    },
                },
                headers=mcp_headers(session_id),
            )

            assert response.status_code == 200
            payload = extract_mcp_json_payload(response.text)

            assert "error" not in payload
            links = payload["external_links"]
            assert len(links) == 2

            sources = {link["source"] for link in links}
            assert sources == {"strava", "google_calendar"}

            strava_link = next(link for link in links if link["source"] == "strava")
            assert strava_link["external_id"] == "99887766"
            assert strava_link["url"] == "https://www.strava.com/activities/99887766"

            gcal_link = next(
                link for link in links if link["source"] == "google_calendar"
            )
            assert gcal_link["external_id"] == "gcal_trail_run_xyz"
            assert gcal_link["url"] is not None

    @pytest.mark.asyncio
    async def test_get_journal_without_external_links(
        self,
        authenticated_lifespan_client,
        journal_without_links: int,
    ) -> None:
        """get_journal returns empty external_links for plain journal."""
        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            response = await client.post(
                "/mcp-server/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "get_journal",
                        "arguments": {"journal_id": journal_without_links},
                    },
                },
                headers=mcp_headers(session_id),
            )

            assert response.status_code == 200
            payload = extract_mcp_json_payload(response.text)

            assert "error" not in payload
            assert "external_links" in payload
            assert payload["external_links"] == []

    @pytest.mark.asyncio
    async def test_get_journal_with_pending_google_link(
        self,
        authenticated_lifespan_client,
        journal_with_pending_google_link: int,
    ) -> None:
        """get_journal returns empty external_links for journal with pending google calendar link."""
        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            response = await client.post(
                "/mcp-server/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "get_journal",
                        "arguments": {"journal_id": journal_with_pending_google_link},
                    },
                },
                headers=mcp_headers(session_id),
            )

            assert response.status_code == 200
            payload = extract_mcp_json_payload(response.text)

            assert "error" not in payload
            assert "external_links" in payload
            assert payload["external_links"] == []

    @pytest.mark.asyncio
    async def test_fitness_data_completeness(
        self,
        authenticated_lifespan_client,
        journal_with_strava: int,
    ) -> None:
        """Fitness data fields are fully populated in MCP response."""
        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            response = await client.post(
                "/mcp-server/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "get_journal",
                        "arguments": {"journal_id": journal_with_strava},
                    },
                },
                headers=mcp_headers(session_id),
            )

            assert response.status_code == 200
            payload = extract_mcp_json_payload(response.text)

            assert "error" not in payload
            assert "fitness" in payload["types"]
            fitness = payload["type_data"]["fitness"]

            # Verify all required fitness data fields
            assert fitness["distance"] == 10500
            assert fitness["elevation_gain"] == 120
            assert fitness["elevation_loss"] == 115
            assert fitness["duration"] == 3600
            assert fitness["calories"] == 550
            assert fitness["heart_rate_avg"] == 145
            assert fitness["heart_rate_max"] == 175
            assert fitness["strava_activity_id"] == "12345678"


class TestSearchJournalsIntegrationSourceFilter:
    """Integration tests for search_journals integration_source filter."""

    @pytest_asyncio.fixture
    async def journals_with_mixed_sources(
        self, clean_database: AsyncConnection
    ) -> dict[str, int]:
        """Create journals with different integration sources."""
        now = datetime.now(UTC)
        calendar_id = str(uuid4())
        ids: dict[str, int] = {}

        # Create calendar for Google Calendar links
        await clean_database.execute(
            text("""
                INSERT INTO calendars (id, name, color, user_id, google_calendar_id)
                VALUES (:id, :name, :color, :user_id, :google_calendar_id)
            """),
            {
                "id": calendar_id,
                "name": "Test Calendar",
                "color": "#3B82F6",
                "user_id": "test-user-123",
                "google_calendar_id": "test@gmail.com",
            },
        )

        # Journal with Strava link
        result = await clean_database.execute(
            text("""
                INSERT INTO journals (user_id, title, content, event_date_range_start, event_date_range_end)
                VALUES (:user_id, 'Strava Run', 'Imported from Strava', :start, :end)
                RETURNING id
            """),
            {
                "user_id": "test-user-123",
                "start": now,
                "end": now + timedelta(hours=1),
            },
        )
        row = result.fetchone()
        assert row is not None
        strava_id = int(row[0])
        ids["strava"] = strava_id

        await clean_database.execute(
            text("""
                INSERT INTO journal_fitness_data (journal_id, strava_activity_id)
                VALUES (:journal_id, '11111111')
            """),
            {"journal_id": strava_id},
        )

        # Journal with Google Calendar link
        result = await clean_database.execute(
            text("""
                INSERT INTO journals (user_id, title, content, event_date_range_start, event_date_range_end)
                VALUES (:user_id, 'Calendar Event', 'Synced from Google', :start, :end)
                RETURNING id
            """),
            {
                "user_id": "test-user-123",
                "start": now + timedelta(hours=2),
                "end": now + timedelta(hours=3),
            },
        )
        row = result.fetchone()
        assert row is not None
        gcal_id = int(row[0])
        ids["google_calendar"] = gcal_id

        await clean_database.execute(
            text("""
                INSERT INTO journal_calendar_info
                    (journal_id, calendar_id, is_all_day, event_state)
                VALUES (:journal_id, :calendar_id, false, 'confirmed')
            """),
            {"journal_id": gcal_id, "calendar_id": calendar_id},
        )

        await clean_database.execute(
            text("""
                INSERT INTO journal_external_event_links
                    (journal_id, calendar_id, external_event_id,
                     sync_capability, sync_status)
                VALUES (:journal_id, :calendar_id, 'gcal_event_xyz',
                        'bidirectional', 'synced')
            """),
            {"journal_id": gcal_id, "calendar_id": calendar_id},
        )

        # Pending journal (NULL external event id)
        result = await clean_database.execute(
            text("""
                INSERT INTO journals (user_id, title, content, event_date_range_start, event_date_range_end)
                VALUES (:user_id, 'Pending Note', 'No integration', :start, :end)
                RETURNING id
            """),
            {
                "user_id": "test-user-123",
                "start": now + timedelta(hours=4),
                "end": now + timedelta(hours=5),
            },
        )
        row = result.fetchone()
        assert row is not None
        pending_id = int(row[0])
        ids["pending"] = pending_id

        await clean_database.execute(
            text("""
                INSERT INTO journal_calendar_info
                    (journal_id, calendar_id, is_all_day, event_state)
                VALUES (:journal_id, :calendar_id, false, 'confirmed')
            """),
            {"journal_id": pending_id, "calendar_id": calendar_id},
        )

        await clean_database.execute(
            text("""
                INSERT INTO journal_external_event_links
                    (journal_id, calendar_id, external_event_id,
                     sync_capability, sync_status)
                VALUES (:journal_id, :calendar_id, NULL,
                        'outbound', 'pending')
            """),
            {"journal_id": pending_id, "calendar_id": calendar_id},
        )

        # Empty Strava ID
        result = await clean_database.execute(
            text("""
                INSERT INTO journals (user_id, title, content, event_date_range_start, event_date_range_end)
                VALUES (:user_id, 'Empty Strava Note', 'Empty strava id', :start, :end)
                RETURNING id
            """),
            {
                "user_id": "test-user-123",
                "start": now + timedelta(hours=6),
                "end": now + timedelta(hours=7),
            },
        )
        row = result.fetchone()
        assert row is not None
        empty_strava_id = int(row[0])
        ids["empty_strava"] = empty_strava_id

        await clean_database.execute(
            text("""
                INSERT INTO journal_fitness_data (journal_id, strava_activity_id)
                VALUES (:journal_id, '   ')
            """),
            {"journal_id": empty_strava_id},
        )

        # Empty Google Calendar ID
        result = await clean_database.execute(
            text("""
                INSERT INTO journals (user_id, title, content, event_date_range_start, event_date_range_end)
                VALUES (:user_id, 'Empty GCal Note', 'Empty gcal id', :start, :end)
                RETURNING id
            """),
            {
                "user_id": "test-user-123",
                "start": now + timedelta(hours=8),
                "end": now + timedelta(hours=9),
            },
        )
        row = result.fetchone()
        assert row is not None
        empty_gcal_id = int(row[0])
        ids["empty_gcal"] = empty_gcal_id

        await clean_database.execute(
            text("""
                INSERT INTO journal_calendar_info
                    (journal_id, calendar_id, is_all_day, event_state)
                VALUES (:journal_id, :calendar_id, false, 'confirmed')
            """),
            {"journal_id": empty_gcal_id, "calendar_id": calendar_id},
        )

        await clean_database.execute(
            text("""
                INSERT INTO journal_external_event_links
                    (journal_id, calendar_id, external_event_id,
                     sync_capability, sync_status)
                VALUES (:journal_id, :calendar_id, '   ',
                        'outbound', 'synced')
            """),
            {"journal_id": empty_gcal_id, "calendar_id": calendar_id},
        )

        return ids

    @pytest.mark.asyncio
    async def test_search_journals_with_strava_filter(
        self,
        authenticated_lifespan_client,
        journals_with_mixed_sources: dict[str, int],
    ) -> None:
        """search_journals with integration_source=strava returns only Strava-linked journals."""
        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            response = await client.post(
                "/mcp-server/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "search_journals",
                        "arguments": {"integration_source": "strava"},
                    },
                },
                headers=mcp_headers(session_id),
            )

            assert response.status_code == 200
            payload = extract_mcp_json_payload(response.text)

            assert "error" not in payload
            assert payload["total_hits"] == 1
            assert len(payload["results"]) == 1
            assert payload["results"][0]["title"] == "Strava Run"
            assert "strava" in payload["summary"]

    @pytest.mark.asyncio
    async def test_search_journals_with_google_calendar_filter(
        self,
        authenticated_lifespan_client,
        journals_with_mixed_sources: dict[str, int],
    ) -> None:
        """search_journals with integration_source=google_calendar returns only Google-linked journals."""
        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            response = await client.post(
                "/mcp-server/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "search_journals",
                        "arguments": {"integration_source": "google_calendar"},
                    },
                },
                headers=mcp_headers(session_id),
            )

            assert response.status_code == 200
            payload = extract_mcp_json_payload(response.text)

            assert "error" not in payload
            assert payload["total_hits"] == 1
            assert len(payload["results"]) == 1
            assert payload["results"][0]["title"] == "Calendar Event"

    @pytest.mark.asyncio
    async def test_get_journal_with_empty_gcal_link(
        self,
        authenticated_lifespan_client,
        journals_with_mixed_sources: dict[str, int],
    ) -> None:
        """get_journal returns empty external_links for empty/whitespace external_event_id."""
        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            response = await client.post(
                "/mcp-server/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "get_journal",
                        "arguments": {
                            "journal_id": journals_with_mixed_sources["empty_gcal"]
                        },
                    },
                },
                headers=mcp_headers(session_id),
            )

            assert response.status_code == 200
            payload = extract_mcp_json_payload(response.text)
            assert "error" not in payload
            assert "external_links" in payload
            assert payload["external_links"] == []

    @pytest.mark.asyncio
    async def test_search_journals_invalid_integration_source(
        self, authenticated_lifespan_client
    ) -> None:
        """search_journals with invalid integration_source returns error."""
        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            response = await client.post(
                "/mcp-server/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "search_journals",
                        "arguments": {"integration_source": "invalid_source"},
                    },
                },
                headers=mcp_headers(session_id),
            )

            assert response.status_code == 200
            payload = extract_mcp_json_payload(response.text)
            assert payload["error"] == "Validation error"
            assert "Invalid integration_source" in payload["message"]
