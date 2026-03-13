"""
Unit tests for OAuth service.

Tests OAuth provider configuration and user information extraction.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException

from app.infrastructure.auth.models import OAuthUserInfo
from app.infrastructure.auth.oauth_service import OAuthService
from app.infrastructure.config import Settings


class TestOAuthService:
    """Test OAuth service functionality."""

    def test_oauth_service_initialization_no_providers(self):
        """Test OAuth service initialization with no providers configured."""
        settings = Settings()
        oauth_service = OAuthService(settings)

        assert oauth_service.get_available_providers() == []

    def test_oauth_service_initialization_with_github(self):
        """Test OAuth service initialization with GitHub provider."""
        settings = Settings(
            github_client_id="test_client_id", github_client_secret="test_client_secret"
        )
        oauth_service = OAuthService(settings)

        providers = oauth_service.get_available_providers()
        assert "github" in providers

    def test_oauth_service_initialization_with_microsoft(self):
        """Test OAuth service initialization with Microsoft provider."""
        settings = Settings(
            microsoft_client_id="test_client_id",
            microsoft_client_secret="test_client_secret",
        )
        oauth_service = OAuthService(settings)

        providers = oauth_service.get_available_providers()
        assert "microsoft" in providers

    def test_oauth_service_initialization_with_discord(self):
        """Test OAuth service initialization with Discord provider."""
        settings = Settings(
            discord_client_id="test_client_id",
            discord_client_secret="test_client_secret",
        )
        oauth_service = OAuthService(settings)

        providers = oauth_service.get_available_providers()
        assert "discord" in providers

    def test_oauth_service_initialization_with_generic_provider(self):
        """Test OAuth service initialization with generic OAuth provider."""
        settings = Settings(
            oauth_provider_name="custom",
            oauth_client_id="test_client_id",
            oauth_client_secret="test_client_secret",
            oauth_authorization_url="https://example.com/oauth/authorize",
            oauth_token_url="https://example.com/oauth/token",
            oauth_userinfo_url="https://example.com/oauth/userinfo",
        )
        oauth_service = OAuthService(settings)

        providers = oauth_service.get_available_providers()
        assert "custom" in providers

    def test_oauth_service_initialization_with_all_providers(self):
        """Test OAuth service initialization with all providers configured."""
        settings = Settings(
            github_client_id="github_client_id",
            github_client_secret="github_client_secret",
            microsoft_client_id="microsoft_client_id",
            microsoft_client_secret="microsoft_client_secret",
            discord_client_id="discord_client_id",
            discord_client_secret="discord_client_secret",
            oauth_provider_name="custom",
            oauth_client_id="custom_client_id",
            oauth_client_secret="custom_client_secret",
            oauth_authorization_url="https://example.com/oauth/authorize",
            oauth_token_url="https://example.com/oauth/token",
            oauth_userinfo_url="https://example.com/oauth/userinfo",
        )
        oauth_service = OAuthService(settings)

        providers = oauth_service.get_available_providers()
        assert "github" in providers
        assert "microsoft" in providers
        assert "discord" in providers
        assert "custom" in providers
        assert len(providers) == 4

    async def test_get_github_user_info(self):
        """Test extracting user info from GitHub OAuth response."""
        settings = Settings(
            github_client_id="test_client_id", github_client_secret="test_client_secret"
        )
        oauth_service = OAuthService(settings)

        # Mock GitHub API responses
        mock_client = Mock()
        mock_user_response = Mock()
        mock_user_response.json.return_value = {
            "id": 12345,
            "login": "testuser",
            "name": "Test User",
            "email": "test@example.com",
            "avatar_url": "https://github.com/avatar.jpg",
        }
        mock_client.get = AsyncMock(return_value=mock_user_response)

        token = {"access_token": "test_token"}

        user_info = await oauth_service._get_github_user_info(mock_client, token)

        assert isinstance(user_info, OAuthUserInfo)
        assert user_info.id == "12345"
        assert user_info.email == "test@example.com"
        assert user_info.name == "Test User"
        assert user_info.avatar_url == "https://github.com/avatar.jpg"
        assert user_info.provider == "github"

    async def test_get_github_user_info_no_public_email(self):
        """Test extracting user info from GitHub when email is not public."""
        settings = Settings(
            github_client_id="test_client_id", github_client_secret="test_client_secret"
        )
        oauth_service = OAuthService(settings)

        # Mock GitHub API responses
        mock_client = Mock()
        mock_user_response = Mock()
        mock_user_response.json.return_value = {
            "id": 12345,
            "login": "testuser",
            "name": "Test User",
            "email": None,  # No public email
            "avatar_url": "https://github.com/avatar.jpg",
        }

        mock_email_response = Mock()
        mock_email_response.json.return_value = [
            {"email": "test@example.com", "primary": True, "verified": True},
            {"email": "other@example.com", "primary": False, "verified": True},
        ]

        mock_client.get = AsyncMock(
            side_effect=[mock_user_response, mock_email_response]
        )

        token = {"access_token": "test_token"}

        user_info = await oauth_service._get_github_user_info(mock_client, token)

        assert user_info.email == "test@example.com"  # Should get primary email

    async def test_get_microsoft_user_info(self):
        """Test extracting user info from Microsoft OAuth response."""
        settings = Settings(
            microsoft_client_id="test_client_id",
            microsoft_client_secret="test_client_secret",
        )
        oauth_service = OAuthService(settings)

        # Mock Microsoft Graph API response
        mock_client = Mock()
        mock_response = Mock()
        mock_response.json.return_value = {
            "id": "test-user-id",
            "displayName": "Test User",
            "mail": "test@example.com",
            "userPrincipalName": "test@example.onmicrosoft.com",
        }
        mock_client.get = AsyncMock(return_value=mock_response)

        token = {"access_token": "test_token"}

        user_info = await oauth_service._get_microsoft_user_info(mock_client, token)

        assert isinstance(user_info, OAuthUserInfo)
        assert user_info.id == "test-user-id"
        assert user_info.email == "test@example.com"
        assert user_info.name == "Test User"
        assert user_info.provider == "microsoft"

    async def test_get_discord_user_info(self):
        """Test extracting user info from Discord OAuth response."""
        settings = Settings(
            discord_client_id="test_client_id",
            discord_client_secret="test_client_secret",
        )
        oauth_service = OAuthService(settings)

        # Mock Discord API response
        mock_client = Mock()
        mock_response = Mock()
        mock_response.json.return_value = {
            "id": "123456789",
            "username": "testuser",
            "email": "test@example.com",
            "avatar": "avatar_hash",
        }
        mock_client.get = AsyncMock(return_value=mock_response)

        token = {"access_token": "test_token"}

        user_info = await oauth_service._get_discord_user_info(mock_client, token)

        assert isinstance(user_info, OAuthUserInfo)
        assert user_info.id == "123456789"
        assert user_info.email == "test@example.com"
        assert user_info.name == "testuser"
        assert (
            user_info.avatar_url
            == "https://cdn.discordapp.com/avatars/123456789/avatar_hash.png"
        )
        assert user_info.provider == "discord"

    def test_encode_decode_state(self):
        """Test encoding and decoding OAuth state."""
        settings = Settings()
        oauth_service = OAuthService(settings)

        provider = "github"
        redirect_uri = "http://localhost:3000/auth/callback"
        csrf_token = "test_csrf_token"

        # Test encoding
        encoded_state = oauth_service._encode_state(provider, redirect_uri, csrf_token)
        assert isinstance(encoded_state, str)
        assert len(encoded_state) > 0

        # Test decoding
        decoded_state = oauth_service._decode_state(encoded_state)
        assert decoded_state["provider"] == provider
        assert decoded_state["redirect_uri"] == redirect_uri
        assert decoded_state["csrf_token"] == csrf_token

    def test_decode_state_invalid(self):
        """Test decoding invalid OAuth state."""
        settings = Settings()
        oauth_service = OAuthService(settings)

        # Test with invalid base64
        with pytest.raises(HTTPException) as exc_info:
            oauth_service._decode_state("invalid_state")
        assert exc_info.value.status_code == 400

        # Test with valid base64 but invalid JSON
        import base64

        invalid_json = base64.urlsafe_b64encode(b"invalid json").decode()
        with pytest.raises(HTTPException) as exc_info:
            oauth_service._decode_state(invalid_json)
        assert exc_info.value.status_code == 400

    async def test_handle_callback_with_code_redirect_uri_mismatch(self):
        """Test that handle_callback_with_code validates redirect URI."""
        settings = Settings(
            github_client_id="test_client_id", github_client_secret="test_client_secret"
        )
        oauth_service = OAuthService(settings)

        # Create a mock request with session
        mock_request = Mock()
        mock_request.session = {"oauth_csrf_token": "test_csrf_token"}

        # Create state with one redirect URI
        original_redirect_uri = "http://localhost:3000/auth/callback"
        encoded_state = oauth_service._encode_state(
            "github", original_redirect_uri, "test_csrf_token"
        )

        # Try to use a different redirect URI in the callback
        different_redirect_uri = "http://malicious.com/callback"

        with pytest.raises(HTTPException) as exc_info:
            await oauth_service.handle_callback_with_code(
                mock_request,
                "github",
                "test_code",
                encoded_state,
                different_redirect_uri,
            )

        assert exc_info.value.status_code == 400
        assert "redirect URI mismatch" in str(exc_info.value.detail)

    async def test_get_authorization_url_generates_pkce_code_verifier(self):
        """Test that get_authorization_url generates and stores PKCE code verifier."""
        settings = Settings(
            github_client_id="test_client_id", github_client_secret="test_client_secret"
        )
        oauth_service = OAuthService(settings)

        # Create a mock request with session
        mock_request = Mock()
        mock_request.session = {}

        # Mock the OAuth client
        mock_client = Mock()
        mock_client.create_authorization_url = AsyncMock(
            return_value={
                "url": "https://github.com/login/oauth/authorize?code_challenge=test"
            }
        )
        oauth_service.oauth._clients = {"github": mock_client}  # type: ignore

        # Call get_authorization_url
        await oauth_service.get_authorization_url(
            mock_request, "github", "http://localhost:3000/auth/callback"
        )

        # Verify code verifier was generated and stored in session
        assert "oauth_code_verifier" in mock_request.session
        assert len(mock_request.session["oauth_code_verifier"]) > 0
        assert "oauth_csrf_token" in mock_request.session

        # Verify create_authorization_url was called with code_verifier
        mock_client.create_authorization_url.assert_called_once()
        call_args = mock_client.create_authorization_url.call_args
        assert "code_verifier" in call_args.kwargs
        assert (
            call_args.kwargs["code_verifier"]
            == mock_request.session["oauth_code_verifier"]
        )

    async def test_handle_callback_uses_pkce_code_verifier(self):
        """Test that handle_callback uses PKCE code verifier when available."""
        settings = Settings(
            github_client_id="test_client_id", github_client_secret="test_client_secret"
        )
        oauth_service = OAuthService(settings)

        # Create a mock request with session containing code verifier
        mock_request = Mock()
        mock_request.session = {
            "oauth_code_verifier": "test_code_verifier_123",
            "oauth_csrf_token": "test_csrf_token",
        }
        mock_request.query_params = {
            "state": oauth_service._encode_state(
                "github", "http://localhost:3000/auth/callback", "test_csrf_token"
            ),
            "code": "test_code",
        }

        # Mock the OAuth client and token response
        mock_client = Mock()
        mock_client.authorize_access_token = AsyncMock(
            return_value={"access_token": "test_token", "token_type": "bearer"}
        )
        oauth_service.oauth._clients = {"github": mock_client}  # type: ignore

        # Mock _get_user_info
        mock_user_info = OAuthUserInfo(
            id="12345", email="test@example.com", name="Test User", provider="github"
        )
        oauth_service._get_user_info = AsyncMock(return_value=mock_user_info)  # type: ignore

        # Call handle_callback
        result = await oauth_service.handle_callback(mock_request)

        # Verify authorize_access_token was called with code_verifier
        mock_client.authorize_access_token.assert_called_once_with(
            mock_request, code_verifier="test_code_verifier_123"
        )

        # Verify session cleanup
        assert "oauth_code_verifier" not in mock_request.session
        assert "oauth_csrf_token" not in mock_request.session

        # Verify result
        assert result == mock_user_info

    async def test_handle_callback_with_code_includes_pkce_verifier(self):
        """Test that handle_callback_with_code includes PKCE code verifier in token request."""
        settings = Settings(
            github_client_id="test_client_id", github_client_secret="test_client_secret"
        )
        oauth_service = OAuthService(settings)

        # Create a mock request with session containing code verifier
        mock_request = Mock()
        mock_request.session = {
            "oauth_code_verifier": "test_code_verifier_456",
            "oauth_csrf_token": "test_csrf_token",
        }

        # Mock the OAuth client
        mock_client = Mock()
        mock_client.client_id = "test_client_id"
        mock_client.client_secret = "test_client_secret"
        mock_client.access_token_url = "https://github.com/login/oauth/access_token"
        oauth_service.oauth._clients = {"github": mock_client}  # type: ignore

        # Mock httpx response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "test_token",
            "token_type": "bearer",
        }

        # Mock _get_user_info
        mock_user_info = OAuthUserInfo(
            id="12345", email="test@example.com", name="Test User", provider="github"
        )
        oauth_service._get_user_info = AsyncMock(return_value=mock_user_info)  # type: ignore

        with patch("httpx.AsyncClient") as mock_httpx:
            mock_client_instance = AsyncMock()
            mock_client_instance.post.return_value = mock_response
            mock_httpx.return_value.__aenter__.return_value = mock_client_instance

            # Call handle_callback_with_code
            state = oauth_service._encode_state(
                "github", "http://localhost:3000/auth/callback", "test_csrf_token"
            )
            result = await oauth_service.handle_callback_with_code(
                mock_request,
                "github",
                "test_code",
                state,
                "http://localhost:3000/auth/callback",
            )

            # Verify the POST request included code_verifier
            mock_client_instance.post.assert_called_once()
            call_args = mock_client_instance.post.call_args
            posted_data = call_args.kwargs["data"]
            assert "code_verifier" in posted_data
            assert posted_data["code_verifier"] == "test_code_verifier_456"

            # Verify session cleanup
            assert "oauth_code_verifier" not in mock_request.session
            assert "oauth_csrf_token" not in mock_request.session

            # Verify result
            assert result == mock_user_info


class TestOAuthServiceGoogle:
    """Test OAuth service Google Contacts integration functionality."""

    @pytest.fixture
    def oauth_service_with_google(self):
        """Create OAuth service with Google provider configured."""
        settings = Settings(
            google_client_id="test_google_client_id",
            google_client_secret="test_google_client_secret",
        )
        return OAuthService(settings)

    @pytest.fixture
    def mock_request(self):
        """Create mock request with session."""
        request = Mock()
        request.session = {}
        request.base_url = "https://example.com/"
        return request

    @pytest.fixture
    def mock_connection(self):
        """Create mock database connection."""
        return AsyncMock()

    async def test_get_google_authorization_url_success(
        self, oauth_service_with_google, mock_request
    ):
        """Test successful Google Contacts authorization URL generation."""
        redirect_uri = "https://example.com/auth/callback"

        with patch.object(
            oauth_service_with_google.oauth._clients["google"],
            "create_authorization_url",
            new_callable=AsyncMock,
        ) as mock_create_url:
            mock_create_url.return_value = {
                "url": "https://accounts.google.com/oauth/authorize?client_id=test&state=encoded_state"
            }

            await oauth_service_with_google.get_google_authorization_url(
                mock_request, redirect_uri
            )

            # Verify authorization URL was created with correct parameters
            mock_create_url.assert_called_once()
            call_args = mock_create_url.call_args
            assert call_args[0][0] == redirect_uri  # redirect_uri
            assert "state" in call_args[1]
            assert "code_verifier" in call_args[1]
            assert (
                call_args[1]["scope"]
                == "openid email profile https://www.googleapis.com/auth/contacts.readonly"
            )
            assert call_args[1]["access_type"] == "offline"
            assert call_args[1]["prompt"] == "consent"

    async def test_is_google_connected_no_tokens(
        self, oauth_service_with_google, mock_connection
    ):
        """Test is_google_connected returns False when no tokens exist."""
        # Arrange
        user_id = "test-user-123"

        # Mock database query to return no results
        mock_result = Mock()
        mock_result.fetchone.return_value = None
        mock_connection.execute = AsyncMock(return_value=mock_result)

        # Act
        result = await oauth_service_with_google.is_google_connected(
            user_id, mock_connection
        )

        # Assert
        assert result is False
        mock_connection.execute.assert_called_once()

    async def test_is_google_connected_with_valid_tokens(
        self, oauth_service_with_google, mock_connection
    ):
        """Test is_google_connected returns True when valid tokens exist."""
        # Arrange
        user_id = "test-user-123"

        # Mock database query to return a token record
        mock_result = Mock()
        mock_result.fetchone.return_value = {
            "user_id": user_id,
            "google_account_email": "test@gmail.com",
        }
        mock_connection.execute = AsyncMock(return_value=mock_result)

        # Act
        result = await oauth_service_with_google.is_google_connected(
            user_id, mock_connection
        )

        # Assert
        assert result is True
        mock_connection.execute.assert_called_once()

    async def test_get_connected_google_account_email_returns_email(
        self, oauth_service_with_google, mock_connection
    ):
        """Test resolving the stored Google account email for a user."""
        mock_scalars = Mock()
        mock_scalars.all.return_value = ["connected@gmail.com"]
        mock_result = Mock()
        mock_result.scalars.return_value = mock_scalars
        mock_connection.execute = AsyncMock(return_value=mock_result)

        result = await oauth_service_with_google.get_connected_google_account_email(
            "test-user-123", mock_connection
        )

        assert result == "connected@gmail.com"
        mock_connection.execute.assert_called_once()

    async def test_get_connected_google_account_email_raises_when_missing(
        self, oauth_service_with_google, mock_connection
    ):
        """Test resolving the stored Google account email when none exists."""
        mock_scalars = Mock()
        mock_scalars.all.return_value = []
        mock_result = Mock()
        mock_result.scalars.return_value = mock_scalars
        mock_connection.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="No Google Contacts connection found"):
            await oauth_service_with_google.get_connected_google_account_email(
                "test-user-123", mock_connection
            )

    async def test_get_connected_google_account_email_raises_when_ambiguous(
        self, oauth_service_with_google, mock_connection
    ):
        """Test resolving the stored Google account email when multiple exist."""
        mock_scalars = Mock()
        mock_scalars.all.return_value = ["first@gmail.com", "second@gmail.com"]
        mock_result = Mock()
        mock_result.scalars.return_value = mock_scalars
        mock_connection.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(
            ValueError, match="Multiple Google Contacts connections found"
        ):
            await oauth_service_with_google.get_connected_google_account_email(
                "test-user-123", mock_connection
            )

    async def test_get_google_authorization_url_no_provider(self):
        """Test Google Contacts authorization URL when Google provider not configured."""
        settings = Settings()  # No Google provider
        oauth_service = OAuthService(settings)
        mock_request = Mock()
        mock_request.session = {}

        with pytest.raises(HTTPException) as exc_info:
            await oauth_service.get_google_authorization_url(
                mock_request, "https://example.com/callback"
            )

        assert exc_info.value.status_code == 400
        assert "Google OAuth provider not configured" in str(exc_info.value.detail)

    async def test_handle_google_callback_success(
        self, oauth_service_with_google, mock_request
    ):
        """Test successful Google Contacts OAuth callback handling."""
        # Setup session data
        mock_request.session = {
            "oauth_csrf_token": "test_csrf_token",
            "oauth_code_verifier": "test_code_verifier",
        }

        # Mock state encoding/decoding
        with patch.object(
            oauth_service_with_google, "_decode_state"
        ) as mock_decode_state:
            mock_decode_state.return_value = {
                "provider": "google",
                "redirect_uri": "https://example.com/callback",
                "csrf_token": "test_csrf_token",
            }

            # Mock HTTP client for token exchange
            mock_token_data = {
                "access_token": "test_access_token",
                "refresh_token": "test_refresh_token",
                "expires_in": 3600,
            }

            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_token_data

            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client.post = AsyncMock(return_value=mock_response)
                mock_client_class.return_value = mock_client

                result = await oauth_service_with_google.handle_google_callback(
                    mock_request,
                    "test_code",
                    "encoded_state",
                    "https://example.com/callback",
                )

                # Verify HTTP request was made correctly
                mock_client.post.assert_called_once()
                call_args = mock_client.post.call_args
                assert call_args[0][0] == "https://oauth2.googleapis.com/token"
                assert call_args[1]["data"]["grant_type"] == "authorization_code"
                assert call_args[1]["data"]["code"] == "test_code"
                assert (
                    call_args[1]["data"]["redirect_uri"]
                    == "https://example.com/callback"
                )
                assert call_args[1]["data"]["code_verifier"] == "test_code_verifier"

                # Verify session cleanup
                assert "oauth_csrf_token" not in mock_request.session
                assert "oauth_code_verifier" not in mock_request.session

                # Verify result
                assert result == mock_token_data

    async def test_handle_google_callback_invalid_state(
        self, oauth_service_with_google, mock_request
    ):
        """Test Google Contacts callback with invalid state."""
        with patch.object(
            oauth_service_with_google, "_decode_state"
        ) as mock_decode_state:
            mock_decode_state.side_effect = Exception("Invalid state")

            with pytest.raises(HTTPException) as exc_info:
                await oauth_service_with_google.handle_google_callback(
                    mock_request,
                    "test_code",
                    "invalid_state",
                    "https://example.com/callback",
                )

            assert exc_info.value.status_code == 400
            assert "Invalid state parameter" in str(exc_info.value.detail)

    async def test_handle_google_callback_csrf_mismatch(
        self, oauth_service_with_google, mock_request
    ):
        """Test Google Contacts callback with CSRF token mismatch."""
        mock_request.session = {"oauth_csrf_token": "different_token"}

        with patch.object(
            oauth_service_with_google, "_decode_state"
        ) as mock_decode_state:
            mock_decode_state.return_value = {
                "provider": "google",
                "redirect_uri": "https://example.com/callback",
                "csrf_token": "test_csrf_token",
            }

            with pytest.raises(HTTPException) as exc_info:
                await oauth_service_with_google.handle_google_callback(
                    mock_request,
                    "test_code",
                    "encoded_state",
                    "https://example.com/callback",
                )

            assert exc_info.value.status_code == 400
            assert "Invalid CSRF token" in str(exc_info.value.detail)

    async def test_disconnect_google_success(
        self, oauth_service_with_google, mock_connection
    ):
        """Test Google Contacts disconnect successfully deletes tokens."""
        # Arrange
        user_id = "test-user-123"

        # Mock database delete to return 1 row deleted
        mock_result = Mock()
        mock_result.rowcount = 1
        mock_connection.execute = AsyncMock(return_value=mock_result)

        # Act
        result = await oauth_service_with_google.disconnect_google(
            user_id, mock_connection
        )

        # Assert
        assert result is True
        mock_connection.execute.assert_called_once()

    async def test_disconnect_google_no_tokens(
        self, oauth_service_with_google, mock_connection
    ):
        """Test Google Contacts disconnect returns False when no tokens exist."""
        # Arrange
        user_id = "test-user-123"

        # Mock database delete to return 0 rows deleted
        mock_result = Mock()
        mock_result.rowcount = 0
        mock_connection.execute = AsyncMock(return_value=mock_result)

        # Act
        result = await oauth_service_with_google.disconnect_google(
            user_id, mock_connection
        )

        # Assert
        assert result is False
        mock_connection.execute.assert_called_once()

    async def test_get_google_user_email_success(self, oauth_service_with_google):
        """Test successful retrieval of Google user email."""
        # Mock HTTP client for userinfo endpoint
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "email": "test@gmail.com",
            "verified_email": True,
            "name": "Test User",
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            email = await oauth_service_with_google.get_google_user_email(
                "test_access_token"
            )

            assert email == "test@gmail.com"
            mock_client.get.assert_called_once_with(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": "Bearer test_access_token"},
            )

    async def test_get_google_user_email_no_email_in_response(
        self, oauth_service_with_google
    ):
        """Test get_google_user_email raises error when no email in response."""
        # Mock HTTP client for userinfo endpoint
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "name": "Test User",
            # No email field
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            with pytest.raises(HTTPException) as exc_info:
                await oauth_service_with_google.get_google_user_email(
                    "test_access_token"
                )

            assert exc_info.value.status_code == 400
            assert "No email found" in str(exc_info.value.detail)

    async def test_get_google_user_email_api_error(self, oauth_service_with_google):
        """Test get_google_user_email raises error when API returns error."""
        # Mock HTTP client for userinfo endpoint
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            with pytest.raises(HTTPException) as exc_info:
                await oauth_service_with_google.get_google_user_email(
                    "test_access_token"
                )

            assert exc_info.value.status_code == 400
            assert "Failed to fetch Google user information" in str(
                exc_info.value.detail
            )
