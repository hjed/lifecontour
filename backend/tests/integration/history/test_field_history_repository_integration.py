"""Integration tests for the generalised SqlFieldHistoryRepository."""

from datetime import UTC, datetime, timedelta

import pytest
from core_shared.models.history import Provenance
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.history.adapters.sql.field_history_repository import (
    SqlFieldHistoryRepository,
)
from app.core.history.models import (
    CREATED_MARKER,
    DELETED_MARKER,
    FieldHistoryEntry,
    UnknownAggregationRootError,
)
from app.core.tasks.models.events import contact_field_name, journal_field_name
from tests.integration.contact_seeding import seed_contact
from tests.integration.tasks.task_seeding import OTHER_USER_ID, USER_ID, create_task


@pytest.mark.integration
class TestSqlFieldHistoryRepositoryIntegration:
    """Integration tests for the entity-agnostic field history repository."""

    @pytest.fixture
    def history_repo(
        self, clean_database: AsyncConnection
    ) -> SqlFieldHistoryRepository:
        return SqlFieldHistoryRepository(clean_database)

    async def _create_contact(self, conn: AsyncConnection, first_name: str) -> int:
        return await seed_contact(conn, first_name=first_name)

    async def _create_method(self, conn: AsyncConnection, contact_id: int) -> int:
        result = await conn.execute(
            text(
                "INSERT INTO contact_methods (contact_id, method_type, value) "
                "VALUES (:cid, 'email', 'a@example.com') RETURNING id"
            ),
            {"cid": contact_id},
        )
        return int(result.scalar_one())

    async def _count_rows(
        self,
        conn: AsyncConnection,
        *,
        entity_type: str,
        entity_id: int,
        field_name: str,
    ) -> int:
        result = await conn.execute(
            text(
                "SELECT COUNT(*) FROM field_history "
                "WHERE entity_type = :et AND entity_id = :ei AND field_name = :fn"
            ),
            {"et": entity_type, "ei": entity_id, "fn": field_name},
        )
        return int(result.scalar_one())

    async def test_record_change_persists_and_returns_metadata(
        self, history_repo: SqlFieldHistoryRepository
    ) -> None:
        entry = FieldHistoryEntry(
            entity_type="contact",
            entity_id=1,
            field_name="first_name",
            old_value="John",
            new_value="Jane",
            changed_by="test_user",
            source=Provenance.UI,
        )

        saved = await history_repo.record_change(entry)

        assert saved.id is not None
        assert saved.created_at is not None
        assert saved.source == Provenance.UI

    async def test_record_change_persists_event_id(
        self, history_repo: SqlFieldHistoryRepository, clean_database: AsyncConnection
    ) -> None:
        entry = FieldHistoryEntry(
            entity_type="journal",
            entity_id=7,
            field_name="title",
            old_value="a",
            new_value="b",
            event_id="evt-persist",
        )

        await history_repo.record_change(entry)

        result = await clean_database.execute(
            text("SELECT event_id FROM field_history WHERE entity_id = 7"),
        )
        assert result.scalar_one() == "evt-persist"

    async def test_record_change_is_idempotent_for_same_event_key(
        self, history_repo: SqlFieldHistoryRepository, clean_database: AsyncConnection
    ) -> None:
        """Re-projecting the same event must not create a duplicate row."""
        entry = FieldHistoryEntry(
            entity_type="journal",
            entity_id=99,
            field_name="title",
            old_value="a",
            new_value="b",
            event_id="evt-dup",
        )

        first = await history_repo.record_change(entry)
        # Second call with the same (event_id, entity_type, entity_id, field_name).
        second = await history_repo.record_change(
            FieldHistoryEntry(
                entity_type="journal",
                entity_id=99,
                field_name="title",
                old_value="a",
                new_value="b",
                event_id="evt-dup",
            )
        )

        assert first.id is not None
        # The conflicting re-insert returns without error and writes no new row.
        assert second.id is None
        assert (
            await self._count_rows(
                clean_database,
                entity_type="journal",
                entity_id=99,
                field_name="title",
            )
            == 1
        )

    async def test_record_change_clears_metadata_on_conflict_for_reused_instance(
        self, history_repo: SqlFieldHistoryRepository
    ) -> None:
        """A reused, already-persisted instance must not report stale id/created_at."""
        entry = FieldHistoryEntry(
            entity_type="journal",
            entity_id=123,
            field_name="title",
            old_value="a",
            new_value="b",
            event_id="evt-reuse",
        )

        saved = await history_repo.record_change(entry)
        assert saved.id is not None
        assert saved.created_at is not None

        # Re-record the SAME instance: it conflicts and its stale metadata is cleared.
        reprojected = await history_repo.record_change(entry)
        assert reprojected is entry
        assert reprojected.id is None
        assert reprojected.created_at is None

    async def test_null_event_ids_are_not_deduplicated(
        self, history_repo: SqlFieldHistoryRepository, clean_database: AsyncConnection
    ) -> None:
        """Contact dual-writes (event_id NULL) must remain un-deduplicated."""
        for _ in range(2):
            await history_repo.record_change(
                FieldHistoryEntry(
                    entity_type="contact",
                    entity_id=5,
                    field_name="first_name",
                    old_value="John",
                    new_value="Jane",
                )
            )

        assert (
            await self._count_rows(
                clean_database,
                entity_type="contact",
                entity_id=5,
                field_name="first_name",
            )
            == 2
        )

    async def test_get_history_for_aggregate_contact_aggregation(
        self, history_repo: SqlFieldHistoryRepository, clean_database: AsyncConnection
    ) -> None:
        """The contact strategy aggregates the contact and its related sub-entities."""
        contact_id = await self._create_contact(clean_database, "Aggie")
        method_id = await self._create_method(clean_database, contact_id)
        other_id = await self._create_contact(clean_database, "Other")

        await history_repo.record_change(
            FieldHistoryEntry(
                entity_type="contact",
                entity_id=contact_id,
                field_name="first_name",
                old_value="Aggie",
                new_value="Agatha",
            )
        )
        await history_repo.record_change(
            FieldHistoryEntry(
                entity_type="contact_method",
                entity_id=method_id,
                field_name="value",
                old_value="a@example.com",
                new_value="b@example.com",
            )
        )
        # Belongs to a different contact and must not appear.
        await history_repo.record_change(
            FieldHistoryEntry(
                entity_type="contact",
                entity_id=other_id,
                field_name="first_name",
                old_value="Other",
                new_value="Another",
            )
        )

        entries = await history_repo.get_history_for_aggregate(
            "contact", contact_id, limit=50, offset=0
        )
        count = await history_repo.get_history_for_aggregate_count(
            "contact", contact_id, reader_user_id=USER_ID
        )

        keys = {(e.entity_type, e.entity_id) for e in entries}
        assert ("contact", contact_id) in keys
        assert ("contact_method", method_id) in keys
        assert ("contact", other_id) not in keys
        assert count == 2

    async def test_get_history_for_aggregate_pagination_and_order(
        self, history_repo: SqlFieldHistoryRepository, clean_database: AsyncConnection
    ) -> None:
        contact_id = await self._create_contact(clean_database, "Paged")
        for i in range(5):
            await history_repo.record_change(
                FieldHistoryEntry(
                    entity_type="contact",
                    entity_id=contact_id,
                    field_name=f"field_{i}",
                    old_value=f"old_{i}",
                    new_value=f"new_{i}",
                )
            )

        page = await history_repo.get_history_for_aggregate(
            "contact", contact_id, limit=2, offset=0
        )
        next_page = await history_repo.get_history_for_aggregate(
            "contact", contact_id, limit=2, offset=2
        )

        assert len(page) == 2
        assert len(next_page) == 2
        # Most-recent-first ordering.
        timestamps = [e.created_at for e in page if e.created_at is not None]
        assert len(timestamps) == len(page)
        assert timestamps == sorted(timestamps, reverse=True)
        # Pages are disjoint.
        assert {e.id for e in page}.isdisjoint({e.id for e in next_page})

    async def test_get_history_for_aggregate_unknown_root_raises(
        self, history_repo: SqlFieldHistoryRepository
    ) -> None:
        with pytest.raises(UnknownAggregationRootError):
            await history_repo.get_history_for_aggregate("nope", 1)

    async def test_record_change_persists_explicit_created_at(
        self, history_repo: SqlFieldHistoryRepository, clean_database: AsyncConnection
    ) -> None:
        """Projection passes event.occurred_at so history reflects when the change
        actually happened, not wall-clock at projection time."""
        occurred_at = datetime(2023, 6, 1, 9, 30, 0, tzinfo=UTC)
        entry = FieldHistoryEntry(
            entity_type="journal",
            entity_id=4242,
            field_name="title",
            old_value="a",
            new_value="b",
            event_id="evt-occurred-at",
            created_at=occurred_at,
        )

        await history_repo.record_change(entry)

        result = await clean_database.execute(
            text("SELECT created_at FROM field_history WHERE entity_id = 4242"),
        )
        stored = result.scalar_one()
        assert stored == occurred_at

    async def test_repoint_entity_history_moves_top_level_rows(
        self, history_repo: SqlFieldHistoryRepository, clean_database: AsyncConnection
    ) -> None:
        """Re-pointing moves the source's top-level ``contact`` rows onto the
        survivor while leaving sub-entity rows untouched."""
        survivor_id = await self._create_contact(clean_database, "Survivor")
        source_id = await self._create_contact(clean_database, "Source")
        source_method_id = await self._create_method(clean_database, source_id)

        # Two top-level rows on the source plus one sub-entity row.
        await history_repo.record_change(
            FieldHistoryEntry(
                entity_type="contact",
                entity_id=source_id,
                field_name="first_name",
                old_value="Source",
                new_value="Sourced",
                event_id="evt-src-1",
            )
        )
        await history_repo.record_change(
            FieldHistoryEntry(
                entity_type="contact",
                entity_id=source_id,
                field_name="company",
                old_value=None,
                new_value="Acme",
                event_id="evt-src-2",
            )
        )
        await history_repo.record_change(
            FieldHistoryEntry(
                entity_type="contact_method",
                entity_id=source_method_id,
                field_name="value",
                old_value="a@example.com",
                new_value="b@example.com",
                event_id="evt-method-1",
            )
        )

        moved = await history_repo.repoint_entity_history(
            source_id, survivor_id, "contact", clean_database
        )

        assert moved == 2
        # The source's top-level rows now belong to the survivor.
        survivor_rows = await history_repo.get_entity_history("contact", survivor_id)
        survivor_fields = {r.field_name for r in survivor_rows}
        assert {"first_name", "company"} <= survivor_fields
        # The source has no remaining top-level rows.
        assert (
            await self._count_rows(
                clean_database,
                entity_type="contact",
                entity_id=source_id,
                field_name="first_name",
            )
            == 0
        )
        # Only top-level contact rows move; sub-entity rows are left untouched.
        method_rows = await history_repo.get_entity_history(
            "contact_method", source_method_id
        )
        assert len(method_rows) == 1

    async def test_repoint_entity_history_preserves_provenance_and_event_id(
        self, history_repo: SqlFieldHistoryRepository, clean_database: AsyncConnection
    ) -> None:
        """Moved rows keep their original provenance and event id so the survivor's
        audit trail stays faithful."""
        survivor_id = await self._create_contact(clean_database, "Keep")
        source_id = await self._create_contact(clean_database, "Absorb")
        await history_repo.record_change(
            FieldHistoryEntry(
                entity_type="contact",
                entity_id=source_id,
                field_name="first_name",
                old_value="Absorb",
                new_value="Absorbed",
                changed_by="mcp",
                source=Provenance.MCP,
                event_id="evt-prov-1",
            )
        )

        await history_repo.repoint_entity_history(
            source_id, survivor_id, "contact", clean_database
        )

        rows = await history_repo.get_entity_history("contact", survivor_id)
        moved = next(r for r in rows if r.field_name == "first_name")
        assert moved.source == Provenance.MCP
        assert moved.changed_by == "mcp"
        assert moved.event_id == "evt-prov-1"

    async def test_repoint_entity_history_is_idempotent(
        self, history_repo: SqlFieldHistoryRepository, clean_database: AsyncConnection
    ) -> None:
        """Re-running the re-point produces no duplicates and is a stable no-op once
        the source's rows have moved (covers the ON CONFLICT DO NOTHING path)."""
        survivor_id = await self._create_contact(clean_database, "Survivor")
        source_id = await self._create_contact(clean_database, "Source")
        await history_repo.record_change(
            FieldHistoryEntry(
                entity_type="contact",
                entity_id=source_id,
                field_name="first_name",
                old_value="Source",
                new_value="Sourced",
                event_id="evt-idem-1",
            )
        )

        first = await history_repo.repoint_entity_history(
            source_id, survivor_id, "contact", clean_database
        )
        count_after_first = await history_repo.get_history_for_aggregate_count(
            "contact", survivor_id
        )
        second = await history_repo.repoint_entity_history(
            source_id, survivor_id, "contact", clean_database
        )
        count_after_second = await history_repo.get_history_for_aggregate_count(
            "contact", survivor_id
        )

        assert first == 1
        # Source rows are already gone, so the re-run moves nothing.
        assert second == 0
        assert count_after_first == count_after_second
        assert (
            await self._count_rows(
                clean_database,
                entity_type="contact",
                entity_id=survivor_id,
                field_name="first_name",
            )
            == 1
        )

    async def test_repoint_entity_history_dedupes_conflicting_rows(
        self, history_repo: SqlFieldHistoryRepository, clean_database: AsyncConnection
    ) -> None:
        """When the survivor already carries a row with the same dedup key, the
        source's duplicate collapses rather than raising."""
        survivor_id = await self._create_contact(clean_database, "Survivor")
        source_id = await self._create_contact(clean_database, "Source")
        # Both contacts carry a row that, once re-pointed, shares the dedup key
        # (event_id, entity_type, entity_id, field_name).
        for entity_id in (survivor_id, source_id):
            await history_repo.record_change(
                FieldHistoryEntry(
                    entity_type="contact",
                    entity_id=entity_id,
                    field_name="first_name",
                    old_value="x",
                    new_value="y",
                    event_id="evt-shared",
                )
            )

        moved = await history_repo.repoint_entity_history(
            source_id, survivor_id, "contact", clean_database
        )

        # The conflicting source row is dropped; the survivor keeps a single row.
        assert moved == 0
        assert (
            await self._count_rows(
                clean_database,
                entity_type="contact",
                entity_id=survivor_id,
                field_name="first_name",
            )
            == 1
        )
        assert (
            await self._count_rows(
                clean_database,
                entity_type="contact",
                entity_id=source_id,
                field_name="first_name",
            )
            == 0
        )

    async def test_repoint_entity_history_self_move_is_a_noop(
        self, history_repo: SqlFieldHistoryRepository, clean_database: AsyncConnection
    ) -> None:
        """Re-pointing an entity onto itself must not wipe its history: the copy
        conflicts on every row while the delete would remove them, so the
        self-move is rejected."""
        contact_id = await self._create_contact(clean_database, "Same")
        await history_repo.record_change(
            FieldHistoryEntry(
                entity_type="contact",
                entity_id=contact_id,
                field_name="first_name",
                old_value="Same",
                new_value="Samed",
                event_id="evt-self",
            )
        )

        moved = await history_repo.repoint_entity_history(
            contact_id, contact_id, "contact", clean_database
        )

        assert moved == 0
        assert (
            await self._count_rows(
                clean_database,
                entity_type="contact",
                entity_id=contact_id,
                field_name="first_name",
            )
            == 1
        )

    async def test_record_change_falls_back_to_db_default_created_at(
        self, history_repo: SqlFieldHistoryRepository, clean_database: AsyncConnection
    ) -> None:
        """The synchronous contact dual-write passes no created_at and must keep
        using the database default (now()) rather than NULL."""
        entry = FieldHistoryEntry(
            entity_type="contact",
            entity_id=4243,
            field_name="first_name",
            old_value="John",
            new_value="Jane",
        )

        saved = await history_repo.record_change(entry)

        assert saved.created_at is not None
        result = await clean_database.execute(
            text("SELECT created_at FROM field_history WHERE entity_id = 4243"),
        )
        stored = result.scalar_one()
        # Falls back to a DB-generated timestamp (now()), never NULL. Exact value
        # is the transaction time, unreliable to compare against wall clock under
        # the savepoint fixture, so we assert it is a populated datetime.
        assert isinstance(stored, datetime)


