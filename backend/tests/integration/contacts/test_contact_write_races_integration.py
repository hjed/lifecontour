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
