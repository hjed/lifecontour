"""Integration tests for adopting a journal after a recurrence re-keyed.

Moving a whole Google recurrence to a new time re-issues every instance id and
never cancels the old ones. The Google worker pairs each orphaned link with
the new instance on its day and sends that instance as an update of the old
journal carrying ``rekeyed_from``, the old event id. The journal must come out
re-pointed - new event id, new time, same journal and series - with local
edits intact; and an adoption the journal has since moved past must never
steal it.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from core_shared.calendar_sync_base import (
    CalendarSyncField,
    description_key,
    location_key,
    summary_key,
    when_key,
)
from core_shared.models.outbox import OutboxEvent
from core_shared.sync_base import SYNCED_ENTRIES_KEY
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.journal_outbox_event_processor import (
    JournalOutboxEventProcessor,
)
from app.core.journal.adapters.sql.journal_series_repository import (
    SqlJournalSeriesRepository,
)
from tests.integration.core.integrations.journal_sync_seeding import (
    USER_ID,
    build_processor,
    create_calendar,
    event_state,
    sync_event,
)

pytestmark = pytest.mark.integration

RECURRENCE = "dc7pp0jpb9fdfg6b6csu2jbfes"
OLD_START = (datetime.now(UTC) + timedelta(days=14)).replace(
    hour=3, minute=0, second=0, microsecond=0
)
NEW_START = OLD_START + timedelta(minutes=30)
OLD_ID = f"{RECURRENCE}_{OLD_START:%Y%m%dT%H%M%SZ}"
NEW_ID = f"{RECURRENCE}_{NEW_START:%Y%m%dT%H%M%SZ}"
LATER = datetime(2099, 1, 1, tzinfo=UTC)


def _keys(title: str, start: datetime) -> dict[str, list[str]]:
    """The base the worker sends for an instance holding these values."""

    def stamp(moment: datetime) -> dict[str, str]:
        return {"dateTime": moment.isoformat().replace("+00:00", "Z")}

    return {
        CalendarSyncField.SUMMARY: [summary_key(title)],
        CalendarSyncField.DESCRIPTION: [description_key("Synced from Google Calendar")],
        CalendarSyncField.LOCATION: [location_key(None)],
        CalendarSyncField.WHEN: [
            when_key(stamp(start), stamp(start + timedelta(hours=1)))
        ],
    }


def _event(
    event_type: str,
    calendar_id: str,
    external_event_id: str,
    start: datetime,
    *,
    title: str = "Retro",
    etag: str = '"etag-1"',
    existing_journal_id: int | None = None,
    rekeyed_from: str | None = None,
    synced: bool = True,
) -> OutboxEvent:
    event = sync_event(
        event_type,
        calendar_id=calendar_id,
        external_event_id=external_event_id,
        title=title,
        start=start,
        etag=etag,
        existing_journal_id=existing_journal_id,
        recurring_event_id=RECURRENCE,
        series_recurring_event_id=RECURRENCE,
    )
    if synced:
        event.event_data["synced_entries"] = _keys(title, start)
    event.event_data["rekeyed_from"] = rekeyed_from
    return event


async def _seed(
    processor: JournalOutboxEventProcessor, calendar_id: str, *, synced: bool = True
) -> int:
    created = await processor.process_event(
        _event("journal_event.created", calendar_id, OLD_ID, OLD_START, synced=synced)
    )
    assert created["status"] == "success"
    journal_id: int = created["journal_id"]
    return journal_id


def _adoption(
    calendar_id: str, journal_id: int, *, title: str = "Retro", synced: bool = True
) -> OutboxEvent:
    """The worker's adopting update: the new id and time, aimed at the journal."""
    return _event(
        "journal_event.updated",
        calendar_id,
        NEW_ID,
        NEW_START,
        title=title,
        etag='"etag-new"',
        existing_journal_id=journal_id,
        rekeyed_from=OLD_ID,
        synced=synced,
    )


async def _journal(connection: AsyncConnection, journal_id: int) -> Any:
    return (
        await connection.execute(
            text("""
                SELECT j.title, j.content, j.event_date_range_start,
                       l.external_event_id
                FROM journals j
                JOIN journal_external_event_links l ON l.journal_id = j.id
                WHERE j.id = :id
            """),
            {"id": journal_id},
        )
    ).one()


async def _base(connection: AsyncConnection, journal_id: int) -> dict[str, Any]:
    raw = (
        await connection.execute(
            text(
                "SELECT reference_data FROM journal_external_event_links"
                " WHERE journal_id = :id"
            ),
            {"id": journal_id},
        )
    ).scalar_one()
    recorded: dict[str, Any] = json.loads(raw)[SYNCED_ENTRIES_KEY]
    return recorded


async def _journal_ids(connection: AsyncConnection) -> list[int]:
    result = await connection.execute(
        text("SELECT id FROM journals WHERE user_id = :user_id ORDER BY id"),
        {"user_id": USER_ID},
    )
    return list(result.scalars())


