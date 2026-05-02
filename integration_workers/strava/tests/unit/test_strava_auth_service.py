"""
Unit tests for StravaAuthService.

Tests encryption, OAuth URL generation, token response parsing,
refresh request building, and token revocation — all without I/O.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from strava_auth_service import StravaAuthService, StravaTokenData


def _make_httpx_response(
    json_data: dict[str, object] | None = None, status: int = 200
) -> MagicMock:
    """Create a mock httpx.Response with synchronous .json() and .raise_for_status()."""
    mock = MagicMock()
    mock.status_code = status
    if json_data is not None:
        mock.json.return_value = json_data
    mock.raise_for_status.return_value = None
    return mock


@pytest.fixture
def auth_service() -> StravaAuthService:
    """Create a StravaAuthService with test credentials."""
    # Generate a valid Fernet key for testing
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    return StravaAuthService(
        encryption_key=key,
        client_id="test_client_id",
        client_secret="test_client_secret",
    )


class TestEncryption:
    """Test encrypt/decrypt roundtrip."""

    def test_encrypt_decrypt_roundtrip(self, auth_service: StravaAuthService) -> None:
        """Encrypting then decrypting returns the original value."""
        original = "my_secret_token_value"
        encrypted = auth_service.encrypt(original)
        decrypted = auth_service.decrypt(encrypted)
        assert decrypted == original

    def test_encrypt_produces_different_output_each_time(
        self, auth_service: StravaAuthService
    ) -> None:
        """Fernet encryption is non-deterministic (different IV each time)."""
        original = "same_value"
        encrypted_1 = auth_service.encrypt(original)
        encrypted_2 = auth_service.encrypt(original)
        assert encrypted_1 != encrypted_2

    def test_encrypt_returns_bytes(self, auth_service: StravaAuthService) -> None:
        """Encrypted output is bytes."""
        result = auth_service.encrypt("test")
        assert isinstance(result, bytes)


class TestAuthorizationUrl:
    """Test OAuth authorization URL generation."""

    def test_build_authorization_url_contains_strava_domain(
        self, auth_service: StravaAuthService
    ) -> None:
        """Authorization URL points to Strava's OAuth endpoint."""
        url = auth_service.build_authorization_url(
            redirect_uri="http://localhost:3000/auth/callback",
            state="test_state",
        )
        assert "https://www.strava.com/oauth/authorize" in url

    def test_build_authorization_url_contains_client_id(
        self, auth_service: StravaAuthService
    ) -> None:
        """Authorization URL includes the client ID."""
        url = auth_service.build_authorization_url(
            redirect_uri="http://localhost:3000/auth/callback",
            state="test_state",
        )
        assert "client_id=test_client_id" in url

    def test_build_authorization_url_contains_redirect_uri(
        self, auth_service: StravaAuthService
    ) -> None:
        """Authorization URL includes the redirect URI."""
        url = auth_service.build_authorization_url(
            redirect_uri="http://localhost:3000/auth/callback",
            state="test_state",
        )
        assert "redirect_uri=" in url
        assert "localhost" in url

    def test_build_authorization_url_requests_activity_read_all_scope(
        self, auth_service: StravaAuthService
    ) -> None:
        """Authorization URL requests activity:read_all scope per product spec."""
        url = auth_service.build_authorization_url(
            redirect_uri="http://localhost:3000/auth/callback",
            state="test_state",
        )
        assert "scope=activity%3Aread_all" in url or "scope=activity:read_all" in url

    def test_build_authorization_url_includes_state(
        self, auth_service: StravaAuthService
    ) -> None:
        """Authorization URL includes the CSRF state parameter."""
        url = auth_service.build_authorization_url(
            redirect_uri="http://localhost:3000/auth/callback",
            state="my_csrf_state",
        )
        assert "state=my_csrf_state" in url

    def test_build_authorization_url_response_type_is_code(
        self, auth_service: StravaAuthService
    ) -> None:
        """Authorization URL uses response_type=code for authorization code flow."""
        url = auth_service.build_authorization_url(
            redirect_uri="http://localhost:3000/auth/callback",
            state="test_state",
        )
        assert "response_type=code" in url


