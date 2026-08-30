"""One real-world event in two calendars becomes one journal.

The case is an event a person is invited to on both their calendars — the
work calendar invites the personal one, or the other way round. Each calendar
returns its *own* copy, with its own event id, so the per-calendar link lookup
can never match them up and the sync used to produce two journals for one
meeting.

What joins them is ``external_identity``: a token the integration worker
builds and this side treats as opaque. **Every token in this file is
deliberately not Google-shaped.** The rule under test is "same token, same
user, same journal", and nothing here should pass because the token happened
to look like an iCalUID — if a future change made the processor parse the
token, or key on anything Google-specific, these tests would fail, which is
exactly what they are for.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_merge_service import JournalMergeService
from app.core.tasks.adapters.sql.task_anchor_repository import SqlTaskAnchorRepository
from app.core.tasks.services.task_journal_merge_service import (
    TaskJournalMergeService,
)
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from tests.integration.core.integrations.journal_sync_seeding import (
    USER_ID,
    build_processor,
    create_calendar,
    event_state,
    journal_exists,
    sync_event,
)

pytestmark = pytest.mark.integration

# Opaque on purpose: the processor must not care what is inside.
SHARED_TOKEN = "widget-7f3a::instance-0"
OTHER_TOKEN = "widget-7f3a::instance-1"


async def _links(connection: AsyncConnection, journal_id: int) -> list[Any]:
    """Every external link on a journal, oldest calendar first."""
    result = await connection.execute(
        text("""
            SELECT calendar_id, external_event_id, external_identity,
                   sync_status, external_version
            FROM journal_external_event_links
            WHERE journal_id = :journal_id
            ORDER BY created_at, calendar_id
        """),
        {"journal_id": journal_id},
    )
    return list(result.fetchall())


async def _review_items(connection: AsyncConnection) -> list[Any]:
    """Everything sitting in the review queue, oldest first."""
    result = await connection.execute(
        text("""
            SELECT source_journal_id, candidate_journal_id, reason,
                   confidence_score, status, details
            FROM journal_review_items
            ORDER BY created_at, id
        """)
    )
    return list(result.fetchall())


async def _journal_count(connection: AsyncConnection, user_id: str = USER_ID) -> int:
    result = await connection.execute(
        text("SELECT count(*) FROM journals WHERE user_id = :user_id"),
        {"user_id": user_id},
    )
    return int(result.scalar() or 0)


async def _display_calendar(connection: AsyncConnection, journal_id: int) -> str:
    result = await connection.execute(
        text("SELECT calendar_id FROM journal_calendar_info WHERE journal_id = :id"),
        {"id": journal_id},
    )
    return str(result.scalar())


async def _title(connection: AsyncConnection, journal_id: int) -> str:
    result = await connection.execute(
        text("SELECT title FROM journals WHERE id = :id"), {"id": journal_id}
    )
    return str(result.scalar())


class TestOneEventInTwoCalendars:
    """The behaviour the ticket asks for."""

    async def test_the_second_calendar_links_to_the_first_calendars_journal(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """Two copies, one journal, two links.

        Both events arrive as ``created`` — which is what the worker emits
        when neither calendar has a link yet, the situation on a first sync.
        Nothing but the shared token can tell the processor they are the
        same meeting: the ids differ and so do the calendars.
        """
        processor = build_processor(async_connection)
        work = await create_calendar(async_connection, name="Work")
        personal = await create_calendar(async_connection, name="Personal")

        first = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=work,
                external_event_id="work-copy-1",
                external_identity=SHARED_TOKEN,
            )
        )
        second = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=personal,
                external_event_id="personal-copy-9",
                external_identity=SHARED_TOKEN,
                etag='"etag-2"',
            )
        )

        assert await _journal_count(async_connection) == 1
        assert second["journal_id"] == first["journal_id"]

        links = await _links(async_connection, first["journal_id"])
        assert {str(link.calendar_id) for link in links} == {work, personal}
        assert {link.external_event_id for link in links} == {
            "work-copy-1",
            "personal-copy-9",
        }

    async def test_each_link_keeps_its_own_calendars_event_id_and_version(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """The links are not copies of each other.

        Each calendar has its own event id and its own ETag, and the sync
        has to keep them apart or the next incremental pass would compare
        one calendar's version against the other's.
        """
        processor = build_processor(async_connection)
        work = await create_calendar(async_connection, name="Work")
        personal = await create_calendar(async_connection, name="Personal")

        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=work,
                external_event_id="work-copy-1",
                etag='"work-etag"',
                external_identity=SHARED_TOKEN,
            )
        )
        await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=personal,
                external_event_id="personal-copy-9",
                etag='"personal-etag"',
                external_identity=SHARED_TOKEN,
            )
        )

        by_calendar = {
            str(link.calendar_id): link
            for link in await _links(async_connection, created["journal_id"])
        }
        assert by_calendar[work].external_version == '"work-etag"'
        assert by_calendar[personal].external_version == '"personal-etag"'

    async def test_the_token_is_recorded_on_both_links(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """Without storing it, the next sync would have nothing to match on."""
        processor = build_processor(async_connection)
        work = await create_calendar(async_connection, name="Work")
        personal = await create_calendar(async_connection, name="Personal")

        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=work,
                external_event_id="work-copy-1",
                external_identity=SHARED_TOKEN,
            )
        )
        await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=personal,
                external_event_id="personal-copy-9",
                external_identity=SHARED_TOKEN,
            )
        )

        links = await _links(async_connection, created["journal_id"])
        assert [link.external_identity for link in links] == [
            SHARED_TOKEN,
            SHARED_TOKEN,
        ]

    async def test_a_third_calendar_joins_the_same_journal(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """Nothing about the rule is limited to a pair."""
        processor = build_processor(async_connection)
        calendars = [
            await create_calendar(async_connection, name=name)
            for name in ("Work", "Personal", "Shared")
        ]

        results = [
            await processor.process_event(
                sync_event(
                    "journal_event.created",
                    calendar_id=calendar_id,
                    external_event_id=f"copy-{index}",
                    external_identity=SHARED_TOKEN,
                )
            )
            for index, calendar_id in enumerate(calendars)
        ]

        assert await _journal_count(async_connection) == 1
        assert len({result["journal_id"] for result in results}) == 1
        assert len(await _links(async_connection, results[0]["journal_id"])) == 3


class TestWhatMustNotBeMerged:
    """The rule has to be narrow, or it merges unrelated events."""

    async def test_different_tokens_stay_separate_journals(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """This is the recurring-series case.

        Two instances of one weekly meeting share everything Google says
        about the series and differ only in when they start — which the
        worker folds into the token. Distinct tokens must stay distinct
        journals, or a weekly meeting collapses into a single entry.
        """
        processor = build_processor(async_connection)
        work = await create_calendar(async_connection, name="Work")
        personal = await create_calendar(async_connection, name="Personal")

        first = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=work,
                external_event_id="week-1",
                external_identity=SHARED_TOKEN,
            )
        )
        second = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=personal,
                external_event_id="week-2",
                external_identity=OTHER_TOKEN,
            )
        )

        assert first["journal_id"] != second["journal_id"]
        assert await _journal_count(async_connection) == 2

    async def test_events_without_a_token_are_never_merged(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """A missing identity is not an identity two events can share.

        Sources that supply no token — and links made before tokens
        existed — must fall through to the old per-calendar behaviour
        rather than collapsing into one journal.
        """
        processor = build_processor(async_connection)
        work = await create_calendar(async_connection, name="Work")
        personal = await create_calendar(async_connection, name="Personal")

        first = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=work,
                external_event_id="untokened-1",
                external_identity=None,
            )
        )
        second = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=personal,
                external_event_id="untokened-2",
                external_identity=None,
            )
        )

        assert first["journal_id"] != second["journal_id"]
        assert await _journal_count(async_connection) == 2

    async def test_another_users_matching_token_is_not_touched(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """A token means nothing across owners.

        Two people invited to the same meeting hold their own copies. If
        the lookup were not scoped by user, one person's sync would attach
        a link to the other person's journal.
        """
        processor = build_processor(async_connection)
        mine = await create_calendar(async_connection, name="Mine")
        theirs = await create_calendar(
            async_connection, user_id="somebody-else", name="Theirs"
        )

        first = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=mine,
                external_event_id="my-copy",
                external_identity=SHARED_TOKEN,
            )
        )
        second = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=theirs,
                external_event_id="their-copy",
                user_id="somebody-else",
                external_identity=SHARED_TOKEN,
            )
        )

        assert first["journal_id"] != second["journal_id"]
        assert await _journal_count(async_connection, USER_ID) == 1
        assert await _journal_count(async_connection, "somebody-else") == 1


class TestTheDisplayCalendarIsStable:
    """A journal shows in one calendar; the second must not steal it."""

    async def test_the_first_calendar_keeps_the_journal(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """``journal_calendar_info`` holds one calendar per journal.

        Left alone, the second calendar's sync would overwrite it and the
        event would appear to jump calendars — and jump back on the next
        sync, depending on which calendar ran last.
        """
        processor = build_processor(async_connection)
        work = await create_calendar(async_connection, name="Work")
        personal = await create_calendar(async_connection, name="Personal")

        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=work,
                external_event_id="work-copy-1",
                external_identity=SHARED_TOKEN,
            )
        )
        await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=personal,
                external_event_id="personal-copy-9",
                external_identity=SHARED_TOKEN,
            )
        )

        assert await _display_calendar(async_connection, created["journal_id"]) == work

    async def test_it_survives_repeated_syncs_of_the_second_calendar(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """Every later sync of the second calendar is an update, too."""
        processor = build_processor(async_connection)
        work = await create_calendar(async_connection, name="Work")
        personal = await create_calendar(async_connection, name="Personal")

        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=work,
                external_event_id="work-copy-1",
                external_identity=SHARED_TOKEN,
            )
        )
        for etag in ('"v2"', '"v3"'):
            await processor.process_event(
                sync_event(
                    "journal_event.updated",
                    calendar_id=personal,
                    external_event_id="personal-copy-9",
                    existing_journal_id=created["journal_id"],
                    etag=etag,
                    external_identity=SHARED_TOKEN,
                )
            )

        assert await _display_calendar(async_connection, created["journal_id"]) == work
        assert len(await _links(async_connection, created["journal_id"])) == 2


class TestCancellingOneCopy:
    """Removing the event from one calendar leaves the other alone."""

    async def _two_linked_calendars(
        self, connection: AsyncConnection
    ) -> tuple[Any, str, str, int]:
        processor = build_processor(connection)
        work = await create_calendar(connection, name="Work")
        personal = await create_calendar(connection, name="Personal")
        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=work,
                external_event_id="work-copy-1",
                external_identity=SHARED_TOKEN,
            )
        )
        await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=personal,
                external_event_id="personal-copy-9",
                external_identity=SHARED_TOKEN,
            )
        )
        return processor, work, personal, created["journal_id"]

    async def test_the_journal_survives_while_another_calendar_still_has_it(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """Declining on one calendar must not cancel the meeting.

        Before de-duping this could not happen — one journal, one calendar.
        Now that two calendars share a journal, cancelling on either would
        cancel the shared journal unless the other link is checked.
        """
        processor, _work, personal, journal_id = await self._two_linked_calendars(
            async_connection
        )

        await processor.process_event(
            sync_event(
                "journal_event.cancelled",
                calendar_id=personal,
                external_event_id="personal-copy-9",
                existing_journal_id=journal_id,
                external_identity=SHARED_TOKEN,
            )
        )

        assert await journal_exists(async_connection, journal_id)
        assert await event_state(async_connection, journal_id) != "cancelled"

    async def test_only_the_cancelled_calendars_link_is_marked(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """The other calendar's link stays live and syncable."""
        processor, work, personal, journal_id = await self._two_linked_calendars(
            async_connection
        )

        await processor.process_event(
            sync_event(
                "journal_event.cancelled",
                calendar_id=personal,
                external_event_id="personal-copy-9",
                existing_journal_id=journal_id,
                external_identity=SHARED_TOKEN,
            )
        )

        by_calendar = {
            str(link.calendar_id): link
            for link in await _links(async_connection, journal_id)
        }
        assert by_calendar[personal].sync_status == "cancelled"
        assert by_calendar[work].sync_status != "cancelled"

    async def test_cancelling_the_last_copy_cancels_the_journal(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """Once no calendar still holds it, the event really is cancelled."""
        processor, work, personal, journal_id = await self._two_linked_calendars(
            async_connection
        )

        for calendar_id, external_event_id in (
            (personal, "personal-copy-9"),
            (work, "work-copy-1"),
        ):
            await processor.process_event(
                sync_event(
                    "journal_event.cancelled",
                    calendar_id=calendar_id,
                    external_event_id=external_event_id,
                    existing_journal_id=journal_id,
                    external_identity=SHARED_TOKEN,
                )
            )

        assert await event_state(async_connection, journal_id) == "cancelled"

    async def test_a_single_calendar_journal_still_cancels(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """The ordinary case is unchanged by the new guard."""
        processor = build_processor(async_connection)
        work = await create_calendar(async_connection, name="Work")

        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=work,
                external_event_id="work-copy-1",
                external_identity=SHARED_TOKEN,
            )
        )
        await processor.process_event(
            sync_event(
                "journal_event.cancelled",
                calendar_id=work,
                external_event_id="work-copy-1",
                existing_journal_id=created["journal_id"],
                external_identity=SHARED_TOKEN,
            )
        )

        assert await event_state(async_connection, created["journal_id"]) == "cancelled"


