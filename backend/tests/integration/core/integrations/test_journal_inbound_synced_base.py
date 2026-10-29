"""An applied calendar pull records, and honours, the synced base (#1899).

The journal push sends only the fields local changed since the base, so the
base an applied pull records decides what the next push leaves alone. These
tests drive the processor with events shaped like the Google worker's and
read the base back off the link:

* a field the journal now holds Google's value for advances to Google's key;
  one local kept (a local edit, or the description an update never writes)
  keeps its old key, so the push still sees which side moved;
* with a base, a field is protected only if local changed *that* field — a
  local content edit no longer holds back Google's title;
* ``pending_import`` applies an event whose etag is the push's own, without
  overwriting a local edit still to be pushed.
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
from core_shared.sync_base import PENDING_IMPORT_KEY, SYNCED_ENTRIES_KEY
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.journal_outbox_event_processor import (
    JournalOutboxEventProcessor,
)
from tests.integration.core.integrations.journal_sync_seeding import (
    build_processor,
    create_calendar,
    sync_event,
)

pytestmark = pytest.mark.integration

START = datetime(2026, 11, 20, 1, tzinfo=UTC)
END = START + timedelta(hours=1)
EVENT_ID = "synced-base-event"
FAR_FUTURE = datetime(2099, 1, 1, tzinfo=UTC)


def _when(start: datetime, end: datetime) -> str:
    return when_key(
        {"dateTime": start.isoformat().replace("+00:00", "Z")},
        {"dateTime": end.isoformat().replace("+00:00", "Z")},
    )


def _google_keys(
    *,
    title: str,
    description: str = "Synced from Google Calendar",
    location: str | None = None,
    start: datetime = START,
    end: datetime = END,
) -> dict[str, list[str]]:
    """The base the worker sends for an event holding these values."""
    return {
        CalendarSyncField.SUMMARY: [summary_key(title)],
        CalendarSyncField.DESCRIPTION: [description_key(description)],
        CalendarSyncField.LOCATION: [location_key(location)],
        CalendarSyncField.WHEN: [_when(start, end)],
    }


def _event(
    event_type: str,
    calendar_id: str,
    *,
    title: str,
    location: str | None = None,
    start: datetime = START,
    end: datetime = END,
    etag: str,
    existing_journal_id: int | None = None,
    synced: bool = True,
) -> OutboxEvent:
    event = sync_event(
        event_type,
        calendar_id=calendar_id,
        external_event_id=EVENT_ID,
        title=title,
        start=start,
        end=end,
        etag=etag,
        existing_journal_id=existing_journal_id,
    )
    if existing_journal_id is not None:
        # An update never carries the description: the worker sends it only
        # when the journal is created.
        del event.event_data["journal_data"]["content"]
    event.event_data["calendar_info_data"]["location"] = location
    if synced:
        event.event_data["synced_entries"] = _google_keys(
            title=title, location=location, start=start, end=end
        )
    return event


async def _created(
    processor: JournalOutboxEventProcessor, calendar_id: str, **fields: Any
) -> int:
    result = await processor.process_event(
        _event("journal_event.created", calendar_id, etag='"etag-1"', **fields)
    )
    assert result["status"] == "success"
    journal_id: int = result["journal_id"]
    return journal_id


async def _reference(connection: AsyncConnection, journal_id: int) -> dict[str, Any]:
    result = await connection.execute(
        text(
            "SELECT reference_data FROM journal_external_event_links"
            " WHERE journal_id = :id"
        ),
        {"id": journal_id},
    )
    raw = result.scalar()
    return json.loads(raw) if raw else {}


async def _base(connection: AsyncConnection, journal_id: int) -> dict[str, set[str]]:
    recorded = (await _reference(connection, journal_id)).get(SYNCED_ENTRIES_KEY)
    return {field: set(keys) for field, keys in (recorded or {}).items()}


async def _mark_pending_import(connection: AsyncConnection, journal_id: int) -> None:
    await connection.execute(
        text(
            """
            UPDATE journal_external_event_links
            SET reference_data = (reference_data::jsonb
                                  || '{"pending_import": true}'::jsonb)::text
            WHERE journal_id = :id
            """
        ),
        {"id": journal_id},
    )


async def _edit_journal(
    connection: AsyncConnection, journal_id: int, **values: object
) -> None:
    """A local edit made after the last sync, as the journal row records it."""
    assignments = ", ".join(f"{column} = :{column}" for column in values)
    await connection.execute(
        text(
            f"UPDATE journals SET {assignments}, updated_at = :later"  # noqa: S608
            " WHERE id = :id"
        ),
        {**values, "later": FAR_FUTURE, "id": journal_id},
    )


async def _set_location(
    connection: AsyncConnection, journal_id: int, location: str
) -> None:
    await connection.execute(
        text(
            "UPDATE journal_calendar_info SET location = :location"
            " WHERE journal_id = :id"
        ),
        {"location": location, "id": journal_id},
    )


async def _journal(connection: AsyncConnection, journal_id: int) -> Any:
    result = await connection.execute(
        text(
            """
            SELECT j.title, j.event_date_range_start, jci.location
            FROM journals j
            JOIN journal_calendar_info jci ON jci.journal_id = j.id
            WHERE j.id = :id
            """
        ),
        {"id": journal_id},
    )
    return result.one()


async def _update(
    processor: JournalOutboxEventProcessor,
    calendar_id: str,
    journal_id: int,
    *,
    etag: str = '"etag-2"',
    **fields: Any,
) -> dict[str, Any]:
    return await processor.process_event(
        _event(
            "journal_event.updated",
            calendar_id,
            etag=etag,
            existing_journal_id=journal_id,
            **fields,
        )
    )


class TestBaseRecordedByAnAppliedPull:
    async def test_a_created_event_records_every_field(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        processor = build_processor(async_connection)
        calendar = await create_calendar(async_connection)

        journal_id = await _created(
            processor, calendar, title="Physio", location="Clinic"
        )

        expected = _google_keys(title="Physio", location="Clinic")
        assert await _base(async_connection, journal_id) == {
            field: set(keys) for field, keys in expected.items()
        }

    async def test_an_update_advances_what_it_applied_and_keeps_the_description(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        processor = build_processor(async_connection)
        calendar = await create_calendar(async_connection)
        journal_id = await _created(processor, calendar, title="Physio")
        description_before = (await _base(async_connection, journal_id))[
            CalendarSyncField.DESCRIPTION
        ]

        await _update(processor, calendar, journal_id, title="Physio (moved)")

        base = await _base(async_connection, journal_id)
        assert base[CalendarSyncField.SUMMARY] == {summary_key("Physio (moved)")}
        assert base[CalendarSyncField.DESCRIPTION] == description_before

    async def test_an_event_without_a_base_clears_the_recorded_one(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        processor = build_processor(async_connection)
        calendar = await create_calendar(async_connection)
        journal_id = await _created(processor, calendar, title="Physio")

        await processor.process_event(
            _event(
                "journal_event.updated",
                calendar,
                title="Physio",
                etag='"etag-2"',
                existing_journal_id=journal_id,
                synced=False,
            )
        )

        assert await _base(async_connection, journal_id) == {}


class TestPerFieldProtection:
    async def test_googles_title_applies_despite_a_local_content_edit(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        processor = build_processor(async_connection)
        calendar = await create_calendar(async_connection)
        journal_id = await _created(processor, calendar, title="Physio")
        await _edit_journal(async_connection, journal_id, content="my notes")

        await _update(processor, calendar, journal_id, title="Physio (moved)")

        assert (await _journal(async_connection, journal_id)).title == "Physio (moved)"

    async def test_a_local_title_edit_is_kept_and_its_base_unchanged(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        processor = build_processor(async_connection)
        calendar = await create_calendar(async_connection)
        journal_id = await _created(processor, calendar, title="Physio")
        await _edit_journal(async_connection, journal_id, title="My physio")

        await _update(processor, calendar, journal_id, title="Physio (moved)")

        assert (await _journal(async_connection, journal_id)).title == "My physio"
        assert (await _base(async_connection, journal_id))[
            CalendarSyncField.SUMMARY
        ] == {summary_key("Physio")}

    async def test_a_local_time_edit_is_kept(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        processor = build_processor(async_connection)
        calendar = await create_calendar(async_connection)
        journal_id = await _created(processor, calendar, title="Physio")
        moved_locally = START + timedelta(days=1)
        await _edit_journal(
            async_connection,
            journal_id,
            event_date_range_start=moved_locally,
            event_date_range_end=moved_locally + timedelta(hours=1),
        )

        await _update(
            processor,
            calendar,
            journal_id,
            title="Physio",
            start=START + timedelta(hours=3),
            end=END + timedelta(hours=3),
        )

        journal = await _journal(async_connection, journal_id)
        assert journal.event_date_range_start == moved_locally

    async def test_a_local_location_edit_is_kept(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        processor = build_processor(async_connection)
        calendar = await create_calendar(async_connection)
        journal_id = await _created(
            processor, calendar, title="Physio", location="Clinic"
        )
        await _set_location(async_connection, journal_id, "Home visit")

        await _update(
            processor, calendar, journal_id, title="Physio", location="New clinic"
        )

        journal = await _journal(async_connection, journal_id)
        assert journal.location == "Home visit"
        assert (await _base(async_connection, journal_id))[
            CalendarSyncField.LOCATION
        ] == {location_key("Clinic")}

    async def test_googles_location_applies_when_local_left_it_alone(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        processor = build_processor(async_connection)
        calendar = await create_calendar(async_connection)
        journal_id = await _created(
            processor, calendar, title="Physio", location="Clinic"
        )

        await _update(
            processor, calendar, journal_id, title="Physio", location="New clinic"
        )

        assert (await _journal(async_connection, journal_id)).location == "New clinic"

    async def test_a_link_without_a_base_keeps_the_journal_wide_rule(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        processor = build_processor(async_connection)
        calendar = await create_calendar(async_connection)
        journal_id = await _created(processor, calendar, title="Physio", synced=False)
        await _edit_journal(async_connection, journal_id, content="my notes")

        await _update(processor, calendar, journal_id, title="Physio (moved)")

        # A local edit anywhere protects the title, as before bases existed.
        assert (await _journal(async_connection, journal_id)).title == "Physio"

    async def test_a_link_on_another_calendar_keeps_the_journal_wide_rule(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        # The push only keeps the displayed calendar's base current, so a
        # second calendar's base would protect a locally pushed title forever.
        processor = build_processor(async_connection)
        displayed = await create_calendar(async_connection, name="Displayed")
        other = await create_calendar(async_connection, name="Other")
        journal_id = await _created(processor, displayed, title="Physio")
        await async_connection.execute(
            text(
                """
                INSERT INTO journal_external_event_links
                    (journal_id, calendar_id, external_event_id,
                     external_version, reference_data, sync_capability,
                     sync_status, created_at, updated_at)
                VALUES (:journal_id, :calendar_id, :event_id, '"other-1"',
                        :reference_data, 'bidirectional', 'synced',
                        :now, :now)
                """
            ),
            {
                "journal_id": journal_id,
                "calendar_id": other,
                "event_id": "other-calendar-copy",
                "reference_data": json.dumps(
                    {SYNCED_ENTRIES_KEY: {"summary": [summary_key("Stale")]}}
                ),
                "now": FAR_FUTURE,
            },
        )
        event = _event(
            "journal_event.updated",
            other,
            title="Physio (moved)",
            etag='"other-2"',
            existing_journal_id=journal_id,
        )
        event.event_data["external_event_id"] = "other-calendar-copy"

        await processor.process_event(event)

        assert (await _journal(async_connection, journal_id)).title == "Physio (moved)"


class TestPendingImport:
    async def test_applies_an_unchanged_etag_and_clears(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        processor = build_processor(async_connection)
        calendar = await create_calendar(async_connection)
        journal_id = await _created(processor, calendar, title="Physio")
        await _mark_pending_import(async_connection, journal_id)

        # The push kept Google's title and recorded its own etag; the pull
        # then reads the event at that same etag.
        result = await _update(
            processor, calendar, journal_id, etag='"etag-1"', title="Physio (moved)"
        )

        assert result["status"] == "success"
        assert (await _journal(async_connection, journal_id)).title == "Physio (moved)"
        assert (await _reference(async_connection, journal_id))[
            PENDING_IMPORT_KEY
        ] is False

    async def test_never_overwrites_a_local_edit_still_to_push(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        processor = build_processor(async_connection)
        calendar = await create_calendar(async_connection)
        journal_id = await _created(processor, calendar, title="Physio")
        await _mark_pending_import(async_connection, journal_id)
        await _edit_journal(async_connection, journal_id, title="My physio")

        await _update(
            processor, calendar, journal_id, etag='"etag-1"', title="Physio (moved)"
        )

        assert (await _journal(async_connection, journal_id)).title == "My physio"

    async def test_an_unchanged_etag_without_it_is_still_skipped(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        processor = build_processor(async_connection)
        calendar = await create_calendar(async_connection)
        journal_id = await _created(processor, calendar, title="Physio")

        result = await _update(
            processor, calendar, journal_id, etag='"etag-1"', title="Physio (moved)"
        )

        assert result["reason"] == "etag_unchanged"