class TestTokenResponseParsing:
    """Test parsing of Strava token exchange responses."""

    def test_parse_token_response_extracts_all_fields(
        self, auth_service: StravaAuthService
    ) -> None:
        """Parsing extracts access_token, refresh_token, expires_at, athlete_id."""
        data = {
            "access_token": "access_123",
            "refresh_token": "refresh_456",
            "expires_at": 1700000000,
            "athlete": {"id": 12345},
        }
        result = auth_service.parse_token_response(data)

        assert isinstance(result, StravaTokenData)
        assert result.access_token == "access_123"
        assert result.refresh_token == "refresh_456"
        assert result.athlete_id == 12345
        assert isinstance(result.expires_at, datetime)

    def test_parse_token_response_converts_expires_at_to_datetime(
        self, auth_service: StravaAuthService
    ) -> None:
        """expires_at epoch timestamp is converted to a timezone-aware datetime."""
        data = {
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_at": 1700000000,
            "athlete": {"id": 1},
        }
        result = auth_service.parse_token_response(data)
        expected = datetime.fromtimestamp(1700000000, tz=UTC)
        assert result.expires_at == expected

    def test_parse_token_response_missing_athlete_raises(
        self, auth_service: StravaAuthService
    ) -> None:
        """Missing athlete data raises ValueError."""
        data = {
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_at": 1700000000,
        }
        with pytest.raises((ValueError, KeyError)):
            auth_service.parse_token_response(data)


class TestTokenExchange:
    """Test code exchange with mocked HTTP."""

    @pytest.mark.asyncio
    async def test_exchange_code_calls_strava_token_endpoint(
        self, auth_service: StravaAuthService
    ) -> None:
        """exchange_code POSTs to Strava's token endpoint."""
        mock_response = _make_httpx_response(
            {
                "access_token": "access_123",
                "refresh_token": "refresh_456",
                "expires_at": 1700000000,
                "athlete": {"id": 999},
            }
        )

        with patch("httpx.AsyncClient.post", return_value=mock_response) as mock_post:
            result = await auth_service.exchange_code("auth_code_abc")

            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args
            assert "https://www.strava.com/oauth/token" in str(call_kwargs)
            assert result.access_token == "access_123"
            assert result.athlete_id == 999

    @pytest.mark.asyncio
    async def test_refresh_token_calls_strava_token_endpoint(
        self, auth_service: StravaAuthService
    ) -> None:
        """refresh_token POSTs to Strava's token endpoint with grant_type=refresh_token."""
        mock_response = _make_httpx_response(
            {
                "access_token": "new_access",
                "refresh_token": "new_refresh",
                "expires_at": 1700003600,
                "athlete": {"id": 999},
            }
        )

        with patch("httpx.AsyncClient.post", return_value=mock_response) as mock_post:
            result = await auth_service.refresh_token("old_refresh_token")

            mock_post.assert_called_once()
            call_args = mock_post.call_args
            # Verify grant_type is refresh_token
            post_data = call_args.kwargs.get("data", {})
            assert post_data.get("grant_type") == "refresh_token"
            assert result.access_token == "new_access"


class TestTokenRevocation:
    """Test token revocation (disconnect)."""

    @pytest.mark.asyncio
    async def test_revoke_token_calls_strava_deauthorize(
        self, auth_service: StravaAuthService
    ) -> None:
        """revoke_token POSTs to Strava's deauthorize endpoint."""
        mock_response = _make_httpx_response()

        with patch("httpx.AsyncClient.post", return_value=mock_response) as mock_post:
            await auth_service.revoke_token("access_token_to_revoke")

            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert "https://www.strava.com/oauth/deauthorize" in str(call_args)
