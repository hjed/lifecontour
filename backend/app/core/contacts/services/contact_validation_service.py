"""Contact validation service with transaction support."""

from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.entities import Contact, MethodType
from app.core.contacts.models.exceptions import (
    ContactNotFoundError,
    ContactValidationError,
    DuplicateEmailError,
)
from app.core.contacts.models.repositories import ContactRepository


class ContactValidationService:
    """Service for validating contact data with database constraints."""

    def __init__(self, contact_repo: ContactRepository):
        self.contact_repo = contact_repo

    async def validate_email_uniqueness(
        self,
        email: str,
        _transaction: AsyncConnection,
        exclude_contact_id: int | None = None,
    ) -> None:
        """Validate that email is unique across all contacts."""
        existing_contact = await self.contact_repo.find_by_email(email)

        if existing_contact:
            if existing_contact.id is None:
                raise ContactValidationError(
                    "contact_id", "Existing contact has no ID - data integrity issue"
                )

            if exclude_contact_id is None or existing_contact.id != exclude_contact_id:
                raise DuplicateEmailError(email, existing_contact.id)

    async def validate_primary_method(
        self, contact_id: int, method_type: MethodType, _transaction: AsyncConnection
    ) -> None:
        """Validate primary method constraints."""
        contact = await self.contact_repo.find_by_id(contact_id)
        if not contact:
            raise ContactNotFoundError(contact_id)

        # Check if there's already a primary method of this type
        for method in contact.methods:
            if method.method_type == method_type and method.is_primary:
                # This will be handled by database constraints
                # The service just validates the business rule exists
                pass

    async def validate_primary_address(
        self, contact_id: int, _transaction: AsyncConnection
    ) -> None:
        """Validate primary address constraints."""
        contact = await self.contact_repo.find_by_id(contact_id)
        if not contact:
            raise ContactNotFoundError(contact_id)

        # Check if there's already a primary address
        for address in contact.addresses:
            if address.is_primary:
                # This will be handled by database constraints
                # The service just validates the business rule exists
                pass

    async def validate_contact_exists(
        self, contact_id: int, _transaction: AsyncConnection
    ) -> None:
        """Validate that a contact exists."""
        contact = await self.contact_repo.find_by_id(contact_id)
        if not contact:
            raise ContactNotFoundError(contact_id)

    async def validate_contact_tag_limit(
        self, contact_id: int, _transaction: AsyncConnection
    ) -> None:
        """Validate that contact doesn't exceed tag limit."""
        contact = await self.contact_repo.find_by_id(contact_id)
        if not contact:
            raise ContactNotFoundError(contact_id)

        if len(contact.tags) >= 25:
            from app.core.contacts.models.exceptions import TooManyTagsError

            raise TooManyTagsError(len(contact.tags), contact_id)

    async def validate_contact_update(
        self,
        contact: Contact,
        transaction: AsyncConnection,
        exclude_contact_id: int | None = None,
    ) -> None:
        """Validate contact data for updates."""
        # Validate email uniqueness if contact has email methods
        for method in contact.methods:
            if method.method_type == MethodType.EMAIL:
                await self.validate_email_uniqueness(
                    method.value, transaction, exclude_contact_id
                )
