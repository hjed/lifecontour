"""Integration tests for projecting CONTACT events into field_history.

ITER12-003 Phase 2 switched contacts onto the event-driven HistoryProjectionConsumer
and removed the synchronous dual-write. These tests therefore:

* drive ``consumer._handle_event`` directly with contact StreamEvents to prove the
  projection writes the right rows (idempotently);
* prove the live ``_process_batch`` now DOES project contact events;
* run real ContactService / ContactRelationshipService mutations through the full
  service -> outbox -> relay -> consumer chain and assert the resulting
  field_history rows (the closest backend equivalent to the user-facing feed);
* prove a *bulk* full-contact update produces NO spurious per-sub-entity "created"
  markers (the aggregate ContactUpdated rows are the feed) — the main correctness
  gate for turning the projection on.

Mirrors test_history_projection_consumer_integration.py and
test_journal_history_projection_e2e.py.
"""

import uuid
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from core_shared.models.contacts.entities import (
    Contact,
    ContactMethod,
    ImportantDate,
    MethodType,
    RelationshipType,
)
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)
from core_shared.models.contacts.value_objects import Provenance
from core_shared.stream_client import StreamClient, StreamEvent
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.history.adapters.sql.field_history_repository import (
    SqlFieldHistoryRepository,
)
from app.core.history.models import FieldHistoryEntry
from app.infrastructure.events.history_projection_consumer import (
    HistoryProjectionConsumer,
)
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.events.outbox_relay import OutboxRelay
from tests.integration.conftest import ContactFactory
from tests.integration.contact_seeding import TEST_USER_ID

GROUP_NAME = "history-projection"
OCCURRED_AT = "2024-03-01T08:00:00+00:00"


