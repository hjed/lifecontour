"""
Unit tests for MeiliSearch client configuration.

Tests the MeiliSearch client configuration and index settings.
"""

from unittest.mock import MagicMock, patch

import pytest
from meilisearch.errors import MeilisearchError, MeilisearchTimeoutError

from app.infrastructure.search.meilisearch_client import (
    CONTACTS_INDEX_SETTINGS,
    CONTACTS_REQUIRED_FILTERABLE_ATTRIBUTES,
    HTTP_TIMEOUT_SECONDS,
    MEILI_BATCH_SIZE,
    TASK_TIMEOUT_MS,
    SearchTaskFailedError,
    add_documents_reporting_rejected,
    ensure_index_configured,
    get_meilisearch_client,
    wait_for_task_success,
)


def test_the_client_gives_up_on_a_server_that_stops_answering() -> None:
    get_meilisearch_client.cache_clear()
    with patch(
        "app.infrastructure.search.meilisearch_client.MeiliSearchClient"
    ) as client_class:
        get_meilisearch_client()
    get_meilisearch_client.cache_clear()

    assert client_class.call_args.kwargs["timeout"] == HTTP_TIMEOUT_SECONDS


class TestMeiliSearchClientConfiguration:
    """Test cases for MeiliSearch client configuration."""

    def test_contacts_index_settings_includes_is_favourite_filterable(self):
        """Test that CONTACTS_INDEX_SETTINGS includes is_favourite as filterable attribute."""
        # Assert
        assert "filterableAttributes" in CONTACTS_INDEX_SETTINGS
        filterable_attributes = CONTACTS_INDEX_SETTINGS["filterableAttributes"]

        # Check that is_favourite is included in filterable attributes
        assert "is_favourite" in filterable_attributes

        # Verify other expected filterable attributes are still present
        expected_filterable = [
            "tags",
            "entity_type",
            "created_at",
            "updated_at",
            "is_favourite",
        ]
        for attr in expected_filterable:
            assert attr in filterable_attributes

    def test_contacts_index_settings_includes_is_favourite_displayed(self):
        """Test that CONTACTS_INDEX_SETTINGS includes is_favourite as displayed attribute."""
        # Assert
        assert "displayedAttributes" in CONTACTS_INDEX_SETTINGS
        displayed_attributes = CONTACTS_INDEX_SETTINGS["displayedAttributes"]

        # Check that is_favourite is included in displayed attributes
        assert "is_favourite" in displayed_attributes

        # Verify other expected displayed attributes are still present
        expected_displayed = [
            "id",
            "first_name",
            "last_name",
            "middle_name",
            "nick_name",
            "full_name",
            "email",
            "emails",
            "phone",
            "phones",
            "notes_content",
            "tags",
            "entity_type",
            "created_at",
            "updated_at",
            "is_favourite",
        ]
        for attr in expected_displayed:
            assert attr in displayed_attributes

    def test_contacts_index_settings_searchable_attributes_unchanged(self):
        """Test that searchable attributes remain unchanged (is_favourite should not be searchable)."""
        # Assert
        assert "searchableAttributes" in CONTACTS_INDEX_SETTINGS
        searchable_attributes = CONTACTS_INDEX_SETTINGS["searchableAttributes"]

        # is_favourite should NOT be in searchable attributes (it's for filtering, not searching)
        assert "is_favourite" not in searchable_attributes

        # Verify expected searchable attributes are present
        expected_searchable = [
            "first_name",
            "last_name",
            "middle_name",
            "nick_name",
            "full_name",
            "email",
            "emails",
            "phone",
            "phones",
            "notes_content",
        ]
        for attr in expected_searchable:
            assert attr in searchable_attributes

    def test_contacts_index_settings_sortable_attributes_unchanged(self):
        """Test that sortable attributes remain unchanged (is_favourite could be sortable but not required)."""
        # Assert
        assert "sortableAttributes" in CONTACTS_INDEX_SETTINGS
        sortable_attributes = CONTACTS_INDEX_SETTINGS["sortableAttributes"]

        # Verify expected sortable attributes are present
        expected_sortable = ["created_at", "updated_at", "last_name", "first_name"]
        for attr in expected_sortable:
            assert attr in sortable_attributes


