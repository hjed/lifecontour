#!/usr/bin/env python3
"""
Tests for Google Contacts Integration Worker.

Tests the actual sync logic implementation using the Google People API.
"""

# Add core_shared to path for imports
import sys
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, "/core_shared")



class TestGoogleContactsWorker:
    """Test cases for Google Contacts worker sync logic."""

    @pytest.fixture
    def mock_session_factory(self):
        """Mock session factory for database operations."""
        mock_session = AsyncMock()
        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__.return_value = mock_session
        return mock_factory

    @pytest.fixture
    def mock_google_auth_service(self):
        """Mock Google authentication service."""
        mock_service = AsyncMock()
        mock_service.get_access_token.return_value = "mock_access_token"
        mock_service.refresh_access_token.return_value = "refreshed_token"
        return mock_service

    @pytest.fixture
    def mock_google_contacts_client(self):
        """Mock Google Contacts API client."""
        mock_client = AsyncMock()
        mock_client.list_connections.return_value = {
            "connections": [
                {
                    "resourceName": "people/c123456789",
                    "etag": "etag123",
                    "names": [{"displayName": "John Doe"}],
                    "emailAddresses": [{"value": "john@example.com"}],
                    "metadata": {"sources": [{"type": "CONTACT"}]},
                }
            ],
            "nextSyncToken": "sync_token_123",
        }
        return mock_client

    @pytest.mark.asyncio
    async def test_sync_google_contacts_full_sync_success(
        self,
        mock_session_factory,
        mock_google_auth_service,
        mock_google_contacts_client,
    ):
        """Test successful full sync of Google Contacts."""
        # Import the worker function
        from worker import sync_google_contacts

        # Mock the dependencies
        with (
            patch("worker.GoogleAuthService", return_value=mock_google_auth_service),
            patch(
                "worker.GoogleContactsAPIClient",
                return_value=mock_google_contacts_client,
            ),
        ):
            # Execute the sync task with session_factory in ctx
            result = await sync_google_contacts(
                ctx={"session_factory": mock_session_factory},
                google_account_email="test@example.com",
                sync_type="full",
            )

            # Verify the result
            assert result["status"] == "success"
            assert result["google_account_email"] == "test@example.com"
            assert "contacts_processed" in result
            assert result["contacts_processed"] > 0

    @pytest.mark.asyncio
    async def test_sync_google_contacts_incremental_sync_success(
        self,
        mock_session_factory,
        mock_google_auth_service,
        mock_google_contacts_client,
    ):
        """Test successful incremental sync of Google Contacts."""
        # Mock existing sync token
        mock_session = mock_session_factory.return_value.__aenter__.return_value
        mock_session.execute.return_value.fetchone.return_value = {
            "sync_token": "existing_sync_token"
        }

        from worker import sync_google_contacts

        with (
            patch("worker.GoogleAuthService", return_value=mock_google_auth_service),
            patch(
                "worker.GoogleContactsAPIClient",
                return_value=mock_google_contacts_client,
            ),
        ):
            result = await sync_google_contacts(
                ctx={"session_factory": mock_session_factory},
                google_account_email="test@example.com",
                sync_type="incremental",
            )

            assert result["status"] == "success"
            assert result["google_account_email"] == "test@example.com"

    @pytest.mark.asyncio
    async def test_sync_google_contacts_smart_sync_chooses_incremental(
        self,
        mock_session_factory,
        mock_google_auth_service,
        mock_google_contacts_client,
    ):
        """Test smart sync chooses incremental when sync token exists."""
        # Mock existing sync token
        mock_session = mock_session_factory.return_value.__aenter__.return_value
        mock_result = MagicMock()
        mock_result.scalar.return_value = "existing_sync_token"
        mock_session.execute.return_value = mock_result

        from worker import sync_google_contacts

        with (
            patch("worker.GoogleAuthService", return_value=mock_google_auth_service),
            patch(
                "worker.GoogleContactsAPIClient",
                return_value=mock_google_contacts_client,
            ),
        ):
            result = await sync_google_contacts(
                ctx={"session_factory": mock_session_factory},
                google_account_email="test@example.com",
                sync_type="smart",
            )

            assert result["status"] == "success"
            # Should have used incremental sync - check that sync_token was passed
            # Note: The actual call might have page_size and page_token as well
            calls = mock_google_contacts_client.list_connections.call_args_list
            assert len(calls) > 0
            # Check that at least one call had sync_token
            assert any("sync_token" in str(call) for call in calls)

    @pytest.mark.asyncio
    async def test_sync_google_contacts_handles_auth_error(
        self,
        mock_session_factory,
        mock_google_auth_service,
        mock_google_contacts_client,
    ):
        """Test sync handles authentication errors gracefully."""
        # Mock client to raise auth error when list_connections is called
        mock_google_contacts_client.list_connections.side_effect = Exception("Auth failed")

        from worker import sync_google_contacts

        with (
            patch("worker.GoogleAuthService", return_value=mock_google_auth_service),
            patch(
                "worker.GoogleContactsAPIClient",
                return_value=mock_google_contacts_client,
            ),
        ):
            result = await sync_google_contacts(
                ctx={"session_factory": mock_session_factory},
                google_account_email="test@example.com",
                sync_type="full",
            )

            assert result["status"] == "error"
            assert "Auth failed" in result["error"]

    @pytest.mark.asyncio
    async def test_sync_google_contacts_handles_api_error(
        self,
        mock_session_factory,
        mock_google_auth_service,
        mock_google_contacts_client,
    ):
        """Test sync handles Google API errors gracefully."""
        # Mock API client to raise error
        mock_google_contacts_client.list_connections.side_effect = Exception(
            "API error"
        )

        from worker import sync_google_contacts

        with (
            patch("worker.GoogleAuthService", return_value=mock_google_auth_service),
            patch(
                "worker.GoogleContactsAPIClient",
                return_value=mock_google_contacts_client,
            ),
        ):
            result = await sync_google_contacts(
                ctx={"session_factory": mock_session_factory},
                google_account_email="test@example.com",
                sync_type="full",
            )

            assert result["status"] == "error"
            assert "API error" in result["error"]


