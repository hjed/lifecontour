#!/usr/bin/env python3
"""
Tests for Google Contacts Integration Worker.

Tests the actual sync logic implementation using the Google People API.
"""

# Add core_shared to path for imports
import asyncio
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, "/core_shared")


class TestGoogleWorker:
    """Test cases for Google Contacts worker sync logic."""

    @pytest.fixture
    def mock_session_factory(self):
        """Mock session factory for database operations."""
        # Create a mock row object for database results
        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.job_id = "test-job-id"
        mock_row.user_id = "1"
        mock_row.integration_source = "google"
        mock_row.sync_type = "full"
        mock_row.status = "running"
        mock_row.created_at = datetime.now(UTC)
        mock_row.started_at = None
        mock_row.completed_at = None
        mock_row.error_message = None
        mock_row.contacts_processed = 0
        mock_row.contacts_created = 0
        mock_row.contacts_updated = 0
        mock_row.contacts_deleted = 0
        mock_row.progress = 0
        mock_row.updated_at = datetime.now(UTC)

        # Create mock result for connection.execute()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        mock_result.scalar.return_value = None

        # Create mock connection with proper async behavior
        mock_connection = AsyncMock()

        async def mock_execute(*args, **kwargs):
            # Yield control to event loop (required for async function)
            await asyncio.sleep(0)
            return mock_result

        mock_connection.execute = mock_execute

        # Create mock session with proper async behavior
        mock_session = AsyncMock()
        mock_session.add = MagicMock()

        # Make connection() return the mock connection (it's an async method)
        async def mock_connection_func():
            # Yield control to event loop (required for async function)
            await asyncio.sleep(0)
            return mock_connection

        mock_session.connection = mock_connection_func

        # Mock session.execute to return a result with fetchone and scalar
        mock_session_result = MagicMock()
        mock_session_result.fetchone.return_value = None
        mock_session_result.scalar.return_value = None
        mock_session.execute.return_value = mock_session_result

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
    def mock_google_client(self):
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
        mock_google_client,
    ):
        """Test successful full sync of Google Contacts."""
        # Import the worker function
        from worker import sync_google_contacts

        # Mock the dependencies
        with (
            patch("worker.GoogleAuthService", return_value=mock_google_auth_service),
            patch(
                "worker.GoogleAPIClient",
                return_value=mock_google_client,
            ),
        ):
            # Execute the sync task with session_factory in ctx
            result = await sync_google_contacts(
                ctx={"session_factory": mock_session_factory},
                google_account_email="test@example.com",
                user_id=1,
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
        mock_google_client,
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
                "worker.GoogleAPIClient",
                return_value=mock_google_client,
            ),
        ):
            result = await sync_google_contacts(
                ctx={"session_factory": mock_session_factory},
                google_account_email="test@example.com",
                user_id=1,
                sync_type="incremental",
            )

            assert result["status"] == "success"
            assert result["google_account_email"] == "test@example.com"

    @pytest.mark.asyncio
    async def test_sync_google_contacts_smart_sync_chooses_incremental(
        self,
        mock_session_factory,
        mock_google_auth_service,
        mock_google_client,
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
                "worker.GoogleAPIClient",
                return_value=mock_google_client,
            ),
        ):
            result = await sync_google_contacts(
                ctx={"session_factory": mock_session_factory},
                google_account_email="test@example.com",
                user_id=1,
                sync_type="smart",
            )

            assert result["status"] == "success"
            # Should have used incremental sync - check that sync_token was passed
            # Note: The actual call might have page_size and page_token as well
            calls = mock_google_client.list_connections.call_args_list
            assert len(calls) > 0
            # Check that at least one call had sync_token as a keyword argument
            assert any("sync_token" in call.kwargs for call in calls)

    @pytest.mark.asyncio
    async def test_sync_google_contacts_handles_auth_error(
        self,
        mock_session_factory,
        mock_google_auth_service,
        mock_google_client,
    ):
        """Test sync handles authentication errors gracefully."""
        # Mock client to raise auth error when list_connections is called
        mock_google_client.list_connections.side_effect = Exception("Auth failed")

        from worker import sync_google_contacts

        with (
            patch("worker.GoogleAuthService", return_value=mock_google_auth_service),
            patch(
                "worker.GoogleAPIClient",
                return_value=mock_google_client,
            ),
        ):
            result = await sync_google_contacts(
                ctx={"session_factory": mock_session_factory},
                google_account_email="test@example.com",
                user_id=1,
                sync_type="full",
            )

            assert result["status"] == "error"
            assert "Auth failed" in result["error"]

    @pytest.mark.asyncio
    async def test_sync_google_contacts_handles_api_error(
        self,
        mock_session_factory,
        mock_google_auth_service,
        mock_google_client,
    ):
        """Test sync handles Google API errors gracefully."""
        # Mock API client to raise error
        mock_google_client.list_connections.side_effect = Exception("API error")

        from worker import sync_google_contacts

        with (
            patch("worker.GoogleAuthService", return_value=mock_google_auth_service),
            patch(
                "worker.GoogleAPIClient",
                return_value=mock_google_client,
            ),
        ):
            result = await sync_google_contacts(
                ctx={"session_factory": mock_session_factory},
                google_account_email="test@example.com",
                user_id=1,
                sync_type="full",
            )

            assert result["status"] == "error"
            assert "API error" in result["error"]

    def test_process_contacts_batch_partial_failure(self):
        """Test that a single invalid contact does not fail the entire batch."""
        from worker import _process_contacts_batch

        # Mock transformer
        mock_transformer = MagicMock()
        mock_transformer.transform_person.side_effect = [
            MagicMock(id=1),
            Exception("Invalid contact data"),
            MagicMock(id=3),
        ]

        # Mock connections
        connections = [
            MagicMock(resource_name="people/1"),
            MagicMock(resource_name="people/2"),
            MagicMock(resource_name="people/3"),
        ]

        metrics = {"errors": 0}

        with patch("worker.serialize_contact", side_effect=[{"id": 1}, {"id": 3}]):
            result = _process_contacts_batch(
                connections, mock_transformer, "test@example.com", metrics
            )

            assert len(result) == 2
            assert result[0][0] == connections[0]
            assert result[0][1] == {"id": 1}
            assert result[1][0] == connections[2]
            assert result[1][1] == {"id": 3}
            assert metrics["errors"] == 1

    @pytest.mark.asyncio
    async def test_perform_full_sync_uses_partial_batch_processing(self):
        """Test full sync keeps valid contacts when a page contains invalid data."""
        from worker import _perform_full_sync

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_client = AsyncMock()
        mock_client.list_connections.return_value = {
            "connections": [
                {"resourceName": "people/1", "etag": "etag-1"},
                {"resourceName": "people/2", "etag": "etag-2"},
            ],
            "nextSyncToken": "sync-token-123",
        }
        metrics = {"contacts_processed": 0, "errors": 0}
        processed_contacts = [
            (
                MagicMock(resource_name="people/2", etag="etag-2"),
                {
                    "first_name": "Valid",
                    "methods": [],
                    "addresses": [],
                    "notes": [],
                    "tags": [],
                },
            )
        ]

        with (
            patch(
                "worker._process_contacts_batch", return_value=processed_contacts
            ) as mock_process,
            patch(
                "worker._save_sync_token", new_callable=AsyncMock
            ) as mock_save_sync_token,
            patch(
                "worker.OutboxEvent.create_contact_sync_event", return_value=MagicMock()
            ),
            patch(
                "worker._find_existing_external_ids",
                new_callable=AsyncMock,
                return_value=set(),
            ),
        ):
            result = await _perform_full_sync(
                session=mock_session,
                client=mock_client,
                google_account_email="test@example.com",
                metrics=metrics,
                user_id=1,
            )

        assert result == {"contacts_created": 1, "contacts_updated": 0}
        assert metrics["contacts_processed"] == 1
        mock_process.assert_called_once()
        assert mock_session.add.call_count == 1
        mock_save_sync_token.assert_awaited_once_with(
            mock_session, "test@example.com", "sync-token-123", 1
        )

    @pytest.mark.asyncio
    async def test_perform_full_sync_uses_created_for_new_contacts(self):
        """Test full sync uses sync_type='created' for contacts without existing sync metadata."""
        from worker import _perform_full_sync

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_client = AsyncMock()
        mock_client.list_connections.return_value = {
            "connections": [
                {"resourceName": "people/new1", "etag": "etag-new1"},
            ],
            "nextSyncToken": "sync-token-new",
        }
        metrics = {"contacts_processed": 0, "errors": 0}
        processed_contacts = [
            (
                MagicMock(resource_name="people/new1", etag="etag-new1"),
                {
                    "first_name": "New",
                    "methods": [],
                    "addresses": [],
                    "notes": [],
                    "tags": [],
                },
            )
        ]

        mock_create_event = MagicMock(return_value=MagicMock())

        with (
            patch("worker._process_contacts_batch", return_value=processed_contacts),
            patch("worker._save_sync_token", new_callable=AsyncMock),
            patch("worker.OutboxEvent.create_contact_sync_event", mock_create_event),
            patch(
                "worker._find_existing_external_ids",
                new_callable=AsyncMock,
                return_value=set(),
            ),
        ):
            result = await _perform_full_sync(
                session=mock_session,
                client=mock_client,
                google_account_email="test@example.com",
                metrics=metrics,
                user_id=1,
            )

        assert result["contacts_created"] == 1
        assert result["contacts_updated"] == 0
        mock_create_event.assert_called_once()
        _, kwargs = mock_create_event.call_args
        assert kwargs["sync_type"] == "created"

    @pytest.mark.asyncio
    async def test_perform_full_sync_uses_updated_for_existing_contacts(self):
        """Test full sync uses sync_type='updated' for contacts with existing sync metadata."""
        from worker import _perform_full_sync

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_client = AsyncMock()
        mock_client.list_connections.return_value = {
            "connections": [
                {"resourceName": "people/existing1", "etag": "etag-existing1"},
            ],
            "nextSyncToken": "sync-token-existing",
        }
        metrics = {"contacts_processed": 0, "errors": 0}
        processed_contacts = [
            (
                MagicMock(resource_name="people/existing1", etag="etag-existing1"),
                {
                    "first_name": "Existing",
                    "methods": [],
                    "addresses": [],
                    "notes": [],
                    "tags": [],
                },
            )
        ]

        mock_create_event = MagicMock(return_value=MagicMock())

        with (
            patch("worker._process_contacts_batch", return_value=processed_contacts),
            patch("worker._save_sync_token", new_callable=AsyncMock),
            patch("worker.OutboxEvent.create_contact_sync_event", mock_create_event),
            patch(
                "worker._find_existing_external_ids",
                new_callable=AsyncMock,
                return_value={"people/existing1"},
            ),
        ):
            result = await _perform_full_sync(
                session=mock_session,
                client=mock_client,
                google_account_email="test@example.com",
                metrics=metrics,
                user_id=1,
            )

        assert result["contacts_created"] == 0
        assert result["contacts_updated"] == 1
        mock_create_event.assert_called_once()
        _, kwargs = mock_create_event.call_args
        assert kwargs["sync_type"] == "updated"

    @pytest.mark.asyncio
    async def test_perform_full_sync_mixed_new_and_existing(self):
        """Test full sync correctly differentiates new and existing contacts in same batch."""
        from worker import _perform_full_sync

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_client = AsyncMock()
        mock_client.list_connections.return_value = {
            "connections": [
                {"resourceName": "people/new1", "etag": "etag-new1"},
                {"resourceName": "people/existing1", "etag": "etag-existing1"},
            ],
            "nextSyncToken": "sync-token-mixed",
        }
        metrics = {"contacts_processed": 0, "errors": 0}
        processed_contacts = [
            (
                MagicMock(resource_name="people/new1", etag="etag-new1"),
                {
                    "first_name": "New",
                    "methods": [],
                    "addresses": [],
                    "notes": [],
                    "tags": [],
                },
            ),
            (
                MagicMock(resource_name="people/existing1", etag="etag-existing1"),
                {
                    "first_name": "Existing",
                    "methods": [],
                    "addresses": [],
                    "notes": [],
                    "tags": [],
                },
            ),
        ]

        mock_create_event = MagicMock(return_value=MagicMock())

        with (
            patch("worker._process_contacts_batch", return_value=processed_contacts),
            patch("worker._save_sync_token", new_callable=AsyncMock),
            patch("worker.OutboxEvent.create_contact_sync_event", mock_create_event),
            patch(
                "worker._find_existing_external_ids",
                new_callable=AsyncMock,
                return_value={"people/existing1"},
            ),
        ):
            result = await _perform_full_sync(
                session=mock_session,
                client=mock_client,
                google_account_email="test@example.com",
                metrics=metrics,
                user_id=1,
            )

        assert result["contacts_created"] == 1
        assert result["contacts_updated"] == 1
        assert mock_create_event.call_count == 2

        # Verify sync_types match the expected values
        calls = mock_create_event.call_args_list
        sync_types = {
            call.kwargs["external_id"]: call.kwargs["sync_type"] for call in calls
        }
        assert sync_types["people/new1"] == "created"
        assert sync_types["people/existing1"] == "updated"

    @pytest.mark.asyncio
    async def test_perform_incremental_sync_uses_partial_batch_processing(self):
        """Test incremental sync keeps valid contacts when a batch contains invalid data."""
        from worker import _perform_incremental_sync

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        sync_token_result = MagicMock()
        sync_token_result.scalar.return_value = "existing-sync-token"
        mock_session.execute.return_value = sync_token_result

        mock_client = AsyncMock()
        mock_client.list_connections.return_value = {
            "connections": [
                {"resourceName": "people/1", "etag": "etag-1"},
                {"resourceName": "people/2", "etag": "etag-2"},
            ]
        }
        metrics = {"contacts_processed": 0, "errors": 0}
        processed_contacts = [
            (
                MagicMock(resource_name="people/2", etag="etag-2"),
                {
                    "first_name": "Valid",
                    "methods": [],
                    "addresses": [],
                    "notes": [],
                    "tags": [],
                },
            )
        ]

        with (
            patch(
                "worker._process_contacts_batch", return_value=processed_contacts
            ) as mock_process,
            patch(
                "worker.OutboxEvent.create_contact_sync_event", return_value=MagicMock()
            ),
        ):
            result = await _perform_incremental_sync(
                session=mock_session,
                client=mock_client,
                google_account_email="test@example.com",
                metrics=metrics,
                user_id=1,
            )

        # No sync_metadata exists for the contact, so it is emitted as 'created'.
        assert result == {"contacts_created": 1, "contacts_updated": 0}
        assert metrics["contacts_processed"] == 1
        mock_process.assert_called_once()
        assert mock_session.add.call_count == 1


