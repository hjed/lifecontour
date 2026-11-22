"""Integration tests for recurring-series handling in sync_calendar_events.

Covers the whole-series deletion signal (a single cancelled master event)
emitting a journal_event.series_cancelled outbox event, and the backfill
promotion of ETag-unchanged instances whose link predates the series feature.
"""

import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text

from worker import sync_calendar_events


def _as_dict(event_data: object) -> dict:
    """Normalize a raw outbox event_data column value to a dict."""
    if isinstance(event_data, str):
        return json.loads(event_data)
    assert isinstance(event_data, dict)
    return event_data


TEST_EMAIL = "series_sync_test@example.com"
TEST_USER = "22222222-2222-2222-2222-222222222222"
MASTER_ID = "recurring-master-abc"
ETAG = '"etag-series-1"'


async def _seed_calendar_with_recurring_instance(
    db_session,
    *,
    link_recurring_event_id: str | None,
) -> tuple[str, int]:
    """Seed a synced calendar plus one journal linked to a recurring instance."""
    now = datetime.now(UTC)
    calendar_uuid = str(uuid.uuid4())
    journal_id = int(datetime.now(UTC).timestamp() * 1000) % 1_000_000 + 5000

    await db_session.execute(
        text("""
            INSERT INTO calendars (id, user_id, name, color, created_at,
                updated_at, google_calendar_id, is_synced_to_google)
            VALUES (:cal_id, :user_id, 'Series Cal', '#00FF00', :now, :now,
                'primary', true)
        """),
        {"cal_id": calendar_uuid, "user_id": TEST_USER, "now": now},
    )
    await db_session.execute(
        text("""
            INSERT INTO journals (id, user_id, title, content,
                event_date_range_start, event_date_range_end,
                created_at, updated_at)
            VALUES (:journal_id, :user_id, 'Recurring Instance', '', :now,
                :now, :now, :now)
        """),
        {"journal_id": journal_id, "user_id": TEST_USER, "now": now},
    )
    await db_session.execute(
        text("""
            INSERT INTO journal_external_event_links
            (journal_id, calendar_id, external_event_id, external_version,
             recurring_event_id, sync_capability, sync_status,
             created_at, updated_at)
            VALUES (:journal_id, :cal_id, :external_event_id, :etag,
                :recurring_event_id, 'bidirectional', 'synced', :now, :now)
        """),
        {
            "journal_id": journal_id,
            "cal_id": calendar_uuid,
            "external_event_id": f"{MASTER_ID}_20260801T090000Z",
            "etag": ETAG,
            "recurring_event_id": link_recurring_event_id,
            "now": now,
        },
    )
    await db_session.commit()
    return calendar_uuid, journal_id


def _ctx(db_session) -> dict:
    @asynccontextmanager
    async def mock_session_factory():
        yield db_session

    return {
        "session_factory": mock_session_factory,
        "redis": AsyncMock(),
        "job_id": "test_series_job",
    }


async def _run_sync(db_session, items: list[dict]) -> dict:
    mock_client = MagicMock()
    mock_client.list_events = AsyncMock(
        return_value={"items": items, "nextSyncToken": "sync_token"}
    )
    with patch("worker._create_google_client", return_value=mock_client):
        return await sync_calendar_events(
            _ctx(db_session), TEST_EMAIL, TEST_USER, "smart"
        )