async def _relay_and_project(
    stream_client: StreamClient,
    stream_name: str,
    async_connection: AsyncConnection,
    consumer_name: str,
) -> None:
    """Relay outbox events to the stream and run the projection consumer once.

    Both the relay and the consumer operate on the test ``async_connection`` (the
    consumer's engine is patched to yield it) so all writes share the test
    savepoint and roll back at teardown. Mirrors the journal e2e helper.
    """
    relay = OutboxRelay(
        stream_client=stream_client, stream_name=stream_name, batch_size=50
    )
    await relay.relay_batch(async_connection)

    consumer = HistoryProjectionConsumer(
        stream_client=stream_client,
        stream_name=stream_name,
        consumer_name=consumer_name,
        block_ms=100,
    )
    await stream_client.ensure_consumer_group(stream_name, GROUP_NAME)

    with patch(
        "app.infrastructure.events.history_projection_consumer.get_async_database_engine",
        return_value=_patched_engine(async_connection),
    ):
        await consumer._process_batch()


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
    async def test_contact_events_are_projected_by_live_subscription(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        """ITER12-003 Phase 2: a ContactUpdated on the stream is now consumed by the
        LIVE subscription and projected into field_history (the projection is the
        sole writer of contact history)."""
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

        assert await _rows_for(
            async_connection, entity_type="contact", entity_id=880007
        ) == [("first_name", "A", "B", "ui", "ui")]


async def _count_rows(conn: AsyncConnection, *, entity_type: str) -> int:
    result = await conn.execute(
        text("SELECT COUNT(*) FROM field_history WHERE entity_type = :et"),
        {"et": entity_type},
    )
    return int(result.scalar_one())


@pytest.mark.integration
class TestContactProjectionEndToEnd:
    """Real service mutations travel the full service -> outbox -> relay ->
    HistoryProjectionConsumer chain and write the expected field_history rows
    (the closest backend equivalent to the user-facing contact activity feed)."""

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
        # Publish to the outbox so the relay can deliver the real event.
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

    def _relationship_service(self, conn: AsyncConnection):
        from app.core.contacts.adapters.sql import (
            SqlContactRelationshipRepository,
            SqlContactRepository,
        )
        from app.core.contacts.services import ContactRelationshipService

        return ContactRelationshipService(
            SqlContactRepository(conn),
            SqlContactRelationshipRepository(conn),
            OutboxEventPublisher(conn),
        )

    def _tag_service(self, conn: AsyncConnection):
        from app.core.contacts.adapters.sql import SqlTagRepository
        from app.core.contacts.services import TagHierarchyService, TagService

        tag_repo = SqlTagRepository(conn)
        return TagService(
            tag_repo=tag_repo,
            tag_hierarchy_service=TagHierarchyService(tag_repo),
            event_publisher=OutboxEventPublisher(conn),
        )

    async def _drain(
        self,
        stream_client: StreamClient,
        stream_name: str,
        conn: AsyncConnection,
    ) -> None:
        await _relay_and_project(
            stream_client, stream_name, conn, f"e2e-{uuid.uuid4().hex[:6]}"
        )

    @pytest.mark.asyncio
    async def test_create_projects_contact_and_subentity_markers(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        """Create with a method projects the contact-level AND the per-sub-entity
        "created" markers (affects_history defaults True on the create path)."""
        service = self._service(async_connection)
        created = await service.create_contact(
            Contact(
                user_id=TEST_USER_ID,
                first_name="John",
                methods=[
                    ContactMethod(
                        method_type=MethodType.EMAIL,
                        value="j@example.com",
                        contact_id=0,
                    )
                ],
            ),
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
        )
        assert created.id is not None and created.methods is not None
        method_id = created.methods[0].id
        assert method_id is not None
        await self._drain(stream_client, test_stream_name, async_connection)

        assert await _rows_for(
            async_connection, entity_type="contact", entity_id=created.id
        ) == [("status", None, "created", "ui", "ui")]
        assert await _rows_for(
            async_connection,
            entity_type="contact_method",
            entity_id=method_id,
        ) == [("status", None, "created", "ui", "ui")]

    @pytest.mark.asyncio
    async def test_base_field_update_projected(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        service = self._service(async_connection)
        created = await service.create_contact(
            Contact(user_id=TEST_USER_ID, first_name="John", last_name="Doe"),
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
        )
        assert created.id is not None
        await service.update_contact_field(
            created.id,
            "first_name",
            "Jonathan",
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
            user_id=TEST_USER_ID,
        )
        await self._drain(stream_client, test_stream_name, async_connection)

        rows = await _rows_for(
            async_connection, entity_type="contact", entity_id=created.id
        )
        assert ("first_name", "John", "Jonathan", "ui", "ui") in rows

    @pytest.mark.asyncio
    async def test_method_field_update_projected(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        """A method field edit publishes ContactUpdated with a "method_{id}_{field}"
        key, which projects to the contact_method row."""
        service = self._service(async_connection)
        created = await service.create_contact(
            Contact(
                user_id=TEST_USER_ID,
                first_name="Mia",
                methods=[
                    ContactMethod(
                        method_type=MethodType.EMAIL,
                        value="old@example.com",
                        contact_id=0,
                    )
                ],
            ),
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
        )
        assert created.id is not None and created.methods is not None
        method_id = created.methods[0].id
        assert method_id is not None
        await service.update_contact_method_field(
            created.id,
            method_id,
            "value",
            "new@example.com",
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
            user_id=TEST_USER_ID,
        )
        await self._drain(stream_client, test_stream_name, async_connection)

        rows = await _rows_for(
            async_connection, entity_type="contact_method", entity_id=method_id
        )
        assert ("value", "old@example.com", "new@example.com", "ui", "ui") in rows

    @pytest.mark.asyncio
    async def test_archiving_a_primary_method_projects_both_changes(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        """Archiving demotes the primary; the feed records both, as one edit."""
        service = self._service(async_connection)
        created = await service.create_contact(
            Contact(
                user_id=TEST_USER_ID,
                first_name="Ari",
                methods=[
                    ContactMethod(
                        method_type=MethodType.EMAIL,
                        value="old@example.com",
                        contact_id=0,
                        is_primary=True,
                    )
                ],
            ),
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
        )
        assert created.id is not None and created.methods is not None
        method_id = created.methods[0].id
        assert method_id is not None
        await service.update_contact_method_field(
            created.id,
            method_id,
            "is_archived",
            True,
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
            user_id=TEST_USER_ID,
        )
        await self._drain(stream_client, test_stream_name, async_connection)

        rows = await _rows_for(
            async_connection, entity_type="contact_method", entity_id=method_id
        )
        assert ("is_archived", "False", "True", "ui", "ui") in rows
        assert ("is_primary", "True", "False", "ui", "ui") in rows

    @pytest.mark.asyncio
    async def test_tag_assign_projected(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        service = self._service(async_connection)
        created = await service.create_contact(
            Contact(user_id=TEST_USER_ID, first_name="Tara"),
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
        )
        assert created.id is not None
        tag = await self._tag_service(async_connection).create_tag(
            "vip", async_connection
        )
        assert tag.id is not None
        await service.assign_tag_to_contact(
            created.id,
            tag.id,
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
            user_id=TEST_USER_ID,
        )
        await self._drain(stream_client, test_stream_name, async_connection)

        rows = await _rows_for(
            async_connection, entity_type="contact", entity_id=created.id
        )
        assert ("tags", None, "vip", "ui", "ui") in rows

    @pytest.mark.asyncio
    async def test_important_date_add_projected(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        service = self._service(async_connection)
        created = await service.create_contact(
            Contact(user_id=TEST_USER_ID, first_name="Dana"),
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
        )
        assert created.id is not None
        saved_date = await service.add_contact_important_date(
            created.id,
            ImportantDate(
                contact_id=created.id,
                date_type=ImportantDateType.BIRTHDAY,
                precision=DatePrecision.DAY_MONTH,
                month=5,
                day=15,
            ),
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
            user_id=TEST_USER_ID,
        )
        assert saved_date.id is not None
        await self._drain(stream_client, test_stream_name, async_connection)

        assert await _rows_for(
            async_connection,
            entity_type="contact_important_date",
            entity_id=saved_date.id,
        ) == [("status", None, "created", "ui", "ui")]

    @pytest.mark.asyncio
    async def test_important_date_edit_projects_changed_fields(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        """An in-place edit reaches the feed as the fields that moved.

        The add and delete either side of it are bare status markers; an edit
        has something to say, and says it through the same changed-fields
        projection a relationship edit uses.
        """
        service = self._service(async_connection)
        created = await service.create_contact(
            Contact(user_id=TEST_USER_ID, first_name="Edith"),
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
        )
        assert created.id is not None
        saved_date = await service.add_contact_important_date(
            created.id,
            ImportantDate(
                contact_id=created.id,
                date_type=ImportantDateType.BIRTHDAY,
                precision=DatePrecision.FULL,
                year=1990,
                month=5,
                day=15,
            ),
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
            user_id=TEST_USER_ID,
        )
        assert saved_date.id is not None
        # Drain the add so only the edit's rows are under test.
        await self._drain(stream_client, test_stream_name, async_connection)

        await service.update_contact_important_date(
            created.id,
            saved_date.id,
            ImportantDate(
                id=saved_date.id,
                contact_id=created.id,
                date_type=ImportantDateType.BIRTHDAY,
                precision=DatePrecision.FULL,
                year=1991,
                month=5,
                day=15,
            ),
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
            user_id=TEST_USER_ID,
        )
        await self._drain(stream_client, test_stream_name, async_connection)

        rows = await _rows_for(
            async_connection,
            entity_type="contact_important_date",
            entity_id=saved_date.id,
        )
        # The whole history of this date: the add's marker, then one row for
        # the single field the edit moved. Asserted as a set rather than a
        # membership check, so an edit that reported month and day as having
        # "changed" from themselves would fail here.
        assert set(rows) == {
            ("status", None, "created", "ui", "ui"),
            ("year", "1990", "1991", "ui", "ui"),
        }

    @pytest.mark.asyncio
    async def test_bulk_update_produces_no_spurious_subentity_markers(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        """The headline correctness gate. A bulk full-contact update that adds a
        method and a tag must produce ONLY the aggregate ContactUpdated rows
        (``contact_methods`` / ``tags`` on the contact) — NOT spurious
        per-sub-entity "created"/per-tag markers. Neither the method nor the
        tag matches anything stored, so the save inserts them, and an inserted
        row's per-item event still carries affects_history=False."""
        service = self._service(async_connection)
        created = await service.create_contact(
            Contact(user_id=TEST_USER_ID, first_name="Bea"),
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
        )
        assert created.id is not None
        # Drain the create so we start from a known state (contact status:created).
        await self._drain(stream_client, test_stream_name, async_connection)
        assert await _count_rows(async_connection, entity_type="contact_method") == 0

        # Bulk update: add a method and a tag through the re-save path.
        await service.update_contact(
            Contact(
                user_id=TEST_USER_ID,
                id=created.id,
                first_name="Bea",
                methods=[
                    ContactMethod(
                        method_type=MethodType.EMAIL,
                        value="bea@example.com",
                        contact_id=created.id,
                    )
                ],
            ),
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
            tag_names=["work"],
            user_id=TEST_USER_ID,
        )
        await self._drain(stream_client, test_stream_name, async_connection)

        rows = await _rows_for(
            async_connection, entity_type="contact", entity_id=created.id
        )
        # The aggregate rows ARE the feed for a bulk update.
        field_names = {r[0] for r in rows}
        assert "contact_methods" in field_names
        tags_rows = [r for r in rows if r[0] == "tags"]
        # Exactly one tags row — the aggregate ("None" -> "work"), NOT a per-tag
        # (None -> "work") marker. The aggregate uses the literal string "None".
        assert tags_rows == [("tags", "None", "work", "ui", "ui")]
        # No per-sub-entity "created" markers from the re-saved method.
        assert await _count_rows(async_connection, entity_type="contact_method") == 0

    @pytest.mark.asyncio
    async def test_bulk_update_projects_a_matched_date_edit(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        """The other half of the gate above. A whole-contact save that *edits*
        a date it matched writes the same per-field rows the per-date endpoint
        writes — which is what MCP could not do before (#1524)."""
        service = self._service(async_connection)
        created = await service.create_contact(
            Contact(
                user_id=TEST_USER_ID,
                first_name="Cleo",
                important_dates=[
                    ImportantDate(
                        contact_id=0,
                        date_type=ImportantDateType.BIRTHDAY,
                        precision=DatePrecision.FULL,
                        year=1990,
                        month=5,
                        day=15,
                    )
                ],
            ),
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
        )
        assert created.id is not None
        assert created.important_dates is not None
        date_id = created.important_dates[0].id
        assert date_id is not None
        # Drain the create so only the edit's rows are under test.
        await self._drain(stream_client, test_stream_name, async_connection)

        # As MCP submits it: the whole date list, carrying no ids.
        await service.update_contact(
            Contact(
                user_id=TEST_USER_ID,
                id=created.id,
                first_name="Cleo",
                important_dates=[
                    ImportantDate(
                        contact_id=created.id,
                        date_type=ImportantDateType.BIRTHDAY,
                        precision=DatePrecision.FULL,
                        year=1991,
                        month=5,
                        day=15,
                    )
                ],
            ),
            async_connection,
            changed_by="mcp",
            source=Provenance.MCP,
            user_id=TEST_USER_ID,
        )
        await self._drain(stream_client, test_stream_name, async_connection)

        rows = await _rows_for(
            async_connection, entity_type="contact_important_date", entity_id=date_id
        )
        # The create's own marker, then one row for the single field the save
        # moved — asserted as a set, so a save reporting month and day as
        # having "changed" from themselves would fail here.
        assert set(rows) == {
            ("status", None, "created", "ui", "ui"),
            ("year", "1990", "1991", "mcp", "mcp"),
        }

    @pytest.mark.asyncio
    async def test_bulk_update_projects_a_matched_method_edit(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        """A matched method edit rides the aggregate event under a
        per-sub-entity key, so it lands on the method's own row exactly as a
        field-level PATCH would."""
        service = self._service(async_connection)
        created = await service.create_contact(
            Contact(
                user_id=TEST_USER_ID,
                first_name="Dara",
                methods=[
                    ContactMethod(
                        method_type=MethodType.EMAIL,
                        value="dara.before@example.com",
                        contact_id=0,
                    )
                ],
            ),
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
        )
        assert created.id is not None
        assert created.methods is not None
        method_id = created.methods[0].id
        assert method_id is not None
        await self._drain(stream_client, test_stream_name, async_connection)

        created.methods[0].value = "dara.after@example.com"
        await service.update_contact(
            created,
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
            user_id=TEST_USER_ID,
        )
        await self._drain(stream_client, test_stream_name, async_connection)

        rows = await _rows_for(
            async_connection, entity_type="contact_method", entity_id=method_id
        )
        assert set(rows) == {
            ("status", None, "created", "ui", "ui"),
            ("value", "dara.before@example.com", "dara.after@example.com", "ui", "ui"),
        }

    @pytest.mark.asyncio
    async def test_relationship_create_projected(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        service = self._service(async_connection)
        a = await service.create_contact(
            Contact(user_id=TEST_USER_ID, first_name="Ann"),
            async_connection,
            source=Provenance.UI,
        )
        b = await service.create_contact(
            Contact(user_id=TEST_USER_ID, first_name="Ben"),
            async_connection,
            source=Provenance.UI,
        )
        assert a.id is not None and b.id is not None
        rel_service = self._relationship_service(async_connection)
        created_rel = await rel_service.create_relationship(
            from_contact_id=a.id,
            to_contact_id=b.id,
            relationship_type=RelationshipType.FRIEND,
            create_bidirectional=False,
            transaction=async_connection,
            changed_by="ui",
            source=Provenance.UI,
            user_id=TEST_USER_ID,
        )
        rel_id = (
            created_rel.id if not isinstance(created_rel, list) else created_rel[0].id
        )
        assert rel_id is not None
        await self._drain(stream_client, test_stream_name, async_connection)

        assert await _rows_for(
            async_connection, entity_type="contact_relationship", entity_id=rel_id
        ) == [
            ("relationship_type", None, "friend", "ui", "ui"),
            ("status", None, "created", "ui", "ui"),
        ]

    @pytest.mark.asyncio
    async def test_summary_updated_projected(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        """A ContactSummaryUpdated event (published by the summary generator)
        projects to the contact_summary entity."""
        from app.core.contacts.models.events import ContactSummaryUpdated

        publisher = OutboxEventPublisher(async_connection)
        await publisher.publish(
            ContactSummaryUpdated(
                contact_id=990123,
                changed_fields={"summary_text": ("old", "new")},
                transaction=async_connection,
            )
        )
        await self._drain(stream_client, test_stream_name, async_connection)

        assert await _rows_for(
            async_connection, entity_type="contact_summary", entity_id=990123
        ) == [
            (
                "summary_text",
                "old",
                "new",
                Provenance.SUMMARY_REGENERATION.value,
                "system",
            )
        ]

    @pytest.mark.asyncio
    async def test_redelivery_no_duplicates_end_to_end(
        self,
        test_stream_name: str,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
    ) -> None:
        """Projecting the same outbox event twice (relay + re-project) must not
        duplicate rows — the unique index makes the projection idempotent."""
        service = self._service(async_connection)
        created = await service.create_contact(
            Contact(user_id=TEST_USER_ID, first_name="Uno"),
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
        )
        assert created.id is not None
        await service.update_contact_field(
            created.id,
            "first_name",
            "Una",
            async_connection,
            changed_by="ui",
            source=Provenance.UI,
            user_id=TEST_USER_ID,
        )
        # First delivery.
        await self._drain(stream_client, test_stream_name, async_connection)
        # Re-project the same already-relayed stream events (re-read from id 0).
        consumer = HistoryProjectionConsumer(
            stream_client=stream_client,
            stream_name=test_stream_name,
            consumer_name=f"redeliver-{uuid.uuid4().hex[:6]}",
            block_ms=100,
        )
        await stream_client.ensure_consumer_group(test_stream_name, GROUP_NAME)
        with patch(
            "app.infrastructure.events.history_projection_consumer.get_async_database_engine",
            return_value=_patched_engine(async_connection),
        ):
            await consumer._process_batch()

        update_rows = [
            r
            for r in await _rows_for(
                async_connection, entity_type="contact", entity_id=created.id
            )
            if r[0] == "first_name"
        ]
        assert update_rows == [("first_name", "Uno", "Una", "ui", "ui")]


@pytest.mark.integration
class TestMergeHistoryFeed:
    """After a merge the survivor's activity feed carries both the source's
    re-pointed history and the merge event with correct provenance.

    Drives the real REST surface (POST merge -> GET history) plus the real
    outbox -> relay -> projection chain, the closest backend equivalent to what
    the user sees in the activity feed.
    """

    @pytest.mark.asyncio
    async def test_merge_event_surfaces_in_activity_feed_with_provenance(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
        async_connection: AsyncConnection,
        stream_client: StreamClient,
        test_stream_name: str,
    ) -> None:
        survivor = await contact_factory.create_contact(
            first_name="Survivor", last_name="Keep"
        )
        source = await contact_factory.create_contact(
            first_name="Source", last_name="Drop"
        )
        survivor_id = int(survivor["id"])
        source_id = int(source["id"])

        # A pre-merge change recorded against the source contact (a projected prior
        # change, seeded deterministically — normal field projection is covered by
        # the tests above).
        repo = SqlFieldHistoryRepository(async_connection)
        await repo.record_change(
            FieldHistoryEntry(
                entity_type="contact",
                entity_id=source_id,
                field_name="first_name",
                old_value="Source",
                new_value="Sourced",
                changed_by="ui",
                source=Provenance.UI,
                event_id="evt-premerge-feed",
            )
        )

        merge_res = await authenticated_client.post(
            f"/api/contacts/{survivor_id}/merge",
            json={
                "data": {
                    "type": "contact-merge",
                    "attributes": {"source_contact_id": source_id},
                }
            },
        )
        assert merge_res.status_code == 200, merge_res.text

        # Project the published merged_from event into field_history.
        await _relay_and_project(
            stream_client,
            test_stream_name,
            async_connection,
            f"merge-feed-{uuid.uuid4().hex[:6]}",
        )

        history_res = await authenticated_client.get(
            f"/api/contacts/{survivor_id}/history"
        )
        assert history_res.status_code == 200, history_res.text
        attrs = [e["attributes"] for e in history_res.json()["data"]]

        # The merge event is surfaced with UI provenance and references the source.
        # Search the entries rather than keying by field_name, which would collapse
        # any duplicate rows for the same field.
        merge_rows = [a for a in attrs if a["field_name"] == "merged_from"]
        assert len(merge_rows) == 1
        assert merge_rows[0]["source"] == Provenance.UI.value
        assert str(source_id) in (merge_rows[0]["old_value"] or "")
        # The source's pre-merge change is carried onto the survivor.
        assert any(
            a["field_name"] == "first_name" and a["new_value"] == "Sourced"
            for a in attrs
        )
