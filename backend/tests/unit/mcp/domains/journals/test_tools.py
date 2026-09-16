"""
Unit tests for journal domain MCP tools.

Tests the MCP tools for journal management functionality.
Note: Full functionality testing with mocked services is done in integration tests.
These unit tests focus on tool registration and basic structure.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from core_shared.models.history import Provenance
from fastmcp import Client, FastMCP

from app.core.history.models import FieldHistoryEntry
from app.mcp.domains.journals.tools import (
    _journal_history_entry_to_schema,
    _parse_optional_datetime_filter,
    _resolve_tag_filters,
    register_journal_tools,
)


class TestJournalTools:
    """Test journal MCP tools registration and functionality."""

    @pytest.fixture
    def mcp_server(self):
        """Create FastMCP server for testing."""
        from typing import Any

        mcp: Any = FastMCP("TestServer")
        register_journal_tools(mcp)
        return mcp

    @pytest.mark.asyncio
    async def test_list_tools(self, mcp_server):
        """Test that journal tools are properly registered and listed."""
        # Use FastMCP Client for in-memory testing
        async with Client(mcp_server) as client:
            # List available tools
            tools_response = await client.list_tools()

            # Extract tools list - the response might be a list or have a tools attribute
            if hasattr(tools_response, "tools"):
                tools = tools_response.tools
            else:
                tools = tools_response

            # Verify journal tools are registered
            tool_names = [tool.name for tool in tools]
            expected_tools = [
                "create_journal_entry",
                "update_journal_entry",
                "get_journal",
                "search_journals",
                "search_activities",
                "get_activity_stats",
                "analyze_activity_trends",
                "get_route_history",
                "get_journal_history",
                "delete_journal",
                "get_contact_journals",
                "link_journal_to_contact",
                "merge_journals",
                "get_merge_candidates",
                "get_daily_summary",
                "list_journal_tags",
                "delete_journal_tag",
                "merge_journal_tag",
            ]

            for expected_tool in expected_tools:
                assert expected_tool in tool_names, (
                    f"Tool {expected_tool} not found in registered tools"
                )

    @pytest.mark.asyncio
    async def test_list_journal_tags_tool_schema(self, mcp_server):
        """Test list_journal_tags exposes an optional bounded limit parameter."""
        async with Client(mcp_server) as client:
            tools_response = await client.list_tools()

            if hasattr(tools_response, "tools"):
                tools = tools_response.tools
            else:
                tools = tools_response

            tool = next(t for t in tools if t.name == "list_journal_tags")

            schema = tool.input_schema
            assert "limit" in schema["properties"], (
                "list_journal_tags should expose a limit parameter"
            )
            # limit is optional so AI callers can list tags with no arguments
            assert "limit" not in schema.get("required", [])
            assert schema["properties"]["limit"]["maximum"] == 100
            assert schema["properties"]["limit"]["minimum"] == 1

    @pytest.mark.asyncio
    async def test_update_journal_tag_tool_schema(self, mcp_server):
        """Test update_journal_tag exposes the editable fields and requires only the id."""
        async with Client(mcp_server) as client:
            tools_response = await client.list_tools()

            if hasattr(tools_response, "tools"):
                tools = tools_response.tools
            else:
                tools = tools_response

            tool = next(t for t in tools if t.name == "update_journal_tag")

            schema = tool.input_schema
            properties = schema["properties"]
            for field in ("tag_id", "name", "color", "description", "parent_id"):
                assert field in properties, f"{field} should be an update parameter"

            # Only the tag id is mandatory: every other field is an optional edit.
            assert schema.get("required", []) == ["tag_id"]

            # move_to_root is how callers clear a parent, since an omitted
            # parent_id means "leave the parent alone".
            assert "move_to_root" in properties

            assert tool.description is not None
            assert "update_contact_tag" in tool.description, (
                "journal tag tool should point at the contact tag equivalent"
            )

    @pytest.mark.asyncio
    async def test_delete_journal_tag_tool_schema(self, mcp_server):
        """Test delete_journal_tag takes only the tag id and warns about un-assignment."""
        async with Client(mcp_server) as client:
            tools_response = await client.list_tools()

            if hasattr(tools_response, "tools"):
                tools = tools_response.tools
            else:
                tools = tools_response

            tool = next(t for t in tools if t.name == "delete_journal_tag")

            schema = tool.input_schema
            assert "tag_id" in schema["properties"]
            assert schema.get("required", []) == ["tag_id"]

            assert tool.description is not None
            # Deleting un-assigns the tag from every journal, so the docstring
            # must say so rather than letting callers assume it is blocked.
            # Assert the phrase, not just the word "journal" — the tool name
            # alone would satisfy that and the contract would go undefended.
            assert "every journal" in tool.description.lower()
            assert "re-parented" in tool.description.lower()
            assert "delete_contact_tag" in tool.description, (
                "journal tag tool should point at the contact tag equivalent"
            )

    @pytest.mark.asyncio
    async def test_merge_journal_tag_tool_schema(self, mcp_server):
        """Test merge_journal_tag takes both tag ids and documents the semantics."""
        async with Client(mcp_server) as client:
            tools_response = await client.list_tools()

            if hasattr(tools_response, "tools"):
                tools = tools_response.tools
            else:
                tools = tools_response

            tool = next(t for t in tools if t.name == "merge_journal_tag")

            schema = tool.input_schema
            properties = schema["properties"]
            assert "source_tag_id" in properties
            assert "target_tag_id" in properties
            # Both ids are mandatory: there is no sensible default survivor.
            assert sorted(schema.get("required", [])) == [
                "source_tag_id",
                "target_tag_id",
            ]

            assert tool.description is not None
            description = tool.description.lower()
            # The destructive half of the contract must be stated, not implied
            # by the tool name — the source tag is deleted.
            assert "deleted" in description
            assert "descendant" in description, (
                "the rejected-merge rule should be documented for callers"
            )
            assert "merge_contact_tags" in tool.description, (
                "journal tag tool should point at the contact tag equivalent"
            )

    @pytest.mark.asyncio
    async def test_create_journal_entry_tool_registration(self, mcp_server):
        """Test that create_journal_entry tool is properly registered with correct schema."""
        async with Client(mcp_server) as client:
            # List available tools
            tools_response = await client.list_tools()

            # Extract tools list
            if hasattr(tools_response, "tools"):
                tools = tools_response.tools
            else:
                tools = tools_response

            # Find the create_journal_entry tool
            create_tool = None
            for tool in tools:
                if tool.name == "create_journal_entry":
                    create_tool = tool
                    break

            assert create_tool is not None, "create_journal_entry tool not found"
            assert create_tool.description is not None
            assert "create" in create_tool.description.lower()
            assert create_tool.input_schema is not None

            # Verify the tool has the expected parameter
            properties = create_tool.input_schema.get("properties", {})
            assert "request" in properties

    @pytest.mark.asyncio
    async def test_update_journal_entry_tool_registration(self, mcp_server):
        """Test that update_journal_entry tool is properly registered with correct schema."""
        async with Client(mcp_server) as client:
            # List available tools
            tools_response = await client.list_tools()

            # Extract tools list
            if hasattr(tools_response, "tools"):
                tools = tools_response.tools
            else:
                tools = tools_response

            # Find the update_journal_entry tool
            update_tool = None
            for tool in tools:
                if tool.name == "update_journal_entry":
                    update_tool = tool
                    break

            assert update_tool is not None, "update_journal_entry tool not found"
            assert update_tool.description is not None
            assert "update" in update_tool.description.lower()
            assert update_tool.input_schema is not None

            # Verify the tool has the expected parameters
            properties = update_tool.input_schema.get("properties", {})
            assert "journal_id" in properties
            assert "request" in properties

    @pytest.mark.asyncio
    async def test_get_journal_tool_registration(self, mcp_server):
        """Test that get_journal tool is properly registered with correct schema."""
        async with Client(mcp_server) as client:
            # List available tools
            tools_response = await client.list_tools()

            # Extract tools list
            if hasattr(tools_response, "tools"):
                tools = tools_response.tools
            else:
                tools = tools_response

            # Find the get_journal tool
            get_tool = None
            for tool in tools:
                if tool.name == "get_journal":
                    get_tool = tool
                    break

            assert get_tool is not None, "get_journal tool not found"
            assert get_tool.description is not None
            assert get_tool.input_schema is not None

            # Verify the tool has the expected parameters
            properties = get_tool.input_schema.get("properties", {})
            assert "journal_id" in properties
            assert "include_children" in properties

    @pytest.mark.asyncio
    async def test_get_daily_summary_tool_registration(self, mcp_server):
        """Test that get_daily_summary tool is properly registered with correct schema."""
        async with Client(mcp_server) as client:
            tools_response = await client.list_tools()
            tools = (
                tools_response.tools
                if hasattr(tools_response, "tools")
                else tools_response
            )

            summary_tool = next(
                (t for t in tools if t.name == "get_daily_summary"), None
            )

            assert summary_tool is not None, "get_daily_summary tool not found"
            assert summary_tool.description is not None
            assert summary_tool.input_schema is not None

            # Verify the tool has the expected parameters
            properties = summary_tool.input_schema.get("properties", {})
            assert "summary_date" in properties

    @pytest.mark.asyncio
    async def test_get_journal_history_tool_registration(self, mcp_server):
        """Test that get_journal_history is registered with the expected schema."""
        async with Client(mcp_server) as client:
            tools_response = await client.list_tools()
            tools = (
                tools_response.tools
                if hasattr(tools_response, "tools")
                else tools_response
            )

            history_tool = next(
                (t for t in tools if t.name == "get_journal_history"), None
            )

            assert history_tool is not None, "get_journal_history tool not found"
            assert history_tool.description is not None
            assert "history" in history_tool.description.lower()
            assert history_tool.input_schema is not None

            # Verify the tool exposes journal_id plus pagination params.
            properties = history_tool.input_schema.get("properties", {})
            assert "journal_id" in properties
            assert "page" in properties
            assert "limit" in properties


class TestJournalHistoryEntryMapping:
    """The MCP mapping must preserve field-level detail and provenance,
    matching the REST ``HistoryConverter`` value coercion."""

    def test_maps_all_fields_and_coerces_provenance_enum(self) -> None:
        entry = FieldHistoryEntry(
            entity_type="journal",
            entity_id=42,
            field_name="title",
            old_value="Old",
            new_value="New",
            changed_by="user@example.com",
            source=Provenance.UI,
            created_at=datetime(2024, 1, 15, 10, 30, tzinfo=UTC),
            id=7,
        )

        schema = _journal_history_entry_to_schema(entry)

        assert schema.entity_type == "journal"
        assert schema.entity_id == 42
        assert schema.field_name == "title"
        assert schema.old_value == "Old"
        assert schema.new_value == "New"
        assert schema.changed_by == "user@example.com"
        # Provenance enum is coerced to its string value (parity with the API).
        assert schema.source == "ui"
        assert schema.created_at == datetime(2024, 1, 15, 10, 30, tzinfo=UTC)

    def test_parses_iso_string_created_at(self) -> None:
        entry = FieldHistoryEntry(
            entity_type="journal",
            entity_id=1,
            field_name="content",
            source=Provenance.MCP,
            created_at="2024-03-11T08:00:00+00:00",
            id=9,
        )

        schema = _journal_history_entry_to_schema(entry)

        assert schema.source == "mcp"
        assert schema.created_at == datetime.fromisoformat("2024-03-11T08:00:00+00:00")
        assert schema.old_value is None
        assert schema.new_value is None


class TestDatetimeFilterParsing:
    def test_normalizes_date_only_filters_to_utc_bounds(self) -> None:
        assert _parse_optional_datetime_filter("2024-03-11", "start_date") == datetime(
            2024, 3, 11, 0, 0, 0, tzinfo=UTC
        )
        assert _parse_optional_datetime_filter(
            "2024-03-11", "end_date", is_end=True
        ) == datetime(2024, 3, 11, 23, 59, 59, 999999, tzinfo=UTC)

    def test_preserves_timezone_aware_datetime_filters(self) -> None:
        assert _parse_optional_datetime_filter(
            "2024-03-11T09:15:00Z", "start_date"
        ) == datetime(2024, 3, 11, 9, 15, 0, tzinfo=UTC)


class TestMergeToolRegistration:
    """Test merge tool registration and schema."""

    @pytest.fixture
    def mcp_server(self):
        from typing import Any

        mcp: Any = FastMCP("TestServer")
        register_journal_tools(mcp)
        return mcp

    @pytest.mark.asyncio
    async def test_merge_journals_tool_registration(self, mcp_server):
        """Test that merge_journals tool is registered with correct schema."""
        async with Client(mcp_server) as client:
            tools_response = await client.list_tools()
            tools = (
                tools_response.tools
                if hasattr(tools_response, "tools")
                else tools_response
            )

            merge_tool = next((t for t in tools if t.name == "merge_journals"), None)
            assert merge_tool is not None, "merge_journals tool not found"
            assert merge_tool.description is not None
            assert "merge" in merge_tool.description.lower()
            assert merge_tool.input_schema is not None

            properties = merge_tool.input_schema.get("properties", {})
            assert "target_journal_id" in properties
            assert "merge_data" in properties
            assert properties["merge_data"]["type"] == "string"

    @pytest.mark.asyncio
    async def test_get_merge_candidates_tool_registration(self, mcp_server):
        """Test that get_merge_candidates tool is registered with correct schema."""
        async with Client(mcp_server) as client:
            tools_response = await client.list_tools()
            tools = (
                tools_response.tools
                if hasattr(tools_response, "tools")
                else tools_response
            )

            candidates_tool = next(
                (t for t in tools if t.name == "get_merge_candidates"), None
            )
            assert candidates_tool is not None, "get_merge_candidates tool not found"
            assert candidates_tool.description is not None
            assert candidates_tool.input_schema is not None

            properties = candidates_tool.input_schema.get("properties", {})
            assert "journal_id" in properties
            assert "limit" in properties


class TestReviewItemToolSchemas:
    """The review queue tools act for the authenticated user only."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tool_name", ["list_review_items", "dismiss_review_item"])
    async def test_no_argument_selects_whose_review_items(self, tool_name: str) -> None:
        mcp: FastMCP[None] = FastMCP("TestServer")
        register_journal_tools(mcp)

        async with Client(mcp) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}

        properties = tools[tool_name].input_schema.get("properties", {})
        assert "user_id_override" not in properties
        assert not any("user" in name for name in properties)