class TestGoogleContactsAPIClient:
    """Test cases for Google Contacts API client create/update methods."""

    @pytest.fixture
    def mock_auth_service(self):
        """Mock Google authentication service."""
        mock_service = AsyncMock()
        mock_service.get_access_token.return_value = "mock_access_token"
        return mock_service

    @pytest.fixture
    def mock_google_service(self):
        """Mock Google People API service."""
        mock_service = MagicMock()
        return mock_service

    @pytest.mark.asyncio
    async def test_create_contact_success(self, mock_auth_service, mock_google_service):
        """Test successful contact creation in Google."""
        from google_contacts_client import GoogleContactsAPIClient

        # Mock the service response
        mock_google_service.people().createContact().execute.return_value = {
            "resourceName": "people/c987654321",
            "etag": "new_etag_123",
            "names": [{"displayName": "Jane Smith", "givenName": "Jane", "familyName": "Smith"}],
            "emailAddresses": [{"value": "jane@example.com"}],
        }

        # Create client
        client = GoogleContactsAPIClient(
            auth_service=mock_auth_service,
            google_account_email="test@example.com",
            google_client_id="client_id",
            google_client_secret="client_secret",
        )

        # Mock the service
        with patch.object(client, "_get_service", return_value=mock_google_service):
            # Reset mock call count after setup
            mock_google_service.people().createContact.reset_mock()

            # Create contact data
            contact_data = {
                "names": [{"givenName": "Jane", "familyName": "Smith"}],
                "emailAddresses": [{"value": "jane@example.com"}],
            }

            # Execute create
            result = await client.create_contact(contact_data)

            # Verify result
            assert result["resourceName"] == "people/c987654321"
            assert result["etag"] == "new_etag_123"
            assert "names" in result
            assert "emailAddresses" in result

            # Verify API was called correctly with expected data
            mock_google_service.people().createContact.assert_called_once_with(body=contact_data)

    @pytest.mark.asyncio
    async def test_update_contact_success(self, mock_auth_service, mock_google_service):
        """Test successful contact update in Google with ETag."""
        from google_contacts_client import GoogleContactsAPIClient

        # Mock the service response
        mock_google_service.people().updateContact().execute.return_value = {
            "resourceName": "people/c123456789",
            "etag": "updated_etag_456",
            "names": [{"displayName": "John Updated", "givenName": "John", "familyName": "Updated"}],
            "emailAddresses": [{"value": "john.updated@example.com"}],
        }

        # Create client
        client = GoogleContactsAPIClient(
            auth_service=mock_auth_service,
            google_account_email="test@example.com",
            google_client_id="client_id",
            google_client_secret="client_secret",
        )

        # Mock the service
        with patch.object(client, "_get_service", return_value=mock_google_service):
            # Reset mock call count after setup
            mock_google_service.people().updateContact.reset_mock()

            # Update contact data
            contact_data = {
                "names": [{"givenName": "John", "familyName": "Updated"}],
                "emailAddresses": [{"value": "john.updated@example.com"}],
            }

            # Execute update with ETag
            result = await client.update_contact(
                resource_name="people/c123456789",
                contact_data=contact_data,
                etag="old_etag_123",
            )

            # Verify result
            assert result["resourceName"] == "people/c123456789"
            assert result["etag"] == "updated_etag_456"

            # Verify API was called correctly
            expected_body = {
                **contact_data,
                "metadata": {"sources": [{"etag": "old_etag_123"}]}
            }
            mock_google_service.people().updateContact.assert_called_once_with(
                resourceName="people/c123456789",
                updatePersonFields="names,emailAddresses",
                body=expected_body
            )

    @pytest.mark.asyncio
    async def test_update_contact_conflict_400_failed_precondition(
        self, mock_auth_service, mock_google_service
    ):
        """Test update contact handles 400 with failedPrecondition (ETag conflict)."""
        from google_contacts_client import GoogleContactsAPIClient
        from googleapiclient.errors import HttpError

        # Mock 400 error response with failedPrecondition
        mock_response = MagicMock()
        mock_response.status = 400
        mock_error = HttpError(
            resp=mock_response,
            content=b'{"error": {"code": 400, "message": "Request person.metadata.sources.etag is different", "status": "FAILED_PRECONDITION"}}',
        )
        mock_google_service.people().updateContact().execute.side_effect = mock_error

        # Create client
        client = GoogleContactsAPIClient(
            auth_service=mock_auth_service,
            google_account_email="test@example.com",
            google_client_id="client_id",
            google_client_secret="client_secret",
        )

        # Mock the service
        with patch.object(client, "_get_service", return_value=mock_google_service):
            contact_data = {
                "names": [{"givenName": "John", "familyName": "Doe"}],
            }

            # Execute update - should raise HttpError with 400
            with pytest.raises(HttpError) as exc_info:
                await client.update_contact(
                    resource_name="people/c123456789",
                    contact_data=contact_data,
                    etag="stale_etag",
                )

            # Verify it's a 400 error with failedPrecondition
            assert exc_info.value.resp.status == 400
            assert b"FAILED_PRECONDITION" in exc_info.value.content


