"""Integration tests for the Immich album-creation MCP tools (ITER11-006).

Drives ``search_immich_photos_for_journal`` and
``create_immich_album_for_journal`` over the mounted MCP HTTP transport, with
the Immich server stubbed via respx and credentials patched.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.mcp.http_helpers import (
    extract_mcp_json_payload,
    sessionless_mcp_headers,
    sessionless_mcp_request,
)

USER_ID = "test-user-123"
SERVER_URL = "https://immich.example.com"
CREDS = (SERVER_URL, "test-api-key")
_GET_CREDS = (
    "app.infrastructure.auth.immich_token_service.ImmichTokenService.get_credentials"
)

_SEARCH_RESPONSE = {
    "assets": {
        "items": [
            {"id": "asset-1", "originalFileName": "a.jpg"},
            {"id": "asset-2", "originalFileName": "b.jpg"},
        ]
    }
}


async def _seed_journal(connection: AsyncConnection) -> int:
    journal_id = (
        await connection.execute(
            text("""
                INSERT INTO journals
                    (user_id, title, content,
                     event_date_range_start, event_date_range_end,
                     created_at, updated_at)
                VALUES (:u, 'Trip', '',
                        '2026-01-15T00:00:00+00:00', '2026-01-15T23:59:59+00:00',
                        now(), now())
                RETURNING id
            """),
            {"u": USER_ID},
        )
    ).scalar_one()
    return int(journal_id)


async def _call_tool(
    client: object, name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    resp = await client.post(  # type: ignore[attr-defined]
        "/mcp-server/mcp",
        json=sessionless_mcp_request(
            "tools/call", {"name": name, "arguments": arguments}
        ),
        headers=sessionless_mcp_headers("tools/call", name),
    )
    assert resp.status_code == 200
    return extract_mcp_json_payload(resp.text)


@pytest.mark.asyncio
async def test_search_immich_photos_for_journal_mcp(
    authenticated_lifespan_client,
    clean_database: AsyncConnection,
    respx_mock,
) -> None:
    journal_id = await _seed_journal(clean_database)
    respx_mock.post(f"{SERVER_URL}/api/search/metadata").mock(
        return_value=httpx.Response(200, json=_SEARCH_RESPONSE)
    )

    with patch(_GET_CREDS, new_callable=AsyncMock, return_value=CREDS):
        async with authenticated_lifespan_client() as client:
            payload = await _call_tool(
                client,
                "search_immich_photos_for_journal",
                {"journal_id": journal_id},
            )

    assert payload["total_count"] == 2
    assert [p["asset_id"] for p in payload["photos"]] == ["asset-1", "asset-2"]


@pytest.mark.asyncio
async def test_create_immich_album_for_journal_mcp_excludes_assets(
    authenticated_lifespan_client,
    clean_database: AsyncConnection,
    respx_mock,
) -> None:
    journal_id = await _seed_journal(clean_database)
    respx_mock.post(f"{SERVER_URL}/api/search/metadata").mock(
        return_value=httpx.Response(200, json=_SEARCH_RESPONSE)
    )
    create_route = respx_mock.post(f"{SERVER_URL}/api/albums").mock(
        return_value=httpx.Response(
            201, json={"id": "album-uuid-1", "albumName": "Trip", "assetCount": 1}
        )
    )

    with patch(_GET_CREDS, new_callable=AsyncMock, return_value=CREDS):
        async with authenticated_lifespan_client() as client:
            payload = await _call_tool(
                client,
                "create_immich_album_for_journal",
                {"journal_id": journal_id, "exclude_asset_ids": ["asset-2"]},
            )

    assert payload["album_id"] == "album-uuid-1"
    assert payload["status"] == "created"
    # The excluded asset must not be sent to Immich.
    sent_body = create_route.calls.last.request.content.decode()
    assert "asset-1" in sent_body
    assert "asset-2" not in sent_body

    # The journal is now linked as a PHOTO_ALBUM.
    from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository

    types = await SqlJournalRepository(clean_database).get_types(journal_id)
    assert "PHOTO_ALBUM" in types


@pytest.mark.asyncio
async def test_create_immich_album_for_journal_mcp_excluding_all_creates_nothing(
    authenticated_lifespan_client,
    clean_database: AsyncConnection,
    respx_mock,
) -> None:
    journal_id = await _seed_journal(clean_database)
    respx_mock.post(f"{SERVER_URL}/api/search/metadata").mock(
        return_value=httpx.Response(200, json=_SEARCH_RESPONSE)
    )
    create_route = respx_mock.post(f"{SERVER_URL}/api/albums").mock(
        return_value=httpx.Response(201, json={"id": "album-x"})
    )

    with patch(_GET_CREDS, new_callable=AsyncMock, return_value=CREDS):
        async with authenticated_lifespan_client() as client:
            payload = await _call_tool(
                client,
                "create_immich_album_for_journal",
                {"journal_id": journal_id, "exclude_asset_ids": ["asset-1", "asset-2"]},
            )

    # Excluding every candidate must not create an album.
    assert payload.get("status") != "created"
    assert "album_id" not in payload
    assert not create_route.called

    from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository

    types = await SqlJournalRepository(clean_database).get_types(journal_id)
    assert "PHOTO_ALBUM" not in types
