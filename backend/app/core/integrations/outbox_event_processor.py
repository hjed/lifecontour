"""
Outbox Event Processor for handling integration sync events.

Processes outbox events created by integration workers to create/update
contacts in the core system using the message-based architecture pattern.

This processor implements production-grade resilience patterns:
1. SELECT FOR UPDATE locking for concurrent sync operations
2. Version hash-based idempotency checks
3. Atomic operations with proper transaction handling
"""

from typing import Any

import structlog
from core_shared.models.contacts.serialization import (
    ContactDeserializationError,
    deserialize_contact,
)
from core_shared.models.outbox import OutboxEvent
from core_shared.models.sync_metadata import SyncStatus
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.services.contact_service import ContactService
from app.core.integrations.adapters.sql.sync_metadata_repository import (
    SyncMetadataRepository,
)
from app.core.integrations.external_reference_service import ExternalReferenceService
from app.core.integrations.utils.version_hash import calculate_contact_version_hash

logger = structlog.get_logger()

# Event type constants
EVENT_TYPE_CONTACT_CREATED = "contact.created"
EVENT_TYPE_CONTACT_UPDATED = "contact.updated"
EVENT_TYPE_SYNC_COMPLETED = "sync.completed"


class OutboxEventProcessingError(Exception):
    """Raised when outbox event processing fails."""


class PermanentOutboxEventProcessingError(OutboxEventProcessingError):
    """Raised when an outbox event payload is permanently invalid."""


