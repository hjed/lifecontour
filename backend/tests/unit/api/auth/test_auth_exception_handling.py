"""
Unit tests for auth provider exception handling.

Tests that auth providers properly raise domain exceptions. Session-cookie
authentication is resolved in ``get_auth_context``; ``get_current_user`` simply
unwraps it.
"""

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.infrastructure.auth.models import SessionUser
from app.infrastructure.config import Settings
from app.infrastructure.di.auth import AuthContext, AuthProvider

_VALID_SESSION = {
    "id": "12345",
    "email": "test@example.com",
    "name": "Test User",
    "avatar_url": "https://example.com/avatar.jpg",
    "provider": "github",
    "authenticated_at": datetime.now(UTC).isoformat(),
}


def _request(session: dict[str, object]) -> Mock:
    """Mock request with the given session and no Authorization header."""
    request = Mock()
    request.session = session
    request.headers = {}
    return request


def _settings() -> Mock:
    settings = Mock(spec=Settings)
    settings.disable_auth = False
    settings.oauth_enforce_scopes = True
    return settings


class TestAuthProviderExceptionHandling:
    """Test that auth providers properly raise domain exceptions."""

    async def test_auth_context_with_valid_session(self) -> None:
        """get_auth_context resolves a SessionUser from a valid session."""
        auth_provider = AuthProvider()

        context = await auth_provider.get_auth_context(
            _request({"user": _VALID_SESSION}), _settings(), verifier=None
        )

        assert isinstance(context, AuthContext)
        assert context.user.id == "12345"
        assert context.user.email == "test@example.com"
        assert context.user.provider == "github"
        # get_current_user unwraps the context's user.
        assert auth_provider.get_current_user(context) is context.user

    async def test_auth_context_with_no_session(self) -> None:
        """get_auth_context raises HTTP 401 when no session is present."""
        auth_provider = AuthProvider()

        with pytest.raises(HTTPException) as exc_info:
            await auth_provider.get_auth_context(
                _request({}), _settings(), verifier=None
            )

        assert exc_info.value.status_code == 401
        assert "Authentication required" in str(exc_info.value.detail)

    async def test_auth_context_with_invalid_session(self) -> None:
        """get_auth_context raises HTTP 401 for malformed session data."""
        auth_provider = AuthProvider()

        with pytest.raises(HTTPException) as exc_info:
            await auth_provider.get_auth_context(
                _request({"user": "invalid_data"}), _settings(), verifier=None
            )

        assert exc_info.value.status_code == 401

    async def test_get_optional_user_with_no_session(self) -> None:
        """get_optional_user returns None when no session is present."""
        auth_provider = AuthProvider()

        result = await auth_provider.get_optional_user(
            _request({}), _settings(), verifier=None
        )
        assert result is None

    async def test_get_optional_user_with_valid_session(self) -> None:
        """get_optional_user returns the SessionUser for a valid session."""
        auth_provider = AuthProvider()

        result = await auth_provider.get_optional_user(
            _request({"user": _VALID_SESSION}), _settings(), verifier=None
        )
        assert isinstance(result, SessionUser)
        assert result.id == "12345"

    async def test_get_optional_user_with_invalid_session(self) -> None:
        """get_optional_user returns None for malformed session data."""
        auth_provider = AuthProvider()

        result = await auth_provider.get_optional_user(
            _request({"user": "invalid_data"}), _settings(), verifier=None
        )
        assert result is None