class TestGoogleAPIClient:
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
        from google_client import GoogleAPIClient

        # Mock the service response
        mock_google_service.people().createContact().execute.return_value = {
            "resourceName": "people/c987654321",
            "etag": "new_etag_123",
            "names": [
                {
                    "displayName": "Jane Smith",
                    "givenName": "Jane",
                    "familyName": "Smith",
                }
            ],
            "emailAddresses": [{"value": "jane@example.com"}],
        }

        # Create client
        client = GoogleAPIClient(
            auth_service=mock_auth_service,
            google_account_email="test@example.com",
            google_client_id="client_id",
            google_client_secret="client_secret",
            user_id=1,
        )

        # Mock the service
        with patch.object(
            client, "_get_people_service", return_value=mock_google_service
        ):
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
            mock_google_service.people().createContact.assert_called_once_with(
                body=contact_data
            )

    @pytest.mark.asyncio
    async def test_update_contact_success(self, mock_auth_service, mock_google_service):
        """Test successful contact update in Google with ETag."""
        from google_client import GoogleAPIClient

        # Mock the service response
        mock_google_service.people().updateContact().execute.return_value = {
            "resourceName": "people/c123456789",
            "etag": "updated_etag_456",
            "names": [
                {
                    "displayName": "John Updated",
                    "givenName": "John",
                    "familyName": "Updated",
                }
            ],
            "emailAddresses": [{"value": "john.updated@example.com"}],
        }

        # Create client
        client = GoogleAPIClient(
            auth_service=mock_auth_service,
            google_account_email="test@example.com",
            google_client_id="client_id",
            google_client_secret="client_secret",
            user_id=1,
        )

        # Mock the service
        with patch.object(
            client, "_get_people_service", return_value=mock_google_service
        ):
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

            # Verify API was called correctly — etag goes in the top-level
            # person.etag field, NOT under metadata.sources.
            expected_body = {
                **contact_data,
                "etag": "old_etag_123",
            }
            mock_google_service.people().updateContact.assert_called_once_with(
                resourceName="people/c123456789",
                updatePersonFields="names,emailAddresses",
                body=expected_body,
            )
            # Regression guard for the "must set person.etag" 400 error: the
            # etag must be top-level and never nested under metadata.sources.
            sent_body = mock_google_service.people().updateContact.call_args.kwargs[
                "body"
            ]
            assert sent_body["etag"] == "old_etag_123"
            assert "metadata" not in sent_body

    @pytest.mark.asyncio
    async def test_update_contact_conflict_refetches_etag_and_retries(
        self, mock_auth_service, mock_google_service
    ):
        """A stale-etag 400 triggers a re-fetch of the fresh etag and one retry."""
        from googleapiclient.errors import HttpError

        from google_client import GoogleAPIClient

        # First update attempt fails with a stale-etag conflict; second succeeds.
        mock_response = MagicMock()
        mock_response.status = 400
        conflict_error = HttpError(
            resp=mock_response,
            content=b'{"error": {"code": 400, "message": "Request etag is different", "status": "FAILED_PRECONDITION"}}',
        )
        success_result = {
            "resourceName": "people/c123456789",
            "etag": "updated_etag_after_retry",
            "names": [{"givenName": "John", "familyName": "Doe"}],
        }
        mock_google_service.people().updateContact().execute.side_effect = [
            conflict_error,
            success_result,
        ]
        # get_person returns the fresh etag from Google.
        mock_google_service.people().get().execute.return_value = {
            "resourceName": "people/c123456789",
            "etag": "fresh_etag_999",
        }

        client = GoogleAPIClient(
            auth_service=mock_auth_service,
            google_account_email="test@example.com",
            google_client_id="client_id",
            google_client_secret="client_secret",
            user_id=1,
        )

        with patch.object(
            client, "_get_people_service", return_value=mock_google_service
        ):
            mock_google_service.people().updateContact.reset_mock()
            mock_google_service.people().get.reset_mock()

            contact_data = {"names": [{"givenName": "John", "familyName": "Doe"}]}

            result = await client.update_contact(
                resource_name="people/c123456789",
                contact_data=contact_data,
                etag="stale_etag",
            )

            # The retry succeeded and returned the fresh result.
            assert result["etag"] == "updated_etag_after_retry"
            # We refetched exactly once and updated twice.
            assert mock_google_service.people().get.call_count == 1
            assert mock_google_service.people().updateContact.call_count == 2
            # The retry used the freshly-fetched top-level etag.
            retry_body = mock_google_service.people().updateContact.call_args.kwargs[
                "body"
            ]
            assert retry_body["etag"] == "fresh_etag_999"

    @pytest.mark.asyncio
    async def test_update_contact_conflict_retry_exhausted_raises(
        self, mock_auth_service, mock_google_service
    ):
        """When the retry also conflicts, the error propagates after one retry."""
        from googleapiclient.errors import HttpError

        from google_client import GoogleAPIClient

        mock_response = MagicMock()
        mock_response.status = 400
        conflict_error = HttpError(
            resp=mock_response,
            content=b'{"error": {"code": 400, "message": "Request etag is different", "status": "FAILED_PRECONDITION"}}',
        )
        mock_google_service.people().updateContact().execute.side_effect = (
            conflict_error
        )
        mock_google_service.people().get().execute.return_value = {
            "resourceName": "people/c123456789",
            "etag": "fresh_etag_999",
        }

        client = GoogleAPIClient(
            auth_service=mock_auth_service,
            google_account_email="test@example.com",
            google_client_id="client_id",
            google_client_secret="client_secret",
            user_id=1,
        )

        with patch.object(
            client, "_get_people_service", return_value=mock_google_service
        ):
            mock_google_service.people().updateContact.reset_mock()
            mock_google_service.people().get.reset_mock()

            contact_data = {"names": [{"givenName": "John", "familyName": "Doe"}]}

            with pytest.raises(HttpError) as exc_info:
                await client.update_contact(
                    resource_name="people/c123456789",
                    contact_data=contact_data,
                    etag="stale_etag",
                )

            assert exc_info.value.resp.status == 400
            assert b"FAILED_PRECONDITION" in exc_info.value.content
            # Exactly one retry: two update attempts, one refetch.
            assert mock_google_service.people().get.call_count == 1
            assert mock_google_service.people().updateContact.call_count == 2

    @pytest.mark.asyncio
    async def test_update_contact_non_conflict_400_not_retried(
        self, mock_auth_service, mock_google_service
    ):
        """A non-etag 400 (e.g. bad request) raises immediately without a refetch."""
        from googleapiclient.errors import HttpError

        from google_client import GoogleAPIClient

        mock_response = MagicMock()
        mock_response.status = 400
        bad_request_error = HttpError(
            resp=mock_response,
            content=b'{"error": {"code": 400, "message": "Invalid field mask", "status": "INVALID_ARGUMENT"}}',
        )
        mock_google_service.people().updateContact().execute.side_effect = (
            bad_request_error
        )

        client = GoogleAPIClient(
            auth_service=mock_auth_service,
            google_account_email="test@example.com",
            google_client_id="client_id",
            google_client_secret="client_secret",
            user_id=1,
        )

        with patch.object(
            client, "_get_people_service", return_value=mock_google_service
        ):
            mock_google_service.people().updateContact.reset_mock()
            mock_google_service.people().get.reset_mock()

            contact_data = {"names": [{"givenName": "John", "familyName": "Doe"}]}

            with pytest.raises(HttpError) as exc_info:
                await client.update_contact(
                    resource_name="people/c123456789",
                    contact_data=contact_data,
                    etag="some_etag",
                )

            assert exc_info.value.resp.status == 400
            # No refetch, no retry.
            assert mock_google_service.people().get.call_count == 0
            assert mock_google_service.people().updateContact.call_count == 1

    @staticmethod
    def _http_error(status: int, message: str, reason: str) -> Any:
        """An ``HttpError`` with the given status and Google error body."""
        from googleapiclient.errors import HttpError

        mock_response = MagicMock()
        mock_response.status = status
        body = (
            f'{{"error": {{"code": {status}, "message": "{message}", '
            f'"status": "{reason}"}}}}'
        )
        return HttpError(resp=mock_response, content=body.encode())

    def _client(self, mock_auth_service: Any) -> Any:
        from google_client import GoogleAPIClient

        return GoogleAPIClient(
            auth_service=mock_auth_service,
            google_account_email="test@example.com",
            google_client_id="client_id",
            google_client_secret="client_secret",
            user_id=1,
        )

    @pytest.mark.asyncio
    async def test_update_contact_404_raises_contact_not_found(
        self, mock_auth_service: Any, mock_google_service: MagicMock
    ) -> None:
        """A contact deleted on Google's side surfaces as a typed not-found."""
        from google_client import GoogleContactNotFoundError

        not_found = self._http_error(
            404, "Requested entity was not found.", "NOT_FOUND"
        )
        mock_google_service.people().updateContact().execute.side_effect = not_found
        client = self._client(mock_auth_service)

        with patch.object(
            client, "_get_people_service", return_value=mock_google_service
        ):
            mock_google_service.people().get.reset_mock()
            with pytest.raises(GoogleContactNotFoundError) as exc_info:
                await client.update_contact(
                    resource_name="people/cGONE",
                    contact_data={"names": [{"givenName": "Gone"}]},
                    etag="some_etag",
                )

        assert exc_info.value.resource_name == "people/cGONE"
        assert exc_info.value.__cause__ is not_found
        assert mock_google_service.people().get.call_count == 0

    @pytest.mark.asyncio
    async def test_update_contact_404_on_conflict_refetch_raises_contact_not_found(
        self, mock_auth_service: Any, mock_google_service: MagicMock
    ) -> None:
        """A contact deleted between the etag conflict and its refetch is not-found."""
        from google_client import GoogleContactNotFoundError

        mock_google_service.people().updateContact().execute.side_effect = (
            self._http_error(400, "Request etag is different", "FAILED_PRECONDITION")
        )
        mock_google_service.people().get().execute.side_effect = self._http_error(
            404, "Requested entity was not found.", "NOT_FOUND"
        )
        client = self._client(mock_auth_service)

        with patch.object(
            client, "_get_people_service", return_value=mock_google_service
        ):
            with pytest.raises(GoogleContactNotFoundError) as exc_info:
                await client.update_contact(
                    resource_name="people/cGONE",
                    contact_data={"names": [{"givenName": "Gone"}]},
                    etag="stale_etag",
                )

        assert exc_info.value.resource_name == "people/cGONE"

    @pytest.mark.asyncio
    async def test_update_contact_404_on_conflict_retry_raises_contact_not_found(
        self, mock_auth_service: Any, mock_google_service: MagicMock
    ) -> None:
        """A contact deleted between the refetch and the retried update is not-found."""
        from google_client import GoogleContactNotFoundError

        mock_google_service.people().updateContact().execute.side_effect = [
            self._http_error(400, "Request etag is different", "FAILED_PRECONDITION"),
            self._http_error(404, "Requested entity was not found.", "NOT_FOUND"),
        ]
        mock_google_service.people().get().execute.return_value = {
            "resourceName": "people/cGONE",
            "etag": "fresh_etag",
        }
        client = self._client(mock_auth_service)

        with patch.object(
            client, "_get_people_service", return_value=mock_google_service
        ):
            with pytest.raises(GoogleContactNotFoundError) as exc_info:
                await client.update_contact(
                    resource_name="people/cGONE",
                    contact_data={"names": [{"givenName": "Gone"}]},
                    etag="stale_etag",
                )

        assert exc_info.value.resource_name == "people/cGONE"

    @pytest.mark.asyncio
    async def test_update_contact_server_error_still_raises_http_error(
        self, mock_auth_service: Any, mock_google_service: MagicMock
    ) -> None:
        """Only a 404 becomes not-found; other failures keep their HttpError."""
        from googleapiclient.errors import HttpError

        mock_google_service.people().updateContact().execute.side_effect = (
            self._http_error(500, "Internal error", "INTERNAL")
        )
        client = self._client(mock_auth_service)

        with patch.object(
            client, "_get_people_service", return_value=mock_google_service
        ):
            with pytest.raises(HttpError) as exc_info:
                await client.update_contact(
                    resource_name="people/c123",
                    contact_data={"names": [{"givenName": "John"}]},
                )

        assert exc_info.value.resp.status == 500

    @pytest.mark.asyncio
    async def test_update_contact_empty_fields_raises_error(
        self, mock_auth_service, mock_google_service
    ):
        """Test that updating with empty contact_data raises ValueError."""
        from google_client import GoogleAPIClient

        # Create client
        client = GoogleAPIClient(
            auth_service=mock_auth_service,
            google_account_email="test@example.com",
            google_client_id="client_id",
            google_client_secret="client_secret",
            user_id=1,
        )

        # Mock the service
        with patch.object(
            client, "_get_people_service", return_value=mock_google_service
        ):
            # Empty contact data (only metadata/resourceName/etag)
            contact_data = {
                "metadata": {"sources": [{"etag": "some_etag"}]},
            }

            # Execute update - should raise ValueError
            with pytest.raises(ValueError) as exc_info:
                await client.update_contact(
                    resource_name="people/c123456789",
                    contact_data=contact_data,
                    etag="some_etag",
                )

            # Verify error message
            assert "No fields to update" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_list_calendars_success(self, mock_auth_service, mock_google_service):
        """Test successful fetching of calendars."""
        from google_client import GoogleAPIClient

        mock_list = mock_google_service.calendarList.return_value.list
        mock_list.return_value.execute.return_value = {
            "items": [{"id": "cal1", "summary": "Primary"}],
            "nextPageToken": "token123",
        }

        client = GoogleAPIClient(
            auth_service=mock_auth_service,
            google_account_email="test@example.com",
            google_client_id="client_id",
            google_client_secret="client_secret",
            user_id=1,
        )

        with patch.object(
            client, "_get_calendar_service", return_value=mock_google_service
        ):
            result = await client.list_calendars(page_token="token123")

            assert len(result["items"]) == 1
            assert result["items"][0]["id"] == "cal1"
            mock_list.assert_called_once_with(maxResults=250, pageToken="token123")

    @pytest.mark.asyncio
    async def test_list_events_success(self, mock_auth_service, mock_google_service):
        """Test successful fetching of events."""
        from google_client import GoogleAPIClient

        mock_list = mock_google_service.events.return_value.list
        mock_list.return_value.execute.return_value = {
            "items": [{"id": "ev1", "summary": "Meeting"}],
            "nextSyncToken": "syncToken456",
        }

        client = GoogleAPIClient(
            auth_service=mock_auth_service,
            google_account_email="test@example.com",
            google_client_id="client_id",
            google_client_secret="client_secret",
            user_id=1,
        )

        with patch.object(
            client, "_get_calendar_service", return_value=mock_google_service
        ):
            result = await client.list_events(
                calendar_id="primary", sync_token="syncToken456"
            )

            assert len(result["items"]) == 1
            assert result["items"][0]["id"] == "ev1"
            mock_list.assert_called_once_with(
                calendarId="primary", maxResults=2500, syncToken="syncToken456"
            )


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
            session=mock_session, integration_source="google"
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
            session=mock_session, integration_source="google"
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
            session=mock_session, integration_source="google"
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
            session=mock_session, integration_source="google"
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

    @pytest.fixture(autouse=True)
    def _no_contact_link(self) -> Iterator[None]:
        """Stub the per-contact lock and link re-read, like the other DB helpers.

        These tests drive ``push_contacts_to_google`` with a bare ``AsyncMock``
        session and patch its database helpers. The push now locks each contact
        and re-reads its link under the lock; with no link the list's
        ``sync_action`` stands, which is what these tests exercise.
        """
        with (
            patch("worker._lock_contact_for_push", new_callable=AsyncMock),
            patch("worker._read_sync_link", new_callable=AsyncMock, return_value=None),
        ):
            yield

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
            with patch(
                "worker._upsert_sync_metadata", new_callable=AsyncMock
            ) as mock_upsert:
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
    async def test_push_updated_contact_to_google(
        self, mock_session, mock_google_client
    ):
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
            with patch(
                "worker._upsert_sync_metadata", new_callable=AsyncMock
            ) as mock_upsert:
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
    async def test_push_handles_412_conflict(self, mock_session, mock_google_client):
        """Test push sync handles 412 Precondition Failed (standard HTTP conflict)."""
        from googleapiclient.errors import HttpError

        from worker import push_contacts_to_google

        # Mock local contact to push
        local_contacts = [
            {
                "id": 4,
                "first_name": "Dave",
                "last_name": "Conflict412",
                "sync_action": "update",
                "external_id": "people/c888999000",
                "version_hash": "stale_hash_412",
            }
        ]

        # Mock 412 error (standard HTTP precondition failed)
        mock_response = MagicMock()
        mock_response.status = 412
        mock_error = HttpError(
            resp=mock_response,
            content=b'{"error": {"message": "Precondition Failed"}}',
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
            with patch(
                "worker._upsert_sync_metadata", new_callable=AsyncMock
            ) as mock_upsert:
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
            with patch(
                "worker._upsert_sync_metadata", new_callable=AsyncMock
            ) as mock_upsert:
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
                    integration_source="google",
                )


