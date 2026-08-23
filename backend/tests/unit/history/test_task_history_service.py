"""Unit tests for TaskHistoryService — the read and, mostly, the authorisation.

The read half is the same three lines ``JournalHistoryService`` has. What is
worth testing here is the half that is *not* the same: **how a task history read
decides whose history it is**.

Every other history read in this system loads the aggregate and compares
``user_id``. A task is hard-deleted, so that read has nothing to load — and the
``__deleted__`` marker its deletion projects would sit on a surface nothing
could authorise. The owner is therefore carried on the history rows, with the
live task row as a fallback for the window before the projection catches up.
Both directions of both checks are pinned below, because getting either wrong
produces one of the two failures this phase exists to prevent: a deleted task's
history unreachable by its owner, or a live task's history reachable by somebody
else.
"""

from datetime import UTC, datetime

import pytest
from core_shared.models.history import Provenance
from core_shared.models.tasks import Task, TaskStatus
from core_shared.models.tasks.exceptions import TaskNotFoundError

from app.core.history.models import FieldHistoryEntry
from app.core.history.services.task_history_service import TaskHistoryService

OWNER = "u1"
INTRUDER = "u2"
TASK_ID = 42


def _entry(field_name: str, *, user_id: str | None = OWNER) -> FieldHistoryEntry:
    return FieldHistoryEntry(
        entity_type="task",
        entity_id=TASK_ID,
        field_name=field_name,
        old_value=None,
        new_value="Book the venue",
        changed_by="ui",
        source=Provenance.UI,
        event_id=f"evt-{field_name}",
        id=1,
        created_at=datetime(2024, 3, 1, 8, 0, tzinfo=UTC),
        user_id=user_id,
    )


def _task(user_id: str = OWNER) -> Task:
    return Task(
        id=TASK_ID,
        user_id=user_id,
        text="Book the venue",
        status=TaskStatus.NOT_DONE,
        creating_journal_id=100,
        due_journal_id=200,
    )


class FakeHistoryRepo:
    """Records what it was asked, so the service's arithmetic is observable."""

    def __init__(
        self, *, owner: str | None, entries: list[FieldHistoryEntry] | None = None
    ) -> None:
        self._owner = owner
        self._entries = entries or []
        self.owner_calls: list[tuple[str, int]] = []
        self.aggregate_calls: list[tuple[str, int, int, int]] = []
        self.count_calls: list[tuple[str, int]] = []

    async def get_history_owner(self, entity_type: str, entity_id: int) -> str | None:
        self.owner_calls.append((entity_type, entity_id))
        return self._owner

    async def get_history_for_aggregate(
        self, root_type: str, root_id: int, limit: int = 50, offset: int = 0
    ) -> list[FieldHistoryEntry]:
        self.aggregate_calls.append((root_type, root_id, limit, offset))
        return self._entries

    async def get_history_for_aggregate_count(
        self, root_type: str, root_id: int
    ) -> int:
        self.count_calls.append((root_type, root_id))
        return len(self._entries)


class FakeTaskRepo:
    """Owner-scoped like the real one: another user's task is simply not found."""

    def __init__(self, task: Task | None) -> None:
        self._task = task
        self.calls: list[tuple[int, str]] = []

    async def find_by_id(self, task_id: int, user_id: str) -> Task | None:
        self.calls.append((task_id, user_id))
        if self._task is None or self._task.user_id != user_id:
            return None
        return self._task


def _service(history_repo: object, task_repo: object) -> TaskHistoryService:
    return TaskHistoryService(
        history_repo=history_repo,  # type: ignore[arg-type]
        task_repo=task_repo,  # type: ignore[arg-type]
    )


