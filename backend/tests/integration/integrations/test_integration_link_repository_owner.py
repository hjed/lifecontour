"""Integration tests: ``IntegrationLinkRepository`` reads only the owner's links.

An external id is the owner's handle on a remote record, so a lookup by external
id is keyed by ``(user_id, integration_source, external_id)`` — another user's
link for the same id is never returned.
"""

import pytest
from core_shared.repositories.integration_link_repository import (
    IntegrationLinkRepository,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.contact_seeding import TEST_USER_ID, seed_contact

OTHER_USER_ID = "other-user-456"


async def _seed_person_link(
    connection: AsyncConnection, *, user_id: str, person_id: str
) -> int:
    contact_id = await seed_contact(connection, user_id=user_id)
    await connection.execute(
        text("""
            INSERT INTO sync_metadata (
                user_id, internal_id, integration_source, external_id,
                last_synced_at, version_hash, sync_status, internal_entity_type,
                external_entity_type
            ) VALUES (
                :uid, :cid, 'immich', :pid, now(), 'h', 'success', 'contact',
                'person'
            )
        """),
        {"uid": user_id, "cid": contact_id, "pid": person_id},
    )
    return contact_id


@pytest.mark.integration
class TestIntegrationLinkRepositoryOwner:
    async def test_a_link_by_external_id_is_the_owners_only(
        self, clean_database: AsyncConnection
    ) -> None:
        contact_id = await _seed_person_link(
            clean_database, user_id=OTHER_USER_ID, person_id="person-theirs"
        )
        repo = IntegrationLinkRepository(clean_database)

        mine = await repo.find_link_by_external(
            "immich", "person-theirs", user_id=TEST_USER_ID
        )
        theirs = await repo.find_link_by_external(
            "immich", "person-theirs", user_id=OTHER_USER_ID
        )

        assert mine is None
        assert theirs is not None
        assert theirs["internal_id"] == contact_id

    async def test_people_resolve_only_to_the_owners_contacts(
        self, clean_database: AsyncConnection
    ) -> None:
        mine = await _seed_person_link(
            clean_database, user_id=TEST_USER_ID, person_id="person-mine"
        )
        await _seed_person_link(
            clean_database, user_id=OTHER_USER_ID, person_id="person-theirs"
        )
        repo = IntegrationLinkRepository(clean_database)

        resolved = await repo.get_contact_ids_by_immich_person_ids(
            ["person-mine", "person-theirs"], user_id=TEST_USER_ID
        )

        assert resolved == {"person-mine": mine}

    async def test_a_contacts_person_is_found_only_by_its_owner(
        self, clean_database: AsyncConnection
    ) -> None:
        """The avatar proxy fetches whatever person this returns with the
        caller's own Immich key, so another user's link must not resolve."""
        contact_id = await _seed_person_link(
            clean_database, user_id=OTHER_USER_ID, person_id="person-theirs"
        )
        repo = IntegrationLinkRepository(clean_database)

        assert await repo.get_immich_person_id(contact_id, user_id=TEST_USER_ID) is None
        assert (
            await repo.get_immich_person_id(contact_id, user_id=OTHER_USER_ID)
            == "person-theirs"
        )
