"""Cancelling a journal, end to end, and what it does to the tasks on it.

The lapse *rule* is already covered — ITER18-001 Phase 12 pinned
``DUE_JOURNAL_CANCELLED`` at the rule, at the assembler and against a
``journal_calendar_info`` row the test wrote itself. What none of that shows is
that the state a **real cancellation** leaves behind is the state the read model
looks for. That seam is what this file tests: every *act* of cancelling here
goes through production code, and every verdict is read back through
``TaskReadService``. (One test seeds an already-cancelled journal — the
un-cancellation test, whose subject is the reverse operation, so a cancelled
journal is its starting position rather than the thing it asserts.)

Three production paths write ``EventState.CANCELLED``, and they are tested
separately because no one of them is evidence for the others:

* ``journal_event.cancelled`` — calendar sync cancels one instance upstream;
* ``journal_event.series_cancelled`` — the whole-series fan-out;
* ``PUT /api/journals/{id}/types/EVENT/data`` — **a person** setting the event
  editor's status to "Cancelled", which is a plain type-data edit and shares no
  code with the two above.

The two sync routes converge on the same fallback for a journal a task is
anchored to: the processor prefers to *delete* an untouched far-future
instance, the Phase 1 delete guard refuses because deleting it would destroy a
commitment, and the processor marks it cancelled instead. A task's due journal
is future-dated by invariant, so that is the ordinary path rather than an edge
of it.

**Every journal a task is *due* in is ten days out**, well clear of any day
boundary, which is the point: the date cause demonstrably cannot be what fired,
so a lapse can only have come from the cancellation. The timezone-boundary cases
belong to the rule and are Phase 12's. The one exception is the journal in the
mention test, which is near-future for a reason given there.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from core_shared.models.journals.event_state import EventState
from core_shared.models.tasks import LapseReason, TaskStatus
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.journal_outbox_event_processor import (
    JournalOutboxEventProcessor,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.tasks.services.task_read_service import TaskReadService
from app.core.tasks.services.task_service import TaskService
from tests.integration.core.integrations.journal_sync_seeding import (
    MASTER_ID,
    USER_ID,
    build_processor,
    create_calendar,
    event_state,
    journal_exists,
    series_cancelled_event,
    sync_event,
)
from tests.integration.tasks.task_seeding import (
    USER_ID as TASK_USER_ID,
)
from tests.integration.tasks.task_seeding import (
    create_contact,
    create_journal,
    create_task,
    link_contact,
    link_intermediate_journal,
    linked_contact_ids,
    mark_journal_as_event,
)

# The journals here belong to the sync harness's owner rather than the task
# suite's, because the processor creates them from the payload's ``user_id``.
# Every task is seeded under that same owner, since the read model is
# owner-scoped on each of its fetches and would otherwise see neither.

# Inside the fan-out's "cancel, don't delete" bucket (anything within a day).
# Used for a journal nothing anchors, which the delete guard has no reason to
# protect and which a far-future cancellation would therefore destroy outright.
NEAR_FUTURE_HOURS = 6

_SELECT_TASK_ANCHORS = text(
    "SELECT creating_journal_id, due_journal_id, status, text"
    " FROM tasks WHERE id = :task_id"
)
_SELECT_MENTIONS = text(
    "SELECT journal_id FROM task_intermediate_journals"
    " WHERE task_id = :task_id ORDER BY journal_id"
)


async def _seed_instance(
    processor: JournalOutboxEventProcessor,
    *,
    calendar_id: str,
    suffix: str,
    hours_from_now: int | None = None,
) -> int:
    """A synced recurring instance, ten days out unless told otherwise.

    Created through the processor rather than seeded, because the external link
    row it writes is what a later cancellation event is matched on — a journal
    without one cannot be cancelled at all.
    """
    start = (
        datetime.now(UTC) + timedelta(hours=hours_from_now)
        if hours_from_now is not None
        else None
    )
    created = await processor.process_event(
        sync_event(
            "journal_event.created",
            calendar_id=calendar_id,
            external_event_id=f"{MASTER_ID}_{suffix}",
            start=start,
            recurring_event_id=MASTER_ID,
        )
    )
    return int(created["journal_id"])


async def _cancel_instance(
    processor: JournalOutboxEventProcessor,
    *,
    calendar_id: str,
    suffix: str,
    journal_id: int,
) -> dict[str, object]:
    """Cancel one instance upstream and return what the processor reported."""
    return await processor.process_event(
        sync_event(
            "journal_event.cancelled",
            calendar_id=calendar_id,
            external_event_id=f"{MASTER_ID}_{suffix}",
            existing_journal_id=journal_id,
            recurring_event_id=MASTER_ID,
        )
    )


@pytest.mark.integration
class TestCancellingTheDueJournalLapsesTheTask:
    async def test_a_task_lapses_only_once_its_due_journal_is_cancelled(
        self,
        async_connection: AsyncConnection,
        read_service: TaskReadService,
    ) -> None:
        """The transition is the assertion, on one set of rows.

        Asserting the lapse alone would pass against a rule that lapsed
        everything; asserting the control alone would pass against a rule that
        lapsed nothing. The before/after pair is what shows the cancellation is
        the cause — and the journal is ten days out throughout, so the passage
        of time cannot be.
        """
        calendar_id = await create_calendar(async_connection, user_id=USER_ID)
        processor = build_processor(async_connection)
        journal_id = await _seed_instance(
            processor, calendar_id=calendar_id, suffix="due"
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=journal_id,
            due_journal_id=journal_id,
            user_id=USER_ID,
        )

        before = await read_service.read_model(USER_ID, task_id)
        assert before.lapsed is False
        assert before.lapse_reason is None

        await _cancel_instance(
            processor,
            calendar_id=calendar_id,
            suffix="due",
            journal_id=journal_id,
        )

        after = await read_service.read_model(USER_ID, task_id)
        assert after.lapsed is True
        assert after.lapse_reason is LapseReason.DUE_JOURNAL_CANCELLED

    async def test_retargeting_off_the_cancelled_journal_un_lapses_the_task(
        self,
        async_connection: AsyncConnection,
        read_service: TaskReadService,
        service: TaskService,
    ) -> None:
        """The recovery the specification names: "where the user can retarget it".

        Worth its own test because it is the one that shows the lapse is
        *derived* rather than sticky. The cancelled journal does not go away —
        retargeting retains it as an intermediate link — so a rule that had
        recorded the cancellation against the task, or that consulted every
        journal instead of the due one, would leave it lapsed forever with no
        way back.
        """
        calendar_id = await create_calendar(async_connection, user_id=USER_ID)
        processor = build_processor(async_connection)
        journal_id = await _seed_instance(
            processor, calendar_id=calendar_id, suffix="resurrect_due"
        )
        replacement_id = await _seed_instance(
            processor, calendar_id=calendar_id, suffix="resurrect_new"
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=journal_id,
            due_journal_id=journal_id,
            user_id=USER_ID,
        )
        await _cancel_instance(
            processor,
            calendar_id=calendar_id,
            suffix="resurrect_due",
            journal_id=journal_id,
        )
        assert (await read_service.read_model(USER_ID, task_id)).lapsed is True

        await service.retarget_due_journal(
            user_id=USER_ID,
            task_id=task_id,
            due_journal_id=replacement_id,
            transaction=async_connection,
        )

        model = await read_service.read_model(USER_ID, task_id)
        assert model.lapsed is False
        assert model.lapse_reason is None
        assert model.due_journal.id == replacement_id
        # The cancelled journal is still on the task, still marked, and now
        # decides nothing — which is the whole point of the previous assertion.
        assert [(ref.id, ref.cancelled) for ref in model.intermediate_journals] == [
            (journal_id, True)
        ]

    async def test_the_series_fan_out_reaches_the_same_verdict(
        self,
        async_connection: AsyncConnection,
        read_service: TaskReadService,
    ) -> None:
        """The other route to a cancelled journal, asserted separately.

        The fan-out decides per instance and reaches the cancellation through
        the delete guard's refusal, so it exercises different code from the
        single-instance event even though both end at the same column.
        """
        calendar_id = await create_calendar(async_connection, user_id=USER_ID)
        processor = build_processor(async_connection)
        journal_id = await _seed_instance(
            processor, calendar_id=calendar_id, suffix="series_due"
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=journal_id,
            due_journal_id=journal_id,
            user_id=USER_ID,
        )

        result = await processor.process_event(series_cancelled_event(calendar_id))

        # The guard refused the deletion the fan-out wanted, and the instance
        # was cancelled instead of being destroyed under the task.
        assert result["deleted"] == 0
        assert result["cancelled"] == 1
        assert await journal_exists(async_connection, journal_id)

        model = await read_service.read_model(USER_ID, task_id)
        assert model.lapsed is True
        assert model.lapse_reason is LapseReason.DUE_JOURNAL_CANCELLED

    async def test_only_the_due_journal_ref_is_marked_cancelled(
        self,
        async_connection: AsyncConnection,
        read_service: TaskReadService,
    ) -> None:
        """The flag lands on the journal that was cancelled and nowhere else.

        Three distinct journals in three roles, one of them cancelled: a read
        that marked every ref, or the wrong one, would still produce a lapsed
        task and pass the tests above.
        """
        calendar_id = await create_calendar(async_connection, user_id=USER_ID)
        processor = build_processor(async_connection)
        creating_id = await _seed_instance(
            processor, calendar_id=calendar_id, suffix="ref_creating"
        )
        due_id = await _seed_instance(
            processor, calendar_id=calendar_id, suffix="ref_due"
        )
        mention_id = await _seed_instance(
            processor, calendar_id=calendar_id, suffix="ref_mention"
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            user_id=USER_ID,
        )
        await link_intermediate_journal(
            async_connection, task_id=task_id, journal_id=mention_id
        )

        await _cancel_instance(
            processor,
            calendar_id=calendar_id,
            suffix="ref_due",
            journal_id=due_id,
        )

        model = await read_service.read_model(USER_ID, task_id)
        assert model.due_journal.cancelled is True
        assert model.creating_journal.cancelled is False
        assert [ref.cancelled for ref in model.intermediate_journals] == [False]

    @pytest.mark.parametrize("status", [TaskStatus.DONE, TaskStatus.CANCELLED])
    async def test_a_terminal_task_does_not_lapse(
        self,
        async_connection: AsyncConnection,
        read_service: TaskReadService,
        status: TaskStatus,
    ) -> None:
        """A commitment that was met or called off cannot then be let slide.

        Phase 12 asserts this at the rule; here the journal is really cancelled
        by the sync, which is the only arrangement that could show the status
        gate being bypassed somewhere between the write and the read.
        """
        calendar_id = await create_calendar(async_connection, user_id=USER_ID)
        processor = build_processor(async_connection)
        journal_id = await _seed_instance(
            processor, calendar_id=calendar_id, suffix=f"terminal_{status.value}"
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=journal_id,
            due_journal_id=journal_id,
            status=status,
            user_id=USER_ID,
        )

        await _cancel_instance(
            processor,
            calendar_id=calendar_id,
            suffix=f"terminal_{status.value}",
            journal_id=journal_id,
        )

        model = await read_service.read_model(USER_ID, task_id)
        assert model.due_journal.cancelled is True
        assert model.lapsed is False
        assert model.lapse_reason is None
        # And the cancellation did not quietly move the task's own status.
        assert model.task.status is status


@pytest.mark.integration
class TestCancellingAnyOtherJournalIsInert:
    async def test_cancelling_the_creating_journal_changes_no_verdict(
        self,
        async_connection: AsyncConnection,
        read_service: TaskReadService,
    ) -> None:
        """The creating journal is where the commitment arose, not when it is due.

        It is marked on its ref — a surface may want to say so — but it decides
        nothing, which is the third of this phase's acceptance criteria and the
        place the rule would first go wrong if it consulted every anchor.
        """
        calendar_id = await create_calendar(async_connection, user_id=USER_ID)
        processor = build_processor(async_connection)
        creating_id = await _seed_instance(
            processor, calendar_id=calendar_id, suffix="inert_creating"
        )
        due_id = await _seed_instance(
            processor, calendar_id=calendar_id, suffix="inert_due"
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            user_id=USER_ID,
        )

        await _cancel_instance(
            processor,
            calendar_id=calendar_id,
            suffix="inert_creating",
            journal_id=creating_id,
        )

        model = await read_service.read_model(USER_ID, task_id)
        assert model.creating_journal.cancelled is True
        assert model.due_journal.cancelled is False
        assert model.lapsed is False
        assert model.lapse_reason is None

    async def test_cancelling_a_mentioned_journal_changes_no_verdict(
        self,
        async_connection: AsyncConnection,
        read_service: TaskReadService,
    ) -> None:
        """A journal the task merely passed through decides nothing either.

        The mention is seeded **near** future so the sync cancels it rather than
        deleting it: nothing anchors it, so the delete guard has no reason to
        refuse, and a far-future instance would simply be destroyed — which is a
        different behaviour and not the one under test here.
        """
        calendar_id = await create_calendar(async_connection, user_id=USER_ID)
        processor = build_processor(async_connection)
        due_id = await _seed_instance(
            processor, calendar_id=calendar_id, suffix="mention_due"
        )
        mention_id = await _seed_instance(
            processor,
            calendar_id=calendar_id,
            suffix="mention_near",
            hours_from_now=NEAR_FUTURE_HOURS,
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=due_id,
            due_journal_id=due_id,
            user_id=USER_ID,
        )
        await link_intermediate_journal(
            async_connection, task_id=task_id, journal_id=mention_id
        )

        await _cancel_instance(
            processor,
            calendar_id=calendar_id,
            suffix="mention_near",
            journal_id=mention_id,
        )

        assert await event_state(async_connection, mention_id) == "cancelled"
        model = await read_service.read_model(USER_ID, task_id)
        assert [ref.cancelled for ref in model.intermediate_journals] == [True]
        assert model.lapsed is False
        assert model.lapse_reason is None


@pytest.mark.integration
class TestCancellationLeavesTheTaskAlone:
    async def test_cancellation_changes_no_task_links(
        self,
        async_connection: AsyncConnection,
        read_service: TaskReadService,
    ) -> None:
        """The specification's first cancellation rule, read from the tables.

        Every link a task can hold is present before the cancellation and has to
        be present, unchanged, afterwards: both anchors, an intermediate journal
        and a contact. Read back from the rows rather than from the read model,
        so a read model that papered over a lost link could not hide it.
        """
        calendar_id = await create_calendar(async_connection, user_id=USER_ID)
        processor = build_processor(async_connection)
        creating_id = await _seed_instance(
            processor, calendar_id=calendar_id, suffix="links_creating"
        )
        due_id = await _seed_instance(
            processor, calendar_id=calendar_id, suffix="links_due"
        )
        mention_id = await _seed_instance(
            processor, calendar_id=calendar_id, suffix="links_mention"
        )
        contact_id = await create_contact(async_connection, first_name="Priya")
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="return the harness",
            user_id=USER_ID,
        )
        await link_intermediate_journal(
            async_connection, task_id=task_id, journal_id=mention_id
        )
        await link_contact(async_connection, task_id=task_id, contact_id=contact_id)

        await _cancel_instance(
            processor,
            calendar_id=calendar_id,
            suffix="links_due",
            journal_id=due_id,
        )

        anchors = (
            await async_connection.execute(_SELECT_TASK_ANCHORS, {"task_id": task_id})
        ).one()
        assert anchors.creating_journal_id == creating_id
        assert anchors.due_journal_id == due_id
        assert anchors.status == TaskStatus.NOT_DONE.value
        assert anchors.text == "return the harness"
        mentions = (
            await async_connection.execute(_SELECT_MENTIONS, {"task_id": task_id})
        ).scalars()
        assert list(mentions) == [mention_id]
        assert await linked_contact_ids(async_connection, task_id) == [contact_id]

        # And the task still reads whole, now lapsed for the one right reason.
        model = await read_service.read_model(USER_ID, task_id)
        assert model.lapse_reason is LapseReason.DUE_JOURNAL_CANCELLED
        assert [ref.id for ref in model.intermediate_journals] == [mention_id]
        assert [ref.id for ref in model.contacts] == [contact_id]

    async def test_cancelling_a_journal_that_anchors_tasks_is_never_blocked(
        self,
        async_connection: AsyncConnection,
    ) -> None:
        """Cancellation is the escape hatch the delete guard steers users toward.

        Deleting this journal is refused whatever the anchored tasks' statuses,
        so cancelling it must not be — a guard that treated the two alike would
        leave a cancelled upstream event with nowhere to land, and the sync
        retrying it forever over a journal that is never going to become
        deletable.
        """
        calendar_id = await create_calendar(async_connection, user_id=USER_ID)
        processor = build_processor(async_connection)
        journal_id = await _seed_instance(
            processor, calendar_id=calendar_id, suffix="anchored_all_statuses"
        )
        for status in TaskStatus:
            await create_task(
                async_connection,
                creating_journal_id=journal_id,
                due_journal_id=journal_id,
                text=f"a {status.value} task",
                status=status,
                user_id=USER_ID,
            )

        result = await _cancel_instance(
            processor,
            calendar_id=calendar_id,
            suffix="anchored_all_statuses",
            journal_id=journal_id,
        )

        assert result["status"] == "success"
        assert result.get("action") != "deleted"
        assert await journal_exists(async_connection, journal_id)
        assert await event_state(async_connection, journal_id) == "cancelled"


@pytest.mark.integration
class TestCancellingThroughTheProductSurface:
    """The route a *person* takes, which is not the sync processor.

    Everything above drives calendar sync, because that is where a cancellation
    normally comes from. But a user can cancel an event journal themselves —
    the event editor's *Event Status* select offers "Cancelled", and it saves
    through ``PUT /api/journals/{id}/types/EVENT/data``, whose ``event_state``
    is an ordinary editable field of the EVENT type data.

    That path writes the same column by completely different code:
    ``JournalWriteService.update_type_data`` rather than
    ``_mark_journal_cancelled``. It reaches the lapse rule the same way and is
    the more important of the two to get right, because it is the one the
    specification's "cancel rather than delete" steer actually points at.
    """

    async def test_a_user_cancelling_the_event_lapses_the_task_due_in_it(
        self,
        async_connection: AsyncConnection,
        authenticated_client: Any,
        journal_repository: SqlJournalRepository,
        read_service: TaskReadService,
    ) -> None:
        """Cancel through the real endpoint; observe the lapse in the read model.

        The journal is made an event *before* the request — that is the
        arrangement, not the act. The cancellation itself is a real HTTP call
        through the real service, so nothing here seeds the state whose arrival
        is being asserted.
        """
        creating_id = await create_journal(
            journal_repository, title="Where it came up", days_offset=-1
        )
        due_id = await create_journal(
            journal_repository, title="Physio appointment", days_offset=10
        )
        await mark_journal_as_event(
            async_connection, due_id, event_state=EventState.CONFIRMED
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="take the referral",
        )

        before = await read_service.read_model(TASK_USER_ID, task_id)
        assert before.lapsed is False

        response = await authenticated_client.put(
            f"/api/journals/{due_id}/types/EVENT/data",
            json={
                "data": {
                    "type": "journal-type-data",
                    "attributes": {"event_state": EventState.CANCELLED.value},
                }
            },
        )

        assert response.status_code == 200
        after = await read_service.read_model(TASK_USER_ID, task_id)
        assert after.lapsed is True
        assert after.lapse_reason is LapseReason.DUE_JOURNAL_CANCELLED
        assert after.due_journal.cancelled is True

    async def test_a_user_un_cancelling_the_event_un_lapses_the_task(
        self,
        async_connection: AsyncConnection,
        authenticated_client: Any,
        journal_repository: SqlJournalRepository,
        read_service: TaskReadService,
    ) -> None:
        """The reverse, which only the user-facing path can do.

        Sync has no un-cancel; a person changing the status back does. It is
        worth asserting because it is the second demonstration that the lapse
        is *derived on every read* rather than recorded — and because a
        cancellation that could not be undone through the same control that
        applied it would be a trap.
        """
        due_id = await create_journal(
            journal_repository, title="Physio appointment", days_offset=10
        )
        await mark_journal_as_event(
            async_connection, due_id, event_state=EventState.CANCELLED
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=due_id,
            due_journal_id=due_id,
            text="take the referral",
        )
        assert (await read_service.read_model(TASK_USER_ID, task_id)).lapsed is True

        response = await authenticated_client.put(
            f"/api/journals/{due_id}/types/EVENT/data",
            json={
                "data": {
                    "type": "journal-type-data",
                    "attributes": {"event_state": EventState.CONFIRMED.value},
                }
            },
        )

        assert response.status_code == 200
        after = await read_service.read_model(TASK_USER_ID, task_id)
        assert after.lapsed is False
        assert after.lapse_reason is None
        assert after.due_journal.cancelled is False


@pytest.mark.integration
class TestTheLapseReachesTheReadSurfaces:
    """The same verdict, asked for the way a caller asks for it.

    ITER18-001 Phase 13 ships `GET /api/tasks/{id}` and
    `GET /api/journals/{id}/tasks`, and covers the cancellation lapse on both —
    against a journal it cancels by writing `journal_calendar_info` directly.
    That proves the *serialisation* and assumes the write, which is the split
    this phase exists to close. These two ask the same surfaces after a **real**
    cancellation, so the whole chain is exercised in one test: user action →
    type-data update → the column → the batched cancellation lookup → the rule →
    the JSON a client actually receives.
    """

    async def _cancel_via_api(self, client: Any, journal_id: int) -> None:
        """Cancel an event journal the way the event editor does."""
        response = await client.put(
            f"/api/journals/{journal_id}/types/EVENT/data",
            json={
                "data": {
                    "type": "journal-type-data",
                    "attributes": {"event_state": EventState.CANCELLED.value},
                }
            },
        )
        assert response.status_code == 200

    async def test_get_task_reports_the_cancellation_after_a_real_one(
        self,
        async_connection: AsyncConnection,
        authenticated_client: Any,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """`GET /api/tasks/{id}` names cancellation, not the passage of time.

        The journal is a week out, so `date_passed` cannot be the reason and a
        surface that reported merely "lapsed" would fail here.
        """
        creating_id = await create_journal(
            journal_repository, title="Where it came up", days_offset=-1
        )
        due_id = await create_journal(
            journal_repository, title="Physio appointment", days_offset=7
        )
        await mark_journal_as_event(
            async_connection, due_id, event_state=EventState.CONFIRMED
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="take the referral",
        )

        before = await authenticated_client.get(f"/api/tasks/{task_id}")
        assert before.json()["data"]["attributes"]["lapsed"] is False

        await self._cancel_via_api(authenticated_client, due_id)

        attributes = (await authenticated_client.get(f"/api/tasks/{task_id}")).json()[
            "data"
        ]["attributes"]
        assert attributes["lapsed"] is True
        assert attributes["lapse_reason"] == LapseReason.DUE_JOURNAL_CANCELLED.value
        assert attributes["due_journal"]["cancelled"] is True

    async def test_the_journal_listing_reports_the_cancellation_too(
        self,
        async_connection: AsyncConnection,
        authenticated_client: Any,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """`GET /api/journals/{id}/tasks` is the surface the spec describes.

        "The journal listing on the task should make it obvious that the reason
        is cancellation rather than the passage of time" — this is that listing,
        asked for on the cancelled journal itself, where the user meets the
        lapsed task.
        """
        due_id = await create_journal(
            journal_repository, title="Physio appointment", days_offset=7
        )
        await mark_journal_as_event(
            async_connection, due_id, event_state=EventState.CONFIRMED
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=due_id,
            due_journal_id=due_id,
            text="take the referral",
        )

        await self._cancel_via_api(authenticated_client, due_id)

        payload = (
            await authenticated_client.get(f"/api/journals/{due_id}/tasks")
        ).json()
        rows = [row for row in payload["data"] if int(row["id"]) == task_id]
        assert len(rows) == 1
        attributes = rows[0]["attributes"]
        assert attributes["lapsed"] is True
        assert attributes["lapse_reason"] == LapseReason.DUE_JOURNAL_CANCELLED.value
