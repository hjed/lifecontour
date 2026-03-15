"""
Outbox Event Processor for handling integration sync events.

Processes outbox events created by integration workers to create/update
contacts in the core system using the message-based architecture pattern.

This processor implements production-grade resilience patterns:
1. SELECT FOR UPDATE locking for concurrent sync operations
2. Version hash-based idempotency checks
3. Atomic operations with proper transaction handling
"""

import json
from collections.abc import Sequence
from typing import Any, cast

import structlog
from core_shared.models.contacts.entities import Contact, Tag
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


def _normalize_email_dedup_key(value: str) -> str:
    """Build a stable deduplication key for email methods."""
    return value.strip().lower()


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
        from app.core.contacts.adapters.sql.tag_repository import SqlTagRepository

        self.tag_repo = SqlTagRepository(connection)

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

    def _normalize_contact_data(self, contact_data: dict[str, Any]) -> dict[str, Any]:
        """Normalize inbound contact data before versioning and persistence."""
        normalized_contact_data = dict(contact_data)

        # Strip explicit None lists so deserialize_contact doesn't fail
        for list_field in ["methods", "addresses", "notes", "tags"]:
            if (
                list_field in normalized_contact_data
                and normalized_contact_data[list_field] is None
            ):
                del normalized_contact_data[list_field]

        methods = normalized_contact_data.get("methods")
        if isinstance(methods, Sequence) and not isinstance(methods, (str, bytes)):
            normalized_contact_data["methods"] = self._deduplicate_contact_methods(
                methods
            )
        return normalized_contact_data

    def _deduplicate_contact_methods(self, methods: Sequence[object]) -> list[Any]:
        """Deduplicate duplicate inbound email methods while preserving order."""
        deduplicated_methods: list[Any] = []
        seen_email_indexes: dict[str, int] = {}

        for raw_method in methods:
            if not isinstance(raw_method, dict):
                deduplicated_methods.append(raw_method)
                continue

            method = dict(raw_method)
            if method.get("method_type") != "email":
                deduplicated_methods.append(method)
                continue

            value = method.get("value")
            if not isinstance(value, str):
                deduplicated_methods.append(method)
                continue

            dedup_key = _normalize_email_dedup_key(value)
            if not dedup_key:
                deduplicated_methods.append(method)
                continue

            existing_index = seen_email_indexes.get(dedup_key)
            if existing_index is None:
                seen_email_indexes[dedup_key] = len(deduplicated_methods)
                deduplicated_methods.append(method)
                continue

            existing_method = deduplicated_methods[existing_index]
            if not isinstance(existing_method, dict):
                deduplicated_methods[existing_index] = method
                continue

            existing_is_primary = bool(existing_method.get("is_primary"))
            new_is_primary = bool(method.get("is_primary"))

            if new_is_primary and not existing_is_primary:
                merged_method = dict(existing_method)
                merged_method.update(method)
                merged_method["is_primary"] = True
                deduplicated_methods[existing_index] = merged_method
            elif not existing_method.get("label") and method.get("label"):
                existing_method["label"] = method["label"]

            logger.info(
                "Deduplicated duplicate inbound email method",
                email=value,
            )

        return deduplicated_methods

    def _extract_candidate_emails(self, contact_data: dict[str, Any]) -> list[str]:
        """Extract unique candidate email addresses from normalized contact data."""
        methods = contact_data.get("methods")
        if not isinstance(methods, Sequence) or isinstance(methods, (str, bytes)):
            return []

        candidate_emails: list[str] = []
        seen_email_keys: set[str] = set()

        for raw_method in methods:
            if not isinstance(raw_method, dict):
                continue
            if raw_method.get("method_type") != "email":
                continue

            value = raw_method.get("value")
            if not isinstance(value, str):
                continue

            stripped_value = value.strip()
            if not stripped_value:
                continue

            dedup_key = _normalize_email_dedup_key(stripped_value)
            if dedup_key in seen_email_keys:
                continue

            seen_email_keys.add(dedup_key)
            candidate_emails.append(stripped_value)

        return candidate_emails

    async def _find_existing_contact_for_email_reconciliation(
        self,
        contact_data: dict[str, Any],
        integration_source: str,
    ) -> Contact | None:
        """Find a single safe local contact candidate for email-based reconciliation."""
        matched_contacts: dict[int, Contact] = {}

        for email in self._extract_candidate_emails(contact_data):
            existing_contact = await self.contact_service.get_contact_by_email(email)
            if existing_contact is None or existing_contact.id is None:
                continue
            matched_contacts[existing_contact.id] = existing_contact

        if not matched_contacts:
            return None

        if len(matched_contacts) > 1:
            matched_contact_ids = sorted(matched_contacts.keys())
            raise OutboxEventProcessingError(
                "Multiple existing contacts matched inbound email addresses for "
                f"{integration_source}: {matched_contact_ids}"
            )

        matched_contact = next(iter(matched_contacts.values()))
        if matched_contact.id is None:
            raise OutboxEventProcessingError(
                "Matched contact is missing an ID during email reconciliation"
            )

        existing_integration_reference = (
            await self.external_reference_service.find_external_reference(
                internal_entity_type="contact",
                internal_entity_id=matched_contact.id,
                external_system=integration_source,
            )
        )
        if existing_integration_reference is not None:
            raise OutboxEventProcessingError(
                "Matched local contact is already linked to integration source "
                f"{integration_source} via external ID "
                f"{existing_integration_reference.external_entity_id}"
            )

        return matched_contact

    def _parse_reference_data(
        self, reference_data: str, reference_id: int | None = None
    ) -> dict[str, Any] | None:
        """Parse reference_data safely, expecting standard JSON format."""
        import json

        if not reference_data:
            return None

        try:
            ref_data = json.loads(reference_data)
            if isinstance(ref_data, dict):
                return ref_data
        except json.JSONDecodeError as e:
            logger.warning(
                "Failed to parse reference_data as JSON",
                error=str(e),
                reference_id=reference_id,
                reference_data_preview=reference_data[:200],
            )
        except Exception as e:
            logger.warning(
                "Unexpected error parsing reference_data",
                error=str(e),
                reference_id=reference_id,
                reference_data_preview=reference_data[:200],
            )

        return None

    async def _resolve_contact_tags(
        self,
        contact_data: dict[str, Any],
        existing_reference_data: str | None = None,
        existing_reference_id: int | None = None,
        existing_contact_tags: list[Tag] | None = None,
    ) -> list[Tag] | None:
        """
        Merge inbound tags with existing local tags based on sync history.
        Preserves locally created tags that were never synced by the integration.
        """

        incoming_tags = contact_data.get("tags")
        if incoming_tags is None:
            return None

        # Preserve incoming order while deduplicating
        incoming_tag_names_ordered = []
        for tag in incoming_tags:
            tag_name = tag["name"]
            if tag_name not in incoming_tag_names_ordered:
                incoming_tag_names_ordered.append(tag_name)

        incoming_tag_names_set = set(incoming_tag_names_ordered)

        existing_contact_tags = existing_contact_tags or []
        existing_tag_names = {str(tag.name) for tag in existing_contact_tags}

        # Determine which tags were previously synced
        previously_synced_tags = set()
        if existing_reference_data:
            ref_data = self._parse_reference_data(
                existing_reference_data, existing_reference_id
            )
            if isinstance(ref_data, dict):
                if "synced_tags" in ref_data:
                    synced = ref_data.get("synced_tags")
                    if isinstance(synced, list) and all(
                        isinstance(x, str) for x in synced
                    ):
                        previously_synced_tags = set(synced)
                    else:
                        logger.warning(
                            "synced_tags in reference_data is not a list of strings",
                            reference_id=existing_reference_id,
                            synced_value=synced,
                        )

        # Tags that are purely local (never synced before)
        local_only_tags = existing_tag_names - previously_synced_tags

        # Stable order: inbound tags first, then local only
        final_tag_names_ordered = list(incoming_tag_names_ordered)
        for tag_name in sorted(local_only_tags):
            if tag_name not in incoming_tag_names_set:
                final_tag_names_ordered.append(tag_name)

        if not final_tag_names_ordered:
            return []

        # Bulk lookup all required tags
        found_tags_dict = await self.tag_repo.find_by_names(final_tag_names_ordered)

        resolved_tags = []
        for tag_name in final_tag_names_ordered:
            if tag_name in found_tags_dict:
                resolved_tags.append(found_tags_dict[tag_name])
            else:
                from core_shared.models.contacts.value_objects import TagName

                new_tag = Tag(name=TagName(tag_name))
                saved_tag = await self.tag_repo.save(new_tag)
                resolved_tags.append(saved_tag)

        return resolved_tags

    async def _process_contact_created(self, event: OutboxEvent) -> dict[str, Any]:
        """Process a contact.created event."""
        event_data: dict[str, Any] = cast(dict[str, Any], event.event_data)
        integration_source: str = event_data["integration_source"]
        external_id: str = event_data["external_id"]
        contact_data = self._normalize_contact_data(event_data["contact_data"])

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

        # Reconcile to an existing local contact when there is a single clear email match.
        try:
            matched_contact = (
                await self._find_existing_contact_for_email_reconciliation(
                    contact_data=contact_data,
                    integration_source=integration_source,
                )
            )
        except Exception as e:
            raise OutboxEventProcessingError(
                f"Failed to reconcile contact by email: {str(e)}"
            ) from e

        contact_action = "created"

        # Create or update the contact using the contact service.
        try:
            if matched_contact is None:
                created_contact = await self.contact_service.create_contact(
                    contact, self.connection
                )
            else:
                contact.id = matched_contact.id
                created_contact = await self.contact_service.update_contact(
                    contact, self.connection
                )
                contact_action = "reconciled"
                logger.info(
                    "Reused existing local contact for inbound contact creation event",
                    contact_id=created_contact.id,
                    integration_source=integration_source,
                    external_id=external_id,
                )
        except Exception as e:
            raise OutboxEventProcessingError(
                f"Failed to {contact_action} contact: {str(e)}"
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
                reference_data=json.dumps(
                    {
                        "resource_name": external_id,
                        "etag": event_data.get("etag"),
                        "sync_timestamp": event_data["sync_timestamp"],
                    }
                ),
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
            "Successfully processed contact creation from outbox event",
            contact_id=created_contact.id,
            contact_action=contact_action,
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
        event_data: dict[str, Any] = cast(dict[str, Any], event.event_data)
        integration_source: str = event_data["integration_source"]
        external_id: str = event_data["external_id"]
        contact_data = self._normalize_contact_data(event_data["contact_data"])

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

            if existing_contact.id is None:
                raise OutboxEventProcessingError("Existing contact has no ID")

            # Preserve the existing contact ID
            updated_contact_data.id = existing_contact.id

            # Refetch full contact to ensure we have current tags
            full_existing_contact = await self.contact_service.get_contact_by_id(
                existing_contact.id
            )
            existing_tags = full_existing_contact.tags if full_existing_contact else []

            # Find existing integration reference
            existing_ref = (
                await self.external_reference_service.find_external_reference(
                    internal_entity_type="contact",
                    internal_entity_id=existing_contact.id,
                    external_system=integration_source,
                )
            )

            ref_data_str = existing_ref.reference_data if existing_ref else None
            if "tags" in contact_data and contact_data["tags"] is not None:
                resolved_tags = await self._resolve_contact_tags(
                    contact_data,
                    existing_reference_data=ref_data_str,
                    existing_reference_id=existing_ref.id if existing_ref else None,
                    existing_contact_tags=existing_tags,
                )
                updated_contact_data.tags = resolved_tags
            else:
                updated_contact_data.tags = None
        except ContactDeserializationError as e:
            raise PermanentOutboxEventProcessingError(str(e)) from e

        # Update the contact using the contact service
        try:
            updated_contact = await self.contact_service.update_contact(
                updated_contact_data, self.connection
            )

            # Update reference data with new synced tags
            if (
                existing_ref
                and "tags" in contact_data
                and contact_data["tags"] is not None
            ):
                incoming_tag_names = [
                    tag_data["name"] for tag_data in contact_data["tags"]
                ]

                new_ref_data = {}
                if existing_ref.reference_data:
                    parsed = self._parse_reference_data(
                        existing_ref.reference_data, existing_ref.id
                    )
                    if parsed is not None:
                        new_ref_data = parsed

                new_ref_data["synced_tags"] = incoming_tag_names
                await self.external_reference_service.update_external_reference(
                    reference_id=existing_ref.id,
                    reference_data=new_ref_data,
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
