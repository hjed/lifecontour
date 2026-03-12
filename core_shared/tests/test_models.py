"""
Tests for shared SQLAlchemy models.

Tests model creation, validation, and basic functionality without requiring
a database connection.
"""

from datetime import UTC, datetime
from uuid import UUID

from core_shared.models import (
    ExternalEventLinkSyncCapability,
    ExternalEventLinkSyncStatus,
    ExternalReference,
    JournalExternalEventLink,
    SyncMetadata,
    SyncStatus,
)


class TestSyncStatus:
    """Test SyncStatus enum."""

    def test_sync_status_values(self) -> None:
        """Test that SyncStatus has expected values."""
        assert SyncStatus.SUCCESS.value == "success"
        assert SyncStatus.FAILED.value == "failed"
        assert SyncStatus.IN_PROGRESS.value == "in_progress"
        assert SyncStatus.PENDING.value == "pending"


class TestExternalEventLinkEnums:
    """Test external event link enums."""

    def test_sync_capability_values(self) -> None:
        """Test that event link sync capability has expected values."""
        assert ExternalEventLinkSyncCapability.OUTBOUND.value == "outbound"
        assert ExternalEventLinkSyncCapability.BIDIRECTIONAL.value == "bidirectional"

    def test_sync_status_values(self) -> None:
        """Test that event link sync status has expected values."""
        assert ExternalEventLinkSyncStatus.PENDING.value == "pending"
        assert ExternalEventLinkSyncStatus.SYNCED.value == "synced"
        assert ExternalEventLinkSyncStatus.CONFLICTED.value == "conflicted"
        assert ExternalEventLinkSyncStatus.CANCELLED.value == "cancelled"
        assert ExternalEventLinkSyncStatus.ERRORED.value == "errored"


class TestSyncMetadata:
    """Test SyncMetadata model."""

    def test_sync_metadata_creation(self) -> None:
        """Test creating SyncMetadata instance."""
        now = datetime.now(UTC)

        sync_metadata = SyncMetadata(
            internal_id=123,
            integration_source="google_contacts",
            external_id="person/abc123",
            last_synced_at=now,
            version_hash="sha256_hash_of_data",
            sync_status=SyncStatus.SUCCESS.value,
            error_message=None,
            retry_count=0,
            created_at=now,
            updated_at=now,
        )

        assert sync_metadata.internal_id == 123
        assert sync_metadata.integration_source == "google_contacts"
        assert sync_metadata.external_id == "person/abc123"
        assert sync_metadata.last_synced_at == now
        assert sync_metadata.version_hash == "sha256_hash_of_data"
        assert sync_metadata.sync_status == SyncStatus.SUCCESS.value
        assert sync_metadata.error_message is None
        assert sync_metadata.retry_count == 0

    def test_sync_metadata_repr(self) -> None:
        """Test SyncMetadata string representation."""
        sync_metadata = SyncMetadata(
            id=1,
            internal_id=123,
            integration_source="google_contacts",
            external_id="person/abc123",
            last_synced_at=datetime.now(UTC),
            version_hash="hash123",
            sync_status=SyncStatus.SUCCESS.value,
        )

        repr_str = repr(sync_metadata)
        assert "SyncMetadata(id=1" in repr_str
        assert "integration_source='google_contacts'" in repr_str
        assert "external_id='person/abc123'" in repr_str
        assert "sync_status='success'" in repr_str

    def test_sync_metadata_table_name(self) -> None:
        """Test that SyncMetadata has correct table name."""
        assert SyncMetadata.__tablename__ == "sync_metadata"