class TestUpsertSyncMetadataEntityTypes:
    """Dual-write: worker sync_metadata writes carry contact/person entity types."""

    @pytest.mark.asyncio
    async def test_upsert_sync_metadata_writes_contact_person_entity_types(self):
        """``_upsert_sync_metadata`` persists the internal/external entity types.

        Consolidating links onto ``sync_metadata`` needs every writer (including
        the Google outbound worker's direct-SQL upsert) to populate the entity
        types so the canonical link store stays complete.
        """
        from worker import _upsert_sync_metadata

        session = AsyncMock()

        await _upsert_sync_metadata(
            session=session,
            internal_id=20,
            external_id="people/c_entity_types",
            etag="etag-1",
            integration_source="google",
        )

        session.execute.assert_called_once()
        stmt, params = session.execute.call_args[0]
        sql = str(stmt)
        assert "internal_entity_type" in sql
        assert "external_entity_type" in sql
        assert params["internal_entity_type"] == "contact"
        assert params["external_entity_type"] == "person"


class TestContactTypeNormalization:
    """Test cases for contact type normalization."""

    def test_normalize_work_labels(self):
        """Test normalization of work-related labels."""
        from worker import _normalize_contact_type

        assert _normalize_contact_type("work") == "work"
        assert _normalize_contact_type("Work") == "work"
        assert _normalize_contact_type("WORK") == "work"
        assert _normalize_contact_type("office") == "work"
        assert _normalize_contact_type("Office") == "work"
        assert _normalize_contact_type("business") == "work"
        assert _normalize_contact_type("Business") == "work"

    def test_normalize_home_labels(self):
        """Test normalization of home-related labels."""
        from worker import _normalize_contact_type

        assert _normalize_contact_type("home") == "home"
        assert _normalize_contact_type("Home") == "home"
        assert _normalize_contact_type("HOME") == "home"
        assert _normalize_contact_type("personal") == "home"
        assert _normalize_contact_type("Personal") == "home"

    def test_normalize_mobile_and_main(self):
        """Test normalization of mobile and main labels."""
        from worker import _normalize_contact_type

        assert _normalize_contact_type("mobile") == "mobile"
        assert _normalize_contact_type("Mobile") == "mobile"
        assert _normalize_contact_type("main") == "main"
        assert _normalize_contact_type("Main") == "main"

    def test_normalize_other_label(self):
        """Test normalization of 'other' label."""
        from worker import _normalize_contact_type

        assert _normalize_contact_type("other") == "other"
        assert _normalize_contact_type("Other") == "other"

    def test_normalize_empty_label(self):
        """Test normalization of empty/None label."""
        from worker import _normalize_contact_type

        assert _normalize_contact_type("") == "other"
        assert _normalize_contact_type(None) == "other"

    def test_normalize_unknown_label_passthrough(self):
        """Test that unknown labels are passed through unchanged."""
        from worker import _normalize_contact_type

        assert _normalize_contact_type("custom_label") == "custom_label"
        assert _normalize_contact_type("Fax") == "Fax"
        assert _normalize_contact_type("Assistant") == "Assistant"

    def test_normalize_whitespace_handling(self):
        """Test that whitespace is handled correctly."""
        from worker import _normalize_contact_type

        assert _normalize_contact_type("  work  ") == "work"
        assert _normalize_contact_type("  Home  ") == "home"


