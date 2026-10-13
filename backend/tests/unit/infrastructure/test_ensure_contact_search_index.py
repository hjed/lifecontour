"""Startup reconfiguration of the contacts search index."""

from unittest.mock import MagicMock

from meilisearch.errors import MeilisearchError

from app.infrastructure.search.meilisearch_client import CONTACTS_INDEX_SETTINGS
from app.infrastructure.search.search_indexer import ensure_contact_search_index


def _client(filterable: list[str] | None, *, exists: bool = True) -> MagicMock:
    client = MagicMock()
    index = client.index.return_value
    if exists:
        index.get_filterable_attributes.return_value = filterable
    else:
        index.get_filterable_attributes.side_effect = MeilisearchError(
            "index not found"
        )
    client.create_index.return_value.task_uid = 1
    index.update_settings.return_value.task_uid = 2
    return client


def test_index_predating_the_owner_filter_is_reconfigured() -> None:
    client = _client(["tags", "entity_type", "is_favourite"])

    assert ensure_contact_search_index(client) is True

    client.index.return_value.update_settings.assert_called_once_with(
        CONTACTS_INDEX_SETTINGS
    )
    client.create_index.assert_not_called()


def test_up_to_date_index_is_left_alone() -> None:
    client = _client(list(CONTACTS_INDEX_SETTINGS["filterableAttributes"]))

    assert ensure_contact_search_index(client) is False

    client.index.return_value.update_settings.assert_not_called()
    client.create_index.assert_not_called()


def test_missing_index_is_created_and_configured() -> None:
    client = _client(None, exists=False)

    assert ensure_contact_search_index(client) is True

    client.create_index.assert_called_once()
    client.index.return_value.update_settings.assert_called_once_with(
        CONTACTS_INDEX_SETTINGS
    )
