"""
Unit tests for integration domain MCP tools.

Tests tool registration and basic structure.
Full functionality is tested in integration tests.
"""

import pytest
from fastmcp import Client, FastMCP

from app.mcp.domains.integrations.tools import register_integration_tools


class TestIntegrationTools:
    """Test integration MCP tools registration and functionality."""

    @pytest.fixture
    def mcp_server(self):
        """Create FastMCP server for testing."""
        from typing import Any

        mcp: Any = FastMCP("TestServer")
        register_integration_tools(mcp)
        return mcp

    def test_register_integration_tools(self, mcp_server):
        """Test that integration tools are registered successfully."""
        assert mcp_server is not None

    @pytest.mark.asyncio
    async def test_list_integrations_tool_registered(self, mcp_server):
        """Test that list_integrations tool is registered."""
        async with Client(mcp_server) as client:
            tools_response = await client.list_tools()

            if hasattr(tools_response, "tools"):
                tools = tools_response.tools
            else:
                tools = tools_response

            tool_names = [tool.name for tool in tools]
            assert "list_integrations" in tool_names, (
                "list_integrations tool not found in registered tools"
            )
            assert "trigger_sync" in tool_names, (
                "trigger_sync tool not found in registered tools"
            )
            assert "get_strava_athlete_mappings" in tool_names, (
                "get_strava_athlete_mappings tool not found in registered tools"
            )

    @pytest.mark.asyncio
    async def test_list_integrations_tool_description(self, mcp_server):
        """Test that list_integrations tool has a descriptive description."""
        async with Client(mcp_server) as client:
            tools_response = await client.list_tools()

            if hasattr(tools_response, "tools"):
                tools = tools_response.tools
            else:
                tools = tools_response

            tool = next((t for t in tools if t.name == "list_integrations"), None)
            assert tool is not None
            assert tool.description is not None

            # Should mention key concepts for AI understanding
            desc = tool.description.lower()
            assert "integration" in desc
            assert "status" in desc

    @pytest.mark.asyncio
    async def test_list_integrations_tool_has_no_required_inputs(self, mcp_server):
        """Test that list_integrations doesn't require any user inputs.

        All parameters (user_id, connection, registry_service) are injected
        via DI/depends, so there should be no required user-facing inputs.
        """
        async with Client(mcp_server) as client:
            tools_response = await client.list_tools()

            if hasattr(tools_response, "tools"):
                tools = tools_response.tools
            else:
                tools = tools_response

            tool = next((t for t in tools if t.name == "list_integrations"), None)
            assert tool is not None
            assert tool.input_schema is not None

            # DI-injected params should not appear as required user inputs
            required = tool.input_schema.get("required", [])
            assert "user_id" not in required
            assert "connection" not in required
            assert "registry_service" not in required

    @pytest.mark.asyncio
    async def test_trigger_sync_tool_has_required_inputs(self, mcp_server):
        """Test that trigger_sync has required inputs."""
        async with Client(mcp_server) as client:
            tools_response = await client.list_tools()

            if hasattr(tools_response, "tools"):
                tools = tools_response.tools
            else:
                tools = tools_response

            tool = next((t for t in tools if t.name == "trigger_sync"), None)
            assert tool is not None
            assert tool.input_schema is not None

            required = tool.input_schema.get("required", [])
            assert "integration_id" in required
            assert "user_id" not in required
            assert "task_queue_service" not in required

    @pytest.mark.asyncio
    async def test_get_strava_athlete_mappings_tool_inputs(self, mcp_server):
        """Test that get_strava_athlete_mappings has optional inputs."""
        async with Client(mcp_server) as client:
            tools_response = await client.list_tools()

            if hasattr(tools_response, "tools"):
                tools = tools_response.tools
            else:
                tools = tools_response

            tool = next(
                (t for t in tools if t.name == "get_strava_athlete_mappings"), None
            )
            assert tool is not None
            assert tool.input_schema is not None

            required = tool.input_schema.get("required", [])
            assert "user_id" not in required
            assert "mapping_service" not in required
            assert "contact_id" not in required
            assert "strava_athlete_id" not in required

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("tool_name", "fields"),
        [
            ("list_integrations", {"integrations", "total_count", "summary"}),
            ("trigger_sync", {"integration_id", "job_id", "status"}),
            ("get_strava_athlete_mappings", {"mappings", "total_count"}),
            ("list_immich_conflicts", {"conflicts", "total_count"}),
            (
                "resolve_immich_conflict",
                {"conflict_id", "action", "contact_id", "status"},
            ),
            (
                "search_immich_photos_for_journal",
                {"journal_id", "photos", "total_count"},
            ),
            (
                "create_immich_album_for_journal",
                {"journal_id", "album_id", "asset_count", "shared_link_url", "status"},
            ),
        ],
    )
    async def test_tool_publishes_its_result_shape(
        self, mcp_server: FastMCP[None], tool_name: str, fields: set[str]
    ) -> None:
        """A client learns the result's fields from the outputSchema."""
        async with Client(mcp_server) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}

        schema = tools[tool_name].output_schema
        assert schema is not None
        assert set(schema["properties"]) == fields

    @pytest.mark.asyncio
    async def test_integration_status_is_an_enumerated_value(
        self, mcp_server: FastMCP[None]
    ) -> None:
        """The status a client branches on is a closed set, and says so."""
        async with Client(mcp_server) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}

        schema = tools["list_integrations"].output_schema
        assert schema is not None
        integration = schema["properties"]["integrations"]["items"]
        assert "connected" in integration["properties"]["status"]["enum"]
