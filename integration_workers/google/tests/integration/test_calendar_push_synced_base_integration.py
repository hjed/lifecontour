"""The journal push leaves alone what Google changed since the base (#1899).

Each test seeds a journal linked both ways to a Google event, and a fake
Google that applies each PATCH to its copy of the event and answers with the
whole event, as the API does. The link records the base — what both sides
last agreed on — and the tests check what the push sends and what it leaves
on the link.
"""

import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, time, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from core_shared.calendar_sync_base import google_event_keys, summary_key
from core_shared.sync_base import PENDING_IMPORT_KEY, SYNCED_ENTRIES_KEY
from googleapiclient.errors import HttpError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from worker import process_journal_event

START = datetime(2026, 11, 20, 1, tzinfo=UTC)
END = START + timedelta(hours=1)
EVENT_ID = "google-event-1"


def _google_event(**overrides: Any) -> dict[str, Any]:
    """Google's copy of the event, agreeing with the seeded journal."""
    event: dict[str, Any] = {
        "id": EVENT_ID,
        "etag": '"etag-0"',
        "summary": "Physio",
        "description": "notes",
        "location": "Clinic",
        "start": {"dateTime": "2026-11-20T01:00:00Z"},
        "end": {"dateTime": "2026-11-20T02:00:00Z"},
    }
    event.update(overrides)
    return event


