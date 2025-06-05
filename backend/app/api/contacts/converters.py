"""
Converters for transforming domain entities to API resources.

Handles the conversion between domain models and JSON API resources,
ensuring proper separation between domain and API layers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.api.common.schemas import JsonApiLinks

if TYPE_CHECKING:
    from app.api.contacts.schemas import ContactCreateData, ContactUpdateData
from app.api.contacts.schemas import (
    ContactAddressAttributes,
    ContactAddressResource,
    ContactAttributes,
    ContactMethodAttributes,
    ContactMethodResource,
    ContactNoteAttributes,
    ContactNoteResource,
    ContactRelationships,
    ContactResource,
    TagAttributes,
    TagResource,
)
from app.core.contacts.models.entities import (
    Contact,
    ContactAddress,
    ContactMethod,
    ContactNote,
    Tag,
)


class ContactConverter:
    """Converter for Contact domain entities to API resources."""

    @staticmethod
    def to_method_resource(method: ContactMethod) -> ContactMethodResource:
        """Convert ContactMethod domain entity to API resource."""
        return ContactMethodResource(
            id=method.id,
            attributes=ContactMethodAttributes(
                method_type=method.method_type.value,
                value=method.value,
                label=method.label,
                is_primary=method.is_primary,
            ),
        )

    @staticmethod
    def to_address_resource(address: ContactAddress) -> ContactAddressResource:
        """Convert ContactAddress domain entity to API resource."""
        return ContactAddressResource(
            id=address.id,
            attributes=ContactAddressAttributes(
                label=address.label,
                street_line_1=address.street_line_1,
                street_line_2=address.street_line_2,
                locality=address.locality,
                region=address.region,
                postal_code=address.postal_code,
                country_code=address.country_code,
                is_primary=address.is_primary,
            ),
        )

    @staticmethod
    def to_note_resource(note: ContactNote) -> ContactNoteResource:
        """Convert ContactNote domain entity to API resource."""
        return ContactNoteResource(
            id=note.id,
            attributes=ContactNoteAttributes(
                content=note.content,
                created_at=note.created_at,
                updated_at=note.updated_at,
            ),
        )

    @staticmethod
    def to_resource(contact: Contact, base_url: str = "") -> ContactResource:
        """Convert Contact domain entity to API resource."""
        # Convert embedded entities
        contact_methods = [
            ContactConverter.to_method_resource(method) for method in contact.methods
        ]
        addresses = [
            ContactConverter.to_address_resource(address)
            for address in contact.addresses
        ]
        notes = [ContactConverter.to_note_resource(note) for note in contact.notes]

        # Create attributes
        attributes = ContactAttributes(
            first_name=contact.first_name,
            last_name=contact.last_name,
            middle_name=contact.middle_name,
            nick_name=contact.nick_name,
            created_at=contact.created_at,
            updated_at=contact.updated_at,
            contact_methods=contact_methods,
            addresses=addresses,
            notes=notes,
        )

        # Create relationships (tags will be handled separately)
        relationships = None
        if contact.tags:
            relationships = ContactRelationships(
                tags={
                    "data": [
                        {"type": "tags", "id": str(tag.id)}
                        for tag in contact.tags
                        if tag.id
                    ]
                }
            )

        # Create links
        links = None
        if base_url and contact.id:
            links = JsonApiLinks(
                self=f"{base_url}/api/contacts/{contact.id}",
            )

        return ContactResource(
            id=str(contact.id) if contact.id else "0",
            attributes=attributes,
            relationships=relationships,
            links=links,
        )


class TagConverter:
    """Converter for Tag domain entities to API resources."""

    @staticmethod
    def to_resource(tag: Tag, base_url: str = "") -> TagResource:
        """Convert Tag domain entity to API resource."""
        attributes = TagAttributes(
            name=tag.name.value,
            color=tag.color,
            description=tag.description,
        )

        # Create links
        links = None
        if base_url and tag.id:
            links = JsonApiLinks(
                self=f"{base_url}/api/tags/{tag.id}",
            )

        return TagResource(
            id=str(tag.id) if tag.id else "0",
            attributes=attributes,
            links=links,
        )


class ContactRequestConverter:
    """Converter for API requests to domain entities."""

    @staticmethod
    def from_method_resource(
        method_resource: ContactMethodResource, contact_id: int
    ) -> ContactMethod:
        """Convert API method resource to domain entity."""
        from app.core.contacts.models.entities import MethodType

        return ContactMethod(
            id=method_resource.id,
            contact_id=contact_id,
            method_type=MethodType(method_resource.attributes.method_type),
            value=method_resource.attributes.value,
            label=method_resource.attributes.label,
            is_primary=method_resource.attributes.is_primary,
        )

    @staticmethod
    def from_address_resource(
        address_resource: ContactAddressResource, contact_id: int
    ) -> ContactAddress:
        """Convert API address resource to domain entity."""
        return ContactAddress(
            id=address_resource.id,
            contact_id=contact_id,
            label=address_resource.attributes.label,
            street_line_1=address_resource.attributes.street_line_1,
            street_line_2=address_resource.attributes.street_line_2,
            locality=address_resource.attributes.locality,
            region=address_resource.attributes.region,
            postal_code=address_resource.attributes.postal_code,
            country_code=address_resource.attributes.country_code,
            is_primary=address_resource.attributes.is_primary,
        )

    @staticmethod
    def from_note_resource(
        note_resource: ContactNoteResource, contact_id: int
    ) -> ContactNote:
        """Convert API note resource to domain entity."""
        return ContactNote(
            id=note_resource.id,
            contact_id=contact_id,
            content=note_resource.attributes.content,
            created_at=note_resource.attributes.created_at,
            updated_at=note_resource.attributes.updated_at,
        )

    @staticmethod
    def from_create_request(
        request_data: ContactCreateData,
    ) -> Contact:
        """Convert API create request to domain entity."""
        attrs = request_data.attributes

        # Convert embedded entities
        methods = [
            ContactRequestConverter.from_method_resource(
                method, 0
            )  # contact_id will be set later
            for method in attrs.contact_methods
        ]
        addresses = [
            ContactRequestConverter.from_address_resource(
                address, 0
            )  # contact_id will be set later
            for address in attrs.addresses
        ]
        notes = [
            ContactRequestConverter.from_note_resource(
                note, 0
            )  # contact_id will be set later
            for note in attrs.notes
        ]

        return Contact(
            first_name=attrs.first_name,
            last_name=attrs.last_name,
            middle_name=attrs.middle_name,
            nick_name=attrs.nick_name,
            methods=methods,
            addresses=addresses,
            notes=notes,
        )

    @staticmethod
    def from_update_request(
        request_data: ContactUpdateData,
        existing_contact: Contact,
    ) -> Contact:
        """Convert API update request to domain entity."""
        attrs = request_data.attributes

        # Convert embedded entities
        methods = [
            ContactRequestConverter.from_method_resource(
                method, existing_contact.id or 0
            )
            for method in attrs.contact_methods
        ]
        addresses = [
            ContactRequestConverter.from_address_resource(
                address, existing_contact.id or 0
            )
            for address in attrs.addresses
        ]
        notes = [
            ContactRequestConverter.from_note_resource(note, existing_contact.id or 0)
            for note in attrs.notes
        ]

        # Update the existing contact with new data
        updated_contact = Contact(
            id=existing_contact.id,
            first_name=attrs.first_name,
            last_name=attrs.last_name,
            middle_name=attrs.middle_name,
            nick_name=attrs.nick_name,
            methods=methods,
            addresses=addresses,
            notes=notes,
            tags=existing_contact.tags,  # Preserve existing tags
            created_at=existing_contact.created_at,
            updated_at=existing_contact.updated_at,
        )

        return updated_contact
