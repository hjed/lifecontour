"""
Integration tests for Google Contacts API client.

Tests the complete flow of API calls with automatic token refresh
on 401 responses.
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest

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
async def test_successful_api_call_with_valid_token(
    google_client: GoogleContactsAPIClient,
    google_auth_service: GoogleAuthService,
) -> None:
    """Test successful API call with valid access token."""
    from unittest.mock import MagicMock, patch

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

    # Mock the service at the client level
    with patch.object(google_client, "_get_service") as mock_get_service:
        mock_service = MagicMock()
        mock_people = MagicMock()
        mock_connections = MagicMock()
        mock_list = MagicMock()

        mock_get_service.return_value = mock_service
        mock_service.people.return_value = mock_people
        mock_people.connections.return_value = mock_connections
        mock_connections.list.return_value = mock_list
        mock_list.execute.return_value = mock_response

        # Make API call
        result = await google_client.list_connections()

        # Verify response
        assert result == mock_response
        assert len(result["connections"]) == 1
        assert result["connections"][0]["names"][0]["displayName"] == "John Doe"


@pytest.mark.asyncio
async def test_api_error_handling(
    google_client: GoogleContactsAPIClient,
    google_auth_service: GoogleAuthService,
) -> None:
    """Test that API errors are properly handled and re-raised."""
    from unittest.mock import MagicMock, patch

    from googleapiclient.errors import HttpError

    google_email = "test@example.com"

    # Store valid tokens
    await google_auth_service.store_tokens(
        google_account_email=google_email,
        access_token="valid-access-token",
        refresh_token="refresh-token",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    # Mock the service at the client level
    with patch.object(google_client, "_get_service") as mock_get_service:
        mock_service = MagicMock()
        mock_people = MagicMock()
        mock_connections = MagicMock()
        mock_list = MagicMock()

        mock_get_service.return_value = mock_service
        mock_service.people.return_value = mock_people
        mock_people.connections.return_value = mock_connections
        mock_connections.list.return_value = mock_list

        # Mock 401 error
        mock_response_401 = MagicMock()
        mock_response_401.status = 401
        http_error = HttpError(
            mock_response_401, b'{"error": {"message": "Invalid token"}}'
        )
        mock_list.execute.side_effect = http_error

        # API call should raise HttpError
        with pytest.raises(HttpError) as exc_info:
            await google_client.list_connections()

        assert exc_info.value.resp.status == 401


@pytest.mark.asyncio
async def test_api_server_error_handling(
    google_client: GoogleContactsAPIClient,
    google_auth_service: GoogleAuthService,
) -> None:
    """Test that server errors are properly handled and re-raised."""
    from unittest.mock import MagicMock, patch

    from googleapiclient.errors import HttpError

    google_email = "test@example.com"

    # Store valid tokens
    await google_auth_service.store_tokens(
        google_account_email=google_email,
        access_token="valid-access-token",
        refresh_token="refresh-token",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    # Mock the service at the client level
    with patch.object(google_client, "_get_service") as mock_get_service:
        mock_service = MagicMock()
        mock_people = MagicMock()
        mock_connections = MagicMock()
        mock_list = MagicMock()

        mock_get_service.return_value = mock_service
        mock_service.people.return_value = mock_people
        mock_people.connections.return_value = mock_connections
        mock_connections.list.return_value = mock_list

        # Mock 500 server error
        mock_response_500 = MagicMock()
        mock_response_500.status = 500
        http_error = HttpError(
            mock_response_500, b'{"error": {"message": "Internal server error"}}'
        )
        mock_list.execute.side_effect = http_error

        # API call should raise HttpError
        with pytest.raises(HttpError) as exc_info:
            await google_client.list_connections()

        assert exc_info.value.resp.status == 500


@pytest.mark.asyncio
async def test_get_specific_contact(
    google_client: GoogleContactsAPIClient,
    google_auth_service: GoogleAuthService,
) -> None:
    """Test getting a specific contact by resource name."""
    from unittest.mock import MagicMock, patch

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

    # Mock the service at the client level
    with patch.object(google_client, "_get_service") as mock_get_service:
        mock_service = MagicMock()
        mock_people = MagicMock()
        mock_get = MagicMock()

        mock_get_service.return_value = mock_service
        mock_service.people.return_value = mock_people
        mock_people.get.return_value = mock_get
        mock_get.execute.return_value = mock_contact

        # Get specific contact
        result = await google_client.get_contact("people/123")

        # Verify response
        assert result == mock_contact
        assert result["resourceName"] == "people/123"
        assert result["names"][0]["displayName"] == "John Doe"


@pytest.mark.asyncio
async def test_list_connections_with_pagination(
    google_client: GoogleContactsAPIClient,
    google_auth_service: GoogleAuthService,
) -> None:
    """Test listing connections with pagination parameters."""
    from unittest.mock import MagicMock, patch

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

    # Mock the service at the client level
    with patch.object(google_client, "_get_service") as mock_get_service:
        mock_service = MagicMock()
        mock_people = MagicMock()
        mock_connections = MagicMock()
        mock_list = MagicMock()

        mock_get_service.return_value = mock_service
        mock_service.people.return_value = mock_people
        mock_people.connections.return_value = mock_connections
        mock_connections.list.return_value = mock_list
        mock_list.execute.return_value = mock_response

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

        # Verify the API was called with correct parameters
        mock_connections.list.assert_called_once_with(
            resourceName="people/me",
            pageSize=50,
            pageToken="current-page-token",
            syncToken="sync-token-123",
            personFields="names,emailAddresses,phoneNumbers,addresses,organizations,birthdays,metadata",
        )


@pytest.mark.asyncio
async def test_client_initialization(
    google_auth_service: GoogleAuthService,
) -> None:
    """Test client initialization and basic properties."""
    google_email = "test@example.com"

    # Test client creation
    client = GoogleContactsAPIClient(
        auth_service=google_auth_service,
        google_account_email=google_email,
        google_client_id="test_client_id",
        google_client_secret="test_client_secret",
    )

    assert client is not None
    assert client.google_account_email == google_email
    assert client.auth_service == google_auth_service
    assert client.google_client_id == "test_client_id"
    assert client.google_client_secret == "test_client_secret"

    # Verify the client can be created without errors
    # The service will be created lazily when needed
