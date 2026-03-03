"""
Integration tests for contact outbox event processing.

Tests the complete flow from outbox events to contact creation/update in the database.
This verifies that the OutboxEventProcessor correctly processes contact.* events
from integration workers and creates/updates contacts in the database.
"""

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.events.outbox_repository import OutboxRepository


class TestContactOutboxProcessorIntegration:
    """Integration tests for contact outbox event processing."""

    @pytest.fixture
    def sample_contact_data(self) -> dict[str, Any]:
        """Create sample internal contact data for testing."""
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
                    "label": "work",
                    "is_primary": True,
                },
                {
                    "method_type": "phone",
                    "value": "+1-555-123-4567",
                    "label": "mobile",
                    "is_primary": True,
                },
            ],
            "addresses": [],
            "notes": [],
            "tags": [],
        }

    @pytest.mark.asyncio
    async def test_process_contact_created_event_creates_contact(
        self,
        clean_database: AsyncConnection,
        sample_contact_data: dict[str, Any],
    ):
        """Test that processing a contact.created event creates a contact in the database."""
        # Step 1: Create a contact.created outbox event
        # Note: We use raw SQL to match the actual database schema (Integer id, not UUID)
        now = datetime.utcnow()  # Use timezone-naive datetime to match migration schema
        event_data = {
            "integration_source": "google_contacts",
            "external_id": "people/c123456789",
            "contact_data": sample_contact_data,
            "sync_timestamp": datetime.now(UTC).isoformat(),
            "sync_type": "created",
            "etag": "etag123",
        }

        # Insert the event using the same pattern as OutboxEventPublisher
        await clean_database.execute(
            text("""
                INSERT INTO outbox_events
                (event_id, event_type, aggregate_id, event_data, occurred_at, retry_count, created_at)
                VALUES (:event_id, :event_type, :aggregate_id, :event_data, :occurred_at, :retry_count, :created_at)
            """),
            {
                "event_id": f"test-event-{uuid4()}",
                "event_type": "contact.created",
                "aggregate_id": 0,  # Not used for contact sync events
                "event_data": json.dumps(event_data),
                "occurred_at": now,
                "retry_count": 0,
                "created_at": now,
            },
        )

        # Verify event is in the database
        repository = OutboxRepository(clean_database)
        unprocessed_events = await repository.get_unprocessed_events()
        assert len(unprocessed_events) == 1
        assert unprocessed_events[0].event_type == "contact.created"

        # Step 2: Process the event using OutboxProcessor
        from app.infrastructure.events.outbox_processor import OutboxProcessor

        processor = OutboxProcessor()

        # Process events manually using the test database connection
        from app.infrastructure.search.search_indexer import SearchIndexer

        search_indexer = SearchIndexer(db_connection=clean_database)

        # Get unprocessed events
        events = await repository.get_unprocessed_events(limit=50)

        # Process each event
        for event in events:
            try:
                await processor._process_single_event(event, repository, search_indexer)
            except Exception:
                # Increment retry count if under max retries
                if event.retry_count < processor.max_retries:
                    await repository.increment_retry_count(event.event_id)
                raise

        # Step 3: Verify the contact was created in the database
        result = await clean_database.execute(
            text("""
                SELECT id, first_name, last_name
                FROM contacts
                WHERE first_name = :first_name AND last_name = :last_name
            """),
            {"first_name": "John", "last_name": "Doe"},
        )
        contact_row = result.fetchone()

        assert contact_row is not None, "Contact should be created in database"
        assert contact_row[1] == "John"  # first_name
        assert contact_row[2] == "Doe"  # last_name

        # Step 4: Verify contact methods (email and phone) were created
        contact_id = contact_row[0]
        result = await clean_database.execute(
            text("""
                SELECT method_type, value
                FROM contact_methods
                WHERE contact_id = :contact_id
                ORDER BY method_type
            """),
            {"contact_id": contact_id},
        )
        methods = result.fetchall()

        assert len(methods) == 2, "Should have email and phone methods"
        # Methods are ordered by method_type (email comes before phone alphabetically)
        assert methods[0][0] == "email"
        assert methods[0][1] == "john.doe@example.com"
        assert methods[1][0] == "phone"
        assert methods[1][1] == "+1-555-123-4567"

        # Step 5: Verify external reference was created
        result = await clean_database.execute(
            text("""
                SELECT external_system, external_entity_id
                FROM external_references
                WHERE internal_entity_type = 'contact' AND internal_entity_id = :contact_id
            """),
            {"contact_id": contact_id},
        )
        ref_row = result.fetchone()

        assert ref_row is not None, "External reference should be created"
        assert ref_row[0] == "google_contacts"
        assert ref_row[1] == "people/c123456789"

        # Step 6: Verify the original contact.created event was marked as processed
        # Note: The contact creation may generate additional domain events (ContactMethodAdded, etc.)
        # so we check specifically for the contact.created event
        all_events = await clean_database.execute(
            text("""
                SELECT event_type, processed_at
                FROM outbox_events
                WHERE event_type = 'contact.created'
            """)
        )
        created_event = all_events.fetchone()

        assert created_event is not None, "contact.created event should exist"
        assert created_event[1] is not None, (
            "contact.created event should be marked as processed"
        )