class TestBackfillingAnExistingDuplicate:
    """Links made before tokens existed acquire one on their next sync."""

    async def test_a_resynced_link_records_its_token(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """The worker re-emits an unchanged event once; this stores the token."""
        processor = build_processor(async_connection)
        work = await create_calendar(async_connection, name="Work")

        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=work,
                external_event_id="work-copy-1",
                external_identity=None,
            )
        )
        links = await _links(async_connection, created["journal_id"])
        assert links[0].external_identity is None

        await processor.process_event(
            sync_event(
                "journal_event.updated",
                calendar_id=work,
                external_event_id="work-copy-1",
                existing_journal_id=created["journal_id"],
                etag='"etag-2"',
                external_identity=SHARED_TOKEN,
            )
        )

        links = await _links(async_connection, created["journal_id"])
        assert links[0].external_identity == SHARED_TOKEN

    async def test_a_backfilled_token_makes_the_second_calendar_de_dupe(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """The whole point of backfilling: events synced before the feature
        shipped start de-duping once both sides carry a token."""
        processor = build_processor(async_connection)
        work = await create_calendar(async_connection, name="Work")
        personal = await create_calendar(async_connection, name="Personal")

        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=work,
                external_event_id="work-copy-1",
                external_identity=None,
            )
        )
        await processor.process_event(
            sync_event(
                "journal_event.updated",
                calendar_id=work,
                external_event_id="work-copy-1",
                existing_journal_id=created["journal_id"],
                etag='"etag-2"',
                external_identity=SHARED_TOKEN,
            )
        )

        second = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=personal,
                external_event_id="personal-copy-9",
                external_identity=SHARED_TOKEN,
            )
        )

        assert second["journal_id"] == created["journal_id"]
        assert await _journal_count(async_connection) == 1

    async def test_an_update_without_a_token_keeps_the_stored_one(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """A payload that omits the token must not erase it.

        Cancellations and older payloads carry no identity; treating that
        as "clear it" would undo the backfill on the very next sync.
        """
        processor = build_processor(async_connection)
        work = await create_calendar(async_connection, name="Work")

        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=work,
                external_event_id="work-copy-1",
                external_identity=SHARED_TOKEN,
            )
        )
        await processor.process_event(
            sync_event(
                "journal_event.updated",
                calendar_id=work,
                external_event_id="work-copy-1",
                existing_journal_id=created["journal_id"],
                etag='"etag-2"',
                external_identity=None,
            )
        )

        links = await _links(async_connection, created["journal_id"])
        assert links[0].external_identity == SHARED_TOKEN


