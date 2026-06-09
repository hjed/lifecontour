"""
Integration tests for ImmichSyncService external_reference DB operations.

These exercise the raw SQL in ``_create_external_reference`` and
``_find_external_reference`` against a real PostgreSQL database via asyncpg.

They guard against the asyncpg ``AmbiguousParameterError`` ("inconsistent
types deduced for parameter") that the mocked unit tests cannot catch: the
INSERT projects bind parameters bare in the SELECT list while reusing them in
the WHERE NOT EXISTS comparison, so the parameter types must be cast
consistently for asyncpg to accept the query.
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


async def _count_references(connection: Any, person_id: str) -> int:
    """Count external_references rows for an Immich person."""
    result = await connection.execute(
        text("""
            SELECT count(*) AS n
            FROM external_references
            WHERE external_system = 'immich'
              AND internal_entity_type = 'contact'
              AND external_entity_type = 'person'
              AND external_entity_id = :person_id
        """),
        {"person_id": person_id},
    )
    return int(result.fetchone().n)


class TestExternalReferenceDbOperations:
    """Real-database tests for the external_reference SQL."""

    @pytest.mark.asyncio
    async def test_create_external_reference_inserts_row(
        self,
        sync_service: ImmichSyncService,
        async_connection: Any,
    ) -> None:
        """Creating a reference inserts a correctly typed row.

        Regression test for the asyncpg AmbiguousParameterError: this fails
        against real asyncpg if the INSERT ... SELECT parameters are not cast.
        """
        contact_id = 436173
        person_id = "d796a719-ad3f-4a68-ba15-2dc5bc9a2651"

        await sync_service._create_external_reference(contact_id, person_id)

        result = await async_connection.execute(
            text("""
                SELECT internal_entity_type, internal_entity_id, external_system,
                       external_entity_type, external_entity_id
                FROM external_references
                WHERE external_system = 'immich'
                  AND external_entity_id = :person_id
            """),
            {"person_id": person_id},
        )
        row = result.fetchone()
        assert row is not None
        assert row.internal_entity_type == "contact"
        assert row.internal_entity_id == contact_id
        assert row.external_system == "immich"
        assert row.external_entity_type == "person"
        assert row.external_entity_id == person_id

    @pytest.mark.asyncio
    async def test_create_external_reference_is_idempotent(
        self,
        sync_service: ImmichSyncService,
        async_connection: Any,
    ) -> None:
        """The WHERE NOT EXISTS guard prevents duplicate references."""
        contact_id = 100
        person_id = "8eb4363b-4a27-4162-bf25-a07b4ac6e481"

        await sync_service._create_external_reference(contact_id, person_id)
        await sync_service._create_external_reference(contact_id, person_id)

        assert await _count_references(async_connection, person_id) == 1

    @pytest.mark.asyncio
    async def test_find_external_reference_round_trip(
        self,
        sync_service: ImmichSyncService,
    ) -> None:
        """A reference is absent before creation and found afterwards."""
        contact_id = 555
        person_id = "11111111-2222-3333-4444-555555555555"

        assert await sync_service._find_external_reference(person_id) is None

        await sync_service._create_external_reference(contact_id, person_id)

        found = await sync_service._find_external_reference(person_id)
        assert found is not None
        assert found.internal_entity_id == contact_id