async def _edit(
    connection: AsyncConnection,
    journal_id: int,
    *,
    at: datetime = LATER,
    **values: str,
) -> None:
    """A local edit made after the last sync (at ``at``)."""
    assignments = ", ".join(f"{column} = :{column}" for column in values)
    await connection.execute(
        text(
            f"UPDATE journals SET {assignments}, updated_at = :later"  # noqa: S608
            " WHERE id = :id"
        ),
        {**values, "later": at, "id": journal_id},
    )


class TestRekeyedAdoption:
    async def test_the_journal_is_repointed_at_the_new_instance(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journal_id = await _seed(processor, calendar_id)
        [series] = await SqlJournalSeriesRepository(
            async_connection
        ).get_series_for_journal(journal_id, USER_ID)
        await _edit(async_connection, journal_id, content="my notes")

        result = await processor.process_event(_adoption(calendar_id, journal_id))

        assert result["status"] == "success"
        assert result["journal_id"] == journal_id
        journal = await _journal(async_connection, journal_id)
        assert journal.external_event_id == NEW_ID
        assert journal.event_date_range_start == NEW_START
        assert journal.content == "my notes"
        assert await _journal_ids(async_connection) == [journal_id]
        # The base moved with the link and records the time it applied.
        assert set(
            (await _base(async_connection, journal_id))[CalendarSyncField.WHEN]
        ) == {*_keys("Retro", NEW_START)[CalendarSyncField.WHEN]}
        assert [
            s.id
            for s in await SqlJournalSeriesRepository(
                async_connection
            ).get_series_for_journal(journal_id, USER_ID)
        ] == [series.id]

    async def test_a_local_rename_survives_the_adoption(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journal_id = await _seed(processor, calendar_id)
        await _edit(async_connection, journal_id, title="My retro")

        await processor.process_event(_adoption(calendar_id, journal_id))

        journal = await _journal(async_connection, journal_id)
        assert journal.title == "My retro"
        assert journal.event_date_range_start == NEW_START

    async def test_a_local_rename_survives_an_adoption_without_a_base(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """Without a recorded base, local edits are judged against when the
        link last synced - the old link's time, not the re-point's."""
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journal_id = await _seed(processor, calendar_id, synced=False)
        await _edit(
            async_connection, journal_id, at=datetime.now(UTC), title="My retro"
        )

        await processor.process_event(
            _adoption(calendar_id, journal_id, title="Retro - NYX", synced=False)
        )

        journal = await _journal(async_connection, journal_id)
        assert journal.title == "My retro"
        assert journal.external_event_id == NEW_ID

    async def test_googles_rename_applies_with_the_adoption(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journal_id = await _seed(processor, calendar_id)

        await processor.process_event(
            _adoption(calendar_id, journal_id, title="Retro - NYX")
        )

        assert (await _journal(async_connection, journal_id)).title == "Retro - NYX"

    async def test_a_replayed_adoption_changes_nothing(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journal_id = await _seed(processor, calendar_id)
        await processor.process_event(_adoption(calendar_id, journal_id))

        await processor.process_event(_adoption(calendar_id, journal_id))

        assert await _journal_ids(async_connection) == [journal_id]
        assert (await _journal(async_connection, journal_id)).external_event_id == (
            NEW_ID
        )

    async def test_a_stale_adoption_creates_instead_of_stealing(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """The journal's link has moved on to a third event since the worker
        read it, so the new instance is a journal of its own."""
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journal_id = await _seed(processor, calendar_id)
        await async_connection.execute(
            text(
                "UPDATE journal_external_event_links"
                " SET external_event_id = 'elsewhere' WHERE journal_id = :id"
            ),
            {"id": journal_id},
        )

        result = await processor.process_event(_adoption(calendar_id, journal_id))

        assert result["status"] == "success"
        assert result["journal_id"] != journal_id
        assert (await _journal(async_connection, journal_id)).external_event_id == (
            "elsewhere"
        )
        created = await _journal(async_connection, result["journal_id"])
        assert created.external_event_id == NEW_ID
        assert created.event_date_range_start == NEW_START

    async def test_an_adoption_whose_journal_is_gone_creates_the_instance(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journal_id = await _seed(processor, calendar_id)
        await async_connection.execute(
            text("DELETE FROM journals WHERE id = :id"), {"id": journal_id}
        )

        result = await processor.process_event(_adoption(calendar_id, journal_id))

        assert result["status"] == "success"
        created = await _journal(async_connection, result["journal_id"])
        assert created.external_event_id == NEW_ID

    async def test_the_old_ids_cancellation_queued_after_is_skipped(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        calendar_id = await create_calendar(async_connection)
        processor = build_processor(async_connection)
        journal_id = await _seed(processor, calendar_id)
        await processor.process_event(_adoption(calendar_id, journal_id))

        result = await processor.process_event(
            _event(
                "journal_event.cancelled",
                calendar_id,
                OLD_ID,
                OLD_START,
                existing_journal_id=journal_id,
            )
        )

        assert result["status"] == "skipped"
        assert await event_state(async_connection, journal_id) == "confirmed"
