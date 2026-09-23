"""Driving the journal sync processor from an integration test.

`JournalOutboxEventProcessor` is how *calendar sync* puts a journal into
`EventState.CANCELLED` — one of the three production paths that reach that
state, and the two harder ones to arrange. (The third is a person editing the
EVENT type data, which is an ordinary `PUT` and needs none of this.) A test that
wants a genuinely sync-cancelled journal — rather than a `journal_calendar_info`
row it wrote itself — has to build the processor and feed it an outbox event,
which is more setup than a seeding call: a calendar row, a payload shaped like
the Google worker's, and the knowledge that a `journal_event.created` must
precede everything else because the link row is what later events are matched
on.

These helpers were private to `test_journal_series_sync_processor.py` until the
task-cancellation tests needed the same arrangement from
`tests/integration/tasks/`. They live here rather than being copied, on the same
grounds as ``recorded_statements``: a second copy of a harness whose
correctness is not obvious is the kind of duplication that drifts. The sync
suite owns them because it owns the processor; the tasks suite imports across,
which is the direction the traffic already goes — this module's counterpart
imports ``tests.integration.tasks.task_seeding``.

Everything takes ``user_id`` so a caller can seed under whichever owner its own
fixtures use.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from core_shared.models.outbox import OutboxEvent
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.journal_outbox_event_processor import (
    JournalOutboxEventProcessor,
)
from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_service import JournalService
from app.core.tasks.adapters.sql.task_anchor_repository import SqlTaskAnchorRepository
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher

USER_ID = "series-sync-user"
MASTER_ID = "recurring-master-1"


def build_processor(connection: AsyncConnection) -> JournalOutboxEventProcessor:
    """The processor over real adapters on the test's single connection.

    The `JournalService` carries a real `SqlTaskAnchorRepository`, which is what
    makes the delete guard live: a cancelled far-future instance that a task is
    anchored to must be refused deletion and fall back to being marked
    cancelled, and a guard-less service would silently delete it instead.

    Contact and Strava syncing are passed as `None` because no scenario here
    exercises them; a double would only assert that the test knows they are
    unused.
    """
    service = JournalService(
        journal_repo=SqlJournalRepository(connection),
        event_publisher=OutboxEventPublisher(connection),
        contact_relationship_repo=SqlJournalContactRelationshipRepository(connection),
        task_anchor_repo=SqlTaskAnchorRepository(connection),
    )
    return JournalOutboxEventProcessor(
        journal_service=service,
        connection=connection,
        contact_repository=None,  # type: ignore[arg-type]
        strava_athlete_mapping_repository=None,  # type: ignore[arg-type]
    )


def sync_event(
    event_type: str,
    *,
    calendar_id: str,
    external_event_id: str,
    user_id: str = USER_ID,
    title: str = "Physio appointment",
    start: datetime | None = None,
    end: datetime | None = None,
    etag: str = '"etag-1"',
    existing_journal_id: int | None = None,
    recurring_event_id: str | None = None,
    external_identity: str | None = None,
    timezone: str | None = None,
    contact_relationships: list[dict[str, Any]] | None = None,
) -> OutboxEvent:
    """A `journal_event.created` / `.updated` / `.cancelled` outbox event.

    Defaults to ten days out, which is both future-dated enough to satisfy a
    task's due-journal invariant and far enough ahead to be a deletion
    candidate when its series is cancelled — the pairing the anchored-task
    fallback exists for.
    """
    start = start or (datetime.now(UTC) + timedelta(days=10))
    end = end or (start + timedelta(hours=1))
    event_data: dict[str, Any] = {
        "integration_source": "google",
        "external_event_id": external_event_id,
        "calendar_id": calendar_id,
        "journal_data": {
            "user_id": user_id,
            "title": title,
            "content": "Synced from Google Calendar",
            "event_date_range_start": start.isoformat(),
            "event_date_range_end": end.isoformat(),
        },
        "calendar_info_data": {
            "calendar_id": calendar_id,
            "is_all_day": False,
            **({"timezone": timezone} if timezone is not None else {}),
        },
        "sync_timestamp": datetime.now(UTC).isoformat(),
        "sync_action": event_type.split(".")[1],
        "etag": etag,
        "existing_journal_id": existing_journal_id,
        "contact_relationships": contact_relationships or [],
        "recurring_event_id": recurring_event_id,
        "external_identity": external_identity,
    }
    return OutboxEvent(
        id=uuid.uuid4(),
        event_type=event_type,
        aggregate_id="0",
        event_data=event_data,
        occurred_at=datetime.now(UTC),
        retry_count=0,
    )


def series_cancelled_event(calendar_id: str, master_id: str = MASTER_ID) -> OutboxEvent:
    """A whole-series cancellation, which fans out over every linked instance."""
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


async def create_calendar(
    connection: AsyncConnection,
    *,
    user_id: str = USER_ID,
    name: str = "Sync Test Calendar",
) -> str:
    """A calendar row for the synced journals to belong to, as a string uuid."""
    calendar_id = uuid.uuid4()
    await connection.execute(
        text(
            """
            INSERT INTO calendars (id, user_id, name, color)
            VALUES (:id, :user_id, :name, '#336699')
            """
        ),
        {"id": calendar_id, "user_id": user_id, "name": name},
    )
    return str(calendar_id)


async def journal_exists(connection: AsyncConnection, journal_id: int) -> bool:
    """Whether the journal row is still there."""
    result = await connection.execute(
        text("SELECT 1 FROM journals WHERE id = :id"), {"id": journal_id}
    )
    return result.fetchone() is not None


async def event_state(connection: AsyncConnection, journal_id: int) -> str | None:
    """The journal's stored event state, or `None` when it is not an event.

    Read from the column rather than through `CalendarInfoRepository`, so a test
    asserting *what the sync wrote* is not also asserting that the read path
    agrees with it.
    """
    result = await connection.execute(
        text("SELECT event_state FROM journal_calendar_info WHERE journal_id = :id"),
        {"id": journal_id},
    )
    return result.scalar()


async def link_recurring_id(connection: AsyncConnection, journal_id: int) -> str | None:
    """The recurring master id recorded on the journal's external link."""
    result = await connection.execute(
        text(
            "SELECT recurring_event_id FROM journal_external_event_links"
            " WHERE journal_id = :id"
        ),
        {"id": journal_id},
    )
    return result.scalar()