def test_contacts_index_can_filter_by_owner() -> None:
    """Every contact search filters on ``user_id``, so the index must allow it."""
    assert "user_id" in CONTACTS_REQUIRED_FILTERABLE_ATTRIBUTES
    assert set(CONTACTS_REQUIRED_FILTERABLE_ATTRIBUTES) <= set(
        CONTACTS_INDEX_SETTINGS["filterableAttributes"]
    )


def test_contacts_index_never_displays_the_owner() -> None:
    """The owner is a filter, not part of the search response."""
    assert "user_id" not in CONTACTS_INDEX_SETTINGS["displayedAttributes"]


def _task(status: str, *, error: dict[str, str] | None = None) -> MagicMock:
    """A finished MeiliSearch task as ``wait_for_task`` returns it."""
    return MagicMock(status=status, error=error, uid=7)


class TestWaitForTaskSuccess:
    """The SDK returns a failed task without raising, so the helper must."""

    def test_returns_when_the_task_succeeded(self) -> None:
        client = MagicMock()
        client.wait_for_task.return_value = _task("succeeded")

        wait_for_task_success(client, 7)

        client.wait_for_task.assert_called_once_with(7, timeout_in_ms=TASK_TIMEOUT_MS)

    @pytest.mark.parametrize("status", ["failed", "canceled"])
    def test_raises_for_any_other_outcome(self, status: str) -> None:
        client = MagicMock()
        client.wait_for_task.return_value = _task(
            status, error={"code": "invalid_document_id"}
        )

        with pytest.raises(SearchTaskFailedError, match="invalid_document_id"):
            wait_for_task_success(client, 7)

    def test_the_failure_is_a_meilisearch_error(self) -> None:
        """Callers already translate ``MeilisearchError`` into a 503."""
        assert issubclass(SearchTaskFailedError, MeilisearchError)


class TestAddDocumentsReportingRejected:
    """One invalid document fails its whole task, so a batch is retried singly."""

    def _client(self, outcomes: list[MagicMock]) -> tuple[MagicMock, MagicMock]:
        client = MagicMock()
        index = client.index.return_value
        index.add_documents.return_value = MagicMock(task_uid=7)
        client.wait_for_task.side_effect = outcomes
        return client, index

    def test_a_clean_batch_is_sent_once(self) -> None:
        client, index = self._client([_task("succeeded")])
        documents = [{"id": 1}, {"id": 2}]

        rejected = add_documents_reporting_rejected(client, "contacts", documents)

        assert rejected == []
        index.add_documents.assert_called_once_with(documents)

    def test_a_failed_batch_is_retried_one_document_at_a_time(self) -> None:
        client, index = self._client(
            [_task("failed"), _task("succeeded"), _task("failed")]
        )
        documents = [{"id": 1}, {"id": 2}]

        rejected = add_documents_reporting_rejected(client, "contacts", documents)

        assert rejected == [2]
        assert [call.args[0] for call in index.add_documents.call_args_list] == [
            documents,
            [{"id": 1}],
            [{"id": 2}],
        ]

    def test_documents_are_sent_in_bounded_batches(self) -> None:
        client, index = self._client([_task("succeeded")] * 2)
        documents = [{"id": n} for n in range(MEILI_BATCH_SIZE + 1)]

        add_documents_reporting_rejected(client, "contacts", documents)

        assert [len(call.args[0]) for call in index.add_documents.call_args_list] == [
            MEILI_BATCH_SIZE,
            1,
        ]

    def test_a_timeout_is_not_treated_as_a_rejected_document(self) -> None:
        client, index = self._client([])
        client.wait_for_task.side_effect = MeilisearchTimeoutError("slow")

        with pytest.raises(MeilisearchTimeoutError):
            add_documents_reporting_rejected(client, "contacts", [{"id": 1}])

        index.add_documents.assert_called_once()


def test_ensure_index_configured_raises_when_applying_settings_fails() -> None:
    """A settings task that failed must not read as a configured index."""
    client = MagicMock()
    client.index.return_value.get_filterable_attributes.return_value = []
    client.wait_for_task.return_value = _task("failed", error={"code": "bad"})

    with pytest.raises(SearchTaskFailedError):
        ensure_index_configured(client, "contacts", {}, ("user_id",))
