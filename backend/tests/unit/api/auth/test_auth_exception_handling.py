"""
Unit tests for auth controller exception handling.

Tests that domain exceptions are properly raised and handled by global handlers.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest

from app.api.auth.controllers import authorize, get_current_user_info
from app.infrastructure.auth.exceptions import (
    AuthenticationError,
    ProviderNotConfiguredError,
)
from app.infrastructure.auth.models import SessionUser


class TestAuthExceptionHandling:
    """Test that auth controllers properly raise domain exceptions."""

    async def test_get_current_user_info_raises_authentication_error(self):
        """Test that get_current_user_info raises AuthenticationError for unauthenticated users."""
        # Test with None user (unauthenticated)
        with pytest.raises(AuthenticationError) as exc_info:
            await get_current_user_info(user=None)

        assert str(exc_info.value) == "Not authenticated"

    async def test_get_current_user_info_success_with_authenticated_user(self):
        """Test that get_current_user_info works correctly with authenticated user."""
        # Create a mock authenticated user
        user = SessionUser(
            id="12345",
            email="test@example.com",
            name="Test User",
            avatar_url="https://example.com/avatar.jpg",
            provider="github",
            authenticated_at=datetime.now(UTC),
        )

        # Should not raise any exception
        response = await get_current_user_info(user=user)

        assert response.id == "12345"
        assert response.email == "test@example.com"
        assert response.name == "Test User"
        assert response.provider == "github"

    async def test_authorize_lets_domain_exceptions_bubble_up(self):
        """Test that authorize endpoint lets domain exceptions bubble up."""
        # Create mock request and oauth service
        mock_request = Mock()
        mock_request.session = {}
        mock_request.url_for.return_value = "http://localhost/callback/github"

        # Mock oauth service that raises ProviderNotConfiguredError
        mock_oauth_service = Mock()
        mock_oauth_service.get_authorization_url = AsyncMock(
            side_effect=ProviderNotConfiguredError("github")
        )

        # The authorize function should let the exception bubble up
        with pytest.raises(ProviderNotConfiguredError) as exc_info:
            await authorize(
                provider="github",
                request=mock_request,
                oauth_service=mock_oauth_service,
                redirect_url="/",
            )

        assert "github" in str(exc_info.value)

    async def test_authorize_success_flow(self):
        """Test that authorize endpoint works correctly in success case."""
        # Create mock request and oauth service
        mock_request = Mock()
        mock_request.session = {}
        mock_request.url_for.return_value = "http://localhost/callback/github"

        # Mock oauth service that returns authorization URL
        mock_oauth_service = Mock()
        mock_oauth_service.get_authorization_url = AsyncMock(
            return_value="https://github.com/login/oauth/authorize?client_id=test"
        )

        # Should return RedirectResponse
        response = await authorize(
            provider="github",
            request=mock_request,
            oauth_service=mock_oauth_service,
            redirect_url="/dashboard",
        )

        # Check that session was updated
        assert mock_request.session["post_auth_redirect"] == "/dashboard"

        # Check that it's a redirect response
        assert response.status_code == 307
        assert "github.com" in response.headers["location"]