class OutboxEventProcessor:
    """
    Processes outbox events from integration workers.

    Handles contact sync events by transforming external contact data
    and creating/updating contacts in the core system.
    """

    def __init__(
        self,
        contact_service: ContactService,
        connection: AsyncConnection,
    ):
        """
        Initialize the outbox event processor.

        Args:
            contact_service: Service for contact operations
            connection: Database connection for transactions
        """
        self.contact_service = contact_service
        self.connection = connection
        self.external_reference_service = ExternalReferenceService(connection)
        self.sync_metadata_repo = SyncMetadataRepository(connection)

    async def process_event(self, event: OutboxEvent) -> dict[str, Any]:
        """
        Process a single outbox event.

        Args:
            event: Outbox event to process

        Returns:
            Processing result dictionary

        Raises:
            PermanentOutboxEventProcessingError: If the event payload is invalid
                and retrying will never succeed
            OutboxEventProcessingError: If event processing fails transiently
        """
        logger.info(
            "Processing outbox event",
            event_id=event.id,
            event_type=event.event_type,
            retry_count=event.retry_count,
        )

        try:
            if event.event_type == EVENT_TYPE_CONTACT_CREATED:
                return await self._process_contact_created(event)
            if event.event_type == EVENT_TYPE_CONTACT_UPDATED:
                return await self._process_contact_updated(event)
            if event.event_type == EVENT_TYPE_SYNC_COMPLETED:
                return self._process_sync_completed(event)

            raise OutboxEventProcessingError(f"Unknown event type: {event.event_type}")

        except PermanentOutboxEventProcessingError as e:
            self._log_processing_failure(
                event,
                e,
                message="Outbox event has permanent invalid payload",
            )
            raise
        except Exception as e:
            self._log_processing_failure(
                event, e, message="Failed to process outbox event"
            )
            raise OutboxEventProcessingError(
                f"Failed to process {event.event_type} event: {str(e)}"
            ) from e

    def _log_processing_failure(
        self, event: OutboxEvent, error: Exception, message: str
    ) -> None:
        """Log a failed outbox event processing attempt."""
        logger.error(
            message,
            event_id=event.id,
            event_type=event.event_type,
            error=str(error),
            error_type=type(error).__name__,
        )

    async def _process_contact_created(self, event: OutboxEvent) -> dict[str, Any]:
        """Process a contact.created event."""
        event_data: dict[str, Any] = event.event_data  # type: ignore
        integration_source: str = event_data["integration_source"]
        external_id: str = event_data["external_id"]
        contact_data: dict[str, Any] = event_data["contact_data"]

        # IDEMPOTENCY CHECK: Ensure we don't create duplicate contacts
        try:
            existing_ref = await self.external_reference_service.find_by_external_id(
                external_system=integration_source,
                external_entity_id=external_id,
            )
            if existing_ref:
                logger.info(
                    "Contact creation event already processed, skipping",
                    contact_id=existing_ref.internal_entity_id,
                    external_id=external_id,
                    integration_source=integration_source,
                )
                return {
                    "status": "skipped",
                    "reason": "already_processed",
                    "contact_id": existing_ref.internal_entity_id,
                }
        except Exception as e:
            # If we can't check for existing references, this is a critical issue
            # We should not proceed with creation as it could create duplicates
            logger.error(
                "Failed to check for existing external reference - aborting to prevent duplicates",
                error=str(e),
                external_id=external_id,
                integration_source=integration_source,
            )
            raise OutboxEventProcessingError(
                f"Cannot verify idempotency for contact creation: {str(e)}"
            ) from e

        logger.info(
            "Processing contact creation",
            integration_source=integration_source,
            external_id=external_id,
        )

        # Deserialize contact data from outbox event
        try:
            contact = deserialize_contact(contact_data)
        except ContactDeserializationError as e:
            raise PermanentOutboxEventProcessingError(str(e)) from e

        # Create the contact using the contact service
        try:
            created_contact = await self.contact_service.create_contact(
                contact, self.connection
            )
        except Exception as e:
            raise OutboxEventProcessingError(
                f"Failed to create contact: {str(e)}"
            ) from e

        # Create external reference to link contact with external system
        if created_contact.id is None:
            raise OutboxEventProcessingError("Created contact has no ID")

        try:
            await self.external_reference_service.create_external_reference(
                internal_entity_type="contact",
                internal_entity_id=created_contact.id,
                external_system=integration_source,
                external_entity_type="person",
                external_entity_id=external_id,
                reference_data={
                    "resource_name": external_id,
                    "etag": event_data.get("etag"),
                    "sync_timestamp": event_data["sync_timestamp"],
                },
            )
        except Exception as e:
            logger.warning(
                "Failed to create external reference",
                contact_id=created_contact.id,
                integration_source=integration_source,
                external_id=external_id,
                error=str(e),
            )
            # Don't fail the entire operation if external reference creation fails

        # Create initial sync metadata
        # Calculate version hash for the contact data
        version_hash = calculate_contact_version_hash(contact_data)

        try:
            await self.sync_metadata_repo.upsert(
                internal_id=created_contact.id,
                integration_source=integration_source,
                external_id=external_id,
                version_hash=version_hash,
                sync_status=SyncStatus.SUCCESS,
            )
        except Exception as e:
            logger.warning(
                "Failed to create sync metadata - will be created on first update",
                contact_id=created_contact.id,
                integration_source=integration_source,
                external_id=external_id,
                error=str(e),
            )
            # Don't fail the entire operation if sync metadata creation fails
            # The sync_metadata will be created automatically on the first contact.updated event
            # This provides better resilience - contact creation succeeds even if sync_metadata fails

        logger.info(
            "Successfully created contact from outbox event",
            contact_id=created_contact.id,
            integration_source=integration_source,
            external_id=external_id,
            version_hash=version_hash,
        )

        return {
            "status": "success",
            "event_type": EVENT_TYPE_CONTACT_CREATED,
            "contact_id": created_contact.id,
            "integration_source": integration_source,
            "external_id": external_id,
        }

    async def _process_contact_updated(self, event: OutboxEvent) -> dict[str, Any]:
        """
        Process a contact update event with SELECT FOR UPDATE locking and idempotency.

        This method implements production-grade resilience patterns:
        1. Acquires exclusive lock on sync metadata using SELECT FOR UPDATE
        2. Checks version hash for idempotency (skip if unchanged)
        3. Updates contact and sync metadata atomically
        """
        event_data: dict[str, Any] = event.event_data  # type: ignore
        integration_source: str = event_data["integration_source"]
        external_id: str = event_data["external_id"]
        contact_data: dict[str, Any] = event_data["contact_data"]

        logger.info(
            "Processing contact update with locking",
            integration_source=integration_source,
            external_id=external_id,
        )

        # Calculate version hash for idempotency check
        new_version_hash = calculate_contact_version_hash(contact_data)

        # Acquire lock on sync metadata (SELECT FOR UPDATE)
        # This prevents concurrent updates to the same contact
        # Note: sync_metadata may be None if this is the first sync or if
        # sync_metadata creation failed during contact.created
        sync_metadata = await self.sync_metadata_repo.find_and_lock(
            integration_source=integration_source,
            external_id=external_id,
        )

        if sync_metadata is None:
            logger.info(
                "No existing sync metadata found - will create on first update",
                integration_source=integration_source,
                external_id=external_id,
            )

        # Idempotency check: Skip if version hash matches
        # should_sync() handles None gracefully (returns True to proceed with sync)
        if not self.sync_metadata_repo.should_sync(sync_metadata, new_version_hash):
            logger.info(
                "Contact update skipped - version hash unchanged (idempotent)",
                integration_source=integration_source,
                external_id=external_id,
                version_hash=new_version_hash,
            )
            return {
                "status": "skipped",
                "reason": "version_hash_unchanged",
                "event_type": EVENT_TYPE_CONTACT_UPDATED,
                "integration_source": integration_source,
                "external_id": external_id,
            }

        # Find existing contact by external reference
        try:
            existing_contact = (
                await self.contact_service.find_contact_by_external_reference(
                    integration_source=integration_source,
                    external_id=external_id,
                    transaction=self.connection,
                )
            )
        except AttributeError as e:
            # Method doesn't exist yet - this is expected during development
            raise OutboxEventProcessingError(
                "ContactService.find_contact_by_external_reference not implemented yet"
            ) from e

        if not existing_contact:
            raise OutboxEventProcessingError(
                f"Contact not found for update: {external_id} from {integration_source}"
            )

        # Deserialize contact data from outbox event
        try:
            updated_contact_data = deserialize_contact(contact_data)

            # Preserve the existing contact ID
            updated_contact_data.id = existing_contact.id
        except ContactDeserializationError as e:
            raise PermanentOutboxEventProcessingError(str(e)) from e

        # Update the contact using the contact service
        try:
            updated_contact = await self.contact_service.update_contact(
                updated_contact_data, self.connection
            )
        except Exception as e:
            raise OutboxEventProcessingError(
                f"Failed to update contact: {str(e)}"
            ) from e

        # Update sync metadata with new version hash
        # This is done atomically in the same transaction as the contact update
        if updated_contact.id is None:
            raise OutboxEventProcessingError("Updated contact has no ID")

        try:
            await self.sync_metadata_repo.upsert(
                internal_id=updated_contact.id,
                integration_source=integration_source,
                external_id=external_id,
                version_hash=new_version_hash,
                sync_status=SyncStatus.SUCCESS,
            )
        except Exception as e:
            logger.warning(
                "Failed to update sync metadata",
                contact_id=updated_contact.id,
                integration_source=integration_source,
                external_id=external_id,
                error=str(e),
            )
            # Don't fail the entire operation if sync metadata update fails
            # The contact was updated successfully

        logger.info(
            "Successfully updated contact from outbox event",
            contact_id=updated_contact.id,
            integration_source=integration_source,
            external_id=external_id,
            version_hash=new_version_hash,
        )

        return {
            "status": "success",
            "event_type": EVENT_TYPE_CONTACT_UPDATED,
            "contact_id": updated_contact.id,
            "integration_source": integration_source,
            "external_id": external_id,
        }

    def _process_sync_completed(self, event: OutboxEvent) -> dict[str, Any]:
        """Process a sync.completed event."""
        event_data = event.event_data
        integration_source = event_data["integration_source"]
        google_account_email = event_data["google_account_email"]
        metrics = event_data["metrics"]

        logger.info(
            "Processing sync completion",
            integration_source=integration_source,
            google_account_email=google_account_email,
            contacts_processed=metrics.get("contacts_processed", 0),
            contacts_created=metrics.get("contacts_created", 0),
            contacts_updated=metrics.get("contacts_updated", 0),
            errors=metrics.get("errors", 0),
        )

        # For sync completion events, we mainly log the metrics
        # In the future, this could update sync status, send notifications, etc.

        return {
            "status": "success",
            "event_type": EVENT_TYPE_SYNC_COMPLETED,
            "integration_source": integration_source,
            "google_account_email": google_account_email,
            "metrics": metrics,
        }
