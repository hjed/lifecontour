"""Integration tests for ImmichSyncService pending_entity_mapping DB operations.

These exercise the raw SQL in ``_create_pending_entity_mapping`` against a real
PostgreSQL database via asyncpg.

They guard against the ``PostgresSyntaxError`` ("syntax error at or near \":\"")
caused by binding the JSONB column as ``:candidate_contact_ids::jsonb``:
SQLAlchemy's textual bind-param parser will not treat a ``:name`` token that is
immediately followed by ``::`` as a parameter, so the literal ``:`` reaches
Postgres. The mocked unit tests cannot catch this; only a real asyncpg round
trip does.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from immich_sync_service import ImmichSyncService


@pytest.fixture
def sync_service(async_connection: Any) -> ImmichSyncService:
    """Build a sync service bound to the real test connection.

    The API client is mocked because these tests only exercise the
    database-access methods, which never touch the Immich API.
    """
    return ImmichSyncService(
        api_client=AsyncMock(),
        connection=async_connection,
        user_id="test-user-immich",
        integration_source="immich",
    )


class TestPendingEntityMappingDbOperations:
    """Real-database tests for the pending_entity_mapping SQL."""

    @pytest.mark.asyncio
    async def test_create_pending_entity_mapping_inserts_row(
        self,
        sync_service: ImmichSyncService,
        async_connection: Any,
    ) -> None:
        """Creating a pending mapping inserts an unresolved row with candidates.

        Regression test for the ``:candidate_contact_ids::jsonb`` bind-param
        bug: this raises ``PostgresSyntaxError`` before the fix.
        """
        person_id = "6b0d875a-e8c3-4621-9f88-f3535404ec89"

        await sync_service._create_pending_entity_mapping(
            person_id=person_id,
            person_name="Daryl Osborne",
            candidate_ids=[10, 20],
        )

        result = await async_connection.execute(
            text("""
                SELECT external_entity_name, candidate_contact_ids, status
                FROM pending_entity_mappings
                WHERE user_id = 'test-user-immich'
                  AND integration_source = 'immich'
                  AND external_entity_id = :person_id
            """),
            {"person_id": person_id},
        )
        row = result.fetchone()
        assert row is not None
        assert row.external_entity_name == "Daryl Osborne"
        assert row.candidate_contact_ids == [10, 20]
        assert row.status == "unresolved"
