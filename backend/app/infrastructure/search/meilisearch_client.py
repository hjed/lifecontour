"""
MeiliSearch client configuration and connection management.

Provides a configured MeiliSearch client with proper settings
for the personal management system search functionality.
"""

from functools import lru_cache

import structlog
from meilisearch import Client as MeiliSearchClient
from meilisearch.errors import MeilisearchError

from app.infrastructure.config import get_settings

logger = structlog.get_logger()


@lru_cache
def get_meilisearch_client() -> MeiliSearchClient:
    """Get cached MeiliSearch client."""
    settings = get_settings()

    client = MeiliSearchClient(
        url=settings.meilisearch_url,
        api_key=settings.meilisearch_api_key if settings.meilisearch_api_key else None,
    )

    logger.info("MeiliSearch client created", url=settings.meilisearch_url)
    return client


def check_meilisearch_connection() -> bool:
    """
    Check if MeiliSearch connection is working.

    Returns:
        bool: True if connection is successful, False otherwise
    """
    try:
        client = get_meilisearch_client()
        # Test connection by getting health status
        health = client.health()
        return health.get("status") == "available"
    except MeilisearchError as e:
        logger.error("MeiliSearch connection check failed", error=str(e))
        return False
    except Exception as e:
        logger.error("Unexpected error checking MeiliSearch connection", error=str(e))
        return False


def get_index_name(entity_type: str) -> str:
    """
    Get the full index name for an entity type.

    Args:
        entity_type: The entity type (e.g., 'contacts', 'journal', 'calendar')

    Returns:
        str: The full index name with prefix
    """
    settings = get_settings()
    return f"{settings.search_index_prefix}{entity_type}"


# Index configuration for contacts
CONTACTS_INDEX_SETTINGS = {
    "searchableAttributes": [
        "first_name",
        "last_name",
        "middle_name",
        "nick_name",
        "full_name",
        "company",
        "job_title",
        "email",
        "emails",
        "phone",
        "phones",
        "notes_content",
        "relationships",
        "summary_text",
        "important_dates",
        "journal_mentions",
    ],
    "filterableAttributes": [
        "tags",
        "entity_type",
        "created_at",
        "updated_at",
        "is_favourite",
        "has_summary",
        "last_activity_date",
        "journal_count_30d",
        "activity_count_30d",
    ],
    "sortableAttributes": [
        "created_at",
        "updated_at",
        "last_name",
        "first_name",
        "last_activity_date",
        "journal_count_30d",
        "activity_count_30d",
    ],
    "displayedAttributes": [
        "id",
        "first_name",
        "last_name",
        "middle_name",
        "nick_name",
        "full_name",
        "company",
        "job_title",
        "email",
        "emails",
        "phone",
        "phones",
        "notes_content",
        "tags",
        "relationships",
        "entity_type",
        "created_at",
        "updated_at",
        "is_favourite",
        "summary_text",
        "important_dates",
        "journal_mentions",
        "has_summary",
        "last_activity_date",
        "journal_count_30d",
        "activity_count_30d",
    ],
}

# Index configuration for journals
JOURNAL_INDEX_SETTINGS = {
    "searchableAttributes": [
        "title",
        "content",
        "location",
    ],
    "filterableAttributes": [
        "user_id",
        "event_date_range_start",
        "event_date_range_end",
        "types",
        "contact_ids",
        "tag_ids",
        "calendar_id",
        "parent_id",
        "entity_type",
        "created_at",
        "updated_at",
    ],
    "sortableAttributes": [
        "event_date_range_start",
        "event_date_range_end",
        "created_at",
        "updated_at",
        "title",
    ],
    "displayedAttributes": [
        "id",
        "user_id",
        "title",
        "content",
        "event_date_range_start",
        "event_date_range_end",
        "types",
        "contact_ids",
        "tag_ids",
        "calendar_id",
        "parent_id",
        "location",
        "entity_type",
        "created_at",
        "updated_at",
    ],
}

# Global search index settings (for cross-entity search)
GLOBAL_INDEX_SETTINGS = {
    "searchableAttributes": ["title", "content", "name", "description"],
    "filterableAttributes": ["entity_type", "tags", "created_at"],
    "sortableAttributes": ["created_at", "updated_at", "relevance_score"],
}
