"""Main contact service with transaction management."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import structlog
from core_shared.models.contacts.entities import (
    Contact,
    ContactAddress,
    ContactMethod,
    ContactNote,
    ImportantDate,
    MethodType,
    Tag,
)
from core_shared.models.contacts.exceptions import ContactValidationError
from core_shared.models.contacts.value_objects import Provenance
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.events import (
    ContactAddressAdded,
    ContactAddressDeleted,
    ContactCreated,
    ContactDeleted,
    ContactMethodAdded,
    ContactMethodDeleted,
    ContactNoteAdded,
    ContactSummaryRefreshRequested,
    ContactUpdated,
    ImportantDateAdded,
    ImportantDateDeleted,
    TagAssigned,
    TagRemoved,
)
from app.core.contacts.models.exceptions import (
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
from app.infrastructure.unit_of_work import unit_of_work

if TYPE_CHECKING:
    from app.core.contacts.services.tag_service import TagService

logger = structlog.get_logger()


def _normalize_field_value(value: Any) -> str | None:
    """Normalize field values for comparison.

    Converts all values to strings for consistent comparison,
    handling booleans and None values appropriately.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value).lower()  # "true" or "false"
    return str(value)


def _validate_contact_field_name(field_name: str) -> None:
    """Validate that the field name is allowed for contact updates."""
    valid_fields = {
        "first_name",
        "last_name",
        "middle_name",
        "nick_name",
        "is_favourite",
    }
    if field_name not in valid_fields:
        raise ContactValidationError(
            "field_name",
            f"Invalid field name '{field_name}'. Valid fields: {', '.join(valid_fields)}",
        )


def _convert_contact_field_value(field_name: str, field_value: Any) -> Any:
    """Convert field value to appropriate type based on field name."""
    if field_name == "is_favourite":
        if isinstance(field_value, str):
            return field_value.lower() in ("true", "1", "yes")
        else:
            return bool(field_value)
    else:
        return str(field_value) if field_value is not None else None


def _validate_method_field_name(field_name: str) -> None:
    """Validate that the field name is allowed for method updates."""
    valid_fields = {"value", "label", "is_primary"}
    if field_name not in valid_fields:
        raise ContactValidationError(
            "field_name",
            f"Invalid method field name '{field_name}'. Valid fields: {', '.join(valid_fields)}",
        )


def _convert_method_field_value(field_name: str, field_value: Any) -> Any:
    """Convert method field value to appropriate type based on field name."""
    if field_name == "is_primary":
        if isinstance(field_value, str):
            return field_value.lower() in ("true", "1", "yes")
        else:
            return bool(field_value)
    else:
        return str(field_value) if field_value is not None else None


def _validate_address_field_name(field_name: str) -> None:
    """Validate that the field name is allowed for address updates."""
    valid_fields = {
        "label",
        "street_line_1",
        "street_line_2",
        "locality",
        "region",
        "postal_code",
        "country_code",
        "is_primary",
    }
    if field_name not in valid_fields:
        raise ContactValidationError(
            "field_name",
            f"Invalid address field name '{field_name}'. Valid fields: {', '.join(valid_fields)}",
        )


def _convert_address_field_value(field_name: str, field_value: Any) -> Any:
    """Convert address field value to appropriate type based on field name."""
    if field_name == "is_primary":
        if isinstance(field_value, str):
            return field_value.lower() in ("true", "1", "yes")
        else:
            return bool(field_value)
    else:
        return str(field_value) if field_value is not None else None


