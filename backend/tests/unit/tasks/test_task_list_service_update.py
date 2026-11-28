"""Unit tests for associating a list with a journal through
``TaskListService.update_task_list``, against mocked ports.

What is pinned here is the service's own part:

- a patch naming a journal takes that journal ``FOR KEY SHARE`` **before** the
  list's row lock — the order a journal delete or merge takes, holding the
  journal before any list — and a patch that clears the association or leaves
  it alone takes no journal at all;
- what is refused, and in which order: a missing list, then an archived one,
  then an unreachable journal, with nothing written or published;
- an association the list already has is a no-op;
- the ``associated_journal_id`` pair each change announces.

The rows, the owner-scoped journal read and the lock order between real
transactions are proved in
``tests/integration/tasks/test_task_list_service_integration.py`` and
``tests/integration/tasks/test_task_list_association_lock_order_integration.py``.
"""

import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from core_shared.models.history import Provenance
from core_shared.models.journals import EventDateRange, Journal
from core_shared.models.tasks import (
    TaskList,
    TaskListArchivedError,
    TaskListJournalNotFoundError,
    TaskListNotFoundError,
)

from app.core.tasks.models.events import DomainEvent
from app.core.tasks.models.task_list_events import TaskListUpdated
from app.core.tasks.services.task_list_patch import TaskListPatch
from app.core.tasks.services.task_list_service import TaskListService

pytestmark = pytest.mark.unit

USER_ID = "user-1"
LIST_ID = 7
JOURNAL_ID = 31
OTHER_JOURNAL_ID = 32
ARCHIVED_AT = datetime.datetime(2026, 11, 1, tzinfo=datetime.UTC)


def _list(*, journal_id: int | None = None, archived: bool = False) -> TaskList:
    return TaskList(
        id=LIST_ID,
        user_id=USER_ID,
        name="Packing",
        position=0,
        associated_journal_id=journal_id,
        archived_at=ARCHIVED_AT if archived else None,
    )


def _journal(journal_id: int) -> Journal:
    start = datetime.datetime(2026, 12, 5, tzinfo=datetime.UTC)
    return Journal(
        id=journal_id,
        user_id=USER_ID,
        title="Trip",
        content="content",
        event_date_range=EventDateRange(start=start, end=start),
    )


class _Ports:
    """The service's ports, attached to one parent so call order is recorded."""

    def __init__(
        self, *, stored: TaskList | None, journals: list[Journal] | None = None
    ) -> None:
        self.calls = MagicMock()
        self.task_list_repo = AsyncMock()
        self.task_repo = AsyncMock()
        self.journal_repo = AsyncMock()
        self.event_publisher = AsyncMock()
        self.task_list_repo.find_by_id_for_update.return_value = stored
        self.task_list_repo.save.side_effect = lambda task_list: task_list
        self.journal_repo.find_and_lock_by_ids_for_user.return_value = journals or []
        self.calls.attach_mock(self.task_list_repo, "task_list_repo")
        self.calls.attach_mock(self.journal_repo, "journal_repo")
        self.calls.attach_mock(self.event_publisher, "event_publisher")

    def service(self) -> TaskListService:
        return TaskListService(
            task_list_repo=self.task_list_repo,
            task_repo=self.task_repo,
            journal_repo=self.journal_repo,
            event_publisher=self.event_publisher,
        )

    def call_names(self) -> list[str]:
        return [call[0] for call in self.calls.mock_calls if call[0]]

    def published(self) -> list[DomainEvent]:
        return [call.args[0] for call in self.event_publisher.publish.await_args_list]


async def _update(
    ports: _Ports, patch: TaskListPatch, *, source: Provenance = Provenance.UI
) -> TaskList:
    return await ports.service().update_task_list(
        user_id=USER_ID,
        task_list_id=LIST_ID,
        patch=patch,
        transaction=AsyncMock(),
        source=source,
        changed_by=source.value,
    )


