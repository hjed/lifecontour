"""Integration tests for projecting CONTACT events into field_history.

ITER12-003 Phase 1 teaches the HistoryProjectionConsumer to derive contact
history from contact domain events, but keeps those event types OUT of the live
subscription so the synchronous dual-write stays the sole writer this phase
(inert). These tests therefore:

* drive ``consumer._handle_event`` directly with contact StreamEvents to prove
  the projection writes the rows the dual-write writes today (idempotently);
* prove the live ``_process_batch`` does NOT project contact events (inert);
* run a real ContactService mutation through the outbox and assert the published
  event projects to rows equivalent to the dual-write's record_* output.

Mirrors test_history_projection_consumer_integration.py and
test_journal_history_projection_e2e.py.
"""

import json
import uuid
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from core_shared.models.contacts.entities import Contact, ContactMethod, MethodType
from core_shared.models.contacts.value_objects import Provenance
from core_shared.stream_client import StreamClient, StreamEvent
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.history.services.history_service import HistoryService
from app.infrastructure.events.history_projection_consumer import (
    HistoryProjectionConsumer,
)
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.events.outbox_repository import OutboxEvent

GROUP_NAME = "history-projection"
OCCURRED_AT = "2024-03-01T08:00:00+00:00"


def _patched_engine(async_connection: AsyncConnection) -> MagicMock:
    """Mock engine whose .begin() yields the test transaction (shared savepoint)."""
    mock_engine = MagicMock()

    @asynccontextmanager
    async def mock_begin():
        yield async_connection

    mock_engine.begin = mock_begin
    return mock_engine


def _stream_event(
    event_type: str, event_data: dict[str, Any], *, event_id: str | None = None
) -> StreamEvent:
    return StreamEvent(
        message_id="1-0",
        event_id=event_id or f"evt-{uuid.uuid4().hex[:8]}",
        event_type=event_type,
        aggregate_id=int(event_data.get("contact_id") or 0),
        event_data=event_data,
        occurred_at=OCCURRED_AT,
    )


def _consumer(
    stream_client: StreamClient, stream_name: str
) -> HistoryProjectionConsumer:
    return HistoryProjectionConsumer(
        stream_client=stream_client,
        stream_name=stream_name,
        consumer_name=f"test-contact-{uuid.uuid4().hex[:6]}",
        block_ms=100,
    )


async def _rows_for(
    conn: AsyncConnection, *, entity_type: str, entity_id: int
) -> list[tuple[object, ...]]:
    result = await conn.execute(
        text(
            "SELECT field_name, old_value, new_value, source, changed_by "
            "FROM field_history WHERE entity_type = :et AND entity_id = :ei "
            "ORDER BY field_name"
        ),
        {"et": entity_type, "ei": entity_id},
    )
    return [tuple(r) for r in result.fetchall()]