@pytest.mark.asyncio
class TestRecurringSeriesSyncIntegration:
    async def test_series_deletion_creates_series_cancelled_outbox_event(
        self, db_session
    ) -> None:
        """A cancelled master id with linked instances emits a series event."""
        calendar_uuid, _ = await _seed_calendar_with_recurring_instance(
            db_session, link_recurring_event_id=MASTER_ID
        )

        result = await _run_sync(
            db_session,
            [{"id": MASTER_ID, "status": "cancelled", "etag": '"etag-cancelled"'}],
        )

        assert result["status"] == "success"
        assert result.get("series_cancellations") == 1

        outbox = await db_session.execute(
            text("""
                SELECT event_data FROM outbox_events
                WHERE event_type = 'journal_event.series_cancelled'
            """)
        )
        rows = outbox.fetchall()
        assert len(rows) == 1
        event_data = _as_dict(rows[0].event_data)
        assert event_data["recurring_event_id"] == MASTER_ID
        assert event_data["calendar_id"] == calendar_uuid

    async def test_unchanged_instance_backfills_recurring_id_via_update(
        self, db_session
    ) -> None:
        """An ETag-unchanged instance with an unbackfilled link is promoted."""
        _, journal_id = await _seed_calendar_with_recurring_instance(
            db_session, link_recurring_event_id=None
        )

        result = await _run_sync(
            db_session,
            [
                {
                    "id": f"{MASTER_ID}_20260801T090000Z",
                    "summary": "Recurring Instance",
                    "etag": ETAG,  # unchanged
                    "status": "confirmed",
                    "recurringEventId": MASTER_ID,
                    "start": {"dateTime": "2026-08-01T09:00:00Z"},
                    "end": {"dateTime": "2026-08-01T10:00:00Z"},
                }
            ],
        )

        assert result["status"] == "success"

        outbox = await db_session.execute(
            text("""
                SELECT event_data FROM outbox_events
                WHERE event_type = 'journal_event.updated'
            """)
        )
        rows = outbox.fetchall()
        assert len(rows) == 1
        event_data = _as_dict(rows[0].event_data)
        assert event_data["recurring_event_id"] == MASTER_ID
        assert event_data["existing_journal_id"] == journal_id

    async def test_backfilled_unchanged_instance_stays_skipped(
        self, db_session
    ) -> None:
        """Once backfilled, unchanged instances create no further events."""
        await _seed_calendar_with_recurring_instance(
            db_session, link_recurring_event_id=MASTER_ID
        )

        result = await _run_sync(
            db_session,
            [
                {
                    "id": f"{MASTER_ID}_20260801T090000Z",
                    "summary": "Recurring Instance",
                    "etag": ETAG,  # unchanged
                    "status": "confirmed",
                    "recurringEventId": MASTER_ID,
                    "start": {"dateTime": "2026-08-01T09:00:00Z"},
                    "end": {"dateTime": "2026-08-01T10:00:00Z"},
                }
            ],
        )

        assert result["status"] == "success"
        assert result["events_skipped"] >= 1

        outbox = await db_session.execute(
            text(
                "SELECT count(*) FROM outbox_events WHERE event_type LIKE 'journal_event.%'"
            )
        )
        assert outbox.scalar() == 0

    async def test_series_deletion_detected_via_legacy_link_prefix(
        self, db_session
    ) -> None:
        """A legacy link (no backfilled recurring id) still gates the
        series_cancelled emission via the instance-id prefix fallback."""
        await _seed_calendar_with_recurring_instance(
            db_session, link_recurring_event_id=None
        )

        result = await _run_sync(
            db_session,
            [{"id": MASTER_ID, "status": "cancelled", "etag": '"etag-cancelled"'}],
        )

        assert result["status"] == "success"
        assert result.get("series_cancellations") == 1

        outbox = await db_session.execute(
            text("""
                SELECT count(*) FROM outbox_events
                WHERE event_type = 'journal_event.series_cancelled'
            """)
        )
        assert outbox.scalar() == 1


