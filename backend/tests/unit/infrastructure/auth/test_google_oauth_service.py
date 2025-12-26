"""
Unit tests for Google OAuth service integration.

Tests the Google OAuth provider configuration and integration-specific OAuth flows.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException, Request

from app.infrastructure.auth.oauth_service import OAuthService
from app.infrastructure.config import Settings


@pytest.fixture
def google_oauth_settings():
    """Create test settings with Google OAuth configured."""
    return Settings(
        debug=True,
        database_url="postgresql://test:test@localhost:5432/test",
        session_secret_key="test-session-secret",
        allowed_hosts=["*"],
        google_client_id="test_google_client_id",
        google_client_secret="test_google_client_secret",
        google_encryption_key="test_encryption_key_32_chars_long",
        frontend_url="http://localhost:3000",
    )


@pytest.fixture
def oauth_service(google_oauth_settings):
    """Create OAuth service with Google provider configured."""
    return OAuthService(google_oauth_settings)


@pytest.fixture
def mock_request():
    """Create mock FastAPI request."""
    request = Mock(spec=Request)
    request.session = {}
    request.url = Mock()
    request.url.scheme = "http"
    request.url.hostname = "localhost"
    request.url.port = 8000
    return request


class TestGoogleOAuthProvider:
    """Test Google OAuth provider configuration."""

    def test_google_provider_configured_when_credentials_present(self, oauth_service):
        """Test that Google provider is configured when credentials are present."""
        available_providers = oauth_service.get_available_providers()
        assert "google" in available_providers

    def test_google_provider_not_configured_when_credentials_missing(self):
        """Test that Google provider is not configured when credentials are missing."""
        settings = Settings(
            debug=True,
            database_url="postgresql://test:test@localhost:5432/test",
            session_secret_key="test-session-secret",
            allowed_hosts=["*"],
            # No Google credentials
        )
        oauth_service = OAuthService(settings)
        available_providers = oauth_service.get_available_providers()
        assert "google" not in available_providers

    async def test_get_google_authorization_url_success(
        self, oauth_service, mock_request
    ):
        """Test getting Google authorization URL for integration."""
        redirect_uri = "http://localhost:3000/integrations/google/callback"

        auth_url = await oauth_service.get_authorization_url(
            mock_request, "google", redirect_uri
        )

        # Google OAuth uses the v2 endpoint
        assert auth_url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
        assert "oauth_csrf_token" in mock_request.session
        assert "oauth_code_verifier" in mock_request.session

    async def test_get_google_authorization_url_with_contacts_scope(
        self, oauth_service, mock_request
    ):
        """Test getting Google authorization URL with contacts scope."""
        redirect_uri = "http://localhost:3000/integrations/google/callback"

        # Test with contacts scope for integration
        auth_url = await oauth_service.get_google_contacts_authorization_url(
            mock_request, redirect_uri
        )

        # Google OAuth uses the v2 endpoint
        assert auth_url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
        # Verify contacts scope is included in the URL (check for the scope in the URL)
        assert "contacts.readonly" in auth_url
        assert "oauth_csrf_token" in mock_request.session
        assert "oauth_code_verifier" in mock_request.session

    async def test_get_authorization_url_invalid_provider(
        self, oauth_service, mock_request
    ):
        """Test getting authorization URL for invalid provider raises exception."""
        with pytest.raises(HTTPException) as exc_info:
            await oauth_service.get_authorization_url(
                mock_request, "invalid_provider", "http://localhost:3000/callback"
            )

        assert exc_info.value.status_code == 400
        assert "not configured" in str(exc_info.value.detail)


class TestGoogleOAuthCallback:
    """Test Google OAuth callback handling."""

    async def test_handle_google_callback_success(self, oauth_service, mock_request):
        """Test successful Google OAuth callback handling."""
        import base64
        import json

        # Create properly encoded state
        csrf_token = "test_csrf_token"
        state_data = {
            "provider": "google",
            "redirect_uri": "http://localhost:3000/callback",
            "csrf_token": csrf_token,
            "flow_type": "integration",
        }
        state_json = json.dumps(state_data)
        encoded_state = base64.urlsafe_b64encode(state_json.encode()).decode()

        mock_request.session = {
            "oauth_csrf_token": csrf_token,
            "oauth_code_verifier": "test_code_verifier",
        }

        # Mock the Google OAuth client
        mock_client = Mock()
        mock_token = {
            "access_token": "test_access_token",
            "refresh_token": "test_refresh_token",
            "expires_in": 3600,
            "scope": "https://www.googleapis.com/auth/contacts.readonly email profile",
        }
        mock_client.authorize_access_token = AsyncMock(return_value=mock_token)

        # Patch the _clients dictionary
        with patch.dict(oauth_service.oauth._clients, {"google": mock_client}):
            token_data = await oauth_service.handle_google_contacts_callback(
                mock_request,
                "test_code",
                encoded_state,
                "http://localhost:3000/callback",
            )

            assert token_data["access_token"] == "test_access_token"
            assert token_data["refresh_token"] == "test_refresh_token"
            assert token_data["expires_in"] == 3600

    async def test_handle_google_callback_invalid_state(
        self, oauth_service, mock_request
    ):
        """Test Google OAuth callback with invalid state raises exception."""
        mock_request.session = {"oauth_state": "valid_state"}

        with pytest.raises(HTTPException) as exc_info:
            await oauth_service.handle_google_contacts_callback(
                mock_request,
                "test_code",
                "invalid_state",
                "http://localhost:3000/callback",
            )

        assert exc_info.value.status_code == 400
        assert "Invalid state parameter" in str(exc_info.value.detail)

    async def test_handle_google_callback_missing_state(
        self, oauth_service, mock_request
    ):
        """Test Google OAuth callback with missing state raises exception."""
        mock_request.session = {}  # No oauth_state in session

        with pytest.raises(HTTPException) as exc_info:
            await oauth_service.handle_google_contacts_callback(
                mock_request,
                "test_code",
                "test_state",
                "http://localhost:3000/callback",
            )

        assert exc_info.value.status_code == 400
        assert "Invalid state parameter" in str(exc_info.value.detail)

    async def test_handle_google_callback_missing_code_verifier(
        self, oauth_service, mock_request
    ):
        """Test Google OAuth callback with missing code verifier raises exception."""
        import base64
        import json

        # Create properly encoded state
        csrf_token = "test_csrf_token"
        state_data = {
            "provider": "google",
            "redirect_uri": "http://localhost:3000/callback",
            "csrf_token": csrf_token,
            "flow_type": "integration",
        }
        state_json = json.dumps(state_data)
        encoded_state = base64.urlsafe_b64encode(state_json.encode()).decode()

        mock_request.session = {"oauth_csrf_token": csrf_token}  # No code_verifier

        with pytest.raises(HTTPException) as exc_info:
            await oauth_service.handle_google_contacts_callback(
                mock_request,
                "test_code",
                encoded_state,
                "http://localhost:3000/callback",
            )

        assert exc_info.value.status_code == 400
        assert "Missing code verifier" in str(exc_info.value.detail)
