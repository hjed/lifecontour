"""Integration tests for PendingEntityMappingRepository with a real database.

These exercise the raw SQL in ``create`` against real PostgreSQL via asyncpg.
They guard against the ``PostgresSyntaxError`` ("syntax error at or near
\":\"") caused by binding the JSONB column as ``:candidate_contact_ids::jsonb``:
SQLAlchemy's textual bind-param parser will not treat a ``:name`` token that is
immediately followed by ``::`` as a parameter, so the literal ``:`` reaches
Postgres. The mocked unit tests cannot catch this; only a real asyncpg round
trip does.
"""

from __future__ import annotations

import pytest
from core_shared.repositories.pending_entity_mapping_repository import (
    PendingEntityMappingRepository,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


@pytest.mark.integration
class TestPendingEntityMappingRepositoryIntegration:
    """Real-database tests for PendingEntityMappingRepository."""

    @pytest.fixture
    def repo(self, clean_database: AsyncConnection) -> PendingEntityMappingRepository:
        """Create the repository with a real database connection."""
        return PendingEntityMappingRepository(clean_database)

    @pytest.mark.asyncio
    async def test_create_inserts_unresolved_conflict_with_candidates(
        self,
        repo: PendingEntityMappingRepository,
        clean_database: AsyncConnection,
    ) -> None:
        """Creating a conflict persists a row with JSONB candidate IDs.

        Regression test for the ``:candidate_contact_ids::jsonb`` bind-param
        bug: this raises ``PostgresSyntaxError`` before the fix.
        """
        result = await repo.create(
            user_id="user-immich-1",
            integration_source="immich",
            external_entity_id="6b0d875a-e8c3-4621-9f88-f3535404ec89",
            external_entity_name="Daryl Osborne",
            candidate_contact_ids=[1, 2],
        )

        # Returned dict
        assert result["id"] is not None
        assert result["status"] == "unresolved"
        assert result["external_entity_name"] == "Daryl Osborne"
        assert result["candidate_contact_ids"] == [1, 2]

        # Persisted row
        db_result = await clean_database.execute(
            text("""
                SELECT external_entity_name, candidate_contact_ids, status
                FROM pending_entity_mappings
                WHERE user_id = :user_id
                  AND integration_source = :integration_source
                  AND external_entity_id = :external_entity_id
            """),
            {
                "user_id": "user-immich-1",
                "integration_source": "immich",
                "external_entity_id": "6b0d875a-e8c3-4621-9f88-f3535404ec89",
            },
        )
        row = db_result.fetchone()
        assert row is not None
        assert row.external_entity_name == "Daryl Osborne"
        assert row.candidate_contact_ids == [1, 2]
        assert row.status == "unresolved"
