"""
Integration tests for MeiliSearch functionality.

Tests the search service and indexer with a real MeiliSearch instance.
These tests require MeiliSearch to be running (can be skipped if not available).
"""

from unittest.mock import patch

import pytest
from meilisearch import Client as MeiliSearchClient
from meilisearch.errors import MeilisearchError

from app.infrastructure.search.meilisearch_client import (
    CONTACTS_INDEX_SETTINGS,
    check_meilisearch_connection,
    get_index_name,
)
from app.infrastructure.search.search_service import SearchService


@pytest.mark.integration
@pytest.mark.meilisearch
class TestMeiliSearchIntegration:
    """Integration tests for MeiliSearch functionality."""

    @pytest.fixture(scope="class")
    def meilisearch_client(self):
        """Create a real MeiliSearch client for testing."""
        try:
            # Use test port 7701 to connect to test MeiliSearch instance
            client = MeiliSearchClient(
                "http://localhost:7701", api_key="test_master_key"
            )
            # Test connection
            health = client.health()
            if health.get("status") != "available":
                pytest.skip("MeiliSearch is not available")
            return client
        except Exception:
            pytest.skip("MeiliSearch is not available")

    @pytest.fixture(scope="class")
    def test_index_name(self):
        """Get a test index name."""
        return "test_pms_contacts"

    @pytest.fixture(autouse=True)
    def cleanup_test_index(self, meilisearch_client, test_index_name):
        """Clean up test index before and after each test."""
        try:
            meilisearch_client.delete_index(test_index_name)
        except MeilisearchError:
            pass  # Index doesn't exist, which is fine

        yield

        try:
            meilisearch_client.delete_index(test_index_name)
        except MeilisearchError:
            pass

    def test_meilisearch_connection(self):
        """Test MeiliSearch connection check."""
        # This test will be skipped if MeiliSearch is not available
        # due to the fixture setup
        is_connected = check_meilisearch_connection()
        assert is_connected is True

    def test_create_and_configure_index(self, meilisearch_client, test_index_name):
        """Test creating and configuring a search index."""
        # Create index
        task = meilisearch_client.create_index(test_index_name, {"primaryKey": "id"})
        meilisearch_client.wait_for_task(task.task_uid)

        # Configure index settings
        index = meilisearch_client.index(test_index_name)
        task = index.update_settings(CONTACTS_INDEX_SETTINGS)
        meilisearch_client.wait_for_task(task.task_uid)

        # Verify settings were applied
        settings = index.get_settings()
        assert "first_name" in settings["searchableAttributes"]
        assert "last_name" in settings["searchableAttributes"]
        assert "tags" in settings["filterableAttributes"]

    def test_index_and_search_documents(self, meilisearch_client, test_index_name):
        """Test indexing documents and searching them."""
        # Create and configure index
        task = meilisearch_client.create_index(test_index_name, {"primaryKey": "id"})
        meilisearch_client.wait_for_task(task.task_uid)

        index = meilisearch_client.index(test_index_name)
        task = index.update_settings(CONTACTS_INDEX_SETTINGS)
        meilisearch_client.wait_for_task(task.task_uid)

        # Index test documents
        test_contacts = [
            {
                "id": 1,
                "first_name": "John",
                "last_name": "Doe",
                "full_name": "John Doe",
                "email": "john@example.com",
                "phone": "+1234567890",
                "tags": ["customer", "vip"],
                "entity_type": "contact",
                "created_at": "2024-01-01T12:00:00Z",
                "updated_at": "2024-01-01T12:00:00Z",
            },
            {
                "id": 2,
                "first_name": "Jane",
                "last_name": "Smith",
                "full_name": "Jane Smith",
                "email": "jane@example.com",
                "phone": "+1234567891",
                "tags": ["customer"],
                "entity_type": "contact",
                "created_at": "2024-01-01T12:05:00Z",
                "updated_at": "2024-01-01T12:05:00Z",
            },
            {
                "id": 3,
                "first_name": "Bob",
                "last_name": "Johnson",
                "full_name": "Bob Johnson",
                "email": "bob@example.com",
                "phone": "+1234567892",
                "tags": ["prospect"],
                "entity_type": "contact",
                "created_at": "2024-01-01T12:10:00Z",
                "updated_at": "2024-01-01T12:10:00Z",
            },
        ]

        task = index.add_documents(test_contacts)
        meilisearch_client.wait_for_task(task.task_uid)

        # Test basic search
        results = index.search("John")
        assert len(results["hits"]) >= 1
        assert any(hit["first_name"] == "John" for hit in results["hits"])

        # Test search with filters
        results = index.search("", {"filter": "tags = 'vip'"})
        assert len(results["hits"]) == 1
        assert results["hits"][0]["first_name"] == "John"

        # Test search by email
        results = index.search("jane@example.com")
        assert len(results["hits"]) >= 1
        assert any(hit["email"] == "jane@example.com" for hit in results["hits"])

    def test_update_and_delete_documents(self, meilisearch_client, test_index_name):
        """Test updating and deleting documents."""
        # Create and configure index
        task = meilisearch_client.create_index(test_index_name, {"primaryKey": "id"})
        meilisearch_client.wait_for_task(task.task_uid)

        index = meilisearch_client.index(test_index_name)
        task = index.update_settings(CONTACTS_INDEX_SETTINGS)
        meilisearch_client.wait_for_task(task.task_uid)

        # Index initial document
        initial_doc = {
            "id": 1,
            "first_name": "John",
            "last_name": "Doe",
            "full_name": "John Doe",
            "email": "john@example.com",
            "entity_type": "contact",
        }

        task = index.add_documents([initial_doc])
        meilisearch_client.wait_for_task(task.task_uid)

        # Update document
        updated_doc = {
            "id": 1,
            "first_name": "Johnny",
            "last_name": "Doe",
            "full_name": "Johnny Doe",
            "email": "johnny@example.com",
        }

        task = index.update_documents([updated_doc])
        meilisearch_client.wait_for_task(task.task_uid)

        # Verify update
        results = index.search("Johnny")
        assert len(results["hits"]) == 1
        assert results["hits"][0]["first_name"] == "Johnny"
        assert results["hits"][0]["email"] == "johnny@example.com"

        # Delete document
        task = index.delete_document(1)
        meilisearch_client.wait_for_task(task.task_uid)

        # Verify deletion
        results = index.search("Johnny")
        assert len(results["hits"]) == 0

    def test_search_service_integration(self, meilisearch_client, test_index_name):
        """Test SearchService with real MeiliSearch."""
        # Create and configure index
        task = meilisearch_client.create_index(test_index_name, {"primaryKey": "id"})
        meilisearch_client.wait_for_task(task.task_uid)

        index = meilisearch_client.index(test_index_name)
        task = index.update_settings(CONTACTS_INDEX_SETTINGS)
        meilisearch_client.wait_for_task(task.task_uid)

        # Index test data
        test_contacts = [
            {
                "id": 1,
                "first_name": "Alice",
                "last_name": "Wonder",
                "full_name": "Alice Wonder",
                "email": "alice@wonderland.com",
                "tags": ["customer", "premium"],
                "entity_type": "contact",
            },
            {
                "id": 2,
                "first_name": "Bob",
                "last_name": "Builder",
                "full_name": "Bob Builder",
                "email": "bob@construction.com",
                "tags": ["contractor"],
                "entity_type": "contact",
            },
        ]

        task = index.add_documents(test_contacts)
        meilisearch_client.wait_for_task(task.task_uid)

        # Test SearchService
        with (
            patch(
                "app.infrastructure.search.search_service.get_meilisearch_client",
                return_value=meilisearch_client,
            ),
            patch(
                "app.infrastructure.search.search_service.get_index_name",
                return_value=test_index_name,
            ),
        ):
            search_service = SearchService()

            # Test basic search
            results = search_service.search_contacts("Alice")
            assert results["estimated_total_hits"] >= 1
            assert any(hit["first_name"] == "Alice" for hit in results["hits"])

            # Test search with filters
            results = search_service.search_contacts("", filters={"tags": ["premium"]})
            assert len(results["hits"]) >= 1
            assert results["hits"][0]["first_name"] == "Alice"

            # Test pagination
            results = search_service.search_contacts("", limit=1, offset=0)
            assert len(results["hits"]) == 1
            assert results["limit"] == 1
            assert results["offset"] == 0

            # Test global search
            global_results = search_service.global_search("Bob")
            assert global_results["estimated_total_hits"] >= 1
            assert "searched_entity_types" in global_results
            assert "available_entity_types" in global_results

    def test_search_health_check(self, meilisearch_client):
        """Test search health check functionality."""
        with patch(
            "app.infrastructure.search.search_service.get_meilisearch_client",
            return_value=meilisearch_client,
        ):
            search_service = SearchService()
            health = search_service.get_search_health()

            assert health["status"] == "available"
            assert "meilisearch_health" in health
            assert "indices" in health

    def test_index_name_generation(self):
        """Test index name generation with prefix."""
        index_name = get_index_name("contacts")
        assert index_name.startswith("pms_")
        assert index_name.endswith("contacts")

        index_name = get_index_name("journal")
        assert index_name == "pms_journal"
