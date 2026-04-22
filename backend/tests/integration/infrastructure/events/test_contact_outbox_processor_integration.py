"""
Integration tests for contact outbox event processing.

Tests the complete flow from outbox events to contact creation/update in the database.
This verifies that the OutboxEventProcessor correctly processes contact.* events
from integration workers and creates/updates contacts in the database.
"""

import copy
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.events.outbox_repository import OutboxRepository

INTEGRATION_SOURCE = "google"
MAX_RETRY_COUNT = 3


class _NoCommitConnectionProxy:
    """Proxy test connection that suppresses batch commits inside the savepoint."""

    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection

    async def commit(self) -> None:
        """Keep writes inside the test savepoint for rollback."""

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


class TestContactOutboxProcessorIntegration:
    """Integration tests for contact outbox event processing."""

    def _naive_utc_now(self) -> datetime:
        """Create a timezone-naive UTC datetime for legacy timestamp columns."""
        return datetime.now(UTC).replace(tzinfo=None)

    def _build_invalid_contact_data(self, last_name: str) -> dict[str, Any]:
        """Build malformed contact payloads missing the required first_name."""
        return {
            "last_name": last_name,
            "methods": [],
            "addresses": [],
            "notes": [],
            "tags": [],
        }

    async def _insert_contact_sync_event(
        self,
        connection: AsyncConnection,
        *,
        event_type: str,
        contact_data: dict[str, Any],
        external_id: str,
        sync_type: str,
    ) -> str:
        """Insert a contact sync outbox event for integration testing."""
        now = self._naive_utc_now()
        event_id = f"test-event-{uuid4()}"
        event_data = {
            "integration_source": INTEGRATION_SOURCE,
            "external_id": external_id,
            "contact_data": contact_data,
            "sync_timestamp": datetime.now(UTC).isoformat(),
            "sync_type": sync_type,
            "etag": f"etag-{uuid4()}",
        }

        await connection.execute(
            text("""
                INSERT INTO outbox_events
                (event_id, event_type, aggregate_id, event_data, occurred_at, retry_count, created_at)
                VALUES (:event_id, :event_type, :aggregate_id, :event_data, :occurred_at, :retry_count, :created_at)
            """),
            {
                "event_id": event_id,
                "event_type": event_type,
                "aggregate_id": 0,
                "event_data": json.dumps(event_data),
                "occurred_at": now,
                "retry_count": 0,
                "created_at": now,
            },
        )

        return event_id

    async def _run_outbox_processor(self, connection: AsyncConnection) -> None:
        """Run the real outbox processor against the test savepoint connection."""
        from app.infrastructure.events.outbox_processor import OutboxProcessor

        proxied_connection = _NoCommitConnectionProxy(connection)

        @asynccontextmanager
        async def mock_begin():
            yield proxied_connection

        class _TestEngine:
            def begin(self):
                return mock_begin()

        from unittest.mock import AsyncMock

        with patch(
            "app.infrastructure.events.outbox_processor.get_async_database_engine",
            return_value=_TestEngine(),
        ):
            await OutboxProcessor(AsyncMock()).process_events()

    async def _fetch_contact_by_name(
        self,
        connection: AsyncConnection,
        *,
        first_name: str,
        last_name: str,
    ) -> Any:
        """Fetch a contact row by first and last name."""
        result = await connection.execute(
            text("""
                SELECT id, first_name, last_name
                FROM contacts
                WHERE first_name = :first_name AND last_name = :last_name
            """),
            {"first_name": first_name, "last_name": last_name},
        )
        return result.fetchone()

    async def _fetch_contact_by_id(
        self,
        connection: AsyncConnection,
        *,
        contact_id: int,
    ) -> Any:
        """Fetch a contact row by id."""
        result = await connection.execute(
            text("""
                SELECT id, first_name, last_name
                FROM contacts
                WHERE id = :contact_id
            """),
            {"contact_id": contact_id},
        )
        return result.fetchone()

    async def _fetch_contact_methods(
        self,
        connection: AsyncConnection,
        *,
        contact_id: int,
    ) -> list[Any]:
        """Fetch contact methods for the given contact."""
        result = await connection.execute(
            text("""
                SELECT method_type, value
                FROM contact_methods
                WHERE contact_id = :contact_id
                ORDER BY method_type
            """),
            {"contact_id": contact_id},
        )
        return list(result.fetchall())

    async def _count_contacts(self, connection: AsyncConnection) -> int:
        """Count contacts in the database."""
        result = await connection.execute(text("SELECT COUNT(*) FROM contacts"))
        return int(result.scalar_one())

    async def _fetch_outbox_event_state(
        self,
        connection: AsyncConnection,
        *,
        event_id: str,
    ) -> Any:
        """Fetch retry and processed state for a specific outbox event."""
        result = await connection.execute(
            text("""
                SELECT retry_count, processed_at
                FROM outbox_events
                WHERE event_id = :event_id
            """),
            {"event_id": event_id},
        )
        return result.fetchone()

    async def _assert_external_reference(
        self,
        connection: AsyncConnection,
        *,
        contact_id: int,
        external_id: str,
    ) -> None:
        """Assert that the contact has the expected Google external reference."""
        result = await connection.execute(
            text("""
                SELECT external_system, external_entity_id
                FROM external_references
                WHERE internal_entity_type = 'contact' AND internal_entity_id = :contact_id
            """),
            {"contact_id": contact_id},
        )
        ref_row = result.fetchone()

        assert ref_row is not None, "External reference should be created"
        assert ref_row == (INTEGRATION_SOURCE, external_id)

    async def _assert_no_external_reference(
        self,
        connection: AsyncConnection,
        *,
        external_id: str,
    ) -> None:
        """Assert that no Google external reference exists for the external id."""
        result = await connection.execute(
            text("""
                SELECT COUNT(*)
                FROM external_references
                WHERE external_system = :external_system
                AND external_entity_id = :external_id
            """),
            {"external_system": INTEGRATION_SOURCE, "external_id": external_id},
        )
        assert result.scalar_one() == 0

    async def _assert_event_processed(
        self,
        connection: AsyncConnection,
        *,
        event_type: str,
    ) -> None:
        """Assert that the requested outbox event type was marked processed."""
        result = await connection.execute(
            text("""
                SELECT processed_at
                FROM outbox_events
                WHERE event_type = :event_type
            """),
            {"event_type": event_type},
        )
        processed_at = result.scalar()

        assert processed_at is not None, (
            f"{event_type} event should be marked as processed"
        )

    async def _assert_event_failed_terminally(
        self,
        connection: AsyncConnection,
        event_id: str,
    ) -> None:
        """Assert that an event reached terminal failure state."""
        repository = OutboxRepository(connection)
        remaining_events = await repository.get_unprocessed_events(
            limit=10, max_retry_count=MAX_RETRY_COUNT
        )
        failed_events = await repository.get_failed_events(max_retries=MAX_RETRY_COUNT)

        result = await connection.execute(
            text("""
                SELECT retry_count, processed_at
                FROM outbox_events
                WHERE event_id = :event_id
            """),
            {"event_id": event_id},
        )
        event_row = result.fetchone()

        assert event_row is not None
        assert event_row[0] == MAX_RETRY_COUNT
        assert event_row[1] is None
        assert all(event.event_id != event_id for event in remaining_events)
        assert any(event.event_id == event_id for event in failed_events)

    async def _insert_existing_contact_reference(
        self,
        connection: AsyncConnection,
        *,
        contact_id: int,
        external_id: str,
        first_name: str,
        last_name: str,
    ) -> None:
        """Insert an existing contact and its Google external reference."""
        await self._insert_contact(
            connection,
            contact_id=contact_id,
            first_name=first_name,
            last_name=last_name,
        )
        await connection.execute(
            text("""
                INSERT INTO external_references
                (internal_entity_type, internal_entity_id, external_system,
                 external_entity_type, external_entity_id, reference_data)
                VALUES (:internal_entity_type, :internal_entity_id, :external_system,
                        :external_entity_type, :external_entity_id, :reference_data)
            """),
            {
                "internal_entity_type": "contact",
                "internal_entity_id": contact_id,
                "external_system": INTEGRATION_SOURCE,
                "external_entity_type": "person",
                "external_entity_id": external_id,
                "reference_data": "{}",
            },
        )

    async def _insert_contact(
        self,
        connection: AsyncConnection,
        *,
        contact_id: int,
        first_name: str,
        last_name: str,
    ) -> None:
        """Insert a contact row for integration testing."""
        await connection.execute(
            text("""
                INSERT INTO contacts (id, first_name, last_name, created_at, updated_at)
                VALUES (:id, :first_name, :last_name, NOW(), NOW())
            """),
            {"id": contact_id, "first_name": first_name, "last_name": last_name},
        )

    async def _insert_contact_method(
        self,
        connection: AsyncConnection,
        *,
        contact_id: int,
        method_type: str,
        value: str,
        label: str | None = None,
        is_primary: bool = False,
    ) -> None:
        """Insert a contact method row for integration testing."""
        await connection.execute(
            text("""
                INSERT INTO contact_methods
                (contact_id, method_type, value, label, is_primary, created_at, updated_at)
                VALUES
                (:contact_id, :method_type, :value, :label, :is_primary, NOW(), NOW())
            """),
            {
                "contact_id": contact_id,
                "method_type": method_type,
                "value": value,
                "label": label,
                "is_primary": is_primary,
            },
        )

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
        external_id = "people/c123456789"
        await self._insert_contact_sync_event(
            clean_database,
            event_type="contact.created",
            contact_data=sample_contact_data,
            external_id=external_id,
            sync_type="created",
        )

        await self._run_outbox_processor(clean_database)

        contact_row = await self._fetch_contact_by_name(
            clean_database,
            first_name="John",
            last_name="Doe",
        )

        assert contact_row is not None, "Contact should be created in database"
        assert contact_row[1] == "John"  # first_name
        assert contact_row[2] == "Doe"  # last_name

        contact_id = contact_row[0]
        methods = await self._fetch_contact_methods(
            clean_database,
            contact_id=contact_id,
        )

        assert len(methods) == 2, "Should have email and phone methods"
        assert methods[0][0] == "email"
        assert methods[0][1] == "john.doe@example.com"
        assert methods[1][0] == "phone"
        assert methods[1][1] == "+1-555-123-4567"

        await self._assert_external_reference(
            clean_database,
            contact_id=contact_id,
            external_id=external_id,
        )
        await self._assert_event_processed(
            clean_database,
            event_type="contact.created",
        )

    @pytest.mark.asyncio
    async def test_process_contact_created_event_deduplicates_duplicate_email_methods(
        self,
        clean_database: AsyncConnection,
        sample_contact_data: dict[str, Any],
    ):
        """Duplicate email methods in one inbound contact should not fail creation."""
        external_id = f"people/duplicate-email-created-{uuid4()}"
        contact_data = copy.deepcopy(sample_contact_data)
        contact_data["methods"] = [
            {
                "method_type": "email",
                "value": "john.doe@example.com",
                "label": "work",
                "is_primary": False,
            },
            {
                "method_type": "email",
                "value": "john.doe@example.com",
                "label": "home",
                "is_primary": True,
            },
            {
                "method_type": "phone",
                "value": "+1-555-123-4567",
                "label": "mobile",
                "is_primary": True,
            },
        ]

        await self._insert_contact_sync_event(
            clean_database,
            event_type="contact.created",
            contact_data=contact_data,
            external_id=external_id,
            sync_type="created",
        )

        await self._run_outbox_processor(clean_database)

        contact_row = await self._fetch_contact_by_name(
            clean_database,
            first_name="John",
            last_name="Doe",
        )

        assert contact_row is not None

        methods = await self._fetch_contact_methods(
            clean_database,
            contact_id=contact_row[0],
        )
        email_methods = [method for method in methods if method[0] == "email"]
        phone_methods = [method for method in methods if method[0] == "phone"]

        assert len(email_methods) == 1
        assert email_methods[0][1] == "john.doe@example.com"
        assert len(phone_methods) == 1

        await self._assert_external_reference(
            clean_database,
            contact_id=contact_row[0],
            external_id=external_id,
        )
        await self._assert_event_processed(
            clean_database,
            event_type="contact.created",
        )

    @pytest.mark.asyncio
    async def test_process_contact_created_event_matches_existing_local_contact_by_email(
        self,
        clean_database: AsyncConnection,
        sample_contact_data: dict[str, Any],
    ):
        """contact.created should reuse an existing local contact matched by email."""
        contact_id = 45678
        external_id = f"people/match-existing-by-email-{uuid4()}"

        await self._insert_contact(
            clean_database,
            contact_id=contact_id,
            first_name="Local",
            last_name="Only",
        )
        await self._insert_contact_method(
            clean_database,
            contact_id=contact_id,
            method_type="email",
            value="  JOHN.DOE@EXAMPLE.COM  ",
            label="personal",
            is_primary=True,
        )

        await self._insert_contact_sync_event(
            clean_database,
            event_type="contact.created",
            contact_data=copy.deepcopy(sample_contact_data),
            external_id=external_id,
            sync_type="created",
        )

        await self._run_outbox_processor(clean_database)

        assert await self._count_contacts(clean_database) == 1

        matched_contact = await self._fetch_contact_by_id(
            clean_database,
            contact_id=contact_id,
        )
        assert matched_contact is not None
        assert matched_contact[1] == "John"
        assert matched_contact[2] == "Doe"

        contact_by_name = await self._fetch_contact_by_name(
            clean_database,
            first_name="John",
            last_name="Doe",
        )
        assert contact_by_name is not None
        assert contact_by_name[0] == contact_id

        methods = await self._fetch_contact_methods(
            clean_database,
            contact_id=contact_id,
        )
        email_methods = [method for method in methods if method[0] == "email"]
        phone_methods = [method for method in methods if method[0] == "phone"]

        assert len(email_methods) == 1
        assert email_methods[0][1] == "john.doe@example.com"
        assert len(phone_methods) == 1
        assert phone_methods[0][1] == "+1-555-123-4567"

        await self._assert_external_reference(
            clean_database,
            contact_id=contact_id,
            external_id=external_id,
        )
        await self._assert_event_processed(
            clean_database,
            event_type="contact.created",
        )

    @pytest.mark.asyncio
    async def test_process_contact_created_event_retries_when_multiple_local_contacts_match_inbound_emails(
        self,
        clean_database: AsyncConnection,
        sample_contact_data: dict[str, Any],
    ):
        """Ambiguous email matches should fail safely without linking the wrong contact."""
        first_contact_id = 45679
        second_contact_id = 45680
        external_id = f"people/ambiguous-email-match-{uuid4()}"

        await self._insert_contact(
            clean_database,
            contact_id=first_contact_id,
            first_name="Local",
            last_name="One",
        )
        await self._insert_contact_method(
            clean_database,
            contact_id=first_contact_id,
            method_type="email",
            value="john.doe@example.com",
            label="personal",
            is_primary=True,
        )

        await self._insert_contact(
            clean_database,
            contact_id=second_contact_id,
            first_name="Local",
            last_name="Two",
        )
        await self._insert_contact_method(
            clean_database,
            contact_id=second_contact_id,
            method_type="email",
            value="jane.smith@example.com",
            label="personal",
            is_primary=True,
        )

        contact_data = copy.deepcopy(sample_contact_data)
        contact_data["methods"] = [
            {
                "method_type": "email",
                "value": "john.doe@example.com",
                "label": "work",
                "is_primary": True,
            },
            {
                "method_type": "email",
                "value": "jane.smith@example.com",
                "label": "home",
                "is_primary": False,
            },
            {
                "method_type": "phone",
                "value": "+1-555-123-4567",
                "label": "mobile",
                "is_primary": True,
            },
        ]

        event_id = await self._insert_contact_sync_event(
            clean_database,
            event_type="contact.created",
            contact_data=contact_data,
            external_id=external_id,
            sync_type="created",
        )

        await self._run_outbox_processor(clean_database)

        assert await self._count_contacts(clean_database) == 2

        first_contact = await self._fetch_contact_by_id(
            clean_database,
            contact_id=first_contact_id,
        )
        second_contact = await self._fetch_contact_by_id(
            clean_database,
            contact_id=second_contact_id,
        )
        assert first_contact is not None
        assert second_contact is not None
        assert first_contact[1:] == ("Local", "One")
        assert second_contact[1:] == ("Local", "Two")

        event_state = await self._fetch_outbox_event_state(
            clean_database,
            event_id=event_id,
        )
        assert event_state is not None
        assert event_state[0] == 1
        assert event_state[1] is None

        await self._assert_no_external_reference(
            clean_database,
            external_id=external_id,
        )

    @pytest.mark.asyncio
    async def test_process_contact_updated_event_deduplicates_duplicate_email_methods(
        self,
        clean_database: AsyncConnection,
        sample_contact_data: dict[str, Any],
    ):
        """Duplicate email methods in one inbound update should not fail sync."""
        contact_id = 56789
        external_id = f"people/duplicate-email-updated-{uuid4()}"

        await self._insert_existing_contact_reference(
            clean_database,
            contact_id=contact_id,
            external_id=external_id,
            first_name="Existing",
            last_name="Contact",
        )
        await self._insert_contact_method(
            clean_database,
            contact_id=contact_id,
            method_type="email",
            value="legacy@example.com",
            label="legacy",
            is_primary=True,
        )

        contact_data = copy.deepcopy(sample_contact_data)
        contact_data["first_name"] = "Updated"
        contact_data["last_name"] = "Name"
        contact_data["methods"] = [
            {
                "method_type": "email",
                "value": "updated@example.com",
                "label": "work",
                "is_primary": False,
            },
            {
                "method_type": "email",
                "value": "updated@example.com",
                "label": "home",
                "is_primary": True,
            },
            {
                "method_type": "phone",
                "value": "+1-555-987-6543",
                "label": "mobile",
                "is_primary": True,
            },
        ]

        await self._insert_contact_sync_event(
            clean_database,
            event_type="contact.updated",
            contact_data=contact_data,
            external_id=external_id,
            sync_type="updated",
        )

        await self._run_outbox_processor(clean_database)

        updated_contact = await self._fetch_contact_by_id(
            clean_database,
            contact_id=contact_id,
        )
        assert updated_contact is not None
        assert updated_contact[1] == "Updated"
        assert updated_contact[2] == "Name"

        methods = await self._fetch_contact_methods(
            clean_database,
            contact_id=contact_id,
        )
        email_methods = [method for method in methods if method[0] == "email"]
        phone_methods = [method for method in methods if method[0] == "phone"]

        assert len(email_methods) == 1
        assert email_methods[0][1] == "updated@example.com"
        assert len(phone_methods) == 1
        assert phone_methods[0][1] == "+1-555-987-6543"

        await self._assert_external_reference(
            clean_database,
            contact_id=contact_id,
            external_id=external_id,
        )
        await self._assert_event_processed(
            clean_database,
            event_type="contact.updated",
        )

    @pytest.mark.asyncio
    async def test_process_events_persists_retry_count_after_db_error_and_continues_batch(
        self,
        clean_database: AsyncConnection,
        sample_contact_data: dict[str, Any],
    ):
        """A DB error in one event should not abort retry persistence or later events."""
        from app.infrastructure.events.outbox_processor import OutboxProcessor

        failing_external_id = f"people/failing-{uuid4()}"
        succeeding_external_id = f"people/succeeding-{uuid4()}"

        failing_event_id = await self._insert_contact_sync_event(
            clean_database,
            event_type="contact.created",
            contact_data=sample_contact_data,
            external_id=failing_external_id,
            sync_type="created",
        )
        await self._insert_contact_sync_event(
            clean_database,
            event_type="contact.created",
            contact_data={
                **copy.deepcopy(sample_contact_data),
                "first_name": "Jane",
                "last_name": "Smith",
                "methods": [
                    {
                        "method_type": "email",
                        "value": "jane.smith@example.com",
                        "label": "work",
                        "is_primary": True,
                    }
                ],
            },
            external_id=succeeding_external_id,
            sync_type="created",
        )

        original_process_contact_event = OutboxProcessor._process_contact_event

        async def fail_first_contact_event(
            self: OutboxProcessor, event: Any, connection: Any
        ) -> None:
            if event.event_id == failing_event_id:
                await connection.execute(text("SELECT * FROM definitely_missing_table"))
            await original_process_contact_event(self, event, connection)

        with patch.object(
            OutboxProcessor,
            "_process_contact_event",
            new=fail_first_contact_event,
        ):
            await self._run_outbox_processor(clean_database)

        failing_event_state = await self._fetch_outbox_event_state(
            clean_database,
            event_id=failing_event_id,
        )
        assert failing_event_state is not None
        assert failing_event_state[0] == 1
        assert failing_event_state[1] is None

        succeeding_contact = await self._fetch_contact_by_name(
            clean_database,
            first_name="Jane",
            last_name="Smith",
        )
        assert succeeding_contact is not None

        await self._assert_external_reference(
            clean_database,
            contact_id=succeeding_contact[0],
            external_id=succeeding_external_id,
        )

    @pytest.mark.asyncio
    async def test_process_events_marks_invalid_contact_created_event_as_failed(
        self,
        clean_database: AsyncConnection,
    ):
        """Invalid contact.created payloads should be terminally failed and skipped."""
        external_id = f"people/invalid-created-{uuid4()}"
        event_id = await self._insert_contact_sync_event(
            clean_database,
            event_type="contact.created",
            contact_data=self._build_invalid_contact_data("Broken"),
            external_id=external_id,
            sync_type="created",
        )

        await self._run_outbox_processor(clean_database)
        await self._assert_event_failed_terminally(clean_database, event_id)

        await self._assert_no_external_reference(
            clean_database,
            external_id=external_id,
        )

    @pytest.mark.asyncio
    async def test_process_events_marks_contact_created_with_non_list_methods_as_failed(
        self,
        clean_database: AsyncConnection,
    ):
        """Malformed contact.created methods should stay invalid and fail terminally."""
        external_id = f"people/invalid-created-methods-{uuid4()}"
        event_id = await self._insert_contact_sync_event(
            clean_database,
            event_type="contact.created",
            contact_data={
                "first_name": "Broken",
                "last_name": "Methods",
                "methods": "john.doe@example.com",
                "addresses": [],
                "notes": [],
                "tags": [],
            },
            external_id=external_id,
            sync_type="created",
        )

        await self._run_outbox_processor(clean_database)
        await self._assert_event_failed_terminally(clean_database, event_id)

        await self._assert_no_external_reference(
            clean_database,
            external_id=external_id,
        )

    @pytest.mark.asyncio
    async def test_process_events_marks_invalid_contact_updated_event_as_failed(
        self,
        clean_database: AsyncConnection,
    ):
        """Invalid contact.updated payloads should fail permanently without mutating contacts."""
        contact_id = 98765
        external_id = f"people/invalid-updated-{uuid4()}"

        await self._insert_existing_contact_reference(
            clean_database,
            contact_id=contact_id,
            external_id=external_id,
            first_name="Existing",
            last_name="Contact",
        )

        event_id = await self._insert_contact_sync_event(
            clean_database,
            event_type="contact.updated",
            contact_data=self._build_invalid_contact_data("Mutated"),
            external_id=external_id,
            sync_type="updated",
        )

        await self._run_outbox_processor(clean_database)
        await self._assert_event_failed_terminally(clean_database, event_id)

        contact_row = await self._fetch_contact_by_id(
            clean_database,
            contact_id=contact_id,
        )

        assert contact_row is not None
        assert contact_row[1:] == ("Existing", "Contact")

    @pytest.mark.asyncio
    async def test_process_events_marks_contact_updated_with_non_list_methods_as_failed(
        self,
        clean_database: AsyncConnection,
    ):
        """Malformed contact.updated methods should stay invalid and fail terminally."""
        contact_id = 98766
        external_id = f"people/invalid-updated-methods-{uuid4()}"

        await self._insert_existing_contact_reference(
            clean_database,
            contact_id=contact_id,
            external_id=external_id,
            first_name="Existing",
            last_name="Contact",
        )

        event_id = await self._insert_contact_sync_event(
            clean_database,
            event_type="contact.updated",
            contact_data={
                "first_name": "Mutated",
                "last_name": "Contact",
                "methods": "updated@example.com",
                "addresses": [],
                "notes": [],
                "tags": [],
            },
            external_id=external_id,
            sync_type="updated",
        )

        await self._run_outbox_processor(clean_database)
        await self._assert_event_failed_terminally(clean_database, event_id)

        contact_row = await self._fetch_contact_by_id(
            clean_database,
            contact_id=contact_id,
        )

        assert contact_row is not None
        assert contact_row[1:] == ("Existing", "Contact")

    @pytest.mark.asyncio
    async def test_process_legacy_google_contacts_event_normalizes_to_google(
        self,
        clean_database: AsyncConnection,
        sample_contact_data: dict[str, Any],
    ):
        """Events with legacy 'google_contacts' integration_source should be normalized to 'google'.

        Migration 0029 renamed google_contacts → google in the sync_metadata
        check constraint but did not update existing outbox events. The processor
        must normalize the legacy value to avoid a CheckViolationError.
        """
        external_id = f"people/legacy-source-{uuid4()}"

        # Insert an outbox event with the LEGACY integration source
        now = self._naive_utc_now()
        event_id = f"test-event-{uuid4()}"
        event_data = {
            "integration_source": "google_contacts",  # <-- legacy value
            "external_id": external_id,
            "contact_data": sample_contact_data,
            "sync_timestamp": datetime.now(UTC).isoformat(),
            "sync_type": "created",
            "etag": f"etag-{uuid4()}",
        }

        await clean_database.execute(
            text("""
                INSERT INTO outbox_events
                (event_id, event_type, aggregate_id, event_data, occurred_at, retry_count, created_at)
                VALUES (:event_id, :event_type, :aggregate_id, :event_data, :occurred_at, :retry_count, :created_at)
            """),
            {
                "event_id": event_id,
                "event_type": "contact.created",
                "aggregate_id": 0,
                "event_data": json.dumps(event_data),
                "occurred_at": now,
                "retry_count": 0,
                "created_at": now,
            },
        )

        # Run the outbox processor — this must NOT raise a CheckViolationError
        await self._run_outbox_processor(clean_database)

        # Verify the contact was created
        contact_row = await self._fetch_contact_by_name(
            clean_database,
            first_name="John",
            last_name="Doe",
        )
        assert contact_row is not None, (
            "Contact should be created despite legacy source"
        )

        contact_id = contact_row[0]

        # Verify the external reference was created with the normalized value
        result = await clean_database.execute(
            text("""
                SELECT external_system
                FROM external_references
                WHERE internal_entity_type = 'contact'
                AND internal_entity_id = :contact_id
            """),
            {"contact_id": contact_id},
        )
        ref_row = result.fetchone()
        assert ref_row is not None, "External reference should be created"
        assert ref_row[0] == "google", (
            f"external_system should be normalized to 'google', got '{ref_row[0]}'"
        )

        # Verify the sync metadata was created with 'google' (not 'google_contacts')
        result = await clean_database.execute(
            text("""
                SELECT integration_source
                FROM sync_metadata
                WHERE internal_id = :contact_id
            """),
            {"contact_id": contact_id},
        )
        sync_row = result.fetchone()
        assert sync_row is not None, "Sync metadata should be created"
        assert sync_row[0] == "google", (
            f"integration_source should be 'google', got '{sync_row[0]}'"
        )

        # Verify the event was marked as processed (not failed)
        event_state = await self._fetch_outbox_event_state(
            clean_database,
            event_id=event_id,
        )
        assert event_state is not None
        assert event_state[1] is not None, "Event should be marked as processed"
        assert event_state[0] == 0, "Retry count should remain 0"

    @pytest.mark.asyncio
    async def test_process_contact_updated_event_triggers_on_birthday_change(
        self,
        clean_database: AsyncConnection,
        sample_contact_data: dict[str, Any],
    ):
        """A change only to important_dates triggers an update via idempotency checks."""
        contact_id = 98765
        external_id = f"people/birthday-update-{uuid4()}"

        await self._insert_existing_contact_reference(
            clean_database,
            contact_id=contact_id,
            external_id=external_id,
            first_name="Birthday",
            last_name="Update",
        )
        await self._insert_contact_method(
            clean_database,
            contact_id=contact_id,
            method_type="email",
            value="birthday@example.com",
            label="personal",
            is_primary=True,
        )

        contact_data = copy.deepcopy(sample_contact_data)
        contact_data["first_name"] = "Birthday"
        contact_data["last_name"] = "Update"
        contact_data["methods"] = [
            {
                "method_type": "email",
                "value": "birthday@example.com",
                "label": "personal",
                "is_primary": True,
            }
        ]
        # First sync to establish the initial version hash without birthday
        event_id_1 = await self._insert_contact_sync_event(
            clean_database,
            event_type="contact.updated",
            contact_data=contact_data,
            external_id=external_id,
            sync_type="updated",
        )
        await self._run_outbox_processor(clean_database)

        # Ensure first event processed successfully
        event_state_1 = await self._fetch_outbox_event_state(
            clean_database,
            event_id=event_id_1,
        )
        assert event_state_1 is not None
        assert event_state_1[1] is not None  # processed_at is set

        # Second sync: ONLY add a birthday
        contact_data["important_dates"] = [
            {
                "date_type": "birthday",
                "precision": "full",
                "year": 1990,
                "month": 5,
                "day": 15,
                "custom_date_type_id": None,
                "custom_date_type_name": None,
            }
        ]
        event_id_2 = await self._insert_contact_sync_event(
            clean_database,
            event_type="contact.updated",
            contact_data=contact_data,
            external_id=external_id,
            sync_type="updated",
        )
        await self._run_outbox_processor(clean_database)

        # Check if the second event was skipped or processed
        # The key assertion is that the important date actually updated in the database
        result = await clean_database.execute(
            text("""
                SELECT date_type, year, month, day
                FROM contact_important_dates
                WHERE contact_id = :contact_id
            """),
            {"contact_id": contact_id},
        )
        dates = result.fetchall()

        assert len(dates) == 1, "Birthday should have been persisted"
        assert dates[0][0] == "birthday"
        assert dates[0][1] == 1990
        assert dates[0][2] == 5
        assert dates[0][3] == 15

        event_state_2 = await self._fetch_outbox_event_state(
            clean_database,
            event_id=event_id_2,
        )
        assert event_state_2 is not None
        assert event_state_2[1] is not None
