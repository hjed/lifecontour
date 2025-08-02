"""
Unit tests for auth provider exception handling.

Tests that auth providers properly raise domain exceptions.
"""

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.infrastructure.auth.models import SessionUser
from app.infrastructure.config import Settings
from app.infrastructure.di.auth import AuthProvider


class TestAuthProviderExceptionHandling:
    """Test that auth providers properly raise domain exceptions."""

    def test_auth_provider_get_current_user_with_valid_session(self):
        """Test that auth provider works correctly with valid session."""
        # Create mock request with valid session data
        user_data = {
            "id": "12345",
            "email": "test@example.com",
            "name": "Test User",
            "avatar_url": "https://example.com/avatar.jpg",
            "provider": "github",
            "authenticated_at": datetime.now(UTC).isoformat(),
        }
        mock_request = Mock()
        mock_request.session = {"user": user_data}

        # Create mock settings with auth enabled
        mock_settings = Mock(spec=Settings)
        mock_settings.disable_auth = False

        auth_provider = AuthProvider()

        # Should return valid SessionUser
        result = auth_provider.get_current_user(mock_request, mock_settings)
        assert isinstance(result, SessionUser)
        assert result.id == "12345"
        assert result.email == "test@example.com"
        assert result.name == "Test User"
        assert result.provider == "github"

    def test_auth_provider_get_current_user_with_no_session(self):
        """Test that auth provider raises HTTPException for no session."""
        # Create mock request with no session data
        mock_request = Mock()
        mock_request.session = {}

        # Create mock settings with auth enabled
        mock_settings = Mock(spec=Settings)
        mock_settings.disable_auth = False

        auth_provider = AuthProvider()

        # Should raise HTTPException for no session
        with pytest.raises(HTTPException) as exc_info:
            auth_provider.get_current_user(mock_request, mock_settings)

        assert exc_info.value.status_code == 401
        assert "Authentication required" in str(exc_info.value.detail)

    def test_auth_provider_get_current_user_with_invalid_session(self):
        """Test that auth provider raises HTTPException for invalid session."""
        # Create mock request with invalid session data
        mock_request = Mock()
        mock_request.session = {"user": "invalid_data"}

        # Create mock settings with auth enabled
        mock_settings = Mock(spec=Settings)
        mock_settings.disable_auth = False

        auth_provider = AuthProvider()

        # Should raise HTTPException for invalid session data
        with pytest.raises(HTTPException) as exc_info:
            auth_provider.get_current_user(mock_request, mock_settings)

        assert exc_info.value.status_code == 401

    def test_auth_provider_get_optional_user_with_no_session(self):
        """Test that auth provider returns None for no session."""
        # Create mock request with no session data
        mock_request = Mock()
        mock_request.session = {}

        # Create mock settings with auth enabled
        mock_settings = Mock(spec=Settings)
        mock_settings.disable_auth = False

        auth_provider = AuthProvider()

        # Should return None for no session
        result = auth_provider.get_optional_user(mock_request, mock_settings)
        assert result is None

    def test_auth_provider_get_optional_user_with_valid_session(self):
        """Test that auth provider returns SessionUser for valid session."""
        # Create mock request with valid session data
        user_data = {
            "id": "12345",
            "email": "test@example.com",
            "name": "Test User",
            "avatar_url": "https://example.com/avatar.jpg",
            "provider": "github",
            "authenticated_at": datetime.now(UTC).isoformat(),
        }
        mock_request = Mock()
        mock_request.session = {"user": user_data}

        # Create mock settings with auth enabled
        mock_settings = Mock(spec=Settings)
        mock_settings.disable_auth = False

        auth_provider = AuthProvider()

        # Should return valid SessionUser
        result = auth_provider.get_optional_user(mock_request, mock_settings)
        assert isinstance(result, SessionUser)
        assert result.id == "12345"

    def test_auth_provider_get_optional_user_with_invalid_session(self):
        """Test that auth provider returns None for invalid session."""
        # Create mock request with invalid session data
        mock_request = Mock()
        mock_request.session = {"user": "invalid_data"}

        # Create mock settings with auth enabled
        mock_settings = Mock(spec=Settings)
        mock_settings.disable_auth = False

        auth_provider = AuthProvider()

        # Should return None for invalid session (graceful handling)
        result = auth_provider.get_optional_user(mock_request, mock_settings)
        assert result is None
