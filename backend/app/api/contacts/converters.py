"""
Converters for transforming domain entities to API resources.

Handles the conversion between domain models and JSON API resources,
ensuring proper separation between domain and API layers.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from app.api.common.schemas import JsonApiLinks

if TYPE_CHECKING:
    from app.api.contacts.schemas import (
        ContactCreateData,
        ContactRelationshipCreateData,
        ContactRelationshipUpdateData,
        ContactUpdateData,
        CustomDateTypeCreateData,
        ImportantDateCreateData,
    )

from core_shared.models.contacts.entities import (
    Contact,
    ContactAddress,
    ContactMethod,
    ContactNote,
    ContactRelationship,
    ImportantDate,
    RelationshipType,
    Tag,
)
from core_shared.models.contacts.important_date_types import (
    CustomDateType,
    DatePrecision,
    ImportantDateType,
)

from app.api.contacts.schemas import (
    ContactAddressAttributes,
    ContactAddressResource,
    ContactAttributes,
    ContactHistoryAttributes,
    ContactHistoryResource,
    ContactMethodAttributes,
    ContactMethodResource,
    ContactNoteAttributes,
    ContactNoteResource,
    ContactRelationshipResource,
    ContactRelationshipResponseAttributes,
    ContactRelationships,
    ContactResource,
    CustomDateTypeAttributes,
    CustomDateTypeResource,
    ImportantDateAttributes,
    ImportantDateResource,
    TagAttributes,
    TagResource,
)
from app.core.contacts.models.repositories import ContactFieldHistoryEntry


def _validate_entity_id(entity_id: int | None, entity_type: str) -> None:
    """Validate that an entity has an ID before serialization."""
    if entity_id is None:
        raise ValueError(
            f"Cannot serialize {entity_type} without ID - {entity_type} must be persisted first"
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
    def to_important_date_resource(date: ImportantDate) -> ImportantDateResource:
        """Convert ImportantDate domain entity to API resource."""
        return ImportantDateResource(
            id=date.id,
            attributes=ImportantDateAttributes(
                date_type=date.date_type.value,
                precision=date.precision.value,
                year=date.year,
                month=date.month,
                day=date.day,
                custom_date_type_id=date.custom_date_type_id,
                custom_date_type_name=date.custom_date_type_name,
                created_at=date.created_at,
                updated_at=date.updated_at,
            ),
        )

    @staticmethod
    def to_resource(contact: Contact, base_url: str = "") -> ContactResource:
        """Convert Contact domain entity to API resource."""
        # Convert embedded entities
        contact_methods = [
            ContactConverter.to_method_resource(method)
            for method in (contact.methods or [])
        ]
        addresses = [
            ContactConverter.to_address_resource(address)
            for address in (contact.addresses or [])
        ]
        notes = [
            ContactConverter.to_note_resource(note) for note in (contact.notes or [])
        ]
        relationship_resources = [
            ContactRelationshipConverter.to_resource(relationship, base_url)
            for relationship in (contact.relationships or [])
        ]
        important_date_resources = [
            ContactConverter.to_important_date_resource(date)
            for date in (contact.important_dates or [])
        ]

        # Create attributes
        attributes = ContactAttributes(
            first_name=contact.first_name,
            last_name=contact.last_name,
            middle_name=contact.middle_name,
            nick_name=contact.nick_name,
            is_favourite=contact.is_favourite,
            created_at=contact.created_at,
            updated_at=contact.updated_at,
            contact_methods=contact_methods,
            addresses=addresses,
            notes=notes,
            relationships=relationship_resources,
            important_dates=important_date_resources,
        )

        # Create relationships (tags included with full attributes)
        relationships = None
        if contact.tags:
            relationships = ContactRelationships(
                tags={
                    "data": [
                        TagConverter.to_resource(tag, base_url).model_dump(
                            exclude_none=True
                        )
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

        _validate_entity_id(contact.id, "contact")

        return ContactResource(
            id=str(contact.id),
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
            parent_id=tag.parent_id,
        )

        # Create links
        links = None
        if base_url and tag.id:
            links = JsonApiLinks(
                self=f"{base_url}/api/tags/{tag.id}",
            )

        _validate_entity_id(tag.id, "tag")

        return TagResource(
            id=str(tag.id),
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
        from core_shared.models.contacts.entities import MethodType

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
    def from_important_date_resource(
        date_resource: ImportantDateResource, contact_id: int
    ) -> ImportantDate:
        """Convert API important date resource to domain entity."""
        return ImportantDate(
            id=date_resource.id,
            contact_id=contact_id,
            date_type=ImportantDateType(date_resource.attributes.date_type),
            precision=DatePrecision(date_resource.attributes.precision),
            year=date_resource.attributes.year,
            month=date_resource.attributes.month,
            day=date_resource.attributes.day,
            custom_date_type_id=date_resource.attributes.custom_date_type_id,
            custom_date_type_name=date_resource.attributes.custom_date_type_name,
            created_at=date_resource.attributes.created_at,
            updated_at=date_resource.attributes.updated_at,
        )

    @staticmethod
    def from_important_date_create_request(
        request_data: ImportantDateCreateData,
        contact_id: int,
    ) -> ImportantDate:
        """Convert API create request for important date to domain entity."""
        attrs = request_data.attributes
        return ImportantDate(
            contact_id=contact_id,
            date_type=ImportantDateType(attrs.date_type),
            precision=DatePrecision(attrs.precision),
            year=attrs.year,
            month=attrs.month,
            day=attrs.day,
            custom_date_type_id=attrs.custom_date_type_id,
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
        important_dates = [
            ContactRequestConverter.from_important_date_resource(
                date, 0
            )  # contact_id will be set later
            for date in attrs.important_dates
        ]

        return Contact(
            first_name=attrs.first_name,
            last_name=attrs.last_name,
            middle_name=attrs.middle_name,
            nick_name=attrs.nick_name,
            is_favourite=attrs.is_favourite,
            methods=methods,
            addresses=addresses,
            notes=notes,
            important_dates=important_dates,
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
        important_dates = [
            ContactRequestConverter.from_important_date_resource(
                date, existing_contact.id or 0
            )
            for date in attrs.important_dates
        ]

        # Update the existing contact with new data
        updated_contact = Contact(
            id=existing_contact.id,
            first_name=attrs.first_name,
            last_name=attrs.last_name,
            middle_name=attrs.middle_name,
            nick_name=attrs.nick_name,
            is_favourite=attrs.is_favourite,
            methods=methods,
            addresses=addresses,
            notes=notes,
            tags=existing_contact.tags,  # Preserve existing tags
            important_dates=important_dates,
            created_at=existing_contact.created_at,
            updated_at=existing_contact.updated_at,
        )

        return updated_contact


class ContactRelationshipConverter:
    """Converter for ContactRelationship domain entities to API resources."""

    @staticmethod
    def to_resource(
        relationship: ContactRelationship, base_url: str = ""
    ) -> ContactRelationshipResource:
        """Convert ContactRelationship domain entity to API resource."""
        attributes = ContactRelationshipResponseAttributes(
            relationship_type=relationship.relationship_type.value,
            from_contact_id=relationship.from_contact_id,
            to_contact_id=relationship.to_contact_id,
            to_contact_name=relationship.to_contact_name,
            created_at=relationship.created_at,
            updated_at=relationship.updated_at,
        )

        # Create links
        links = None
        if base_url and relationship.id:
            links = JsonApiLinks(
                self=f"{base_url}/api/contacts/{relationship.from_contact_id}/relationships/{relationship.id}",
            )

        if relationship.id is None:
            raise ValueError(
                "Cannot serialize relationship without ID - relationship must be persisted first"
            )

        return ContactRelationshipResource(
            id=str(relationship.id),
            attributes=attributes,
            links=links,
        )


class ContactRelationshipRequestConverter:
    """Converter for API requests to ContactRelationship domain entities."""

    @staticmethod
    def from_create_request(
        request_data: ContactRelationshipCreateData,
    ) -> ContactRelationship:
        """Convert API create request to domain entity."""

        attrs = request_data.attributes
        return ContactRelationship(
            from_contact_id=attrs.from_contact_id,
            to_contact_id=attrs.to_contact_id,
            relationship_type=RelationshipType(attrs.relationship_type),
        )

    @staticmethod
    def from_update_request(
        request_data: ContactRelationshipUpdateData,
        existing_relationship: ContactRelationship,
    ) -> ContactRelationship:
        """Convert API update request to domain entity."""
        from core_shared.models.contacts.entities import RelationshipType

        attrs = request_data.attributes
        return ContactRelationship(
            id=existing_relationship.id,
            from_contact_id=attrs.from_contact_id,
            to_contact_id=attrs.to_contact_id,
            relationship_type=RelationshipType(attrs.relationship_type),
            created_at=existing_relationship.created_at,
            updated_at=existing_relationship.updated_at,
        )


class ContactHistoryConverter:
    """Converter for ContactFieldHistoryEntry to API resources."""

    @staticmethod
    def to_resource(
        entry: ContactFieldHistoryEntry,
    ) -> ContactHistoryResource:
        """Convert ContactFieldHistoryEntry to API resource."""
        # Parse created_at if it's a string
        created_at = None
        if entry.created_at:
            if isinstance(entry.created_at, str):
                try:
                    created_at = datetime.fromisoformat(entry.created_at)
                except ValueError:
                    created_at = None
            else:
                created_at = entry.created_at

        attributes = ContactHistoryAttributes(
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            field_name=entry.field_name,
            old_value=entry.old_value,
            new_value=entry.new_value,
            changed_by=entry.changed_by,
            created_at=created_at,
        )

        if entry.id is None:
            raise ValueError("Cannot serialize history entry without ID")

        return ContactHistoryResource(
            type="contact_history",
            id=str(entry.id),
            attributes=attributes,
        )


class CustomDateTypeConverter:
    """Converter for CustomDateType domain entities to API resources."""

    @staticmethod
    def to_resource(
        ctype: CustomDateType, base_url: str = ""
    ) -> CustomDateTypeResource:
        """Convert CustomDateType domain entity to API resource."""
        attributes = CustomDateTypeAttributes(
            name=ctype.name,
            created_at=ctype.created_at,
            updated_at=ctype.updated_at,
        )

        links = None
        if base_url and ctype.id:
            links = JsonApiLinks(
                self=f"{base_url}/api/custom-date-types/{ctype.id}",
            )

        _validate_entity_id(ctype.id, "custom date type")

        return CustomDateTypeResource(
            id=str(ctype.id),
            attributes=attributes,
            links=links,
        )


class CustomDateTypeRequestConverter:
    """Converter for CustomDateType API requests to domain entities."""

    @staticmethod
    def from_create_request(request_data: CustomDateTypeCreateData) -> CustomDateType:
        """Convert API create request logic."""
        # Using domain directly since CustomDateType is just an entity kwargs model right now
        return CustomDateType(name=request_data.attributes.name)
