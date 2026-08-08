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

from unittest.mock import AsyncMock

import pytest
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
    USER_ID,
    make_task,
)

NEW_TEXT = "return Sarah's book and the DVD"


async def update(
    service: TaskService,
    transaction: AsyncMock,
    *,
    text: str | None = None,
    status: TaskStatus | None = None,
    user_id: str = USER_ID,
    task_id: int = TASK_ID,
) -> Task:
    """Call ``update_task`` with the ordinary arguments, overriding as needed."""
    return await service.update_task(
        user_id=user_id,
        task_id=task_id,
        text=text,
        status=status,
        transaction=transaction,
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

        result = await update(service, mock_transaction, text=NEW_TEXT)

        saved = mock_task_repo.save.await_args.args[0]
        assert saved.text == NEW_TEXT
        assert result.text == NEW_TEXT

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

        result = await update(service, mock_transaction, text=NEW_TEXT)

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
        await update(service, mock_transaction, text=NEW_TEXT)

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
        await update(service, mock_transaction, text=NEW_TEXT)

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
        await update(service, mock_transaction, text=NEW_TEXT)

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
        await update(service, mock_transaction, text=NEW_TEXT)

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
            await update(service, mock_transaction, text=NEW_TEXT)

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
                service, mock_transaction, text=NEW_TEXT, user_id=OTHER_USER_ID
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
            service, mock_transaction, text=NEW_TEXT, status=TaskStatus.DONE
        )

        assert mock_task_repo.save.await_count == 1
        saved = mock_task_repo.save.await_args.args[0]
        assert saved.text == NEW_TEXT
        assert saved.status == TaskStatus.DONE
        assert result.text == NEW_TEXT
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
                service, mock_transaction, text=NEW_TEXT, status=TaskStatus.DONE
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
            service, mock_transaction, text=NEW_TEXT, status=TaskStatus.NOT_DONE
        )

        assert mock_task_repo.save.await_count == 1
        assert result.text == NEW_TEXT
