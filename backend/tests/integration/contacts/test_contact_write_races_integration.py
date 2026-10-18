"""Two contact writes overlapping against real PostgreSQL lose neither.

Each test holds the first write's transaction open, starts the second, waits
until PostgreSQL reports it blocked on a lock, and only then lets the first
commit (see :mod:`tests.integration.concurrency_helpers`). A writer that read
the contact before taking its lock would by then hold a stale copy, and write
it back over the first writer's change.
"""

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.contacts.services.contact_patch import ContactFieldsPatch, ContactPatch
from app.infrastructure.unit_of_work import unit_of_work
from tests.integration.concurrency_helpers import (
    backend_pid,
    bounded,
    wait_until_blocked_on_a_lock,
)
from tests.integration.contacts.committed_contact import (
    committed_contact,
    contact_service_on,
    stored_contact,
)


@pytest.mark.integration
class TestOverlappingContactWrites:
    async def test_two_favourite_toggles_both_apply(
        self, async_engine: AsyncEngine
    ) -> None:
        """Toggled twice, a contact is back where it started - not toggled once."""
        async with committed_contact(async_engine, is_favourite=False) as (
            user_id,
            contact_id,
        ):
            async with (
                async_engine.connect() as first,
                async_engine.connect() as second,
            ):

                async def second_toggle() -> None:
                    await contact_service_on(second).toggle_contact_favourite(
                        contact_id, second, user_id=user_id
                    )

                second_pid = await backend_pid(second)
                async with unit_of_work(first):
                    await contact_service_on(first).toggle_contact_favourite(
                        contact_id, first, user_id=user_id
                    )
                    overlapping = asyncio.create_task(second_toggle())
                    await wait_until_blocked_on_a_lock(async_engine, second_pid)
                await bounded(overlapping)

            assert (
                await stored_contact(async_engine, contact_id, user_id)
            ).is_favourite is False

    async def test_a_partial_update_keeps_a_concurrent_change_it_did_not_name(
        self, async_engine: AsyncEngine
    ) -> None:
        """Issue #1557: a company change does not put back a rename made under it.

        The MCP tool used to read the contact, copy every field it was not
        asked to change from that read, and save the lot - so a rename
        committed between its read and its write was reverted.
        """
        async with committed_contact(
            async_engine, company="Analytical Engines Ltd"
        ) as (user_id, contact_id):
            async with (
                async_engine.connect() as renaming,
                async_engine.connect() as patching,
            ):

                async def patch_company() -> None:
                    await contact_service_on(patching).patch_contact(
                        contact_id,
                        ContactPatch(
                            fields=ContactFieldsPatch(company="Difference Engines Ltd")
                        ),
                        patching,
                        user_id=user_id,
                    )

                patching_pid = await backend_pid(patching)
                async with unit_of_work(renaming):
                    await contact_service_on(renaming).update_contact_field(
                        contact_id, "first_name", "Augusta", renaming, user_id=user_id
                    )
                    overlapping = asyncio.create_task(patch_company())
                    await wait_until_blocked_on_a_lock(async_engine, patching_pid)
                await bounded(overlapping)

            stored = await stored_contact(async_engine, contact_id, user_id)
            assert (stored.first_name, stored.company) == (
                "Augusta",
                "Difference Engines Ltd",
            )