class _FakeGoogle:
    """Applies each PATCH to its copy of the event, as the API does."""

    def __init__(
        self,
        event: dict[str, Any],
        during_patch: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.event = event
        self.patches: list[dict[str, Any]] = []
        self._during_patch = during_patch

    async def update_event(
        self, event_id: str, body: dict[str, Any], calendar_id: str = "primary"
    ) -> dict[str, Any]:
        assert event_id == EVENT_ID
        self.patches.append(dict(body))
        self.event = {**self.event, **body, "etag": f'"etag-{len(self.patches)}"'}
        if self._during_patch is not None:
            await self._during_patch()
        return dict(self.event)


def _agreed_base(**event_overrides: Any) -> str:
    keys = google_event_keys(_google_event(**event_overrides))
    return json.dumps(
        {SYNCED_ENTRIES_KEY: {field: [key] for field, key in keys.items()}}
    )


async def _seed(
    session: AsyncSession,
    *,
    reference_data: str | None,
    capability: str = "bidirectional",
    sync_status: str = "synced",
    calendar_info: dict[str, Any] | None = None,
) -> int:
    """A journal holding ``_google_event()``'s values, linked to that event."""
    user_id = str(uuid.uuid4())
    calendar_id = str(uuid.uuid4())
    await session.execute(
        text("""
            INSERT INTO user_google_auth (user_id, google_account_email,
                encrypted_access_token, encrypted_refresh_token, expires_at,
                created_at, updated_at)
            VALUES (:user_id, :email, 'x', 'y', now() + interval '1 hour',
                    now(), now())
        """),
        {"user_id": user_id, "email": f"{user_id}@example.com"},
    )
    await session.execute(
        text("""
            INSERT INTO calendars (id, user_id, name, color, google_calendar_id,
                                   is_synced_to_google)
            VALUES (:id, :user_id, 'Cal', '#FF0000', 'primary', true)
        """),
        {"id": calendar_id, "user_id": user_id},
    )
    journal_id = (
        await session.execute(
            text("""
                INSERT INTO journals (user_id, title, content,
                                      event_date_range_start, event_date_range_end)
                VALUES (:user_id, 'Physio', 'notes', :start, :end)
                RETURNING id
            """),
            {"user_id": user_id, "start": START, "end": END},
        )
    ).scalar_one()
    info = {
        "is_all_day": False,
        "location": "Clinic",
        "timezone": None,
        "start_time": None,
        "end_time": None,
    }
    info.update(calendar_info or {})
    await session.execute(
        text("""
            INSERT INTO journal_calendar_info (journal_id, calendar_id, is_all_day,
                location, timezone, start_time, end_time)
            VALUES (:journal_id, :calendar_id, :is_all_day, :location, :timezone,
                    :start_time, :end_time)
        """),
        {"journal_id": journal_id, "calendar_id": calendar_id, **info},
    )
    await session.execute(
        text("""
            INSERT INTO journal_external_event_links (journal_id, calendar_id,
                external_event_id, external_version, reference_data,
                sync_capability, sync_status, created_at, updated_at)
            VALUES (:journal_id, :calendar_id, :event_id, '"etag-0"',
                    :reference_data, :capability, :sync_status, now(), now())
        """),
        {
            "journal_id": journal_id,
            "calendar_id": calendar_id,
            "event_id": EVENT_ID,
            "reference_data": reference_data,
            "capability": capability,
            "sync_status": sync_status,
        },
    )
    await session.commit()
    return int(journal_id)


async def _edit(session: AsyncSession, journal_id: int, sql: str) -> None:
    """A local edit: ``sql`` runs with ``:id`` bound to the journal."""
    await session.execute(text(sql), {"id": journal_id})
    await session.commit()


async def _push(
    session: AsyncSession, journal_id: int, google: _FakeGoogle
) -> dict[str, Any]:
    @asynccontextmanager
    async def session_factory() -> AsyncIterator[AsyncSession]:
        yield session

    client = AsyncMock()
    client.update_event.side_effect = google.update_event
    with (
        patch("worker.GoogleAuthService", return_value=AsyncMock()),
        patch("worker.GoogleAPIClient", return_value=client),
    ):
        result: dict[str, Any] = await process_journal_event(
            ctx={"session_factory": session_factory, "job_id": "push"},
            event_type="JournalUpdated",
            event_data={"journal_id": journal_id, "changed_fields": {"title": 1}},
        )
    return result


async def _link(session: AsyncSession, journal_id: int) -> Any:
    result = await session.execute(
        text("""
            SELECT external_version, reference_data, sync_status
            FROM journal_external_event_links WHERE journal_id = :id
        """),
        {"id": journal_id},
    )
    return result.one()


async def _reference(session: AsyncSession, journal_id: int) -> dict[str, Any]:
    raw = (await _link(session, journal_id)).reference_data
    return json.loads(raw) if raw else {}


@pytest.mark.asyncio
class TestPushAgainstTheBase:
    async def test_sends_local_changes_and_leaves_googles_title(
        self, db_session: AsyncSession
    ) -> None:
        journal_id = await _seed(db_session, reference_data=_agreed_base())
        await _edit(
            db_session,
            journal_id,
            "UPDATE journals SET content = 'mine' WHERE id = :id",
        )
        google = _FakeGoogle(_google_event(summary="Physio (moved in Google)"))

        await _push(db_session, journal_id, google)

        assert google.patches == [{"description": "mine"}]
        assert google.event["summary"] == "Physio (moved in Google)"
        reference = await _reference(db_session, journal_id)
        assert reference[PENDING_IMPORT_KEY] is True
        assert (
            reference[SYNCED_ENTRIES_KEY]["summary"]
            == (json.loads(_agreed_base())[SYNCED_ENTRIES_KEY]["summary"])
        )
        assert (await _link(db_session, journal_id)).external_version == '"etag-1"'

    async def test_a_title_a_pull_imports_mid_push_keeps_its_base(
        self, db_session: AsyncSession
    ) -> None:
        """The push writes only the base fields it decided.

        A pull that imports Google's title while the PATCH is in flight
        records that title as agreed. Were the push to write back the whole
        base it read first, the imported title would look like a local edit:
        the next pull would refuse Google's next title, and the next push
        would overwrite it.
        """
        journal_id = await _seed(db_session, reference_data=_agreed_base())
        await _edit(
            db_session,
            journal_id,
            "UPDATE journals SET content = 'mine' WHERE id = :id",
        )

        async def pull_imports_the_title() -> None:
            await db_session.execute(
                text("UPDATE journals SET title = 'Physio (Google)' WHERE id = :id"),
                {"id": journal_id},
            )
            await db_session.execute(
                text("""
                    UPDATE journal_external_event_links
                    SET reference_data = jsonb_set(
                        reference_data::jsonb,
                        '{synced_entries,summary}',
                        CAST(:keys AS jsonb)
                    )::text
                    WHERE journal_id = :id
                """),
                {
                    "keys": json.dumps([summary_key("Physio (Google)")]),
                    "id": journal_id,
                },
            )

        google = _FakeGoogle(
            _google_event(summary="Physio (Google)"), pull_imports_the_title
        )

        await _push(db_session, journal_id, google)

        assert google.patches == [{"description": "mine"}]
        reference = await _reference(db_session, journal_id)
        assert reference[SYNCED_ENTRIES_KEY]["summary"] == [
            summary_key("Physio (Google)")
        ]

    async def test_a_revert_after_a_push_whose_answer_was_lost_is_sent(
        self,
        db_session: AsyncSession,
        google_http_error: Callable[[int, bytes], HttpError],
    ) -> None:
        """A failed push leaves the fields it sent unconfirmed.

        Google applied the rename but its answer never arrived, so the base
        still holds the old title. Were the push to leave it there, a local
        revert to that title would read as unchanged: the push would skip it,
        and the next pull would import the rename over the revert.
        """
        journal_id = await _seed(db_session, reference_data=_agreed_base())
        await _edit(
            db_session,
            journal_id,
            "UPDATE journals SET title = 'Physio (renamed)' WHERE id = :id",
        )
        google = _FakeGoogle(_google_event())

        async def answer_lost() -> None:
            raise google_http_error(503, b"backend error")

        lossy = _FakeGoogle(_google_event(), answer_lost)
        with pytest.raises(HttpError):
            await _push(db_session, journal_id, lossy)
        google.event = lossy.event
        await _edit(
            db_session,
            journal_id,
            "UPDATE journals SET title = 'Physio' WHERE id = :id",
        )

        await _push(db_session, journal_id, google)

        assert lossy.patches == [{"summary": "Physio (renamed)"}]
        assert google.patches == [{"summary": "Physio"}]
        assert google.event["summary"] == "Physio"

    async def test_a_second_push_still_leaves_googles_title(
        self, db_session: AsyncSession
    ) -> None:
        journal_id = await _seed(db_session, reference_data=_agreed_base())
        google = _FakeGoogle(_google_event(summary="Physio (moved in Google)"))
        await _edit(
            db_session,
            journal_id,
            "UPDATE journals SET content = 'mine' WHERE id = :id",
        )
        await _push(db_session, journal_id, google)

        # The pull has not imported the title yet when local edits again.
        await _edit(
            db_session,
            journal_id,
            "UPDATE journal_calendar_info SET location = 'Home' WHERE journal_id = :id",
        )
        await _push(db_session, journal_id, google)

        assert google.patches == [{"description": "mine"}, {"location": "Home"}]
        assert google.event["summary"] == "Physio (moved in Google)"

    async def test_never_sends_a_description_google_changed(
        self, db_session: AsyncSession
    ) -> None:
        journal_id = await _seed(db_session, reference_data=_agreed_base())
        google = _FakeGoogle(_google_event(description="Google's notes"))

        for title in ("Physio 1", "Physio 2"):
            await _edit(
                db_session,
                journal_id,
                f"UPDATE journals SET title = '{title}' WHERE id = :id",
            )
            await _push(db_session, journal_id, google)

        assert google.patches == [{"summary": "Physio 1"}, {"summary": "Physio 2"}]
        assert google.event["description"] == "Google's notes"
        # A pull never writes the description on an update: nothing to import.
        assert (await _reference(db_session, journal_id))[PENDING_IMPORT_KEY] is False

    async def test_sends_a_switch_to_all_day_as_start_and_end_together(
        self, db_session: AsyncSession
    ) -> None:
        journal_id = await _seed(db_session, reference_data=_agreed_base())
        await _edit(
            db_session,
            journal_id,
            "UPDATE journal_calendar_info SET is_all_day = true WHERE journal_id = :id",
        )
        google = _FakeGoogle(_google_event())

        await _push(db_session, journal_id, google)

        assert google.patches == [
            {"start": {"date": "2026-11-20"}, "end": {"date": "2026-11-21"}}
        ]

    async def test_with_nothing_changed_locally_calls_google_not_at_all(
        self, db_session: AsyncSession
    ) -> None:
        journal_id = await _seed(
            db_session, reference_data=_agreed_base(), sync_status="errored"
        )
        google = _FakeGoogle(_google_event(summary="Physio (moved in Google)"))

        result = await _push(db_session, journal_id, google)

        assert google.patches == []
        assert result["reason"] == "no_local_change"
        assert (await _link(db_session, journal_id)).sync_status == "synced"

    async def test_anchored_times_are_not_a_local_change(
        self, db_session: AsyncSession
    ) -> None:
        # The stored instant is an hour off the clock time the row records;
        # the push re-anchors it, and so must the comparison.
        journal_id = await _seed(
            db_session,
            reference_data=_agreed_base(
                start={"dateTime": "2026-11-20T13:00:00+11:00"},
                end={"dateTime": "2026-11-20T14:00:00+11:00"},
            ),
            calendar_info={
                "timezone": "Australia/Sydney",
                "start_time": time(13),
                "end_time": time(14),
            },
        )
        google = _FakeGoogle(_google_event())

        await _push(db_session, journal_id, google)

        assert google.patches == []


@pytest.mark.asyncio
class TestPushWithoutAMergeableBase:
    async def test_a_link_without_a_base_sends_everything_and_records_one(
        self, db_session: AsyncSession
    ) -> None:
        journal_id = await _seed(db_session, reference_data=None)
        google = _FakeGoogle(_google_event(summary="Physio (moved in Google)"))

        await _push(db_session, journal_id, google)

        assert set(google.patches[0]) == {
            "summary",
            "description",
            "location",
            "start",
            "end",
        }
        reference = await _reference(db_session, journal_id)
        assert set(reference[SYNCED_ENTRIES_KEY]) == {
            "summary",
            "description",
            "location",
            "when",
        }

    async def test_an_outbound_link_sends_everything_and_records_nothing(
        self, db_session: AsyncSession
    ) -> None:
        journal_id = await _seed(
            db_session, reference_data=_agreed_base(), capability="outbound"
        )
        google = _FakeGoogle(_google_event(summary="Physio (moved in Google)"))

        await _push(db_session, journal_id, google)

        assert google.patches[0]["summary"] == "Physio"
        assert (await _link(db_session, journal_id)).reference_data == (_agreed_base())

    async def test_before_the_migration_every_field_is_pushed_and_nothing_recorded(
        self, db_session: AsyncSession
    ) -> None:
        journal_id = await _seed(db_session, reference_data=_agreed_base())
        google = _FakeGoogle(_google_event(summary="Physio (moved in Google)"))

        with patch("worker.link_reference_data_ready", AsyncMock(return_value=False)):
            await _push(db_session, journal_id, google)

        assert google.patches[0]["summary"] == "Physio"
        assert (await _link(db_session, journal_id)).reference_data == (_agreed_base())
