"""
Search API utilities for common operations.

Contains helper functions to reduce code duplication in search controllers.
"""

from typing import Any

from app.api.common.schemas import JsonApiLinks
from app.api.contacts.schemas import ContactAttributes, ContactResource


def create_contact_resource_from_search_hit(
    hit: dict[str, Any], base_url: str
) -> ContactResource:
    """
    Create a ContactResource from a MeiliSearch hit.

    Args:
        hit: Search result hit from MeiliSearch
        base_url: Base URL for building resource links

    Returns:
        ContactResource with search metadata
    """
    contact_id = str(hit["id"])

    attributes = ContactAttributes(
        first_name=hit.get("first_name", ""),
        last_name=hit.get("last_name"),
        middle_name=hit.get("middle_name"),
        nick_name=hit.get("nick_name"),
        company=hit.get("company"),
        job_title=hit.get("job_title"),
        is_favourite=hit.get("is_favourite", False),
        created_at=hit.get("created_at"),
        updated_at=hit.get("updated_at"),
        contact_methods=[],
        addresses=[],
        notes=[],
    )

    links = JsonApiLinks(
        self=f"{base_url}/api/contacts/{contact_id}",
    )

    return ContactResource(
        type="contacts",
        id=contact_id,
        attributes=attributes,
        links=links,
        meta={
            "search_score": hit.get("_rankingScore"),
            "highlighted": hit.get("_formatted"),
            "search_metadata": {
                "tags": hit.get("tags", []),
                "email": hit.get("email"),
                "phone": hit.get("phone"),
                "is_favourite": hit.get("is_favourite", False),
                "has_summary": hit.get("has_summary", False),
                "journal_count_30d": hit.get("journal_count_30d", 0),
                "activity_count_30d": hit.get("activity_count_30d", 0),
                "last_activity_date": hit.get("last_activity_date"),
                "relationships": hit.get("relationships", []),
            },
        },
    )


def calculate_pagination_offset(page: int, limit: int) -> int:
    """Calculate offset from page and limit."""
    return (page - 1) * limit
