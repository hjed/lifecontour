"""
Converters between domain entities and JSON API schemas.

Handles the conversion between Contact domain entities and JSON API compliant
request/response schemas.
"""


from app.api.contacts.schemas import (
    ContactAddressAttributes,
    ContactAddressData,
    ContactAttributes,
    ContactData,
    ContactDataRequest,
    ContactMethodAttributes,
    ContactMethodData,
    ContactNoteAttributes,
    ContactNoteData,
    ContactRelationships,
    TagAttributes,
    TagData,
)
from app.core.contacts.models.entities import (
    Contact,
    ContactAddress,
    ContactMethod,
    ContactNote,
    Tag,
)


def contact_to_json_api(contact: Contact, include_relationships: bool = True) -> ContactData:
    """Convert a Contact domain entity to JSON API format."""
    # Build full name using the domain method
    full_name = contact.get_full_name()

    attributes = ContactAttributes(
        first_name=contact.first_name,
        last_name=contact.last_name,
        middle_name=contact.middle_name,
        nick_name=contact.nick_name,
        full_name=full_name,
        created_at=contact.created_at,
        updated_at=contact.updated_at,
    )

    relationships = None
    if include_relationships:
        relationships = ContactRelationships(
            methods={
                "data": [
                    {"type": "contact_method", "id": str(method.id)}
                    for method in contact.methods
                    if method.id is not None
                ]
            }
            if contact.methods
            else None,
            addresses={
                "data": [
                    {"type": "contact_address", "id": str(address.id)}
                    for address in contact.addresses
                    if address.id is not None
                ]
            }
            if contact.addresses
            else None,
            notes={
                "data": [
                    {"type": "contact_note", "id": str(note.id)}
                    for note in contact.notes
                    if note.id is not None
                ]
            }
            if contact.notes
            else None,
            tags={
                "data": [
                    {"type": "tag", "id": str(tag.id)}
                    for tag in contact.tags
                    if tag.id is not None
                ]
            }
            if contact.tags
            else None,
        )

    return ContactData(
        id=str(contact.id) if contact.id is not None else None,
        attributes=attributes,
        relationships=relationships,
    )


def json_api_to_contact(data: ContactData | ContactDataRequest, existing_contact: Contact | None = None) -> Contact:
    """Convert JSON API format to a Contact domain entity."""
    attrs = data.attributes

    # Handle methods from relationships
    methods = []
    if data.relationships and hasattr(data.relationships, 'methods') and data.relationships.methods:
        for method_data in data.relationships.methods:
            method = json_api_to_contact_method(method_data, 0)  # contact_id will be set later
            methods.append(method)

    # Handle addresses from relationships
    addresses = []
    if data.relationships and hasattr(data.relationships, 'addresses') and data.relationships.addresses:
        for address_data in data.relationships.addresses:
            address = json_api_to_contact_address(address_data, 0)  # contact_id will be set later
            addresses.append(address)

    # Handle notes from relationships
    notes = []
    if data.relationships and hasattr(data.relationships, 'notes') and data.relationships.notes:
        for note_data in data.relationships.notes:
            note = json_api_to_contact_note(note_data, 0)  # contact_id will be set later
            notes.append(note)

    # Handle tags from relationships
    tags = []
    if data.relationships and hasattr(data.relationships, 'tags') and data.relationships.tags:
        for tag_data in data.relationships.tags:
            # For now, we'll just create basic tag objects
            # In a real implementation, you might want to validate these exist
            tag = Tag(
                id=int(tag_data.id) if tag_data.id else None,
                name=tag_data.attributes.name,
                color=tag_data.attributes.color,
                parent_id=tag_data.attributes.parent_id,
            )
            tags.append(tag)

    if existing_contact:
        # Update existing contact
        existing_contact.first_name = attrs.first_name
        existing_contact.last_name = attrs.last_name
        existing_contact.middle_name = attrs.middle_name
        existing_contact.nick_name = attrs.nick_name

        # Update relationships if provided
        if methods:
            existing_contact.methods = methods
        if addresses:
            existing_contact.addresses = addresses
        if notes:
            existing_contact.notes = notes
        if tags:
            existing_contact.tags = tags

        return existing_contact
    else:
        # Create new contact
        return Contact(
            id=int(data.id) if data.id else None,
            first_name=attrs.first_name,
            last_name=attrs.last_name,
            middle_name=attrs.middle_name,
            nick_name=attrs.nick_name,
            methods=methods,
            addresses=addresses,
            notes=notes,
            tags=tags,
        )


