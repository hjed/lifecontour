"""
Unit tests for MCP session authentication.

Tests the session-based authentication integration for MCP tools.
"""

from unittest.mock import Mock

import pytest
from starlette.requests import Request
from starlette.responses import Response

from app.mcp.auth.session_auth import SessionAuthMiddleware


class TestSessionAuthMiddleware:
    """Test SessionAuthMiddleware for MCP authentication."""

    @pytest.fixture
    def mock_request(self):
        """Create a mock request for testing."""
        request = Mock(spec=Request)
        request.session = {}
        request.url = Mock()
        request.url.path = "/mcp-server/mcp"
        return request

    @pytest.fixture
    def mock_call_next(self):
        """Create a mock call_next function."""

        async def call_next(request):
            return Response("OK", status_code=200)

        return call_next

    @pytest.fixture
    def middleware(self):
        """Create SessionAuthMiddleware instance."""
        return SessionAuthMiddleware(Mock())

    @pytest.mark.asyncio
    async def test_valid_session_passes_through(
        self, middleware, mock_request, mock_call_next
    ):
        """Test that valid session allows request to pass through."""
        # Setup valid session
        mock_request.session = {
            "user": {
                "id": "user-123",
                "email": "test@example.com",
                "name": "Test User",
                "provider": "github",
            }
        }

        # Process request
        response = await middleware.dispatch(mock_request, mock_call_next)

        # Should pass through successfully
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_missing_session_returns_401(
        self, middleware, mock_request, mock_call_next
    ):
        """Test that missing session returns 401."""
        # Setup request with no session
        mock_request.session = {}

        # Process request
        response = await middleware.dispatch(mock_request, mock_call_next)

        # Should return 401
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_session_returns_401(
        self, middleware, mock_request, mock_call_next
    ):
        """Test that invalid session returns 401."""
        # Setup request with invalid session (missing required fields)
        mock_request.session = {
            "user": {
                "id": "user-123"
                # Missing email, name, provider
            }
        }

        # Process request
        response = await middleware.dispatch(mock_request, mock_call_next)

        # Should return 401
        assert response.status_code == 401

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "path",
        ["/mcp", "/api/contacts"],
        ids=["mcp-path", "non-mcp-path"],
    )
    async def test_all_paths_enforce_auth(self, middleware, mock_call_next, path):
        """Test that auth is enforced for any path reaching the middleware.

        Since the middleware is exclusively mounted on the MCP sub-app,
        all requests reaching it are MCP requests regardless of path.
        """
        mock_request = Mock(spec=Request)
        mock_request.url = Mock()
        mock_request.url.path = path
        mock_request.session = {}  # No session

        response = await middleware.dispatch(mock_request, mock_call_next)

        # Should return 401 — auth is always enforced
        assert response.status_code == 401
