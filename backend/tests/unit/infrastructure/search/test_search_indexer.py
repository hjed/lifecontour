"""
Unit tests for SearchIndexer.

Tests the search indexer that processes domain events and updates MeiliSearch indices.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from meilisearch.errors import MeilisearchError

from app.infrastructure.events.outbox_repository import OutboxEvent
from app.infrastructure.search.search_indexer import SearchIndexer


class TestSearchIndexer:
    """Test cases for SearchIndexer."""

    @pytest.fixture
    def mock_meilisearch_client(self):
        """Create a mock MeiliSearch client."""
        client = MagicMock()
        return client

    @pytest.fixture
    def mock_db_connection(self):
        """Create a mock database connection."""
        return MagicMock()

    @pytest.fixture
    def indexer(self, mock_meilisearch_client, mock_db_connection):
        """Create a SearchIndexer instance with mock client."""
        with patch(
            "app.infrastructure.search.search_indexer.get_meilisearch_client",
            return_value=mock_meilisearch_client,
        ):
            return SearchIndexer(db_connection=mock_db_connection)

    @pytest.fixture
    def contact_created_event(self):
        """Create a ContactCreated outbox event for testing."""
        return OutboxEvent(
            id=1,
            event_id="contact-created-123",
            event_type="ContactCreated",
            aggregate_id=42,
            event_data={"contact_id": 42, "first_name": "John", "last_name": "Doe"},
            occurred_at=datetime(2024, 1, 1, 12, 0, 0),
            retry_count=0,
            created_at=datetime(2024, 1, 1, 12, 0, 0),
        )

    @pytest.fixture
    def contact_updated_event(self):
        """Create a ContactUpdated outbox event for testing."""
        return OutboxEvent(
            id=2,
            event_id="contact-updated-456",
            event_type="ContactUpdated",
            aggregate_id=42,
            event_data={
                "contact_id": 42,
                "changed_fields": {"first_name": "Jane", "last_name": "Smith"},
            },
            occurred_at=datetime(2024, 1, 1, 13, 0, 0),
            retry_count=0,
            created_at=datetime(2024, 1, 1, 13, 0, 0),
        )

    @pytest.fixture
    def contact_deleted_event(self):
        """Create a ContactDeleted outbox event for testing."""
        return OutboxEvent(
            id=3,
            event_id="contact-deleted-789",
            event_type="ContactDeleted",
            aggregate_id=42,
            event_data={"contact_id": 42},
            occurred_at=datetime(2024, 1, 1, 14, 0, 0),
            retry_count=0,
            created_at=datetime(2024, 1, 1, 14, 0, 0),
        )

    @pytest.mark.asyncio
    async def test_process_contact_created_event(
        self, indexer, mock_meilisearch_client, contact_created_event
    ):
        """Test processing a ContactCreated event."""
        # Arrange
        mock_index = MagicMock()
        mock_meilisearch_client.index.return_value = mock_index
        mock_index.get_stats.return_value = {"numberOfDocuments": 0}

        mock_task = MagicMock()
        mock_task.task_uid = "task-123"
        mock_index.add_documents.return_value = mock_task

        with patch(
            "app.infrastructure.search.search_indexer.get_index_name",
            return_value="pms_contacts",
        ):
            # Act
            await indexer.process_event(contact_created_event)

        # Assert
        mock_index.add_documents.assert_called_once()
        documents = mock_index.add_documents.call_args[0][0]

        assert len(documents) == 1
        doc = documents[0]
        assert doc["id"] == 42
        assert doc["first_name"] == "John"
        assert doc["last_name"] == "Doe"
        assert doc["full_name"] == "John Doe"
        assert doc["entity_type"] == "contact"

    @pytest.mark.asyncio
    async def test_process_contact_updated_event(
        self, indexer, mock_meilisearch_client, contact_updated_event
    ):
        """Test processing a ContactUpdated event."""
        # Arrange
        mock_index = MagicMock()
        mock_meilisearch_client.index.return_value = mock_index
        mock_index.get_stats.return_value = {"numberOfDocuments": 1}

        mock_task = MagicMock()
        mock_task.task_uid = "task-456"
        mock_index.update_documents.return_value = mock_task

        # Mock the complete contact data fetch
        complete_contact_data = {
            "id": 42,
            "first_name": "Jane",
            "last_name": "Smith",
            "full_name": "Jane Smith",
            "email": "jane@example.com",
            "entity_type": "contact",
            "tags": ["customer"],
        }

        with (
            patch(
                "app.infrastructure.search.search_indexer.get_index_name",
                return_value="pms_contacts",
            ),
            patch.object(
                indexer,
                "_fetch_complete_contact_data",
                return_value=complete_contact_data,
            ),
        ):
            # Act
            await indexer.process_event(contact_updated_event)

        # Assert
        mock_index.update_documents.assert_called_once()
        documents = mock_index.update_documents.call_args[0][0]

        assert len(documents) == 1
        doc = documents[0]
        assert doc["id"] == 42
        assert doc["first_name"] == "Jane"
        assert doc["last_name"] == "Smith"
        assert doc["full_name"] == "Jane Smith"

    @pytest.mark.asyncio
    async def test_process_contact_deleted_event(
        self, indexer, mock_meilisearch_client, contact_deleted_event
    ):
        """Test processing a ContactDeleted event."""
        # Arrange
        mock_index = MagicMock()
        mock_meilisearch_client.index.return_value = mock_index
        mock_index.get_stats.return_value = {"numberOfDocuments": 1}

        mock_task = MagicMock()
        mock_task.task_uid = "task-789"
        mock_index.delete_document.return_value = mock_task

        with patch(
            "app.infrastructure.search.search_indexer.get_index_name",
            return_value="pms_contacts",
        ):
            # Act
            await indexer.process_event(contact_deleted_event)

        # Assert
        mock_index.delete_document.assert_called_once_with(42)

    @pytest.mark.asyncio
    async def test_process_unsupported_event_type(self, indexer):
        """Test processing an unsupported event type."""
        # Arrange
        unsupported_event = OutboxEvent(
            id=4,
            event_id="unsupported-event",
            event_type="UnsupportedEvent",
            aggregate_id=1,
            event_data={},
            occurred_at=datetime(2024, 1, 1, 15, 0, 0),
            retry_count=0,
            created_at=datetime(2024, 1, 1, 15, 0, 0),
        )

        # Act (should not raise an exception)
        await indexer.process_event(unsupported_event)

        # Assert - no MeiliSearch operations should be called
        indexer.client.index.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_contacts_index_creation(
        self, indexer, mock_meilisearch_client
    ):
        """Test that the contacts index is created if it doesn't exist."""
        # Arrange
        mock_index = MagicMock()
        mock_meilisearch_client.index.return_value = mock_index
        mock_index.get_stats.side_effect = MeilisearchError("Index not found")

        mock_create_task = MagicMock()
        mock_create_task.task_uid = "create-task"
        mock_meilisearch_client.create_index.return_value = mock_create_task

        mock_settings_task = MagicMock()
        mock_settings_task.task_uid = "settings-task"
        mock_index.update_settings.return_value = mock_settings_task

        # Act
        indexer._ensure_contacts_index_exists("pms_contacts")

        # Assert
        mock_meilisearch_client.create_index.assert_called_once_with(
            "pms_contacts", {"primaryKey": "id"}
        )
        mock_index.update_settings.assert_called_once()
        mock_meilisearch_client.wait_for_task.assert_called()

    @pytest.mark.asyncio
    async def test_process_event_handles_meilisearch_error(
        self, indexer, mock_meilisearch_client, contact_created_event
    ):
        """Test that MeiliSearch errors are properly handled."""
        # Arrange
        mock_meilisearch_client.index.side_effect = MeilisearchError(
            "Connection failed"
        )

        # Act & Assert
        with pytest.raises(MeilisearchError, match="Connection failed"):
            await indexer.process_event(contact_created_event)

    @pytest.mark.asyncio
    async def test_tag_assignment_event(self, indexer, mock_meilisearch_client):
        """Test processing a TagAssigned event."""
        # Arrange
        tag_event = OutboxEvent(
            id=5,
            event_id="tag-assigned-123",
            event_type="TagAssigned",
            aggregate_id=42,
            event_data={"contact_id": 42, "tag_name": "VIP"},
            occurred_at=datetime(2024, 1, 1, 16, 0, 0),
            retry_count=0,
            created_at=datetime(2024, 1, 1, 16, 0, 0),
        )

        mock_index = MagicMock()
        mock_meilisearch_client.index.return_value = mock_index
        mock_index.get_stats.return_value = {"numberOfDocuments": 1}

        mock_task = MagicMock()
        mock_task.task_uid = "tag-task"
        mock_index.update_documents.return_value = mock_task

        # Mock the complete contact data fetch
        complete_contact_data = {
            "id": 42,
            "first_name": "John",
            "last_name": "Doe",
            "full_name": "John Doe",
            "email": "john@example.com",
            "entity_type": "contact",
            "tags": ["customer", "VIP"],
        }

        with (
            patch(
                "app.infrastructure.search.search_indexer.get_index_name",
                return_value="pms_contacts",
            ),
            patch.object(
                indexer,
                "_fetch_complete_contact_data",
                return_value=complete_contact_data,
            ),
        ):
            # Act
            await indexer.process_event(tag_event)

        # Assert
        mock_index.update_documents.assert_called_once()
        documents = mock_index.update_documents.call_args[0][0]
        assert documents[0]["id"] == 42

    @pytest.mark.asyncio
    async def test_contact_created_includes_is_favourite_field(
        self, indexer, mock_meilisearch_client, contact_created_event
    ):
        """Test that ContactCreated event includes is_favourite field in indexed document."""
        # Arrange
        mock_index = MagicMock()
        mock_meilisearch_client.index.return_value = mock_index
        mock_index.get_stats.return_value = {"numberOfDocuments": 0}

        mock_task = MagicMock()
        mock_task.task_uid = "task-123"
        mock_index.add_documents.return_value = mock_task

        # Mock the complete contact data fetch to include is_favourite
        complete_contact_data = {
            "id": 42,
            "first_name": "John",
            "last_name": "Doe",
            "full_name": "John Doe",
            "email": "john@example.com",
            "entity_type": "contact",
            "is_favourite": True,
            "tags": [],
        }

        with (
            patch(
                "app.infrastructure.search.search_indexer.get_index_name",
                return_value="pms_contacts",
            ),
            patch.object(
                indexer,
                "_fetch_complete_contact_data",
                return_value=complete_contact_data,
            ),
        ):
            # Act
            await indexer.process_event(contact_created_event)

        # Assert
        mock_index.add_documents.assert_called_once()
        documents = mock_index.add_documents.call_args[0][0]

        assert len(documents) == 1
        doc = documents[0]
        assert doc["id"] == 42
        assert doc["is_favourite"] is True
        assert "is_favourite" in doc

    @pytest.mark.asyncio
    async def test_contact_updated_includes_is_favourite_field(
        self, indexer, mock_meilisearch_client, contact_updated_event
    ):
        """Test that ContactUpdated event includes is_favourite field in indexed document."""
        # Arrange
        mock_index = MagicMock()
        mock_meilisearch_client.index.return_value = mock_index
        mock_index.get_stats.return_value = {"numberOfDocuments": 1}

        mock_task = MagicMock()
        mock_task.task_uid = "task-456"
        mock_index.update_documents.return_value = mock_task

        # Mock the complete contact data fetch to include is_favourite
        complete_contact_data = {
            "id": 42,
            "first_name": "Jane",
            "last_name": "Smith",
            "full_name": "Jane Smith",
            "email": "jane@example.com",
            "entity_type": "contact",
            "is_favourite": False,
            "tags": ["customer"],
        }

        with (
            patch(
                "app.infrastructure.search.search_indexer.get_index_name",
                return_value="pms_contacts",
            ),
            patch.object(
                indexer,
                "_fetch_complete_contact_data",
                return_value=complete_contact_data,
            ),
        ):
            # Act
            await indexer.process_event(contact_updated_event)

        # Assert
        mock_index.update_documents.assert_called_once()
        documents = mock_index.update_documents.call_args[0][0]

        assert len(documents) == 1
        doc = documents[0]
        assert doc["id"] == 42
        assert doc["is_favourite"] is False
        assert "is_favourite" in doc

    @pytest.mark.asyncio
    async def test_relationship_change_event(self, indexer, mock_meilisearch_client):
        """Test processing a ContactRelationshipCreated event."""
        # Arrange
        rel_event = OutboxEvent(
            id=6,
            event_id="rel-created-123",
            event_type="ContactRelationshipCreated",
            aggregate_id=42,
            event_data={
                "from_contact_id": 42,
                "to_contact_id": 43,
                "relationship_type": "friend",
            },
            occurred_at=datetime(2024, 1, 1, 17, 0, 0),
            retry_count=0,
            created_at=datetime(2024, 1, 1, 17, 0, 0),
        )

        mock_index = MagicMock()
        mock_meilisearch_client.index.return_value = mock_index
        mock_index.get_stats.return_value = {"numberOfDocuments": 2}

        mock_task = MagicMock()
        mock_task.task_uid = "rel-task"
        mock_index.update_documents.return_value = mock_task

        # Mock the complete contact data fetch
        complete_contact_data = {
            "id": 42,
            "first_name": "John",
            "last_name": "Doe",
            "full_name": "John Doe",
            "email": "john@example.com",
            "entity_type": "contact",
            "relationships": ["Friend of Jane Smith"],
        }

        with (
            patch(
                "app.infrastructure.search.search_indexer.get_index_name",
                return_value="pms_contacts",
            ),
            patch.object(
                indexer,
                "_fetch_complete_contact_data",
                return_value=complete_contact_data,
            ),
        ):
            # Act
            await indexer.process_event(rel_event)

        # Assert - should be called for both contact_id 42 and 43
        assert mock_index.update_documents.call_count == 2
