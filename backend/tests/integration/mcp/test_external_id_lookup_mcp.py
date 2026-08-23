"""MCP lookup of journals and contacts by ``(source, external_id)``."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.mcp.http_helpers import call_mcp_tool, initialize_mcp_session

USER_ID = "test-user-123"


async def _insert_journal(
    conn: AsyncConnection, title: str, user_id: str = USER_ID
) -> int:
    now = datetime.now(UTC)
    result = await conn.execute(
        text("""
            INSERT INTO journals
                (user_id, title, content, event_date_range_start, event_date_range_end)
            VALUES (:user_id, :title, 'x', :start, :end)
            RETURNING id
        """),
        {
            "user_id": user_id,
            "title": title,
            "start": now,
            "end": now + timedelta(hours=1),
        },
    )
    row = result.fetchone()
    assert row is not None
    return int(row[0])


async def _link_sync_metadata(
    conn: AsyncConnection,
    *,
    source: str,
    external_id: str,
    internal_id: int | None = None,
    internal_uuid: str | None = None,
    entity_type: str = "journal",
) -> None:
    await conn.execute(
        text("""
            INSERT INTO sync_metadata
                (internal_id, internal_uuid, integration_source, external_id,
                 last_synced_at, version_hash, sync_status, internal_entity_type)
            VALUES (:internal_id, :internal_uuid, :source, :external_id, now(), 'h',
                    'success', :entity_type)
        """),
        {
            "internal_id": internal_id,
            "internal_uuid": internal_uuid,
            "source": source,
            "external_id": external_id,
            "entity_type": entity_type,
        },
    )


class TestGetJournalByExternalId:
    @pytest.mark.asyncio
    async def test_strava_activity_id_resolves_via_fitness_column(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        journal_id = await _insert_journal(clean_database, "Imlay approach")
        await clean_database.execute(
            text(
                "INSERT INTO journal_fitness_data (journal_id, strava_activity_id) "
                "VALUES (:journal_id, '16152597201')"
            ),
            {"journal_id": journal_id},
        )

        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            payload = await call_mcp_tool(
                client,
                session_id,
                "get_journal_by_external_id",
                {"source": "strava", "external_id": "16152597201"},
            )

        assert payload["id"] == journal_id
        assert payload["title"] == "Imlay approach"
        assert payload["external_links"][0]["external_id"] == "16152597201"

    @pytest.mark.asyncio
    async def test_immich_album_resolves_via_sync_metadata(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        journal_id = await _insert_journal(clean_database, "Zion photos")
        album_id = str(uuid4())
        await _link_sync_metadata(
            clean_database,
            source="immich_album",
            external_id=album_id,
            internal_id=journal_id,
        )

        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            payload = await call_mcp_tool(
                client,
                session_id,
                "get_journal_by_external_id",
                {"source": "immich_album", "external_id": album_id},
            )

        assert payload["id"] == journal_id
        assert "photo_album" in payload["types"]

    @pytest.mark.asyncio
    async def test_another_users_journal_is_not_found(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        journal_id = await _insert_journal(clean_database, "Theirs", user_id="someone")
        await clean_database.execute(
            text(
                "INSERT INTO journal_fitness_data (journal_id, strava_activity_id) "
                "VALUES (:journal_id, '999')"
            ),
            {"journal_id": journal_id},
        )

        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            payload = await call_mcp_tool(
                client,
                session_id,
                "get_journal_by_external_id",
                {"source": "strava", "external_id": "999"},
            )

        assert payload["error"] == "Not found"
        assert payload["message"] == "No journal is linked to strava id '999'"
        assert payload["source"] == "strava"
        assert payload["external_id"] == "999"

    @pytest.mark.asyncio
    async def test_invalid_source_is_rejected_with_allowed_values(
        self, authenticated_lifespan_client
    ) -> None:
        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            payload = await call_mcp_tool(
                client,
                session_id,
                "get_journal_by_external_id",
                {"source": "garmin", "external_id": "1"},
            )

        assert payload["error"] == "Validation error"
        assert "Invalid integration_source 'garmin'" in payload["message"]
        assert "strava" in payload["message"]


class TestGetContactByExternalId:
    @pytest.mark.asyncio
    async def test_google_people_id_resolves(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        result = await clean_database.execute(
            text(
                "INSERT INTO contacts (first_name, last_name, is_favourite) "
                "VALUES ('Sarah-Jane', 'Petts', false) RETURNING id"
            )
        )
        row = result.fetchone()
        assert row is not None
        contact_id = int(row[0])
        await _link_sync_metadata(
            clean_database,
            source="google",
            external_id="people/c123",
            internal_id=contact_id,
            entity_type="contact",
        )

        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            payload = await call_mcp_tool(
                client,
                session_id,
                "get_contact_by_external_id",
                {"source": "google", "external_id": "people/c123"},
            )

        assert payload["id"] == str(contact_id)
        assert payload["name"] == "Sarah-Jane Petts"
        assert payload["external_links"][0]["external_id"] == "people/c123"

    @pytest.mark.asyncio
    async def test_unknown_id_is_not_found(self, authenticated_lifespan_client) -> None:
        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            payload = await call_mcp_tool(
                client,
                session_id,
                "get_contact_by_external_id",
                {"source": "immich", "external_id": "nobody"},
            )

        assert payload["error"] == "Not found"
        assert payload["message"] == "No contact is linked to immich id 'nobody'"

    @pytest.mark.asyncio
    async def test_invalid_source_is_rejected(
        self, authenticated_lifespan_client
    ) -> None:
        async with authenticated_lifespan_client() as client:
            session_id = await initialize_mcp_session(client)
            payload = await call_mcp_tool(
                client,
                session_id,
                "get_contact_by_external_id",
                {"source": "strava", "external_id": "1"},
            )

        assert payload["error"] == "Validation error"
        assert "Invalid source 'strava'" in payload["message"]
        assert "google, immich" in payload["message"]
