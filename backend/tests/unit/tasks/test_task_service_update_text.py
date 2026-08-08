"""Unit tests for ``TaskService.update_task`` — rewording a task.

The specification puts text under *Status and lifecycle*: "Task text and contact
links can be edited at any time, **in any status**", and under *Journal links
and retargeting*: "Updating a task never requires a journal." Both are absolute,
so both are asserted here rather than left to the surfaces.

What is under test:

- text is editable from **every** status, including cancelled, and an edit
  changes the text and nothing else;
- **no journal and no other domain is involved** — the due journal is not even
  read, which is what keeps a *lapsed* task editable;
- the read is the **locking** read, because this method decides from what it
  read and writes that decision back (Phase 6's lesson, inherited);
- an unknown task and another user's task are the same answer;
- a call that changes nothing writes nothing, extending Phase 6's same-status
  no-op to same-text;
- text and status arriving together are applied as **one** write, which is the
  reason a single method owns both.

The transition matrix itself lives in ``test_task_status_transitions.py`` and
the status path's own rules in ``test_task_service_set_status.py``; only their
interaction with a text edit is asserted here.

Repositories are mocked: none of this needs a database, and the SQL is covered
by ``test_task_service_update_and_delete_integration.py``.
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest
from core_shared.models.history import Provenance
from core_shared.models.tasks import (
    Task,
    TaskNotFoundError,
    TaskStatus,
    TaskStatusTransitionError,
    TaskValidationError,
)

from app.core.tasks.services.task_service import TaskService
from tests.unit.tasks.task_doubles import (
    CREATING_JOURNAL_ID,
    DUE_JOURNAL_ID,
    ORIGINAL_TEXT,
    OTHER_USER_ID,
    TASK_ID,
    UPDATED_TEXT,
    USER_ID,
    make_task,
    published_events,
)


async def update(
    service: TaskService,
    transaction: AsyncMock,
    *,
    text: str | None = None,
    status: TaskStatus | None = None,
    user_id: str = USER_ID,
    task_id: int = TASK_ID,
    source: Provenance | None = None,
    changed_by: str | None = None,
) -> Task:
    """Call ``update_task`` with the ordinary arguments, overriding as needed.

    ``source`` and ``changed_by`` are omitted entirely unless a test names one,
    so the service's own defaults are exercised by every test that does not care
    where the change came from — and asserted by the one that does.
    """
    provenance: dict[str, Any] = {}
    if source is not None:
        provenance["source"] = source
    if changed_by is not None:
        provenance["changed_by"] = changed_by
    return await service.update_task(
        user_id=user_id,
        task_id=task_id,
        text=text,
        status=status,
        transaction=transaction,
        **provenance,
    )


@pytest.mark.unit
class TestTextIsEditableInAnyStatus:
    """ "In any status" is the whole rule, so every status is asserted."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", list(TaskStatus))
    async def test_the_new_text_is_written_and_returned(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
        status: TaskStatus,
    ) -> None:
        """Including cancelled: a retired commitment can still be reworded."""
        mock_task_repo.find_by_id_for_update.return_value = make_task(status)

        result = await update(service, mock_transaction, text=UPDATED_TEXT)

        saved = mock_task_repo.save.await_args.args[0]
        assert saved.text == UPDATED_TEXT
        assert result.text == UPDATED_TEXT

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", list(TaskStatus))
    async def test_the_status_is_carried_through_unchanged(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
        status: TaskStatus,
    ) -> None:
        """Rewording a cancelled task must not quietly reopen it.

        Reopening happens by retargeting and by nothing else, so a text edit
        that moved the status would be a second exit from cancelled reached by
        accident — the hole Phase 6 exists to close.
        """
        mock_task_repo.find_by_id_for_update.return_value = make_task(status)

        result = await update(service, mock_transaction, text=UPDATED_TEXT)

        saved = mock_task_repo.save.await_args.args[0]
        assert saved.status == status
        assert result.status == status

    @pytest.mark.asyncio
    async def test_the_anchors_and_the_owner_are_untouched(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The creating journal is immutable and the due journal is retargeted
        elsewhere; neither moves because somebody fixed a typo."""
        await update(service, mock_transaction, text=UPDATED_TEXT)

        saved = mock_task_repo.save.await_args.args[0]
        assert saved.creating_journal_id == CREATING_JOURNAL_ID
        assert saved.due_journal_id == DUE_JOURNAL_ID
        assert saved.user_id == USER_ID
        assert saved.id == TASK_ID


@pytest.mark.unit
class TestNoJournalIsInvolved:
    """ "Updating a task never requires a journal" — specification, verbatim."""

    @pytest.mark.asyncio
    async def test_no_other_domain_is_touched_at_all(
        self,
        service: TaskService,
        mock_journal_repo: AsyncMock,
        mock_contact_repo: AsyncMock,
        mock_settings_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Not even the due journal is loaded, which is what keeps a *lapsed*
        task editable.

        Re-reading the due journal here would invite a future-dated re-check on
        a rule the specification applies only when a due journal is **set** —
        and would then refuse to fix a typo on precisely the tasks a user most
        needs to tidy up.

        Asserted on ``mock_calls`` rather than on named methods, per Phase 6: a
        named-method assertion passes for any method added to the port later,
        which is the opposite of what "no journal is involved" guarantees.
        """
        await update(service, mock_transaction, text=UPDATED_TEXT)

        assert mock_journal_repo.mock_calls == []
        assert mock_contact_repo.mock_calls == []
        assert mock_settings_repo.mock_calls == []

    @pytest.mark.asyncio
    async def test_no_link_row_is_written(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Intermediate links are explicit only; nothing is inferred from an edit."""
        await update(service, mock_transaction, text=UPDATED_TEXT)

        mock_task_repo.add_intermediate_journal.assert_not_awaited()
        mock_task_repo.add_contact.assert_not_awaited()


@pytest.mark.unit
class TestTheReadIsOwnerScopedAndLocked:
    """The row is held for as long as the decision takes."""

    @pytest.mark.asyncio
    async def test_the_locking_read_is_used(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Which read is used is load-bearing, so it is asserted directly.

        This method reads a task, decides from what it read, and writes that
        decision back — the shape that loses a *rule*, not merely a field, when
        two calls overlap. A refactor that "simplified" this back to the plain
        read would reopen the hole Phase 6 closed, silently.
        """
        await update(service, mock_transaction, text=UPDATED_TEXT)

        mock_task_repo.find_by_id_for_update.assert_awaited_once_with(TASK_ID, USER_ID)
        mock_task_repo.find_by_id.assert_not_awaited()


@pytest.mark.unit
class TestTextValidation:
    """The entity owns what an acceptable text is; the service does not restate it."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
    async def test_blank_text_is_refused_and_nothing_is_written(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
        blank: str,
    ) -> None:
        """A task with no text says nothing, so an edit cannot empty one out."""
        with pytest.raises(TaskValidationError) as exc_info:
            await update(service, mock_transaction, text=blank)

        assert exc_info.value.field == "text"
        assert exc_info.value.status_code == 400
        mock_task_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_there_is_no_length_bound(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Settled in Phase 1: plain text in a ``TEXT`` column, unbounded.

        Short text is a product convention, not a constraint — so an edit that
        makes a task long is accepted rather than rejected by a limit nobody
        agreed to.
        """
        long_text = "x" * 10_000

        await update(service, mock_transaction, text=long_text)

        assert mock_task_repo.save.await_args.args[0].text == long_text

    @pytest.mark.asyncio
    async def test_text_is_stored_verbatim_rather_than_trimmed(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Creation does not trim, so neither does an edit.

        Trimming on one path and not the other would make a task's text depend
        on which surface last wrote it.
        """
        await update(service, mock_transaction, text="  spaced out  ")

        assert mock_task_repo.save.await_args.args[0].text == "  spaced out  "


@pytest.mark.unit
class TestUnreachableTasks:
    """Somebody else's task and a nonexistent one are the same answer."""

    @pytest.mark.asyncio
    async def test_an_unknown_task_is_not_found(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        mock_task_repo.find_by_id_for_update.return_value = None

        with pytest.raises(TaskNotFoundError) as exc_info:
            await update(service, mock_transaction, text=UPDATED_TEXT)

        assert exc_info.value.task_id == TASK_ID
        mock_task_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_another_users_task_is_indistinguishable(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The owner-scoped read returns nothing, so the message cannot leak.

        The service never compares a ``user_id`` itself, so there is no branch
        that could say more than "not found".
        """
        mock_task_repo.find_by_id_for_update.return_value = None

        with pytest.raises(TaskNotFoundError) as exc_info:
            await update(
                service, mock_transaction, text=UPDATED_TEXT, user_id=OTHER_USER_ID
            )

        assert str(exc_info.value) == str(TaskNotFoundError(TASK_ID))
        mock_task_repo.find_by_id_for_update.assert_awaited_once_with(
            TASK_ID, OTHER_USER_ID
        )
        mock_task_repo.save.assert_not_awaited()


@pytest.mark.unit
class TestAnUpdateThatChangesNothing:
    """Phase 6's same-status no-op, extended to the text."""

    @pytest.mark.asyncio
    async def test_the_same_text_is_a_no_op(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """``updated_at`` must not move for an edit that edited nothing.

        ITER18-002's history projection derives its events from writes, so a
        write that changed nothing would show up as a change that never
        happened.
        """
        result = await update(service, mock_transaction, text=ORIGINAL_TEXT)

        assert result.text == ORIGINAL_TEXT
        mock_task_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_empty_update_is_a_no_op_rather_than_a_failure(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Naming no change is refused by the REST schema, not by the service.

        The surfaces decide whether an empty request is meaningful — the JSON:API
        one says no, because a body with no attributes is a malformed request.
        Down here it is simply nothing to do, so the service stays free of a
        rule that belongs to a transport.
        """
        result = await update(service, mock_transaction)

        assert result.text == ORIGINAL_TEXT
        mock_task_repo.save.assert_not_awaited()


@pytest.mark.unit
class TestTextAndStatusTogether:
    """One method owns both, so one write applies both."""

    @pytest.mark.asyncio
    async def test_both_are_applied_in_a_single_save(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """This is the reason the two are not separate service calls.

        Two calls would be two units of work and two read-decide-write
        sequences, so a client that reworded and completed a task in one request
        could have half of it applied.
        """
        result = await update(
            service, mock_transaction, text=UPDATED_TEXT, status=TaskStatus.DONE
        )

        assert mock_task_repo.save.await_count == 1
        saved = mock_task_repo.save.await_args.args[0]
        assert saved.text == UPDATED_TEXT
        assert saved.status == TaskStatus.DONE
        assert result.text == UPDATED_TEXT
        assert result.status == TaskStatus.DONE

    @pytest.mark.asyncio
    async def test_a_refused_transition_takes_the_text_edit_with_it(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """One request is one decision: a refused half refuses the whole."""
        mock_task_repo.find_by_id_for_update.return_value = make_task(
            TaskStatus.CANCELLED
        )

        with pytest.raises(TaskStatusTransitionError):
            await update(
                service, mock_transaction, text=UPDATED_TEXT, status=TaskStatus.DONE
            )

        mock_task_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_blank_text_is_refused_before_the_status_is_considered(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The entity's own rules come first, as they do on creation.

        Pinned so the answer to a doubly-invalid request is stable: the caller
        is told about the text, which is the field they got wrong outright,
        rather than about a transition they might not have intended to make.
        """
        mock_task_repo.find_by_id_for_update.return_value = make_task(
            TaskStatus.CANCELLED
        )

        with pytest.raises(TaskValidationError):
            await update(service, mock_transaction, text="", status=TaskStatus.DONE)

        mock_task_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_text_edit_alongside_the_status_it_already_has_still_writes(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The no-op rule is about the *request*, not about either field alone."""
        result = await update(
            service, mock_transaction, text=UPDATED_TEXT, status=TaskStatus.NOT_DONE
        )

        assert mock_task_repo.save.await_count == 1
        assert result.text == UPDATED_TEXT


@pytest.mark.unit
class TestTheChangeIsAnnounced:
    """One write, one ``TaskUpdated`` — carrying only what actually moved.

    The specification makes tasks first-class domain entities emitting events
    "through the same transactional outbox and stream that contacts and journals
    use", covering task text updated and task status changed. Both live on this
    method, so both are asserted here; the status path's own event rules — the
    refusal, the delegation from ``set_status`` — are in
    ``test_task_service_set_status.py``.
    """

    @pytest.mark.asyncio
    async def test_a_reword_publishes_exactly_one_task_updated_event(
        self,
        service: TaskService,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        await update(service, mock_transaction, text=UPDATED_TEXT)

        (event,) = published_events(mock_event_publisher)
        assert event.event_type == "TaskUpdated"
        assert event.aggregate_id == TASK_ID

    @pytest.mark.asyncio
    async def test_the_reword_is_carried_as_an_old_new_pair(
        self,
        service: TaskService,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The old text comes from the read; it exists nowhere else.

        Once the row is saved the previous wording is gone, so an event that
        carried only the new text would leave the history unable to say what the
        task used to say — which is most of what a change record is for.
        """
        await update(service, mock_transaction, text=UPDATED_TEXT)

        (event,) = published_events(mock_event_publisher)
        assert event.event_data["changed_fields"]["text"] == (
            ORIGINAL_TEXT,
            UPDATED_TEXT,
        )

    @pytest.mark.asyncio
    async def test_a_reword_says_nothing_about_the_status(
        self,
        service: TaskService,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Only what moved is named.

        A ``status`` key here — even one whose two halves are equal — would
        project a history row claiming the user changed a status they never
        touched.
        """
        await update(service, mock_transaction, text=UPDATED_TEXT)

        (event,) = published_events(mock_event_publisher)
        assert list(event.event_data["changed_fields"]) == ["text"]

    @pytest.mark.asyncio
    async def test_text_and_status_together_publish_one_event_with_both_fields(
        self,
        service: TaskService,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The decision this phase turns on: one write is one event.

        A ``PATCH`` that rewords a task and completes it is a single unit of
        work, and publishing two events for it would announce two changes where
        one happened — and would make "every task write path publishes exactly
        one event" false for this path alone. Asserted through the whole
        published list rather than "a ``TaskUpdated`` is among them", because
        the count is the claim.
        """
        await update(
            service, mock_transaction, text=UPDATED_TEXT, status=TaskStatus.DONE
        )

        events = published_events(mock_event_publisher)
        assert [event.event_type for event in events] == ["TaskUpdated"]
        assert events[0].event_data["changed_fields"] == {
            "text": (ORIGINAL_TEXT, UPDATED_TEXT),
            "status": (TaskStatus.NOT_DONE.value, TaskStatus.DONE.value),
        }

    @pytest.mark.asyncio
    async def test_a_field_that_was_sent_but_did_not_move_is_left_out(
        self,
        service: TaskService,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """A client resending the current text is not a text change.

        Both surfaces send whole resources, so the text a caller "changed" is
        routinely the text it already had. What the event names is what the
        service *decided*, not what it was handed.
        """
        await update(
            service, mock_transaction, text=ORIGINAL_TEXT, status=TaskStatus.DONE
        )

        (event,) = published_events(mock_event_publisher)
        assert list(event.event_data["changed_fields"]) == ["status"]

    @pytest.mark.asyncio
    async def test_an_update_that_changes_nothing_publishes_nothing(
        self,
        service: TaskService,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """No write, no event.

        A no-op that still published would put a change into the user's history
        that never happened — and, unlike a spurious ``updated_at``, one they
        would actually read.
        """
        await update(service, mock_transaction, text=ORIGINAL_TEXT)

        assert published_events(mock_event_publisher) == []

    @pytest.mark.asyncio
    async def test_an_empty_update_publishes_nothing(
        self,
        service: TaskService,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        await update(service, mock_transaction)

        assert published_events(mock_event_publisher) == []

    @pytest.mark.asyncio
    async def test_an_unknown_task_publishes_nothing(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        mock_task_repo.find_by_id_for_update.return_value = None

        with pytest.raises(TaskNotFoundError):
            await update(service, mock_transaction, text=UPDATED_TEXT)

        assert published_events(mock_event_publisher) == []

    @pytest.mark.asyncio
    async def test_blank_text_publishes_nothing(
        self,
        service: TaskService,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        with pytest.raises(TaskValidationError):
            await update(service, mock_transaction, text="")

        assert published_events(mock_event_publisher) == []

    @pytest.mark.asyncio
    async def test_the_event_follows_the_save_rather_than_preceding_it(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The event announces a change that finished.

        Ordering cannot be asserted by reading the code and is invisible in a
        passing test that only checks *what* was published, so it is proved by
        breaking the write: with ``save`` failing, a service that published
        first would still have announced the change.
        """
        mock_task_repo.save.side_effect = RuntimeError("write failed")

        with pytest.raises(RuntimeError):
            await update(service, mock_transaction, text=UPDATED_TEXT)

        assert published_events(mock_event_publisher) == []

    @pytest.mark.asyncio
    async def test_the_event_carries_the_owner(
        self,
        service: TaskService,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Phase 8 scopes a task-scoped history read by this, not by the row."""
        await update(service, mock_transaction, text=UPDATED_TEXT)

        (event,) = published_events(mock_event_publisher)
        assert event.event_data["user_id"] == USER_ID
        assert event.event_data["task_id"] == TASK_ID

    @pytest.mark.asyncio
    async def test_a_caller_that_names_no_origin_is_recorded_as_the_system(
        self,
        service: TaskService,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The default is deliberately the honest one, not "ui".

        A surface that forgets to say where it is calling from files a person's
        edit under "system" rather than mislabelling it as somebody's click —
        wrong, but wrong in the direction that does not invent an actor. The
        surfaces are each asserted to remember, in their own integration tests.
        """
        await update(service, mock_transaction, text=UPDATED_TEXT)

        (event,) = published_events(mock_event_publisher)
        assert event.event_data["source"] == Provenance.SYSTEM.value
        assert event.event_data["changed_by"] == "system"

    @pytest.mark.asyncio
    async def test_a_person_editing_in_the_browser_is_recorded_as_ui(
        self,
        service: TaskService,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        await update(
            service,
            mock_transaction,
            text=UPDATED_TEXT,
            source=Provenance.UI,
            changed_by="ui",
        )

        (event,) = published_events(mock_event_publisher)
        assert event.event_data["source"] == Provenance.UI.value
        assert event.event_data["changed_by"] == "ui"

    @pytest.mark.asyncio
    async def test_an_ai_agent_rewording_a_task_is_recorded_as_mcp(
        self,
        service: TaskService,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The case the activity-history specification exists to make visible."""
        await update(
            service,
            mock_transaction,
            text=UPDATED_TEXT,
            source=Provenance.MCP,
            changed_by="mcp",
        )

        (event,) = published_events(mock_event_publisher)
        assert event.event_data["source"] == Provenance.MCP.value
        assert event.event_data["changed_by"] == "mcp"

    @pytest.mark.asyncio
    async def test_the_event_is_handed_the_calling_transaction(
        self,
        service: TaskService,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Protocol conformance, not the atomicity guarantee.

        ``OutboxEventPublisher`` never reads this field — it inserts on the
        connection DI handed it, which is the same request connection the
        repositories got, and *that* is what makes the outbox row live or die
        with the task row. The evidence for it is in
        ``test_task_events_integration.py``, against a real database.
        """
        await update(service, mock_transaction, text=UPDATED_TEXT)

        (event,) = published_events(mock_event_publisher)
        assert event.transaction is mock_transaction
