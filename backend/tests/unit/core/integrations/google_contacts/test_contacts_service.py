"""
Unit tests for Google Contacts service.

Tests the GoogleContactsService.full_sync method with mocked API responses,
including pagination and token extraction scenarios.
Also tests persistence logic and incremental sync functionality.
"""

import hashlib
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.models.sync_metadata import SyncMetadata, SyncStatus
from googleapiclient.errors import HttpError

from app.core.contacts.models.entities import Contact, ContactMethod, MethodType, Tag
from app.core.contacts.models.repositories import ContactRepository
from app.core.contacts.models.value_objects import TagName
from app.core.integrations.google_contacts.client_factory import (
    GoogleContactsClientFactory,
)
from app.core.integrations.google_contacts.contacts_service import (
    GoogleContactsService,
    GoogleContactsSyncError,
)
from app.core.integrations.google_contacts.service import GoogleAuthService
from app.core.integrations.google_contacts.transformer import GoogleContactTransformer


@pytest.fixture
def mock_connection():
    """Mock database connection."""
    connection = AsyncMock()
    return connection


@pytest.fixture
def mock_auth_service():
    """Mock Google auth service."""
    auth_service = AsyncMock(spec=GoogleAuthService)
    return auth_service


@pytest.fixture
def mock_client_factory():
    """Mock Google Contacts client factory."""
    factory = AsyncMock(spec=GoogleContactsClientFactory)
    return factory


@pytest.fixture
def mock_transformer():
    """Mock Google Contact transformer."""
    transformer = AsyncMock(spec=GoogleContactTransformer)
    return transformer


@pytest.fixture
def mock_contact_repository():
    """Mock ContactRepository."""
    repository = AsyncMock(spec=ContactRepository)
    return repository


@pytest.fixture
def contacts_service(mock_connection, mock_client_factory, mock_transformer, mock_contact_repository):
    """Create GoogleContactsService instance with mocked dependencies."""
    return GoogleContactsService(
        connection=mock_connection,
        client_factory=mock_client_factory,
        transformer=mock_transformer,
        contact_repository=mock_contact_repository,
    )


@pytest.fixture
def sample_google_person_data():
    """Sample Google Person API response data."""
    return {
        "resourceName": "people/c123456789",
        "etag": "test_etag_123",
        "names": [
            {
                "metadata": {"primary": True, "sourcePrimary": True},
                "displayName": "John Doe",
                "familyName": "Doe",
                "givenName": "John",
                "middleName": "Michael",
            }
        ],
        "emailAddresses": [
            {
                "metadata": {"primary": True, "sourcePrimary": True},
                "value": "john.doe@example.com",
                "type": "work",
                "formattedType": "Work",
            },
            {
                "metadata": {"primary": False, "sourcePrimary": False},
                "value": "john.personal@example.com",
                "type": "home",
                "formattedType": "Home",
            },
        ],
        "phoneNumbers": [
            {
                "metadata": {"primary": True, "sourcePrimary": True},
                "value": "+1-555-123-4567",
                "canonicalForm": "+15551234567",
                "type": "work",
                "formattedType": "Work",
            }
        ],
        "addresses": [
            {
                "metadata": {"primary": True, "sourcePrimary": True},
                "formattedValue": "123 Main St, Anytown, CA 12345, USA",
                "streetAddress": "123 Main St",
                "city": "Anytown",
                "region": "CA",
                "postalCode": "12345",
                "country": "USA",
                "countryCode": "US",
                "type": "home",
            }
        ],
        "biographies": [
            {
                "metadata": {"primary": True, "sourcePrimary": True},
                "value": "Software engineer with 10 years of experience.",
                "contentType": "TEXT_PLAIN",
            }
        ],
        "organizations": [
            {
                "metadata": {"primary": True, "sourcePrimary": True},
                "name": "Tech Corp",
                "title": "Senior Developer",
                "type": "work",
            }
        ],
    }


@pytest.fixture
def sample_list_connections_response(sample_google_person_data):
    """Sample Google People API list connections response."""
    return {
        "connections": [sample_google_person_data],
        "nextPageToken": None,
        "nextSyncToken": "sync_token_abc123",
        "totalPeople": 1,
    }


