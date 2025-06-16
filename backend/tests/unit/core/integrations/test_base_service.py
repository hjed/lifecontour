"""
Unit tests for base integration service.

Tests the base integration service interface and common patterns
used across all integration services.
"""

from datetime import datetime
from typing import Any

from core_shared import (
    BaseIntegrationService,
    IntegrationError,
    SyncDirection,
    SyncError,
    SyncMetadata,
    SyncResult,
    SyncStatus,
    TransformationError,
)


class MockExternalEntity:
    """Mock external entity for testing."""

    def __init__(self, id: str, name: str, email: str) -> None:
        self.id = id
        self.name = name
        self.email = email


class MockInternalEntity:
    """Mock internal entity for testing."""

    def __init__(self, id: int, name: str, email: str) -> None:
        self.id = id
        self.name = name
        self.email = email


class MockIntegrationService(
    BaseIntegrationService[MockExternalEntity, MockInternalEntity]
):
    """Mock integration service for testing."""

    def __init__(self) -> None:
        super().__init__("test_integration")
        self._external_entities: dict[str, MockExternalEntity] = {}
        self._internal_entities: dict[int, MockInternalEntity] = {}
        self._sync_metadata: dict[str, SyncMetadata] = {}

    async def sync_entity(
        self,
        external_id: str,
        _direction: SyncDirection = SyncDirection.INBOUND,
        _force_update: bool = False,
    ) -> SyncResult:
        """Mock sync entity implementation."""
        external_entity = await self.fetch_external_entity(external_id)
        if external_entity is None:
            return SyncResult.FAILED

        internal_entity = await self.transform_to_internal(external_entity)
        await self.save_internal_entity(internal_entity)
        return SyncResult.SUCCESS

    async def fetch_external_entity(
        self, external_id: str
    ) -> MockExternalEntity | None:
        """Mock fetch external entity."""
        return self._external_entities.get(external_id)

    async def transform_to_internal(
        self, external_entity: MockExternalEntity
    ) -> MockInternalEntity:
        """Mock transform to internal."""
        return MockInternalEntity(
            id=hash(external_entity.id) % 1000,
            name=external_entity.name,
            email=external_entity.email,
        )

    async def transform_to_external(
        self, internal_entity: MockInternalEntity
    ) -> MockExternalEntity:
        """Mock transform to external."""
        return MockExternalEntity(
            id=str(internal_entity.id),
            name=internal_entity.name,
            email=internal_entity.email,
        )

    async def save_internal_entity(
        self, internal_entity: MockInternalEntity
    ) -> MockInternalEntity:
        """Mock save internal entity."""
        self._internal_entities[internal_entity.id] = internal_entity
        return internal_entity

    async def get_sync_metadata(self, external_id: str) -> SyncMetadata | None:
        """Mock get sync metadata."""
        return self._sync_metadata.get(external_id)

    async def save_sync_metadata(self, sync_metadata: SyncMetadata) -> SyncMetadata:
        """Mock save sync metadata."""
        self._sync_metadata[sync_metadata.external_id] = sync_metadata
        return sync_metadata

    async def _entity_to_dict(self, entity: MockExternalEntity) -> dict[str, Any]:
        """Convert entity to dict for hashing."""
        return {
            "id": entity.id,
            "name": entity.name,
            "email": entity.email,
        }

    # Helper methods for testing
    def add_external_entity(self, entity: MockExternalEntity) -> None:
        """Add external entity for testing."""
        self._external_entities[entity.id] = entity