class TestTheHistoryRowsAnswerFirst:
    async def test_the_owner_reads_the_history_of_a_task_that_no_longer_exists(
        self,
    ) -> None:
        """The discriminator this phase exists for.

        The task repository finds nothing — the row is gone — and the read still
        succeeds, because the rows say whose they are. Were this to 404, the
        ``__deleted__`` marker Phase 6 writes would be unreadable by anyone,
        forever.
        """
        history = FakeHistoryRepo(owner=OWNER, entries=[_entry("__deleted__")])
        tasks = FakeTaskRepo(None)

        entries = await _service(history, tasks).get_task_history(
            task_id=TASK_ID, user_id=OWNER
        )

        assert [e.field_name for e in entries] == ["__deleted__"]

    async def test_another_user_is_refused_a_deleted_task_too(self) -> None:
        """The leak this closes has no other guard once the row is gone."""
        history = FakeHistoryRepo(owner=OWNER, entries=[_entry("__deleted__")])

        with pytest.raises(TaskNotFoundError):
            await _service(history, FakeTaskRepo(None)).get_task_history(
                task_id=TASK_ID, user_id=INTRUDER
            )

    async def test_a_refusal_reads_nothing(self) -> None:
        """Nothing is fetched for a caller who will be refused.

        Not an optimisation: a service that reads the rows and then decides is
        one refactor away from returning them.
        """
        history = FakeHistoryRepo(owner=OWNER, entries=[_entry("__created__")])

        with pytest.raises(TaskNotFoundError):
            await _service(history, FakeTaskRepo(None)).get_task_history(
                task_id=TASK_ID, user_id=INTRUDER
            )

        assert history.aggregate_calls == []

    async def test_the_task_row_is_not_consulted_when_the_rows_answer(self) -> None:
        """The fallback is a fallback, not a second condition.

        A live task whose history is present must not need the ``tasks`` row —
        otherwise the deleted case works only by accident of ordering.
        """
        history = FakeHistoryRepo(owner=OWNER, entries=[_entry("__created__")])
        tasks = FakeTaskRepo(_task())

        await _service(history, tasks).get_task_history(task_id=TASK_ID, user_id=OWNER)

        assert tasks.calls == []


class TestTheTaskRowIsTheFallback:
    async def test_a_task_whose_events_have_not_projected_yet_reads_empty(self) -> None:
        """Projection is asynchronous, and a 404 here would be a lie.

        A task created a moment ago has no history rows, so the owner lookup
        answers ``None``. Treating that as "not yours" would make a brand-new
        task's history page 404 until the consumer caught up — an empty list is
        the truthful answer, and it becomes populated on its own.
        """
        history = FakeHistoryRepo(owner=None, entries=[])
        tasks = FakeTaskRepo(_task())

        entries = await _service(history, tasks).get_task_history(
            task_id=TASK_ID, user_id=OWNER
        )

        assert entries == []
        assert tasks.calls == [(TASK_ID, OWNER)]

    async def test_an_unknown_task_with_no_history_is_refused(self) -> None:
        history = FakeHistoryRepo(owner=None, entries=[])

        with pytest.raises(TaskNotFoundError):
            await _service(history, FakeTaskRepo(None)).get_task_history(
                task_id=TASK_ID, user_id=OWNER
            )

    async def test_another_users_unprojected_task_is_refused(self) -> None:
        """The fallback inherits the repository's owner scoping rather than
        re-implementing it, so a foreign task is 'not found' here as everywhere."""
        history = FakeHistoryRepo(owner=None, entries=[])

        with pytest.raises(TaskNotFoundError):
            await _service(history, FakeTaskRepo(_task(OWNER))).get_task_history(
                task_id=TASK_ID, user_id=INTRUDER
            )


class TestPagination:
    async def test_limit_and_offset_reach_the_repository_unchanged(self) -> None:
        history = FakeHistoryRepo(owner=OWNER, entries=[])

        await _service(history, FakeTaskRepo(_task())).get_task_history(
            task_id=TASK_ID, user_id=OWNER, limit=5, offset=10
        )

        assert history.aggregate_calls == [("task", TASK_ID, 5, 10)]

    async def test_it_reads_through_the_task_aggregation_strategy(self) -> None:
        """The registered ``"task"`` root, not a hand-rolled predicate."""
        history = FakeHistoryRepo(owner=OWNER, entries=[])

        await _service(history, FakeTaskRepo(_task())).get_task_history(
            task_id=TASK_ID, user_id=OWNER
        )

        assert history.aggregate_calls[0][0] == "task"

    async def test_the_count_is_authorised_the_same_way(self) -> None:
        """A count is a disclosure too — how much history a task has is
        information about somebody else's task."""
        history = FakeHistoryRepo(owner=OWNER, entries=[_entry("__created__")])

        with pytest.raises(TaskNotFoundError):
            await _service(history, FakeTaskRepo(None)).get_task_history_count(
                task_id=TASK_ID, user_id=INTRUDER
            )

    async def test_the_count_does_not_depend_on_the_page(self) -> None:
        """The total is the total; a second page must not renumber it."""
        history = FakeHistoryRepo(
            owner=OWNER, entries=[_entry("__created__"), _entry("text")]
        )
        service = _service(history, FakeTaskRepo(_task()))

        total = await service.get_task_history_count(task_id=TASK_ID, user_id=OWNER)

        assert total == 2
        assert history.count_calls == [("task", TASK_ID)]
