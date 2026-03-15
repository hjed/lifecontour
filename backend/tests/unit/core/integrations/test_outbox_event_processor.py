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
from core_shared.models.contacts.entities import Contact, ContactMethod, MethodType
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
    def processor(
        self, mock_contact_service: AsyncMock, mock_connection: AsyncConnection
    ) -> OutboxEventProcessor:
        """Create OutboxEventProcessor instance."""
        return OutboxEventProcessor(
            contact_service=mock_contact_service, connection=mock_connection
        )

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
            processed_at=None,
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
            processed_at=None,
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
            processed_at=None,
            retry_count=0,
        )

    @pytest.mark.asyncio
    async def test_process_contact_created_event(
        self,
        processor: OutboxEventProcessor,
        contact_created_event: OutboxEvent,
        mock_contact_service: AsyncMock,
        mock_connection: AsyncConnection,
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

        # Mock external reference service to return None (no existing reference)
        mock_external_ref_service = AsyncMock()
        mock_external_ref_service.find_by_external_id.return_value = None
        mock_external_ref_service.create_external_reference.return_value = AsyncMock()

        mock_sync_metadata_repo = AsyncMock()
        mock_sync_metadata_repo.upsert.return_value = None

        with (
            patch.object(
                processor, "external_reference_service", mock_external_ref_service
            ),
            patch.object(processor, "sync_metadata_repo", mock_sync_metadata_repo),
        ):
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

        # Mock external reference service
        mock_external_ref_service = AsyncMock()
        mock_external_ref_service.create_external_reference.return_value = AsyncMock()

        # Mock sync metadata repository
        mock_sync_metadata_repo = AsyncMock()
        mock_sync_metadata_repo.find_and_lock.return_value = (
            None  # No existing sync metadata
        )
        mock_sync_metadata_repo.should_sync = MagicMock(
            return_value=True
        )  # Synchronous method
        mock_sync_metadata_repo.upsert.return_value = AsyncMock()

        with (
            patch.object(
                processor, "external_reference_service", mock_external_ref_service
            ),
            patch.object(processor, "sync_metadata_repo", mock_sync_metadata_repo),
        ):
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

    @pytest.mark.asyncio
    async def test_process_contact_updated_updates_reference_data(
        self,
        processor: OutboxEventProcessor,
        contact_updated_event: OutboxEvent,
        mock_contact_service: AsyncMock,
        mock_connection: AsyncConnection,
    ):
        """Test that updating a contact also parses and updates existing reference_data JSON correctly."""
        import json

        from core_shared.models.external_reference import ExternalReference

        # We will add some fake "tags" to the event payload to test the synced_tags update
        contact_updated_event.event_data["contact_data"]["tags"] = [{"name": "VIP"}]

        existing_contact = Contact(id=123, first_name="John", last_name="Doe")
        mock_contact_service.find_contact_by_external_reference.return_value = (
            existing_contact
        )
        mock_contact_service.update_contact.return_value = existing_contact

        mock_external_ref_service = AsyncMock()
        mock_external_ref_service.find_external_reference.return_value = (
            ExternalReference(
                id=99,
                internal_entity_type="contact",
                internal_entity_id=123,
                external_system="google",
                external_entity_type="person",
                external_entity_id="people/c123456789",
                reference_data=json.dumps({"old_key": "old_value"}),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )

        mock_sync_metadata_repo = AsyncMock()
        mock_sync_metadata_repo.find_and_lock.return_value = None
        mock_sync_metadata_repo.should_sync = MagicMock(return_value=True)
        mock_sync_metadata_repo.upsert.return_value = AsyncMock()

        processor.tag_repo = AsyncMock()
        processor.tag_repo.find_by_names.return_value = {}

        with (
            patch.object(
                processor, "external_reference_service", mock_external_ref_service
            ),
            patch.object(processor, "sync_metadata_repo", mock_sync_metadata_repo),
        ):
            await processor.process_event(contact_updated_event)

        mock_external_ref_service.update_external_reference.assert_called_once()
        call_kwargs = mock_external_ref_service.update_external_reference.call_args[1]
        assert call_kwargs["reference_id"] == 99

        # Verify JSON
        updated_ref_data = json.loads(call_kwargs["reference_data"])
        assert updated_ref_data["old_key"] == "old_value"
        assert updated_ref_data["synced_tags"] == ["VIP"]

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
            processed_at=None,
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

        # Mock external reference service
        mock_external_ref_service = AsyncMock()
        mock_external_ref_service.find_by_external_id.return_value = None

        with patch.object(
            processor, "external_reference_service", mock_external_ref_service
        ):
            # Should raise OutboxEventProcessingError
            with pytest.raises(OutboxEventProcessingError) as exc_info:
                await processor.process_event(contact_created_event)

        assert "Failed to process contact.created event" in str(exc_info.value)
        assert "Database error" in str(exc_info.value)

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

        # Mock sync metadata repository
        mock_sync_metadata_repo = AsyncMock()
        mock_sync_metadata_repo.find_and_lock.return_value = None
        mock_sync_metadata_repo.should_sync = MagicMock(
            return_value=True
        )  # Synchronous method

        with patch.object(processor, "sync_metadata_repo", mock_sync_metadata_repo):
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
        invalid_event = OutboxEvent(
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
            processed_at=None,
            retry_count=0,
        )

        # Mock external reference service
        mock_external_ref_service = AsyncMock()
        mock_external_ref_service.find_by_external_id.return_value = None

        with patch.object(
            processor, "external_reference_service", mock_external_ref_service
        ):
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

        mock_sync_metadata_repo = AsyncMock()
        mock_sync_metadata_repo.find_and_lock.return_value = None
        mock_sync_metadata_repo.should_sync = MagicMock(return_value=True)

        with patch.object(processor, "sync_metadata_repo", mock_sync_metadata_repo):
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
        invalid_event = OutboxEvent(
            id=uuid4(),
            event_type="contact.created",
            event_data={
                "integration_source": "google",
                "external_id": "people/invalid",
                "contact_data": {"invalid": "data"},
                "sync_timestamp": datetime.now(UTC).isoformat(),
                "sync_type": "created",
            },
            created_at=datetime.now(UTC),
            processed_at=None,
            retry_count=0,
        )

        mock_external_ref_service = AsyncMock()
        mock_external_ref_service.find_by_external_id.return_value = None

        with (
            patch.object(
                processor, "external_reference_service", mock_external_ref_service
            ),
            patch(
                "app.core.integrations.outbox_event_processor.logger.error"
            ) as mock_log_error,
        ):
            with pytest.raises(PermanentOutboxEventProcessingError):
                await processor.process_event(invalid_event)

        mock_log_error.assert_called_once()
        assert mock_log_error.call_args.args[0] == (
            "Outbox event has permanent invalid payload"
        )
        mock_contact_service.create_contact.assert_not_called()
