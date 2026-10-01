"""
Unit tests for MCP server setup.

Tests the FastMCP server configuration and initialization.
"""

from unittest.mock import patch

from core_shared.product import PRODUCT_NAME

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
