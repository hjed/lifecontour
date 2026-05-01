"""
Unit tests for OutboxEventProcessor service.

Tests the processing of outbox events from integration workers,
including contact sync events and sync completion events.
"""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from core_shared.models.contacts.entities import Contact, ContactMethod, MethodType, Tag
from core_shared.models.contacts.value_objects import TagName
from core_shared.models.outbox import OutboxEvent
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.services.contact_service import ContactService
from app.core.integrations.outbox_event_processor import (
    OutboxEventProcessingError,
    OutboxEventProcessor,
    PermanentOutboxEventProcessingError,
)


class TestOutboxEventProcessor:
    """Test cases for OutboxEventProcessor."""

    @pytest.fixture
    def mock_contact_service(self) -> AsyncMock:
        """Create mock contact service."""
        return AsyncMock(spec=ContactService)

    @pytest.fixture
    def mock_connection(self) -> AsyncMock:
        """Create mock database connection."""
        from contextlib import asynccontextmanager

        conn = AsyncMock(spec=AsyncConnection)

        @asynccontextmanager
        async def mock_begin_nested():
            yield conn

        conn.begin_nested = mock_begin_nested
        return conn

    @pytest.fixture
    def mock_external_ref_service(self) -> AsyncMock:
        """Create mock external reference service."""
        service = AsyncMock()
        service.find_by_external_id.return_value = None
        service.find_external_reference.return_value = None
        service.create_external_reference.return_value = AsyncMock()
        return service

    @pytest.fixture
    def mock_sync_metadata_repo(self) -> AsyncMock:
        """Create mock sync metadata repository."""
        repo = AsyncMock()
        repo.find_and_lock.return_value = None
        repo.upsert.return_value = AsyncMock()
        repo.should_sync = MagicMock(return_value=True)
        return repo

    @pytest.fixture
    def mock_tag_repo(self) -> AsyncMock:
        """Create mock tag repository."""

        repo = AsyncMock()
        repo.find_by_names.return_value = {}
        return repo

    @pytest.fixture
    def processor(
        self,
        mock_contact_service: AsyncMock,
        mock_connection: AsyncConnection,
        mock_external_ref_service: AsyncMock,
        mock_sync_metadata_repo: AsyncMock,
        mock_tag_repo: AsyncMock,
    ) -> OutboxEventProcessor:
        """Create OutboxEventProcessor instance."""
        processor = OutboxEventProcessor(
            contact_service=mock_contact_service, connection=mock_connection
        )
        processor.external_reference_service = mock_external_ref_service
        processor.sync_metadata_repo = mock_sync_metadata_repo
        processor.tag_repo = mock_tag_repo
        return processor

    @pytest.fixture
    def sample_contact_event_data(self) -> dict[str, Any]:
        """Sample contact data in internal format (as stored in outbox events after transformation)."""
        return {
            "first_name": "John",
            "last_name": "Doe",
            "middle_name": None,
            "nick_name": None,
            "company": None,
            "job_title": None,
            "is_favourite": False,
            "methods": [
                {
                    "method_type": "email",
                    "value": "john.doe@example.com",
                    "label": "Work",
                    "is_primary": True,
                },
                {
                    "method_type": "phone",
                    "value": "+1-555-123-4567",
                    "label": "Mobile",
                    "is_primary": True,
                },
            ],
            "addresses": [],
            "notes": [],
            "tags": [],
        }

    @pytest.fixture
    def contact_created_event(
        self, sample_contact_event_data: dict[str, Any]
    ) -> OutboxEvent:
        """Create a contact.created outbox event."""
        return OutboxEvent(
            id=uuid4(),
            event_type="contact.created",
            event_data={
                "integration_source": "google",
                "external_id": "people/c123456789",
                "contact_data": sample_contact_event_data,
                "sync_timestamp": datetime.now(UTC).isoformat(),
                "sync_type": "created",
            },
            created_at=datetime.now(UTC),
            retry_count=0,
        )

    @pytest.fixture
    def contact_updated_event(
        self, sample_contact_event_data: dict[str, Any]
    ) -> OutboxEvent:
        """Create a contact.updated outbox event."""
        updated_data = sample_contact_event_data.copy()
        updated_data["first_name"] = "Johnny"  # Updated name

        return OutboxEvent(
            id=uuid4(),
            event_type="contact.updated",
            event_data={
                "integration_source": "google",
                "external_id": "people/c123456789",
                "contact_data": updated_data,
                "sync_timestamp": datetime.now(UTC).isoformat(),
                "sync_type": "updated",
            },
            created_at=datetime.now(UTC),
            retry_count=0,
        )

    @pytest.fixture
    def sync_completed_event(self) -> OutboxEvent:
        """Create a sync.completed outbox event."""
        return OutboxEvent(
            id=uuid4(),
            event_type="sync.completed",
            event_data={
                "integration_source": "google",
                "google_account_email": "user@example.com",
                "metrics": {
                    "contacts_processed": 5,
                    "contacts_created": 3,
                    "contacts_updated": 2,
                    "errors": 0,
                    "sync_type": "full",
                    "started_at": "2024-01-01T10:00:00Z",
                    "completed_at": "2024-01-01T10:05:00Z",
                },
                "completed_at": datetime.now(UTC).isoformat(),
            },
            created_at=datetime.now(UTC),
            retry_count=0,
        )

    @pytest.mark.asyncio
    async def test_process_contact_created_event(
        self,
        processor: OutboxEventProcessor,
        contact_created_event: OutboxEvent,
        mock_contact_service: AsyncMock,
        mock_connection: AsyncConnection,
        mock_external_ref_service: AsyncMock,
        mock_sync_metadata_repo: AsyncMock,
    ):
        """Test processing a contact.created event."""
        # Mock contact service to return created contact
        expected_contact = Contact(
            id=123,
            first_name="John",
            last_name="Doe",
            methods=[
                ContactMethod(
                    id=1,
                    method_type=MethodType.EMAIL,
                    value="john.doe@example.com",
                    contact_id=123,
                    is_primary=True,
                )
            ],
        )
        mock_contact_service.create_contact.return_value = expected_contact
        mock_contact_service.get_contact_by_email.return_value = None

        # Process the event
        result = await processor.process_event(contact_created_event)

        # Verify contact service was called correctly
        mock_contact_service.create_contact.assert_called_once()
        mock_sync_metadata_repo.upsert.assert_called_once()
        created_contact_arg = mock_contact_service.create_contact.call_args[0][0]

        assert created_contact_arg.first_name == "John"
        assert created_contact_arg.last_name == "Doe"
        assert len(created_contact_arg.methods) == 2  # Email + phone
        assert any(
            m.value == "john.doe@example.com" for m in created_contact_arg.methods
        )
        assert any(m.value == "+1-555-123-4567" for m in created_contact_arg.methods)

        # Verify transaction was passed
        assert mock_contact_service.create_contact.call_args[0][1] == mock_connection

        # Verify result
        assert result["status"] == "success"
        assert result["event_type"] == "contact.created"
        assert result["contact_id"] == 123

    @pytest.mark.asyncio
    async def test_process_contact_updated_event(
        self,
        processor: OutboxEventProcessor,
        contact_updated_event: OutboxEvent,
        mock_contact_service: AsyncMock,
        mock_connection: AsyncConnection,
        mock_external_ref_service: AsyncMock,
        mock_sync_metadata_repo: AsyncMock,
    ):
        """Test processing a contact.updated event."""
        # Mock existing contact lookup
        existing_contact = Contact(
            id=123,
            first_name="John",
            last_name="Doe",
        )
        mock_contact_service.find_contact_by_external_reference.return_value = (
            existing_contact
        )

        # Mock contact service to return updated contact
        updated_contact = Contact(
            id=123,
            first_name="Johnny",  # Updated name
            last_name="Doe",
        )
        mock_contact_service.update_contact.return_value = updated_contact

        # Process the event
        result = await processor.process_event(contact_updated_event)

        # Verify existing contact was looked up
        mock_contact_service.find_contact_by_external_reference.assert_called_once_with(
            integration_source="google",
            external_id="people/c123456789",
            transaction=mock_connection,
        )

        # Verify contact service was called correctly
        mock_contact_service.update_contact.assert_called_once()
        updated_contact_arg = mock_contact_service.update_contact.call_args[0][0]

        assert updated_contact_arg.id == 123
        assert updated_contact_arg.first_name == "Johnny"  # Updated name
        assert updated_contact_arg.last_name == "Doe"

        # Verify result
        assert result["status"] == "success"
        assert result["event_type"] == "contact.updated"
        assert result["contact_id"] == 123

    def _setup_contact_and_reference_mocks(
        self,
        mock_contact_service: AsyncMock,
        mock_external_ref_service: AsyncMock,
        reference_data_dict: dict[str, Any],
    ) -> Contact:
        import json

        from core_shared.models.external_reference import ExternalReference

        existing_contact = Contact(id=123, first_name="John", last_name="Doe", tags=[])
        mock_contact_service.find_contact_by_external_reference.return_value = (
            existing_contact
        )
        mock_contact_service.get_contact_by_id.return_value = existing_contact
        mock_contact_service.update_contact.return_value = existing_contact

        mock_external_ref_service.find_external_reference.return_value = (
            ExternalReference(
                id=99,
                internal_entity_type="contact",
                internal_entity_id=123,
                external_system="google",
                external_entity_type="person",
                external_entity_id="people/c123456789",
                reference_data=json.dumps(reference_data_dict),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        return existing_contact

    def _create_invalid_event(self) -> OutboxEvent:
        return OutboxEvent(
            id=uuid4(),
            event_type="contact.created",
            event_data={
                "integration_source": "google",
                "external_id": "people/invalid",
                "contact_data": {"invalid": "data"},  # Missing required fields
                "sync_timestamp": datetime.now(UTC).isoformat(),
                "sync_type": "created",
            },
            created_at=datetime.now(UTC),
            retry_count=0,
        )

    @pytest.mark.asyncio
    async def test_process_contact_updated_updates_reference_data(
        self,
        processor: OutboxEventProcessor,
        contact_updated_event: OutboxEvent,
        mock_contact_service: AsyncMock,
        mock_connection: AsyncConnection,
        mock_external_ref_service: AsyncMock,
    ):
        """Test that updating a contact also parses and updates existing reference_data JSON correctly."""
        # We will add some fake "tags" to the event payload to test the synced_tags update
        contact_updated_event.event_data["contact_data"]["tags"] = [{"name": "VIP"}]

        self._setup_contact_and_reference_mocks(
            mock_contact_service, mock_external_ref_service, {"old_key": "old_value"}
        )

        await processor.process_event(contact_updated_event)

        mock_external_ref_service.update_external_reference.assert_called_once()
        call_kwargs = mock_external_ref_service.update_external_reference.call_args[1]
        assert call_kwargs["reference_id"] == 99

        # Verify JSON
        updated_ref_data_str = call_kwargs["reference_data"]
        assert isinstance(updated_ref_data_str, str)
        import json

        updated_ref_data = json.loads(updated_ref_data_str)
        assert updated_ref_data["old_key"] == "old_value"
        assert updated_ref_data["synced_tags"] == ["VIP"]

    @pytest.mark.asyncio
    async def test_process_contact_updated_omits_reference_data_tags(
        self,
        processor: OutboxEventProcessor,
        contact_updated_event: OutboxEvent,
        mock_contact_service: AsyncMock,
        mock_connection: AsyncConnection,
        mock_external_ref_service: AsyncMock,
    ):
        """Test that omitting tags in a contact update does not overwrite existing synced_tags in reference_data."""
        # Remove "tags" from contact data
        if "tags" in contact_updated_event.event_data["contact_data"]:
            del contact_updated_event.event_data["contact_data"]["tags"]

        self._setup_contact_and_reference_mocks(
            mock_contact_service,
            mock_external_ref_service,
            {"old_key": "old_value", "synced_tags": ["Work"]},
        )

        await processor.process_event(contact_updated_event)

        mock_external_ref_service.update_external_reference.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_contact_updated_none_tags_reference_data(
        self,
        processor: OutboxEventProcessor,
        contact_updated_event: OutboxEvent,
        mock_contact_service: AsyncMock,
        mock_connection: AsyncConnection,
        mock_external_ref_service: AsyncMock,
        mock_sync_metadata_repo: AsyncMock,
    ):
        """Test that explicitly setting tags to None in contact update does not overwrite existing synced_tags."""
        # Explicitly set tags to None
        contact_updated_event.event_data["contact_data"]["tags"] = None

        self._setup_contact_and_reference_mocks(
            mock_contact_service,
            mock_external_ref_service,
            {"old_key": "old_value", "synced_tags": ["Work"]},
        )

        # Mock tag_repo as it's accessed directly by the processor
        processor.tag_repo = AsyncMock()
        processor.tag_repo.find_by_names.return_value = {}

        await processor.process_event(contact_updated_event)

        mock_external_ref_service.update_external_reference.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_sync_completed_event(
        self,
        processor: OutboxEventProcessor,
        sync_completed_event: OutboxEvent,
    ):
        """Test processing a sync.completed event."""
        # Process the event
        result = await processor.process_event(sync_completed_event)

        # Verify result (sync completed events are just logged)
        assert result["status"] == "success"
        assert result["event_type"] == "sync.completed"
        assert result["google_account_email"] == "user@example.com"
        assert result["metrics"]["contacts_processed"] == 5

    @pytest.mark.asyncio
    async def test_process_unknown_event_type(
        self,
        processor: OutboxEventProcessor,
    ):
        """Test processing an unknown event type."""
        unknown_event = OutboxEvent(
            id=uuid4(),
            event_type="unknown.event",
            event_data={"test": "data"},
            created_at=datetime.now(UTC),
            retry_count=0,
        )

        # Should raise an error for unknown event types
        with pytest.raises(OutboxEventProcessingError) as exc_info:
            await processor.process_event(unknown_event)

        assert "Unknown event type" in str(exc_info.value)
        assert "unknown.event" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_process_contact_created_with_service_error(
        self,
        processor: OutboxEventProcessor,
        contact_created_event: OutboxEvent,
        mock_contact_service: AsyncMock,
    ):
        """Test handling contact service errors during contact creation."""
        # Mock contact service to raise an error
        mock_contact_service.get_contact_by_email.return_value = None
        mock_contact_service.create_contact.side_effect = Exception("Database error")

        # Should raise OutboxEventProcessingError
        with pytest.raises(OutboxEventProcessingError) as exc_info:
            await processor.process_event(contact_created_event)

        assert "Failed to process contact.created event" in str(exc_info.value)
        assert "Database error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_process_contact_created_duplicate_email_returns_conflict(
        self,
        processor: OutboxEventProcessor,
        contact_created_event: OutboxEvent,
        mock_contact_service: AsyncMock,
    ):
        """Test that DuplicateEmailError during creation returns conflict instead of raising."""
        from app.core.contacts.models.exceptions import DuplicateEmailError

        mock_contact_service.get_contact_by_email.return_value = None
        mock_contact_service.create_contact.side_effect = DuplicateEmailError(
            "john.doe@example.com", 999
        )

        # Should NOT raise - should return conflict result
        result = await processor.process_event(contact_created_event)

        assert result["status"] == "conflict"
        assert result["reason"] == "duplicate_email"
        assert result["event_type"] == "contact.created"
        assert "john.doe@example.com" in result["error"]
        mock_contact_service.create_contact.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_contact_created_already_linked_returns_conflict(
        self,
        processor: OutboxEventProcessor,
        contact_created_event: OutboxEvent,
        mock_contact_service: AsyncMock,
        mock_external_ref_service: AsyncMock,
    ):
        """Test that reconciling with a contact already linked to the same source returns conflict."""
        from core_shared.models.external_reference import ExternalReference

        existing_contact = Contact(id=123, first_name="John", last_name="Doe")
        mock_contact_service.get_contact_by_email.return_value = existing_contact

        mock_external_ref_service.find_external_reference.return_value = (
            ExternalReference(
                id=99,
                internal_entity_type="contact",
                internal_entity_id=123,
                external_system="google",
                external_entity_type="person",
                external_entity_id="people/existing",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )

        result = await processor.process_event(contact_created_event)

        assert result["status"] == "conflict"
        assert result["reason"] == "reconciliation_conflict"
        assert result["event_type"] == "contact.created"
        assert result["integration_source"] == "google"
        assert "error" in result
        mock_contact_service.create_contact.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_contact_updated_duplicate_email_returns_conflict(
        self,
        processor: OutboxEventProcessor,
        contact_updated_event: OutboxEvent,
        mock_contact_service: AsyncMock,
        mock_connection: AsyncConnection,
        mock_external_ref_service: AsyncMock,
        mock_sync_metadata_repo: AsyncMock,
    ):
        """Test that DuplicateEmailError during update returns conflict and records in sync_metadata."""
        from app.core.contacts.models.exceptions import DuplicateEmailError

        existing_contact = Contact(id=123, first_name="John", last_name="Doe", tags=[])
        mock_contact_service.find_contact_by_external_reference.return_value = (
            existing_contact
        )
        mock_contact_service.get_contact_by_id.return_value = existing_contact
        mock_contact_service.update_contact.side_effect = DuplicateEmailError(
            "john.doe@example.com", 456
        )

        # Should NOT raise - should return conflict result
        result = await processor.process_event(contact_updated_event)

        assert result["status"] == "conflict"
        assert result["reason"] == "duplicate_email"
        assert result["event_type"] == "contact.updated"
        assert "john.doe@example.com" in result["error"]

        # Verify conflict was recorded in sync_metadata
        mock_sync_metadata_repo.upsert.assert_called_once()
        upsert_kwargs = mock_sync_metadata_repo.upsert.call_args[1]
        assert upsert_kwargs["internal_id"] == 123
        assert upsert_kwargs["integration_source"] == "google"
        from core_shared.models.sync_metadata import SyncStatus

        assert upsert_kwargs["sync_status"] == SyncStatus.CONFLICT
        assert "john.doe@example.com" in upsert_kwargs["error_message"]

    @pytest.mark.asyncio
    async def test_process_contact_updated_contact_not_found(
        self,
        processor: OutboxEventProcessor,
        contact_updated_event: OutboxEvent,
        mock_contact_service: AsyncMock,
        mock_connection: AsyncConnection,
    ):
        """Test handling contact.updated when contact doesn't exist."""
        # Mock contact service to return None (contact not found)
        mock_contact_service.find_contact_by_external_reference.return_value = None

        # Should raise OutboxEventProcessingError
        with pytest.raises(OutboxEventProcessingError) as exc_info:
            await processor.process_event(contact_updated_event)

        assert "Contact not found for update" in str(exc_info.value)
        assert "people/c123456789" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_process_event_with_invalid_contact_data(
        self,
        processor: OutboxEventProcessor,
        mock_contact_service: AsyncMock,
    ):
        """Test processing event with invalid contact data."""
        invalid_event = self._create_invalid_event()

        # Should raise a permanent processing error for malformed payloads
        with pytest.raises(PermanentOutboxEventProcessingError) as exc_info:
            await processor.process_event(invalid_event)

        assert "Missing required contact field 'first_name'" in str(exc_info.value)
        mock_contact_service.create_contact.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_contact_updated_with_invalid_contact_data_is_permanent(
        self,
        processor: OutboxEventProcessor,
        contact_updated_event: OutboxEvent,
        mock_contact_service: AsyncMock,
    ):
        """Test malformed contact.updated payloads are treated as permanent failures."""
        contact_updated_event.event_data["contact_data"] = {"invalid": "data"}

        existing_contact = Contact(id=123, first_name="John", last_name="Doe")
        mock_contact_service.find_contact_by_external_reference.return_value = (
            existing_contact
        )

        with pytest.raises(PermanentOutboxEventProcessingError) as exc_info:
            await processor.process_event(contact_updated_event)

        assert "Missing required contact field 'first_name'" in str(exc_info.value)
        mock_contact_service.update_contact.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_event_logs_permanent_failures_distinctly(
        self,
        processor: OutboxEventProcessor,
        mock_contact_service: AsyncMock,
    ):
        """Test permanent payload failures use a distinct log message."""
        invalid_event = self._create_invalid_event()

        with patch(
            "app.core.integrations.outbox_event_processor.logger.error"
        ) as mock_log_error:
            with pytest.raises(PermanentOutboxEventProcessingError):
                await processor.process_event(invalid_event)

        mock_log_error.assert_called_once()
        assert mock_log_error.call_args.args[0] == (
            "Outbox event has permanent invalid payload"
        )
        mock_contact_service.create_contact.assert_not_called()

    @pytest.mark.asyncio
    async def test_resolve_contact_tags_returns_none_if_tags_not_in_payload(
        self, processor: OutboxEventProcessor
    ):
        """If incoming tags are None/omitted, it should return None to avoid overwriting."""
        result = await processor._resolve_contact_tags(
            contact_data={"first_name": "Test"},
            existing_reference_data=None,
            existing_contact_tags=[],
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_resolve_contact_tags_preserves_local_only_tags(
        self, processor: OutboxEventProcessor, mock_tag_repo: AsyncMock
    ):
        """Locally added tags (not in synced_tags history) should be preserved."""
        # mock_tag_repo fixture needs to return our dict
        mock_tag_repo.find_by_names.return_value = {
            "incoming": Tag(id=1, name=TagName("incoming")),
            "local": Tag(id=2, name=TagName("local")),
        }

        result = await processor._resolve_contact_tags(
            contact_data={"tags": [{"name": "incoming"}]},
            existing_reference_data='{"synced_tags": ["old_incoming"]}',
            existing_contact_tags=[Tag(id=2, name=TagName("local"))],
        )

        assert result is not None
        assert len(result) == 2
        names = [str(t.name) for t in result]
        assert "incoming" in names
        assert "local" in names

    @pytest.mark.asyncio
    async def test_resolve_contact_tags_removes_previously_synced_tags(
        self, processor: OutboxEventProcessor, mock_tag_repo: AsyncMock
    ):
        """Tags that were synced previously but are missing from inbound should be removed."""
        mock_tag_repo.find_by_names.return_value = {
            "new_incoming": Tag(id=1, name=TagName("new_incoming")),
            "local": Tag(id=2, name=TagName("local")),
        }

        # 'removed_incoming' is in reference_data so we know it came from the integration
        result = await processor._resolve_contact_tags(
            contact_data={"tags": [{"name": "new_incoming"}]},
            existing_reference_data='{"synced_tags": ["removed_incoming"]}',
            existing_contact_tags=[
                Tag(id=2, name=TagName("local")),
                Tag(id=3, name=TagName("removed_incoming")),
            ],
        )

        assert result is not None
        assert len(result) == 2
        names = [str(t.name) for t in result]
        assert "new_incoming" in names
        assert "local" in names
        assert "removed_incoming" not in names

    @pytest.mark.asyncio
    async def test_resolve_contact_tags_creates_missing_inbound_tags(
        self, processor: OutboxEventProcessor, mock_tag_repo: AsyncMock
    ):
        """Tags not found in repository are saved to DB before being assigned."""
        mock_tag_repo.find_by_names.return_value = {}  # Empty DB

        def mock_save(tag: Tag) -> Tag:
            return Tag(id=99, name=tag.name)

        mock_tag_repo.save.side_effect = mock_save

        result = await processor._resolve_contact_tags(
            contact_data={"tags": [{"name": "missing1"}, {"name": "missing2"}]},
            existing_reference_data=None,
            existing_contact_tags=[],
        )

        assert result is not None
        assert len(result) == 2
        assert result[0].id == 99
        assert str(result[0].name) == "missing1"
        assert result[1].id == 99
        assert str(result[1].name) == "missing2"
        assert mock_tag_repo.save.call_count == 2

    @pytest.mark.asyncio
    async def test_resolve_contact_tags_legacy_reference_data(
        self, processor: OutboxEventProcessor, mock_tag_repo: AsyncMock
    ):
        """Legacy reference_data without synced_tags defaults to preserving all existing tags currently to prevent data loss."""
        mock_tag_repo.find_by_names.return_value = {
            "incoming": Tag(id=1, name=TagName("incoming")),
            "existing_local": Tag(id=2, name=TagName("existing_local")),
            "existing_synced_but_unknown": Tag(
                id=3, name=TagName("existing_synced_but_unknown")
            ),
        }

        # Legacy data (e.g., just resource_name, no synced_tags)
        legacy_ref_data = '{"resource_name": "people/123"}'
        existing_tags = [
            Tag(id=2, name=TagName("existing_local")),
            Tag(id=3, name=TagName("existing_synced_but_unknown")),
        ]

        result = await processor._resolve_contact_tags(
            contact_data={"tags": [{"name": "incoming"}]},
            existing_reference_data=legacy_ref_data,
            existing_contact_tags=existing_tags,
        )

        assert result is not None
        assert len(result) == 3
        names = [str(t.name) for t in result]
        assert "incoming" in names
        assert "existing_local" in names
        assert "existing_synced_but_unknown" in names

    @pytest.mark.asyncio
    async def test_resolve_contact_tags_preserves_local_when_inbound_removes_synced(
        self, processor: OutboxEventProcessor, mock_tag_repo: AsyncMock
    ):
        """If inbound removes a synced tag, the synced tag is removed but local ones are kept."""
        mock_tag_repo.find_by_names.return_value = {
            "local_tag1": Tag(id=2, name=TagName("local_tag1")),
        }

        # The remote system removed 'synced_tag1'
        result = await processor._resolve_contact_tags(
            contact_data={"tags": []},  # Explicit empty list means remote removed tags
            existing_reference_data='{"synced_tags": ["synced_tag1"]}',
            existing_contact_tags=[
                Tag(id=2, name=TagName("local_tag1")),
                Tag(id=3, name=TagName("synced_tag1")),
            ],
        )

        assert result is not None
        assert len(result) == 1
        assert str(result[0].name) == "local_tag1"

    @pytest.mark.asyncio
    async def test_process_contact_created_passes_google_sync_provenance(
        self,
        processor: OutboxEventProcessor,
        contact_created_event: OutboxEvent,
        mock_contact_service: AsyncMock,
        mock_connection: AsyncConnection,
        mock_external_ref_service: AsyncMock,
        mock_sync_metadata_repo: AsyncMock,
    ):
        """Test that contact.created events pass changed_by='google_sync' to contact service."""
        expected_contact = Contact(
            id=123,
            first_name="John",
            last_name="Doe",
            methods=[
                ContactMethod(
                    id=1,
                    method_type=MethodType.EMAIL,
                    value="john.doe@example.com",
                    contact_id=123,
                    is_primary=True,
                )
            ],
        )
        mock_contact_service.create_contact.return_value = expected_contact
        mock_contact_service.get_contact_by_email.return_value = None

        await processor.process_event(contact_created_event)

        # Verify changed_by was passed as keyword argument
        call_kwargs = mock_contact_service.create_contact.call_args
        assert call_kwargs.kwargs.get("changed_by") == "google_sync"

    @pytest.mark.asyncio
    async def test_process_contact_updated_passes_google_sync_provenance(
        self,
        processor: OutboxEventProcessor,
        contact_updated_event: OutboxEvent,
        mock_contact_service: AsyncMock,
        mock_connection: AsyncConnection,
        mock_external_ref_service: AsyncMock,
        mock_sync_metadata_repo: AsyncMock,
    ):
        """Test that contact.updated events pass changed_by='google_sync' to contact service."""
        existing_contact = Contact(id=123, first_name="John", last_name="Doe", tags=[])
        mock_contact_service.find_contact_by_external_reference.return_value = (
            existing_contact
        )
        mock_contact_service.get_contact_by_id.return_value = existing_contact
        mock_contact_service.update_contact.return_value = existing_contact

        await processor.process_event(contact_updated_event)

        # Verify changed_by was passed as keyword argument
        call_kwargs = mock_contact_service.update_contact.call_args
        assert call_kwargs.kwargs.get("changed_by") == "google_sync"

    @pytest.mark.asyncio
    async def test_process_contact_created_normalizes_legacy_integration_source(
        self,
        processor: OutboxEventProcessor,
        mock_contact_service: AsyncMock,
        mock_connection: AsyncConnection,
        mock_external_ref_service: AsyncMock,
        mock_sync_metadata_repo: AsyncMock,
    ):
        """Test that contact.created with legacy 'google_contacts' normalizes to 'google'."""
        # Create event with legacy integration_source
        legacy_event = OutboxEvent(
            id=uuid4(),
            event_type="contact.created",
            event_data={
                "integration_source": "google_contacts",
                "external_id": "people/c999888777",
                "contact_data": {
                    "first_name": "Legacy",
                    "last_name": "Contact",
                    "middle_name": None,
                    "nick_name": None,
                    "company": None,
                    "job_title": None,
                    "is_favourite": False,
                    "methods": [],
                    "addresses": [],
                    "notes": [],
                    "tags": [],
                },
                "sync_timestamp": datetime.now(UTC).isoformat(),
                "sync_type": "created",
            },
            created_at=datetime.now(UTC),
            retry_count=0,
        )

        expected_contact = Contact(id=456, first_name="Legacy", last_name="Contact")
        mock_contact_service.create_contact.return_value = expected_contact
        mock_contact_service.get_contact_by_email.return_value = None

        result = await processor.process_event(legacy_event)

        assert result["status"] == "success"
        assert result["integration_source"] == "google"

        # Verify sync metadata was called with normalized 'google', not 'google_contacts'
        mock_sync_metadata_repo.upsert.assert_called_once()
        upsert_kwargs = mock_sync_metadata_repo.upsert.call_args[1]
        assert upsert_kwargs["integration_source"] == "google"

        # Verify external reference was called with normalized 'google'
        mock_external_ref_service.create_external_reference.assert_called_once()
        ref_kwargs = mock_external_ref_service.create_external_reference.call_args[1]
        assert ref_kwargs["external_system"] == "google"

        # Verify changed_by uses the normalized source
        call_kwargs = mock_contact_service.create_contact.call_args
        assert call_kwargs.kwargs.get("changed_by") == "google_sync"

    @pytest.mark.asyncio
    async def test_process_contact_updated_normalizes_legacy_integration_source(
        self,
        processor: OutboxEventProcessor,
        mock_contact_service: AsyncMock,
        mock_connection: AsyncConnection,
        mock_external_ref_service: AsyncMock,
        mock_sync_metadata_repo: AsyncMock,
    ):
        """Test that contact.updated with legacy 'google_contacts' normalizes to 'google'."""
        legacy_event = OutboxEvent(
            id=uuid4(),
            event_type="contact.updated",
            event_data={
                "integration_source": "google_contacts",
                "external_id": "people/c999888777",
                "contact_data": {
                    "first_name": "Updated",
                    "last_name": "Legacy",
                    "middle_name": None,
                    "nick_name": None,
                    "company": None,
                    "job_title": None,
                    "is_favourite": False,
                    "methods": [],
                    "addresses": [],
                    "notes": [],
                    "tags": [],
                },
                "sync_timestamp": datetime.now(UTC).isoformat(),
                "sync_type": "updated",
            },
            created_at=datetime.now(UTC),
            retry_count=0,
        )

        existing_contact = Contact(id=456, first_name="Legacy", last_name="Contact")
        mock_contact_service.find_contact_by_external_reference.return_value = (
            existing_contact
        )
        mock_contact_service.get_contact_by_id.return_value = existing_contact
        mock_contact_service.update_contact.return_value = existing_contact

        result = await processor.process_event(legacy_event)

        assert result["status"] == "success"
        assert result["integration_source"] == "google"

        # Verify lookup used normalized 'google'
        mock_contact_service.find_contact_by_external_reference.assert_called_once_with(
            integration_source="google",
            external_id="people/c999888777",
            transaction=mock_connection,
        )

        # Verify sync metadata was called with normalized 'google'
        mock_sync_metadata_repo.upsert.assert_called_once()
        upsert_kwargs = mock_sync_metadata_repo.upsert.call_args[1]
        assert upsert_kwargs["integration_source"] == "google"

        # Verify changed_by uses the normalized source
        call_kwargs = mock_contact_service.update_contact.call_args
        assert call_kwargs.kwargs.get("changed_by") == "google_sync"
