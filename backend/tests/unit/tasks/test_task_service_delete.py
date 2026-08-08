"""Unit tests for ``TaskService.delete_task``.

Hard deletion "exists for genuine mistakes", and the specification is explicit
that cancelling is the ordinary action. That stance is carried by the *surfaces*
— it is what their docstrings must say — while the service's job is narrower and
absolute: remove that user's task and nothing else.

What is under test here is the shape of the operation rather than the SQL:

- the delete is **owner-scoped in the repository**, so another user's task is
  the same answer as one that never existed;
- **no read precedes it.** The statement is atomic and already owner-scoped, so
  unlike ``update_task`` there is no read-decide-write sequence to lose a rule,
  and a locking read here would buy nothing;
- **the links are the database's job.** Both link tables cascade from
  ``task_id``, so the service does not walk them — and must not, because a
  service that removed them one at a time could leave half of them behind.

That the cascade actually happens, and that the journals and contacts survive
it, is a property of the schema and is asserted against a real database in
``test_task_service_update_and_delete_integration.py``.
"""

from unittest.mock import AsyncMock

import pytest
from core_shared.models.history import Provenance
from core_shared.models.tasks import TaskNotFoundError

from app.core.tasks.services.task_service import TaskService
from tests.unit.tasks.task_doubles import (
    OTHER_USER_ID,
    TASK_ID,
    USER_ID,
    published_events,
)


