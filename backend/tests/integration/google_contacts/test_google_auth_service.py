"""
Integration tests for Google authentication service.

Tests the complete flow of storing, retrieving, and refreshing Google OAuth tokens
with real database operations and encrypted storage.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.encryption import EncryptionService
from app.core.integrations.google_contacts.models import SITE_USER_ID
from app.core.integrations.google_contacts.service import (
    GoogleAuthService,
    TokenRefreshFailedError,
)
from app.infrastructure.config import Settings


@pytest.fixture
def test_settings() -> Settings:
    """Create test settings with encryption key."""
    return Settings(
        google_client_id="test-client-id",
        google_client_secret="test-client-secret",
        google_encryption_key="EM2rovSCk4Z2FjGzeugSOM8YVNEc4IiOoRxNrhLiDCo=",
    )


@pytest.fixture
def encryption_service(test_settings: Settings) -> EncryptionService:
    """Create encryption service for testing."""
    return EncryptionService(test_settings)


@pytest.fixture
def google_auth_service(
    async_connection: AsyncConnection,
    encryption_service: EncryptionService,
    test_settings: Settings,
) -> GoogleAuthService:
    """Create Google auth service for testing."""
    return GoogleAuthService(
        connection=async_connection,
        encryption_service=encryption_service,
        google_client_id=test_settings.google_client_id,
        google_client_secret=test_settings.google_client_secret,
    )


@pytest.mark.asyncio
async def test_store_and_retrieve_tokens(
    google_auth_service: GoogleAuthService,
    async_connection: AsyncConnection,
    encryption_service: EncryptionService,
) -> None:
    """Test storing and retrieving Google OAuth tokens."""
    # Test data
    google_email = "test@example.com"
    access_token = "test-access-token"
    refresh_token = "test-refresh-token"
    expires_at = datetime.now(UTC) + timedelta(hours=1)

    # Store tokens
    await google_auth_service.store_tokens(
        google_account_email=google_email,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
    )

    # Verify tokens are stored in database
    stmt = text("""
        SELECT id, user_id, google_account_email, encrypted_access_token,
               encrypted_refresh_token, expires_at, created_at, updated_at
        FROM user_google_auth
        WHERE user_id = :user_id AND google_account_email = :email
    """)
    result = await async_connection.execute(
        stmt, {"user_id": SITE_USER_ID, "email": google_email}
    )
    auth_record = result.fetchone()

    assert auth_record is not None
    assert auth_record.user_id == SITE_USER_ID
    assert auth_record.google_account_email == google_email
    assert auth_record.expires_at == expires_at

    # Verify tokens are encrypted
    assert auth_record.encrypted_access_token != access_token.encode()
    assert auth_record.encrypted_refresh_token != refresh_token.encode()

    # Verify tokens can be decrypted
    decrypted_access = encryption_service.decrypt(auth_record.encrypted_access_token)
    decrypted_refresh = encryption_service.decrypt(auth_record.encrypted_refresh_token)
    assert decrypted_access == access_token
    assert decrypted_refresh == refresh_token

    # Retrieve access token via service
    retrieved_token = await google_auth_service.get_access_token(google_email)
    assert retrieved_token == access_token


@pytest.mark.asyncio
async def test_update_existing_tokens(
    google_auth_service: GoogleAuthService,
    async_connection: AsyncConnection,
) -> None:
    """Test updating existing Google OAuth tokens."""
    google_email = "test@example.com"

    # Store initial tokens
    initial_access_token = "initial-access-token"
    initial_refresh_token = "initial-refresh-token"
    initial_expires_at = datetime.now(UTC) + timedelta(hours=1)

    await google_auth_service.store_tokens(
        google_account_email=google_email,
        access_token=initial_access_token,
        refresh_token=initial_refresh_token,
        expires_at=initial_expires_at,
    )

    # Update with new tokens
    new_access_token = "new-access-token"
    new_refresh_token = "new-refresh-token"
    new_expires_at = datetime.now(UTC) + timedelta(hours=2)

    await google_auth_service.store_tokens(
        google_account_email=google_email,
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        expires_at=new_expires_at,
    )

    # Verify only one record exists
    stmt = text("""
        SELECT COUNT(*) FROM user_google_auth
        WHERE user_id = :user_id AND google_account_email = :email
    """)
    result = await async_connection.execute(
        stmt, {"user_id": SITE_USER_ID, "email": google_email}
    )
    count = result.scalar()
    assert count == 1

    # Verify updated tokens
    retrieved_token = await google_auth_service.get_access_token(google_email)
    assert retrieved_token == new_access_token


@pytest.mark.asyncio
@respx.mock
async def test_successful_token_refresh(
    google_auth_service: GoogleAuthService,
) -> None:
    """Test successful Google token refresh on 401 response."""
    google_email = "test@example.com"

    # Store initial tokens with short expiry
    initial_access_token = "expired-access-token"
    refresh_token = "valid-refresh-token"
    expires_at = datetime.now(UTC) - timedelta(minutes=1)  # Expired

    await google_auth_service.store_tokens(
        google_account_email=google_email,
        access_token=initial_access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
    )

    # Mock Google token refresh endpoint
    new_access_token = "new-access-token"
    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": new_access_token,
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )
    )

    # Refresh token
    refreshed_token = await google_auth_service.refresh_access_token(google_email)

    # Verify new token is returned
    assert refreshed_token == new_access_token

    # Verify new token is stored in database
    stored_token = await google_auth_service.get_access_token(google_email)
    assert stored_token == new_access_token


@pytest.mark.asyncio
@respx.mock
async def test_token_refresh_failure(
    google_auth_service: GoogleAuthService,
) -> None:
    """Test Google token refresh failure handling."""
    google_email = "test@example.com"

    # Store tokens
    await google_auth_service.store_tokens(
        google_account_email=google_email,
        access_token="access-token",
        refresh_token="invalid-refresh-token",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    # Mock Google token refresh endpoint to return error
    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(
            400,
            json={
                "error": "invalid_grant",
                "error_description": "Token has been expired or revoked.",
            },
        )
    )

    # Attempt refresh should raise exception
    with pytest.raises(TokenRefreshFailedError):
        await google_auth_service.refresh_access_token(google_email)


@pytest.mark.asyncio
async def test_get_access_token_not_found(
    google_auth_service: GoogleAuthService,
) -> None:
    """Test getting access token for non-existent account."""
    with pytest.raises(ValueError, match="No Google auth found"):
        await google_auth_service.get_access_token("nonexistent@example.com")


@pytest.mark.asyncio
async def test_refresh_token_not_found(
    google_auth_service: GoogleAuthService,
) -> None:
    """Test refreshing token for non-existent account."""
    with pytest.raises(ValueError, match="No Google auth found"):
        await google_auth_service.refresh_access_token("nonexistent@example.com")


@pytest.mark.asyncio
async def test_refresh_token_missing_refresh_token(
    google_auth_service: GoogleAuthService,
) -> None:
    """Test refreshing token when no refresh token is stored."""
    google_email = "test@example.com"

    # Store tokens without refresh token
    await google_auth_service.store_tokens(
        google_account_email=google_email,
        access_token="access-token",
        refresh_token=None,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    # Attempt refresh should raise exception
    with pytest.raises(TokenRefreshFailedError, match="No refresh token available"):
        await google_auth_service.refresh_access_token(google_email)
