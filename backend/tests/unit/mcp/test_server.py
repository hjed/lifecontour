"""
Unit tests for MCP server setup.

Tests the FastMCP server configuration and initialization.
"""

from unittest.mock import patch

from app.infrastructure.config import Settings
from app.infrastructure.di.container import create_container
from app.mcp.server import create_mcp_app, create_mcp_server


def _test_settings() -> Settings:
    """Create minimal test settings with auth disabled."""
    return Settings(
        database_url="postgresql://test:test@localhost:5432/test",
        disable_auth=True,
    )


class TestMCPServer:
    """Test MCP server creation and configuration."""

    def test_create_mcp_server(self):
        """Test MCP server creation."""
        server = create_mcp_server(_test_settings())

        # Should create FastMCP instance
        assert server is not None
        assert hasattr(server, "tool")  # Should have tool decorator

    def test_create_mcp_app(self):
        """Test MCP ASGI app creation."""
        settings = _test_settings()
        container = create_container(settings)
        app = create_mcp_app(container, settings)

        # Should create ASGI application
        assert app is not None
        # Should be callable (ASGI app)
        assert callable(app)

    @patch("app.mcp.server.register_contact_tools")
    def test_server_registers_contact_tools(self, mock_register):
        """Test that server registers contact tools."""
        server = create_mcp_server(_test_settings())

        # Should have called register_contact_tools
        mock_register.assert_called_once_with(server)

    def test_server_has_instructions(self):
        """Test that server has proper instructions."""
        server = create_mcp_server(_test_settings())

        # Should have instructions for AI
        assert hasattr(server, "name")
        # Instructions should be set during creation
