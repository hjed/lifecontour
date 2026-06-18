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
    SyncJob,
    SyncJobStatus,
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


class TestSyncJobStatus:
    """Test SyncJobStatus enum."""

    def test_existing_status_values_unchanged(self) -> None:
        """The pre-existing sync job statuses retain their values."""
        assert SyncJobStatus.QUEUED.value == "queued"
        assert SyncJobStatus.RUNNING.value == "running"
        assert SyncJobStatus.COMPLETED.value == "completed"
        assert SyncJobStatus.FAILED.value == "failed"
        assert SyncJobStatus.CANCELLED.value == "cancelled"

    def test_in_progress_status_added(self) -> None:
        """SyncJobStatus gains IN_PROGRESS for dispatched-but-awaiting parents."""
        assert SyncJobStatus.IN_PROGRESS.value == "in_progress"

    def test_status_value_set_is_complete(self) -> None:
        """IN_PROGRESS is additive: the full value set is as expected."""
        assert {s.value for s in SyncJobStatus} == {
            "queued",
            "running",
            "in_progress",
            "completed",
            "failed",
            "cancelled",
        }


class TestSyncJobHierarchyColumns:
    """Test the SyncJob fan-out hierarchy columns."""

    def test_sync_job_accepts_parent_and_counter_fields(self) -> None:
        """SyncJob can be instantiated with parent link and child counters."""
        now = datetime.now(UTC)
        job = SyncJob(
            job_id="child-1",
            user_id="user-1",
            integration_source="immich",
            sync_type="full",
            status=SyncJobStatus.QUEUED.value,
            parent_job_id="parent-1",
            expected_children=0,
            completed_children=0,
            failed_children=0,
            created_at=now,
            updated_at=now,
        )

        assert job.parent_job_id == "parent-1"
        assert job.expected_children == 0
        assert job.completed_children == 0
        assert job.failed_children == 0


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
            integration_source="google",
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
        assert sync_metadata.integration_source == "google"
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
            integration_source="google",
            external_id="person/abc123",
            last_synced_at=datetime.now(UTC),
            version_hash="hash123",
            sync_status=SyncStatus.SUCCESS.value,
        )

        repr_str = repr(sync_metadata)
        assert "SyncMetadata(id=1" in repr_str
        assert "integration_source='google'" in repr_str
        assert "external_id='person/abc123'" in repr_str
        assert "sync_status='success'" in repr_str

    def test_sync_metadata_table_name(self) -> None:
        """Test that SyncMetadata has correct table name."""
        assert SyncMetadata.__tablename__ == "sync_metadata"

    def test_sync_metadata_link_columns_round_trip(self) -> None:
        """Test the consolidated integration-link columns round-trip."""
        now = datetime.now(UTC)

        sync_metadata = SyncMetadata(
            internal_id=42,
            integration_source="immich_album",
            external_id="album/abc123",
            last_synced_at=now,
            version_hash="hash123",
            sync_status=SyncStatus.SUCCESS.value,
            reference_data='{"album_name": "Trip"}',
            internal_entity_type="journal",
            external_entity_type="album",
        )

        assert sync_metadata.reference_data == '{"album_name": "Trip"}'
        assert sync_metadata.internal_entity_type == "journal"
        assert sync_metadata.external_entity_type == "album"

    def test_sync_metadata_link_columns_are_mapped(self) -> None:
        """The link fields are mapped table columns, not plain attributes."""
        columns = SyncMetadata.__table__.columns

        assert "reference_data" in columns
        assert "internal_entity_type" in columns
        assert "external_entity_type" in columns

        # Nullable so existing rows and old writers stay valid.
        assert columns["reference_data"].nullable is True
        assert columns["internal_entity_type"].nullable is True
        assert columns["external_entity_type"].nullable is True

        # Entity-type columns are bounded to VARCHAR(50) per the migration.
        assert str(columns["internal_entity_type"].type) == "VARCHAR(50)"
        assert str(columns["external_entity_type"].type) == "VARCHAR(50)"

    def test_sync_metadata_link_columns_default_to_none(self) -> None:
        """Link columns are optional and default to None when omitted."""
        sync_metadata = SyncMetadata(
            internal_id=1,
            integration_source="google",
            external_id="people/c1",
            last_synced_at=datetime.now(UTC),
            version_hash="hash",
            sync_status=SyncStatus.SUCCESS.value,
        )

        assert sync_metadata.reference_data is None
        assert sync_metadata.internal_entity_type is None
        assert sync_metadata.external_entity_type is None


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
