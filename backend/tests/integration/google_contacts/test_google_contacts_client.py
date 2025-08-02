"""
Integration tests for Google Contacts API client.

Tests the complete flow of API calls with automatic token refresh
on 401 responses.
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from app.core.integrations.encryption import EncryptionService
from app.core.integrations.google_contacts.client import GoogleContactsAPIClient
from app.core.integrations.google_contacts.service import GoogleAuthService
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
    async_connection,
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


@pytest.fixture
async def google_client(
    google_auth_service: GoogleAuthService,
) -> AsyncGenerator[GoogleContactsAPIClient, None]:
    """Create Google Contacts API client for testing."""
    client = GoogleContactsAPIClient(
        auth_service=google_auth_service,
        google_account_email="test@example.com",
        google_client_id="test_client_id",
        google_client_secret="test_client_secret",
    )
    yield client
    await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_successful_api_call_with_valid_token(
    google_client: GoogleContactsAPIClient,
    google_auth_service: GoogleAuthService,
) -> None:
    """Test successful API call with valid access token."""
    google_email = "test@example.com"
    access_token = "valid-access-token"

    # Store valid tokens
    await google_auth_service.store_tokens(
        google_account_email=google_email,
        access_token=access_token,
        refresh_token="refresh-token",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    # Mock successful Google People API response
    mock_response = {
        "connections": [
            {
                "resourceName": "people/123",
                "names": [{"displayName": "John Doe"}],
                "emailAddresses": [{"value": "john@example.com"}],
            }
        ],
        "totalItems": 1,
    }

    # Mock the API endpoint
    respx.get("https://people.googleapis.com/v1/people/me/connections").mock(
        return_value=httpx.Response(200, json=mock_response)
    )

    # Make API call
    result = await google_client.list_connections()

    # Verify response
    assert result == mock_response
    assert len(result["connections"]) == 1
    assert result["connections"][0]["names"][0]["displayName"] == "John Doe"


@pytest.mark.asyncio
@respx.mock
async def test_token_refresh_on_401_response(
    google_client: GoogleContactsAPIClient,
    google_auth_service: GoogleAuthService,
) -> None:
    """Test automatic token refresh when API returns 401."""
    google_email = "test@example.com"
    expired_token = "expired-access-token"
    refresh_token = "valid-refresh-token"
    new_access_token = "new-access-token"

    # Store expired tokens
    await google_auth_service.store_tokens(
        google_account_email=google_email,
        access_token=expired_token,
        refresh_token=refresh_token,
        expires_at=datetime.now(UTC) - timedelta(minutes=1),  # Expired
    )

    # Mock API responses
    mock_contacts_response = {
        "connections": [
            {
                "resourceName": "people/456",
                "names": [{"displayName": "Jane Doe"}],
            }
        ]
    }

    # First call returns 401 (expired token)
    # Second call returns 200 (after refresh)
    respx.get("https://people.googleapis.com/v1/people/me/connections").mock(
        side_effect=[
            httpx.Response(401, json={"error": "invalid_token"}),
            httpx.Response(200, json=mock_contacts_response),
        ]
    )

    # Mock token refresh endpoint
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

    # Make API call - should automatically refresh token and retry
    result = await google_client.list_connections()

    # Verify successful response after token refresh
    assert result == mock_contacts_response
    assert len(result["connections"]) == 1
    assert result["connections"][0]["names"][0]["displayName"] == "Jane Doe"

    # Verify new token is stored in database
    stored_token = await google_auth_service.get_access_token(google_email)
    assert stored_token == new_access_token


@pytest.mark.asyncio
@respx.mock
async def test_token_refresh_failure_returns_401(
    google_client: GoogleContactsAPIClient,
    google_auth_service: GoogleAuthService,
) -> None:
    """Test that 401 is returned when token refresh fails."""
    google_email = "test@example.com"

    # Store tokens with invalid refresh token
    await google_auth_service.store_tokens(
        google_account_email=google_email,
        access_token="expired-access-token",
        refresh_token="invalid-refresh-token",
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )

    # Mock API to return 401
    respx.get("https://people.googleapis.com/v1/people/me/connections").mock(
        return_value=httpx.Response(401, json={"error": "invalid_token"})
    )

    # Mock token refresh to fail
    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(
            400,
            json={"error": "invalid_grant"},
        )
    )

    # API call should raise HTTPStatusError due to 401
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await google_client.list_connections()

    assert exc_info.value.response.status_code == 401


@pytest.mark.asyncio
@respx.mock
async def test_get_specific_contact(
    google_client: GoogleContactsAPIClient,
    google_auth_service: GoogleAuthService,
) -> None:
    """Test getting a specific contact by resource name."""
    google_email = "test@example.com"

    # Store valid tokens
    await google_auth_service.store_tokens(
        google_account_email=google_email,
        access_token="valid-access-token",
        refresh_token="refresh-token",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    # Mock contact response
    mock_contact = {
        "resourceName": "people/123",
        "names": [
            {"displayName": "John Doe", "givenName": "John", "familyName": "Doe"}
        ],
        "emailAddresses": [{"value": "john@example.com", "type": "work"}],
        "phoneNumbers": [{"value": "+1234567890", "type": "mobile"}],
    }

    # Mock the API endpoint
    respx.get("https://people.googleapis.com/v1/people/123").mock(
        return_value=httpx.Response(200, json=mock_contact)
    )

    # Get specific contact
    result = await google_client.get_contact("people/123")

    # Verify response
    assert result == mock_contact
    assert result["resourceName"] == "people/123"
    assert result["names"][0]["displayName"] == "John Doe"


@pytest.mark.asyncio
@respx.mock
async def test_list_connections_with_pagination(
    google_client: GoogleContactsAPIClient,
    google_auth_service: GoogleAuthService,
) -> None:
    """Test listing connections with pagination parameters."""
    google_email = "test@example.com"

    # Store valid tokens
    await google_auth_service.store_tokens(
        google_account_email=google_email,
        access_token="valid-access-token",
        refresh_token="refresh-token",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    # Mock paginated response
    mock_response = {
        "connections": [{"resourceName": "people/123"}],
        "nextPageToken": "next-page-token",
        "totalItems": 100,
    }

    # Mock the API endpoint with query parameters
    respx.get("https://people.googleapis.com/v1/people/me/connections").mock(
        return_value=httpx.Response(200, json=mock_response)
    )

    # Make API call with pagination
    result = await google_client.list_connections(
        page_size=50,
        page_token="current-page-token",
        sync_token="sync-token-123",
    )

    # Verify response
    assert result == mock_response
    assert result["nextPageToken"] == "next-page-token"
    assert result["totalItems"] == 100


@pytest.mark.asyncio
async def test_client_context_manager(
    google_auth_service: GoogleAuthService,
) -> None:
    """Test using the client as an async context manager."""
    google_email = "test@example.com"

    # Test context manager usage
    async with GoogleContactsAPIClient(
        auth_service=google_auth_service,
        google_account_email=google_email,
        google_client_id="test_client_id",
        google_client_secret="test_client_secret",
    ) as client:
        assert client is not None
        assert client.google_account_email == google_email
        assert client.client is not None

    # Client should be closed after context manager exits
    assert client.client.is_closed
