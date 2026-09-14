"""
Integration tests for MCP integration tools.

Tests the full MCP integration tools with real database and queue service integration
using Dishka dependency injection patterns.
"""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.mcp.http_helpers import (
    extract_mcp_json_payload,
    sessionless_mcp_headers,
    sessionless_mcp_request,
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
            resp = await authenticated_client.post(
                "/mcp-server/mcp",
                json=sessionless_mcp_request(
                    "tools/call",
                    {
                        "name": "trigger_sync",
                        "arguments": {"integration_id": "strava"},
                    },
                ),
                headers=sessionless_mcp_headers("tools/call", "trigger_sync"),
            )
            assert resp.status_code == 200
            payload = extract_mcp_json_payload(resp.text)

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
            resp = await authenticated_client.post(
                "/mcp-server/mcp",
                json=sessionless_mcp_request(
                    "tools/call",
                    {
                        "name": "trigger_sync",
                        "arguments": {"integration_id": "immich"},
                    },
                ),
                headers=sessionless_mcp_headers("tools/call", "trigger_sync"),
            )
            assert resp.status_code == 200
            payload = extract_mcp_json_payload(resp.text)

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
    result = await clean_database.execute(
        text(
            "INSERT INTO contacts (first_name, last_name) VALUES ('Athlete', 'One') RETURNING id"
        )
    )
    c1_id = result.scalar()
    assert c1_id is not None

    # Insert strava athlete mapping
    await clean_database.execute(
        text(
            "INSERT INTO strava_athlete_mappings (user_id, contact_id, strava_athlete_id, strava_athlete_name) "
            "VALUES ('test-user-123', :contact_id, '123456', 'Athlete One')"
        ),
        {"contact_id": int(c1_id)},
    )

    async with authenticated_lifespan_client() as authenticated_client:
        resp = await authenticated_client.post(
            "/mcp-server/mcp",
            json=sessionless_mcp_request(
                "tools/call",
                {
                    "name": "get_strava_athlete_mappings",
                    "arguments": {},
                },
            ),
            headers=sessionless_mcp_headers(
                "tools/call", "get_strava_athlete_mappings"
            ),
        )
        assert resp.status_code == 200
        payload = extract_mcp_json_payload(resp.text)

        assert "mappings" in payload
        assert len(payload["mappings"]) == 1
        assert payload["mappings"][0]["contact_id"] == int(c1_id)
        assert payload["mappings"][0]["strava_athlete_id"] == "123456"
        assert payload["mappings"][0]["strava_athlete_name"] == "Athlete One"

        # Test filtering by strava_athlete_id
        resp2 = await authenticated_client.post(
            "/mcp-server/mcp",
            json=sessionless_mcp_request(
                "tools/call",
                {
                    "name": "get_strava_athlete_mappings",
                    "arguments": {"strava_athlete_id": "999999"},
                },
                request_id=2,
            ),
            headers=sessionless_mcp_headers(
                "tools/call", "get_strava_athlete_mappings"
            ),
        )
        assert resp2.status_code == 200
        payload2 = extract_mcp_json_payload(resp2.text)
        assert "mappings" in payload2
        assert len(payload2["mappings"]) == 0
