"""
Serialization and deserialization for Contact entities.

Provides functions to convert Contact domain entities to/from plain dicts
for use in outbox event payloads and other cross-boundary communication.
"""

from typing import Any

from core_shared.models.contacts.entities import (
    Contact,
    ContactAddress,
    ContactMethod,
    ContactNote,
    MethodType,
    Tag,
)
from core_shared.models.contacts.value_objects import TagName


class ContactDeserializationError(ValueError):
    """Raised when serialized contact data is malformed or invalid."""


def serialize_contact(contact: Contact) -> dict[str, Any]:
    """
    Serialize a Contact entity to a plain dict for storage in outbox events.

    Only includes fields relevant to the contact's identity and data,
    excluding internal fields like id, contact_id, created_at, updated_at.

    Args:
        contact: Contact entity to serialize

    Returns:
        Dictionary representation of the contact
    """
    return {
        "first_name": contact.first_name,
        "last_name": contact.last_name,
        "middle_name": contact.middle_name,
        "nick_name": contact.nick_name,
        "company": contact.company,
        "job_title": contact.job_title,
        "is_favourite": contact.is_favourite,
        "methods": [
            {
                "method_type": method.method_type.value,
                "value": method.value,
                "label": method.label,
                "is_primary": method.is_primary,
            }
            for method in contact.methods
        ],
        "addresses": [
            {
                "street_line_1": address.street_line_1,
                "street_line_2": address.street_line_2,
                "locality": address.locality,
                "region": address.region,
                "postal_code": address.postal_code,
                "country_code": address.country_code,
                "label": address.label,
                "is_primary": address.is_primary,
            }
            for address in contact.addresses
        ],
        "notes": [{"content": note.content} for note in contact.notes],
        "tags": [{"name": tag.name.value} for tag in contact.tags],
    }


def deserialize_contact(data: dict[str, Any]) -> Contact:
    """
    Deserialize a Contact entity from a plain dict (as stored in outbox events).

    Args:
        data: Dictionary representation of the contact

    Returns:
        Contact entity

    Raises:
        ContactDeserializationError: If required fields are missing or invalid
    """
    if not isinstance(data, dict):
        raise ContactDeserializationError("Contact payload must be a dictionary")

    try:
        methods = [
            ContactMethod(
                method_type=MethodType(method_data["method_type"]),
                value=method_data["value"],
                label=method_data.get("label"),
                is_primary=method_data.get("is_primary", False),
                contact_id=0,
            )
            for method_data in (data.get("methods") or [])
        ]

        addresses = [
            ContactAddress(
                street_line_1=addr_data["street_line_1"],
                country_code=addr_data["country_code"],
                street_line_2=addr_data.get("street_line_2"),
                locality=addr_data.get("locality"),
                region=addr_data.get("region"),
                postal_code=addr_data.get("postal_code"),
                label=addr_data.get("label"),
                is_primary=addr_data.get("is_primary", False),
                contact_id=0,
            )
            for addr_data in (data.get("addresses") or [])
        ]

        notes = [
            ContactNote(content=note_data["content"], contact_id=0)
            for note_data in (data.get("notes") or [])
        ]

        tags = [
            Tag(name=TagName(tag_data["name"])) for tag_data in (data.get("tags") or [])
        ]

        return Contact(
            first_name=data["first_name"],
            last_name=data.get("last_name"),
            middle_name=data.get("middle_name"),
            nick_name=data.get("nick_name"),
            company=data.get("company"),
            job_title=data.get("job_title"),
            is_favourite=data.get("is_favourite", False),
            methods=methods,
            addresses=addresses,
            notes=notes,
            tags=tags,
        )
    except KeyError as exc:
        raise ContactDeserializationError(
            f"Missing required contact field '{exc.args[0]}'"
        ) from exc
    except (TypeError, ValueError) as exc:
        raise ContactDeserializationError(str(exc)) from exc
