"""An applied import records the addresses it skipped, for review (#1820).

The Google import leaves out an address whose region it cannot place and
reports it on the event. Each applied event replaces the contact's issues from
that source with the ones it carries - so fixing the address in Google clears
its flag on the next pull - while a dismissed one stays dismissed for as long
as Google still holds the same address.
"""

from __future__ import annotations

from typing import Any

import pytest
from core_shared.models.outbox import OutboxEvent
from core_shared.models.outbox_events import SkippedAddress
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.outbox_event_processor import OutboxEventProcessor
from tests.integration.contact_seeding import TEST_USER_ID
from tests.integration.integrations.link_consolidation_helpers import (
    build_contact_service,
)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_database")]

_LONDON = SkippedAddress(
    street_line_1="10 Downing St",
    locality="London",
    region="London",
    country_code="AU",
    reason="unrecognised_region",
)
_PARIS = SkippedAddress(
    street_line_1="1 Rue de Rivoli",
    region="Ile-de-France",
    country_code="AU",
    reason="unrecognised_region",
)


def _event(sync_type: str, *, etag: str, skipped: list[SkippedAddress]) -> OutboxEvent:
    return OutboxEvent.create_contact_sync_event(
        contact_data={"user_id": TEST_USER_ID, "first_name": "Kiri"},
        integration_source="google",
        external_id="people/cSkip",
        sync_type=sync_type,
        etag=etag,
        user_id=TEST_USER_ID,
        skipped_addresses=skipped,
    )


async def _apply(conn: AsyncConnection, event: OutboxEvent) -> dict[str, Any]:
    return await OutboxEventProcessor(build_contact_service(conn), conn).process_event(
        event
    )


async def _issues(conn: AsyncConnection) -> list[tuple[str, str, str]]:
    rows = await conn.execute(
        text(
            """
            SELECT payload->>'street_line_1' AS street, reason, status
            FROM contact_import_issues
            WHERE user_id = :user_id
            ORDER BY payload->>'street_line_1'
            """
        ),
        {"user_id": TEST_USER_ID},
    )
    return [(row.street, row.reason, row.status) for row in rows]


@pytest.mark.asyncio
async def test_a_created_contact_records_its_skipped_addresses(
    async_connection: AsyncConnection,
) -> None:
    result = await _apply(
        async_connection, _event("created", etag="e1", skipped=[_LONDON])
    )

    assert result["status"] == "success"
    assert await _issues(async_connection) == [
        ("10 Downing St", "unrecognised_region", "pending")
    ]


@pytest.mark.asyncio
async def test_an_update_replaces_the_issues_with_the_ones_it_carries(
    async_connection: AsyncConnection,
) -> None:
    await _apply(async_connection, _event("created", etag="e1", skipped=[_LONDON]))

    await _apply(async_connection, _event("updated", etag="e2", skipped=[_PARIS]))

    assert await _issues(async_connection) == [
        ("1 Rue de Rivoli", "unrecognised_region", "pending")
    ]


@pytest.mark.asyncio
async def test_fixing_the_address_at_the_source_clears_its_issue(
    async_connection: AsyncConnection,
) -> None:
    await _apply(async_connection, _event("created", etag="e1", skipped=[_LONDON]))

    await _apply(async_connection, _event("updated", etag="e2", skipped=[]))

    assert await _issues(async_connection) == []


@pytest.mark.asyncio
async def test_a_dismissed_issue_stays_dismissed_while_the_address_is_unchanged(
    async_connection: AsyncConnection,
) -> None:
    await _apply(async_connection, _event("created", etag="e1", skipped=[_LONDON]))
    await async_connection.execute(
        text("UPDATE contact_import_issues SET status = 'dismissed'")
    )

    await _apply(
        async_connection, _event("updated", etag="e2", skipped=[_LONDON, _PARIS])
    )

    assert await _issues(async_connection) == [
        ("1 Rue de Rivoli", "unrecognised_region", "pending"),
        ("10 Downing St", "unrecognised_region", "dismissed"),
    ]


@pytest.mark.asyncio
async def test_a_skipped_update_leaves_the_issues(
    async_connection: AsyncConnection,
) -> None:
    """An unchanged etag applies nothing, so the issues still match the contact."""
    await _apply(async_connection, _event("created", etag="e1", skipped=[_LONDON]))

    result = await _apply(async_connection, _event("updated", etag="e1", skipped=[]))

    assert result["status"] == "skipped"
    assert await _issues(async_connection) == [
        ("10 Downing St", "unrecognised_region", "pending")
    ]
