"""
Unit tests for Google auth service token revocation detection.

Tests that the auth service correctly detects invalid_grant responses,
sets the needs_reauth flag, and raises TokenRevokedError.
"""

import json
import sys
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if TYPE_CHECKING:
    from google_auth_service import GoogleAuthService

sys.path.insert(0, "/core_shared")


def _make_auth_record(auth_service: "GoogleAuthService") -> MagicMock:
    """Create a mock auth record with valid encrypted tokens."""
    record = MagicMock()
    record.id = 1
    record.encrypted_refresh_token = auth_service.encrypt("fake-refresh-token")
    record.expires_at = datetime.now(UTC) - timedelta(hours=1)
    return record


def _make_invalid_grant_response() -> MagicMock:
    """Create a mock HTTP response representing an invalid_grant error."""
    response = MagicMock()
    response.status_code = 400
    response.text = json.dumps(
        {
            "error": "invalid_grant",
            "error_description": "Token has been expired or revoked.",
        }
    )
    return response


def _patch_httpx(response: MagicMock) -> Any:
    """Context manager to patch httpx.AsyncClient to return a given response."""
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=response)

    return patch(
        "google_auth_service.httpx.AsyncClient",
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_client),
            __aexit__=AsyncMock(return_value=None),
        ),
    )


class TestTokenRevocationDetection:
    """Tests for detecting and handling revoked/expired Google tokens."""

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        """Create a mock async database session.

        Session.execute is async (awaited), but the returned CursorResult
        has sync methods like fetchone()/fetchall().
        """
        session = AsyncMock()
        return session

    @pytest.fixture
    def auth_service(self, mock_session: AsyncMock) -> "GoogleAuthService":
        """Create a GoogleAuthService with mock dependencies."""
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode()

        from google_auth_service import GoogleAuthService

        return GoogleAuthService(
            session=mock_session,
            encryption_key=key,
            google_client_id="test-client-id",
            google_client_secret="test-client-secret",
        )

    def _setup_auth_record_mock(
        self,
        mock_session: AsyncMock,
        auth_service: "GoogleAuthService",
    ) -> None:
        """Configure mock session to return a valid auth record for SELECT FOR UPDATE."""
        record = _make_auth_record(auth_service)
        # The first execute returns a result whose fetchone gives the record.
        # Subsequent execute calls (UPDATE) return a plain MagicMock.
        select_result = MagicMock()
        select_result.fetchone.return_value = record
        update_result = MagicMock()

        mock_session.execute = AsyncMock(side_effect=[select_result, update_result])

    @pytest.mark.asyncio
    async def test_refresh_detects_invalid_grant_and_raises_token_revoked_error(
        self, auth_service: "GoogleAuthService", mock_session: AsyncMock
    ) -> None:
        """When Google returns invalid_grant, should raise TokenRevokedError."""
        from google_auth_service import TokenRevokedError

        self._setup_auth_record_mock(mock_session, auth_service)

        with _patch_httpx(_make_invalid_grant_response()):
            with pytest.raises(TokenRevokedError) as exc_info:
                await auth_service.refresh_access_token("user-1", "test@gmail.com")

            assert "invalid_grant" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_refresh_sets_needs_reauth_flag_on_invalid_grant(
        self, auth_service: "GoogleAuthService", mock_session: AsyncMock
    ) -> None:
        """When invalid_grant is detected, should set needs_reauth=true in DB."""
        from google_auth_service import TokenRevokedError

        self._setup_auth_record_mock(mock_session, auth_service)

        with _patch_httpx(_make_invalid_grant_response()):
            with pytest.raises(TokenRevokedError):
                await auth_service.refresh_access_token("user-1", "test@gmail.com")

        # Verify that the needs_reauth flag was set via a second execute call
        # The first call is the SELECT FOR UPDATE, the second should be the UPDATE
        assert mock_session.execute.call_count >= 2
        update_call = mock_session.execute.call_args_list[1]
        update_sql = str(update_call[0][0])
        assert "needs_reauth" in update_sql
        update_params = update_call[0][1]
        assert update_params["needs_reauth"] is True

    @pytest.mark.asyncio
    async def test_refresh_raises_generic_error_for_non_invalid_grant_failures(
        self, auth_service: "GoogleAuthService", mock_session: AsyncMock
    ) -> None:
        """Non-invalid_grant errors should raise TokenRefreshFailedError, not TokenRevokedError."""
        from google_auth_service import TokenRefreshFailedError, TokenRevokedError

        self._setup_auth_record_mock(mock_session, auth_service)

        # Mock a different error (e.g., server error)
        error_response = MagicMock()
        error_response.status_code = 500
        error_response.text = "Internal Server Error"

        with _patch_httpx(error_response):
            with pytest.raises(TokenRefreshFailedError) as exc_info:
                await auth_service.refresh_access_token("user-1", "test@gmail.com")

            # Should NOT be the subclass TokenRevokedError
            assert not isinstance(exc_info.value, TokenRevokedError)

    @pytest.mark.asyncio
    async def test_token_revoked_error_is_subclass_of_token_refresh_failed(
        self,
    ) -> None:
        """TokenRevokedError should be a subclass of TokenRefreshFailedError for backward compat."""
        from google_auth_service import TokenRefreshFailedError, TokenRevokedError

        error = TokenRevokedError("test")
        assert isinstance(error, TokenRefreshFailedError)
