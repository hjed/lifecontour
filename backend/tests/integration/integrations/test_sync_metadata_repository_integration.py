"""Integration tests for SyncMetadataRepository link-column writes.

Verifies that ``upsert`` persists the consolidated link columns
(``internal_entity_type``, ``external_entity_type``, ``reference_data``) to a
real database and that a later writer which omits them does not clobber the
existing values (COALESCE-on-conflict behaviour).
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.adapters.sql.sync_metadata_repository import (
    SyncMetadataRepository,
)


@pytest.mark.integration
class TestSyncMetadataRepositoryLinkColumns:
    """upsert persists and preserves the consolidated link columns."""

    async def test_upsert_persists_link_columns(
        self, clean_database: AsyncConnection
    ) -> None:
        repo = SyncMetadataRepository(clean_database)

        result = await repo.upsert(
            internal_id=101,
            integration_source="google",
            external_id="people/c-link-1",
            version_hash="hash-1",
            internal_entity_type="contact",
            external_entity_type="person",
            reference_data='{"etag": "abc"}',
        )

        assert result.internal_entity_type == "contact"
        assert result.external_entity_type == "person"
        assert result.reference_data == '{"etag": "abc"}'

        row = (
            await clean_database.execute(
                text(
                    "SELECT internal_entity_type, external_entity_type, "
                    "reference_data FROM sync_metadata "
                    "WHERE integration_source = 'google' "
                    "AND external_id = 'people/c-link-1'"
                )
            )
        ).fetchone()
        assert row is not None
        assert row.internal_entity_type == "contact"
        assert row.external_entity_type == "person"
        assert row.reference_data == '{"etag": "abc"}'

    async def test_upsert_without_link_columns_preserves_existing(
        self, clean_database: AsyncConnection
    ) -> None:
        repo = SyncMetadataRepository(clean_database)

        await repo.upsert(
            internal_id=202,
            integration_source="immich",
            external_id="person-link-2",
            version_hash="hash-1",
            internal_entity_type="contact",
            external_entity_type="person",
            reference_data='{"synced_tags": ["a"]}',
        )

        # A later writer (e.g. a worker still on the old code path) omits the
        # link columns; COALESCE must keep the previously-stored values.
        preserved = await repo.upsert(
            internal_id=202,
            integration_source="immich",
            external_id="person-link-2",
            version_hash="hash-2",
        )

        assert preserved.version_hash == "hash-2"
        assert preserved.internal_entity_type == "contact"
        assert preserved.external_entity_type == "person"
        assert preserved.reference_data == '{"synced_tags": ["a"]}'