@pytest.mark.asyncio
class TestSplitAdoptionIntegration:
    """A "this and following" edit under an unrelated id, in one sync."""

    NEW_MASTER = "9p7kac2r5m992mshlenq0j10pf"

    @classmethod
    def _split_batch(cls, new_start: datetime) -> list[dict]:
        """One sync: the old instance cancelled, the new recurrence's live."""
        from datetime import timedelta

        return [
            {
                "id": f"{MASTER_ID}_old",
                "status": "cancelled",
                "etag": '"etag-cancelled"',
                "recurringEventId": MASTER_ID,
            },
            {
                "id": f"{cls.NEW_MASTER}_new",
                "status": "confirmed",
                "etag": '"etag-new"',
                "summary": "Pilates",
                "start": {"dateTime": new_start.isoformat()},
                "end": {"dateTime": (new_start + timedelta(hours=1)).isoformat()},
                "recurringEventId": cls.NEW_MASTER,
            },
        ]

    async def _seed_upcoming_instance(
        self, db_session, *, displayed_elsewhere: bool = False
    ) -> tuple[str, int, datetime]:
        from datetime import timedelta

        now = datetime.now(UTC)
        # Noon UTC (the user has no zone set): ten minutes later is the same
        # local day whatever time the test runs.
        start = (now + timedelta(days=7)).replace(
            hour=12, minute=0, second=0, microsecond=0
        )
        calendar_uuid = str(uuid.uuid4())
        await db_session.execute(
            text("""
                INSERT INTO calendars (id, user_id, name, color, created_at,
                    updated_at, google_calendar_id, is_synced_to_google)
                VALUES (:cal_id, :user_id, 'Split Cal', '#00FF00', :now, :now,
                    'primary', true)
            """),
            {"cal_id": calendar_uuid, "user_id": TEST_USER, "now": now},
        )
        journal_id = (
            await db_session.execute(
                text("""
                    INSERT INTO journals (user_id, title, content,
                        event_date_range_start, event_date_range_end,
                        created_at, updated_at)
                    VALUES (:user_id, 'Pilates', '', :start, :start, :now, :now)
                    RETURNING id
                """),
                {"user_id": TEST_USER, "start": start, "now": now},
            )
        ).scalar_one()
        await db_session.execute(
            text("""
                INSERT INTO journal_external_event_links
                (journal_id, calendar_id, external_event_id, external_version,
                 recurring_event_id, sync_capability, sync_status,
                 created_at, updated_at)
                VALUES (:journal_id, :cal_id, :external_event_id, :etag,
                    :master, 'bidirectional', 'synced', :now, :now)
            """),
            {
                "journal_id": journal_id,
                "cal_id": calendar_uuid,
                "external_event_id": f"{MASTER_ID}_old",
                "etag": ETAG,
                "master": MASTER_ID,
                "now": now,
            },
        )
        display_calendar = calendar_uuid
        if displayed_elsewhere:
            # A shared event: the journal belongs to another calendar, which
            # keys its series; this calendar only holds a copy.
            display_calendar = str(uuid.uuid4())
            await db_session.execute(
                text("""
                    INSERT INTO calendars (id, user_id, name, color, created_at,
                        updated_at, google_calendar_id, is_synced_to_google)
                    VALUES (:cal_id, :user_id, 'Owner Cal', '#0000FF', :now, :now,
                        'owner@example.com', false)
                """),
                {"cal_id": display_calendar, "user_id": TEST_USER, "now": now},
            )
        await db_session.execute(
            text("""
                INSERT INTO journal_calendar_info (journal_id, calendar_id, is_all_day)
                VALUES (:journal_id, :cal_id, false)
            """),
            {"journal_id": journal_id, "cal_id": display_calendar},
        )
        await db_session.commit()
        return calendar_uuid, journal_id, start

    async def test_the_new_instance_adopts_the_old_journal(self, db_session) -> None:
        from datetime import timedelta

        _, journal_id, start = await self._seed_upcoming_instance(db_session)
        new_start = start + timedelta(minutes=10)

        result = await _run_sync(
            db_session,
            self._split_batch(new_start),
        )

        assert result["status"] == "success"
        assert result.get("events_split_adopted") == 1
        outbox = await db_session.execute(
            text("""
                SELECT event_type, event_data FROM outbox_events
                WHERE event_type LIKE 'journal_event.%'
            """)
        )
        rows = outbox.fetchall()
        assert [row.event_type for row in rows] == ["journal_event.updated"]
        event_data = _as_dict(rows[0].event_data)
        assert event_data["existing_journal_id"] == journal_id
        assert event_data["external_event_id"] == f"{self.NEW_MASTER}_new"
        assert event_data["split_adopted_from"] == MASTER_ID

    async def test_a_journal_displayed_in_another_calendar_is_not_paired(
        self, db_session
    ) -> None:
        """Its series is keyed on the calendar it is displayed in, so adopting
        it through this one would start a second series."""
        from datetime import timedelta

        _, journal_id, start = await self._seed_upcoming_instance(
            db_session, displayed_elsewhere=True
        )
        new_start = start + timedelta(minutes=10)

        result = await _run_sync(
            db_session,
            self._split_batch(new_start),
        )

        assert result.get("events_split_adopted", 0) == 0
        outbox = await db_session.execute(
            text("""
                SELECT event_type FROM outbox_events
                WHERE event_type LIKE 'journal_event.%'
                ORDER BY event_type
            """)
        )
        assert [row.event_type for row in outbox] == [
            "journal_event.cancelled",
            "journal_event.created",
        ]


