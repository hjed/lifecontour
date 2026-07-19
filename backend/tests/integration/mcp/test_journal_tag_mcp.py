"""
Integration tests for MCP journal tag tools.

Mirrors the contact `list_contact_tags` coverage in
`test_contact_tools_integration.py` for the journal tag namespace.
"""

from datetime import UTC, datetime
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


async def call_update_journal_tag(
    authenticated_lifespan_client, arguments: dict[str, Any]
) -> str:
    """Call the update_journal_tag MCP tool and return the raw SSE response text."""
    async with authenticated_lifespan_client() as authenticated_client:
        session_id = await initialize_mcp_session(authenticated_client)
        response = await authenticated_client.post(
            "/mcp-server/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "update_journal_tag", "arguments": arguments},
            },
            headers=mcp_headers(session_id),
        )

    assert response.status_code == 200
    return str(response.text)


async def call_delete_journal_tag(
    authenticated_lifespan_client, arguments: dict[str, Any]
) -> str:
    """Call the delete_journal_tag MCP tool and return the raw SSE response text."""
    async with authenticated_lifespan_client() as authenticated_client:
        session_id = await initialize_mcp_session(authenticated_client)
        response = await authenticated_client.post(
            "/mcp-server/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "delete_journal_tag", "arguments": arguments},
            },
            headers=mcp_headers(session_id),
        )

    assert response.status_code == 200
    return str(response.text)


@pytest.mark.integration
class TestUpdateJournalTagMCPTool:
    """Integration tests for the update_journal_tag MCP tool."""

    @pytest.mark.asyncio
    async def test_update_journal_tag_via_mounted_http_session(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
    ):
        """The tool updates a tag and the write is committed."""
        tag = await journal_tag_repo.save(
            JournalTag(name="training", color="#00FF00", description="Old")
        )

        raw = await call_update_journal_tag(
            authenticated_lifespan_client,
            {
                "tag_id": str(tag.id),
                "name": "conditioning",
                "color": "#123456",
                "description": "Structured conditioning work",
            },
        )
        payload = extract_mcp_json_payload(raw)

        assert payload["name"] == "conditioning"
        assert payload["color"] == "#123456"
        assert payload["description"] == "Structured conditioning work"

        persisted = await journal_tag_repo.find_by_id(tag.id)
        assert persisted is not None
        assert persisted.name == "conditioning"
        assert persisted.description == "Structured conditioning work"

    @pytest.mark.asyncio
    async def test_update_journal_tag_partial_update(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
    ):
        """Omitted arguments leave the corresponding fields untouched."""
        tag = await journal_tag_repo.save(
            JournalTag(name="training", color="#00FF00", description="Keep me")
        )

        await call_update_journal_tag(
            authenticated_lifespan_client, {"tag_id": str(tag.id), "name": "cardio"}
        )

        persisted = await journal_tag_repo.find_by_id(tag.id)
        assert persisted is not None
        assert persisted.name == "cardio"
        assert persisted.color == "#00FF00"
        assert persisted.description == "Keep me"

    @pytest.mark.asyncio
    async def test_update_journal_tag_move_to_root(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
    ):
        """move_to_root clears the parent, since an omitted parent_id means no change."""
        parent = await journal_tag_repo.save(JournalTag(name="outdoors"))
        child = await journal_tag_repo.save(
            JournalTag(name="climbing", parent_id=parent.id)
        )

        await call_update_journal_tag(
            authenticated_lifespan_client,
            {"tag_id": str(child.id), "move_to_root": True},
        )

        persisted = await journal_tag_repo.find_by_id(child.id)
        assert persisted is not None
        assert persisted.parent_id is None

    @pytest.mark.asyncio
    async def test_update_journal_tag_reparent(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
    ):
        """A tag can be re-parented under another tag."""
        parent = await journal_tag_repo.save(JournalTag(name="outdoors"))
        child = await journal_tag_repo.save(JournalTag(name="climbing"))

        await call_update_journal_tag(
            authenticated_lifespan_client,
            {"tag_id": str(child.id), "parent_id": str(parent.id)},
        )

        persisted = await journal_tag_repo.find_by_id(child.id)
        assert persisted is not None
        assert persisted.parent_id == parent.id

    @pytest.mark.asyncio
    async def test_update_journal_tag_duplicate_name_errors(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
    ):
        """A name held by another tag is rejected and nothing is written."""
        await journal_tag_repo.save(JournalTag(name="training"))
        other = await journal_tag_repo.save(JournalTag(name="reflection"))

        raw = await call_update_journal_tag(
            authenticated_lifespan_client,
            {"tag_id": str(other.id), "name": "TRAINING"},
        )

        assert "already exists" in raw.lower()
        persisted = await journal_tag_repo.find_by_id(other.id)
        assert persisted is not None
        assert persisted.name == "reflection"

    @pytest.mark.asyncio
    async def test_update_journal_tag_cycle_errors(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
    ):
        """A tag cannot become its own ancestor."""
        parent = await journal_tag_repo.save(JournalTag(name="outdoors"))
        child = await journal_tag_repo.save(
            JournalTag(name="climbing", parent_id=parent.id)
        )

        raw = await call_update_journal_tag(
            authenticated_lifespan_client,
            {"tag_id": str(parent.id), "parent_id": str(child.id)},
        )

        assert "circular" in raw.lower()
        persisted = await journal_tag_repo.find_by_id(parent.id)
        assert persisted is not None
        assert persisted.parent_id is None

    @pytest.mark.asyncio
    async def test_update_journal_tag_unknown_tag_errors(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ):
        """Updating a tag that does not exist reports a not-found error."""
        raw = await call_update_journal_tag(
            authenticated_lifespan_client,
            {
                "tag_id": "00000000-0000-0000-0000-000000000000",
                "name": "ghost",
            },
        )

        assert "not found" in raw.lower()

    @pytest.mark.asyncio
    async def test_update_journal_tag_empty_parent_id_errors(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
    ):
        """An empty-string parent_id is rejected, not silently ignored."""
        tag = await journal_tag_repo.save(JournalTag(name="training"))

        raw = await call_update_journal_tag(
            authenticated_lifespan_client,
            {"tag_id": str(tag.id), "parent_id": ""},
        )

        assert "invalid parent tag uuid" in raw.lower()

    @pytest.mark.asyncio
    async def test_update_journal_tag_invalid_uuid_errors(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ):
        """A malformed tag id is reported rather than raising an unhandled error."""
        raw = await call_update_journal_tag(
            authenticated_lifespan_client, {"tag_id": "not-a-uuid", "name": "x"}
        )

        assert "invalid tag uuid" in raw.lower()