class TestOrganizationTransformation:
    """Test cases for organization transformation functions."""

    def test_transform_organizations_with_both_fields(self):
        """Test transformation when both company and job_title are present."""
        from worker import _transform_organizations

        contact = {
            "company": "Tech Corp",
            "job_title": "Senior Developer",
        }

        result = _transform_organizations(contact)

        assert result is not None
        assert len(result) == 1
        assert result[0]["name"] == "Tech Corp"
        assert result[0]["title"] == "Senior Developer"
        assert result[0]["current"] is True

    def test_transform_organizations_with_company_only(self):
        """Test transformation when only company is present."""
        from worker import _transform_organizations

        contact = {
            "company": "Tech Corp",
            "job_title": None,
        }

        result = _transform_organizations(contact)

        assert result is not None
        assert len(result) == 1
        assert result[0]["name"] == "Tech Corp"
        assert "title" not in result[0]
        assert result[0]["current"] is True

    def test_transform_organizations_with_job_title_only(self):
        """Test transformation when only job_title is present."""
        from worker import _transform_organizations

        contact = {
            "company": None,
            "job_title": "Freelance Developer",
        }

        result = _transform_organizations(contact)

        assert result is not None
        assert len(result) == 1
        assert "name" not in result[0]
        assert result[0]["title"] == "Freelance Developer"
        assert result[0]["current"] is True

    def test_transform_organizations_with_no_fields(self):
        """Test transformation when neither company nor job_title are present."""
        from worker import _transform_organizations

        contact = {
            "company": None,
            "job_title": None,
        }

        result = _transform_organizations(contact)

        assert result is None

    def test_transform_organizations_with_missing_keys(self):
        """Test transformation when keys are missing from contact dict."""
        from worker import _transform_organizations

        contact = {}

        result = _transform_organizations(contact)

        assert result is None

    def test_transform_contact_to_google_person_includes_organizations(self):
        """Test that _transform_contact_to_google_person includes organizations."""
        from worker import _transform_contact_to_google_person

        contact = {
            "first_name": "John",
            "last_name": "Doe",
            "company": "Tech Corp",
            "job_title": "Senior Developer",
            "methods": [],
            "addresses": [],
            "notes": [],
        }

        result = _transform_contact_to_google_person(contact)

        assert "organizations" in result
        assert len(result["organizations"]) == 1
        assert result["organizations"][0]["name"] == "Tech Corp"
        assert result["organizations"][0]["title"] == "Senior Developer"
        assert result["organizations"][0]["current"] is True


