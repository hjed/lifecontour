"""Startup reconfiguration of the journals search index."""

from unittest.mock import MagicMock

from meilisearch.errors import MeilisearchError

from app.infrastructure.search.journal_indexing_service import (
    ensure_journal_search_index,
)
from app.infrastructure.search.meilisearch_client import JOURNAL_INDEX_SETTINGS


def _client(filterable: list[str] | None, *, exists: bool = True) -> MagicMock:
    client = MagicMock()
    index = client.index.return_value
    if not exists:
        index.fetch_info.side_effect = MeilisearchError("index not found")
    index.primary_key = "id"
    index.get_filterable_attributes.return_value = filterable
    client.create_index.return_value.task_uid = 1
    index.update_settings.return_value.task_uid = 2
    return client


def test_index_predating_id_filter_is_reconfigured() -> None:
    client = _client(["user_id", "types"])

    assert ensure_journal_search_index(client) is True

    client.index.return_value.update_settings.assert_called_once_with(
        JOURNAL_INDEX_SETTINGS
    )


def test_up_to_date_index_is_left_alone() -> None:
    client = _client(list(JOURNAL_INDEX_SETTINGS["filterableAttributes"]))

    assert ensure_journal_search_index(client) is False

    client.index.return_value.update_settings.assert_not_called()
    client.create_index.assert_not_called()


def test_missing_index_is_created_and_configured() -> None:
    client = _client(None, exists=False)

    assert ensure_journal_search_index(client) is True

    client.create_index.assert_called_once()
    client.index.return_value.update_settings.assert_called_once_with(
        JOURNAL_INDEX_SETTINGS
    )
