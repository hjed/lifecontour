"""
Integration tests for MCP integration tools.

Tests the full MCP integration tools with real database and queue service integration
using Dishka dependency injection patterns.
"""

import json
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.contact_seeding import seed_contact
from tests.integration.mcp.http_helpers import (
    call_mcp_tool,
)


@pytest.mark.asyncio
async def test_trigger_sync_mcp_tool(
    authenticated_lifespan_client,
    clean_database: AsyncConnection,
):
    """Test trigger_sync MCP tool."""
    # Insert strava auth for test user
    await clean_database.execute(
        text(
            "INSERT INTO user_strava_auth (user_id, athlete_id, encrypted_access_token, encrypted_refresh_token, expires_at, created_at, updated_at) "
            "VALUES ('test-user-123', 12345, 'enc_access', 'enc_refresh', '2030-01-01 00:00:00Z', '2020-01-01 00:00:00Z', '2020-01-01 00:00:00Z')"
        )
    )

    with patch(
        "app.core.integrations.task_queue_service.TaskQueueService.enqueue_strava_sync",
        new_callable=AsyncMock,
    ) as mock_enqueue:
        mock_enqueue.return_value = "test_job_123"
        async with authenticated_lifespan_client() as authenticated_client:
            payload = await call_mcp_tool(
                authenticated_client, "trigger_sync", {"integration_id": "strava"}
            )

            assert "status" in payload
            assert payload["status"] == "queued"
            assert payload["job_id"] == "test_job_123"

            mock_enqueue.assert_awaited_once_with(
                user_id="test-user-123", sync_type="smart"
            )


@pytest.mark.asyncio
async def test_trigger_sync_mcp_tool_immich(
    authenticated_lifespan_client,
    clean_database: AsyncConnection,
):
    """Test trigger_sync MCP tool with Immich integration."""
    # Insert immich auth for test user
    await clean_database.execute(
        text(
            "INSERT INTO user_immich_auth (user_id, server_url, encrypted_api_key, created_at, updated_at) "
            "VALUES ('test-user-123', 'https://immich.example.com', 'encrypted_key', now(), now())"
        )
    )

    with patch(
        "app.core.integrations.task_queue_service.TaskQueueService.enqueue_immich_sync",
        new_callable=AsyncMock,
    ) as mock_enqueue:
        mock_enqueue.return_value = "test_immich_job_123"
        async with authenticated_lifespan_client() as authenticated_client:
            payload = await call_mcp_tool(
                authenticated_client, "trigger_sync", {"integration_id": "immich"}
            )

            assert "status" in payload
            assert payload["status"] == "queued"
            assert payload["job_id"] == "test_immich_job_123"

            mock_enqueue.assert_awaited_once_with(
                user_id="test-user-123", sync_type="smart"
            )


@pytest.mark.asyncio
async def test_get_strava_athlete_mappings_mcp_tool(
    authenticated_lifespan_client,
    clean_database: AsyncConnection,
):
    """Test get_strava_athlete_mappings MCP tool."""
    # Create contact
    c1_id = await seed_contact(clean_database, first_name="Athlete", last_name="One")

    # Insert strava athlete mapping
    await clean_database.execute(
        text(
            "INSERT INTO strava_athlete_mappings (user_id, contact_id, strava_athlete_id, strava_athlete_name) "
            "VALUES ('test-user-123', :contact_id, '123456', 'Athlete One')"
        ),
        {"contact_id": int(c1_id)},
    )

    async with authenticated_lifespan_client() as authenticated_client:
        payload = await call_mcp_tool(
            authenticated_client, "get_strava_athlete_mappings", {}
        )

        assert "mappings" in payload
        assert len(payload["mappings"]) == 1
        assert payload["mappings"][0]["contact_id"] == int(c1_id)
        assert payload["mappings"][0]["strava_athlete_id"] == "123456"
        assert payload["mappings"][0]["strava_athlete_name"] == "Athlete One"

        # Test filtering by strava_athlete_id
        payload2 = await call_mcp_tool(
            authenticated_client,
            "get_strava_athlete_mappings",
            {"strava_athlete_id": "999999"},
            request_id=2,
        )
        assert "mappings" in payload2
        assert len(payload2["mappings"]) == 0


@pytest.mark.asyncio
async def test_resolve_unknown_immich_conflict_is_not_found(
    authenticated_lifespan_client: Callable[..., Any],
) -> None:
    """An unknown conflict answers not-found rather than an internal error."""
    async with authenticated_lifespan_client() as client:
        payload = await call_mcp_tool(
            client,
            "resolve_immich_conflict",
            {"conflict_id": 999_999, "action": "create"},
        )

    assert payload["error"] == "Conflict not found", payload


@pytest.mark.asyncio
async def test_resolve_immich_conflict_link_without_contact_is_refused(
    authenticated_lifespan_client: Callable[..., Any],
    async_connection: AsyncConnection,
) -> None:
    """Linking without naming a contact is reported against contact_id."""
    conflict_id = (
        await async_connection.execute(
            text("""
                INSERT INTO pending_entity_mappings
                    (user_id, integration_source, external_entity_id,
                     external_entity_name, candidate_contact_ids, status)
                VALUES ('test-user-123', 'immich', 'person-no-contact',
                        'Ada Lovelace', '[]'::jsonb, 'unresolved')
                RETURNING id
            """)
        )
    ).scalar_one()

    async with authenticated_lifespan_client() as client:
        payload = await call_mcp_tool(
            client,
            "resolve_immich_conflict",
            {"conflict_id": conflict_id, "action": "link"},
        )

    assert "error" in payload, payload
    assert "contact_id" in json.dumps(payload)