class TestTheJournalIsTakenBeforeTheList:
    async def test_associating_locks_the_journal_then_the_list_then_writes(
        self,
    ) -> None:
        ports = _Ports(stored=_list(), journals=[_journal(JOURNAL_ID)])

        await _update(ports, TaskListPatch(associated_journal_id=JOURNAL_ID))

        assert ports.call_names() == [
            "journal_repo.find_and_lock_by_ids_for_user",
            "task_list_repo.find_by_id_for_update",
            "task_list_repo.save",
            "event_publisher.publish",
        ]
        ports.journal_repo.find_and_lock_by_ids_for_user.assert_awaited_once_with(
            USER_ID, [JOURNAL_ID]
        )

    @pytest.mark.parametrize(
        "patch",
        [TaskListPatch(associated_journal_id=None), TaskListPatch(name="Renamed")],
        ids=["clearing", "leaving-it-alone"],
    )
    async def test_a_patch_joining_no_journal_takes_no_journal(
        self, patch: TaskListPatch
    ) -> None:
        """The journal being left needs no lock: a delete or merge of it waits
        on the list row instead, then skips a list no longer associated."""
        ports = _Ports(stored=_list(journal_id=JOURNAL_ID))

        await _update(ports, patch)

        ports.journal_repo.find_and_lock_by_ids_for_user.assert_not_awaited()


class TestRefusals:
    async def test_a_missing_list_is_refused_before_an_unreachable_journal(
        self,
    ) -> None:
        """A list that is not yours says nothing about journals."""
        ports = _Ports(stored=None, journals=[])

        with pytest.raises(TaskListNotFoundError):
            await _update(ports, TaskListPatch(associated_journal_id=JOURNAL_ID))

        ports.task_list_repo.save.assert_not_awaited()
        ports.event_publisher.publish.assert_not_awaited()

    async def test_an_archived_list_is_refused_before_an_unreachable_journal(
        self,
    ) -> None:
        ports = _Ports(stored=_list(archived=True), journals=[])

        with pytest.raises(TaskListArchivedError):
            await _update(ports, TaskListPatch(associated_journal_id=JOURNAL_ID))

    @pytest.mark.parametrize("journal_id", [JOURNAL_ID, None], ids=["set", "clear"])
    async def test_an_archived_list_keeps_its_association(
        self, journal_id: int | None
    ) -> None:
        ports = _Ports(
            stored=_list(journal_id=OTHER_JOURNAL_ID, archived=True),
            journals=[_journal(JOURNAL_ID)],
        )

        with pytest.raises(TaskListArchivedError):
            await _update(ports, TaskListPatch(associated_journal_id=journal_id))

        ports.task_list_repo.save.assert_not_awaited()
        ports.event_publisher.publish.assert_not_awaited()

    async def test_an_unreachable_journal_is_refused_and_nothing_is_written(
        self,
    ) -> None:
        ports = _Ports(stored=_list(), journals=[])

        with pytest.raises(TaskListJournalNotFoundError) as refused:
            await _update(ports, TaskListPatch(associated_journal_id=JOURNAL_ID))

        assert refused.value.journal_id == JOURNAL_ID
        ports.task_list_repo.save.assert_not_awaited()
        ports.event_publisher.publish.assert_not_awaited()


class TestWhatIsAnnounced:
    async def test_the_journal_the_list_already_has_is_a_no_op(self) -> None:
        ports = _Ports(
            stored=_list(journal_id=JOURNAL_ID), journals=[_journal(JOURNAL_ID)]
        )

        answered = await _update(ports, TaskListPatch(associated_journal_id=JOURNAL_ID))

        assert answered.associated_journal_id == JOURNAL_ID
        ports.task_list_repo.save.assert_not_awaited()
        ports.event_publisher.publish.assert_not_awaited()

    @pytest.mark.parametrize(
        ("before", "after"),
        [(None, JOURNAL_ID), (OTHER_JOURNAL_ID, JOURNAL_ID), (JOURNAL_ID, None)],
        ids=["associate", "change", "remove"],
    )
    async def test_each_change_announces_the_journal_pair(
        self, before: int | None, after: int | None
    ) -> None:
        ports = _Ports(
            stored=_list(journal_id=before),
            journals=[_journal(after)] if after is not None else [],
        )

        saved = await _update(
            ports, TaskListPatch(associated_journal_id=after), source=Provenance.MCP
        )

        assert saved.associated_journal_id == after
        [event] = ports.published()
        assert isinstance(event, TaskListUpdated)
        assert event.event_data["changed_fields"] == {
            "associated_journal_id": (before, after)
        }
        assert event.event_data["source"] == "mcp"
        assert event.event_data["changed_by"] == "mcp"

    async def test_a_rename_and_an_association_are_one_change(self) -> None:
        ports = _Ports(stored=_list(), journals=[_journal(JOURNAL_ID)])

        await _update(
            ports, TaskListPatch(name="Trip packing", associated_journal_id=JOURNAL_ID)
        )

        [event] = ports.published()
        assert isinstance(event, TaskListUpdated)
        assert event.event_data["changed_fields"] == {
            "name": ("Packing", "Trip packing"),
            "associated_journal_id": (None, JOURNAL_ID),
        }
