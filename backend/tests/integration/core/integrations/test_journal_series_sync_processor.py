"""Integration tests for recurring-series sync in JournalOutboxEventProcessor.

Covers series auto-linking on create, recurring-id backfill on update,
whole-series cancellation fan-out (delete far-future, cancel near, skip past),
local-edit protection, and the external-event-id prefix fallback for links
synced before the recurring id was recorded.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from core_shared.models.outbox import OutboxEvent
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.journal_outbox_event_processor import (
    JournalOutboxEventProcessingError,
    JournalOutboxEventProcessor,
)
from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.journal_series_repository import (
    SqlJournalSeriesRepository,
)
from app.core.journal.services.journal_service import JournalService
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher

USER_ID = "series-sync-user"
MASTER_ID = "recurring-master-1"


def _processor(connection: AsyncConnection) -> JournalOutboxEventProcessor:
    service = JournalService(
        journal_repo=SqlJournalRepository(connection),
        event_publisher=OutboxEventPublisher(connection),
        contact_relationship_repo=SqlJournalContactRelationshipRepository(connection),
    )
    return JournalOutboxEventProcessor(
        journal_service=service,
        connection=connection,
        # No contact/strava syncing in these scenarios
        contact_repository=None,  # type: ignore[arg-type]
        strava_athlete_mapping_repository=None,  # type: ignore[arg-type]
    )


def _sync_event(
    event_type: str,
    *,
    calendar_id: str,
    external_event_id: str,
    title: str = "Physio appointment",
    start: datetime | None = None,
    end: datetime | None = None,
    etag: str = '"etag-1"',
    existing_journal_id: int | None = None,
    recurring_event_id: str | None = None,
) -> OutboxEvent:
    start = start or (datetime.now(UTC) + timedelta(days=10))
    end = end or (start + timedelta(hours=1))
    event_data: dict[str, Any] = {
        "integration_source": "google",
        "external_event_id": external_event_id,
        "calendar_id": calendar_id,
        "journal_data": {
            "user_id": USER_ID,
            "title": title,
            "content": "Synced from Google Calendar",
            "event_date_range_start": start.isoformat(),
            "event_date_range_end": end.isoformat(),
        },
        "calendar_info_data": {
            "calendar_id": calendar_id,
            "is_all_day": False,
        },
        "sync_timestamp": datetime.now(UTC).isoformat(),
        "sync_action": event_type.split(".")[1],
        "etag": etag,
        "existing_journal_id": existing_journal_id,
        "contact_relationships": [],
        "recurring_event_id": recurring_event_id,
    }
    return OutboxEvent(
        id=uuid.uuid4(),
        event_type=event_type,
        aggregate_id="0",
        event_data=event_data,
        occurred_at=datetime.now(UTC),
        retry_count=0,
    )


def _series_cancelled_event(
    calendar_id: str, master_id: str = MASTER_ID
) -> OutboxEvent:
    return OutboxEvent(
        id=uuid.uuid4(),
        event_type="journal_event.series_cancelled",
        aggregate_id="0",
        event_data={
            "integration_source": "google",
            "calendar_id": calendar_id,
            "recurring_event_id": master_id,
            "sync_timestamp": datetime.now(UTC).isoformat(),
        },
        occurred_at=datetime.now(UTC),
        retry_count=0,
    )


async def _create_calendar(connection: AsyncConnection) -> str:
    calendar_id = uuid.uuid4()
    await connection.execute(
        text(
            """
            INSERT INTO calendars (id, user_id, name, color)
            VALUES (:id, :user_id, 'Sync Test Calendar', '#336699')
            """
        ),
        {"id": calendar_id, "user_id": USER_ID},
    )
    return str(calendar_id)


async def _journal_exists(connection: AsyncConnection, journal_id: int) -> bool:
    result = await connection.execute(
        text("SELECT 1 FROM journals WHERE id = :id"), {"id": journal_id}
    )
    return result.fetchone() is not None


async def _event_state(connection: AsyncConnection, journal_id: int) -> str | None:
    result = await connection.execute(
        text("SELECT event_state FROM journal_calendar_info WHERE journal_id = :id"),
        {"id": journal_id},
    )
    return result.scalar()


async def _link_recurring_id(
    connection: AsyncConnection, journal_id: int
) -> str | None:
    result = await connection.execute(
        text(
            "SELECT recurring_event_id FROM journal_external_event_links"
            " WHERE journal_id = :id"
        ),
        {"id": journal_id},
    )
    return result.scalar()


@pytest.mark.integration
class TestSeriesAutoLinkingOnCreate:
    async def test_recurring_instances_link_into_one_series(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await _create_calendar(async_connection)
        processor = _processor(async_connection)

        first = await processor.process_event(
            _sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_20260801T090000Z",
                recurring_event_id=MASTER_ID,
            )
        )
        second = await processor.process_event(
            _sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_20260808T090000Z",
                recurring_event_id=MASTER_ID,
            )
        )

        series_repo = SqlJournalSeriesRepository(async_connection)
        first_series = await series_repo.get_series_for_journal(
            first["journal_id"], USER_ID
        )
        second_series = await series_repo.get_series_for_journal(
            second["journal_id"], USER_ID
        )
        assert len(first_series) == 1
        assert first_series[0].name == "Physio appointment"
        assert first_series[0].auto_created is True
        assert [s.id for s in first_series] == [s.id for s in second_series]
        assert await _link_recurring_id(async_connection, first["journal_id"]) == (
            MASTER_ID
        )

    async def test_non_recurring_event_creates_no_series(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await _create_calendar(async_connection)
        processor = _processor(async_connection)

        result = await processor.process_event(
            _sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id="single-event-1",
            )
        )

        series_repo = SqlJournalSeriesRepository(async_connection)
        assert (
            await series_repo.get_series_for_journal(result["journal_id"], USER_ID)
            == []
        )


@pytest.mark.integration
class TestRecurringIdBackfillOnUpdate:
    async def test_promoted_update_populates_recurring_id_and_series(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await _create_calendar(async_connection)
        processor = _processor(async_connection)
        external_event_id = f"{MASTER_ID}_20260801T090000Z"

        # Synced before the series feature: no recurring id on the wire.
        created = await processor.process_event(
            _sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=external_event_id,
            )
        )
        journal_id = created["journal_id"]
        assert await _link_recurring_id(async_connection, journal_id) is None

        # Re-seen with a recurring id (backfill promotion) and a new etag.
        await processor.process_event(
            _sync_event(
                "journal_event.updated",
                calendar_id=calendar_id,
                external_event_id=external_event_id,
                existing_journal_id=journal_id,
                etag='"etag-2"',
                recurring_event_id=MASTER_ID,
            )
        )

        assert await _link_recurring_id(async_connection, journal_id) == MASTER_ID
        series_repo = SqlJournalSeriesRepository(async_connection)
        series = await series_repo.get_series_for_journal(journal_id, USER_ID)
        assert len(series) == 1
        assert series[0].recurring_event_id == MASTER_ID


@pytest.mark.integration
class TestSeriesCancelledFanOut:
    async def test_deletes_future_cancels_near_skips_past(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await _create_calendar(async_connection)
        processor = _processor(async_connection)
        now = datetime.now(UTC)

        journals: dict[str, int] = {}
        for key, start in (
            ("future", now + timedelta(days=10)),
            ("near", now + timedelta(hours=6)),
            ("past", now - timedelta(days=10)),
        ):
            result = await processor.process_event(
                _sync_event(
                    "journal_event.created",
                    calendar_id=calendar_id,
                    external_event_id=f"{MASTER_ID}_{key}",
                    start=start,
                    recurring_event_id=MASTER_ID,
                )
            )
            journals[key] = result["journal_id"]

        result = await processor.process_event(_series_cancelled_event(calendar_id))

        assert result["status"] == "success"
        assert result["deleted"] == 1
        assert result["cancelled"] == 1
        assert result["skipped_past"] == 1
        assert result["errors"] == 0
        assert not await _journal_exists(async_connection, journals["future"])
        assert await _journal_exists(async_connection, journals["near"])
        assert await _event_state(async_connection, journals["near"]) == "cancelled"
        assert await _journal_exists(async_connection, journals["past"])
        assert await _event_state(async_connection, journals["past"]) != "cancelled"

    async def test_edited_future_journal_preserved_as_cancelled(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await _create_calendar(async_connection)
        processor = _processor(async_connection)

        created = await processor.process_event(
            _sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_edited",
                recurring_event_id=MASTER_ID,
            )
        )
        journal_id = created["journal_id"]

        # Local edit after the sync: journal updated_at newer than the link's.
        await async_connection.execute(
            text(
                "UPDATE journals SET content = 'my notes', updated_at = :ts"
                " WHERE id = :id"
            ),
            {"ts": datetime.now(UTC) + timedelta(seconds=30), "id": journal_id},
        )

        result = await processor.process_event(_series_cancelled_event(calendar_id))

        assert result["deleted"] == 0
        assert result["cancelled"] == 1
        assert await _journal_exists(async_connection, journal_id)
        assert await _event_state(async_connection, journal_id) == "cancelled"

    async def test_prefix_fallback_matches_unbackfilled_links(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await _create_calendar(async_connection)
        processor = _processor(async_connection)

        # Link synced before the series feature: no recurring id stored, but
        # the Google instance id embeds the master id as a prefix.
        created = await processor.process_event(
            _sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_20260901T090000Z",
            )
        )
        journal_id = created["journal_id"]
        assert await _link_recurring_id(async_connection, journal_id) is None

        result = await processor.process_event(_series_cancelled_event(calendar_id))

        assert result["deleted"] == 1
        assert not await _journal_exists(async_connection, journal_id)

    async def test_no_links_is_noop_success(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await _create_calendar(async_connection)
        processor = _processor(async_connection)

        result = await processor.process_event(
            _series_cancelled_event(calendar_id, master_id="unknown-master")
        )

        assert result["status"] == "success"
        assert result["deleted"] == 0
        assert result["cancelled"] == 0


@pytest.mark.integration
class TestRecurringInstanceCancellation:
    async def test_cancelled_future_instance_is_deleted(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await _create_calendar(async_connection)
        processor = _processor(async_connection)
        external_event_id = f"{MASTER_ID}_instance1"

        created = await processor.process_event(
            _sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=external_event_id,
                recurring_event_id=MASTER_ID,
            )
        )
        journal_id = created["journal_id"]

        result = await processor.process_event(
            _sync_event(
                "journal_event.cancelled",
                calendar_id=calendar_id,
                external_event_id=external_event_id,
                existing_journal_id=journal_id,
                recurring_event_id=MASTER_ID,
            )
        )

        assert result["action"] == "deleted"
        assert not await _journal_exists(async_connection, journal_id)

    async def test_cancelled_tagged_instance_falls_back_to_cancel(
        self, async_connection: AsyncConnection
    ) -> None:
        calendar_id = await _create_calendar(async_connection)
        processor = _processor(async_connection)
        external_event_id = f"{MASTER_ID}_instance2"

        created = await processor.process_event(
            _sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=external_event_id,
                recurring_event_id=MASTER_ID,
            )
        )
        journal_id = created["journal_id"]

        # A tag is a local addition — deletion would lose user data.
        tag_id = (
            await async_connection.execute(
                text("INSERT INTO journal_tags (name) VALUES (:name) RETURNING id"),
                {"name": f"tag-{uuid.uuid4().hex[:8]}"},
            )
        ).scalar()
        await async_connection.execute(
            text(
                "INSERT INTO journal_tag_assignments (journal_id, tag_id)"
                " VALUES (:journal_id, :tag_id)"
            ),
            {"journal_id": journal_id, "tag_id": tag_id},
        )

        result = await processor.process_event(
            _sync_event(
                "journal_event.cancelled",
                calendar_id=calendar_id,
                external_event_id=external_event_id,
                existing_journal_id=journal_id,
                recurring_event_id=MASTER_ID,
            )
        )

        assert result.get("action") != "deleted"
        assert await _journal_exists(async_connection, journal_id)
        assert await _event_state(async_connection, journal_id) == "cancelled"


@pytest.mark.integration
class TestSeriesCancelledNullableLinkFields:
    async def test_link_without_external_event_id_is_marked_cancelled(
        self, async_connection: AsyncConnection
    ) -> None:
        """Links with a NULL external_event_id still get sync_status updated
        (the UPDATE keys on the link PK, not the nullable external id)."""
        calendar_id = await _create_calendar(async_connection)
        processor = _processor(async_connection)

        created = await processor.process_event(
            _sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_nullid",
                start=datetime.now(UTC) + timedelta(hours=6),
                recurring_event_id=MASTER_ID,
            )
        )
        journal_id = created["journal_id"]
        await async_connection.execute(
            text(
                "UPDATE journal_external_event_links SET external_event_id = NULL"
                " WHERE journal_id = :journal_id"
            ),
            {"journal_id": journal_id},
        )

        result = await processor.process_event(_series_cancelled_event(calendar_id))

        assert result["cancelled"] == 1
        link_status = await async_connection.execute(
            text(
                "SELECT sync_status FROM journal_external_event_links"
                " WHERE journal_id = :journal_id"
            ),
            {"journal_id": journal_id},
        )
        assert link_status.scalar() == "cancelled"
        assert await _event_state(async_connection, journal_id) == "cancelled"


@pytest.mark.integration
class TestSeriesCancelledPerItemSavepoints:
    async def test_failed_delete_rolls_back_link_removal_for_that_item_only(
        self, async_connection: AsyncConnection
    ) -> None:
        """If delete_journal fails after the item's links were removed, the
        SAVEPOINT restores them; other items still process."""
        calendar_id = await _create_calendar(async_connection)
        processor = _processor(async_connection)

        journals: dict[str, int] = {}
        for key in ("fails", "succeeds"):
            created = await processor.process_event(
                _sync_event(
                    "journal_event.created",
                    calendar_id=calendar_id,
                    external_event_id=f"{MASTER_ID}_{key}",
                    recurring_event_id=MASTER_ID,
                )
            )
            journals[key] = created["journal_id"]

        original_delete = processor.journal_service.delete_journal

        async def failing_delete(journal_id: int, *args: Any, **kwargs: Any) -> None:
            if journal_id == journals["fails"]:
                raise RuntimeError("simulated delete failure")
            return await original_delete(journal_id, *args, **kwargs)

        with (
            patch.object(
                processor.journal_service,
                "delete_journal",
                new=failing_delete,
            ),
            pytest.raises(JournalOutboxEventProcessingError, match="1 of 2"),
        ):
            await processor.process_event(_series_cancelled_event(calendar_id))

        # The failed journal survives WITH its link row (the savepoint rolled
        # back the link deletion that ran before the failure).
        assert await _journal_exists(async_connection, journals["fails"])
        link_count = await async_connection.execute(
            text(
                "SELECT COUNT(*) FROM journal_external_event_links"
                " WHERE journal_id = :journal_id"
            ),
            {"journal_id": journals["fails"]},
        )
        assert link_count.scalar() == 1
        # The other journal was still deleted.
        assert not await _journal_exists(async_connection, journals["succeeds"])


@pytest.mark.integration
class TestUnchangedEtagBackfillIntegration:
    async def test_unchanged_etag_update_backfills_link_and_series(
        self, async_connection: AsyncConnection
    ) -> None:
        """The worker's backfill promotion re-sends the SAME etag; the
        recurring id and series membership must persist anyway (otherwise the
        promotion loops forever)."""
        calendar_id = await _create_calendar(async_connection)
        processor = _processor(async_connection)
        external_event_id = f"{MASTER_ID}_20260801T090000Z"

        created = await processor.process_event(
            _sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=external_event_id,
            )
        )
        journal_id = created["journal_id"]
        assert await _link_recurring_id(async_connection, journal_id) is None

        result = await processor.process_event(
            _sync_event(
                "journal_event.updated",
                calendar_id=calendar_id,
                external_event_id=external_event_id,
                existing_journal_id=journal_id,
                etag='"etag-1"',  # unchanged — same as the create
                recurring_event_id=MASTER_ID,
            )
        )

        assert result["status"] == "skipped"
        assert await _link_recurring_id(async_connection, journal_id) == MASTER_ID
        series_repo = SqlJournalSeriesRepository(async_connection)
        series = await series_repo.get_series_for_journal(journal_id, USER_ID)
        assert len(series) == 1
        assert series[0].recurring_event_id == MASTER_ID


@pytest.mark.integration
class TestPrefixFallbackScoping:
    async def test_prefix_fallback_skips_successor_and_backfilled_links(
        self, async_connection: AsyncConnection
    ) -> None:
        """The prefix fallback only matches unbackfilled links whose suffix is
        a single instance timestamp — successor-series ids (extra underscore
        segment) and links backfilled to another master are untouched."""
        calendar_id = await _create_calendar(async_connection)
        processor = _processor(async_connection)

        legacy = await processor.process_event(
            _sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_20260801T090000Z",
            )
        )
        successor_form = await processor.process_event(
            _sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_R20260901T090000_20260908T090000Z",
            )
        )
        backfilled_other = await processor.process_event(
            _sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_20261001T090000Z",
                recurring_event_id=f"{MASTER_ID}_R20260901T090000",
            )
        )

        result = await processor.process_event(_series_cancelled_event(calendar_id))

        assert result["deleted"] == 1
        assert not await _journal_exists(async_connection, legacy["journal_id"])
        assert await _journal_exists(async_connection, successor_form["journal_id"])
        assert (
            await _event_state(async_connection, successor_form["journal_id"])
            != "cancelled"
        )
        assert await _journal_exists(async_connection, backfilled_other["journal_id"])


@pytest.mark.integration
class TestDeletionGuardUserData:
    async def test_instance_with_route_falls_back_to_cancel(
        self, async_connection: AsyncConnection
    ) -> None:
        """A user-attached GPS route protects a far-future instance."""
        calendar_id = await _create_calendar(async_connection)
        processor = _processor(async_connection)

        created = await processor.process_event(
            _sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_routed",
                recurring_event_id=MASTER_ID,
            )
        )
        journal_id = created["journal_id"]
        await async_connection.execute(
            text(
                "INSERT INTO routes (journal_id, name)"
                " VALUES (:journal_id, 'Planned track')"
            ),
            {"journal_id": journal_id},
        )

        result = await processor.process_event(_series_cancelled_event(calendar_id))

        assert result["deleted"] == 0
        assert result["cancelled"] == 1
        assert await _journal_exists(async_connection, journal_id)
        assert await _event_state(async_connection, journal_id) == "cancelled"

    async def test_instance_with_type_data_falls_back_to_cancel(
        self, async_connection: AsyncConnection
    ) -> None:
        """User-added type data (e.g. mood) protects a far-future instance."""
        calendar_id = await _create_calendar(async_connection)
        processor = _processor(async_connection)

        created = await processor.process_event(
            _sync_event(
                "journal_event.created",
                calendar_id=calendar_id,
                external_event_id=f"{MASTER_ID}_mooded",
                recurring_event_id=MASTER_ID,
            )
        )
        journal_id = created["journal_id"]
        await async_connection.execute(
            text(
                "INSERT INTO journal_mood_data (journal_id, mood_value)"
                " VALUES (:journal_id, 4)"
            ),
            {"journal_id": journal_id},
        )

        result = await processor.process_event(_series_cancelled_event(calendar_id))

        assert result["deleted"] == 0
        assert result["cancelled"] == 1
        assert await _journal_exists(async_connection, journal_id)
        assert await _event_state(async_connection, journal_id) == "cancelled"