@pytest.mark.asyncio
class TestRekeyedRecurrenceIntegration:
    """A recurrence re-timed as a whole re-issues every instance id, and
    Google sends no cancellation for the old ones."""

    RECURRENCE = "dc7pp0jpb9fdfg6b6csu2jbfes"

    @staticmethod
    def _day(weeks: int, minute: int = 0) -> datetime:
        from datetime import timedelta

        # Mid-afternoon UTC (the user has no zone set), so half an hour later
        # is the same local day whatever time the test runs.
        return (datetime.now(UTC) + timedelta(weeks=weeks)).replace(
            hour=3, minute=minute, second=0, microsecond=0
        )

    @classmethod
    def _instance_id(cls, start: datetime) -> str:
        return f"{cls.RECURRENCE}_{start:%Y%m%dT%H%M%SZ}"

    @classmethod
    def _instance(cls, start: datetime) -> dict:
        from datetime import timedelta

        return {
            "id": cls._instance_id(start),
            "status": "confirmed",
            "etag": '"etag-rekeyed"',
            "summary": "Retro",
            "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": (start + timedelta(hours=1)).isoformat()},
            "recurringEventId": cls.RECURRENCE,
        }

    @staticmethod
    async def _calendar(db_session, *, sync_token: str | None = None) -> str:
        now = datetime.now(UTC)
        calendar_uuid = str(uuid.uuid4())
        await db_session.execute(
            text("""
                INSERT INTO calendars (id, user_id, name, color, created_at,
                    updated_at, google_calendar_id, is_synced_to_google)
                VALUES (:cal_id, :user_id, 'Rekey Cal', '#00FF00', :now, :now,
                    'primary', true)
            """),
            {"cal_id": calendar_uuid, "user_id": TEST_USER, "now": now},
        )
        if sync_token is not None:
            await db_session.execute(
                text("""
                    INSERT INTO calendar_sync_tokens
                        (user_id, google_account_email, google_calendar_id,
                         sync_token, last_synced_at, created_at, updated_at)
                    VALUES (:user_id, :email, 'primary', :token, :now, :now, :now)
                """),
                {
                    "user_id": TEST_USER,
                    "email": TEST_EMAIL,
                    "token": sync_token,
                    "now": now,
                },
            )
        await db_session.commit()
        return calendar_uuid

    @classmethod
    async def _linked_journal(
        cls,
        db_session,
        calendar_uuid: str,
        start: datetime,
        *,
        displayed: bool = True,
    ) -> int:
        now = datetime.now(UTC)
        journal_id = (
            await db_session.execute(
                text("""
                    INSERT INTO journals (user_id, title, content,
                        event_date_range_start, event_date_range_end,
                        created_at, updated_at)
                    VALUES (:user_id, 'Retro', '', :start, :start, :now, :now)
                    RETURNING id
                """),
                {"user_id": TEST_USER, "start": start, "now": now},
            )
        ).scalar_one()
        await db_session.execute(
            text("""
                INSERT INTO journal_external_event_links
                (journal_id, calendar_id, external_event_id, external_version,
                 recurring_event_id, sync_capability, sync_status,
                 created_at, updated_at)
                VALUES (:journal_id, :cal_id, :external_event_id, :etag,
                    :recurrence, 'bidirectional', 'synced', :now, :now)
            """),
            {
                "journal_id": journal_id,
                "cal_id": calendar_uuid,
                "external_event_id": cls._instance_id(start),
                "etag": ETAG,
                "recurrence": cls.RECURRENCE,
                "now": now,
            },
        )
        if displayed:
            await db_session.execute(
                text("""
                    INSERT INTO journal_calendar_info
                        (journal_id, calendar_id, is_all_day)
                    VALUES (:journal_id, :cal_id, false)
                """),
                {"journal_id": journal_id, "cal_id": calendar_uuid},
            )
        await db_session.commit()
        return journal_id

    @staticmethod
    async def _sync(
        db_session,
        items: list[dict],
        *,
        sync_type: str,
        instances: list[dict] | Exception | None = None,
        rule: str = "RRULE:FREQ=WEEKLY;BYDAY=MO",
    ) -> tuple[dict, MagicMock]:
        client = MagicMock()
        client.list_events = AsyncMock(
            return_value={"items": items, "nextSyncToken": "sync_token"}
        )
        client.list_instances = AsyncMock(
            side_effect=instances if isinstance(instances, Exception) else None,
            return_value=instances or [],
        )
        client.get_event = AsyncMock(
            return_value={
                "id": TestRekeyedRecurrenceIntegration.RECURRENCE,
                "recurrence": [rule],
            }
        )
        with patch("worker._create_google_client", return_value=client):
            result = await sync_calendar_events(
                _ctx(db_session), TEST_EMAIL, TEST_USER, sync_type
            )
        return result, client

    @staticmethod
    async def _outbox(db_session) -> list[tuple[str, dict]]:
        rows = await db_session.execute(
            text("""
                SELECT event_type, event_data FROM outbox_events
                WHERE event_type LIKE 'journal_event.%'
                ORDER BY occurred_at, id
            """)
        )
        return [(row.event_type, _as_dict(row.event_data)) for row in rows]

    async def test_an_incremental_re_time_adopts_every_old_journal(
        self, db_session
    ) -> None:
        from datetime import timedelta

        calendar_uuid = await self._calendar(db_session, sync_token="token")
        olds = [self._day(weeks) for weeks in (1, 2, 3)]
        news = [self._day(weeks, minute=30) for weeks in (1, 2, 3)]
        journals = [
            await self._linked_journal(db_session, calendar_uuid, olds[0]),
            # Displayed in no calendar: a re-key moves no series, so a link
            # alone is adopted too.
            await self._linked_journal(
                db_session, calendar_uuid, olds[1], displayed=False
            ),
            await self._linked_journal(db_session, calendar_uuid, olds[2]),
        ]
        live = [self._instance(start) for start in news]

        result, client = await self._sync(
            db_session, live, sync_type="incremental", instances=live
        )

        assert result["status"] == "success"
        assert result.get("events_rekey_adopted") == 3
        client.list_instances.assert_awaited_once_with(
            "primary", self.RECURRENCE, (olds[0] - timedelta(days=1)).isoformat()
        )
        outbox = await self._outbox(db_session)
        assert [event_type for event_type, _ in outbox] == ["journal_event.updated"] * 3
        assert sorted(
            (
                data["existing_journal_id"],
                data["external_event_id"],
                data["rekeyed_from"],
            )
            for _, data in outbox
        ) == sorted(
            (journal_id, self._instance_id(new), self._instance_id(old))
            for journal_id, old, new in zip(journals, olds, news, strict=True)
        )

    async def test_a_full_listing_cancels_only_the_orphans_inside_its_window(
        self, db_session
    ) -> None:
        """No unlinked instance needed: the listing is Google's whole view.
        A link past the last instance Google returned may still be live."""
        calendar_uuid = await self._calendar(db_session)
        orphan_start = self._day(1)
        live_start, last_start = self._day(2, minute=30), self._day(3, minute=30)
        beyond_start = self._day(10)
        orphan = await self._linked_journal(db_session, calendar_uuid, orphan_start)
        for start in (live_start, last_start, beyond_start):
            await self._linked_journal(db_session, calendar_uuid, start)

        result, client = await self._sync(
            db_session,
            [self._instance(live_start), self._instance(last_start)],
            sync_type="full",
        )

        assert result["status"] == "success"
        client.list_instances.assert_not_awaited()
        cancelled = [
            data
            for event_type, data in await self._outbox(db_session)
            if event_type == "journal_event.cancelled"
        ]
        assert [
            (d["existing_journal_id"], d["external_event_id"]) for d in cancelled
        ] == [(orphan, self._instance_id(orphan_start))]
        assert cancelled[0]["recurring_event_id"] == self.RECURRENCE

    async def test_an_incremental_batch_of_linked_instances_asks_google_nothing(
        self, db_session
    ) -> None:
        calendar_uuid = await self._calendar(db_session, sync_token="token")
        start = self._day(1)
        await self._linked_journal(db_session, calendar_uuid, start)
        await self._linked_journal(db_session, calendar_uuid, self._day(2))

        result, client = await self._sync(
            db_session, [self._instance(start)], sync_type="incremental"
        )

        assert result["status"] == "success"
        client.list_instances.assert_not_awaited()

    async def test_a_failed_instances_listing_retires_nothing(self, db_session) -> None:
        """The recurrence may be gone altogether; its master's cancellation
        handles that. The rest of the sync goes on."""
        from googleapiclient.errors import HttpError

        calendar_uuid = await self._calendar(db_session, sync_token="token")
        await self._linked_journal(db_session, calendar_uuid, self._day(1))
        new = self._instance(self._day(1, minute=30))

        result, _ = await self._sync(
            db_session,
            [new],
            sync_type="incremental",
            instances=HttpError(resp=MagicMock(status=404), content=b"gone"),
        )

        assert result["status"] == "success"
        assert [event_type for event_type, _ in await self._outbox(db_session)] == [
            "journal_event.created"
        ]

    async def test_an_earlier_finite_series_adopts_its_last_occurrence(
        self, db_session
    ) -> None:
        """Moved earlier, the last old occurrence starts after the last new
        one. A rule with an end is listed whole, so it is still adopted."""
        from datetime import timedelta

        calendar_uuid = await self._calendar(db_session)
        olds = [self._day(weeks) for weeks in (1, 2, 3)]
        news = [start - timedelta(hours=1) for start in olds]
        journals = [
            await self._linked_journal(db_session, calendar_uuid, start)
            for start in olds
        ]

        result, _ = await self._sync(
            db_session,
            [self._instance(start) for start in news],
            sync_type="full",
            rule="RRULE:FREQ=WEEKLY;COUNT=3",
        )

        assert result.get("events_rekey_adopted") == 3
        adopted = {
            data["existing_journal_id"]
            for event_type, data in await self._outbox(db_session)
            if event_type == "journal_event.updated"
        }
        assert adopted == set(journals)

    async def test_an_earlier_endless_series_adopts_its_last_listed_day(
        self, db_session
    ) -> None:
        """Endless, Google lists only so far: a link on the last listed day is
        covered, one on a later day is not."""
        from datetime import timedelta

        calendar_uuid = await self._calendar(db_session)
        last_old, beyond = self._day(2), self._day(3)
        last_journal = await self._linked_journal(db_session, calendar_uuid, last_old)
        await self._linked_journal(db_session, calendar_uuid, beyond)

        result, _ = await self._sync(
            db_session,
            [self._instance(last_old - timedelta(hours=1))],
            sync_type="full",
        )

        assert result.get("events_rekey_adopted") == 1
        assert [
            (event_type, data["existing_journal_id"])
            for event_type, data in await self._outbox(db_session)
        ] == [("journal_event.updated", last_journal)]

    async def test_a_far_moved_exception_does_not_stretch_the_window(
        self, db_session
    ) -> None:
        """An occurrence moved far ahead keeps its scheduled slot: the window
        ends where Google stopped expanding the rule, not where it moved."""
        from datetime import timedelta

        calendar_uuid = await self._calendar(db_session)
        first, second = self._day(1), self._day(2)
        unlisted = self._day(10)
        for start in (first, second, unlisted):
            await self._linked_journal(db_session, calendar_uuid, start)
        moved = self._instance(first)
        moved["originalStartTime"] = {"dateTime": first.isoformat()}
        moved_to = first + timedelta(weeks=20)
        moved["start"] = {"dateTime": moved_to.isoformat()}
        moved["end"] = {"dateTime": (moved_to + timedelta(hours=1)).isoformat()}

        result, _ = await self._sync(
            db_session, [moved, self._instance(second)], sync_type="full"
        )

        assert result["status"] == "success"
        # The listed instances are ordinary updates; nothing is retired.
        assert "journal_event.cancelled" not in [
            event_type for event_type, _ in await self._outbox(db_session)
        ]
        assert result.get("events_rekey_adopted", 0) == 0

    async def test_google_is_asked_from_before_a_locally_moved_slot(
        self, db_session
    ) -> None:
        """A journal postponed locally (not yet pushed) is still at its slot in
        Google, so the listing must start before that slot."""
        from datetime import timedelta

        calendar_uuid = await self._calendar(db_session, sync_token="token")
        slot = self._day(1)
        journal_id = await self._linked_journal(db_session, calendar_uuid, slot)
        await db_session.execute(
            text(
                "UPDATE journals SET event_date_range_start = :later,"
                " event_date_range_end = :later WHERE id = :id"
            ),
            {"later": slot + timedelta(days=8), "id": journal_id},
        )
        await db_session.commit()
        still_live = self._instance(slot)
        new = self._instance(self._day(2, minute=30))

        result, client = await self._sync(
            db_session,
            [new],
            sync_type="incremental",
            instances=[still_live, new],
        )

        assert result["status"] == "success"
        client.list_instances.assert_awaited_once_with(
            "primary", self.RECURRENCE, (slot - timedelta(days=1)).isoformat()
        )
        assert [event_type for event_type, _ in await self._outbox(db_session)] == [
            "journal_event.created"
        ]

    async def test_a_far_slot_moved_earlier_does_not_stretch_the_window(
        self, db_session
    ) -> None:
        """The reverse: an occurrence scheduled far past Google's expansion but
        moved into it keeps its far slot, which proves nothing about the dates
        between."""
        from datetime import timedelta

        calendar_uuid = await self._calendar(db_session)
        first, second = self._day(1), self._day(2)
        unlisted = self._day(10)
        for start in (first, second, unlisted):
            await self._linked_journal(db_session, calendar_uuid, start)
        far_slot = self._day(30)
        moved = self._instance(far_slot)
        moved["originalStartTime"] = {"dateTime": far_slot.isoformat()}
        moved_to = second + timedelta(days=2)
        moved["start"] = {"dateTime": moved_to.isoformat()}
        moved["end"] = {"dateTime": (moved_to + timedelta(hours=1)).isoformat()}

        result, _ = await self._sync(
            db_session,
            [self._instance(first), self._instance(second), moved],
            sync_type="full",
        )

        assert result["status"] == "success"
        assert "journal_event.cancelled" not in [
            event_type for event_type, _ in await self._outbox(db_session)
        ]

    async def test_a_finite_series_of_only_moved_instances_is_still_adopted(
        self, db_session
    ) -> None:
        """A rule with an end is listed whole, so no instance needs to sit at
        its slot to show how far Google expanded it."""
        from datetime import timedelta

        calendar_uuid = await self._calendar(db_session)
        olds = [self._day(weeks) for weeks in (1, 2)]
        journals = [
            await self._linked_journal(db_session, calendar_uuid, start)
            for start in olds
        ]
        moved = []
        for old in olds:
            slot = old + timedelta(minutes=30)
            instance = self._instance(slot)
            instance["originalStartTime"] = {"dateTime": slot.isoformat()}
            moved_to = slot + timedelta(hours=1)
            instance["start"] = {"dateTime": moved_to.isoformat()}
            instance["end"] = {"dateTime": (moved_to + timedelta(hours=1)).isoformat()}
            moved.append(instance)

        result, _ = await self._sync(
            db_session, moved, sync_type="full", rule="RRULE:FREQ=WEEKLY;COUNT=2"
        )

        assert result.get("events_rekey_adopted") == 2
        assert {
            data["existing_journal_id"]
            for event_type, data in await self._outbox(db_session)
            if event_type == "journal_event.updated"
        } == set(journals)

    async def test_a_sub_daily_series_is_covered_only_to_its_last_listed_slot(
        self, db_session
    ) -> None:
        """Endless with two slots a day, Google may stop expanding mid-day:
        the later slots on that day were never listed, so are not gone."""
        from datetime import timedelta

        calendar_uuid = await self._calendar(db_session)
        morning = [self._day(weeks) for weeks in (1, 2)]
        evening = [start + timedelta(hours=10) for start in morning]
        for start in (*morning, evening[0]):
            await self._linked_journal(db_session, calendar_uuid, start)
        unlisted_evening = await self._linked_journal(
            db_session, calendar_uuid, evening[1]
        )

        result, _ = await self._sync(
            db_session,
            [self._instance(start) for start in (*morning, evening[0])],
            sync_type="full",
        )

        assert result["status"] == "success"
        cancelled = [
            data["existing_journal_id"]
            for event_type, data in await self._outbox(db_session)
            if event_type == "journal_event.cancelled"
        ]
        assert unlisted_evening not in cancelled

    async def test_an_instance_the_sync_cannot_parse_is_still_live(
        self, db_session
    ) -> None:
        """Google listed it; that it fails our validation does not make it
        gone, so its journal must not be cancelled."""
        calendar_uuid = await self._calendar(db_session)
        rejected_start, valid_start = self._day(1), self._day(2)
        rejected_journal = await self._linked_journal(
            db_session, calendar_uuid, rejected_start
        )
        await self._linked_journal(db_session, calendar_uuid, valid_start)
        rejected = self._instance(rejected_start)
        rejected["attendees"] = [{"displayName": "No email"}]

        result, _ = await self._sync(
            db_session,
            [rejected, self._instance(valid_start)],
            sync_type="full",
        )

        cancelled = [
            data["existing_journal_id"]
            for event_type, data in await self._outbox(db_session)
            if event_type == "journal_event.cancelled"
        ]
        assert rejected_journal not in cancelled
        assert result.get("errors") == 1

    async def test_a_doubled_set_is_merged_into_its_live_journals(
        self, db_session
    ) -> None:
        """Both the old and the new instances were journalled before anything
        could adopt: each old journal is sent to be merged into the live one
        on its day, not cancelled beside it."""
        calendar_uuid = await self._calendar(db_session)
        olds = [self._day(weeks) for weeks in (1, 2)]
        news = [self._day(weeks, minute=30) for weeks in (1, 2)]
        old_journals = [
            await self._linked_journal(db_session, calendar_uuid, start)
            for start in olds
        ]
        new_journals = [
            await self._linked_journal(db_session, calendar_uuid, start)
            for start in news
        ]

        result, _ = await self._sync(
            db_session, [self._instance(start) for start in news], sync_type="full"
        )

        assert result["status"] == "success"
        cancelled = sorted(
            (data["existing_journal_id"], data["superseded_by_journal_id"])
            for event_type, data in await self._outbox(db_session)
            if event_type == "journal_event.cancelled"
        )
        assert cancelled == sorted(zip(old_journals, new_journals, strict=True))

    async def test_a_re_time_back_reclaims_an_id_a_merge_aliased(
        self, db_session
    ) -> None:
        """14:00 was merged into 14:30, then the organiser moved it back: the
        14:00 id Google re-issues is a merged alias of the 14:30 journal, and
        the adoption takes it back instead of skipping it."""
        from core_shared.repositories.merged_alias_repository import (
            ExternalRecord,
            MergedAliasRepository,
        )

        calendar_uuid = await self._calendar(db_session)
        old_slot, new_slot = self._day(1), self._day(1, minute=30)
        journal_id = await self._linked_journal(db_session, calendar_uuid, new_slot)
        await MergedAliasRepository(db_session).record_aliases(
            journal_id=journal_id,
            user_id=TEST_USER,
            records=[
                ExternalRecord(
                    integration_source="google_calendar",
                    external_id=self._instance_id(old_slot),
                    calendar_id=uuid.UUID(calendar_uuid),
                    recurring_event_id=self.RECURRENCE,
                )
            ],
        )
        await db_session.commit()

        result, _ = await self._sync(
            db_session, [self._instance(old_slot)], sync_type="full"
        )

        assert result["status"] == "success"
        assert result.get("events_skipped_merged", 0) == 0
        [(event_type, data)] = await self._outbox(db_session)
        assert event_type == "journal_event.updated"
        assert data["existing_journal_id"] == journal_id
        assert data["external_event_id"] == self._instance_id(old_slot)
        assert data["rekeyed_from"] == self._instance_id(new_slot)
