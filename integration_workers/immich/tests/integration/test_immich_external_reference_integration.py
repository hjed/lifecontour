"""
Integration tests for ImmichSyncService integration-link DB operations.

These exercise the raw SQL in ``_find_external_reference`` and
``_upsert_sync_metadata`` against a real PostgreSQL database via asyncpg.

Since ITER15-001 the worker writes the canonical link to ``sync_metadata`` only
(``external_references`` has been retired).
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


class TestExternalReferenceDbOperations:
    """Real-database tests for the integration-link SQL."""

    @pytest.mark.asyncio
    async def test_find_external_reference_reads_sync_metadata(
        self,
        sync_service: ImmichSyncService,
    ) -> None:
        """The link lookup resolves from the canonical sync_metadata store.

        It is absent before the link exists and is found once the
        ``sync_metadata`` link is written (no ``external_references`` row needed).
        """
        contact_id = 555
        person_id = "11111111-2222-3333-4444-555555555555"

        assert await sync_service._find_external_reference(person_id) is None

        await sync_service._upsert_sync_metadata(
            external_id=person_id,
            internal_id=contact_id,
            version_hash="vh-find",
        )

        found = await sync_service._find_external_reference(person_id)
        assert found is not None
        assert found.internal_entity_id == contact_id


class TestCreateVsUpdateReadsSyncMetadata:
    """The create-vs-update decision keys on the canonical sync_metadata link."""

    @pytest.mark.asyncio
    async def test_existing_sync_metadata_link_takes_update_path(
        self,
        sync_service: ImmichSyncService,
        async_connection: Any,
    ) -> None:
        """A person already linked via sync_metadata is not re-linked/created.

        With a ``sync_metadata`` link present, the worker must see the existing
        link and short-circuit to the unchanged/update path instead of
        name-matching and creating a duplicate.
        """
        result = await async_connection.execute(
            text(
                "INSERT INTO contacts (first_name, last_name) "
                "VALUES ('Synced', 'Person') RETURNING id"
            )
        )
        contact_id = int(result.fetchone().id)
        person_id = "sync-meta-existing-1"

        person = ImmichPerson(id=person_id, name="Synced Person")
        version_hash = sync_service.calculate_version_hash(person)
        await sync_service._upsert_sync_metadata(
            external_id=person_id,
            internal_id=contact_id,
            version_hash=version_hash,
        )

        outcome = await sync_service.sync_people_batch([person.model_dump()])

        # Found via sync_metadata, hash unchanged → no new link, no duplicate.
        assert outcome.linked == 0
        assert outcome.unchanged == 1


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
    """The name-match auto-link writes the canonical sync_metadata link only."""

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
    async def test_auto_link_writes_sync_metadata_only(
        self,
        sync_service: ImmichSyncService,
        async_connection: Any,
    ) -> None:
        """A single name match writes the canonical sync_metadata link."""
        result = await async_connection.execute(
            text(
                "INSERT INTO contacts (first_name, last_name) "
                "VALUES ('Autolink', 'Onlywrite') RETURNING id"
            )
        )
        contact_id = int(result.fetchone().id)
        person_id = "auto-link-person-1"

        person = ImmichPerson(id=person_id, name="Autolink Onlywrite")
        outcome = await sync_service.sync_people_batch([person.model_dump()])

        assert outcome.linked == 1

        # The canonical sync_metadata link is present and typed...
        row = await _fetch_sync_metadata(async_connection, person_id)
        assert row is not None
        assert row.internal_id == contact_id
        assert row.internal_entity_type == "contact"
        assert row.external_entity_type == "person"
