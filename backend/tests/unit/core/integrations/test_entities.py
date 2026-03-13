"""
Unit tests for integration domain entities.

Tests the SyncMetadata entity for proper validation and business logic.

Note: ExternalReference tests have been removed as the production code now uses
the SQLAlchemy model from core_shared.models.external_reference directly.
"""

from datetime import datetime

from app.core.integrations.models.entities import SyncMetadata, SyncStatus


class TestSyncMetadata:
    """Test cases for SyncMetadata entity."""

    def test_create_sync_metadata_success(self) -> None:
        """Test creating a valid SyncMetadata entity."""
        now = datetime.now()
        sync_metadata = SyncMetadata(
            internal_id=123,
            integration_source="google",
            external_id="ext_123",
            last_synced_at=now,
            version_hash="abc123",
            sync_status=SyncStatus.SUCCESS,
        )

        assert sync_metadata.internal_id == 123
        assert sync_metadata.integration_source == "google"
        assert sync_metadata.external_id == "ext_123"
        assert sync_metadata.last_synced_at == now
        assert sync_metadata.version_hash == "abc123"
        assert sync_metadata.sync_status == SyncStatus.SUCCESS
        assert sync_metadata.id is None
        assert sync_metadata.error_message is None
        assert sync_metadata.retry_count == 0

    def test_sync_metadata_with_optional_fields(self) -> None:
        """Test creating SyncMetadata with optional fields."""
        now = datetime.now()
        sync_metadata = SyncMetadata(
            internal_id=123,
            integration_source="google",
            external_id="ext_123",
            last_synced_at=now,
            version_hash="abc123",
            sync_status=SyncStatus.FAILED,
            error_message="Test error",
            retry_count=2,
        )

        assert sync_metadata.error_message == "Test error"
        assert sync_metadata.retry_count == 2
        assert sync_metadata.sync_status == SyncStatus.FAILED


class TestSyncStatus:
    """Test cases for SyncStatus enum."""

    def test_sync_status_values(self) -> None:
        """Test that SyncStatus enum has expected values."""
        assert SyncStatus.SUCCESS.value == "success"
        assert SyncStatus.FAILED.value == "failed"
        assert SyncStatus.IN_PROGRESS.value == "in_progress"
        assert SyncStatus.PENDING.value == "pending"