class TestExternalReference:
    """Test ExternalReference model."""

    def test_external_reference_creation(self) -> None:
        """Test creating ExternalReference instance."""
        now = datetime.now(UTC)

        reference = ExternalReference(
            internal_entity_type="contact",
            internal_entity_id=123,
            external_system="immich",
            external_entity_type="person",
            external_entity_id="person_uuid_456",
            reference_data='{"url": "https://example.com/person/456"}',
            created_at=now,
            updated_at=now,
        )

        assert reference.internal_entity_type == "contact"
        assert reference.internal_entity_id == 123
        assert reference.external_system == "immich"
        assert reference.external_entity_type == "person"
        assert reference.external_entity_id == "person_uuid_456"
        assert reference.reference_data == '{"url": "https://example.com/person/456"}'

    def test_external_reference_repr(self) -> None:
        """Test ExternalReference string representation."""
        reference = ExternalReference(
            id=1,
            internal_entity_type="contact",
            internal_entity_id=123,
            external_system="immich",
            external_entity_type="person",
            external_entity_id="person_uuid_456",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        repr_str = repr(reference)
        assert "ExternalReference(id=1" in repr_str
        assert "internal=contact:123" in repr_str
        assert "external=immich:person_uuid_456" in repr_str

    def test_external_reference_table_name(self) -> None:
        """Test that ExternalReference has correct table name."""
        assert ExternalReference.__tablename__ == "external_references"


class TestJournalExternalEventLink:
    """Test JournalExternalEventLink model."""

    def test_journal_external_event_link_creation(self) -> None:
        """Test creating JournalExternalEventLink instance."""
        now = datetime.now(UTC)

        cal_id = UUID("00000000-0000-0000-0000-000000000123")
        link = JournalExternalEventLink(
            journal_id=123,
            calendar_id=cal_id,
            external_event_id="google-event-123",
            external_version="etag-abc",
            sync_capability=ExternalEventLinkSyncCapability.BIDIRECTIONAL.value,
            sync_status=ExternalEventLinkSyncStatus.SYNCED.value,
            created_at=now,
            updated_at=now,
        )

        assert link.journal_id == 123
        assert link.calendar_id == cal_id
        assert link.external_event_id == "google-event-123"
        assert link.external_version == "etag-abc"
        assert (
            link.sync_capability == ExternalEventLinkSyncCapability.BIDIRECTIONAL.value
        )
        assert link.sync_status == ExternalEventLinkSyncStatus.SYNCED.value

    def test_journal_external_event_link_repr(self) -> None:
        """Test JournalExternalEventLink string representation."""
        cal_id = UUID("00000000-0000-0000-0000-000000000123")
        link = JournalExternalEventLink(
            journal_id=123,
            calendar_id=cal_id,
            external_event_id="google-event-123",
            sync_capability=ExternalEventLinkSyncCapability.OUTBOUND.value,
            sync_status=ExternalEventLinkSyncStatus.PENDING.value,
        )

        repr_str = repr(link)
        assert "JournalExternalEventLink(journal_id=123" in repr_str
        assert "calendar_id=UUID('00000000-0000-0000-0000-000000000123')" in repr_str
        assert "sync_capability='outbound'" in repr_str
        assert "sync_status='pending'" in repr_str

    def test_journal_external_event_link_table_name(self) -> None:
        """Test that JournalExternalEventLink has correct table name."""
        assert JournalExternalEventLink.__tablename__ == "journal_external_event_links"


class TestModelImports:
    """Test that models can be imported from package."""

    def test_import_from_core_shared(self) -> None:
        """Test importing models from main package."""
        from core_shared import (
            Base,
            ExternalEventLinkSyncCapability,
            ExternalEventLinkSyncStatus,
            ExternalReference,
            JournalExternalEventLink,
            SyncMetadata,
            SyncStatus,
        )

        # Test that classes are available
        assert SyncMetadata is not None
        assert SyncStatus is not None
        assert ExternalReference is not None
        assert JournalExternalEventLink is not None
        assert ExternalEventLinkSyncCapability is not None
        assert ExternalEventLinkSyncStatus is not None
        assert Base is not None

        # Test that they are the correct types
        assert issubclass(SyncMetadata, Base)
        assert issubclass(ExternalReference, Base)
        assert issubclass(JournalExternalEventLink, Base)

    def test_import_from_models_package(self) -> None:
        """Test importing models from models subpackage."""
        from core_shared.models import (
            Base,
            ExternalEventLinkSyncCapability,
            ExternalEventLinkSyncStatus,
            ExternalReference,
            JournalExternalEventLink,
            SyncMetadata,
            SyncStatus,
        )

        # Test that classes are available
        assert SyncMetadata is not None
        assert SyncStatus is not None
        assert ExternalReference is not None
        assert JournalExternalEventLink is not None
        assert ExternalEventLinkSyncCapability is not None
        assert ExternalEventLinkSyncStatus is not None
        assert Base is not None
