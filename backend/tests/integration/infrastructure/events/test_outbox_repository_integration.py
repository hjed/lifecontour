"""Integration tests for OutboxRepository against the real outbox_events table."""

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.events.outbox_repository import OutboxRepository
from tests.integration.infrastructure.events.outbox_rows import (
    insert_outbox_event,
    relay_everything,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class TestCountUnrelayed:
    """``count_unrelayed`` is the outbox backlog: rows the relay has not published."""

    async def test_counts_the_events_not_yet_relayed(
        self, async_connection: AsyncConnection
    ) -> None:
        await relay_everything(async_connection)
        await insert_outbox_event(async_connection)
        await insert_outbox_event(async_connection)

        count = await OutboxRepository(async_connection).count_unrelayed()

        assert count == 2

    async def test_leaves_out_an_event_once_it_is_relayed(
        self, async_connection: AsyncConnection
    ) -> None:
        await relay_everything(async_connection)
        relayed = await insert_outbox_event(async_connection)
        await insert_outbox_event(async_connection)
        repository = OutboxRepository(async_connection)

        await repository.mark_as_relayed(relayed)

        assert await repository.count_unrelayed() == 1

    async def test_is_zero_when_every_event_is_relayed(
        self, async_connection: AsyncConnection
    ) -> None:
        await relay_everything(async_connection)
        await insert_outbox_event(async_connection)
        await relay_everything(async_connection)

        count = await OutboxRepository(async_connection).count_unrelayed()

        assert count == 0
