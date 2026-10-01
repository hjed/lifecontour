"""The event push and the cron push must never both create one contact in Google.

Greptile review of #1551: once the cron started pushing pending contacts, a new
contact could be picked up by the stream handler and the cron at the same time.
Both read "no sync link", both called Google's create, and — because
``sync_metadata`` is unique on ``(integration_source, external_id)``, not on the
local contact — both links committed: two Google contacts for one local contact.

Pushes of one contact are now serialised by a transaction-scoped advisory lock
taken before the link is read, and the cron re-reads the link under that lock
instead of trusting the list it selected earlier.
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest
from core_shared.testing.seeding import seed_contact
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from worker import _lock_contact_for_push, push_contacts_to_google

_TRY_LOCK = text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))")


@pytest.mark.asyncio
class TestContactPushLock:
    """The lock genuinely excludes a second transaction, per contact.

    Uses two real connections and writes no data: advisory locks live outside
    any table, and both transactions are rolled back.
    """

    async def test_second_transaction_cannot_take_the_same_contacts_lock(
        self, async_engine: Any
    ) -> None:
        async with async_engine.connect() as holder, async_engine.connect() as rival:
            await holder.begin()
            await rival.begin()
            try:
                await _lock_contact_for_push(holder, 4242)

                same = await rival.execute(
                    _TRY_LOCK, {"key": "google-contact-push:4242"}
                )
                other = await rival.execute(
                    _TRY_LOCK, {"key": "google-contact-push:4243"}
                )

                assert same.scalar_one() is False
                assert other.scalar_one() is True
            finally:
                await holder.rollback()
                await rival.rollback()

    async def test_lock_is_released_when_the_transaction_ends(
        self, async_engine: Any
    ) -> None:
        """Transaction-scoped: a commit or rollback frees the contact."""
        async with async_engine.connect() as holder, async_engine.connect() as rival:
            await holder.begin()
            await _lock_contact_for_push(holder, 4244)
            await holder.rollback()

            await rival.begin()
            try:
                freed = await rival.execute(
                    _TRY_LOCK, {"key": "google-contact-push:4244"}
                )
                assert freed.scalar_one() is True
            finally:
                await rival.rollback()


def _mock_google_client() -> AsyncMock:
    client = AsyncMock()
    client.create_contact.return_value = {
        "resourceName": "people/c-created-twice",
        "etag": "etag-created",
    }
    client.update_contact.return_value = {
        "resourceName": "people/c-already-linked",
        "etag": "etag-updated",
    }
    return client


@pytest.mark.asyncio
class TestCronRereadsTheLinkUnderTheLock:
    """A stale "create" decision must not survive a link written meanwhile."""

    async def test_link_written_after_selection_turns_the_create_into_an_update(
        self, db_session: AsyncSession
    ) -> None:
        """The cron selected the contact as new, then the event path linked it.

        This is the losing side of the race, made deterministic: the stale list
        still says ``create``, but the link now exists, so the push must update
        the linked person rather than create a duplicate.
        """
        contact_id = await seed_contact(
            db_session, first_name="Race", last_name="Loser"
        )

        # What find_contacts_to_push returned before the event path ran.
        stale = [
            {
                "id": contact_id,
                "first_name": "Race",
                "last_name": "Loser",
                "sync_action": "create",
                "external_id": None,
                "version_hash": None,
            }
        ]

        # The event path won: it created the person and committed the link.
        await db_session.execute(
            text(
                """
                INSERT INTO sync_metadata
                    (internal_id, integration_source, external_id,
                     version_hash, sync_status, last_synced_at,
                     internal_entity_type, external_entity_type,
                     created_at, updated_at)
                VALUES (:cid, 'google', 'people/c-already-linked', 'etag-linked',
                        'success', NOW(), 'contact', 'person', NOW(), NOW())
                """
            ),
            {"cid": contact_id},
        )
        await db_session.flush()

        mock_client = _mock_google_client()
        await push_contacts_to_google(
            session=db_session,
            client=mock_client,
            contacts=stale,
            google_account_email="race@example.com",
            group_name_to_resource={},
        )

        mock_client.create_contact.assert_not_called()
        mock_client.update_contact.assert_called_once()
        call = mock_client.update_contact.call_args[1]
        assert call["resource_name"] == "people/c-already-linked"
        assert call["etag"] == "etag-linked"

        links = await db_session.execute(
            text(
                """
                SELECT count(*) FROM sync_metadata
                WHERE integration_source = 'google' AND internal_id = :cid
                """
            ),
            {"cid": contact_id},
        )
        assert links.scalar_one() == 1

    async def test_contact_still_new_under_the_lock_is_created(
        self, db_session: AsyncSession
    ) -> None:
        """The re-read does not suppress a genuine create."""
        contact_id = await seed_contact(
            db_session, first_name="Genuinely", last_name="New"
        )
        await db_session.flush()

        mock_client = _mock_google_client()
        await push_contacts_to_google(
            session=db_session,
            client=mock_client,
            contacts=[
                {
                    "id": contact_id,
                    "first_name": "Genuinely",
                    "last_name": "New",
                    "sync_action": "create",
                    "external_id": None,
                    "version_hash": None,
                }
            ],
            google_account_email="race@example.com",
            group_name_to_resource={},
        )

        mock_client.create_contact.assert_called_once()
        mock_client.update_contact.assert_not_called()
