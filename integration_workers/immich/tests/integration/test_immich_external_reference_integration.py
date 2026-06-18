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

from immich_models import ImmichPerson
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


async def _fetch_sync_metadata(connection: Any, person_id: str) -> Any:
    """Fetch the Immich sync_metadata row for a person, or None."""
    result = await connection.execute(
        text("""
            SELECT internal_id, internal_entity_type, external_entity_type,
                   version_hash
            FROM sync_metadata
            WHERE integration_source = 'immich'
              AND external_id = :person_id
        """),
        {"person_id": person_id},
    )
    return result.fetchone()


class TestAutoLinkDualWrite:
    """The name-match auto-link writes both link tables in one transaction."""

    @pytest.mark.asyncio
    async def test_upsert_sync_metadata_persists_entity_types(
        self,
        sync_service: ImmichSyncService,
        async_connection: Any,
    ) -> None:
        """The worker upsert persists contact/person entity types on real asyncpg."""
        await sync_service._upsert_sync_metadata(
            external_id="person-entity-types",
            internal_id=4242,
            version_hash="vh-1",
        )

        row = await _fetch_sync_metadata(async_connection, "person-entity-types")
        assert row is not None
        assert row.internal_id == 4242
        assert row.internal_entity_type == "contact"
        assert row.external_entity_type == "person"

    @pytest.mark.asyncio
    async def test_auto_link_writes_both_link_rows(
        self,
        sync_service: ImmichSyncService,
        async_connection: Any,
    ) -> None:
        """A single name match dual-writes external_references and sync_metadata."""
        result = await async_connection.execute(
            text(
                "INSERT INTO contacts (first_name, last_name) "
                "VALUES ('Autolink', 'Dualwrite') RETURNING id"
            )
        )
        contact_id = int(result.fetchone().id)
        person_id = "auto-link-person-1"

        person = ImmichPerson(id=person_id, name="Autolink Dualwrite")
        outcome = await sync_service.sync_people_batch([person.model_dump()])

        assert outcome.linked == 1

        # external_references link present.
        assert await _count_references(async_connection, person_id) == 1

        # paired sync_metadata link present, in the same transaction, typed.
        row = await _fetch_sync_metadata(async_connection, person_id)
        assert row is not None
        assert row.internal_id == contact_id
        assert row.internal_entity_type == "contact"
        assert row.external_entity_type == "person"
