"""
Base integration service interface and patterns.

Provides common patterns and interfaces for all integration services
to ensure consistency across different external system integrations.
"""

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Generic, TypeVar

from core_shared.models.sync_metadata import SyncMetadata


class SyncResult(Enum):
    """Result of a synchronization operation."""

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    PARTIAL = "partial"


class SyncDirection(Enum):
    """Direction of synchronization."""

    INBOUND = "inbound"  # External -> Internal
    OUTBOUND = "outbound"  # Internal -> External
    BIDIRECTIONAL = "bidirectional"  # Both directions


# Type variables for generic integration service
TExternalEntity = TypeVar("TExternalEntity")
TInternalEntity = TypeVar("TInternalEntity")


class BaseIntegrationService(ABC, Generic[TExternalEntity, TInternalEntity]):
    """
    Base class for all integration services.

    Provides common patterns for synchronization, error handling,
    and state management across different external systems.
    """

    def __init__(self, integration_source: str) -> None:
        """
        Initialize the integration service.

        Args:
            integration_source: Name of the integration source (e.g., 'google')
        """
        self.integration_source = integration_source

    @abstractmethod
    async def sync_entity(
        self,
        external_id: str,
        direction: SyncDirection = SyncDirection.INBOUND,
        force_update: bool = False,
    ) -> SyncResult:
        """
        Synchronize a single entity between external and internal systems.

        Args:
            external_id: External system's ID for the entity
            direction: Direction of synchronization
            force_update: Whether to force update even if no changes detected

        Returns:
            SyncResult: Result of the synchronization operation
        """
        pass

    @abstractmethod
    async def fetch_external_entity(self, external_id: str) -> TExternalEntity | None:
        """
        Fetch an entity from the external system.

        Args:
            external_id: External system's ID for the entity

        Returns:
            External entity data or None if not found
        """
        pass

    @abstractmethod
    async def transform_to_internal(
        self, external_entity: TExternalEntity
    ) -> TInternalEntity:
        """
        Transform external entity data to internal entity format.

        Args:
            external_entity: External entity data

        Returns:
            Internal entity data
        """
        pass

    @abstractmethod
    async def transform_to_external(
        self, internal_entity: TInternalEntity
    ) -> TExternalEntity:
        """
        Transform internal entity data to external entity format.

        Args:
            internal_entity: Internal entity data

        Returns:
            External entity data
        """
        pass

    @abstractmethod
    async def save_internal_entity(
        self, internal_entity: TInternalEntity
    ) -> TInternalEntity:
        """
        Save internal entity to the database.

        Args:
            internal_entity: Internal entity to save

        Returns:
            Saved internal entity with updated ID/timestamps
        """
        pass

    @abstractmethod
    async def get_sync_metadata(self, external_id: str) -> SyncMetadata | None:
        """
        Get synchronization metadata for an entity.

        Args:
            external_id: External system's ID for the entity

        Returns:
            Sync metadata or None if not found
        """
        pass

    @abstractmethod
    async def save_sync_metadata(self, sync_metadata: SyncMetadata) -> SyncMetadata:
        """
        Save synchronization metadata.

        Args:
            sync_metadata: Sync metadata to save

        Returns:
            Saved sync metadata
        """
        pass

    def calculate_version_hash(self, entity_data: dict[str, Any]) -> str:
        """
        Calculate a version hash for change detection.

        Args:
            entity_data: Entity data to hash

        Returns:
            SHA-256 hash of the entity data
        """
        import hashlib
        import json

        # Sort keys for consistent hashing
        normalized_data = json.dumps(entity_data, sort_keys=True, default=str)
        return hashlib.sha256(normalized_data.encode()).hexdigest()

    async def should_sync_entity(
        self,
        external_entity: TExternalEntity,
        sync_metadata: SyncMetadata | None,
        force_update: bool = False,
    ) -> bool:
        """
        Determine if an entity should be synchronized.

        Args:
            external_entity: External entity data
            sync_metadata: Existing sync metadata
            force_update: Whether to force update

        Returns:
            True if entity should be synchronized
        """
        if force_update:
            return True

        if sync_metadata is None:
            return True

        # Calculate current hash and compare with stored hash
        current_hash = self.calculate_version_hash(
            await self._entity_to_dict(external_entity)
        )
        return current_hash != sync_metadata.version_hash

    @abstractmethod
    async def _entity_to_dict(self, entity: TExternalEntity) -> dict[str, Any]:
        """
        Convert entity to dictionary for hashing.

        Args:
            entity: Entity to convert

        Returns:
            Dictionary representation of entity
        """
        pass

    def create_external_reference_data(
        self,
        internal_entity_id: int,
        internal_entity_type: str,
        external_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Create external reference data for linking internal and external entities.

        Args:
            internal_entity_id: ID of internal entity
            internal_entity_type: Type of internal entity
            external_id: External system's ID
            metadata: Additional metadata

        Returns:
            Dictionary with external reference data
        """
        return {
            "entity_id": internal_entity_id,
            "entity_type": internal_entity_type,
            "integration_source": self.integration_source,
            "external_id": external_id,
            "metadata": metadata or {},
            "created_at": datetime.now(tz=UTC),
            "updated_at": datetime.now(tz=UTC),
        }


class IntegrationError(Exception):
    """Base exception for integration errors."""

    def __init__(
        self, message: str, integration_source: str, external_id: str | None = None
    ) -> None:
        super().__init__(message)
        self.integration_source = integration_source
        self.external_id = external_id


class SyncError(IntegrationError):
    """Exception raised during synchronization operations."""

    def __init__(
        self,
        message: str,
        integration_source: str,
        external_id: str | None = None,
        sync_direction: SyncDirection | None = None,
    ) -> None:
        super().__init__(message, integration_source, external_id)
        self.sync_direction = sync_direction


class TransformationError(IntegrationError):
    """Exception raised during data transformation."""

    def __init__(
        self,
        message: str,
        integration_source: str,
        external_id: str | None = None,
        field_name: str | None = None,
    ) -> None:
        super().__init__(message, integration_source, external_id)
        self.field_name = field_name