@pytest.mark.integration
class TestDeleteJournalTagMCPTool:
    """Integration tests for the delete_journal_tag MCP tool."""

    @pytest.mark.asyncio
    async def test_delete_journal_tag_via_mounted_http_session(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
    ):
        """The tool deletes an unused tag and the write is committed."""
        tag = await journal_tag_repo.save(JournalTag(name="obsolete"))

        raw = await call_delete_journal_tag(
            authenticated_lifespan_client, {"tag_id": str(tag.id)}
        )
        payload = extract_mcp_json_payload(raw)

        assert payload["status"] == "success"
        assert await journal_tag_repo.find_by_id(tag.id) is None

    @pytest.mark.asyncio
    async def test_delete_journal_tag_in_use_unassigns_it(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
        async_connection: AsyncConnection,
    ):
        """Deleting an assigned tag succeeds and leaves the journal untagged."""
        from core_shared.models.journals import EventDateRange, Journal

        from app.core.journal.adapters.sql.journal_repository import (
            SqlJournalRepository,
        )

        journal = await SqlJournalRepository(async_connection).save(
            Journal(
                user_id="test-user",
                title="Tagged Journal",
                content="Test content",
                event_date_range=EventDateRange(
                    start=datetime.now(UTC), end=datetime.now(UTC)
                ),
            )
        )
        tag = await journal_tag_repo.save(JournalTag(name="in-use"))
        await journal_tag_repo.assign_tag(journal.id, tag.id)

        raw = await call_delete_journal_tag(
            authenticated_lifespan_client, {"tag_id": str(tag.id)}
        )

        assert extract_mcp_json_payload(raw)["status"] == "success"
        assert await journal_tag_repo.find_by_id(tag.id) is None
        assert await journal_tag_repo.get_tags_for_journal(journal.id) == []

    @pytest.mark.asyncio
    async def test_delete_journal_tag_unknown_tag_errors(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ):
        """An unknown tag id reports not-found, not a generic failure.

        Asserted on the parsed payload rather than the raw SSE envelope so a
        success response that merely mentions the phrase cannot pass.
        """
        tag_id = "00000000-0000-0000-0000-000000000000"
        raw = await call_delete_journal_tag(
            authenticated_lifespan_client, {"tag_id": tag_id}
        )

        payload = extract_mcp_json_payload(raw)
        assert payload["error"] == "Not found"
        assert str(tag_id) in payload["message"]

    @pytest.mark.asyncio
    async def test_delete_journal_tag_invalid_uuid_errors(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ):
        """A malformed tag id is reported rather than raising an unhandled error."""
        raw = await call_delete_journal_tag(
            authenticated_lifespan_client, {"tag_id": "not-a-uuid"}
        )

        payload = extract_mcp_json_payload(raw)
        assert payload["error"] == "Journal error"
        assert "invalid tag uuid" in payload["message"].lower()


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