@pytest.mark.integration
class TestAContactsFeedCarriesTheirTaskRecords:
    """A task reaches a person's activity history through the field name.

    Task events project onto the **task** — ``entity_type='task'``,
    ``entity_id=task_id`` — and a contact's membership of one is recorded under
    ``contact:{id}``. ITER18-003 Phase 9 widens the contact aggregate to reach
    those rows, so a linked task appears on the contact's history as a read-only
    record of the link.

    The predicate deliberately never joins ``task_contacts`` or ``tasks``, and
    the two survival tests below are what say so in a way a join would fail.
    """

    @pytest.fixture
    def history_repo(
        self, clean_database: AsyncConnection
    ) -> SqlFieldHistoryRepository:
        return SqlFieldHistoryRepository(clean_database)

    async def _contact(self, conn: AsyncConnection, first_name: str) -> int:
        return await seed_contact(conn, first_name=first_name)

    async def _link_row(
        self,
        history_repo: SqlFieldHistoryRepository,
        *,
        task_id: int,
        contact_id: int,
        linked: bool = True,
        source: Provenance = Provenance.UI,
        changed_by: str = "ui",
        created_at: datetime | None = None,
        owner: str = USER_ID,
    ) -> None:
        """The row the projection writes for a link (or an unlink)."""
        await history_repo.record_change(
            FieldHistoryEntry(
                entity_type="task",
                entity_id=task_id,
                field_name=contact_field_name(contact_id),
                old_value=None if linked else str(contact_id),
                new_value=str(contact_id) if linked else None,
                changed_by=changed_by,
                source=source,
                event_id=f"evt-{task_id}-{contact_id}-{'link' if linked else 'unlink'}",
                created_at=created_at,
                user_id=owner,
            )
        )

    async def test_the_link_row_appears_on_the_contacts_feed(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        contact_id = await self._contact(clean_database, "Linked")

        await self._link_row(history_repo, task_id=task_id, contact_id=contact_id)

        entries = await history_repo.get_history_for_aggregate(
            "contact", contact_id, reader_user_id=USER_ID
        )

        assert [(e.entity_type, e.entity_id) for e in entries] == [("task", task_id)]
        assert entries[0].field_name == contact_field_name(contact_id)
        assert entries[0].source == Provenance.UI
        assert entries[0].changed_by == "ui"

    async def test_the_unlink_row_appears_too(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """Both halves of the pair, or the feed shows a removal with no addition."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        contact_id = await self._contact(clean_database, "Unlinked")

        await self._link_row(history_repo, task_id=task_id, contact_id=contact_id)
        await self._link_row(
            history_repo, task_id=task_id, contact_id=contact_id, linked=False
        )

        entries = await history_repo.get_history_for_aggregate(
            "contact", contact_id, reader_user_id=USER_ID
        )

        assert len(entries) == 2
        assert {(e.old_value, e.new_value) for e in entries} == {
            (None, str(contact_id)),
            (str(contact_id), None),
        }

    async def test_the_tasks_own_rows_stay_off_the_contacts_feed(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """Open decision 3: the contact entry records the link, and its end.

        A task's text, status, retarget and journal-link rows belong to the
        task's own history. Folding them in would make a person's page a place
        to watch commitments progress, which the specification's *Where tasks
        appear* rules out as a third working surface. The **delete marker** is
        the one exception and has its own class below: a hard delete is not
        progress, it is the end of the thing the record points at.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        contact_id = await self._contact(clean_database, "Quiet")
        await self._link_row(history_repo, task_id=task_id, contact_id=contact_id)

        for field, old, new in (
            ("__created__", None, "print the permit"),
            ("text", "print the permit", "print two permits"),
            ("status", "not_done", "done"),
            ("due_journal_id", str(due_id), str(creating_id)),
            (journal_field_name(creating_id), None, str(creating_id)),
        ):
            await history_repo.record_change(
                FieldHistoryEntry(
                    entity_type="task",
                    entity_id=task_id,
                    field_name=field,
                    old_value=old,
                    new_value=new,
                    event_id=f"evt-{task_id}-{field}",
                    user_id=USER_ID,
                )
            )

        entries = await history_repo.get_history_for_aggregate(
            "contact", contact_id, reader_user_id=USER_ID
        )

        assert [e.field_name for e in entries] == [contact_field_name(contact_id)]

    async def test_another_contacts_link_row_stays_off_this_feed(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        mine = await self._contact(clean_database, "Mine")
        theirs = await self._contact(clean_database, "Theirs")

        await self._link_row(history_repo, task_id=task_id, contact_id=mine)
        await self._link_row(history_repo, task_id=task_id, contact_id=theirs)

        entries = await history_repo.get_history_for_aggregate(
            "contact", mine, reader_user_id=USER_ID
        )

        assert [e.field_name for e in entries] == [contact_field_name(mine)]

    async def test_a_contact_whose_id_is_a_prefix_of_another_is_not_confused(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """``contact:1`` must not match ``contact:12``.

        The obvious wrong predicate is a ``LIKE 'contact:%'`` or a prefix test;
        both would put every task in the database on contact 1's feed the moment
        contact 12 was linked to one. Equality is what makes the branch safe, and
        this is the test that fails if it is ever relaxed.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        contact_id = await self._contact(clean_database, "Prefixed")

        await history_repo.record_change(
            FieldHistoryEntry(
                entity_type="task",
                entity_id=task_id,
                field_name=f"{contact_field_name(contact_id)}9",
                old_value=None,
                new_value="9",
                event_id=f"evt-{task_id}-decoy",
                user_id=USER_ID,
            )
        )

        entries = await history_repo.get_history_for_aggregate(
            "contact", contact_id, reader_user_id=USER_ID
        )

        assert entries == []

    async def test_the_record_survives_the_task_being_deleted(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """A hard-deleted task is still part of the person's past.

        This is the test a ``task_contacts`` join fails: the link row cascades
        away with the task, so a joined predicate would quietly empty the feed
        of everything that person ever committed to.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        contact_id = await self._contact(clean_database, "Remembered")
        await self._link_row(history_repo, task_id=task_id, contact_id=contact_id)

        await clean_database.execute(
            text("DELETE FROM tasks WHERE id = :id"), {"id": task_id}
        )

        entries = await history_repo.get_history_for_aggregate(
            "contact", contact_id, reader_user_id=USER_ID
        )

        assert [(e.entity_type, e.entity_id) for e in entries] == [("task", task_id)]

    async def test_the_record_survives_the_link_being_removed(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """Unlinking records a second entry; it does not erase the first."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        contact_id = await self._contact(clean_database, "Departed")
        await clean_database.execute(
            text("INSERT INTO task_contacts (task_id, contact_id) VALUES (:t, :c)"),
            {"t": task_id, "c": contact_id},
        )
        await self._link_row(history_repo, task_id=task_id, contact_id=contact_id)

        await clean_database.execute(
            text("DELETE FROM task_contacts WHERE task_id = :t AND contact_id = :c"),
            {"t": task_id, "c": contact_id},
        )

        entries = await history_repo.get_history_for_aggregate(
            "contact", contact_id, reader_user_id=USER_ID
        )

        assert len(entries) == 1

    async def test_the_count_agrees_with_the_list(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """The two statements share a predicate, so they have to share an answer.

        Pagination is computed from the count and rendered from the list; if the
        branch reached only one of them, a contact's feed would advertise a
        "Load More" that returns nothing.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        contact_id = await self._contact(clean_database, "Counted")
        await self._link_row(history_repo, task_id=task_id, contact_id=contact_id)
        await history_repo.record_change(
            FieldHistoryEntry(
                entity_type="contact",
                entity_id=contact_id,
                field_name="first_name",
                old_value="Counted",
                new_value="Recounted",
                event_id=f"evt-contact-{contact_id}",
            )
        )

        entries = await history_repo.get_history_for_aggregate(
            "contact", contact_id, reader_user_id=USER_ID
        )
        count = await history_repo.get_history_for_aggregate_count(
            "contact", contact_id, reader_user_id=USER_ID
        )

        assert count == 2
        assert len(entries) == 2

    async def test_task_and_contact_rows_interleave_most_recent_first(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """One ordering across both kinds of row, not two lists stapled together."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        contact_id = await self._contact(clean_database, "Ordered")
        base = datetime(2024, 5, 1, 9, 0, tzinfo=UTC)

        await history_repo.record_change(
            FieldHistoryEntry(
                entity_type="contact",
                entity_id=contact_id,
                field_name="first_name",
                old_value="Ordered",
                new_value="Reordered",
                event_id=f"evt-contact-early-{contact_id}",
                created_at=base,
            )
        )
        await self._link_row(
            history_repo,
            task_id=task_id,
            contact_id=contact_id,
            created_at=base + timedelta(minutes=5),
        )
        await history_repo.record_change(
            FieldHistoryEntry(
                entity_type="contact",
                entity_id=contact_id,
                field_name="last_name",
                old_value=None,
                new_value="Late",
                event_id=f"evt-contact-late-{contact_id}",
                created_at=base + timedelta(minutes=10),
            )
        )

        entries = await history_repo.get_history_for_aggregate(
            "contact", contact_id, reader_user_id=USER_ID
        )

        assert [e.field_name for e in entries] == [
            "last_name",
            contact_field_name(contact_id),
            "first_name",
        ]


@pytest.mark.integration
class TestADeletedTaskClosesItsOwnStoryOnTheContactsFeed:
    """The delete marker of a task the contact was linked to reaches their feed.

    Without it the feed keeps a "linked to a task" line for a task that no
    longer exists, and the only entry the person has about it reads as a
    commitment still standing.
    """

    @pytest.fixture
    def history_repo(
        self, clean_database: AsyncConnection
    ) -> SqlFieldHistoryRepository:
        return SqlFieldHistoryRepository(clean_database)

    @staticmethod
    async def _contact(conn: AsyncConnection, first_name: str) -> int:
        return await seed_contact(conn, first_name=first_name)

    @staticmethod
    async def _row(
        repo: SqlFieldHistoryRepository,
        *,
        task_id: int,
        field_name: str,
        new_value: str | None = None,
        created_at: datetime | None = None,
    ) -> None:
        await repo.record_change(
            FieldHistoryEntry(
                entity_type="task",
                entity_id=task_id,
                field_name=field_name,
                old_value=None,
                new_value=new_value,
                event_id=f"evt-{task_id}-{field_name}",
                created_at=created_at,
                user_id=USER_ID,
            )
        )

    async def test_the_delete_marker_reaches_a_linked_contacts_feed(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        contact_id = await self._contact(clean_database, "Bereaved")
        await self._row(
            history_repo,
            task_id=task_id,
            field_name=contact_field_name(contact_id),
            new_value=str(contact_id),
        )
        await self._row(history_repo, task_id=task_id, field_name=DELETED_MARKER)

        entries = await history_repo.get_history_for_aggregate(
            "contact", contact_id, reader_user_id=USER_ID
        )

        assert sorted(e.field_name for e in entries) == sorted(
            [contact_field_name(contact_id), DELETED_MARKER]
        )

    async def test_it_does_not_reach_the_feed_of_a_contact_never_linked(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """Otherwise every deleted task would land on every contact's page."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        linked = await self._contact(clean_database, "Linked")
        stranger = await self._contact(clean_database, "Stranger")
        await self._row(
            history_repo,
            task_id=task_id,
            field_name=contact_field_name(linked),
            new_value=str(linked),
        )
        await self._row(history_repo, task_id=task_id, field_name=DELETED_MARKER)

        entries = await history_repo.get_history_for_aggregate(
            "contact", stranger, reader_user_id=USER_ID
        )

        assert entries == []

    async def test_it_survives_the_tasks_row_being_gone(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """Which is the only state this branch exists to serve."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        contact_id = await self._contact(clean_database, "Remembering")
        await self._row(
            history_repo,
            task_id=task_id,
            field_name=contact_field_name(contact_id),
            new_value=str(contact_id),
        )
        await self._row(history_repo, task_id=task_id, field_name=DELETED_MARKER)
        await clean_database.execute(
            text("DELETE FROM tasks WHERE id = :id"), {"id": task_id}
        )

        entries = await history_repo.get_history_for_aggregate(
            "contact", contact_id, reader_user_id=USER_ID
        )

        assert DELETED_MARKER in {e.field_name for e in entries}

    async def test_it_is_counted_as_well_as_listed(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        contact_id = await self._contact(clean_database, "Counted")
        await self._row(
            history_repo,
            task_id=task_id,
            field_name=contact_field_name(contact_id),
            new_value=str(contact_id),
        )
        await self._row(history_repo, task_id=task_id, field_name=DELETED_MARKER)

        count = await history_repo.get_history_for_aggregate_count(
            "contact", contact_id, reader_user_id=USER_ID
        )

        assert count == 2


@pytest.mark.integration
class TestNamingTheTaskAHistoryRowIsAbout:
    """``get_task_labels`` resolves a task's name from history, in one query."""

    @pytest.fixture
    def history_repo(
        self, clean_database: AsyncConnection
    ) -> SqlFieldHistoryRepository:
        return SqlFieldHistoryRepository(clean_database)

    @staticmethod
    async def _row(
        repo: SqlFieldHistoryRepository,
        *,
        task_id: int,
        field_name: str,
        new_value: str | None,
        created_at: datetime,
        owner: str = USER_ID,
    ) -> None:
        await repo.record_change(
            FieldHistoryEntry(
                entity_type="task",
                entity_id=task_id,
                field_name=field_name,
                old_value=None,
                new_value=new_value,
                event_id=f"evt-{task_id}-{field_name}-{created_at.isoformat()}",
                created_at=created_at,
                user_id=owner,
            )
        )

    async def test_a_task_is_named_by_its_creation_marker(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        await self._row(
            history_repo,
            task_id=task_id,
            field_name=CREATED_MARKER,
            new_value="Book the venue",
            created_at=datetime(2024, 6, 1, 9, 0, tzinfo=UTC),
        )

        assert await history_repo.get_task_labels(
            [task_id], reader_user_id=USER_ID
        ) == {task_id: "Book the venue"}

    async def test_a_reworded_task_is_named_by_its_latest_wording(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        base = datetime(2024, 6, 1, 9, 0, tzinfo=UTC)
        await self._row(
            history_repo,
            task_id=task_id,
            field_name=CREATED_MARKER,
            new_value="Book the venue",
            created_at=base,
        )
        await self._row(
            history_repo,
            task_id=task_id,
            field_name="text",
            new_value="Book the other venue",
            created_at=base + timedelta(hours=1),
        )

        assert await history_repo.get_task_labels(
            [task_id], reader_user_id=USER_ID
        ) == {task_id: "Book the other venue"}

    async def test_a_deleted_tasks_name_is_still_resolvable(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """The state the whole design exists for."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        await self._row(
            history_repo,
            task_id=task_id,
            field_name=CREATED_MARKER,
            new_value="Return the harness",
            created_at=datetime(2024, 6, 1, 9, 0, tzinfo=UTC),
        )
        await clean_database.execute(
            text("DELETE FROM tasks WHERE id = :id"), {"id": task_id}
        )

        assert await history_repo.get_task_labels(
            [task_id], reader_user_id=USER_ID
        ) == {task_id: "Return the harness"}

    async def test_a_task_with_nothing_naming_it_is_simply_absent(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """Projection lags, so a task linked a second ago has no rows yet."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )

        assert (
            await history_repo.get_task_labels([task_id], reader_user_id=USER_ID) == {}
        )

    async def test_no_ids_asks_the_database_nothing(
        self, history_repo: SqlFieldHistoryRepository
    ) -> None:
        assert await history_repo.get_task_labels([], reader_user_id=USER_ID) == {}

    async def test_several_tasks_resolve_in_one_call(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """A page of history holds many task rows; it must not cost a query each."""
        creating_id, due_id = task_anchors
        base = datetime(2024, 6, 1, 9, 0, tzinfo=UTC)
        ids = []
        for i in range(3):
            task_id = await create_task(
                clean_database,
                creating_journal_id=creating_id,
                due_journal_id=due_id,
                text=f"task {i}",
            )
            ids.append(task_id)
            await self._row(
                history_repo,
                task_id=task_id,
                field_name=CREATED_MARKER,
                new_value=f"Task number {i}",
                created_at=base,
            )

        assert await history_repo.get_task_labels(ids, reader_user_id=USER_ID) == {
            task_id: f"Task number {i}" for i, task_id in enumerate(ids)
        }


@pytest.mark.integration
class TestAContactIsSharedButTheirTasksAreNot:
    """The one asymmetry this aggregate has to hold.

    ``contacts`` has no owner column and the contact history read authorises by
    existence alone, so any authenticated user can read any contact. Task rows
    *are* owned — and since ITER18-003 Phase 9 names them, an unscoped branch
    would hand one user another user's commitments **and their text** through a
    contact they happen to share.
    """

    @pytest.fixture
    def history_repo(
        self, clean_database: AsyncConnection
    ) -> SqlFieldHistoryRepository:
        return SqlFieldHistoryRepository(clean_database)

    @staticmethod
    async def _contact(conn: AsyncConnection, first_name: str) -> int:
        return await seed_contact(conn, first_name=first_name)

    async def _theirs(
        self,
        repo: SqlFieldHistoryRepository,
        *,
        task_id: int,
        contact_id: int,
    ) -> None:
        """A whole task record belonging to somebody else."""
        for field_name, new_value in (
            (CREATED_MARKER, "Their private commitment"),
            (contact_field_name(contact_id), str(contact_id)),
            (DELETED_MARKER, None),
        ):
            await repo.record_change(
                FieldHistoryEntry(
                    entity_type="task",
                    entity_id=task_id,
                    field_name=field_name,
                    old_value=None,
                    new_value=new_value,
                    event_id=f"evt-other-{task_id}-{field_name}",
                    user_id=OTHER_USER_ID,
                )
            )

    async def test_another_users_task_stays_off_a_shared_contacts_feed(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            user_id=OTHER_USER_ID,
        )
        contact_id = await self._contact(clean_database, "Shared")
        await self._theirs(history_repo, task_id=task_id, contact_id=contact_id)

        entries = await history_repo.get_history_for_aggregate(
            "contact", contact_id, reader_user_id=USER_ID
        )

        assert entries == []

    async def test_their_delete_marker_stays_off_it_too(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """The delete branch's *subquery* is scoped, not just its outer filter.

        Narrowing "which tasks was this contact linked to" by another user's
        link rows would leak exactly what the outer filter refuses.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            user_id=OTHER_USER_ID,
        )
        contact_id = await self._contact(clean_database, "Shared")
        await self._theirs(history_repo, task_id=task_id, contact_id=contact_id)

        entries = await history_repo.get_history_for_aggregate(
            "contact", contact_id, reader_user_id=USER_ID
        )

        assert DELETED_MARKER not in {e.field_name for e in entries}

    async def test_the_count_refuses_them_as_well_as_the_list(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """A count over a wider set is a disclosure of its own — and a broken page."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            user_id=OTHER_USER_ID,
        )
        contact_id = await self._contact(clean_database, "Shared")
        await self._theirs(history_repo, task_id=task_id, contact_id=contact_id)

        count = await history_repo.get_history_for_aggregate_count(
            "contact", contact_id, reader_user_id=USER_ID
        )

        assert count == 0

    async def test_their_task_is_not_nameable_either(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """The name is the task's text, so the naming query is scoped in its own right."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            user_id=OTHER_USER_ID,
        )
        contact_id = await self._contact(clean_database, "Shared")
        await self._theirs(history_repo, task_id=task_id, contact_id=contact_id)

        assert (
            await history_repo.get_task_labels([task_id], reader_user_id=USER_ID) == {}
        )

    async def test_the_owner_still_sees_their_own(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """The positive control: the filter must not empty the feed for everyone."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            user_id=OTHER_USER_ID,
        )
        contact_id = await self._contact(clean_database, "Shared")
        await self._theirs(history_repo, task_id=task_id, contact_id=contact_id)

        entries = await history_repo.get_history_for_aggregate(
            "contact", contact_id, reader_user_id=OTHER_USER_ID
        )

        assert {e.field_name for e in entries} == {
            contact_field_name(contact_id),
            DELETED_MARKER,
        }
        assert await history_repo.get_task_labels(
            [task_id], reader_user_id=OTHER_USER_ID
        ) == {task_id: "Their private commitment"}

    async def test_a_read_that_does_not_say_who_is_asking_sees_no_task_rows(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """Forgetting the reader costs the rows; it never exposes them.

        ``user_id = NULL`` is never true, so the default is fail-closed by
        construction rather than by a check somebody has to remember to write.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            clean_database, creating_journal_id=creating_id, due_journal_id=due_id
        )
        contact_id = await self._contact(clean_database, "Anonymous")
        await self._theirs(history_repo, task_id=task_id, contact_id=contact_id)

        entries = await history_repo.get_history_for_aggregate("contact", contact_id)
        count = await history_repo.get_history_for_aggregate_count(
            "contact", contact_id
        )

        assert entries == []
        assert count == 0
        assert await history_repo.get_task_labels([task_id]) == {}


@pytest.mark.integration
class TestAMergeCarriesTheTaskRecords:
    """The absorbed contact's task records move onto the survivor (ITER18-006 Phase 2).

    Phase 1 moved the ``task_contacts`` rows. It did not move what those links
    had already written down, and that half is invisible for the same reason the
    first half was: a contact's task record is filed on the **task**, and names
    the person only in ``field_name``, so deleting the contact leaves the row
    intact and unreachable. Nothing fails; the trail simply stops.

    **Why the real schema.** The two things being asserted are properties of the
    database. ``ux_field_history_event_dedup`` is what makes a task both people
    were linked to by one event a hard error rather than a cosmetic one, and the
    contact predicate's equality on ``contact:{id}`` is what decides whether a
    moved row is readable at all. Neither is observable against a double.
    """

    @pytest.fixture
    def history_repo(
        self, clean_database: AsyncConnection
    ) -> SqlFieldHistoryRepository:
        return SqlFieldHistoryRepository(clean_database)

    async def _contact(self, conn: AsyncConnection, first_name: str) -> int:
        return await seed_contact(conn, first_name=first_name)

    async def _task(
        self, conn: AsyncConnection, anchors: tuple[int, int], text_: str = "call back"
    ) -> int:
        creating_id, due_id = anchors
        return await create_task(
            conn,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text=text_,
        )

    async def _record(
        self,
        history_repo: SqlFieldHistoryRepository,
        *,
        task_id: int,
        contact_id: int,
        event_id: str,
        linked: bool = True,
        source: Provenance = Provenance.UI,
        changed_by: str = "ui",
        created_at: datetime | None = None,
        owner: str = USER_ID,
    ) -> None:
        """The row the projection writes when a task gains or loses a person."""
        await history_repo.record_change(
            FieldHistoryEntry(
                entity_type="task",
                entity_id=task_id,
                field_name=contact_field_name(contact_id),
                old_value=None if linked else str(contact_id),
                new_value=str(contact_id) if linked else None,
                changed_by=changed_by,
                source=source,
                event_id=event_id,
                created_at=created_at,
                user_id=owner,
            )
        )

    async def _feed_field_names(
        self, history_repo: SqlFieldHistoryRepository, contact_id: int
    ) -> list[str]:
        entries = await history_repo.get_history_for_aggregate(
            "contact", contact_id, reader_user_id=USER_ID
        )
        return [e.field_name for e in entries]

    async def _count_field(
        self, conn: AsyncConnection, *, entity_type: str, field_name: str
    ) -> int:
        result = await conn.execute(
            text(
                "SELECT COUNT(*) FROM field_history "
                "WHERE entity_type = :et AND field_name = :fn"
            ),
            {"et": entity_type, "fn": field_name},
        )
        return int(result.scalar_one())

    async def test_the_absorbed_contacts_records_reach_the_survivors_feed(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """Criterion 5, stated as the read it is about rather than as a row count."""
        absorbed = await self._contact(clean_database, "Sarah")
        survivor = await self._contact(clean_database, "Sara")
        first = await self._task(clean_database, task_anchors)
        second = await self._task(clean_database, task_anchors, "return the book")
        await self._record(
            history_repo, task_id=first, contact_id=absorbed, event_id="evt-1"
        )
        await self._record(
            history_repo, task_id=second, contact_id=absorbed, event_id="evt-2"
        )

        assert await self._feed_field_names(history_repo, survivor) == []

        moved = await history_repo.repoint_contact_task_history(
            absorbed, survivor, clean_database
        )

        assert moved == 2
        assert await self._feed_field_names(history_repo, survivor) == [
            contact_field_name(survivor),
            contact_field_name(survivor),
        ]
        assert await self._feed_field_names(history_repo, absorbed) == []

    async def test_an_unlink_record_moves_as_readily_as_a_link(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """The trail is the whole trail, not the flattering half of it.

        A person removed from a task is part of what happened to them, and the
        statement keys on the field name rather than on the direction, so both
        halves of a link-then-unlink pair arrive together.
        """
        absorbed = await self._contact(clean_database, "Sarah")
        survivor = await self._contact(clean_database, "Sara")
        task_id = await self._task(clean_database, task_anchors)
        await self._record(
            history_repo, task_id=task_id, contact_id=absorbed, event_id="evt-link"
        )
        await self._record(
            history_repo,
            task_id=task_id,
            contact_id=absorbed,
            event_id="evt-unlink",
            linked=False,
        )

        moved = await history_repo.repoint_contact_task_history(
            absorbed, survivor, clean_database
        )

        entries = await history_repo.get_history_for_aggregate(
            "contact", survivor, reader_user_id=USER_ID
        )
        assert moved == 2
        assert {(e.old_value, e.new_value) for e in entries} == {
            (None, str(absorbed)),
            (str(absorbed), None),
        }

    async def test_the_moved_row_keeps_its_provenance_event_and_owner(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """Every column that decides how a row reads, or whether it reads at all.

        ``user_id`` is the one that would fail loudest and most quietly: both
        task branches of the contact predicate are owner-scoped, so a row that
        lost its owner would disappear from **every** feed rather than surface
        on the wrong one. ``event_id`` is the other: the startup backfill treats
        any row bearing an event's id as proof that event was projected, so
        dropping it here would have the next restart rebuild the row this
        statement just moved.
        """
        absorbed = await self._contact(clean_database, "Sarah")
        survivor = await self._contact(clean_database, "Sara")
        task_id = await self._task(clean_database, task_anchors)
        occurred_at = datetime(2024, 3, 2, 8, 15, tzinfo=UTC)
        await self._record(
            history_repo,
            task_id=task_id,
            contact_id=absorbed,
            event_id="evt-provenance",
            source=Provenance.MCP,
            changed_by="agent",
            created_at=occurred_at,
        )

        await history_repo.repoint_contact_task_history(
            absorbed, survivor, clean_database
        )

        entries = await history_repo.get_history_for_aggregate(
            "contact", survivor, reader_user_id=USER_ID
        )
        assert len(entries) == 1
        moved = entries[0]
        assert moved.entity_type == "task"
        assert moved.entity_id == task_id
        assert moved.event_id == "evt-provenance"
        assert moved.source == Provenance.MCP
        assert moved.changed_by == "agent"
        # The read hands back an ISO string; what matters is that the instant is
        # the one the original change happened at, not the moment of the merge.
        assert moved.created_at == occurred_at.isoformat()

    async def test_a_task_both_people_were_on_collapses_to_one_row(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """The conflict clause is what stops this being a failed merge.

        One event can name both people — a task created with the pair on it
        writes a row per person under a single ``event_id`` — and once the
        absorbed contact's row takes the survivor's field name the two agree on
        all four columns of ``ux_field_history_event_dedup``. ``ON CONFLICT``
        cannot rescue an ``UPDATE``, which is why the statement copies and then
        deletes. **Removing ``ON CONFLICT DO NOTHING`` must fail this test**,
        which is the one thing asked of it.
        """
        absorbed = await self._contact(clean_database, "Sarah")
        survivor = await self._contact(clean_database, "Sara")
        task_id = await self._task(clean_database, task_anchors)
        for contact_id in (absorbed, survivor):
            await self._record(
                history_repo,
                task_id=task_id,
                contact_id=contact_id,
                event_id="evt-created-with-both",
            )

        moved = await history_repo.repoint_contact_task_history(
            absorbed, survivor, clean_database
        )

        # The absorbed row is dropped rather than duplicated: the survivor was
        # already on this task under this event and gained nothing.
        assert moved == 0
        assert await self._feed_field_names(history_repo, survivor) == [
            contact_field_name(survivor)
        ]
        assert (
            await self._count_field(
                clean_database,
                entity_type="task",
                field_name=contact_field_name(absorbed),
            )
            == 0
        )

    async def test_the_same_task_under_two_events_keeps_both_rows(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """The dedup key leads on ``event_id``, so this is not a collapse.

        Two people added to one task by two separate actions are two facts, and
        the survivor's feed should carry both after the merge. Without this the
        conflict clause could be over-read as "one row per task".
        """
        absorbed = await self._contact(clean_database, "Sarah")
        survivor = await self._contact(clean_database, "Sara")
        task_id = await self._task(clean_database, task_anchors)
        await self._record(
            history_repo, task_id=task_id, contact_id=absorbed, event_id="evt-added-her"
        )
        await self._record(
            history_repo, task_id=task_id, contact_id=survivor, event_id="evt-added-him"
        )

        moved = await history_repo.repoint_contact_task_history(
            absorbed, survivor, clean_database
        )

        assert moved == 1
        assert await self._feed_field_names(history_repo, survivor) == [
            contact_field_name(survivor),
            contact_field_name(survivor),
        ]

    async def test_re_running_the_move_changes_nothing(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """Idempotent: once the absorbed name is gone there is nothing to match."""
        absorbed = await self._contact(clean_database, "Sarah")
        survivor = await self._contact(clean_database, "Sara")
        task_id = await self._task(clean_database, task_anchors)
        await self._record(
            history_repo, task_id=task_id, contact_id=absorbed, event_id="evt-once"
        )

        first = await history_repo.repoint_contact_task_history(
            absorbed, survivor, clean_database
        )
        after_first = await self._feed_field_names(history_repo, survivor)
        second = await history_repo.repoint_contact_task_history(
            absorbed, survivor, clean_database
        )
        after_second = await self._feed_field_names(history_repo, survivor)

        assert (first, second) == (1, 0)
        assert after_first == after_second == [contact_field_name(survivor)]

    async def test_a_self_move_is_refused_rather_than_destructive(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """Moving a contact onto itself must not empty their feed.

        The copy would conflict on every row while the delete removed the
        originals, so the guard is the difference between a no-op and losing a
        person's entire task trail. The merge rejects a self-merge before it
        reaches here; the guard is for the caller that does not.
        """
        contact_id = await self._contact(clean_database, "Same")
        task_id = await self._task(clean_database, task_anchors)
        await self._record(
            history_repo, task_id=task_id, contact_id=contact_id, event_id="evt-self"
        )

        moved = await history_repo.repoint_contact_task_history(
            contact_id, contact_id, clean_database
        )

        assert moved == 0
        assert await self._feed_field_names(history_repo, contact_id) == [
            contact_field_name(contact_id)
        ]

    async def test_a_third_persons_records_are_untouched(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """Equality on the field name, never a prefix match.

        ``contact:1`` must not match ``contact:12``, which the read side already
        says in its own comment; the write side has to agree or a merge of one
        person would sweep up another's records.
        """
        absorbed = await self._contact(clean_database, "Sarah")
        survivor = await self._contact(clean_database, "Sara")
        bystander = await self._contact(clean_database, "Someone else")
        task_id = await self._task(clean_database, task_anchors)
        await self._record(
            history_repo, task_id=task_id, contact_id=absorbed, event_id="evt-hers"
        )
        await self._record(
            history_repo, task_id=task_id, contact_id=bystander, event_id="evt-theirs"
        )

        await history_repo.repoint_contact_task_history(
            absorbed, survivor, clean_database
        )

        assert await self._feed_field_names(history_repo, bystander) == [
            contact_field_name(bystander)
        ]
        assert await self._feed_field_names(history_repo, survivor) == [
            contact_field_name(survivor)
        ]

    async def test_the_contacts_own_history_rows_are_left_to_the_other_statement(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
    ) -> None:
        """The two re-points address disjoint sets, and this is what says so.

        ``repoint_entity_history`` moves ``entity_type='contact'`` rows by
        ``entity_id``; this one moves ``entity_type='task'`` rows by field name.
        A statement that reached both would move a contact's own edits twice.
        """
        absorbed = await self._contact(clean_database, "Sarah")
        survivor = await self._contact(clean_database, "Sara")
        await history_repo.record_change(
            FieldHistoryEntry(
                entity_type="contact",
                entity_id=absorbed,
                field_name="first_name",
                old_value="Sarah",
                new_value="Sarah Jane",
                event_id="evt-renamed",
            )
        )

        moved = await history_repo.repoint_contact_task_history(
            absorbed, survivor, clean_database
        )

        assert moved == 0
        rows = await history_repo.get_entity_history("contact", absorbed)
        assert [r.field_name for r in rows] == ["first_name"]

    async def test_the_delete_marker_of_a_moved_task_follows_it(
        self,
        history_repo: SqlFieldHistoryRepository,
        clean_database: AsyncConnection,
        task_anchors: tuple[int, int],
    ) -> None:
        """The marker rides on the link row, so moving one moves both.

        A hard-deleted task the absorbed contact was on reaches their feed
        through a subquery over the link rows, not through ``tasks`` — so the
        survivor inherits the ending as well as the commitment, and does so
        without this statement having to know the marker exists.
        """
        absorbed = await self._contact(clean_database, "Sarah")
        survivor = await self._contact(clean_database, "Sara")
        task_id = await self._task(clean_database, task_anchors)
        await self._record(
            history_repo, task_id=task_id, contact_id=absorbed, event_id="evt-linked"
        )
        await history_repo.record_change(
            FieldHistoryEntry(
                entity_type="task",
                entity_id=task_id,
                field_name=DELETED_MARKER,
                old_value=None,
                new_value=None,
                event_id="evt-deleted",
                user_id=USER_ID,
            )
        )
        await clean_database.execute(
            text("DELETE FROM tasks WHERE id = :id"), {"id": task_id}
        )

        await history_repo.repoint_contact_task_history(
            absorbed, survivor, clean_database
        )

        assert set(await self._feed_field_names(history_repo, survivor)) == {
            contact_field_name(survivor),
            DELETED_MARKER,
        }
        assert await self._feed_field_names(history_repo, absorbed) == []
