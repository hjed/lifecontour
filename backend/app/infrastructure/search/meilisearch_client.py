"""
MeiliSearch client configuration and connection management.

Provides a configured MeiliSearch client with proper settings
for Lifecontour search functionality.
"""

from collections.abc import Collection, Mapping
from functools import lru_cache
from typing import Any

import structlog
from meilisearch import Client as MeiliSearchClient
from meilisearch.errors import MeilisearchError

from app.core.contacts.models.importance import CONTACT_IMPORTANCE_ORDER
from app.infrastructure.config import get_settings

logger = structlog.get_logger()


@lru_cache
def get_meilisearch_client() -> MeiliSearchClient:
    """Get cached MeiliSearch client."""
    settings = get_settings()

    client = MeiliSearchClient(
        url=settings.meilisearch_url,
        api_key=settings.meilisearch_api_key or None,
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
    except Exception as e:  # noqa: BLE001
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


def ensure_index_configured(
    client: MeiliSearchClient,
    index_name: str,
    settings: Mapping[str, Any],
    required_filterable: Collection[str],
) -> bool:
    """Create an index if it is missing and configure it if it is stale.

    An index is stale when it lacks one of ``required_filterable``: a search
    that filters on an attribute the index does not allow is an error, not an
    empty result. Returns True when the settings were applied, which means
    documents indexed earlier may predate the current schema.
    """
    try:
        filterable = client.index(index_name).get_filterable_attributes()
    except MeilisearchError:
        logger.info("Creating search index", index_name=index_name)
        task = client.create_index(index_name, {"primaryKey": "id"})
        client.wait_for_task(task.task_uid)
        filterable = None

    if filterable and set(required_filterable) <= set(filterable):
        return False

    logger.info("Configuring search index settings", index_name=index_name)
    task = client.index(index_name).update_settings(dict(settings))
    client.wait_for_task(task.task_uid)
    return True


# Filterable attributes that every deployed contacts index must have; every
# contact search filters on its owner. Verified at application startup (see
# ensure_contact_search_index).
CONTACTS_REQUIRED_FILTERABLE_ATTRIBUTES = ("user_id",)

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
        "user_id",
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
    "rankingRules": [
        "words",
        "typo",
        "proximity",
        "attribute",
        "sort",
        "exactness",
        # Text relevance first, then how much the contact matters to the user.
        # Derived from CONTACT_IMPORTANCE_ORDER rather than listed here, so the
        # index and the dashboard cannot come to disagree about the precedence:
        # there is one place to change it and both read that place.
        *(f"{signal}:desc" for signal in CONTACT_IMPORTANCE_ORDER),
    ],
}

# Index configuration for journals
# Filterable attributes that every deployed journals index must have. An index
# created before one of these was added is re-configured on the next indexing
# pass (see JournalIndexingService._ensure_journals_index_exists).
JOURNAL_REQUIRED_FILTERABLE_ATTRIBUTES = ("user_id", "id")

JOURNAL_INDEX_SETTINGS = {
    "searchableAttributes": [
        "title",
        "content",
        "location",
    ],
    "filterableAttributes": [
        "id",
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
