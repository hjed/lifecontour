"""
Integration tests for MCP journal tag tools.

Mirrors the contact `list_contact_tags` coverage in
`test_contact_tools_integration.py` for the journal tag namespace.
"""

from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_tag_repository import SqlJournalTagRepository
from app.core.journal.models.journal_tag import JournalTag
from tests.integration.mcp.http_helpers import (
    extract_mcp_json_payload,
    initialize_mcp_session,
    mcp_headers,
)


@pytest_asyncio.fixture
async def journal_tag_repo(
    async_connection: AsyncConnection,
) -> SqlJournalTagRepository:
    """Create a journal tag repository bound to the test connection."""
    return SqlJournalTagRepository(async_connection)


async def call_list_journal_tags(
    authenticated_lifespan_client, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Call the list_journal_tags MCP tool and return its payload."""
    async with authenticated_lifespan_client() as authenticated_client:
        session_id = await initialize_mcp_session(authenticated_client)
        response = await authenticated_client.post(
            "/mcp-server/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "list_journal_tags",
                    "arguments": arguments if arguments is not None else {},
                },
            },
            headers=mcp_headers(session_id),
        )

    assert response.status_code == 200
    return extract_mcp_json_payload(response.text)


@pytest.mark.integration
class TestListJournalTagsMCPTool:
    """Integration tests for the list_journal_tags MCP tool."""

    @pytest.mark.asyncio
    async def test_list_journal_tags_via_mounted_http_session(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
    ):
        """Mounted MCP HTTP calls should resolve request-scoped dependencies."""
        await journal_tag_repo.save(JournalTag(name="training"))
        await journal_tag_repo.save(JournalTag(name="reflection"))

        payload = await call_list_journal_tags(
            authenticated_lifespan_client, {"limit": 10}
        )

        assert payload["total_count"] == 2
        # Repository orders by name, so this ordering is deterministic
        assert [tag["name"] for tag in payload["tags"]] == ["reflection", "training"]

    @pytest.mark.asyncio
    async def test_list_journal_tags_returns_colour_and_description(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
    ):
        """The tool exposes colour and description for each tag."""
        await journal_tag_repo.save(
            JournalTag(
                name="training",
                color="#00FF00",
                description="Structured training sessions",
            )
        )

        payload = await call_list_journal_tags(authenticated_lifespan_client)

        tag = payload["tags"][0]
        assert tag["color"] == "#00FF00"
        assert tag["description"] == "Structured training sessions"

    @pytest.mark.asyncio
    async def test_list_journal_tags_returns_hierarchy(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
    ):
        """The tool exposes parent_id so AI callers can reconstruct the tree."""
        parent = await journal_tag_repo.save(JournalTag(name="activities"))
        await journal_tag_repo.save(
            JournalTag(name="activities-climbing", parent_id=parent.id)
        )

        payload = await call_list_journal_tags(authenticated_lifespan_client)

        tags_by_name = {tag["name"]: tag for tag in payload["tags"]}
        assert tags_by_name["activities"]["parent_id"] is None
        assert tags_by_name["activities-climbing"]["parent_id"] == str(parent.id)

    @pytest.mark.asyncio
    async def test_list_journal_tags_without_description_returns_null(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
    ):
        """Tags created without a description serialise it as null."""
        await journal_tag_repo.save(JournalTag(name="training"))

        payload = await call_list_journal_tags(authenticated_lifespan_client)

        assert payload["tags"][0]["description"] is None

    @pytest.mark.asyncio
    async def test_list_journal_tags_respects_limit(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
    ):
        """The limit argument bounds how many tags are returned."""
        await journal_tag_repo.save(JournalTag(name="alpha"))
        await journal_tag_repo.save(JournalTag(name="beta"))
        await journal_tag_repo.save(JournalTag(name="gamma"))

        payload = await call_list_journal_tags(
            authenticated_lifespan_client, {"limit": 2}
        )

        assert payload["total_count"] == 2
        assert [tag["name"] for tag in payload["tags"]] == ["alpha", "beta"]

    @pytest.mark.asyncio
    async def test_list_journal_tags_with_no_tags(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ):
        """An empty tag namespace returns an empty list, not an error."""
        payload = await call_list_journal_tags(authenticated_lifespan_client)

        assert payload["total_count"] == 0
        assert payload["tags"] == []
