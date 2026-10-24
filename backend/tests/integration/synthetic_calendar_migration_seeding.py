"""Seeding for the migrations that give each user their own synthetic calendar.

``app.migrations.synthetic_calendar_scoping`` moves an integration's rows and
pending events off one shared calendar; each revision using it is tested with
the same arrangement, for its own integration source and record ids. Raw SQL
throughout: a migration test runs against the schema of the revision before it,
which no repository describes.
"""

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.migration_helpers import execute


async def rows(url: str, sql: str) -> list[tuple[Any, ...]]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            return [tuple(row) for row in (await conn.execute(text(sql))).fetchall()]
    finally:
        await engine.dispose()


async def seed_calendar(
    url: str, calendar_id: str, owner: str, *, source: str, name: str
) -> None:
    await execute(
        url,
        """
        INSERT INTO calendars (id, user_id, name, color, integration_source)
        VALUES (CAST(:id AS uuid), :owner, :name, '#808080', :source)
        ON CONFLICT (id) DO NOTHING
        """,
        {"id": calendar_id, "owner": owner, "name": name, "source": source},
    )


async def seed_import(url: str, owner: str, external_id: str, calendar_id: str) -> int:
    """A journal imported from ``external_id``, linked on ``calendar_id``."""
    journal_id: int = await execute(
        url,
        """
        INSERT INTO journals (title, content, user_id,
            event_date_range_start, event_date_range_end)
        VALUES (:title, '', :owner, '2026-09-11', '2026-09-11')
        RETURNING id
        """,
        {"title": external_id, "owner": owner},
    )
    await execute(
        url,
        """
        INSERT INTO journal_external_event_links
            (journal_id, calendar_id, external_event_id, sync_capability, sync_status)
        VALUES (:journal_id, CAST(:calendar_id AS uuid), :external_id,
                'bidirectional', 'synced')
        """,
        {
            "journal_id": journal_id,
            "calendar_id": calendar_id,
            "external_id": external_id,
        },
    )
    await execute(
        url,
        """
        INSERT INTO journal_calendar_info (journal_id, calendar_id)
        VALUES (:journal_id, CAST(:calendar_id AS uuid))
        """,
        {"journal_id": journal_id, "calendar_id": calendar_id},
    )
    return journal_id


async def seed_merged_alias(
    url: str,
    owner: str,
    journal_id: int,
    external_id: str,
    *,
    source: str,
    calendar_id: str,
) -> None:
    await execute(
        url,
        """
        INSERT INTO journal_merged_aliases
            (journal_id, user_id, integration_source, external_id, calendar_id)
        VALUES (:journal_id, :owner, :source, :external_id,
                CAST(:calendar_id AS uuid))
        """,
        {
            "journal_id": journal_id,
            "owner": owner,
            "source": source,
            "external_id": external_id,
            "calendar_id": calendar_id,
        },
    )


async def seed_event(
    url: str,
    owner: str,
    *,
    source: str,
    calendar_id: str,
    external_event_id: str,
    relayed: bool = False,
    existing_journal_id: int | None = None,
) -> None:
    """A journal event the worker enqueued on ``calendar_id``: an update of
    ``existing_journal_id`` when given, otherwise a create."""
    sync_action = "created" if existing_journal_id is None else "updated"
    await execute(
        url,
        """
        INSERT INTO outbox_events
            (event_id, event_type, aggregate_id, event_data,
             occurred_at, created_at, retry_count, relayed_at)
        VALUES (gen_random_uuid()::text, :event_type, 0, :data,
                now(), now(), 0, CASE WHEN :relayed THEN now() END)
        """,
        {
            "event_type": f"journal_event.{sync_action}",
            "data": json.dumps(
                {
                    "integration_source": source,
                    "calendar_id": calendar_id,
                    "calendar_info_data": {"calendar_id": calendar_id},
                    "journal_data": {"user_id": owner},
                    "external_event_id": external_event_id,
                    "sync_action": sync_action,
                    "existing_journal_id": existing_journal_id,
                }
            ),
            "relayed": relayed,
        },
    )


async def event_targets(url: str) -> list[tuple[Any, ...]]:
    """Each event's ``(owner, event_type, sync_action, existing_journal_id)``."""
    found = await rows(
        url, "SELECT event_type, event_data FROM outbox_events ORDER BY id"
    )
    return [
        (
            data["journal_data"]["user_id"],
            event_type,
            data["sync_action"],
            data["existing_journal_id"],
        )
        for event_type, data in ((t, json.loads(raw)) for t, raw in found)
    ]


async def event_calendars(url: str) -> list[tuple[Any, ...]]:
    """Each create's ``(owner, relayed, calendar_id, calendar_info calendar_id)``."""
    found = await rows(
        url,
        "SELECT event_data, relayed_at IS NOT NULL FROM outbox_events "
        "WHERE event_type = 'journal_event.created' ORDER BY id",
    )
    return [
        (
            data["journal_data"]["user_id"],
            relayed,
            data["calendar_id"],
            data["calendar_info_data"]["calendar_id"],
        )
        for data, relayed in ((json.loads(raw), relayed) for raw, relayed in found)
    ]


async def link_calendars(url: str) -> list[tuple[Any, ...]]:
    """Each imported journal's ``(owner, link calendar, calendar_info calendar)``."""
    return await rows(
        url,
        "SELECT j.user_id, CAST(l.calendar_id AS text), CAST(i.calendar_id AS text) "
        "FROM journal_external_event_links l "
        "JOIN journals j ON j.id = l.journal_id "
        "JOIN journal_calendar_info i ON i.journal_id = j.id ORDER BY j.user_id",
    )
