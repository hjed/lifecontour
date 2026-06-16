"""Integration tests for the generalised SqlFieldHistoryRepository."""

from datetime import UTC, datetime

import pytest
from core_shared.models.history import Provenance
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.history.adapters.sql.field_history_repository import (
    SqlFieldHistoryRepository,
)
from app.core.history.models import FieldHistoryEntry, UnknownAggregationRootError


@pytest.mark.integration
class TestSqlFieldHistoryRepositoryIntegration:
    """Integration tests for the entity-agnostic field history repository."""

    @pytest.fixture
    def history_repo(
        self, clean_database: AsyncConnection
    ) -> SqlFieldHistoryRepository:
        return SqlFieldHistoryRepository(clean_database)

    async def _create_contact(self, conn: AsyncConnection, first_name: str) -> int:
        result = await conn.execute(
            text("INSERT INTO contacts (first_name) VALUES (:n) RETURNING id"),
            {"n": first_name},
        )
        return int(result.scalar_one())

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
            "contact", contact_id
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