class TestTheSharedJournalStaysCoherent:
    """Both calendars describe one event, so both may update it."""

    async def test_an_update_from_the_second_calendar_reaches_the_journal(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """Renaming the meeting upstream shows up whichever copy reports it."""
        processor = build_processor(async_connection)
        work = await create_calendar(async_connection, name="Work")
        personal = await create_calendar(async_connection, name="Personal")
        start = datetime.now(UTC) + timedelta(days=10)

        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=work,
                external_event_id="work-copy-1",
                title="Physio appointment",
                start=start,
                external_identity=SHARED_TOKEN,
            )
        )
        await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=personal,
                external_event_id="personal-copy-9",
                title="Physio — rescheduled",
                start=start,
                etag='"etag-2"',
                external_identity=SHARED_TOKEN,
            )
        )

        assert await _title(async_connection, created["journal_id"]) == (
            "Physio — rescheduled"
        )


class TestARecurringEventSharedByTwoCalendars:
    """A de-duplicated instance belongs to one series, not one per calendar.

    Series are keyed by ``(calendar_id, recurring_event_id)``, which was
    right when each calendar had its own journals. Now that the two share a
    journal, letting the second calendar create its own series would leave
    the user two series for one weekly meeting, both listing the same
    journals.
    """

    async def _series_rows(self, connection: AsyncConnection) -> list[Any]:
        result = await connection.execute(
            text("""
                SELECT s.id, s.calendar_id, s.recurring_event_id,
                       count(m.journal_id) AS member_count
                FROM journal_series s
                LEFT JOIN journal_series_members m ON m.series_id = s.id
                GROUP BY s.id, s.calendar_id, s.recurring_event_id
                ORDER BY s.created_at
            """)
        )
        return list(result.fetchall())

    async def test_one_series_covers_the_shared_instance(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        processor = build_processor(async_connection)
        work = await create_calendar(async_connection, name="Work")
        personal = await create_calendar(async_connection, name="Personal")

        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=work,
                external_event_id="work-master_20260320T100000Z",
                recurring_event_id="work-master",
                external_identity=SHARED_TOKEN,
            )
        )
        await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=personal,
                external_event_id="personal-master_20260320T100000Z",
                recurring_event_id="personal-master",
                external_identity=SHARED_TOKEN,
            )
        )

        series = await self._series_rows(async_connection)
        assert len(series) == 1
        assert str(series[0].calendar_id) == work
        assert series[0].recurring_event_id == "work-master"
        assert created["journal_id"] is not None

    async def test_the_journal_is_not_a_member_of_two_series(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """Two series listing the same journal is what the user would see."""
        processor = build_processor(async_connection)
        work = await create_calendar(async_connection, name="Work")
        personal = await create_calendar(async_connection, name="Personal")

        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=work,
                external_event_id="work-master_20260320T100000Z",
                recurring_event_id="work-master",
                external_identity=SHARED_TOKEN,
            )
        )
        await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=personal,
                external_event_id="personal-master_20260320T100000Z",
                recurring_event_id="personal-master",
                external_identity=SHARED_TOKEN,
            )
        )

        result = await async_connection.execute(
            text("""
                SELECT count(*) FROM journal_series_members
                WHERE journal_id = :journal_id
            """),
            {"journal_id": created["journal_id"]},
        )
        assert result.scalar() == 1

    async def test_a_single_calendar_series_is_unaffected(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """The ordinary recurring event still gets its series."""
        processor = build_processor(async_connection)
        work = await create_calendar(async_connection, name="Work")

        await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=work,
                external_event_id="work-master_20260320T100000Z",
                recurring_event_id="work-master",
                external_identity=SHARED_TOKEN,
            )
        )

        series = await self._series_rows(async_connection)
        assert len(series) == 1
        assert series[0].member_count == 1


