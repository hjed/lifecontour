"""
Unit tests for OAuth service.

Tests OAuth provider configuration and user information extraction.
"""

from unittest.mock import AsyncMock, Mock

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