@pytest.mark.unit
class TestDeletingATask:
    """The happy path, and what it may not touch."""

    @pytest.mark.asyncio
    async def test_the_delete_is_owner_scoped(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The acting user goes to the repository, which filters on it."""
        await service.delete_task(
            user_id=USER_ID, task_id=TASK_ID, transaction=mock_transaction
        )

        mock_task_repo.delete.assert_awaited_once_with(TASK_ID, USER_ID)

    @pytest.mark.asyncio
    async def test_no_read_precedes_the_delete(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """A locking read would be cargo-cult here, so its absence is pinned.

        ``update_task`` needs one because it decides from what it read. A delete
        decides nothing: the single owner-scoped statement either removes a row
        or does not, and reports which. Adding a read would add a round trip and
        a second way for the two to disagree.
        """
        await service.delete_task(
            user_id=USER_ID, task_id=TASK_ID, transaction=mock_transaction
        )

        mock_task_repo.find_by_id.assert_not_awaited()
        mock_task_repo.find_by_id_for_update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_links_are_left_to_the_cascade(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Walking the link tables by hand could leave half of them behind."""
        await service.delete_task(
            user_id=USER_ID, task_id=TASK_ID, transaction=mock_transaction
        )

        mock_task_repo.remove_contact.assert_not_awaited()
        mock_task_repo.remove_intermediate_journal.assert_not_awaited()
        mock_task_repo.list_contact_ids.assert_not_awaited()
        mock_task_repo.list_intermediate_journal_ids.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_other_domain_is_touched_at_all(
        self,
        service: TaskService,
        mock_journal_repo: AsyncMock,
        mock_contact_repo: AsyncMock,
        mock_settings_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """ "Removing the task and its link rows and nothing else" — the criterion.

        The journals and contacts a task pointed at are not the task's to
        destroy, and the shortest way to guarantee that is for the service never
        to hold either repository's attention.
        """
        await service.delete_task(
            user_id=USER_ID, task_id=TASK_ID, transaction=mock_transaction
        )

        assert mock_journal_repo.mock_calls == []
        assert mock_contact_repo.mock_calls == []
        assert mock_settings_repo.mock_calls == []

    @pytest.mark.asyncio
    async def test_nothing_is_saved(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Deletion is not a soft state; cancelling is, and lives elsewhere."""
        await service.delete_task(
            user_id=USER_ID, task_id=TASK_ID, transaction=mock_transaction
        )

        mock_task_repo.save.assert_not_awaited()


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
        """The repository reports a delete that matched no row; it is not swallowed.

        A delete that quietly succeeded on a task that was not there would tell
        a caller — and an agent retrying one — that a commitment is gone when it
        may still be sitting on somebody's journal.
        """
        mock_task_repo.delete.side_effect = TaskNotFoundError(TASK_ID)

        with pytest.raises(TaskNotFoundError) as exc_info:
            await service.delete_task(
                user_id=USER_ID, task_id=TASK_ID, transaction=mock_transaction
            )

        assert exc_info.value.task_id == TASK_ID

    @pytest.mark.asyncio
    async def test_another_users_task_is_indistinguishable(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Owner scoping happens in the statement, so the message cannot leak."""
        mock_task_repo.delete.side_effect = TaskNotFoundError(TASK_ID)

        with pytest.raises(TaskNotFoundError) as exc_info:
            await service.delete_task(
                user_id=OTHER_USER_ID, task_id=TASK_ID, transaction=mock_transaction
            )

        assert str(exc_info.value) == str(TaskNotFoundError(TASK_ID))
        mock_task_repo.delete.assert_awaited_once_with(TASK_ID, OTHER_USER_ID)


@pytest.mark.unit
class TestDeletionPublishesAnEvent:
    """A deletion is the one change with no row left to read it from.

    Everything else about a task can be recovered by looking at the task. Once
    it is hard-deleted the event is the only record that it ever existed, which
    is why the history projection needs it and why these assertions are about
    the event rather than about the row.
    """

    @pytest.mark.asyncio
    async def test_publishes_exactly_one_task_deleted_event(
        self,
        service: TaskService,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        await service.delete_task(
            user_id=USER_ID, task_id=TASK_ID, transaction=mock_transaction
        )

        (event,) = published_events(mock_event_publisher)
        assert event.event_type == "TaskDeleted"

    @pytest.mark.asyncio
    async def test_the_event_names_the_task_and_its_owner(
        self,
        service: TaskService,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Ownership travels on the event because the row that carried it is gone.

        A task-scoped history read has to answer "is this yours?" for a task
        that no longer exists, and the only place left to ask is here.
        """
        await service.delete_task(
            user_id=USER_ID, task_id=TASK_ID, transaction=mock_transaction
        )

        (event,) = published_events(mock_event_publisher)
        assert event.aggregate_id == TASK_ID
        assert event.event_data["task_id"] == TASK_ID
        assert event.event_data["user_id"] == USER_ID

    @pytest.mark.asyncio
    async def test_the_event_is_built_with_the_callers_connection(
        self,
        service: TaskService,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Protocol conformance only — see the create-side test of the same name.

        The publisher does not read this field; the outbox row shares the task's
        transaction because DI gives both the same connection, which is asserted
        against a live one in ``test_task_events_integration.py``.
        """
        await service.delete_task(
            user_id=USER_ID, task_id=TASK_ID, transaction=mock_transaction
        )

        (event,) = published_events(mock_event_publisher)
        assert event.transaction is mock_transaction

    @pytest.mark.asyncio
    async def test_publishing_still_reads_nothing(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The event did not buy itself a read.

        Enriching the payload with the task's text would have needed one, and
        this method's whole point is that it decides nothing from what it read.
        The payload is therefore a marker: task, owner, provenance.
        """
        await service.delete_task(
            user_id=USER_ID, task_id=TASK_ID, transaction=mock_transaction
        )

        mock_task_repo.find_by_id.assert_not_awaited()
        mock_task_repo.find_by_id_for_update.assert_not_awaited()

        (event,) = published_events(mock_event_publisher)
        assert set(event.event_data) == {
            "task_id",
            "user_id",
            "source",
            "changed_by",
        }


@pytest.mark.unit
class TestDeletionProvenance:
    """Who deleted it is as much of the record as that it was deleted."""

    @pytest.mark.asyncio
    async def test_defaults_to_system(
        self,
        service: TaskService,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        await service.delete_task(
            user_id=USER_ID, task_id=TASK_ID, transaction=mock_transaction
        )

        (event,) = published_events(mock_event_publisher)
        assert event.event_data["source"] == Provenance.SYSTEM.value
        assert event.event_data["changed_by"] == "system"

    @pytest.mark.asyncio
    async def test_records_the_ui_as_the_origin(
        self,
        service: TaskService,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        await service.delete_task(
            user_id=USER_ID,
            task_id=TASK_ID,
            transaction=mock_transaction,
            source=Provenance.UI,
            changed_by="ui",
        )

        (event,) = published_events(mock_event_publisher)
        assert event.event_data["source"] == Provenance.UI.value
        assert event.event_data["changed_by"] == "ui"

    @pytest.mark.asyncio
    async def test_records_an_ai_agent_as_the_origin(
        self,
        service: TaskService,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """An agent deleting a task is exactly the case the user needs to see."""
        await service.delete_task(
            user_id=USER_ID,
            task_id=TASK_ID,
            transaction=mock_transaction,
            source=Provenance.MCP,
            changed_by="mcp",
        )

        (event,) = published_events(mock_event_publisher)
        assert event.event_data["source"] == Provenance.MCP.value
        assert event.event_data["changed_by"] == "mcp"


@pytest.mark.unit
class TestRefusedDeletesAnnounceNothing:
    """A delete that removed no row is not a deletion."""

    @pytest.mark.asyncio
    async def test_an_unknown_task_publishes_nothing(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Otherwise a repeated delete would write a second deletion to history."""
        mock_task_repo.delete.side_effect = TaskNotFoundError(TASK_ID)

        with pytest.raises(TaskNotFoundError):
            await service.delete_task(
                user_id=USER_ID, task_id=TASK_ID, transaction=mock_transaction
            )

        assert published_events(mock_event_publisher) == []

    @pytest.mark.asyncio
    async def test_another_users_task_publishes_nothing(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """A refused delete must not leak the task's existence into an event either."""
        mock_task_repo.delete.side_effect = TaskNotFoundError(TASK_ID)

        with pytest.raises(TaskNotFoundError):
            await service.delete_task(
                user_id=OTHER_USER_ID, task_id=TASK_ID, transaction=mock_transaction
            )

        assert published_events(mock_event_publisher) == []
