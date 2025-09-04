"""
Outbox Event Processor for handling integration sync events.

Processes outbox events created by integration workers to create/update
contacts in the core system using the message-based architecture pattern.
"""

from typing import Any

import structlog
from core_shared.models.outbox import OutboxEvent
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.services.contact_service import ContactService
from app.core.integrations.external_reference_service import ExternalReferenceService
from app.core.integrations.google_contacts.api_models import GooglePerson
from app.core.integrations.google_contacts.transformer import GoogleContactTransformer

logger = structlog.get_logger()


class OutboxEventProcessingError(Exception):
    """Raised when outbox event processing fails."""

    pass


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
        self.google_transformer = GoogleContactTransformer()
        self.external_reference_service = ExternalReferenceService(connection)

    async def process_event(self, event: OutboxEvent) -> dict[str, Any]:
        """
        Process a single outbox event.

        Args:
            event: Outbox event to process

        Returns:
            Processing result dictionary

        Raises:
            OutboxEventProcessingError: If event processing fails
        """
        logger.info(
            "Processing outbox event",
            event_id=event.id,
            event_type=event.event_type,
            retry_count=event.retry_count,
        )

        try:
            if event.event_type == "contact.created":
                return await self._process_contact_created(event)
            elif event.event_type == "contact.updated":
                return await self._process_contact_updated(event)
            elif event.event_type == "sync.completed":
                return await self._process_sync_completed(event)
            else:
                raise OutboxEventProcessingError(
                    f"Unknown event type: {event.event_type}"
                )

        except Exception as e:
            logger.error(
                "Failed to process outbox event",
                event_id=event.id,
                event_type=event.event_type,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise OutboxEventProcessingError(
                f"Failed to process {event.event_type} event: {str(e)}"
            ) from e

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
            # If we can't check for existing references, log and continue
            # This ensures we don't block processing due to reference service issues
            logger.warning(
                "Could not check for existing external reference, proceeding with creation",
                error=str(e),
                external_id=external_id,
                integration_source=integration_source,
            )

        logger.info(
            "Processing contact creation",
            integration_source=integration_source,
            external_id=external_id,
        )

        # Transform Google contact data to our Contact entity
        try:
            google_person = GooglePerson.model_validate(contact_data)
            contact = self.google_transformer.transform_person(google_person)
        except Exception as e:
            raise OutboxEventProcessingError(
                f"Failed to transform Google contact data: {str(e)}"
            ) from e

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
                    "etag": contact_data.get("etag"),
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

        logger.info(
            "Successfully created contact from outbox event",
            contact_id=created_contact.id,
            integration_source=integration_source,
            external_id=external_id,
        )

        return {
            "status": "success",
            "event_type": "contact.created",
            "contact_id": created_contact.id,
            "integration_source": integration_source,
            "external_id": external_id,
        }

    async def _process_contact_updated(self, event: OutboxEvent) -> dict[str, Any]:
        """Process a contact.updated event."""
        event_data: dict[str, Any] = event.event_data  # type: ignore
        integration_source: str = event_data["integration_source"]
        external_id: str = event_data["external_id"]
        contact_data: dict[str, Any] = event_data["contact_data"]

        logger.info(
            "Processing contact update",
            integration_source=integration_source,
            external_id=external_id,
        )

        # Find existing contact by external reference
        # TODO: Implement find_contact_by_external_reference in ContactService
        # For now, we'll raise an error to indicate this needs implementation
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

        # Transform Google contact data to our Contact entity
        try:
            google_person = GooglePerson.model_validate(contact_data)
            updated_contact_data = self.google_transformer.transform_person(
                google_person
            )

            # Preserve the existing contact ID
            updated_contact_data.id = existing_contact.id
        except Exception as e:
            raise OutboxEventProcessingError(
                f"Failed to transform Google contact data: {str(e)}"
            ) from e

        # Update the contact using the contact service
        try:
            updated_contact = await self.contact_service.update_contact(
                updated_contact_data, self.connection
            )
        except Exception as e:
            raise OutboxEventProcessingError(
                f"Failed to update contact: {str(e)}"
            ) from e

        logger.info(
            "Successfully updated contact from outbox event",
            contact_id=updated_contact.id,
            integration_source=integration_source,
            external_id=external_id,
        )

        return {
            "status": "success",
            "event_type": "contact.updated",
            "contact_id": updated_contact.id,
            "integration_source": integration_source,
            "external_id": external_id,
        }

    async def _process_sync_completed(self, event: OutboxEvent) -> dict[str, Any]:
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
            "event_type": "sync.completed",
            "integration_source": integration_source,
            "google_account_email": google_account_email,
            "metrics": metrics,
        }