if __name__ == "__main__":
    pytest.main([__file__])


class TestArchivedValuesAreNotPushed:
    """An archived email, phone or address is never sent to Google.

    The payload replaces Google's lists whole, so leaving an archived value out
    is what removes an already-synced one from Google.
    """

    def test_archived_methods_are_left_out(self) -> None:
        from worker import _transform_contact_to_google_person

        person = _transform_contact_to_google_person(
            {
                "first_name": "Ada",
                "methods": [
                    {
                        "method_type": "email",
                        "value": "now@example.com",
                        "label": None,
                        "is_primary": True,
                        "is_archived": False,
                    },
                    {
                        "method_type": "email",
                        "value": "then@example.com",
                        "label": None,
                        "is_primary": False,
                        "is_archived": True,
                    },
                    {
                        "method_type": "phone",
                        "value": "+44 20 7946 0000",
                        "label": None,
                        "is_primary": False,
                        "is_archived": True,
                    },
                ],
                "addresses": [],
            }
        )

        assert [e["value"] for e in person["emailAddresses"]] == ["now@example.com"]
        # Still sent, empty: that is what removes the archived phone in Google.
        assert person["phoneNumbers"] == []

    def test_archived_addresses_are_left_out(self) -> None:
        from worker import _transform_contact_to_google_person

        person = _transform_contact_to_google_person(
            {
                "first_name": "Ada",
                "methods": [],
                "addresses": [
                    {
                        "street_line_1": "1 Childhood Rd",
                        "country_code": "AU",
                        "is_primary": False,
                        "is_archived": True,
                    }
                ],
            }
        )

        assert person["addresses"] == []
