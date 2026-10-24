"""Integration tests: ``IntegrationLinkRepository.patch_reference_data`` (#1861).

A worker's push records the synced base on the link while the backend may be
recording its own keys on the same row. The patch is one statement that merges
into the stored JSON, so neither writer can drop the other's keys.
"""

import json

import pytest
from core_shared.repositories.integration_link_repository import (
    IntegrationLinkRepository,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.contact_seeding import TEST_USER_ID, seed_contact

OTHER_USER_ID = "other-user-456"
REMOTE = "people/cPATCH"


async def _seed_link(
    connection: AsyncConnection, *, user_id: str, reference_data: str | None
) -> None:
    contact_id = await seed_contact(connection, user_id=user_id)
    await connection.execute(
        text("""
            INSERT INTO sync_metadata (
                user_id, internal_id, integration_source, external_id,
                last_synced_at, version_hash, sync_status, internal_entity_type,
                external_entity_type, reference_data
            ) VALUES (
                :uid, :cid, 'google', :rid, now(), 'etag', 'success', 'contact',
                'person', :ref
            )
        """),
        {"uid": user_id, "cid": contact_id, "rid": REMOTE, "ref": reference_data},
    )


async def _reference_data(connection: AsyncConnection, user_id: str) -> object:
    result = await connection.execute(
        text("""
            SELECT reference_data FROM sync_metadata
            WHERE user_id = :uid AND external_id = :rid
        """),
        {"uid": user_id, "rid": REMOTE},
    )
    stored = result.scalar_one()
    return json.loads(stored) if stored is not None else None


@pytest.mark.integration
class TestPatchReferenceData:
    async def test_merges_into_the_stored_keys(
        self, clean_database: AsyncConnection
    ) -> None:
        await _seed_link(
            clean_database,
            user_id=TEST_USER_ID,
            reference_data=json.dumps({"synced_tags": ["a"], "pending_import": True}),
        )

        await IntegrationLinkRepository(clean_database).patch_reference_data(
            "google",
            REMOTE,
            {"synced_entries": {"emailAddresses": ["k"]}, "pending_import": False},
            user_id=TEST_USER_ID,
        )

        assert await _reference_data(clean_database, TEST_USER_ID) == {
            "synced_tags": ["a"],
            "synced_entries": {"emailAddresses": ["k"]},
            "pending_import": False,
        }

    @pytest.mark.parametrize("stored", [None, "not json", "[1, 2]"])
    async def test_unreadable_reference_data_starts_empty(
        self, clean_database: AsyncConnection, stored: str | None
    ) -> None:
        await _seed_link(clean_database, user_id=TEST_USER_ID, reference_data=stored)

        await IntegrationLinkRepository(clean_database).patch_reference_data(
            "google", REMOTE, {"pending_import": True}, user_id=TEST_USER_ID
        )

        assert await _reference_data(clean_database, TEST_USER_ID) == {
            "pending_import": True
        }

    async def test_patches_only_the_owners_link(
        self, clean_database: AsyncConnection
    ) -> None:
        await _seed_link(clean_database, user_id=TEST_USER_ID, reference_data="{}")
        await _seed_link(clean_database, user_id=OTHER_USER_ID, reference_data="{}")

        await IntegrationLinkRepository(clean_database).patch_reference_data(
            "google", REMOTE, {"pending_import": True}, user_id=TEST_USER_ID
        )

        assert await _reference_data(clean_database, OTHER_USER_ID) == {}