class TestMergeJournalMCPRequestSchema:
    """Test MergeJournalMCPRequest Pydantic schema validation."""

    def test_valid_request_parses_correctly(self):
        from app.mcp.domains.journals.schemas import MergeJournalMCPRequest

        data = {"source_journal_id": 42}
        request = MergeJournalMCPRequest.model_validate(data)
        assert request.source_journal_id == 42
        assert request.overrides is None

    def test_request_with_overrides_parses_correctly(self):
        from app.mcp.domains.journals.schemas import MergeJournalMCPRequest

        data = {
            "source_journal_id": 42,
            "overrides": {
                "title": "Merged title",
                "content": "Merged content",
                "type_data": {"MOOD_RATING": {"mood_value": 8}},
            },
        }
        request = MergeJournalMCPRequest.model_validate(data)
        assert request.source_journal_id == 42
        assert request.overrides is not None
        assert request.overrides["title"] == "Merged title"
        assert request.overrides["type_data"]["MOOD_RATING"]["mood_value"] == 8

    def test_request_missing_source_journal_id_raises(self):
        from pydantic import ValidationError

        from app.mcp.domains.journals.schemas import MergeJournalMCPRequest

        with pytest.raises(ValidationError, match="source_journal_id"):
            MergeJournalMCPRequest.model_validate({})


