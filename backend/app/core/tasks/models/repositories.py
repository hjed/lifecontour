"""Repository ports for the tasks domain.

The tasks domain owns this interface; the SQL adapter in
``app.core.tasks.adapters.sql`` implements it, and services depend on the port
rather than the adapter.

**Owner scoping is part of the contract, not an implementation detail.** Every
method takes the acting user's id and every implementation must filter on it,
so no caller can reach another user's task even by supplying its id. A task the
acting user does not own is treated exactly like one that does not exist:
``find_by_id`` returns ``None`` and every other method raises
``TaskNotFoundError``.

``TaskNotFoundError`` is the *only* way a missing task is reported. An
implementation that checks ownership separately from the statement it guards
must hold that check against a concurrent delete, so a raw foreign-key
violation can never reach the caller in its place.

The repository is responsible only for persistence and for task ownership. The
specification's remaining invariants — the due journal must exist, belong to the
acting user, and be future-dated *at the moment it is set* — need journal data
and the user's timezone, so they live in the service layer where REST and MCP
both inherit them.
"""

from abc import ABC, abstractmethod

from core_shared.models.tasks import Task


class TaskRepository(ABC):
    """Repository interface for task persistence and its link tables.

    A task is anchored to two journals through columns on the task itself, so
    the anchors are read and written as part of the entity. Intermediate
    journals and contacts are separate rows in link tables and have their own
    methods.
    """

    @abstractmethod
    async def save(self, task: Task) -> Task:
        """Insert a new task or update an existing one.

        Args:
            task: The task to persist. A task without an ``id`` is inserted;
                one with an ``id`` is updated in place, keeping its original
                ``created_at``.

        Returns:
            The persisted task, carrying the database-assigned id and
            timestamps.

        Raises:
            TaskNotFoundError: On the update path, when no task with that id
                belongs to ``task.user_id``.
        """

    @abstractmethod
    async def find_by_id(self, task_id: int, user_id: str) -> Task | None:
        """Find one of the user's tasks by id.

        Args:
            task_id: The task id to look up
            user_id: The acting user; a task owned by anyone else is not found

        Returns:
            The task, or ``None`` when it does not exist or is not the user's.
        """

    @abstractmethod
    async def find_by_id_for_update(self, task_id: int, user_id: str) -> Task | None:
        """Find one of the user's tasks, holding it against concurrent writers.

        Same result as :meth:`find_by_id`, with one addition that is the whole
        point of it: the row is **locked until the calling transaction ends**,
        so a caller that reads a task, decides something from its current state
        and then writes it back cannot have another writer slip in between.

        Any rule of the form *"a task in state X may not become Y"* needs this.
        Without it two overlapping calls both read the old state, both decide
        the transition is allowed, and the later write wins — so a task that was
        cancelled in between can be answered ``200`` and left ``done``, which is
        exactly the transition the rule refuses.

        Use :meth:`find_by_id` for reads that only display or return the task;
        a lock nobody needs is a lock somebody else waits on.

        Args:
            task_id: The task id to look up
            user_id: The acting user; a task owned by anyone else is not found

        Returns:
            The task, or ``None`` when it does not exist or is not the user's.
        """

    @abstractmethod
    async def delete(self, task_id: int, user_id: str) -> None:
        """Hard-delete one of the user's tasks.

        Deleting a task removes its intermediate-journal and contact links with
        it, and leaves the journals and contacts themselves untouched.

        Args:
            task_id: The task id to delete
            user_id: The acting user

        Raises:
            TaskNotFoundError: When no such task belongs to the user.
        """

    @abstractmethod
    async def add_intermediate_journal(
        self, task_id: int, journal_id: int, user_id: str
    ) -> bool:
        """Link a journal to the task as an intermediate journal.

        Idempotent: adding a link that already exists changes nothing and
        reports ``False``, so a retry can never create a duplicate row.

        Args:
            task_id: The task to link
            journal_id: The journal the task was discussed, revisited or
                previously due in
            user_id: The acting user

        Returns:
            ``True`` when the link was created, ``False`` when it already
            existed.

        Raises:
            TaskNotFoundError: When no such task belongs to the user.
        """

    @abstractmethod
    async def remove_intermediate_journal(
        self, task_id: int, journal_id: int, user_id: str
    ) -> bool:
        """Remove an intermediate-journal link.

        The creating and due anchors are columns on the task and cannot be
        removed this way — the due anchor is replaced by retargeting.

        Args:
            task_id: The task to unlink
            journal_id: The intermediate journal to unlink
            user_id: The acting user

        Returns:
            ``True`` when a link was removed, ``False`` when there was none.

        Raises:
            TaskNotFoundError: When no such task belongs to the user.
        """

    @abstractmethod
    async def list_intermediate_journal_ids(
        self, task_id: int, user_id: str
    ) -> list[int]:
        """List the ids of the task's intermediate journals.

        Args:
            task_id: The task to read
            user_id: The acting user

        Returns:
            The linked journal ids, oldest link first.

        Raises:
            TaskNotFoundError: When no such task belongs to the user.
        """

    @abstractmethod
    async def add_contact(self, task_id: int, contact_id: int, user_id: str) -> bool:
        """Link a contact to the task.

        Contact links are a plain reference — no relationship type, role or
        attendance status. Idempotent, on the same terms as
        :meth:`add_intermediate_journal`.

        Args:
            task_id: The task to link
            contact_id: The contact to reference
            user_id: The acting user

        Returns:
            ``True`` when the link was created, ``False`` when it already
            existed.

        Raises:
            TaskNotFoundError: When no such task belongs to the user.
        """

    @abstractmethod
    async def remove_contact(self, task_id: int, contact_id: int, user_id: str) -> bool:
        """Remove a contact link.

        Args:
            task_id: The task to unlink
            contact_id: The contact to unlink
            user_id: The acting user

        Returns:
            ``True`` when a link was removed, ``False`` when there was none.

        Raises:
            TaskNotFoundError: When no such task belongs to the user.
        """

    @abstractmethod
    async def list_contact_ids(self, task_id: int, user_id: str) -> list[int]:
        """List the ids of the contacts the task references.

        Args:
            task_id: The task to read
            user_id: The acting user

        Returns:
            The linked contact ids, oldest link first.

        Raises:
            TaskNotFoundError: When no such task belongs to the user.
        """
