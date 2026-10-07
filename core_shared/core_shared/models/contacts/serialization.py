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
    ImportantDate,
    MethodType,
    Tag,
)
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
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
    result: dict[str, Any] = {
        "first_name": contact.first_name,
        "user_id": contact.user_id,
        "last_name": contact.last_name,
        "middle_name": contact.middle_name,
        "nick_name": contact.nick_name,
        "company": contact.company,
        "job_title": contact.job_title,
        "photo_url": contact.photo_url,
        "is_favourite": contact.is_favourite,
    }

    if contact.methods is not None:
        result["methods"] = [
            {
                "method_type": method.method_type.value,
                "value": method.value,
                "label": method.label,
                "is_primary": method.is_primary,
                "is_archived": method.is_archived,
            }
            for method in contact.methods
        ]
    else:
        result["methods"] = None

    if contact.addresses is not None:
        result["addresses"] = [
            {
                "street_line_1": address.street_line_1,
                "street_line_2": address.street_line_2,
                "locality": address.locality,
                "region": address.region,
                "postal_code": address.postal_code,
                "country_code": address.country_code,
                "label": address.label,
                "is_primary": address.is_primary,
                "is_archived": address.is_archived,
            }
            for address in contact.addresses
        ]
    else:
        result["addresses"] = None

    if contact.notes is not None:
        result["notes"] = [{"content": note.content} for note in contact.notes]
    else:
        result["notes"] = None

    if contact.tags is not None:
        serialized_tags = []
        for tag in contact.tags:
            tag_dict: dict[str, Any] = {"name": tag.name.value}
            # Include parent_name for hierarchical tags (set by transformer)
            parent_name = getattr(tag, "_parent_name", None)
            if parent_name is not None:
                tag_dict["parent_name"] = parent_name
            serialized_tags.append(tag_dict)
        result["tags"] = serialized_tags
    else:
        result["tags"] = None

    if contact.important_dates is not None:
        result["important_dates"] = [
            {
                "date_type": date.date_type.value,
                "precision": date.precision.value,
                "year": date.year,
                "month": date.month,
                "day": date.day,
                "custom_date_type_id": date.custom_date_type_id,
            }
            for date in contact.important_dates
        ]
    else:
        result["important_dates"] = None

    return result


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

    # Every contact has exactly one owner; a payload that names none cannot
    # become a contact, and guessing would give it to the wrong user.
    user_id = data.get("user_id")
    if not isinstance(user_id, str) or not user_id.strip():
        raise ContactDeserializationError("Contact payload names no owner (user_id)")

    def _get_list(field: str) -> list[Any] | None:
        if field not in data or data[field] is None:
            return None
        val = data[field]
        if not isinstance(val, list):
            raise ContactDeserializationError(f"Field '{field}' must be a list or null")
        return val

    try:
        methods_data = _get_list("methods")
        methods = (
            [
                ContactMethod(
                    method_type=MethodType(method_data["method_type"]),
                    value=method_data["value"],
                    label=method_data.get("label"),
                    is_primary=method_data.get("is_primary", False),
                    is_archived=method_data.get("is_archived", False),
                    contact_id=0,
                )
                for method_data in methods_data
            ]
            if methods_data is not None
            else None
        )

        addresses_data = _get_list("addresses")
        addresses = (
            [
                ContactAddress(
                    street_line_1=addr_data["street_line_1"],
                    country_code=addr_data["country_code"],
                    street_line_2=addr_data.get("street_line_2"),
                    locality=addr_data.get("locality"),
                    region=addr_data.get("region"),
                    postal_code=addr_data.get("postal_code"),
                    label=addr_data.get("label"),
                    is_primary=addr_data.get("is_primary", False),
                    is_archived=addr_data.get("is_archived", False),
                    contact_id=0,
                )
                for addr_data in addresses_data
            ]
            if addresses_data is not None
            else None
        )

        notes_data = _get_list("notes")
        notes = (
            [
                ContactNote(content=note_data["content"], contact_id=0)
                for note_data in notes_data
            ]
            if notes_data is not None
            else None
        )

        tags_data = _get_list("tags")
        tags = (
            [Tag(name=TagName(tag_data["name"])) for tag_data in tags_data]
            if tags_data is not None
            else None
        )

        important_dates_data = _get_list("important_dates")
        important_dates = (
            [
                ImportantDate(
                    contact_id=0,
                    date_type=ImportantDateType(date_data["date_type"]),
                    precision=DatePrecision(date_data["precision"]),
                    year=date_data.get("year"),
                    month=date_data.get("month"),
                    day=date_data.get("day"),
                    custom_date_type_id=date_data.get("custom_date_type_id"),
                )
                for date_data in important_dates_data
            ]
            if important_dates_data is not None
            else None
        )

        # Default to 'Unknown' when first_name is missing, None, or blank.
        # Google contacts may lack a name (e.g. company-only entries);
        # the transformer already defaults to 'Unknown' but outbox events
        # from older code paths may omit the field entirely.
        raw_first_name = data.get("first_name")
        first_name = (
            raw_first_name
            if isinstance(raw_first_name, str) and raw_first_name.strip()
            else "Unknown"
        )

        return Contact(
            first_name=first_name,
            user_id=user_id,
            last_name=data.get("last_name"),
            middle_name=data.get("middle_name"),
            nick_name=data.get("nick_name"),
            company=data.get("company"),
            job_title=data.get("job_title"),
            photo_url=data.get("photo_url"),
            is_favourite=data.get("is_favourite", False),
            methods=methods,
            addresses=addresses,
            notes=notes,
            tags=tags,
            important_dates=important_dates,
        )
    except KeyError as exc:
        raise ContactDeserializationError(
            f"Missing required contact field '{exc.args[0]}'"
        ) from exc
    except (TypeError, ValueError) as exc:
        raise ContactDeserializationError(str(exc)) from exc