class TestDetectLocalChanges:
    """Test cases for detecting locally created/updated contacts that need to be pushed to Google."""

    @pytest.fixture
    def mock_session(self):
        """Mock database session."""
        mock_session = AsyncMock()
        return mock_session

    @pytest.mark.asyncio
    async def test_find_locally_created_contacts(self, mock_session):
        """Test finding contacts that were created locally (no sync metadata)."""
        from worker import find_contacts_to_push

        # Mock query result - contacts without sync metadata
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            MagicMock(
                id=1,
                first_name="John",
                last_name="Doe",
                middle_name=None,
                nick_name=None,
                is_favourite=False,
                created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
                updated_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
                external_id=None,
                last_synced_at=None,
                version_hash=None,
                sync_action="create",
            ),
            MagicMock(
                id=2,
                first_name="Jane",
                last_name="Smith",
                middle_name=None,
                nick_name=None,
                is_favourite=False,
                created_at=datetime(2024, 1, 2, 12, 0, 0, tzinfo=UTC),
                updated_at=datetime(2024, 1, 2, 12, 0, 0, tzinfo=UTC),
                external_id=None,
                last_synced_at=None,
                version_hash=None,
                sync_action="create",
            ),
        ]
        mock_session.execute.return_value = mock_result

        # Execute
        contacts = await find_contacts_to_push(
            session=mock_session, integration_source="google_contacts"
        )

        # Verify
        assert len(contacts) == 2
        assert contacts[0]["id"] == 1
        assert contacts[0]["first_name"] == "John"
        assert contacts[0]["sync_action"] == "create"
        assert contacts[1]["id"] == 2
        assert contacts[1]["first_name"] == "Jane"
        assert contacts[1]["sync_action"] == "create"

    @pytest.mark.asyncio
    async def test_find_locally_updated_contacts(self, mock_session):
        """Test finding contacts that were updated locally after last sync."""
        from worker import find_contacts_to_push

        # Mock query result - contacts updated after last sync
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            MagicMock(
                id=3,
                first_name="Bob",
                last_name="Johnson",
                middle_name=None,
                nick_name=None,
                is_favourite=False,
                created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
                updated_at=datetime(2024, 1, 5, 14, 30, 0, tzinfo=UTC),
                external_id="people/c123456789",
                last_synced_at=datetime(2024, 1, 3, 10, 0, 0, tzinfo=UTC),
                version_hash="old_hash_123",
                sync_action="update",
            ),
        ]
        mock_session.execute.return_value = mock_result

        # Execute
        contacts = await find_contacts_to_push(
            session=mock_session, integration_source="google_contacts"
        )

        # Verify
        assert len(contacts) == 1
        assert contacts[0]["id"] == 3
        assert contacts[0]["first_name"] == "Bob"
        assert contacts[0]["sync_action"] == "update"
        assert contacts[0]["external_id"] == "people/c123456789"
        # Updated after last sync
        assert contacts[0]["updated_at"] > contacts[0]["last_synced_at"]

    @pytest.mark.asyncio
    async def test_find_no_local_changes(self, mock_session):
        """Test when there are no local changes to push."""
        from worker import find_contacts_to_push

        # Mock empty result
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result

        # Execute
        contacts = await find_contacts_to_push(
            session=mock_session, integration_source="google_contacts"
        )

        # Verify
        assert len(contacts) == 0

    @pytest.mark.asyncio
    async def test_find_mixed_local_changes(self, mock_session):
        """Test finding both newly created and updated contacts."""
        from worker import find_contacts_to_push

        # Mock query result - mix of new and updated contacts
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            # Newly created (no sync metadata)
            MagicMock(
                id=10,
                first_name="Alice",
                last_name="New",
                middle_name=None,
                nick_name=None,
                is_favourite=False,
                created_at=datetime(2024, 1, 10, 12, 0, 0, tzinfo=UTC),
                updated_at=datetime(2024, 1, 10, 12, 0, 0, tzinfo=UTC),
                external_id=None,
                last_synced_at=None,
                version_hash=None,
                sync_action="create",
            ),
            # Updated after sync
            MagicMock(
                id=11,
                first_name="Charlie",
                last_name="Updated",
                middle_name=None,
                nick_name=None,
                is_favourite=False,
                created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
                updated_at=datetime(2024, 1, 11, 15, 0, 0, tzinfo=UTC),
                external_id="people/c987654321",
                last_synced_at=datetime(2024, 1, 5, 10, 0, 0, tzinfo=UTC),
                version_hash="old_hash_456",
                sync_action="update",
            ),
        ]
        mock_session.execute.return_value = mock_result

        # Execute
        contacts = await find_contacts_to_push(
            session=mock_session, integration_source="google_contacts"
        )

        # Verify
        assert len(contacts) == 2
        # First is new
        assert contacts[0]["id"] == 10
        assert contacts[0]["sync_action"] == "create"
        assert contacts[0]["external_id"] is None
        # Second is updated
        assert contacts[1]["id"] == 11
        assert contacts[1]["sync_action"] == "update"
        assert contacts[1]["external_id"] == "people/c987654321"