class TestTagFilterResolution:
    """``_resolve_tag_filters`` turns the MCP ``tags`` string into tag ids."""

    @staticmethod
    def _tag_repo(
        *,
        by_name: dict[str, object] | None = None,
        descendants: list[object] | None = None,
    ) -> AsyncMock:
        repo = AsyncMock()
        lookup = by_name or {}
        repo.find_by_name.side_effect = lambda name: lookup.get(name.lower())
        repo.get_descendants_for_tags.return_value = descendants or []
        return repo

    @pytest.mark.asyncio
    async def test_uuids_pass_through(self) -> None:
        tag_id = uuid4()
        repo = self._tag_repo()

        assert await _resolve_tag_filters(str(tag_id), repo) == [str(tag_id)]
        repo.find_by_name.assert_not_called()

    @pytest.mark.asyncio
    async def test_names_are_resolved_to_ids(self) -> None:
        tag_id = uuid4()
        repo = self._tag_repo(by_name={"hiking": MagicMock(id=tag_id)})

        assert await _resolve_tag_filters("Hiking", repo) == [str(tag_id)]

    @pytest.mark.asyncio
    async def test_descendant_tags_are_included(self) -> None:
        parent_id, child_id = uuid4(), uuid4()
        repo = self._tag_repo(
            by_name={"outdoors": MagicMock(id=parent_id)},
            descendants=[MagicMock(id=child_id)],
        )

        resolved = await _resolve_tag_filters("outdoors", repo)

        assert resolved is not None
        assert set(resolved) == {str(parent_id), str(child_id)}

    @pytest.mark.asyncio
    async def test_unknown_name_is_an_error_not_a_silent_empty_filter(self) -> None:
        """Dropping an unresolvable tag would widen the search without saying so."""
        repo = self._tag_repo()

        with pytest.raises(ValueError, match="nonexistent-tag"):
            await _resolve_tag_filters("nonexistent-tag", repo)

    @pytest.mark.asyncio
    async def test_blank_input_means_no_filter(self) -> None:
        repo = self._tag_repo()

        assert await _resolve_tag_filters(None, repo) is None
        assert await _resolve_tag_filters("  , ", repo) is None