class TestFlaggingDuplicatesThatAlreadyExist:
    """Journals duplicated before the de-dupe shipped are surfaced, not merged.

    The fix stops *new* duplicates. It cannot retroactively join two
    journals that already exist — merging them means choosing whose title,
    content and tags survive, which is the user's call. So once both
    journals carry the same token, the pair goes to the review queue where
    it can be merged or dismissed by hand.
    """

    async def _duplicate_pair(
        self, connection: AsyncConnection
    ) -> tuple[Any, str, str, int, int]:
        """Two journals for one event, as a pre-de-dupe sync would leave them."""
        processor = build_processor(connection)
        work = await create_calendar(connection, name="Work")
        personal = await create_calendar(connection, name="Personal")

        first = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=work,
                external_event_id="work-copy-1",
                external_identity=None,
            )
        )
        second = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=personal,
                external_event_id="personal-copy-9",
                external_identity=None,
            )
        )
        return (
            processor,
            work,
            personal,
            first["journal_id"],
            second["journal_id"],
        )

    async def _backfill(
        self,
        processor: Any,
        *,
        calendar_id: str,
        external_event_id: str,
        journal_id: int,
        etag: str = '"etag-1"',
    ) -> None:
        """The one-shot re-sync that gives an existing link its token.

        The etag defaults to the one the link already carries, because the
        event has *not* changed — the worker promotes it out of
        SKIP_UNCHANGED purely to hand over the token. A changed etag would
        take the ordinary update path and never exercise this.
        """
        await processor.process_event(
            sync_event(
                "journal_event.updated",
                calendar_id=calendar_id,
                external_event_id=external_event_id,
                existing_journal_id=journal_id,
                etag=etag,
                external_identity=SHARED_TOKEN,
            )
        )

    async def test_a_duplicate_pair_reaches_the_review_queue(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """Once both links carry the token, the pair is flagged."""
        processor, work, personal, first, second = await self._duplicate_pair(
            async_connection
        )

        await self._backfill(
            processor,
            calendar_id=work,
            external_event_id="work-copy-1",
            journal_id=first,
        )
        await self._backfill(
            processor,
            calendar_id=personal,
            external_event_id="personal-copy-9",
            journal_id=second,
        )

        items = await _review_items(async_connection)
        assert len(items) == 1
        assert {items[0].source_journal_id, items[0].candidate_journal_id} == {
            first,
            second,
        }
        assert items[0].status == "pending"

    async def test_the_flag_says_the_two_are_one_external_event(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """The reason distinguishes this from an AI similarity guess.

        This is not "these look alike" — the source told us they are one
        event, so it is certain, and the queue should say so.
        """
        processor, work, personal, first, second = await self._duplicate_pair(
            async_connection
        )

        await self._backfill(
            processor,
            calendar_id=work,
            external_event_id="work-copy-1",
            journal_id=first,
        )
        await self._backfill(
            processor,
            calendar_id=personal,
            external_event_id="personal-copy-9",
            journal_id=second,
        )

        item = (await _review_items(async_connection))[0]
        assert item.reason == "external_link_match"
        assert item.confidence_score == 1.0

    async def test_repeated_syncs_do_not_pile_up_items(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """A pending review item is raised once, not once per sync."""
        processor, work, personal, first, second = await self._duplicate_pair(
            async_connection
        )

        for etag in ('"v2"', '"v3"', '"v4"'):
            await self._backfill(
                processor,
                calendar_id=work,
                external_event_id="work-copy-1",
                journal_id=first,
                etag=etag,
            )
            await self._backfill(
                processor,
                calendar_id=personal,
                external_event_id="personal-copy-9",
                journal_id=second,
                etag=etag,
            )

        assert len(await _review_items(async_connection)) == 1

    async def test_which_journal_syncs_first_does_not_change_the_item(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """Order must not produce a second item for the same pair.

        The queue's uniqueness constraint is on the ordered pair, so
        flagging (A, B) on one sync and (B, A) on the next would leave the
        user two rows describing one duplicate.
        """
        processor, work, personal, first, second = await self._duplicate_pair(
            async_connection
        )

        await self._backfill(
            processor,
            calendar_id=personal,
            external_event_id="personal-copy-9",
            journal_id=second,
        )
        await self._backfill(
            processor,
            calendar_id=work,
            external_event_id="work-copy-1",
            journal_id=first,
        )
        # …and now the other way round.
        await self._backfill(
            processor,
            calendar_id=personal,
            external_event_id="personal-copy-9",
            journal_id=second,
            etag='"v3"',
        )

        assert len(await _review_items(async_connection)) == 1

    async def test_an_ai_guess_about_the_pair_is_not_duplicated(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """A pair the AI already queued is not queued a second time.

        Match detection writes the *incoming* journal as the source and
        the one it matched against as the candidate, so it records the
        pair in whichever order the journals were created. This flagging
        sorts instead. The queue's uniqueness is on the ordered pair, so
        two producers using two orderings would each insert, and the user
        would see one duplicate described twice.

        The pair this flags is precisely the pair the AI is most likely to
        have guessed already — one event, so same day and same title.
        """
        processor, work, personal, first, second = await self._duplicate_pair(
            async_connection
        )
        # As match detection leaves it: the newer journal is the source.
        await async_connection.execute(
            text("""
                INSERT INTO journal_review_items
                    (user_id, source_journal_id, candidate_journal_id,
                     reason, confidence_score, status)
                VALUES (:user_id, :source, :candidate,
                        'duplicate_journal', 0.8, 'pending')
            """),
            {"user_id": USER_ID, "source": second, "candidate": first},
        )

        await self._backfill(
            processor,
            calendar_id=work,
            external_event_id="work-copy-1",
            journal_id=first,
        )
        await self._backfill(
            processor,
            calendar_id=personal,
            external_event_id="personal-copy-9",
            journal_id=second,
        )

        items = await _review_items(async_connection)
        assert len(items) == 1
        assert items[0].reason == "duplicate_journal"

    async def test_a_resolved_pair_is_not_raised_again(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """Deciding about a pair is not undone by the next sync.

        A dismissed item is the user saying these two are not one thing.
        Re-flagging it every sync would argue with them.
        """
        processor, work, personal, first, second = await self._duplicate_pair(
            async_connection
        )
        await async_connection.execute(
            text("""
                INSERT INTO journal_review_items
                    (user_id, source_journal_id, candidate_journal_id,
                     reason, confidence_score, status)
                VALUES (:user_id, :source, :candidate,
                        'duplicate_journal', 0.8, 'dismissed')
            """),
            {"user_id": USER_ID, "source": second, "candidate": first},
        )

        await self._backfill(
            processor,
            calendar_id=work,
            external_event_id="work-copy-1",
            journal_id=first,
        )
        await self._backfill(
            processor,
            calendar_id=personal,
            external_event_id="personal-copy-9",
            journal_id=second,
        )

        items = await _review_items(async_connection)
        assert len(items) == 1
        assert items[0].status == "dismissed"

    async def test_an_unchanged_event_still_hands_over_its_token(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """The re-sync that carries the token changes nothing else.

        This is the whole backfill path: the worker lifts a link out of
        SKIP_UNCHANGED *because* it has no token, so the event it sends is
        by definition unchanged and carries the etag already stored. If the
        etag guard turns it away before the token is written, no link
        predating the token ever gets one, the worker re-promotes it every
        sync forever, and nothing is ever flagged.
        """
        processor, work, personal, first, second = await self._duplicate_pair(
            async_connection
        )

        await self._backfill(
            processor,
            calendar_id=work,
            external_event_id="work-copy-1",
            journal_id=first,
        )

        assert [
            link.external_identity for link in await _links(async_connection, first)
        ] == [SHARED_TOKEN]

    async def test_an_unchanged_resync_flags_the_pair(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """Two unchanged events reaching the queue is the point of all this."""
        processor, work, personal, first, second = await self._duplicate_pair(
            async_connection
        )

        await self._backfill(
            processor,
            calendar_id=work,
            external_event_id="work-copy-1",
            journal_id=first,
        )
        await self._backfill(
            processor,
            calendar_id=personal,
            external_event_id="personal-copy-9",
            journal_id=second,
        )

        items = await _review_items(async_connection)
        assert len(items) == 1
        assert {items[0].source_journal_id, items[0].candidate_journal_id} == {
            first,
            second,
        }

    async def test_an_unchanged_resync_leaves_the_journal_alone(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """Handing over a token is not an edit.

        The etag guard exists to stop unchanged events rewriting journals
        and filling the history with no-ops. Backfilling through it must
        not cost that.
        """
        processor, work, _personal, first, _second = await self._duplicate_pair(
            async_connection
        )
        before = await async_connection.execute(
            text("SELECT title, content FROM journals WHERE id = :id"),
            {"id": first},
        )
        untouched = before.fetchone()
        assert untouched is not None

        await self._backfill(
            processor,
            calendar_id=work,
            external_event_id="work-copy-1",
            journal_id=first,
        )

        after = await async_connection.execute(
            text("SELECT title, content FROM journals WHERE id = :id"), {"id": first}
        )
        assert after.fetchone() == untouched
        history = await async_connection.execute(
            text("""
                SELECT count(*) FROM field_history
                WHERE entity_type = 'journal' AND entity_id = :id
            """),
            {"id": first},
        )
        assert history.scalar() == 0

    async def test_a_backfill_does_not_resolve_a_conflict(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """Handing over a token is not a successful sync.

        A conflicted link is waiting on the user. The event has not
        changed — it is promoted only to carry the token — so marking the
        link synced would clear a conflict nobody resolved, and the
        classifier that decides to promote it never looks at sync_status,
        so every conflicted link predating the token would be swept.
        """
        processor, work, _personal, first, _second = await self._duplicate_pair(
            async_connection
        )
        await async_connection.execute(
            text("""UPDATE journal_external_event_links
                    SET sync_status = 'conflicted'
                    WHERE external_event_id = 'work-copy-1'"""),
        )

        await self._backfill(
            processor,
            calendar_id=work,
            external_event_id="work-copy-1",
            journal_id=first,
        )

        status = await async_connection.execute(
            text(
                "SELECT sync_status FROM journal_external_event_links "
                "WHERE external_event_id = 'work-copy-1'"
            )
        )
        assert status.scalar() == "conflicted"

    async def test_the_newer_journal_is_the_one_a_merge_would_absorb(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """The pair's direction decides which journal a merge destroys.

        ``merge_journals`` deletes the *source*, and the queue's own
        "Merge All Identical" walks pending items merging source into
        candidate. Match detection records the incoming journal as the
        source, so the established one survives. Recording the pair
        ascending by id would invert that for these items and delete the
        older journal — the one carrying the longer history — while
        keeping the newer.

        Ordering still has to be deterministic, or two syncs would record
        the pair both ways round; it just has to be the *other* order.
        """
        processor, work, personal, first, second = await self._duplicate_pair(
            async_connection
        )
        assert first < second

        await self._backfill(
            processor,
            calendar_id=work,
            external_event_id="work-copy-1",
            journal_id=first,
        )
        await self._backfill(
            processor,
            calendar_id=personal,
            external_event_id="personal-copy-9",
            journal_id=second,
        )

        item = (await _review_items(async_connection))[0]
        assert item.source_journal_id == second
        assert item.candidate_journal_id == first

    async def test_merging_the_pair_keeps_both_calendars_identified(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """A merge moves the links, so it must move what identifies them.

        Resolving the pair is the point of flagging it, and the merge
        carries the loser's links over to the winner. Dropping the token on
        the way would leave the surviving journal holding a link the sync
        can no longer recognise as this event.
        """
        processor, work, personal, first, second = await self._duplicate_pair(
            async_connection
        )
        await self._backfill(
            processor,
            calendar_id=work,
            external_event_id="work-copy-1",
            journal_id=first,
        )
        await self._backfill(
            processor,
            calendar_id=personal,
            external_event_id="personal-copy-9",
            journal_id=second,
        )

        merge_service = JournalMergeService(
            journal_repo=SqlJournalRepository(async_connection),
            event_publisher=OutboxEventPublisher(async_connection),
            task_merge_service=TaskJournalMergeService(
                task_anchor_repo=SqlTaskAnchorRepository(async_connection),
                event_publisher=OutboxEventPublisher(async_connection),
            ),
        )
        await merge_service.merge_journals(
            target_id=first, source_id=second, transaction=async_connection
        )

        links = await _links(async_connection, first)
        assert len(links) == 2
        assert {link.external_identity for link in links} == {SHARED_TOKEN}

    async def test_a_de_duplicated_event_is_not_flagged(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """One journal with two links is the fixed state, not a duplicate.

        This is the case the whole feature produces, so flagging it would
        put a review item in the queue for every shared event the user has.
        """
        processor = build_processor(async_connection)
        work = await create_calendar(async_connection, name="Work")
        personal = await create_calendar(async_connection, name="Personal")

        created = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=work,
                external_event_id="work-copy-1",
                external_identity=SHARED_TOKEN,
            )
        )
        await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=personal,
                external_event_id="personal-copy-9",
                external_identity=SHARED_TOKEN,
            )
        )

        assert await _review_items(async_connection) == []
        assert created["journal_id"] is not None

    async def test_unrelated_journals_are_not_flagged(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """Different tokens are different events, however alike they look."""
        processor = build_processor(async_connection)
        work = await create_calendar(async_connection, name="Work")
        personal = await create_calendar(async_connection, name="Personal")

        first = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=work,
                external_event_id="week-1",
                external_identity=SHARED_TOKEN,
            )
        )
        second = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=personal,
                external_event_id="week-2",
                external_identity=OTHER_TOKEN,
            )
        )

        await self._backfill(
            processor,
            calendar_id=work,
            external_event_id="week-1",
            journal_id=first["journal_id"],
        )

        assert await _review_items(async_connection) == []
        assert first["journal_id"] != second["journal_id"]

    async def test_another_users_duplicate_is_not_flagged_against_mine(
        self,
        async_connection: AsyncConnection,
        clean_database: None,  # noqa: ARG001
    ) -> None:
        """A review item names two journals one person can merge."""
        processor = build_processor(async_connection)
        mine = await create_calendar(async_connection, name="Mine")
        theirs = await create_calendar(
            async_connection, user_id="somebody-else", name="Theirs"
        )

        first = await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=mine,
                external_event_id="my-copy",
                external_identity=SHARED_TOKEN,
            )
        )
        await processor.process_event(
            sync_event(
                "journal_event.created",
                calendar_id=theirs,
                external_event_id="their-copy",
                user_id="somebody-else",
                external_identity=SHARED_TOKEN,
            )
        )

        await self._backfill(
            processor,
            calendar_id=mine,
            external_event_id="my-copy",
            journal_id=first["journal_id"],
        )

        assert await _review_items(async_connection) == []