@pytest.fixture
def sample_contact():
    """Sample Contact entity for testing."""
    contact = Contact(
        id=1,
        first_name="John",
        last_name="Doe",
        middle_name="Michael",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    contact.methods = [
        ContactMethod(
            id=1,
            contact_id=1,
            method_type=MethodType.EMAIL,
            value="john.doe@example.com",
            is_primary=True,
        )
    ]
    return contact


@pytest.fixture
def sample_sync_metadata():
    """Sample SyncMetadata for testing."""
    return SyncMetadata(
        id=1,
        internal_id=1,
        integration_source="google_contacts",
        external_id="people/c123456789",
        version_hash="test_etag_123",
        sync_status=SyncStatus.SUCCESS.value,
        last_synced_at=datetime.now(UTC),
        retry_count=0,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def create_version_hash(contact_data: dict[str, Any]) -> str:
    """Create version hash from contact data (mimics real implementation)."""
    # Use ETag if available, otherwise hash the data
    if "etag" in contact_data:
        return str(contact_data["etag"])

    # Create hash from contact data
    contact_str = str(sorted(contact_data.items()))
    return hashlib.sha256(contact_str.encode()).hexdigest()[:32]


class TestGoogleContactsServiceFullSync:
    """Test cases for GoogleContactsService.full_sync method."""

    @pytest.mark.asyncio
    async def test_full_sync_single_page_success(
        self,
        contacts_service,
        mock_connection,
        sample_list_connections_response,
        sample_google_person_data,
    ):
        """Test successful full sync with single page of results."""
        google_account_email = "test@example.com"

        # Setup mock transformer response
        expected_contact = Contact(
            id=0,
            first_name="John",
            last_name="Doe",
            middle_name="Michael",
            tags=[Tag(name=TagName("google-contact"))],
            methods=[],
            addresses=[],
            notes=[],
        )
        contacts_service.transformer.transform_person.return_value = expected_contact

        # Setup mock client factory to return a mock client
        mock_client = AsyncMock()
        mock_client.list_connections.return_value = sample_list_connections_response
        contacts_service.client_factory.create_client.return_value = mock_client

        # Execute full sync
        contacts, next_sync_token = await contacts_service.full_sync(
            google_account_email
        )

        # Verify results
        assert len(contacts) == 1
        assert isinstance(contacts[0], Contact)
        assert contacts[0].first_name == "John"
        assert contacts[0].last_name == "Doe"
        assert contacts[0].middle_name == "Michael"
        assert next_sync_token == "sync_token_abc123"

        # Verify client factory was called correctly
        contacts_service.client_factory.create_client.assert_called_once_with(
            google_account_email
        )

        # Verify API client was called correctly
        mock_client.list_connections.assert_called_once_with(
            page_size=100,
            page_token=None,
            sync_token=None,
        )

        # Verify transformer was called correctly
        contacts_service.transformer.transform_person.assert_called_once()

        # Verify sync state was updated
        mock_connection.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_full_sync_multiple_pages(
        self,
        contacts_service,
        mock_connection,
        sample_google_person_data,
    ):
        """Test full sync with pagination across multiple pages."""
        google_account_email = "test@example.com"

        # Create responses for multiple pages
        page1_response = {
            "connections": [sample_google_person_data],
            "nextPageToken": "page_token_2",
            "totalPeople": 2,
        }

        page2_response = {
            "connections": [
                {
                    **sample_google_person_data,
                    "resourceName": "people/c987654321",
                    "names": [
                        {
                            "metadata": {"primary": True, "sourcePrimary": True},
                            "displayName": "Jane Smith",
                            "familyName": "Smith",
                            "givenName": "Jane",
                        }
                    ],
                }
            ],
            "nextPageToken": None,
            "nextSyncToken": "final_sync_token_xyz789",
            "totalPeople": 2,
        }

        # Setup mock client factory to return a mock client
        mock_client = AsyncMock()
        mock_client.list_connections.side_effect = [page1_response, page2_response]
        contacts_service.client_factory.create_client.return_value = mock_client

        # Setup mock transformer responses
        contact1 = Contact(
            id=0,
            first_name="John",
            last_name="Doe",
            tags=[Tag(name=TagName("google-contact"))],
            methods=[],
            addresses=[],
            notes=[],
        )
        contact2 = Contact(
            id=0,
            first_name="Jane",
            last_name="Smith",
            tags=[Tag(name=TagName("google-contact"))],
            methods=[],
            addresses=[],
            notes=[],
        )
        contacts_service.transformer.transform_person.side_effect = [contact1, contact2]

        # Execute full sync
        contacts, next_sync_token = await contacts_service.full_sync(
            google_account_email
        )

        # Verify results
        assert len(contacts) == 2
        assert contacts[0].first_name == "John"
        assert contacts[1].first_name == "Jane"
        assert next_sync_token == "final_sync_token_xyz789"

        # Verify client factory was called correctly
        contacts_service.client_factory.create_client.assert_called_once_with(
            google_account_email
        )

        # Verify API client was called for each page
        assert mock_client.list_connections.call_count == 2

        # Check first call (no page token)
        first_call = mock_client.list_connections.call_args_list[0]
        assert first_call[1]["page_token"] is None

        # Check second call (with page token)
        second_call = mock_client.list_connections.call_args_list[1]
        assert second_call[1]["page_token"] == "page_token_2"

    @pytest.mark.asyncio
    async def test_full_sync_empty_response(
        self,
        contacts_service,
        mock_connection,
    ):
        """Test full sync with empty response from Google."""
        google_account_email = "test@example.com"

        empty_response: dict[str, Any] = {
            "connections": [],
            "nextPageToken": None,
            "nextSyncToken": "empty_sync_token",
            "totalPeople": 0,
        }

        # Setup mock client factory to return a mock client
        mock_client = AsyncMock()
        mock_client.list_connections.return_value = empty_response
        contacts_service.client_factory.create_client.return_value = mock_client

        # Execute full sync
        contacts, next_sync_token = await contacts_service.full_sync(
            google_account_email
        )

        # Verify results
        assert len(contacts) == 0
        assert next_sync_token == "empty_sync_token"

    @pytest.mark.asyncio
    async def test_full_sync_handles_transformation_errors(
        self,
        contacts_service,
        mock_connection,
        sample_google_person_data,
    ):
        """Test that full sync continues when individual contact transformation fails."""
        google_account_email = "test@example.com"

        # Create response with one valid and one invalid contact
        # Make the invalid contact truly invalid by creating an address with invalid country code
        invalid_person_data = {
            "resourceName": "people/invalid",
            "names": [{"givenName": "Invalid", "familyName": "Person"}],
            "addresses": [
                {
                    "streetAddress": "123 Invalid St",
                    "countryCode": "INVALID_CODE",  # This will cause validation error in ContactAddress
                }
            ],
        }

        response = {
            "connections": [sample_google_person_data, invalid_person_data],
            "nextPageToken": None,
            "nextSyncToken": "sync_token_with_errors",
            "totalPeople": 2,
        }

        # Setup mock client factory to return a mock client
        mock_client = AsyncMock()
        mock_client.list_connections.return_value = response
        contacts_service.client_factory.create_client.return_value = mock_client

        # Setup mock transformer to succeed for first contact, fail for second
        valid_contact = Contact(
            id=0,
            first_name="John",
            last_name="Doe",
            tags=[Tag(name=TagName("google-contact"))],
            methods=[],
            addresses=[],
            notes=[],
        )
        contacts_service.transformer.transform_person.side_effect = [
            valid_contact,
            ValueError("Invalid contact data"),
        ]

        # Execute full sync
        contacts, next_sync_token = await contacts_service.full_sync(
            google_account_email
        )

        # Verify that valid contact was processed and invalid one was skipped
        assert len(contacts) == 1
        assert contacts[0].first_name == "John"
        assert next_sync_token == "sync_token_with_errors"

    @pytest.mark.asyncio
    async def test_full_sync_api_error_raises_exception(
        self,
        contacts_service,
        mock_connection,
    ):
        """Test that API errors are properly wrapped and raised."""
        google_account_email = "test@example.com"

        # Setup mock client factory to return a mock client that raises error
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status = 500
        http_error = HttpError(mock_response, b'{"error": {"message": "API Error"}}')
        mock_client.list_connections.side_effect = http_error
        contacts_service.client_factory.create_client.return_value = mock_client

        # Execute full sync and expect exception
        with pytest.raises(GoogleContactsSyncError) as exc_info:
            await contacts_service.full_sync(google_account_email)

        assert "Google API error while syncing contacts" in str(exc_info.value)
        assert "API Error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_full_sync_updates_sync_state(
        self,
        contacts_service,
        mock_connection,
        sample_list_connections_response,
    ):
        """Test that sync state is properly updated in database."""
        google_account_email = "test@example.com"

        # Setup mock client factory to return a mock client
        mock_client = AsyncMock()
        mock_client.list_connections.return_value = sample_list_connections_response
        contacts_service.client_factory.create_client.return_value = mock_client

        # Setup mock transformer response
        expected_contact = Contact(
            id=0,
            first_name="John",
            last_name="Doe",
            tags=[Tag(name=TagName("google-contact"))],
            methods=[],
            addresses=[],
            notes=[],
        )
        contacts_service.transformer.transform_person.return_value = expected_contact

        # Execute full sync
        await contacts_service.full_sync(google_account_email)

        # Verify database update was called
        mock_connection.execute.assert_called_once()

        # Check the SQL parameters
        call_args = mock_connection.execute.call_args
        params = call_args[0][1]  # Second argument contains parameters

        assert params["user_id"] == "site-user"
        assert params["email"] == google_account_email
        assert params["sync_token"] == "sync_token_abc123"
        assert isinstance(params["sync_time"], datetime)
        assert isinstance(params["now"], datetime)

    @pytest.mark.asyncio
    async def test_get_last_sync_token(self, contacts_service, mock_connection):
        """Test retrieving last sync token from database."""
        google_account_email = "test@example.com"
        expected_token = "previous_sync_token"

        # Mock database response
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.contacts_sync_token = expected_token
        mock_result.fetchone.return_value = mock_row
        mock_connection.execute.return_value = mock_result

        # Execute method
        result = await contacts_service.get_last_sync_token(google_account_email)

        # Verify result
        assert result == expected_token
        mock_connection.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_last_sync_token_no_record(
        self, contacts_service, mock_connection
    ):
        """Test retrieving sync token when no record exists."""
        google_account_email = "test@example.com"

        # Mock database response with no record
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_connection.execute.return_value = mock_result

        # Execute method
        result = await contacts_service.get_last_sync_token(google_account_email)

        # Verify result
        assert result is None

    @pytest.mark.asyncio
    async def test_get_last_sync_time(self, contacts_service, mock_connection):
        """Test retrieving last sync time from database."""
        google_account_email = "test@example.com"
        expected_time = datetime.now(UTC)

        # Mock database response
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.last_contacts_sync_at = expected_time
        mock_result.fetchone.return_value = mock_row
        mock_connection.execute.return_value = mock_result

        # Execute method
        result = await contacts_service.get_last_sync_time(google_account_email)

        # Verify result
        assert result == expected_time
        mock_connection.execute.assert_called_once()


class TestGoogleContactsServicePersistence:
    """Test cases for GoogleContactsService persistence logic."""

    @pytest.mark.asyncio
    async def test_save_contacts_with_metadata_new_contacts(
        self,
        contacts_service,
        mock_connection,
        mock_contact_repository,
        sample_contact,
        sample_google_person_data,
    ):
        """Test saving new contacts with sync metadata."""
        google_account_email = "test@example.com"
        google_persons = [sample_google_person_data]

        # Mock database responses for checking existing contacts
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []  # No existing contacts
        mock_connection.execute.return_value = mock_result

        # Mock contact repository save
        mock_contact_repository.save.return_value = sample_contact

        # Execute method
        await contacts_service.save_contacts_with_metadata(
            google_account_email, [sample_contact], google_persons
        )

        # Verify repository was called
        mock_contact_repository.save.assert_called_once()
        # Verify database calls were made for sync metadata
        assert (
            mock_connection.execute.call_count >= 2
        )  # Check existing + insert metadata

    @pytest.mark.asyncio
    async def test_save_contacts_with_metadata_existing_contacts_same_hash(
        self,
        contacts_service,
        mock_connection,
        mock_contact_repository,
        sample_contact,
        sample_google_person_data,
    ):
        """Test saving contacts when sync metadata exists with same hash (idempotent)."""
        google_account_email = "test@example.com"
        google_persons = [sample_google_person_data]

        # Mock existing sync metadata with same hash
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.internal_id = 1
        mock_row.external_id = "people/c123456789"
        mock_row.version_hash = "test_etag_123"  # Same as in sample data
        mock_row.sync_status = SyncStatus.SUCCESS.value
        mock_result.fetchall.return_value = [mock_row]
        mock_connection.execute.return_value = mock_result

        # Execute method
        await contacts_service.save_contacts_with_metadata(
            google_account_email, [sample_contact], google_persons
        )

        # Should not create or update contact since hash is same (idempotent)
        mock_contact_repository.save.assert_not_called()
        # Should only check existing metadata, no updates needed
        assert mock_connection.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_save_contacts_with_metadata_existing_contacts_different_hash(
        self,
        contacts_service,
        mock_connection,
        mock_contact_repository,
        sample_contact,
        sample_google_person_data,
    ):
        """Test saving contacts when sync metadata exists with different hash (needs update)."""
        google_account_email = "test@example.com"
        google_persons = [sample_google_person_data]

        # Mock existing sync metadata with different hash
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.internal_id = 1
        mock_row.external_id = "people/c123456789"
        mock_row.version_hash = "old_etag_456"  # Different from sample data
        mock_row.sync_status = SyncStatus.SUCCESS.value
        mock_result.fetchall.return_value = [mock_row]
        mock_connection.execute.return_value = mock_result

        # Mock contact repository save for update
        mock_contact_repository.save.return_value = sample_contact

        # Execute method
        await contacts_service.save_contacts_with_metadata(
            google_account_email, [sample_contact], google_persons
        )

        # Should update contact via repository
        mock_contact_repository.save.assert_called_once()
        # Should check existing + update metadata
        assert mock_connection.execute.call_count >= 2


class TestGoogleContactsServiceIncrementalSync:
    """Test cases for GoogleContactsService incremental sync functionality."""

    @pytest.mark.asyncio
    async def test_incremental_sync_with_valid_token(
        self, contacts_service, mock_connection, mock_client_factory, mock_transformer
    ):
        """Test incremental sync with valid sync token."""
        google_account_email = "test@example.com"
        sync_token = "valid_sync_token_123"

        # Mock API client
        mock_client = AsyncMock()
        mock_client.list_connections.return_value = {
            "connections": [
                {
                    "resourceName": "people/c123456789",
                    "etag": "new_etag_456",
                    "names": [{"givenName": "John", "familyName": "Doe"}],
                }
            ],
            "nextSyncToken": "new_sync_token_456",
        }
        mock_client_factory.create_client.return_value = mock_client

        # Mock transformer
        mock_contact = Contact(first_name="John", last_name="Doe")
        mock_transformer.transform_person.return_value = mock_contact

        # Execute method (this will be implemented)
        result = await contacts_service.incremental_sync(
            google_account_email, sync_token
        )

        # Verify result structure
        contacts, new_sync_token = result
        assert isinstance(contacts, list)
        assert new_sync_token == "new_sync_token_456"

        # Verify API was called with sync token
        mock_client.list_connections.assert_called_once()
        call_args = mock_client.list_connections.call_args[1]
        assert call_args["sync_token"] == sync_token

    @pytest.mark.asyncio
    async def test_incremental_sync_with_expired_token(
        self, contacts_service, mock_connection, mock_client_factory
    ):
        """Test incremental sync with expired token (HTTP 410) falls back to full sync."""
        google_account_email = "test@example.com"
        sync_token = "expired_sync_token"

        # Mock API client to return HTTP 410 (Gone)
        mock_client = AsyncMock()
        http_error = HttpError(
            resp=MagicMock(status=410), content=b"Sync token expired"
        )
        mock_client.list_connections.side_effect = http_error
        mock_client_factory.create_client.return_value = mock_client

        # Mock full_sync method
        contacts_service.full_sync = AsyncMock()
        contacts_service.full_sync.return_value = ([], "new_full_sync_token")

        # Execute method
        result = await contacts_service.incremental_sync(
            google_account_email, sync_token
        )

        # Should fall back to full sync
        contacts_service.full_sync.assert_called_once_with(google_account_email)
        contacts, new_sync_token = result
        assert new_sync_token == "new_full_sync_token"

    @pytest.mark.asyncio
    async def test_incremental_sync_handles_deleted_contacts(
        self, contacts_service, mock_connection, mock_client_factory, mock_transformer
    ):
        """Test incremental sync handles deleted contacts (soft delete)."""
        google_account_email = "test@example.com"
        sync_token = "valid_sync_token_123"

        # Mock API response with deleted contact
        mock_client = AsyncMock()
        mock_client.list_connections.return_value = {
            "connections": [
                {
                    "resourceName": "people/c123456789",
                    "etag": "deleted_etag",
                    "metadata": {"deleted": True},  # Indicates deletion
                }
            ],
            "nextSyncToken": "new_sync_token_456",
        }
        mock_client_factory.create_client.return_value = mock_client

        # Mock delete result for the DELETE statement
        mock_delete_result = MagicMock()
        mock_delete_result.rowcount = 1  # Simulate successful deletion
        mock_connection.execute.return_value = mock_delete_result

        # Execute method
        result = await contacts_service.incremental_sync(
            google_account_email, sync_token
        )

        # Should handle deletion (soft delete or remove sync metadata)
        contacts, new_sync_token = result
        assert new_sync_token == "new_sync_token_456"

        # Verify database operations for handling deletion
        assert mock_connection.execute.call_count >= 2

    @pytest.mark.asyncio
    async def test_incremental_sync_handles_created_and_updated_contacts(
        self, contacts_service, mock_connection, mock_client_factory, mock_transformer
    ):
        """Test incremental sync handles both created and updated contacts."""
        google_account_email = "test@example.com"
        sync_token = "valid_sync_token_123"

        # Mock API response with new and updated contacts
        mock_client = AsyncMock()
        mock_client.list_connections.return_value = {
            "connections": [
                {
                    "resourceName": "people/c123456789",  # Existing contact
                    "etag": "updated_etag_456",
                    "names": [{"givenName": "John", "familyName": "Doe"}],
                },
                {
                    "resourceName": "people/c987654321",  # New contact
                    "etag": "new_etag_789",
                    "names": [{"givenName": "Jane", "familyName": "Smith"}],
                },
            ],
            "nextSyncToken": "new_sync_token_456",
        }
        mock_client_factory.create_client.return_value = mock_client

        # Mock transformer
        mock_contact1 = Contact(first_name="John", last_name="Doe")
        mock_contact2 = Contact(first_name="Jane", last_name="Smith")
        mock_transformer.transform_person.side_effect = [mock_contact1, mock_contact2]

        # Mock existing sync metadata (only for first contact)
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.internal_id = 1
        mock_row.external_id = "people/c123456789"
        mock_row.version_hash = "old_etag_123"  # Different hash = needs update
        mock_result.fetchall.return_value = [mock_row]
        mock_connection.execute.return_value = mock_result

        # Execute method
        result = await contacts_service.incremental_sync(
            google_account_email, sync_token
        )

        # Verify result
        contacts, new_sync_token = result
        assert len(contacts) == 2
        assert new_sync_token == "new_sync_token_456"

        # Should handle both update and create operations
        assert mock_connection.execute.call_count >= 3

    @pytest.mark.asyncio
    async def test_incremental_sync_error_handling(
        self, contacts_service, mock_connection, mock_client_factory
    ):
        """Test incremental sync handles API errors properly."""
        google_account_email = "test@example.com"
        sync_token = "valid_sync_token_123"

        # Mock API client to return generic HTTP error
        mock_client = AsyncMock()
        http_error = HttpError(
            resp=MagicMock(status=500), content=b"Internal server error"
        )
        mock_client.list_connections.side_effect = http_error
        mock_client_factory.create_client.return_value = mock_client

        # Execute method and expect exception
        with pytest.raises(GoogleContactsSyncError) as exc_info:
            await contacts_service.incremental_sync(google_account_email, sync_token)

        # Verify error message contains relevant information
        assert "incremental sync" in str(exc_info.value).lower()
        assert google_account_email in str(exc_info.value)
