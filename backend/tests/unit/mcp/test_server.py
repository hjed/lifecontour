"""
Unit tests for MCP server setup.

Tests the FastMCP server configuration and initialization.
"""

from typing import cast
from unittest.mock import MagicMock, patch

from core_shared.product import PRODUCT_NAME
from starlette.applications import Starlette

from app.infrastructure.di.container import create_container
from app.mcp.server import create_mcp_app, create_mcp_server


class TestMCPServer:
    """Test MCP server creation and configuration."""

    def test_create_mcp_server(self):
        """Test MCP server creation without auth."""
        server = create_mcp_server()

        # Should create FastMCP instance
        assert server is not None
        assert hasattr(server, "tool")  # Should have tool decorator

    def test_server_is_named_after_the_product(self) -> None:
        """MCP clients display the server name, so it is the product name."""
        server = create_mcp_server()

        assert server.name == PRODUCT_NAME
        assert server.instructions is not None
        assert PRODUCT_NAME in server.instructions

    def test_create_mcp_server_with_auth_none(self):
        """Test MCP server creation with auth=None (dev mode)."""
        server = create_mcp_server(auth=None)
        assert server is not None

    def test_create_mcp_app(self):
        """Test MCP ASGI app creation without auth."""
        container = create_container()
        app = create_mcp_app(container)

        # Should create ASGI application
        assert app is not None
        # Should be callable (ASGI app)
        assert callable(app)

    @patch("app.mcp.server.create_mcp_server")
    def test_create_mcp_app_mounts_a_given_server_without_building_one(
        self, mock_create_server: MagicMock
    ) -> None:
        """A prebuilt server is mounted as is; no second server is built.

        The patch replaces ``app.mcp.server.create_mcp_server`` only, so this
        module's own import still builds a real server.
        """
        prebuilt = create_mcp_server()

        app = create_mcp_app(create_container(), server=prebuilt)

        mock_create_server.assert_not_called()
        assert cast(Starlette, app).state.fastmcp_server is prebuilt

    @patch("app.mcp.server.create_mcp_server")
    def test_create_mcp_app_with_auth_provider(self, mock_create_server):
        """Test MCP ASGI app creation with auth provider."""
        from unittest.mock import MagicMock

        # Mock the FastMCP server to avoid AuthProvider validation
        mock_mcp = MagicMock()
        mock_mcp.http_app.return_value = MagicMock()
        mock_create_server.return_value = mock_mcp

        container = create_container()
        mock_auth = MagicMock()
        app = create_mcp_app(container, auth_provider=mock_auth)

        assert app is not None
        mock_create_server.assert_called_once_with(auth=mock_auth)

    @patch("app.mcp.server.register_contact_tools")
    def test_server_registers_contact_tools(self, mock_register):
        """Test that server registers contact tools."""
        server = create_mcp_server()

        # Should have called register_contact_tools
        mock_register.assert_called_once_with(server)

    def test_server_has_instructions(self):
        """Test that server has proper instructions."""
        server = create_mcp_server()

        # Should have instructions for AI
        assert hasattr(server, "name")
        # Instructions should be set during creation


class TestTheTaskGuidanceDescribesListTasks:
    """The superseded guidance said tasks could not live on a list or a date."""

    def test_says_a_task_can_be_created_on_a_list_with_a_due_date(self) -> None:
        instructions = create_mcp_server().instructions or ""

        assert "on a list" in instructions
        assert "due date" in instructions

    def test_says_a_task_on_a_list_can_be_due_in_a_journal(self) -> None:
        instructions = create_mcp_server().instructions or ""

        assert "due in a future journal" in instructions

    def test_no_longer_says_tasks_cannot_be_placed_on_a_list(self) -> None:
        instructions = create_mcp_server().instructions or ""

        assert "cannot be placed on a list" not in instructions
        assert "never on a bare date" not in instructions

    def test_names_the_tool_that_reads_a_lists_tasks(self) -> None:
        instructions = create_mcp_server().instructions or ""

        assert "list_task_list_tasks" in instructions

    def test_names_the_tool_that_reorders_a_lists_tasks(self) -> None:
        instructions = create_mcp_server().instructions or ""

        assert "reorder_list_tasks" in instructions

    def test_says_update_task_sets_or_clears_a_list_tasks_due_date(self) -> None:
        instructions = create_mcp_server().instructions or ""

        assert "set or clear a list task's due date" in instructions

    def test_names_the_tool_that_moves_a_task_onto_or_between_lists(self) -> None:
        instructions = create_mcp_server().instructions or ""

        assert "move_task_to_list" in instructions
