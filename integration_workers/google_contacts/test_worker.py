#!/usr/bin/env python3
"""
Tests for Google Contacts Integration Worker.

Tests the actual sync logic implementation using the Google People API.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, UTC
from typing import Any

# Add core_shared to path for imports
import sys

sys.path.insert(0, "/core_shared")

from core_shared.database.engine import create_session_factory
from core_shared.models.sync_metadata import SyncMetadata, SyncStatus


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
            patch("worker.session_factory", mock_session_factory),
            patch("worker.GoogleAuthService", return_value=mock_google_auth_service),
            patch(
                "worker.GoogleContactsAPIClient",
                return_value=mock_google_contacts_client,
            ),
        ):
            # Execute the sync task
            result = await sync_google_contacts(
                ctx={"logger": MagicMock()},
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
            patch("worker.session_factory", mock_session_factory),
            patch("worker.GoogleAuthService", return_value=mock_google_auth_service),
            patch(
                "worker.GoogleContactsAPIClient",
                return_value=mock_google_contacts_client,
            ),
        ):
            result = await sync_google_contacts(
                ctx={"logger": MagicMock()},
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
        mock_session.execute.return_value.fetchone.return_value = {
            "sync_token": "existing_sync_token"
        }

        from worker import sync_google_contacts

        with (
            patch("worker.session_factory", mock_session_factory),
            patch("worker.GoogleAuthService", return_value=mock_google_auth_service),
            patch(
                "worker.GoogleContactsAPIClient",
                return_value=mock_google_contacts_client,
            ),
        ):
            result = await sync_google_contacts(
                ctx={"logger": MagicMock()},
                google_account_email="test@example.com",
                sync_type="smart",
            )

            assert result["status"] == "success"
            # Should have used incremental sync
            mock_google_contacts_client.list_connections.assert_called_with(
                sync_token="existing_sync_token"
            )

    @pytest.mark.asyncio
    async def test_sync_google_contacts_handles_auth_error(
        self,
        mock_session_factory,
        mock_google_auth_service,
        mock_google_contacts_client,
    ):
        """Test sync handles authentication errors gracefully."""
        # Mock auth service to raise error
        mock_google_auth_service.get_access_token.side_effect = Exception("Auth failed")

        from worker import sync_google_contacts

        with (
            patch("worker.session_factory", mock_session_factory),
            patch("worker.GoogleAuthService", return_value=mock_google_auth_service),
            patch(
                "worker.GoogleContactsAPIClient",
                return_value=mock_google_contacts_client,
            ),
        ):
            result = await sync_google_contacts(
                ctx={"logger": MagicMock()},
                google_account_email="test@example.com",
                sync_type="full",
            )

            assert result["status"] == "error"
            assert "Auth failed" in result["error_message"]

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
            patch("worker.session_factory", mock_session_factory),
            patch("worker.GoogleAuthService", return_value=mock_google_auth_service),
            patch(
                "worker.GoogleContactsAPIClient",
                return_value=mock_google_contacts_client,
            ),
        ):
            result = await sync_google_contacts(
                ctx={"logger": MagicMock()},
                google_account_email="test@example.com",
                sync_type="full",
            )

            assert result["status"] == "error"
            assert "API error" in result["error_message"]


if __name__ == "__main__":
    pytest.main([__file__])
