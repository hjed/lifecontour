"""
Unit tests for SyncMetadataRepository.

Tests verify SELECT FOR UPDATE locking, version hash checking,
and idempotency patterns.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.models.sync_metadata import SyncMetadata, SyncStatus

from app.core.integrations.adapters.sql.sync_metadata_repository import (
    SyncMetadataRepository,
)


class TestSyncMetadataRepository:
    """Test cases for SyncMetadataRepository."""

    @pytest.fixture
    def mock_connection(self) -> AsyncMock:
        """Create a mock database connection."""
        return AsyncMock()

    @pytest.fixture
    def repository(self, mock_connection: AsyncMock) -> SyncMetadataRepository:
        """Create a SyncMetadataRepository instance."""
        return SyncMetadataRepository(mock_connection)

    @pytest.mark.asyncio
    async def test_find_and_lock_found(
        self, repository: SyncMetadataRepository, mock_connection: AsyncMock
    ) -> None:
        """Test find_and_lock when record exists."""
        # Setup mock result
        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.internal_id = 123
        mock_row.integration_source = "google_contacts"
        mock_row.external_id = "people/c123"
        mock_row.last_synced_at = datetime.now(UTC)
        mock_row.version_hash = "abc123"
        mock_row.sync_status = "success"
        mock_row.error_message = None
        mock_row.retry_count = 0
        mock_row.created_at = datetime.now(UTC)
        mock_row.updated_at = datetime.now(UTC)

        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        mock_connection.execute = AsyncMock(return_value=mock_result)

        # Execute
        result = await repository.find_and_lock("google_contacts", "people/c123")

        # Verify
        assert result is not None
        assert result.id == 1
        assert result.internal_id == 123
        assert result.integration_source == "google_contacts"
        assert result.external_id == "people/c123"
        assert result.version_hash == "abc123"

        # Verify SELECT FOR UPDATE was used
        call_args = mock_connection.execute.call_args
        query_text = str(call_args[0][0])
        assert "FOR UPDATE" in query_text

    @pytest.mark.asyncio
    async def test_find_and_lock_not_found(
        self, repository: SyncMetadataRepository, mock_connection: AsyncMock
    ) -> None:
        """Test find_and_lock when record doesn't exist."""
        # Setup mock result
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_connection.execute = AsyncMock(return_value=mock_result)

        # Execute
        result = await repository.find_and_lock("google_contacts", "people/c123")

        # Verify
        assert result is None

    @pytest.mark.asyncio
    async def test_find_by_external_id_found(
        self, repository: SyncMetadataRepository, mock_connection: AsyncMock
    ) -> None:
        """Test find_by_external_id when record exists."""
        # Setup mock result
        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.internal_id = 123
        mock_row.integration_source = "google_contacts"
        mock_row.external_id = "people/c123"
        mock_row.last_synced_at = datetime.now(UTC)
        mock_row.version_hash = "abc123"
        mock_row.sync_status = "success"
        mock_row.error_message = None
        mock_row.retry_count = 0
        mock_row.created_at = datetime.now(UTC)
        mock_row.updated_at = datetime.now(UTC)

        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        mock_connection.execute = AsyncMock(return_value=mock_result)

        # Execute
        result = await repository.find_by_external_id("google_contacts", "people/c123")

        # Verify
        assert result is not None
        assert result.id == 1
        assert result.version_hash == "abc123"

        # Verify FOR UPDATE was NOT used
        call_args = mock_connection.execute.call_args
        query_text = str(call_args[0][0])
        assert "FOR UPDATE" not in query_text

    @pytest.mark.asyncio
    async def test_upsert_insert(
        self, repository: SyncMetadataRepository, mock_connection: AsyncMock
    ) -> None:
        """Test upsert when inserting a new record."""
        # Setup mock result
        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.internal_id = 123
        mock_row.integration_source = "google_contacts"
        mock_row.external_id = "people/c123"
        mock_row.last_synced_at = datetime.now(UTC)
        mock_row.version_hash = "new_hash"
        mock_row.sync_status = "success"
        mock_row.error_message = None
        mock_row.retry_count = 0
        mock_row.created_at = datetime.now(UTC)
        mock_row.updated_at = datetime.now(UTC)

        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        mock_connection.execute = AsyncMock(return_value=mock_result)

        # Execute
        result = await repository.upsert(
            internal_id=123,
            integration_source="google_contacts",
            external_id="people/c123",
            version_hash="new_hash",
        )

        # Verify
        assert result is not None
        assert result.id == 1
        assert result.version_hash == "new_hash"

    def test_should_sync_no_existing_metadata(
        self, repository: SyncMetadataRepository
    ) -> None:
        """Test should_sync when no existing metadata (new entity)."""
        result = repository.should_sync(None, "new_hash")
        assert result is True

    def test_should_sync_version_hash_matches(
        self, repository: SyncMetadataRepository
    ) -> None:
        """Test should_sync when version hash matches (idempotent)."""
        existing = SyncMetadata(
            id=1,
            internal_id=123,
            integration_source="google_contacts",
            external_id="people/c123",
            last_synced_at=datetime.now(UTC),
            version_hash="same_hash",
            sync_status="success",
        )

        result = repository.should_sync(existing, "same_hash")
        assert result is False  # Skip sync - data unchanged

    def test_should_sync_version_hash_differs(
        self, repository: SyncMetadataRepository
    ) -> None:
        """Test should_sync when version hash differs (data changed)."""
        existing = SyncMetadata(
            id=1,
            internal_id=123,
            integration_source="google_contacts",
            external_id="people/c123",
            last_synced_at=datetime.now(UTC),
            version_hash="old_hash",
            sync_status="success",
        )

        result = repository.should_sync(existing, "new_hash")
        assert result is True  # Proceed with sync - data changed

    @pytest.mark.asyncio
    async def test_upsert_with_error(
        self, repository: SyncMetadataRepository, mock_connection: AsyncMock
    ) -> None:
        """Test upsert with error status."""
        # Setup mock result
        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.internal_id = 123
        mock_row.integration_source = "google_contacts"
        mock_row.external_id = "people/c123"
        mock_row.last_synced_at = datetime.now(UTC)
        mock_row.version_hash = "hash"
        mock_row.sync_status = "failed"
        mock_row.error_message = "API error"
        mock_row.retry_count = 1
        mock_row.created_at = datetime.now(UTC)
        mock_row.updated_at = datetime.now(UTC)

        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        mock_connection.execute = AsyncMock(return_value=mock_result)

        # Execute
        result = await repository.upsert(
            internal_id=123,
            integration_source="google_contacts",
            external_id="people/c123",
            version_hash="hash",
            sync_status=SyncStatus.FAILED,
            error_message="API error",
        )

        # Verify
        assert result is not None
        assert result.sync_status == "failed"
        assert result.error_message == "API error"
