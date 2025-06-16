"""
Unit tests for integration domain entities.

Tests the SyncMetadata and ExternalReference entities for proper validation
and business logic.
"""

from datetime import datetime

import pytest

from app.core.integrations.models.entities import (
    ExternalReference,
    SyncMetadata,
    SyncStatus,
)


class TestSyncMetadata:
    """Test cases for SyncMetadata entity."""

    def test_create_sync_metadata_success(self) -> None:
        """Test creating a valid SyncMetadata entity."""
        now = datetime.now()
        sync_metadata = SyncMetadata(
            internal_id=123,
            integration_source="google_contacts",
            external_id="ext_123",
            last_synced_at=now,
            version_hash="abc123",
            sync_status=SyncStatus.SUCCESS,
        )

        assert sync_metadata.internal_id == 123
        assert sync_metadata.integration_source == "google_contacts"
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
            integration_source="google_contacts",
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


class TestExternalReference:
    """Test cases for ExternalReference entity."""

    def test_create_external_reference_success(self) -> None:
        """Test creating a valid ExternalReference entity."""
        external_ref = ExternalReference(
            entity_id=456,
            entity_type="contact",
            integration_source="google_contacts",
            external_id="ext_456",
            external_url="https://example.com/contact/456",
            metadata={"name": "John Doe"},
        )

        assert external_ref.entity_id == 456
        assert external_ref.entity_type == "contact"
        assert external_ref.integration_source == "google_contacts"
        assert external_ref.external_id == "ext_456"
        assert external_ref.external_url == "https://example.com/contact/456"
        assert external_ref.metadata == {"name": "John Doe"}
        assert external_ref.id is None

    def test_external_reference_validation_empty_entity_type(self) -> None:
        """Test that empty entity type raises ValueError."""
        with pytest.raises(ValueError, match="Entity type cannot be empty"):
            ExternalReference(
                entity_id=456,
                entity_type="",
                integration_source="google_contacts",
                external_id="ext_456",
            )

    def test_external_reference_validation_empty_integration_source(self) -> None:
        """Test that empty integration source raises ValueError."""
        with pytest.raises(ValueError, match="Integration source cannot be empty"):
            ExternalReference(
                entity_id=456,
                entity_type="contact",
                integration_source="",
                external_id="ext_456",
            )

    def test_external_reference_validation_empty_external_id(self) -> None:
        """Test that empty external ID raises ValueError."""
        with pytest.raises(ValueError, match="External ID cannot be empty"):
            ExternalReference(
                entity_id=456,
                entity_type="contact",
                integration_source="google_contacts",
                external_id="",
            )

    def test_external_reference_validation_invalid_entity_type(self) -> None:
        """Test that invalid entity type raises ValueError."""
        with pytest.raises(ValueError, match="Entity type must be one of:"):
            ExternalReference(
                entity_id=456,
                entity_type="invalid_type",
                integration_source="google_contacts",
                external_id="ext_456",
            )

    def test_external_reference_metadata_initialization(self) -> None:
        """Test that metadata is initialized as empty dict when None."""
        external_ref = ExternalReference(
            entity_id=456,
            entity_type="contact",
            integration_source="google_contacts",
            external_id="ext_456",
            metadata=None,
        )

        assert external_ref.metadata == {}


class TestSyncStatus:
    """Test cases for SyncStatus enum."""

    def test_sync_status_values(self) -> None:
        """Test that SyncStatus enum has expected values."""
        assert SyncStatus.SUCCESS.value == "success"
        assert SyncStatus.FAILED.value == "failed"
        assert SyncStatus.IN_PROGRESS.value == "in_progress"
        assert SyncStatus.PENDING.value == "pending"
