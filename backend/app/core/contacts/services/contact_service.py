"""Main contact service with transaction management."""

import asyncio
from typing import Any, cast

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.entities import (
    Contact,
    ContactAddress,
    ContactMethod,
    ContactNote,
    MethodType,
    Tag,
)
from app.core.contacts.models.events import (
    ContactAddressAdded,
    ContactCreated,
    ContactDeleted,
    ContactMethodAdded,
    ContactNoteAdded,
    ContactUpdated,
    TagAssigned,
    TagRemoved,
)
from app.core.contacts.models.exceptions import (
    ContactValidationError,
    DuplicateEmailError,
    PrimaryAddressConflictError,
    PrimaryMethodConflictError,
)
from app.core.contacts.models.repositories import (
    ContactEventPublisher,
    ContactFieldHistoryRepository,
    ContactRepository,
    TagRepository,
)
from app.core.contacts.services.address_validation_service import (
    AddressValidationService,
)
from app.core.contacts.services.contact_history_service import ContactHistoryService
from app.core.contacts.services.contact_validation_service import (
    ContactValidationService,
)
from app.core.contacts.services.tag_hierarchy_service import TagHierarchyService

logger = structlog.get_logger()


class ContactService:
    """Main contact service with transaction management and retry logic."""

    def __init__(
        self,
        contact_repo: ContactRepository,
        tag_repo: TagRepository,
        history_repo: ContactFieldHistoryRepository,
        event_publisher: ContactEventPublisher,
        address_validation_service: AddressValidationService,
        contact_validation_service: ContactValidationService,
        history_service: ContactHistoryService,
        tag_hierarchy_service: TagHierarchyService,
    ):
        self.contact_repo = contact_repo
        self.tag_repo = tag_repo
        self.history_repo = history_repo
        self.event_publisher = event_publisher

        # Initialize services with dependencies
        self.address_validation = (
            address_validation_service or AddressValidationService()
        )
        self.contact_validation = (
            contact_validation_service or ContactValidationService(contact_repo)
        )
        self.history_service = history_service or ContactHistoryService(history_repo)
        self.tag_hierarchy = tag_hierarchy_service or TagHierarchyService(tag_repo)

    async def _execute_with_retry(self, operation: Any, max_retries: int = 3) -> Any:
        """Execute operation with retry logic for transaction conflicts."""
        last_exception = None

        for attempt in range(max_retries):
            try:
                return await operation()
            except IntegrityError as e:
                last_exception = e
                if attempt < max_retries - 1:
                    await self._wait_before_retry(attempt)
                    continue
                else:
                    self._convert_integrity_error_to_domain_exception(e)
            except Exception as e:
                # Don't retry for non-transient errors - re-raise immediately
                logger.error("Non-transient error in operation", error=str(e))
                raise

        # Should never reach here, but just in case
        if last_exception:
            raise last_exception

    async def _wait_before_retry(self, attempt: int) -> None:
        """Wait before retry with exponential backoff."""
        await asyncio.sleep(0.1 * (2**attempt))

    def _convert_integrity_error_to_domain_exception(
        self, error: IntegrityError
    ) -> None:
        """Convert IntegrityError to appropriate domain exception."""
        error_message = str(error).lower()

        if "unique" not in error_message:
            raise error

        if "email" in error_message:
            raise DuplicateEmailError("Email already exists", 0) from error
        elif "primary" in error_message:
            if "method" in error_message:
                raise PrimaryMethodConflictError(0, "unknown") from error
            elif "address" in error_message:
                raise PrimaryAddressConflictError(0) from error

        raise error

    async def create_contact(
        self, contact: Contact, transaction: AsyncConnection
    ) -> Contact:
        """
        Create a new contact with transaction management.

        This method creates a contact and all attached methods, addresses, and notes
        in a single database transaction. Attach methods, addresses, and notes to the
        Contact entity before calling this method for optimal transaction handling.

        Args:
            contact: Contact entity with optional attached methods, addresses, and notes
            transaction: Database transaction

        Returns:
            The saved Contact with all attached entities and assigned IDs

        Raises:
            ContactValidationError: If validation fails or IDs are missing after save
            DuplicateEmailError: If any email method already exists
            PrimaryMethodConflictError: If primary method constraints are violated
            PrimaryAddressConflictError: If primary address constraints are violated

        Example:
            # Create contact with attached method and note
            contact = Contact(first_name="John", last_name="Doe")
            contact.methods.append(ContactMethod(
                method_type=MethodType.EMAIL,
                value="john@example.com",
                contact_id=0,  # Will be set during save
                is_primary=True
            ))
            contact.notes.append(ContactNote(
                content="Important client",
                contact_id=0  # Will be set during save
            ))
            saved_contact = await service.create_contact(contact, transaction)
        """

        async def _create_operation() -> Contact:
            # Validate and save basic contact fields
            saved_contact = await self._validate_and_save_contact_basic_fields(
                contact, transaction
            )
            # contact_id is guaranteed to be not None after _ensure_contact_has_id
            contact_id = saved_contact.id
            assert contact_id is not None

            # Save all related entities
            saved_entities = await self._save_all_related_entities(
                contact_id, contact, transaction
            )

            # Build complete contact with related entities
            complete_contact = self._build_complete_contact(
                saved_contact, saved_entities
            )

            # Publish creation event
            await self._publish_contact_created_event(complete_contact, transaction)

            return complete_contact

        return cast(Contact, await self._execute_with_retry(_create_operation))

    async def update_contact(
        self,
        contact: Contact,
        transaction: AsyncConnection,
    ) -> Contact:
        """
        Update an existing contact with transaction management.

        This method updates a contact and all attached methods, addresses, and notes
        in a single database transaction. Attach methods, addresses, and notes to the
        Contact entity before calling this method for optimal transaction handling.

        Note: This implementation uses a replacement strategy for methods/addresses/notes.
        All existing methods/addresses/notes are replaced with the provided ones.

        Args:
            contact: Contact entity with ID and optional attached methods, addresses, and notes
            transaction: Database transaction

        Returns:
            The updated Contact with all attached entities and assigned IDs

        Raises:
            ContactValidationError: If contact ID is missing, contact not found, or validation fails
            DuplicateEmailError: If any email method already exists (excluding this contact)
            PrimaryMethodConflictError: If primary method constraints are violated
            PrimaryAddressConflictError: If primary address constraints are violated
        """
        if contact.id is None:
            raise ContactValidationError("id", "Contact ID is required for updates")

        async def _update_operation() -> Contact:
            assert contact.id is not None

            # Get current contact and calculate changes
            current_contact = await self._get_existing_contact(contact.id)
            changed_fields = self._calculate_changed_fields(current_contact, contact)

            # Validate and save basic contact fields
            saved_contact = await self._validate_and_save_contact_basic_fields(
                contact, transaction, exclude_contact_id=contact.id
            )
            # contact_id is guaranteed to be not None after _ensure_contact_has_id
            contact_id = saved_contact.id
            assert contact_id is not None

            # Handle related entities update
            saved_entities = await self._handle_update_relations(
                contact_id, contact, current_contact, transaction
            )

            # Build complete contact with related entities
            complete_contact = self._build_complete_contact_for_update(
                saved_contact, saved_entities, current_contact, contact
            )

            # Publish update events if there were changes
            if changed_fields:
                await self._publish_contact_updated_events(
                    complete_contact, changed_fields, transaction
                )

            return complete_contact

        return cast(Contact, await self._execute_with_retry(_update_operation))

    def _calculate_changed_fields(
        self, current_contact: Contact, updated_contact: Contact
    ) -> dict[str, Any]:
        """Calculate which fields have changed between current and updated contact."""
        changed_fields = {}

        # Check basic contact fields
        if current_contact.first_name != updated_contact.first_name:
            changed_fields["first_name"] = (
                current_contact.first_name,
                updated_contact.first_name,
            )

        if current_contact.last_name != updated_contact.last_name:
            changed_fields["last_name"] = (
                current_contact.last_name or "",
                updated_contact.last_name or "",
            )

        if current_contact.middle_name != updated_contact.middle_name:
            changed_fields["middle_name"] = (
                current_contact.middle_name or "",
                updated_contact.middle_name or "",
            )

        if current_contact.nick_name != updated_contact.nick_name:
            changed_fields["nick_name"] = (
                current_contact.nick_name or "",
                updated_contact.nick_name or "",
            )

        # For methods, addresses, and notes, we'll do a simplified comparison
        # A more sophisticated implementation could compare individual items
        if len(current_contact.methods) != len(updated_contact.methods):
            changed_fields["contact_methods"] = (
                f"count:{len(current_contact.methods)}",
                f"count:{len(updated_contact.methods)}",
            )

        if len(current_contact.addresses) != len(updated_contact.addresses):
            changed_fields["addresses"] = (
                f"count:{len(current_contact.addresses)}",
                f"count:{len(updated_contact.addresses)}",
            )

        if len(current_contact.notes) != len(updated_contact.notes):
            changed_fields["notes"] = (
                f"count:{len(current_contact.notes)}",
                f"count:{len(updated_contact.notes)}",
            )

        # Check tag changes by comparing tag IDs
        current_tag_ids = {tag.id for tag in current_contact.tags if tag.id is not None}
        updated_tag_ids = {tag.id for tag in updated_contact.tags if tag.id is not None}

        if current_tag_ids != updated_tag_ids:
            changed_fields["tags"] = (
                f"ids:{sorted(current_tag_ids)}",
                f"ids:{sorted(updated_tag_ids)}",
            )

        return changed_fields

    async def _validate_and_save_contact_basic_fields(
        self,
        contact: Contact,
        transaction: AsyncConnection,
        exclude_contact_id: int | None = None,
    ) -> Contact:
        """Validate contact data and save basic contact fields."""
        # Validate contact data
        await self._validate_contact_data(contact, transaction, exclude_contact_id)

        # Save contact (basic fields only)
        saved_contact = await self.contact_repo.save(contact)

        # Ensure contact has ID after save
        self._ensure_contact_has_id(saved_contact)

        return saved_contact

    def _ensure_contact_has_id(self, contact: Contact) -> None:
        """Ensure contact has ID after save."""
        if contact.id is None:
            raise ContactValidationError("id", "Contact ID is required after save")

    async def _get_existing_contact(self, contact_id: int) -> Contact:
        """Get existing contact by ID, raising error if not found."""
        current_contact = await self.contact_repo.find_by_id(contact_id)
        if current_contact is None:
            raise ContactValidationError(
                "id", f"Contact with ID {contact_id} not found"
            )
        return current_contact

    async def _save_all_related_entities(
        self,
        contact_id: int,
        contact: Contact,
        transaction: AsyncConnection,
    ) -> dict[str, list[Any]]:
        """Save all related entities and return them in a dictionary."""
        saved_methods = await self._save_contact_methods(
            contact_id, contact.methods, transaction
        )
        saved_addresses = await self._save_contact_addresses(
            contact_id, contact.addresses, transaction
        )
        saved_notes = await self._save_contact_notes(
            contact_id, contact.notes, transaction
        )
        saved_tags = await self._save_contact_tags(
            contact_id, contact.tags, transaction
        )

        return {
            "methods": saved_methods,
            "addresses": saved_addresses,
            "notes": saved_notes,
            "tags": saved_tags,
        }

    def _build_complete_contact(
        self, saved_contact: Contact, saved_entities: dict[str, list[Any]]
    ) -> Contact:
        """Build complete contact with all related entities."""
        saved_contact.methods = saved_entities["methods"]
        saved_contact.addresses = saved_entities["addresses"]
        saved_contact.notes = saved_entities["notes"]
        saved_contact.tags = saved_entities["tags"]
        return saved_contact

    async def _publish_contact_created_event(
        self, contact: Contact, transaction: AsyncConnection
    ) -> None:
        """Publish contact created event."""
        assert contact.id is not None
        event = ContactCreated(
            contact.id,
            contact.first_name,
            contact.last_name,
            transaction=transaction,
        )
        await self.event_publisher.publish(event)

    async def _handle_update_relations(
        self,
        contact_id: int,
        contact: Contact,
        current_contact: Contact,
        transaction: AsyncConnection,
    ) -> dict[str, list[Any]]:
        """Handle updating related entities for contact update."""
        # Remove existing relations if new data is provided
        await self._remove_existing_relations(contact_id, contact, current_contact)

        # Save new related entities (only if new data is provided)
        saved_entities: dict[str, list[Any]] = {
            "methods": [],
            "addresses": [],
            "notes": [],
            "tags": [],
        }

        if contact.methods:
            saved_entities["methods"] = await self._save_contact_methods(
                contact_id, contact.methods, transaction
            )

        if contact.addresses:
            saved_entities["addresses"] = await self._save_contact_addresses(
                contact_id, contact.addresses, transaction
            )

        if contact.notes:
            saved_entities["notes"] = await self._save_contact_notes(
                contact_id, contact.notes, transaction
            )

        if contact.tags:
            saved_entities["tags"] = await self._save_contact_tags(
                contact_id, contact.tags, transaction
            )

        return saved_entities

    def _build_complete_contact_for_update(
        self,
        saved_contact: Contact,
        saved_entities: dict[str, list[Any]],
        current_contact: Contact,
        contact: Contact,
    ) -> Contact:
        """Build complete contact for update, preserving existing entities when not updated."""
        # If methods/addresses/notes/tags were provided, use the new ones
        # Otherwise, preserve the existing ones from the current contact
        saved_contact.methods = (
            saved_entities["methods"] if contact.methods else current_contact.methods
        )
        saved_contact.addresses = (
            saved_entities["addresses"]
            if contact.addresses
            else current_contact.addresses
        )
        saved_contact.notes = (
            saved_entities["notes"] if contact.notes else current_contact.notes
        )
        saved_contact.tags = (
            saved_entities["tags"] if contact.tags else current_contact.tags
        )
        return saved_contact

    async def _publish_contact_updated_events(
        self,
        contact: Contact,
        changed_fields: dict[str, Any],
        transaction: AsyncConnection,
    ) -> None:
        """Publish contact updated events and record history."""
        assert contact.id is not None
        await self.history_service.record_contact_change(
            contact.id, changed_fields, _transaction=transaction
        )

        event = ContactUpdated(contact.id, changed_fields, transaction=transaction)
        await self.event_publisher.publish(event)

    async def _validate_contact_data(
        self,
        contact: Contact,
        transaction: AsyncConnection,
        exclude_contact_id: int | None = None,
    ) -> None:
        """Validate contact data including methods and addresses."""
        # Validate email uniqueness if contact has email methods
        for method in contact.methods:
            if method.method_type == MethodType.EMAIL:
                await self.contact_validation.validate_email_uniqueness(
                    method.value, transaction, exclude_contact_id=exclude_contact_id
                )

        # Validate addresses
        for address in contact.addresses:
            await self.address_validation.validate_with_transaction(
                address, transaction
            )

    async def _save_contact_methods(
        self,
        contact_id: int,
        methods: list[ContactMethod],
        transaction: AsyncConnection,
    ) -> list[ContactMethod]:
        """Save contact methods and publish events."""
        saved_methods = []
        for method in methods:
            # Update contact_id for the method
            method.contact_id = contact_id

            # Validate primary method constraints
            if method.is_primary:
                await self.contact_validation.validate_primary_method(
                    contact_id, method.method_type, transaction
                )

            saved_method = await self.contact_repo.add_method(contact_id, method)
            saved_methods.append(saved_method)

            # Ensure method has ID after save
            if saved_method.id is None:
                raise ContactValidationError("id", "Method ID is required after save")

            # Publish method added event
            method_event = ContactMethodAdded(
                contact_id,
                saved_method.id,
                method.method_type.value,
                method.value,
                transaction=transaction,
            )
            await self.event_publisher.publish(method_event)

        return saved_methods

    async def _save_contact_addresses(
        self,
        contact_id: int,
        addresses: list[ContactAddress],
        transaction: AsyncConnection,
    ) -> list[ContactAddress]:
        """Save contact addresses and publish events."""
        saved_addresses = []
        for address in addresses:
            # Update contact_id for the address
            address.contact_id = contact_id

            # Validate primary address constraints
            if address.is_primary:
                await self.contact_validation.validate_primary_address(
                    contact_id, transaction
                )

            saved_address = await self.contact_repo.add_address(contact_id, address)
            saved_addresses.append(saved_address)

            # Ensure address has ID after save
            if saved_address.id is None:
                raise ContactValidationError("id", "Address ID is required after save")

            # Publish address added event
            address_event = ContactAddressAdded(
                contact_id,
                saved_address.id,
                address.street_line_1,
                address.country_code,
                transaction=transaction,
            )
            await self.event_publisher.publish(address_event)

        return saved_addresses

    async def _save_contact_notes(
        self, contact_id: int, notes: list[ContactNote], transaction: AsyncConnection
    ) -> list[ContactNote]:
        """Save contact notes and publish events."""
        saved_notes = []
        for note in notes:
            # Update contact_id for the note
            note.contact_id = contact_id

            saved_note = await self.contact_repo.add_note(contact_id, note)
            saved_notes.append(saved_note)

            # Ensure note has ID after save
            if saved_note.id is None:
                raise ContactValidationError("id", "Note ID is required after save")

            # Publish note added event
            note_event = ContactNoteAdded(
                contact_id, saved_note.id, note.content, transaction=transaction
            )
            await self.event_publisher.publish(note_event)

        return saved_notes

    async def _save_contact_tags(
        self, contact_id: int, tags: list[Tag], transaction: AsyncConnection
    ) -> list[Tag]:
        """Save contact tags and publish events."""
        saved_tags = []
        for tag in tags:
            # Ensure tag has ID
            if tag.id is None:
                raise ContactValidationError("id", "Tag ID is required for assignment")

            # Assign tag to contact
            await self.contact_repo.assign_tag(contact_id, tag.id)
            saved_tags.append(tag)

            # Publish tag assigned event
            tag_event = TagAssigned(
                contact_id, tag.id, str(tag.name), transaction=transaction
            )
            await self.event_publisher.publish(tag_event)

        return saved_tags

    async def _remove_existing_relations(
        self, contact_id: int, contact: Contact, current_contact: Contact
    ) -> None:
        """Remove existing relations when updating contact."""
        # Only replace methods if new methods are provided
        if contact.methods:
            await self.contact_repo.delete_all_methods(contact_id)

        # Only replace addresses if new addresses are provided
        if contact.addresses:
            await self.contact_repo.delete_all_addresses(contact_id)

        # Only replace notes if new notes are provided
        if contact.notes:
            await self.contact_repo.delete_all_notes(contact_id)

        # Only replace tags if new tags are provided
        if contact.tags:
            # Remove all existing tags first
            for current_tag in current_contact.tags:
                if current_tag.id is not None:
                    await self.contact_repo.remove_tag(contact_id, current_tag.id)

    async def delete_contact(
        self, contact_id: int, transaction: AsyncConnection
    ) -> None:
        """Delete a contact with transaction management."""

        async def _delete_operation() -> None:
            # Validate contact exists
            await self.contact_validation.validate_contact_exists(
                contact_id, transaction
            )

            # Delete contact
            await self.contact_repo.delete(contact_id)

            # Record field history (deletion doesn't have field changes)
            # Domain event will capture the deletion action

            # Publish event
            event = ContactDeleted(contact_id, transaction=transaction)
            await self.event_publisher.publish(event)

        return cast(None, await self._execute_with_retry(_delete_operation))

    async def assign_tag_to_contact(
        self, contact_id: int, tag_id: int, transaction: AsyncConnection
    ) -> None:
        """Assign a tag to a contact with transaction management."""

        async def _assign_operation() -> None:
            # Validate contact exists
            await self.contact_validation.validate_contact_exists(
                contact_id, transaction
            )

            # Validate tag limit
            await self.contact_validation.validate_contact_tag_limit(
                contact_id, transaction
            )

            # Validate tag exists
            tag = await self.tag_repo.find_by_id(tag_id)
            if not tag:
                from app.core.contacts.models.exceptions import TagNotFoundError

                raise TagNotFoundError(tag_id)

            # Assign tag
            await self.contact_repo.assign_tag(contact_id, tag_id)

            # Record field history
            await self.history_service.record_tag_change(
                contact_id, tag_id, "assigned", _transaction=transaction
            )

            # Publish event
            event = TagAssigned(
                contact_id, tag_id, str(tag.name), transaction=transaction
            )
            await self.event_publisher.publish(event)

        return cast(None, await self._execute_with_retry(_assign_operation))

    async def remove_tag_from_contact(
        self, contact_id: int, tag_id: int, transaction: AsyncConnection
    ) -> None:
        """Remove a tag from a contact with transaction management."""

        async def _remove_operation() -> None:
            # Validate contact exists
            await self.contact_validation.validate_contact_exists(
                contact_id, transaction
            )

            # Get tag for event
            tag = await self.tag_repo.find_by_id(tag_id)
            if not tag:
                from app.core.contacts.models.exceptions import TagNotFoundError

                raise TagNotFoundError(tag_id)

            # Remove tag
            await self.contact_repo.remove_tag(contact_id, tag_id)

            # Record field history
            await self.history_service.record_tag_change(
                contact_id, tag_id, "removed", _transaction=transaction
            )

            # Publish event
            event = TagRemoved(
                contact_id, tag_id, str(tag.name), transaction=transaction
            )
            await self.event_publisher.publish(event)

        return cast(None, await self._execute_with_retry(_remove_operation))

    async def add_contact_method(
        self, contact_id: int, method: ContactMethod, transaction: AsyncConnection
    ) -> ContactMethod:
        """
        Add a contact method to an EXISTING contact with transaction management.

        WARNING: For new contact creation, attach methods to the Contact entity
        and use create_contact() instead. This method is only for adding methods
        to contacts that already exist in the database.

        Args:
            contact_id: ID of an existing contact
            method: ContactMethod to add
            transaction: Database transaction

        Returns:
            The saved ContactMethod with assigned ID

        Raises:
            ContactValidationError: If contact doesn't exist or validation fails
            DuplicateEmailError: If email already exists
            PrimaryMethodConflictError: If primary constraint is violated
        """

        async def _add_method_operation() -> ContactMethod:
            # Validate contact exists
            await self.contact_validation.validate_contact_exists(
                contact_id, transaction
            )

            # Validate email uniqueness if it's an email
            if method.method_type == MethodType.EMAIL:
                await self.contact_validation.validate_email_uniqueness(
                    method.value, transaction
                )

            # Validate primary method constraints
            if method.is_primary:
                await self.contact_validation.validate_primary_method(
                    contact_id, method.method_type, transaction
                )

            # Add method
            saved_method = await self.contact_repo.add_method(contact_id, method)

            # Ensure method has ID after save
            if saved_method.id is None:
                raise ContactValidationError("id", "Method ID is required after save")

            # Record field history (creation doesn't have field changes)
            # Domain event will capture the addition action

            # Publish event
            event = ContactMethodAdded(
                contact_id,
                saved_method.id,
                method.method_type.value,
                method.value,
                transaction=transaction,
            )
            await self.event_publisher.publish(event)

            return saved_method

        return cast(
            ContactMethod, await self._execute_with_retry(_add_method_operation)
        )

    async def add_contact_address(
        self, contact_id: int, address: ContactAddress, transaction: AsyncConnection
    ) -> ContactAddress:
        """
        Add a contact address to an EXISTING contact with transaction management.

        WARNING: For new contact creation, attach addresses to the Contact entity
        and use create_contact() instead. This method is only for adding addresses
        to contacts that already exist in the database.

        Args:
            contact_id: ID of an existing contact
            address: ContactAddress to add
            transaction: Database transaction

        Returns:
            The saved ContactAddress with assigned ID

        Raises:
            ContactValidationError: If contact doesn't exist or validation fails
            PrimaryAddressConflictError: If primary constraint is violated
        """

        async def _add_address_operation() -> ContactAddress:
            # Validate contact exists
            await self.contact_validation.validate_contact_exists(
                contact_id, transaction
            )

            # Validate address format
            await self.address_validation.validate_with_transaction(
                address, transaction
            )

            # Validate primary address constraints
            if address.is_primary:
                await self.contact_validation.validate_primary_address(
                    contact_id, transaction
                )

            # Add address
            saved_address = await self.contact_repo.add_address(contact_id, address)

            # Ensure address has ID after save
            if saved_address.id is None:
                raise ContactValidationError("id", "Address ID is required after save")

            # Record field history (creation doesn't have field changes)
            # Domain event will capture the addition action

            # Publish event
            event = ContactAddressAdded(
                contact_id,
                saved_address.id,
                address.street_line_1,
                address.country_code,
                transaction=transaction,
            )
            await self.event_publisher.publish(event)

            return saved_address

        return cast(
            ContactAddress, await self._execute_with_retry(_add_address_operation)
        )

    async def add_contact_note(
        self, contact_id: int, note: ContactNote, transaction: AsyncConnection
    ) -> ContactNote:
        """
        Add a contact note to an EXISTING contact with transaction management.

        WARNING: For new contact creation, attach notes to the Contact entity
        and use create_contact() instead. This method is only for adding notes
        to contacts that already exist in the database.

        Args:
            contact_id: ID of an existing contact
            note: ContactNote to add
            transaction: Database transaction

        Returns:
            The saved ContactNote with assigned ID

        Raises:
            ContactValidationError: If contact doesn't exist or validation fails
        """

        async def _add_note_operation() -> ContactNote:
            # Validate contact exists
            await self.contact_validation.validate_contact_exists(
                contact_id, transaction
            )

            # Add note
            saved_note = await self.contact_repo.add_note(contact_id, note)

            # Ensure note has ID after save
            if saved_note.id is None:
                raise ContactValidationError("id", "Note ID is required after save")

            # Record field history (creation doesn't have field changes)
            # Domain event will capture the addition action

            # Publish event
            event = ContactNoteAdded(
                contact_id, saved_note.id, note.content, transaction=transaction
            )
            await self.event_publisher.publish(event)

            return saved_note

        return cast(ContactNote, await self._execute_with_retry(_add_note_operation))

    # Read operations (no transaction management needed)
    async def get_contact_by_id(self, contact_id: int) -> Contact | None:
        """Get a contact by ID."""
        return await self.contact_repo.find_by_id(contact_id)

    async def get_contact_by_email(self, email: str) -> Contact | None:
        """Get a contact by email."""
        return await self.contact_repo.find_by_email(email)

    async def search_contacts(self, query: str, limit: int = 50) -> list[Contact]:
        """Search contacts."""
        return await self.contact_repo.search(query, limit)

    async def get_all_contacts(
        self, limit: int = 100, offset: int = 0
    ) -> list[Contact]:
        """Get all contacts with pagination."""
        return await self.contact_repo.get_all(limit, offset)

    async def get_contacts_paginated(
        self,
        limit: int = 20,
        offset: int = 0,
        is_favourite: bool | None = None,
        tag_ids: list[int] | None = None,
    ) -> list[Contact]:
        """
        Get contacts with pagination and optional filtering.

        Args:
            limit: Maximum number of contacts to return
            offset: Number of contacts to skip
            is_favourite: Filter by favourite status (None for no filter)
            tag_ids: Filter by tag IDs (None for no filter)

        Returns:
            List of contacts matching the filters
        """
        # If no filters are applied, use the existing get_all method
        if is_favourite is None and tag_ids is None:
            return await self.get_all_contacts(limit, offset)

        # Use the filtered method when filters are applied
        return await self.contact_repo.get_contacts_by_filters(
            is_favourite=is_favourite,
            tag_ids=tag_ids,
            limit=limit,
            offset=offset,
        )

    async def get_contacts_count(self) -> int:
        """Get total count of contacts."""
        return await self.contact_repo.get_count()

    async def get_contacts_by_tag(self, tag_id: int) -> list[Contact]:
        """Get contacts by tag."""
        return await self.contact_repo.get_contacts_by_tag(tag_id)

    async def get_contact_history(self, contact_id: int, limit: int = 50) -> list[Any]:
        """Get contact history."""
        return await self.history_service.get_contact_history(contact_id, limit)

    async def toggle_contact_favourite(
        self, contact_id: int, transaction: AsyncConnection
    ) -> Contact:
        """
        Toggle the favourite status of a contact.

        Args:
            contact_id: ID of the contact to toggle
            transaction: Database transaction

        Returns:
            Updated contact with toggled favourite status

        Raises:
            ContactValidationError: If contact not found
        """

        async def _toggle_operation() -> Contact:
            # Find the contact
            contact = await self.contact_repo.find_by_id(contact_id)
            if not contact:
                raise ContactValidationError("id", "Contact not found")

            # Toggle favourite status
            old_favourite = contact.is_favourite
            contact.toggle_favourite()

            # Save the updated contact
            updated_contact = await self.contact_repo.save(contact)

            # Record history and publish event
            changed_fields = {"is_favourite": (old_favourite, contact.is_favourite)}
            await self._publish_contact_updated_events(
                updated_contact, changed_fields, transaction
            )

            return updated_contact

        return cast(Contact, await self._execute_with_retry(_toggle_operation))

    async def get_favourite_contacts(
        self, limit: int = 100, offset: int = 0
    ) -> list[Contact]:
        """
        Get all favourite contacts with pagination.

        Args:
            limit: Maximum number of contacts to return
            offset: Number of contacts to skip

        Returns:
            List of favourite contacts
        """
        return await self.contact_repo.get_favourite_contacts(limit, offset)