class TestPushSyncLogic:
    """Test cases for push sync logic (local → Google)."""

    @pytest.fixture
    def mock_session(self):
        """Mock database session."""
        mock_session = AsyncMock()
        return mock_session

    @pytest.fixture
    def mock_google_client(self):
        """Mock Google Contacts API client."""
        mock_client = AsyncMock()
        return mock_client

    @pytest.mark.asyncio
    async def test_push_new_contact_to_google(self, mock_session, mock_google_client):
        """Test pushing a newly created local contact to Google."""
        from worker import push_contacts_to_google

        # Mock local contact to push
        local_contacts = [
            {
                "id": 1,
                "first_name": "Alice",
                "last_name": "New",
                "sync_action": "create",
                "external_id": None,
            }
        ]

        # Mock Google API response
        mock_google_client.create_contact.return_value = {
            "resourceName": "people/c111222333",
            "etag": "new_etag_abc",
            "names": [{"givenName": "Alice", "familyName": "New"}],
        }

        # Mock _load_full_contact to return empty data
        with patch("worker._load_full_contact", new_callable=AsyncMock) as mock_load:
            mock_load.return_value = {
                "methods": [],
                "addresses": [],
                "notes": [],
            }

            # Mock _upsert_sync_metadata
            with patch("worker._upsert_sync_metadata", new_callable=AsyncMock) as mock_upsert:
                # Execute
                result = await push_contacts_to_google(
                    session=mock_session,
                    client=mock_google_client,
                    contacts=local_contacts,
                    google_account_email="test@example.com",
                )

                # Verify
                assert result["pushed_count"] == 1
                assert result["created_count"] == 1
                assert result["updated_count"] == 0
                assert result["error_count"] == 0

                # Verify create_contact was called
                mock_google_client.create_contact.assert_called_once()

                # Verify sync metadata was updated
                mock_upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_push_updated_contact_to_google(self, mock_session, mock_google_client):
        """Test pushing an updated local contact to Google."""
        from worker import push_contacts_to_google

        # Mock local contact to push (already synced, but updated)
        local_contacts = [
            {
                "id": 2,
                "first_name": "Bob",
                "last_name": "Updated",
                "sync_action": "update",
                "external_id": "people/c444555666",
                "version_hash": "old_hash_123",
            }
        ]

        # Mock Google API response
        mock_google_client.update_contact.return_value = {
            "resourceName": "people/c444555666",
            "etag": "updated_etag_xyz",
            "names": [{"givenName": "Bob", "familyName": "Updated"}],
        }

        # Mock _load_full_contact to return empty data
        with patch("worker._load_full_contact", new_callable=AsyncMock) as mock_load:
            mock_load.return_value = {
                "methods": [],
                "addresses": [],
                "notes": [],
            }

            # Mock _upsert_sync_metadata
            with patch("worker._upsert_sync_metadata", new_callable=AsyncMock) as mock_upsert:
                # Execute
                result = await push_contacts_to_google(
                    session=mock_session,
                    client=mock_google_client,
                    contacts=local_contacts,
                    google_account_email="test@example.com",
                )

                # Verify
                assert result["pushed_count"] == 1
                assert result["created_count"] == 0
                assert result["updated_count"] == 1
                assert result["error_count"] == 0

                # Verify update_contact was called
                mock_google_client.update_contact.assert_called_once()

                # Verify sync metadata was updated
                mock_upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_push_handles_conflict_gracefully(
        self, mock_session, mock_google_client
    ):
        """Test push sync handles ETag conflicts gracefully."""
        from googleapiclient.errors import HttpError
        from worker import push_contacts_to_google

        # Mock local contact to push
        local_contacts = [
            {
                "id": 3,
                "first_name": "Charlie",
                "last_name": "Conflict",
                "sync_action": "update",
                "external_id": "people/c777888999",
                "version_hash": "stale_hash",
            }
        ]

        # Mock 400 error with failedPrecondition (ETag conflict)
        mock_response = MagicMock()
        mock_response.status = 400
        mock_error = HttpError(
            resp=mock_response,
            content=b'{"error": {"status": "FAILED_PRECONDITION"}}',
        )
        mock_google_client.update_contact.side_effect = mock_error

        # Mock _load_full_contact to return empty data
        with patch("worker._load_full_contact", new_callable=AsyncMock) as mock_load:
            mock_load.return_value = {
                "methods": [],
                "addresses": [],
                "notes": [],
            }

            # Execute
            result = await push_contacts_to_google(
                session=mock_session,
                client=mock_google_client,
                contacts=local_contacts,
                google_account_email="test@example.com",
            )

            # Verify - should log conflict but not fail entire sync
            assert result["pushed_count"] == 0
            assert result["error_count"] == 1
            assert result["conflict_count"] == 1

    @pytest.mark.asyncio
    async def test_push_mixed_contacts(self, mock_session, mock_google_client):
        """Test pushing a mix of new and updated contacts."""
        from worker import push_contacts_to_google

        # Mock mixed local contacts
        local_contacts = [
            {
                "id": 10,
                "first_name": "New",
                "last_name": "Contact",
                "sync_action": "create",
                "external_id": None,
            },
            {
                "id": 11,
                "first_name": "Updated",
                "last_name": "Contact",
                "sync_action": "update",
                "external_id": "people/c123",
                "version_hash": "hash_123",
            },
        ]

        # Mock Google API responses
        mock_google_client.create_contact.return_value = {
            "resourceName": "people/c_new",
            "etag": "etag_new",
        }
        mock_google_client.update_contact.return_value = {
            "resourceName": "people/c123",
            "etag": "etag_updated",
        }

        # Mock _load_full_contact to return empty data
        with patch("worker._load_full_contact", new_callable=AsyncMock) as mock_load:
            mock_load.return_value = {
                "methods": [],
                "addresses": [],
                "notes": [],
            }

            # Mock _upsert_sync_metadata
            with patch("worker._upsert_sync_metadata", new_callable=AsyncMock) as mock_upsert:
                # Execute
                result = await push_contacts_to_google(
                    session=mock_session,
                    client=mock_google_client,
                    contacts=local_contacts,
                    google_account_email="test@example.com",
                )

                # Verify
                assert result["pushed_count"] == 2
                assert result["created_count"] == 1
                assert result["updated_count"] == 1
                assert result["error_count"] == 0

                # Verify both methods were called
                mock_google_client.create_contact.assert_called_once()
                mock_google_client.update_contact.assert_called_once()

                # Verify sync metadata was updated twice (once for each contact)
                assert mock_upsert.call_count == 2

    @pytest.mark.asyncio
    async def test_push_updates_sync_metadata(self, mock_session, mock_google_client):
        """Test that push sync updates sync_metadata after successful push."""
        from worker import push_contacts_to_google

        # Mock local contact
        local_contacts = [
            {
                "id": 20,
                "first_name": "Test",
                "last_name": "Metadata",
                "sync_action": "create",
                "external_id": None,
            }
        ]

        # Mock Google API response
        mock_google_client.create_contact.return_value = {
            "resourceName": "people/c_metadata_test",
            "etag": "etag_metadata",
        }

        # Mock _load_full_contact to return empty data
        with patch("worker._load_full_contact", new_callable=AsyncMock) as mock_load:
            mock_load.return_value = {
                "methods": [],
                "addresses": [],
                "notes": [],
            }

            # Mock _upsert_sync_metadata
            with patch("worker._upsert_sync_metadata", new_callable=AsyncMock) as mock_upsert:
                # Execute
                result = await push_contacts_to_google(
                    session=mock_session,
                    client=mock_google_client,
                    contacts=local_contacts,
                    google_account_email="test@example.com",
                )

                # Verify sync_metadata was updated
                assert result["pushed_count"] == 1
                mock_upsert.assert_called_once_with(
                    session=mock_session,
                    internal_id=20,
                    external_id="people/c_metadata_test",
                    etag="etag_metadata",
                    integration_source="google_contacts",
                )


if __name__ == "__main__":
    pytest.main([__file__])
