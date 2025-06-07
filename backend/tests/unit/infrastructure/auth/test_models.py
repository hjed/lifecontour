"""
Unit tests for authentication models.

Tests OAuth user models and session management.
"""

from datetime import UTC, datetime

import pytest

from app.infrastructure.auth.models import OAuthProvider, OAuthUserInfo, SessionUser


class TestOAuthUserInfo:
    """Test OAuth user information model."""

    def test_oauth_user_info_creation(self):
        """Test creating OAuth user info with all fields."""
        user_info = OAuthUserInfo(
            id="12345",
            email="test@example.com",
            name="Test User",
            avatar_url="https://example.com/avatar.jpg",
            provider="github",
            provider_data={"login": "testuser", "public_repos": 10},
        )

        assert user_info.id == "12345"
        assert user_info.email == "test@example.com"
        assert user_info.name == "Test User"
        assert user_info.avatar_url == "https://example.com/avatar.jpg"
        assert user_info.provider == "github"
        assert user_info.provider_data["login"] == "testuser"

    def test_oauth_user_info_minimal(self):
        """Test creating OAuth user info with minimal required fields."""
        user_info = OAuthUserInfo(
            id="12345", email="test@example.com", provider="github"
        )

        assert user_info.id == "12345"
        assert user_info.email == "test@example.com"
        assert user_info.name is None
        assert user_info.avatar_url is None
        assert user_info.provider == "github"
        assert user_info.provider_data == {}

    def test_oauth_user_info_validation(self):
        """Test OAuth user info validation."""
        # Test missing required fields
        with pytest.raises(ValueError):
            OAuthUserInfo(email="test@example.com", provider="github")  # type: ignore[call-arg]  # Missing id

        with pytest.raises(ValueError):
            OAuthUserInfo(id="12345", provider="github")  # type: ignore[call-arg]  # Missing email

        with pytest.raises(ValueError):
            OAuthUserInfo(id="12345", email="test@example.com")  # type: ignore[call-arg]  # Missing provider


class TestSessionUser:
    """Test session user model."""

    def test_session_user_creation(self):
        """Test creating session user with all fields."""
        auth_time = datetime.now(UTC)
        session_user = SessionUser(
            id="12345",
            email="test@example.com",
            name="Test User",
            avatar_url="https://example.com/avatar.jpg",
            provider="github",
            authenticated_at=auth_time,
        )

        assert session_user.id == "12345"
        assert session_user.email == "test@example.com"
        assert session_user.name == "Test User"
        assert session_user.avatar_url == "https://example.com/avatar.jpg"
        assert session_user.provider == "github"
        assert session_user.authenticated_at == auth_time

    def test_session_user_minimal(self):
        """Test creating session user with minimal required fields."""
        session_user = SessionUser(
            id="12345", email="test@example.com", provider="github"
        )

        assert session_user.id == "12345"
        assert session_user.email == "test@example.com"
        assert session_user.name is None
        assert session_user.avatar_url is None
        assert session_user.provider == "github"
        assert isinstance(session_user.authenticated_at, datetime)

    def test_session_user_from_oauth_user(self):
        """Test creating session user from OAuth user info."""
        oauth_user = OAuthUserInfo(
            id="12345",
            email="test@example.com",
            name="Test User",
            avatar_url="https://example.com/avatar.jpg",
            provider="github",
            provider_data={"login": "testuser"},
        )

        session_user = SessionUser.from_oauth_user(oauth_user)

        assert session_user.id == oauth_user.id
        assert session_user.email == oauth_user.email
        assert session_user.name == oauth_user.name
        assert session_user.avatar_url == oauth_user.avatar_url
        assert session_user.provider == oauth_user.provider
        assert isinstance(session_user.authenticated_at, datetime)

    def test_session_user_validation(self):
        """Test session user validation."""
        # Test missing required fields
        with pytest.raises(ValueError):
            SessionUser(email="test@example.com", provider="github")  # type: ignore[call-arg]  # Missing id

        with pytest.raises(ValueError):
            SessionUser(id="12345", provider="github")  # type: ignore[call-arg]  # Missing email

        with pytest.raises(ValueError):
            SessionUser(id="12345", email="test@example.com")  # type: ignore[call-arg]  # Missing provider


class TestOAuthProvider:
    """Test OAuth provider configuration model."""

    def test_oauth_provider_creation(self):
        """Test creating OAuth provider configuration."""
        provider = OAuthProvider(
            name="github",
            client_id="test_client_id",
            client_secret="test_client_secret",
            authorization_url="https://github.com/login/oauth/authorize",
            token_url="https://github.com/login/oauth/access_token",
            userinfo_url="https://api.github.com/user",
            scope="user:email",
        )

        assert provider.name == "github"
        assert provider.client_id == "test_client_id"
        assert provider.client_secret == "test_client_secret"
        assert provider.authorization_url == "https://github.com/login/oauth/authorize"
        assert provider.token_url == "https://github.com/login/oauth/access_token"
        assert provider.userinfo_url == "https://api.github.com/user"
        assert provider.scope == "user:email"

    def test_oauth_provider_minimal(self):
        """Test creating OAuth provider with minimal required fields."""
        provider = OAuthProvider(
            name="github",
            client_id="test_client_id",
            client_secret="test_client_secret",
        )

        assert provider.name == "github"
        assert provider.client_id == "test_client_id"
        assert provider.client_secret == "test_client_secret"
        assert provider.authorization_url is None
        assert provider.token_url is None
        assert provider.userinfo_url is None
        assert provider.scope == "openid email profile"  # Default scope

    def test_oauth_provider_validation(self):
        """Test OAuth provider validation."""
        # Test missing required fields
        with pytest.raises(ValueError):
            OAuthProvider(  # type: ignore[call-arg]  # Missing name
                client_id="test_client_id", client_secret="test_client_secret"
            )

        with pytest.raises(ValueError):
            OAuthProvider(  # type: ignore[call-arg]  # Missing client_id
                name="github", client_secret="test_client_secret"
            )

        with pytest.raises(ValueError):
            OAuthProvider(  # type: ignore[call-arg]  # Missing client_secret
                name="github", client_id="test_client_id"
            )
