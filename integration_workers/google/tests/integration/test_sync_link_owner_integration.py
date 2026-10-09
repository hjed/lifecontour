"""Integration tests: the Google worker reads and changes only the owner's links.

A Google person id is the owner's handle on a remote person, so every link
statement keyed by it is keyed by ``(user_id, 'google', external_id)``. Each
test seeds another user's link for the same person id and proves the owner's
statement neither sees nor changes it.
"""

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from worker import (
    _delete_sync_link,
    _find_existing_external_ids,
    _repoint_sync_link,
)

OWNER = "owner-a"
OTHER_USER = "owner-b"


async def _seed_link(
    db_session: AsyncSession, *, user_id: str, external_id: str
) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO sync_metadata
                (user_id, internal_id, integration_source, external_id,
                 version_hash, sync_status, last_synced_at,
                 internal_entity_type, external_entity_type,
                 created_at, updated_at)
            VALUES (:uid, 1, 'google', :ext, 'etag', 'success', NOW(),
                    'contact', 'person', NOW(), NOW())
            """
        ),
        {"uid": user_id, "ext": external_id},
    )


async def _links(db_session: AsyncSession) -> list[tuple[Any, ...]]:
    result = await db_session.execute(
        text(
            "SELECT user_id, external_id FROM sync_metadata "
            "WHERE integration_source = 'google' ORDER BY user_id, external_id"
        )
    )
    return [tuple(row) for row in result.fetchall()]


@pytest.mark.asyncio
class TestGoogleSyncLinksAreTheOwners:
    async def test_existing_ids_are_the_owners_only(
        self, db_session: AsyncSession
    ) -> None:
        await _seed_link(db_session, user_id=OWNER, external_id="people/mine")
        await _seed_link(db_session, user_id=OTHER_USER, external_id="people/theirs")

        existing = await _find_existing_external_ids(
            db_session, ["people/mine", "people/theirs"], "google", user_id=OWNER
        )

        assert existing == {"people/mine"}

    async def test_deleting_a_link_leaves_another_owners_alone(
        self, db_session: AsyncSession
    ) -> None:
        await _seed_link(db_session, user_id=OTHER_USER, external_id="people/shared")

        await _delete_sync_link(db_session, "people/shared", user_id=OWNER)

        assert await _links(db_session) == [(OTHER_USER, "people/shared")]

    async def test_repointing_a_link_leaves_another_owners_alone(
        self, db_session: AsyncSession
    ) -> None:
        await _seed_link(db_session, user_id=OTHER_USER, external_id="people/old")

        await _repoint_sync_link(db_session, "people/old", "people/new", user_id=OWNER)

        assert await _links(db_session) == [(OTHER_USER, "people/old")]