class TestBaseIntegrationService:
    """Test cases for BaseIntegrationService."""

    def test_initialization(self) -> None:
        """Test service initialization."""
        service = MockIntegrationService()
        assert service.integration_source == "test_integration"

    def test_calculate_version_hash(self) -> None:
        """Test version hash calculation."""
        service = MockIntegrationService()

        data1 = {"name": "John", "email": "john@example.com"}
        data2 = {"email": "john@example.com", "name": "John"}  # Different order
        data3 = {"name": "Jane", "email": "jane@example.com"}

        hash1 = service.calculate_version_hash(data1)
        hash2 = service.calculate_version_hash(data2)
        hash3 = service.calculate_version_hash(data3)

        # Same data should produce same hash regardless of order
        assert hash1 == hash2
        # Different data should produce different hash
        assert hash1 != hash3
        # Hash should be 64 characters (SHA-256)
        assert len(hash1) == 64

    async def test_should_sync_entity_force_update(self) -> None:
        """Test should_sync_entity with force_update=True."""
        service = MockIntegrationService()
        external_entity = MockExternalEntity("ext_1", "John", "john@example.com")

        # Should sync when force_update=True regardless of metadata
        result = await service.should_sync_entity(
            external_entity, None, force_update=True
        )
        assert result is True

    async def test_should_sync_entity_no_metadata(self) -> None:
        """Test should_sync_entity with no existing metadata."""
        service = MockIntegrationService()
        external_entity = MockExternalEntity("ext_1", "John", "john@example.com")

        # Should sync when no metadata exists
        result = await service.should_sync_entity(
            external_entity, None, force_update=False
        )
        assert result is True

    async def test_should_sync_entity_hash_changed(self) -> None:
        """Test should_sync_entity when hash has changed."""
        service = MockIntegrationService()
        external_entity = MockExternalEntity("ext_1", "John", "john@example.com")

        # Create metadata with different hash
        sync_metadata = SyncMetadata(
            internal_id=123,
            integration_source="test_integration",
            external_id="ext_1",
            last_synced_at=datetime.now(),
            version_hash="old_hash",
            sync_status=SyncStatus.SUCCESS,
        )

        # Should sync when hash is different
        result = await service.should_sync_entity(
            external_entity, sync_metadata, force_update=False
        )
        assert result is True

    async def test_should_sync_entity_hash_unchanged(self) -> None:
        """Test should_sync_entity when hash is unchanged."""
        service = MockIntegrationService()
        external_entity = MockExternalEntity("ext_1", "John", "john@example.com")

        # Calculate current hash
        current_hash = service.calculate_version_hash(
            await service._entity_to_dict(external_entity)
        )

        # Create metadata with same hash
        sync_metadata = SyncMetadata(
            internal_id=123,
            integration_source="test_integration",
            external_id="ext_1",
            last_synced_at=datetime.now(),
            version_hash=current_hash,
            sync_status=SyncStatus.SUCCESS,
        )

        # Should not sync when hash is same
        result = await service.should_sync_entity(
            external_entity, sync_metadata, force_update=False
        )
        assert result is False

    def test_create_external_reference_data(self) -> None:
        """Test creating external reference data."""
        service = MockIntegrationService()

        external_ref_data = service.create_external_reference_data(
            internal_entity_id=123,
            internal_entity_type="contact",
            external_id="ext_456",
            metadata={"source": "test"},
        )

        assert external_ref_data["entity_id"] == 123
        assert external_ref_data["entity_type"] == "contact"
        assert external_ref_data["integration_source"] == "test_integration"
        assert external_ref_data["external_id"] == "ext_456"
        assert external_ref_data["metadata"] == {"source": "test"}
        assert external_ref_data["created_at"] is not None
        assert external_ref_data["updated_at"] is not None


class TestIntegrationExceptions:
    """Test cases for integration exceptions."""

    def test_integration_error(self) -> None:
        """Test IntegrationError exception."""
        error = IntegrationError("Test error", "test_integration", "ext_123")

        assert str(error) == "Test error"
        assert error.integration_source == "test_integration"
        assert error.external_id == "ext_123"

    def test_sync_error(self) -> None:
        """Test SyncError exception."""
        error = SyncError(
            "Sync failed",
            "test_integration",
            "ext_123",
            SyncDirection.INBOUND,
        )

        assert str(error) == "Sync failed"
        assert error.integration_source == "test_integration"
        assert error.external_id == "ext_123"
        assert error.sync_direction == SyncDirection.INBOUND

    def test_transformation_error(self) -> None:
        """Test TransformationError exception."""
        error = TransformationError(
            "Transform failed",
            "test_integration",
            "ext_123",
            "email",
        )

        assert str(error) == "Transform failed"
        assert error.integration_source == "test_integration"
        assert error.external_id == "ext_123"
        assert error.field_name == "email"


class TestSyncEnums:
    """Test cases for sync enums."""

    def test_sync_result_values(self) -> None:
        """Test SyncResult enum values."""
        assert SyncResult.SUCCESS.value == "success"
        assert SyncResult.FAILED.value == "failed"
        assert SyncResult.SKIPPED.value == "skipped"
        assert SyncResult.PARTIAL.value == "partial"

    def test_sync_direction_values(self) -> None:
        """Test SyncDirection enum values."""
        assert SyncDirection.INBOUND.value == "inbound"
        assert SyncDirection.OUTBOUND.value == "outbound"
        assert SyncDirection.BIDIRECTIONAL.value == "bidirectional"