@pytest.mark.integration
class TestContactHistoryProjection:
    """Drive _handle_event with contact events and assert dual-write-equivalent rows."""

    @pytest.mark.asyncio
    async def test_contact_updated_projects_one_row_per_field(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        consumer = _consumer(stream_client, test_stream_name)
        event = _stream_event(
            "ContactUpdated",
            {
                "contact_id": 880001,
                "changed_fields": {"first_name": ["John", "Jane"]},
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )
        with patch(
            "app.infrastructure.events.history_projection_consumer.get_async_database_engine",
            return_value=_patched_engine(async_connection),
        ):
            await consumer._handle_event(event)

        assert await _rows_for(
            async_connection, entity_type="contact", entity_id=880001
        ) == [("first_name", "John", "Jane", "ui", "ui")]

    @pytest.mark.asyncio
    async def test_method_edit_via_contact_updated_projects_contact_method_row(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        """A method field edit arrives as ContactUpdated with a per-sub-entity key;
        the projection decodes it to the contact_method row (not a mangled contact
        row)."""
        consumer = _consumer(stream_client, test_stream_name)
        event = _stream_event(
            "ContactUpdated",
            {
                "contact_id": 880002,
                "changed_fields": {"method_5501_value": ["a@b.com", "c@d.com"]},
                "source": Provenance.MCP.value,
                "changed_by": "mcp",
            },
        )
        with patch(
            "app.infrastructure.events.history_projection_consumer.get_async_database_engine",
            return_value=_patched_engine(async_connection),
        ):
            await consumer._handle_event(event)

        # Keyed to the contact_method sub-entity (not a mangled contact row).
        assert await _rows_for(
            async_connection, entity_type="contact_method", entity_id=5501
        ) == [("value", "a@b.com", "c@d.com", "mcp", "mcp")]
        assert (
            await _rows_for(async_connection, entity_type="contact", entity_id=880002)
            == []
        )

    @pytest.mark.asyncio
    async def test_relationship_created_projects_status_and_type_rows(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        consumer = _consumer(stream_client, test_stream_name)
        event = _stream_event(
            "ContactRelationshipCreated",
            {
                "relationship_id": 6601,
                "from_contact_id": 880003,
                "to_contact_id": 880004,
                "relationship_type": "friend",
                "to_user": False,
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )
        with patch(
            "app.infrastructure.events.history_projection_consumer.get_async_database_engine",
            return_value=_patched_engine(async_connection),
        ):
            await consumer._handle_event(event)

        assert await _rows_for(
            async_connection, entity_type="contact_relationship", entity_id=6601
        ) == [
            ("relationship_type", None, "friend", "ui", "ui"),
            ("status", None, "created", "ui", "ui"),
        ]

    @pytest.mark.asyncio
    async def test_tag_assigned_projects_tags_row_on_contact(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        consumer = _consumer(stream_client, test_stream_name)
        event = _stream_event(
            "TagAssigned",
            {
                "contact_id": 880005,
                "tag_id": 9,
                "tag_name": "work",
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
        )
        with patch(
            "app.infrastructure.events.history_projection_consumer.get_async_database_engine",
            return_value=_patched_engine(async_connection),
        ):
            await consumer._handle_event(event)

        assert await _rows_for(
            async_connection, entity_type="contact", entity_id=880005
        ) == [("tags", None, "work", "ui", "ui")]

    @pytest.mark.asyncio
    async def test_redelivery_writes_no_duplicate_rows(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        """Same event_id projected twice must not duplicate rows (idempotent)."""
        consumer = _consumer(stream_client, test_stream_name)
        event = _stream_event(
            "ContactUpdated",
            {
                "contact_id": 880006,
                "changed_fields": {"first_name": ["A", "B"]},
                "source": Provenance.UI.value,
                "changed_by": "ui",
            },
            event_id="evt-dup-contact",
        )
        with patch(
            "app.infrastructure.events.history_projection_consumer.get_async_database_engine",
            return_value=_patched_engine(async_connection),
        ):
            await consumer._handle_event(event)
            await consumer._handle_event(event)

        assert (
            len(
                await _rows_for(
                    async_connection, entity_type="contact", entity_id=880006
                )
            )
            == 1
        )

    @pytest.mark.asyncio
    async def test_contact_events_are_inert_in_live_subscription(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        """End-to-end inertness: a ContactUpdated on the stream is acked by the
        live consumer but projects NO rows, because contact event types are not in
        the journal-only subscription this phase (the dual-write stays sole writer).
        """
        await stream_client.publish(
            stream_name=test_stream_name,
            event_id=f"evt-{uuid.uuid4().hex[:8]}",
            event_type="ContactUpdated",
            aggregate_id=880007,
            event_data={
                "contact_id": 880007,
                "changed_fields": {"first_name": ["A", "B"]},
                "source": "ui",
                "changed_by": "ui",
            },
            occurred_at=OCCURRED_AT,
        )
        consumer = _consumer(stream_client, test_stream_name)
        await stream_client.ensure_consumer_group(test_stream_name, GROUP_NAME)

        with patch(
            "app.infrastructure.events.history_projection_consumer.get_async_database_engine",
            return_value=_patched_engine(async_connection),
        ):
            await consumer._process_batch()

        assert (
            await _rows_for(async_connection, entity_type="contact", entity_id=880007)
            == []
        )


@pytest.mark.integration
class TestContactProjectionMatchesDualWrite:
    """A real ContactService mutation publishes an event that, when projected,
    reproduces the rows the synchronous dual-write wrote (snapshot equivalence)."""

    def _service(self, conn: AsyncConnection):
        from app.core.contacts.adapters.sql import (
            SqlContactFieldHistoryRepository,
            SqlContactRepository,
            SqlTagRepository,
        )
        from app.core.contacts.services import (
            AddressValidationService,
            ContactHistoryService,
            ContactService,
            ContactValidationService,
            TagHierarchyService,
            TagService,
        )

        contact_repo = SqlContactRepository(conn)
        tag_repo = SqlTagRepository(conn)
        history_repo = SqlContactFieldHistoryRepository(conn)
        # Publish to the outbox so we can read & project the real event.
        event_publisher = OutboxEventPublisher(conn)
        tag_hierarchy_service = TagHierarchyService(tag_repo)
        return ContactService(
            contact_repo=contact_repo,
            tag_repo=tag_repo,
            history_repo=history_repo,
            event_publisher=event_publisher,
            address_validation_service=AddressValidationService(),
            contact_validation_service=ContactValidationService(contact_repo),
            history_service=ContactHistoryService(history_repo),
            tag_hierarchy_service=tag_hierarchy_service,
            tag_service=TagService(
                tag_repo=tag_repo,
                tag_hierarchy_service=tag_hierarchy_service,
                event_publisher=event_publisher,
            ),
        )

    async def _project_outbox_after(
        self, conn: AsyncConnection, *, after_id: int
    ) -> set[tuple[object, ...]]:
        """Project every outbox event published after ``after_id`` and return the
        (entity_type, entity_id, field_name, old, new, source, changed_by) tuples the
        projection writes. Provenance is included so an enrichment regression (the
        whole point of Phase 1) can't slip through the equivalence check."""
        result = await conn.execute(
            text(
                "SELECT id, event_id, event_type, aggregate_id, event_data, "
                "occurred_at FROM outbox_events WHERE id > :after ORDER BY id"
            ),
            {"after": after_id},
        )
        service = HistoryService()
        rows: set[tuple[object, ...]] = set()
        for rec in result.fetchall():
            data = rec.event_data
            if isinstance(data, str):
                data = json.loads(data)
            event = OutboxEvent(
                id=rec.id,
                event_id=rec.event_id,
                event_type=rec.event_type,
                aggregate_id=rec.aggregate_id,
                event_data=data,
                occurred_at=rec.occurred_at,
                retry_count=0,
                created_at=rec.occurred_at,
            )
            for r in service.project_event(event):
                rows.add(
                    (
                        r.entity_type,
                        r.entity_id,
                        r.field_name,
                        r.old_value,
                        r.new_value,
                        # field_history stores the provenance string; project_event
                        # yields a Provenance enum, so compare on its value.
                        r.source.value,
                        r.changed_by,
                    )
                )
        return rows

    async def _dualwrite_rows(
        self, conn: AsyncConnection, *, after_id: int
    ) -> set[tuple[object, ...]]:
        """The history rows the dual-write wrote (event_id IS NULL) after ``after_id``,
        including source/changed_by for provenance parity."""
        result = await conn.execute(
            text(
                "SELECT entity_type, entity_id, field_name, old_value, new_value, "
                "source, changed_by FROM field_history "
                "WHERE event_id IS NULL AND id > :after"
            ),
            {"after": after_id},
        )
        return {tuple(r) for r in result.fetchall()}

    async def _max_ids(self, conn: AsyncConnection) -> tuple[int, int]:
        outbox = await conn.execute(
            text("SELECT COALESCE(MAX(id), 0) FROM outbox_events")
        )
        history = await conn.execute(
            text("SELECT COALESCE(MAX(id), 0) FROM field_history")
        )
        return int(outbox.scalar_one()), int(history.scalar_one())

    @pytest.mark.asyncio
    async def test_base_field_update_projection_equals_dual_write(
        self, clean_database: AsyncConnection
    ) -> None:
        service = self._service(clean_database)
        created = await service.create_contact(
            Contact(first_name="John", last_name="Doe"),
            clean_database,
            changed_by="ui",
            source=Provenance.UI,
        )
        assert created.id is not None

        outbox_before, history_before = await self._max_ids(clean_database)
        await service.update_contact_field(
            created.id,
            "first_name",
            "Jonathan",
            clean_database,
            changed_by="ui",
            source=Provenance.UI,
        )

        projected = await self._project_outbox_after(
            clean_database, after_id=outbox_before
        )
        dual_write = await self._dualwrite_rows(clean_database, after_id=history_before)
        assert projected == dual_write
        assert (
            "contact",
            created.id,
            "first_name",
            "John",
            "Jonathan",
            "ui",
            "ui",
        ) in projected

    @pytest.mark.asyncio
    async def test_method_field_update_projection_equals_dual_write(
        self, clean_database: AsyncConnection
    ) -> None:
        """A method field edit publishes ContactUpdated with a "method_{id}_{field}"
        key, which projects to the same contact_method row the dual-write wrote."""
        service = self._service(clean_database)
        created = await service.create_contact(
            Contact(
                first_name="Mia",
                methods=[
                    ContactMethod(
                        method_type=MethodType.EMAIL,
                        value="old@example.com",
                        contact_id=0,
                    )
                ],
            ),
            clean_database,
            changed_by="ui",
            source=Provenance.UI,
        )
        assert created.id is not None and created.methods[0].id is not None
        method_id = created.methods[0].id

        outbox_before, history_before = await self._max_ids(clean_database)
        await service.update_contact_method_field(
            created.id,
            method_id,
            "value",
            "new@example.com",
            clean_database,
            changed_by="ui",
            source=Provenance.UI,
        )

        projected = await self._project_outbox_after(
            clean_database, after_id=outbox_before
        )
        dual_write = await self._dualwrite_rows(clean_database, after_id=history_before)
        assert projected == dual_write
        assert (
            "contact_method",
            method_id,
            "value",
            "old@example.com",
            "new@example.com",
            "ui",
            "ui",
        ) in projected
