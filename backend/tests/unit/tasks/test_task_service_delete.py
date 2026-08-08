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
from core_shared.models.tasks import TaskNotFoundError

from app.core.tasks.services.task_service import TaskService
from tests.unit.tasks.task_doubles import OTHER_USER_ID, TASK_ID, USER_ID


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
