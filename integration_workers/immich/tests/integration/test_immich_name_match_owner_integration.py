"""Integration tests: the Immich name-match auto-link considers only the owner.

A person with no link is matched by name against local contacts. The candidates
are the syncing user's contacts only, so another user's contact of the same name
is neither linked nor counted as a second, conflicting candidate.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from core_shared.testing.seeding import seed_contact
from sqlalchemy import text

from immich_sync_service import ImmichSyncService

OWNER = "test-user-immich"
OTHER_USER = "other-user-immich"
PERSON_ID = "4f1e2d3c-0000-4000-8000-000000000001"


def _service(async_connection: Any) -> ImmichSyncService:
    """A sync service for ``OWNER`` on the real test connection."""
    return ImmichSyncService(
        api_client=AsyncMock(),
        connection=async_connection,
        user_id=OWNER,
        integration_source="immich",
    )


@pytest.mark.asyncio
class TestNameMatchIsPerOwner:
    """Auto-link candidates exclude another user's contacts."""

    async def test_links_the_owners_contact_not_the_other_users(
        self, async_connection: Any
    ) -> None:
        """Both users hold a "Sam Smith"; the person links to the owner's."""
        owners_sam = await seed_contact(
            async_connection, user_id=OWNER, first_name="Sam", last_name="Smith"
        )
        await seed_contact(
            async_connection, user_id=OTHER_USER, first_name="Sam", last_name="Smith"
        )

        result = await _service(async_connection).sync_people_batch(
            [{"id": PERSON_ID, "name": "Sam Smith", "isHidden": False}]
        )

        assert (result.linked, result.conflicts, result.created) == (1, 0, 0)
        link = await async_connection.execute(
            text(
                """
                SELECT internal_id FROM sync_metadata
                WHERE integration_source = 'immich' AND external_id = :person_id
                """
            ),
            {"person_id": PERSON_ID},
        )
        assert link.scalar_one() == owners_sam

    async def test_other_users_contact_is_not_a_candidate(
        self, async_connection: Any
    ) -> None:
        """Only another user holds the name: the person becomes a new contact."""
        await seed_contact(
            async_connection, user_id=OTHER_USER, first_name="Sam", last_name="Smith"
        )

        result = await _service(async_connection).sync_people_batch(
            [{"id": PERSON_ID, "name": "Sam Smith", "isHidden": False}]
        )

        assert (result.linked, result.conflicts, result.created) == (0, 0, 1)