def _validate_note_field_name(field_name: str) -> None:
    """Validate that the field name is allowed for note updates."""
    valid_fields = {"content"}
    if field_name not in valid_fields:
        raise ContactValidationError(
            "field_name",
            f"Invalid note field name '{field_name}'. Valid fields: {', '.join(valid_fields)}",
        )


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
        tag_service: TagService | None = None,
    ):
        self.contact_repo = contact_repo
        self.tag_repo = tag_repo
        self.history_repo = history_repo
        self.event_publisher = event_publisher
        # Optional collaborator used only to resolve tag *names* on create/update
        # (find-or-create). Left None for callers that pass tags by id or never
        # pass tag names (e.g. the event consumer); required when tag_names is used.
        self._tag_service = tag_service

        # Initialize services with dependencies
        self.address_validation = (
            address_validation_service or AddressValidationService()
        )
        self.contact_validation = (
            contact_validation_service or ContactValidationService(contact_repo)
        )
        self.history_service = history_service or ContactHistoryService(history_repo)
        self.tag_hierarchy = tag_hierarchy_service or TagHierarchyService(tag_repo)

    async def _execute_with_retry(
        self, operation: Any, transaction: AsyncConnection
    ) -> Any:
        """Run a write operation as an explicit, committed unit of work.

        Commits the transaction on success (before the response is sent) and
        rolls back on failure. ``unit_of_work`` is re-entrant, so this stays
        correct even when a caller has already opened a unit of work. Unit tests
        pass a mock connection; transaction management is skipped there.
        """
        try:
            if isinstance(transaction, AsyncConnection):
                async with unit_of_work(transaction):
                    return await operation()
            return await operation()
        except IntegrityError as e:
            self._convert_integrity_error_to_domain_exception(e)
            raise

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

    async def _resolve_tag_names(
        self,
        contact: Contact,
        tag_names: list[str],
        transaction: AsyncConnection,
    ) -> None:
        """Resolve tag names to existing-or-new tags and attach them to contact.

        Each name is looked up; a missing name is created via the TagService
        (a race-safe create-or-get), so the tag write is owned by a
        ``@transactional`` service rather than a raw repo call. Runs inside the
        caller's unit of work so tag creation commits atomically with the
        contact. ``add_tag`` handles de-duplication and the per-contact limit.
        """
        if self._tag_service is None:
            raise ContactValidationError(
                "tags",
                "Creating tags by name requires a TagService; none was configured.",
            )
        if contact.tags is None:
            contact.tags = []
        for name in tag_names:
            existing = await self.tag_repo.find_by_name(name)
            tag = (
                existing
                if existing is not None
                else await self._tag_service.create_tag(name, transaction=transaction)
            )
            contact.add_tag(tag)

    async def create_contact(
        self,
        contact: Contact,
        transaction: AsyncConnection,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
        tag_names: list[str] | None = None,
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
            # Resolve any tag names to existing-or-new tags inside this unit of
            # work, so tag creation and the contact write commit together.
            if tag_names:
                await self._resolve_tag_names(contact, tag_names, transaction)

            # Validate and save basic contact fields
            saved_contact = await self._validate_and_save_contact_basic_fields(
                contact, transaction
            )
            # contact_id is guaranteed to be not None after _ensure_contact_has_id
            contact_id = saved_contact.id
            if contact_id is None:
                raise ContactValidationError(
                    "id", "Contact ID is required after save operation"
                )

            # Save all related entities
            saved_entities = await self._save_all_related_entities(
                contact_id, contact, transaction
            )

            # Build complete contact with related entities
            complete_contact = self._build_complete_contact(
                saved_contact, saved_entities
            )

            # Publish creation event
            await self._publish_contact_created_event(
                complete_contact, transaction, changed_by=changed_by, source=source
            )

            return complete_contact

        return cast(
            Contact, await self._execute_with_retry(_create_operation, transaction)
        )

    async def update_contact(
        self,
        contact: Contact,
        transaction: AsyncConnection,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
        tag_names: list[str] | None = None,
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
            if contact.id is None:
                raise ContactValidationError(
                    "id", "Contact ID is required for update operation"
                )

            # Resolve any tag names to existing-or-new tags inside this unit of
            # work (replacement strategy: the resolved set replaces all existing
            # tags). An empty list clears all tags; None leaves tags untouched.
            if tag_names is not None:
                contact.tags = []
                await self._resolve_tag_names(contact, tag_names, transaction)

            # Get current contact and calculate changes
            current_contact = await self._get_existing_contact(contact.id)
            changed_fields = self._calculate_changed_fields(current_contact, contact)

            # Validate and save basic contact fields
            saved_contact = await self._validate_and_save_contact_basic_fields(
                contact, transaction, exclude_contact_id=contact.id
            )
            # contact_id is guaranteed to be not None after _ensure_contact_has_id
            contact_id = saved_contact.id
            if contact_id is None:
                raise ContactValidationError(
                    "id", "Contact ID is required after save operation"
                )

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
                    complete_contact,
                    changed_fields,
                    transaction,
                    changed_by=changed_by,
                    source=source,
                )

            return complete_contact

        return cast(
            Contact, await self._execute_with_retry(_update_operation, transaction)
        )

    async def update_contact_field(
        self,
        contact_id: int,
        field_name: str,
        field_value: Any,
        transaction: AsyncConnection,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
    ) -> tuple[str | None, str | None]:
        """
        Update a single contact field with transaction management.

        This method updates only the specified field of a contact and records
        the change in the contact history. It's optimized for single field updates
        from the frontend inline editing functionality.

        Args:
            contact_id: ID of the contact to update
            field_name: Name of the field to update (first_name, last_name, etc.)
            field_value: New value for the field
            transaction: Database transaction

        Returns:
            Tuple of (old_value, new_value) for the updated field

        Raises:
            ContactValidationError: If contact not found or field name invalid
            ContactNotFoundError: If contact doesn't exist
        """
        # Validate field name
        _validate_contact_field_name(field_name)

        async def _update_field_operation() -> tuple[str | None, str | None]:
            # Get current contact
            current_contact = await self._get_existing_contact(contact_id)

            # Get current field value
            old_value = getattr(current_contact, field_name)

            # Convert field_value to appropriate type
            new_value = _convert_contact_field_value(field_name, field_value)

            # Skip update if value hasn't changed (normalize for comparison)
            if _normalize_field_value(old_value) == _normalize_field_value(new_value):
                return (
                    str(old_value) if old_value is not None else None,
                    str(new_value) if new_value is not None else None,
                )

            # Create updated contact with only the changed field
            updated_contact = Contact(
                id=current_contact.id,
                first_name=current_contact.first_name,
                last_name=current_contact.last_name,
                middle_name=current_contact.middle_name,
                nick_name=current_contact.nick_name,
                is_favourite=current_contact.is_favourite,
                created_at=current_contact.created_at,
                updated_at=current_contact.updated_at,
            )

            # Update the specific field
            setattr(updated_contact, field_name, new_value)

            # Validate the updated contact
            await self.contact_validation.validate_contact_update(
                updated_contact, transaction, exclude_contact_id=contact_id
            )

            # Save the updated contact
            await self.contact_repo.save(updated_contact)

            # Record field history
            changed_fields = {field_name: (old_value, new_value)}
            await self.history_service.record_contact_change(
                contact_id,
                changed_fields,
                changed_by=changed_by,
                source=source,
                _transaction=transaction,
            )

            # Publish update event
            event = ContactUpdated(contact_id, changed_fields, transaction=transaction)
            await self.event_publisher.publish(event)

            return (
                str(old_value) if old_value is not None else None,
                str(new_value) if new_value is not None else None,
            )

        return cast(
            tuple[str | None, str | None],
            await self._execute_with_retry(_update_field_operation, transaction),
        )

    async def update_contact_method_field(
        self,
        contact_id: int,
        method_id: int,
        field_name: str,
        field_value: Any,
        transaction: AsyncConnection,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
    ) -> tuple[str | None, str | None]:
        """
        Update a single contact method field.

        Args:
            contact_id: ID of the contact
            method_id: ID of the contact method to update
            field_name: Name of the field to update (value, label, is_primary)
            field_value: New value for the field
            transaction: Database transaction

        Returns:
            Tuple of (old_value, new_value) for the updated field

        Raises:
            ContactValidationError: If method not found or field name invalid
        """
        # Validate field name
        _validate_method_field_name(field_name)

        async def _update_method_field_operation() -> tuple[str | None, str | None]:
            # Get current contact with methods
            current_contact = await self._get_existing_contact(contact_id)

            # Find the method to update
            method_to_update = None
            for method in current_contact.methods or []:
                if method.id == method_id:
                    method_to_update = method
                    break

            if not method_to_update:
                raise ContactValidationError(
                    "method_id", f"Method with ID {method_id} not found"
                )

            # Get current field value
            old_value = getattr(method_to_update, field_name)

            # Convert field_value to appropriate type
            new_value = _convert_method_field_value(field_name, field_value)

            # Skip update if value hasn't changed (normalize for comparison)
            if _normalize_field_value(old_value) == _normalize_field_value(new_value):
                return (
                    str(old_value) if old_value is not None else None,
                    str(new_value) if new_value is not None else None,
                )

            # Update the method field
            setattr(method_to_update, field_name, new_value)

            # Validate the updated method
            if field_name == "value":
                # Re-validate the method with new value
                method_to_update.__post_init__()

            # Save the updated method
            await self.contact_repo.update_method(method_to_update)

            # Record history
            changed_fields = {field_name: (old_value, new_value)}
            await self.history_service.record_method_change(
                method_id,
                changed_fields,
                changed_by=changed_by,
                source=source,
                _transaction=transaction,
            )

            # Publish update event (method-specific event could be added)
            event = ContactUpdated(
                contact_id,
                {f"method_{method_id}_{field_name}": (old_value, new_value)},
                transaction=transaction,
            )
            await self.event_publisher.publish(event)
            await self.contact_repo.touch(contact_id, transaction)

            return (
                str(old_value) if old_value is not None else None,
                str(new_value) if new_value is not None else None,
            )

        return cast(
            tuple[str | None, str | None],
            await self._execute_with_retry(_update_method_field_operation, transaction),
        )

    async def update_contact_address_field(
        self,
        contact_id: int,
        address_id: int,
        field_name: str,
        field_value: Any,
        transaction: AsyncConnection,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
    ) -> tuple[str | None, str | None]:
        """
        Update a single contact address field.

        Args:
            contact_id: ID of the contact
            address_id: ID of the contact address to update
            field_name: Name of the field to update
            field_value: New value for the field
            transaction: Database transaction

        Returns:
            Tuple of (old_value, new_value) for the updated field
        """
        # Validate field name
        _validate_address_field_name(field_name)

        async def _update_address_field_operation() -> tuple[str | None, str | None]:
            # Get current contact with addresses
            current_contact = await self._get_existing_contact(contact_id)

            # Find the address to update
            address_to_update = None
            for address in current_contact.addresses or []:
                if address.id == address_id:
                    address_to_update = address
                    break

            if not address_to_update:
                raise ContactValidationError(
                    "address_id", f"Address with ID {address_id} not found"
                )

            # Get current field value
            old_value = getattr(address_to_update, field_name)

            # Convert field_value to appropriate type
            new_value = _convert_address_field_value(field_name, field_value)

            # Skip update if value hasn't changed (normalize for comparison)
            if _normalize_field_value(old_value) == _normalize_field_value(new_value):
                return (
                    str(old_value) if old_value is not None else None,
                    str(new_value) if new_value is not None else None,
                )

            # Update the address field
            setattr(address_to_update, field_name, new_value)

            # Validate the updated address
            address_to_update.__post_init__()

            # Save the updated address
            await self.contact_repo.update_address(address_to_update)

            # Record history
            changed_fields = {field_name: (old_value, new_value)}
            await self.history_service.record_address_change(
                address_id,
                changed_fields,
                changed_by=changed_by,
                source=source,
                _transaction=transaction,
            )

            # Publish update event
            event = ContactUpdated(
                contact_id,
                {f"address_{address_id}_{field_name}": (old_value, new_value)},
                transaction=transaction,
            )
            await self.event_publisher.publish(event)
            await self.contact_repo.touch(contact_id, transaction)

            return (
                str(old_value) if old_value is not None else None,
                str(new_value) if new_value is not None else None,
            )

        return cast(
            tuple[str | None, str | None],
            await self._execute_with_retry(
                _update_address_field_operation, transaction
            ),
        )

    async def update_contact_note_field(
        self,
        contact_id: int,
        note_id: int,
        field_name: str,
        field_value: Any,
        transaction: AsyncConnection,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
    ) -> tuple[str | None, str | None]:
        """
        Update a single contact note field.

        Args:
            contact_id: ID of the contact
            note_id: ID of the contact note to update
            field_name: Name of the field to update (content)
            field_value: New value for the field
            transaction: Database transaction

        Returns:
            Tuple of (old_value, new_value) for the updated field
        """
        # Validate field name
        _validate_note_field_name(field_name)

        async def _update_note_field_operation() -> tuple[str | None, str | None]:
            # Get current contact with notes
            current_contact = await self._get_existing_contact(contact_id)

            # Find the note to update
            note_to_update = None
            for note in current_contact.notes or []:
                if note.id == note_id:
                    note_to_update = note
                    break

            if not note_to_update:
                raise ContactValidationError(
                    "note_id", f"Note with ID {note_id} not found"
                )

            # Get current field value
            old_value = getattr(note_to_update, field_name)
            new_value = str(field_value) if field_value is not None else None

            # Skip update if value hasn't changed (normalize for comparison)
            if _normalize_field_value(old_value) == _normalize_field_value(new_value):
                return (
                    str(old_value) if old_value is not None else None,
                    str(new_value) if new_value is not None else None,
                )

            # Update the note field
            setattr(note_to_update, field_name, new_value)

            # Validate the updated note
            note_to_update.__post_init__()

            # Save the updated note
            await self.contact_repo.update_note(note_to_update)

            # Record history
            changed_fields = {field_name: (old_value, new_value)}
            await self.history_service.record_note_change(
                note_id,
                changed_fields,
                changed_by=changed_by,
                source=source,
                _transaction=transaction,
            )

            # Publish update event
            event = ContactUpdated(
                contact_id,
                {f"note_{note_id}_{field_name}": (old_value, new_value)},
                transaction=transaction,
            )
            await self.event_publisher.publish(event)
            await self.contact_repo.touch(contact_id, transaction)

            return (
                str(old_value) if old_value is not None else None,
                str(new_value) if new_value is not None else None,
            )

        return cast(
            tuple[str | None, str | None],
            await self._execute_with_retry(_update_note_field_operation, transaction),
        )

    def _calculate_changed_fields(
        self, current_contact: Contact, updated_contact: Contact
    ) -> dict[str, Any]:
        """Calculate which fields have changed between current and updated contact."""
        changed_fields: dict[str, Any] = {}

        def _add_if_changed(
            field: str, current: str | None, updated: str | None
        ) -> None:
            if current != updated:
                changed_fields[field] = (current, updated)

        # Check basic contact fields
        _add_if_changed(
            "first_name", current_contact.first_name, updated_contact.first_name
        )
        _add_if_changed(
            "last_name", current_contact.last_name, updated_contact.last_name
        )
        _add_if_changed(
            "middle_name", current_contact.middle_name, updated_contact.middle_name
        )
        _add_if_changed(
            "nick_name", current_contact.nick_name, updated_contact.nick_name
        )

        # Check method changes
        if updated_contact.methods is not None:
            current_method_strs = sorted(
                [
                    f"{m.method_type.value}:{m.value}"
                    for m in (current_contact.methods or [])
                    if m.method_type and m.value
                ]
            )
            updated_method_strs = sorted(
                [
                    f"{m.method_type.value}:{m.value}"
                    for m in updated_contact.methods
                    if m.method_type and m.value
                ]
            )

            if current_method_strs != updated_method_strs:
                changed_fields["contact_methods"] = (
                    ", ".join(current_method_strs) if current_method_strs else "None",
                    ", ".join(updated_method_strs) if updated_method_strs else "None",
                )

        # Check address changes
        if updated_contact.addresses is not None:

            def _format_address(a: ContactAddress) -> str:
                parts = [
                    a.street_line_1,
                    a.street_line_2,
                    a.locality,
                    a.region,
                    a.postal_code,
                    a.country_code,
                ]
                return ", ".join(str(p) for p in parts if p) or "Unknown Address"

            current_addr_strs = sorted(
                [_format_address(a) for a in (current_contact.addresses or [])]
            )
            updated_addr_strs = sorted(
                [_format_address(a) for a in updated_contact.addresses]
            )

            if current_addr_strs != updated_addr_strs:
                changed_fields["addresses"] = (
                    " | ".join(current_addr_strs) if current_addr_strs else "None",
                    " | ".join(updated_addr_strs) if updated_addr_strs else "None",
                )

        if updated_contact.notes is not None and len(
            current_contact.notes or []
        ) != len(updated_contact.notes):
            changed_fields["notes"] = (
                f"count:{len(current_contact.notes or [])}",
                f"count:{len(updated_contact.notes)}",
            )

        if updated_contact.important_dates is not None and len(
            current_contact.important_dates or []
        ) != len(updated_contact.important_dates):
            changed_fields["important_dates"] = (
                f"count:{len(current_contact.important_dates or [])}",
                f"count:{len(updated_contact.important_dates)}",
            )

        # Check tag changes
        if updated_contact.tags is not None:

            def _format_tag(t: Tag) -> str:
                if t.name:
                    return str(t.name)
                return f"id:{t.id}" if t.id is not None else "Unknown Tag"

            current_tags = sorted(
                [_format_tag(tag) for tag in (current_contact.tags or [])]
            )
            updated_tags = sorted([_format_tag(tag) for tag in updated_contact.tags])

            if current_tags != updated_tags:
                changed_fields["tags"] = (
                    ", ".join(current_tags) if current_tags else "None",
                    ", ".join(updated_tags) if updated_tags else "None",
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
        saved_dates = await self._save_contact_important_dates(
            contact_id, contact.important_dates, transaction
        )

        return {
            "methods": saved_methods,
            "addresses": saved_addresses,
            "notes": saved_notes,
            "tags": saved_tags,
            "important_dates": saved_dates,
        }

    def _build_complete_contact(
        self, saved_contact: Contact, saved_entities: dict[str, list[Any]]
    ) -> Contact:
        """Build complete contact with all related entities."""
        saved_contact.methods = saved_entities["methods"]
        saved_contact.addresses = saved_entities["addresses"]
        saved_contact.notes = saved_entities["notes"]
        saved_contact.tags = saved_entities["tags"]
        saved_contact.important_dates = saved_entities["important_dates"]
        return saved_contact

    async def _publish_contact_created_event(
        self,
        contact: Contact,
        transaction: AsyncConnection,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
    ) -> None:
        """Publish contact created event.

        Args:
            contact: The created contact
            transaction: Database transaction
            changed_by: Provenance identifier (e.g. "google_sync").
            source: Strongly typed provenance.
        """
        if contact.id is None:
            raise ContactValidationError(
                "id", "Contact ID is required for event publishing"
            )
        await self.history_service.record_contact_change(
            contact.id,
            {"status": (None, "created")},
            changed_by=changed_by,
            source=source,
            _transaction=transaction,
        )
        for method in contact.methods or []:
            if method.id is not None:
                await self.history_service.record_method_change(
                    method.id,
                    {"status": (None, "created")},
                    changed_by=changed_by,
                    source=source,
                    _transaction=transaction,
                )
        for address in contact.addresses or []:
            if address.id is not None:
                await self.history_service.record_address_change(
                    address.id,
                    {"status": (None, "created")},
                    changed_by=changed_by,
                    source=source,
                    _transaction=transaction,
                )
        for note in contact.notes or []:
            if note.id is not None:
                await self.history_service.record_note_change(
                    note.id,
                    {"status": (None, "created")},
                    changed_by=changed_by,
                    source=source,
                    _transaction=transaction,
                )
        for date in contact.important_dates or []:
            if date.id is not None:
                await self.history_service.record_important_date_change(
                    date.id,
                    {"status": (None, "created")},
                    changed_by=changed_by,
                    source=source,
                    _transaction=transaction,
                )

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

        if contact.methods is not None:
            saved_entities["methods"] = await self._save_contact_methods(
                contact_id, contact.methods, transaction
            )

        if contact.addresses is not None:
            saved_entities["addresses"] = await self._save_contact_addresses(
                contact_id, contact.addresses, transaction
            )

        if contact.notes is not None:
            saved_entities["notes"] = await self._save_contact_notes(
                contact_id, contact.notes, transaction
            )

        if contact.tags is not None:
            saved_entities["tags"] = await self._save_contact_tags(
                contact_id, contact.tags, transaction
            )

        if contact.important_dates is not None:
            saved_entities[
                "important_dates"
            ] = await self._save_contact_important_dates(
                contact_id, contact.important_dates, transaction
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
            saved_entities["methods"]
            if contact.methods is not None
            else current_contact.methods
        )
        saved_contact.addresses = (
            saved_entities["addresses"]
            if contact.addresses is not None
            else current_contact.addresses
        )
        saved_contact.notes = (
            saved_entities["notes"]
            if contact.notes is not None
            else current_contact.notes
        )
        saved_contact.tags = (
            saved_entities["tags"] if contact.tags is not None else current_contact.tags
        )
        saved_contact.important_dates = (
            saved_entities["important_dates"]
            if contact.important_dates is not None
            else current_contact.important_dates
        )
        return saved_contact

    async def _publish_contact_updated_events(
        self,
        contact: Contact,
        changed_fields: dict[str, Any],
        transaction: AsyncConnection,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
    ) -> None:
        """Publish contact updated events and record history."""
        if contact.id is None:
            raise ContactValidationError(
                "id", "Contact ID is required for event publishing"
            )
        await self.history_service.record_contact_change(
            contact.id,
            changed_fields,
            changed_by=changed_by,
            source=source,
            _transaction=transaction,
        )

        event = ContactUpdated(contact.id, changed_fields, transaction=transaction)
        await self.event_publisher.publish(event)

        # Trigger async summary regeneration via outbox
        summary_event = ContactSummaryRefreshRequested(
            contact.id, transaction=transaction
        )
        await self.event_publisher.publish(summary_event)

    async def _validate_contact_data(
        self,
        contact: Contact,
        transaction: AsyncConnection,
        exclude_contact_id: int | None = None,
    ) -> None:
        """Validate contact data including methods and addresses."""
        # Validate email uniqueness if contact has email methods
        if contact.methods:
            for method in contact.methods:
                if method.method_type == MethodType.EMAIL:
                    await self.contact_validation.validate_email_uniqueness(
                        method.value, transaction, exclude_contact_id=exclude_contact_id
                    )

        # Validate addresses
        if contact.addresses:
            for address in contact.addresses:
                await self.address_validation.validate_with_transaction(
                    address, transaction
                )

    async def _save_contact_methods(
        self,
        contact_id: int,
        methods: list[ContactMethod] | None,
        transaction: AsyncConnection,
    ) -> list[ContactMethod]:
        """Save contact methods and publish events."""
        saved_methods = []
        if methods is None:
            methods = []
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
        addresses: list[ContactAddress] | None,
        transaction: AsyncConnection,
    ) -> list[ContactAddress]:
        """Save contact addresses and publish events."""
        saved_addresses = []
        if addresses is None:
            addresses = []
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
        self,
        contact_id: int,
        notes: list[ContactNote] | None,
        transaction: AsyncConnection,
    ) -> list[ContactNote]:
        """Save contact notes and publish events."""
        saved_notes = []
        if notes is None:
            notes = []
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
        self, contact_id: int, tags: list[Tag] | None, transaction: AsyncConnection
    ) -> list[Tag]:
        """Save contact tags and publish events."""
        saved_tags = []
        if tags is None:
            tags = []
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

    async def _save_contact_important_dates(
        self,
        contact_id: int,
        dates: list[ImportantDate] | None,
        transaction: AsyncConnection,
    ) -> list[ImportantDate]:
        """Save contact important dates and publish events."""
        saved_dates = []
        if dates is None:
            dates = []
        for date in dates:
            # Update contact_id
            date.contact_id = contact_id

            saved_date = await self.contact_repo.add_important_date(contact_id, date)
            saved_dates.append(saved_date)

            # Ensure date has ID after save
            if saved_date.id is None:
                raise ContactValidationError("id", "Date ID is required after save")

            # Publish date added event
            date_event = ImportantDateAdded(
                contact_id, saved_date.id, date.date_type.value, transaction=transaction
            )
            await self.event_publisher.publish(date_event)

        return saved_dates

    async def _remove_existing_relations(
        self, contact_id: int, contact: Contact, current_contact: Contact
    ) -> None:
        """Remove existing relations when updating contact."""
        # Only replace methods if new methods are provided
        if contact.methods is not None:
            await self.contact_repo.delete_all_methods(contact_id)

        # Only replace addresses if new addresses are provided
        if contact.addresses is not None:
            await self.contact_repo.delete_all_addresses(contact_id)

        # Only replace notes if new notes are provided
        if contact.notes is not None:
            await self.contact_repo.delete_all_notes(contact_id)

        # Only replace tags if new tags are provided
        if contact.tags is not None:
            # Remove all existing tags first
            for current_tag in current_contact.tags or []:
                if current_tag.id is not None:
                    await self.contact_repo.remove_tag(contact_id, current_tag.id)

        # Only replace dates if new dates are provided
        if contact.important_dates is not None:
            await self.contact_repo.delete_all_important_dates(contact_id)

    async def delete_contact(
        self,
        contact_id: int,
        transaction: AsyncConnection,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
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
            await self.history_service.record_contact_change(
                contact_id,
                {"status": ("active", "deleted")},
                changed_by=changed_by,
                source=source,
                _transaction=transaction,
            )
            # Domain event will capture the deletion action

            # Publish event
            event = ContactDeleted(contact_id, transaction=transaction)
            await self.event_publisher.publish(event)

        return cast(
            None, await self._execute_with_retry(_delete_operation, transaction)
        )

    async def bulk_delete_all_contacts(self, transaction: AsyncConnection) -> None:
        """
        Bulk delete all contacts for test cleanup.

        This method is designed for test environments to efficiently clean up
        all contacts without the overhead of individual validation and event
        publishing. It performs a direct bulk delete operation.

        WARNING: This will delete ALL contacts. Only use in test environments.
        """
        # Use the provided transaction for the bulk delete. This bypasses
        # _execute_with_retry, so commit explicitly via the unit of work.
        if isinstance(transaction, AsyncConnection):
            async with unit_of_work(transaction):
                await self.contact_repo.bulk_delete_all(transaction)
        else:
            await self.contact_repo.bulk_delete_all(transaction)

    async def assign_tag_to_contact(
        self,
        contact_id: int,
        tag_id: int,
        transaction: AsyncConnection,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
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
                contact_id,
                tag_id,
                str(tag.name),
                "assigned",
                changed_by=changed_by,
                source=source,
                _transaction=transaction,
            )

            # Publish event
            event = TagAssigned(
                contact_id, tag_id, str(tag.name), transaction=transaction
            )
            await self.event_publisher.publish(event)
            await self.contact_repo.touch(contact_id, transaction)

        return cast(
            None, await self._execute_with_retry(_assign_operation, transaction)
        )

    async def remove_tag_from_contact(
        self,
        contact_id: int,
        tag_id: int,
        transaction: AsyncConnection,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
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
                contact_id,
                tag_id,
                str(tag.name),
                "removed",
                changed_by=changed_by,
                source=source,
                _transaction=transaction,
            )

            # Publish event
            event = TagRemoved(
                contact_id, tag_id, str(tag.name), transaction=transaction
            )
            await self.event_publisher.publish(event)
            await self.contact_repo.touch(contact_id, transaction)

        return cast(
            None, await self._execute_with_retry(_remove_operation, transaction)
        )

    async def add_contact_method(
        self,
        contact_id: int,
        method: ContactMethod,
        transaction: AsyncConnection,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
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

            # Record field history
            await self.history_service.record_method_change(
                saved_method.id,
                {"status": (None, "created")},
                changed_by=changed_by,
                source=source,
                _transaction=transaction,
            )

            # Publish event
            event = ContactMethodAdded(
                contact_id,
                saved_method.id,
                method.method_type.value,
                method.value,
                transaction=transaction,
            )
            await self.event_publisher.publish(event)
            await self.contact_repo.touch(contact_id, transaction)

            return saved_method

        return cast(
            ContactMethod,
            await self._execute_with_retry(_add_method_operation, transaction),
        )

    async def add_contact_address(
        self,
        contact_id: int,
        address: ContactAddress,
        transaction: AsyncConnection,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
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

            # Record field history
            await self.history_service.record_address_change(
                saved_address.id,
                {"status": (None, "created")},
                changed_by=changed_by,
                source=source,
                _transaction=transaction,
            )

            # Publish event
            event = ContactAddressAdded(
                contact_id,
                saved_address.id,
                address.street_line_1,
                address.country_code,
                transaction=transaction,
            )
            await self.event_publisher.publish(event)
            await self.contact_repo.touch(contact_id, transaction)

            return saved_address

        return cast(
            ContactAddress,
            await self._execute_with_retry(_add_address_operation, transaction),
        )

    async def add_contact_note(
        self,
        contact_id: int,
        note: ContactNote,
        transaction: AsyncConnection,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
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

            # Record field history
            await self.history_service.record_note_change(
                saved_note.id,
                {"status": (None, "created")},
                changed_by=changed_by,
                source=source,
                _transaction=transaction,
            )

            # Publish event
            event = ContactNoteAdded(
                contact_id, saved_note.id, note.content, transaction=transaction
            )
            await self.event_publisher.publish(event)
            await self.contact_repo.touch(contact_id, transaction)

            return saved_note

        return cast(
            ContactNote,
            await self._execute_with_retry(_add_note_operation, transaction),
        )

    async def add_contact_important_date(
        self,
        contact_id: int,
        date: ImportantDate,
        transaction: AsyncConnection,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
    ) -> ImportantDate:
        """
        Add an important date to an EXISTING contact with transaction management.
        """

        async def _add_date_operation() -> ImportantDate:
            # Validate contact exists
            await self.contact_validation.validate_contact_exists(
                contact_id, transaction
            )

            # Ensure type constraints are satisfied by running python validation
            date.__post_init__()

            # Add date
            saved_date = await self.contact_repo.add_important_date(contact_id, date)

            # Ensure ID
            if saved_date.id is None:
                raise ContactValidationError("id", "Date ID required after save")

            # Record field history
            await self.history_service.record_important_date_change(
                saved_date.id,
                {"status": (None, "created")},
                changed_by=changed_by,
                source=source,
                _transaction=transaction,
            )

            # Publish event
            event = ImportantDateAdded(
                contact_id, saved_date.id, date.date_type.value, transaction=transaction
            )
            await self.event_publisher.publish(event)
            await self.contact_repo.touch(contact_id, transaction)

            return saved_date

        return cast(
            ImportantDate,
            await self._execute_with_retry(_add_date_operation, transaction),
        )

    async def delete_contact_method(
        self,
        contact_id: int,
        method_id: int,
        transaction: AsyncConnection,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
    ) -> None:
        """
        Delete a contact method with transaction management.

        Args:
            contact_id: ID of the contact that owns the method
            method_id: ID of the method to delete
            transaction: Database transaction

        Raises:
            ContactValidationError: If contact or method doesn't exist
        """

        async def _delete_method_operation() -> None:
            # Validate contact exists
            await self.contact_validation.validate_contact_exists(
                contact_id, transaction
            )

            # Get the method to validate it exists and belongs to the contact
            method = await self.contact_repo.find_method_by_id(method_id)
            if not method or method.contact_id != contact_id:
                raise ContactValidationError("method_id", "Method not found")

            # Delete method
            await self.contact_repo.delete_method(method_id)

            # Record history
            await self.history_service.record_method_change(
                method_id,
                {"status": ("active", "deleted")},
                changed_by=changed_by,
                source=source,
                _transaction=transaction,
            )

            # Publish event
            event = ContactMethodDeleted(
                contact_id,
                method_id,
                method.method_type.value,
                method.value,
                transaction=transaction,
            )
            await self.event_publisher.publish(event)
            await self.contact_repo.touch(contact_id, transaction)

        return cast(
            None, await self._execute_with_retry(_delete_method_operation, transaction)
        )

    async def delete_contact_address(
        self,
        contact_id: int,
        address_id: int,
        transaction: AsyncConnection,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
    ) -> None:
        """
        Delete a contact address with transaction management.

        Args:
            contact_id: ID of the contact that owns the address
            address_id: ID of the address to delete
            transaction: Database transaction

        Raises:
            ContactValidationError: If contact or address doesn't exist
        """

        async def _delete_address_operation() -> None:
            # Validate contact exists
            await self.contact_validation.validate_contact_exists(
                contact_id, transaction
            )

            # Get the address to validate it exists and belongs to the contact
            address = await self.contact_repo.find_address_by_id(address_id)
            if not address or address.contact_id != contact_id:
                raise ContactValidationError("address_id", "Address not found")

            # Delete address
            await self.contact_repo.delete_address(address_id)

            # Record history
            await self.history_service.record_address_change(
                address_id,
                {"status": ("active", "deleted")},
                changed_by=changed_by,
                source=source,
                _transaction=transaction,
            )

            # Publish event
            event = ContactAddressDeleted(
                contact_id, address_id, address.street_line_1, transaction=transaction
            )
            await self.event_publisher.publish(event)
            await self.contact_repo.touch(contact_id, transaction)

        return cast(
            None, await self._execute_with_retry(_delete_address_operation, transaction)
        )

    async def delete_contact_important_date(
        self,
        contact_id: int,
        date_id: int,
        transaction: AsyncConnection,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
    ) -> None:
        """
        Delete an important date with transaction management.
        """

        async def _delete_date_operation() -> None:
            # Validate contact exists
            await self.contact_validation.validate_contact_exists(
                contact_id, transaction
            )

            # Get the date to validate it exists and belongs to the contact
            dates = await self.contact_repo.get_important_dates(contact_id)
            date = next((d for d in dates if d.id == date_id), None)
            if not date:
                raise ContactValidationError("date_id", "Date not found")

            # Delete date
            await self.contact_repo.delete_important_date(date_id)

            # Record history
            await self.history_service.record_important_date_change(
                date_id,
                {"status": ("active", "deleted")},
                changed_by=changed_by,
                source=source,
                _transaction=transaction,
            )

            # Publish event
            event = ImportantDateDeleted(
                contact_id, date_id, date.date_type.value, transaction=transaction
            )
            await self.event_publisher.publish(event)
            await self.contact_repo.touch(contact_id, transaction)

        return cast(
            None, await self._execute_with_retry(_delete_date_operation, transaction)
        )

    # Read operations (no transaction management needed)
    async def get_contact_by_id(self, contact_id: int) -> Contact | None:
        """Get a contact by ID."""
        return await self.contact_repo.find_by_id(contact_id)

    async def get_contact_by_email(self, email: str) -> Contact | None:
        """Get a contact by email."""
        return await self.contact_repo.find_by_email(email)

    async def find_contact_by_external_reference(
        self,
        integration_source: str,
        external_id: str,
        transaction: AsyncConnection,
    ) -> Contact | None:
        """
        Find a contact by external reference.

        Args:
            integration_source: Name of the integration source (e.g., 'google')
            external_id: External system's ID for the contact
            transaction: Database transaction (for consistency)

        Returns:
            Contact if found, None otherwise
        """
        return await self.contact_repo.find_by_external_reference(
            external_system=integration_source, external_entity_id=external_id
        )

    async def search_contacts(self, query: str, limit: int = 50) -> list[Contact]:
        """Search contacts."""
        return await self.contact_repo.search(query, limit)

    async def get_all_contacts(
        self, limit: int = 100, offset: int = 0
    ) -> list[Contact]:
        """Get all contacts with pagination."""
        return await self.contact_repo.get_all(limit, offset)

    async def _expand_tag_ids_with_descendants(self, tag_ids: list[int]) -> list[int]:
        """Expand tag IDs to include all descendant tag IDs.

        For each tag ID, fetches all descendant tags and includes their IDs.
        This enables hierarchical filtering: filtering by a parent tag
        automatically includes contacts tagged with any descendant tag.

        Args:
            tag_ids: Original list of tag IDs

        Returns:
            Expanded list including original IDs plus all descendant IDs
        """
        if not tag_ids:
            return []

        expanded: set[int] = set(tag_ids)
        descendants = await self.tag_hierarchy.get_all_descendants_bulk(tag_ids)
        for descendant in descendants:
            if descendant.id is not None:
                expanded.add(descendant.id)

        return sorted(expanded)

    async def get_contacts_paginated(
        self,
        limit: int = 20,
        offset: int = 0,
        is_favourite: bool | None = None,
        tag_ids: list[int] | None = None,
    ) -> list[Contact]:
        """
        Get contacts with pagination and optional filtering.

        When tag_ids are provided, each tag is automatically expanded to
        include all its descendant tags, enabling hierarchical filtering.

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

        # Expand tag_ids to include descendants for hierarchical filtering
        expanded_tag_ids = (
            await self._expand_tag_ids_with_descendants(tag_ids)
            if tag_ids is not None
            else None
        )

        # Use the filtered method when filters are applied
        return await self.contact_repo.get_contacts_by_filters(
            is_favourite=is_favourite,
            tag_ids=expanded_tag_ids,
            limit=limit,
            offset=offset,
        )

    async def get_contacts_count(
        self,
        is_favourite: bool | None = None,
        tag_ids: list[int] | None = None,
    ) -> int:
        """Get total count of contacts with optional filtering.

        When tag_ids are provided, each tag is automatically expanded to
        include all its descendant tags.
        """
        if is_favourite is None and tag_ids is None:
            return await self.contact_repo.get_count()

        # Expand tag_ids to include descendants for hierarchical filtering
        expanded_tag_ids = (
            await self._expand_tag_ids_with_descendants(tag_ids)
            if tag_ids is not None
            else None
        )

        return await self.contact_repo.get_contacts_count_by_filters(
            is_favourite=is_favourite,
            tag_ids=expanded_tag_ids,
        )

    async def get_contacts_by_tag(self, tag_id: int) -> list[Contact]:
        """Get contacts by tag."""
        return await self.contact_repo.get_contacts_by_tag(tag_id)

    async def get_contact_history(self, contact_id: int, limit: int = 50) -> list[Any]:
        """Get contact history."""
        return await self.history_service.get_contact_history(contact_id, limit)

    async def toggle_contact_favourite(
        self,
        contact_id: int,
        transaction: AsyncConnection,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
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
                updated_contact,
                changed_fields,
                transaction,
                changed_by=changed_by,
                source=source,
            )

            return updated_contact

        return cast(
            Contact, await self._execute_with_retry(_toggle_operation, transaction)
        )

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