def contact_method_to_json_api(method: ContactMethod) -> ContactMethodData:
    """Convert a ContactMethod domain entity to JSON API format."""
    attributes = ContactMethodAttributes(
        method_type=method.method_type,
        value=method.value,
        label=method.label,
        is_primary=method.is_primary,
        created_at=method.created_at,
        updated_at=method.updated_at,
    )

    return ContactMethodData(
        id=str(method.id) if method.id is not None else None,
        attributes=attributes,
    )


def json_api_to_contact_method(data: ContactMethodData, contact_id: int) -> ContactMethod:
    """Convert JSON API format to a ContactMethod domain entity."""
    attrs = data.attributes

    return ContactMethod(
        id=int(data.id) if data.id else None,
        method_type=attrs.method_type,
        value=attrs.value,
        contact_id=contact_id,
        label=attrs.label,
        is_primary=attrs.is_primary,
    )


def contact_address_to_json_api(address: ContactAddress) -> ContactAddressData:
    """Convert a ContactAddress domain entity to JSON API format."""
    attributes = ContactAddressAttributes(
        label=address.label,
        street_line_1=address.street_line_1,
        street_line_2=address.street_line_2,
        locality=address.locality,
        region=address.region,
        postal_code=address.postal_code,
        country_code=address.country_code,
        is_primary=address.is_primary,
        created_at=address.created_at,
        updated_at=address.updated_at,
    )

    return ContactAddressData(
        id=str(address.id) if address.id is not None else None,
        attributes=attributes,
    )


def json_api_to_contact_address(data: ContactAddressData, contact_id: int) -> ContactAddress:
    """Convert JSON API format to a ContactAddress domain entity."""
    attrs = data.attributes

    return ContactAddress(
        id=int(data.id) if data.id else None,
        street_line_1=attrs.street_line_1,
        country_code=attrs.country_code,
        contact_id=contact_id,
        label=attrs.label,
        street_line_2=attrs.street_line_2,
        locality=attrs.locality,
        region=attrs.region,
        postal_code=attrs.postal_code,
        is_primary=attrs.is_primary,
    )


def contact_note_to_json_api(note: ContactNote) -> ContactNoteData:
    """Convert a ContactNote domain entity to JSON API format."""
    attributes = ContactNoteAttributes(
        content=note.content,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )

    return ContactNoteData(
        id=str(note.id) if note.id is not None else None,
        attributes=attributes,
    )


def json_api_to_contact_note(data: ContactNoteData, contact_id: int) -> ContactNote:
    """Convert JSON API format to a ContactNote domain entity."""
    attrs = data.attributes

    return ContactNote(
        id=int(data.id) if data.id else None,
        content=attrs.content,
        contact_id=contact_id,
    )


def tag_to_json_api(tag: Tag) -> TagData:
    """Convert a Tag domain entity to JSON API format."""
    attributes = TagAttributes(
        name=str(tag.name),  # Convert TagName to string
        color=tag.color,
        parent_id=tag.parent_id,
        created_at=tag.created_at,
        updated_at=tag.updated_at,
    )

    return TagData(
        id=str(tag.id) if tag.id is not None else None,
        attributes=attributes,
    )


def build_included_data(contact: Contact) -> list[ContactMethodData | ContactAddressData | ContactNoteData | TagData]:
    """Build the included data array for a contact response."""
    included: list[ContactMethodData | ContactAddressData | ContactNoteData | TagData] = []

    # Add methods
    for method in contact.methods:
        included.append(contact_method_to_json_api(method))

    # Add addresses
    for address in contact.addresses:
        included.append(contact_address_to_json_api(address))

    # Add notes
    for note in contact.notes:
        included.append(contact_note_to_json_api(note))

    # Add tags
    for tag in contact.tags:
        included.append(tag_to_json_api(tag))

    return included


def detect_changed_fields(original: Contact, updated: Contact) -> dict[str, dict[str, str | None]]:
    """Detect which fields have changed between two contact instances."""
    changed_fields: dict[str, dict[str, str | None]] = {}

    if original.first_name != updated.first_name:
        changed_fields["first_name"] = {
            "old": original.first_name,
            "new": updated.first_name,
        }

    if original.last_name != updated.last_name:
        changed_fields["last_name"] = {
            "old": original.last_name,
            "new": updated.last_name,
        }

    if original.middle_name != updated.middle_name:
        changed_fields["middle_name"] = {
            "old": original.middle_name,
            "new": updated.middle_name,
        }

    if original.nick_name != updated.nick_name:
        changed_fields["nick_name"] = {
            "old": original.nick_name,
            "new": updated.nick_name,
        }

    return changed_fields
