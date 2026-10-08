"""Integration tests for ``find_contacts_to_push`` against a real database.

The periodic push runs once per connected Google account, so it must read only
the contacts of that account's owner: another user's contacts are never pushed
into it, whether they are new locally or changed since their last sync.
"""

from datetime import UTC, datetime, timedelta

import pytest
from core_shared.testing.seeding import seed_contact
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from worker import find_contacts_to_push

OWNER = "owner-a"
OTHER_USER = "owner-b"


async def _link(
    db_session: AsyncSession, contact_id: int, external_id: str, synced_at: datetime
) -> None:
    """Record a Google link for ``contact_id``, last synced at ``synced_at``."""
    await db_session.execute(
        text(
            """
            INSERT INTO sync_metadata
                (user_id, internal_id, integration_source, external_id,
                 version_hash, sync_status, last_synced_at,
                 internal_entity_type, external_entity_type,
                 created_at, updated_at)
            VALUES ((SELECT user_id FROM contacts WHERE id = :cid), :cid, 'google', :ext, 'etag', 'success', :synced_at,
                    'contact', 'person', NOW(), NOW())
            """
        ),
        {"cid": contact_id, "ext": external_id, "synced_at": synced_at},
    )


@pytest.mark.asyncio
class TestFindContactsToPushIsPerOwner:
    """Only the owner's new and changed contacts are returned."""

    async def test_returns_only_the_owners_contacts(
        self, db_session: AsyncSession
    ) -> None:
        """New and changed contacts of another user are left out."""
        now = datetime.now(UTC)
        long_ago = now - timedelta(days=30)

        owner_new = await seed_contact(db_session, user_id=OWNER, first_name="New")
        owner_changed = await seed_contact(
            db_session, user_id=OWNER, first_name="Changed", updated_at=now
        )
        await _link(db_session, owner_changed, "people/owner-changed", long_ago)
        await seed_contact(db_session, user_id=OTHER_USER)
        other_changed = await seed_contact(
            db_session, user_id=OTHER_USER, first_name="Theirs", updated_at=now
        )
        await _link(db_session, other_changed, "people/other-changed", long_ago)
        await db_session.flush()

        contacts = await find_contacts_to_push(session=db_session, user_id=OWNER)

        actions = {c["id"]: c["sync_action"] for c in contacts}
        assert actions == {owner_new: "create", owner_changed: "update"}

    async def test_user_without_contacts_gets_nothing(
        self, db_session: AsyncSession
    ) -> None:
        """A user who owns no contacts pushes nothing, whatever others own."""
        await seed_contact(db_session, user_id=OTHER_USER)
        await db_session.flush()

        contacts = await find_contacts_to_push(session=db_session, user_id=OWNER)

        assert contacts == []
