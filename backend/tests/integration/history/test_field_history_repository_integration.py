"""Integration tests for the generalised SqlFieldHistoryRepository."""

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
