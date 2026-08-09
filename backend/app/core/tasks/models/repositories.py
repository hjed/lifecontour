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

from core_shared.models.journals import BlockingTask
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
    async def add_contacts(
        self, task_id: int, contact_ids: list[int], user_id: str
    ) -> list[int]:
        """Link one or more contacts to the task, in one statement.

        Contact links are a plain reference — no relationship type, role or
        attendance status. Idempotent, on the same terms as
        :meth:`add_intermediate_journal`: linking a contact that is already
        linked is accepted and creates nothing.

        **Batched rather than singular**, because the ownership guard is the
        expensive half. A per-contact method re-proved ownership with its own
        ``SELECT … FOR KEY SHARE`` for every id, so linking *N* contacts to one
        task cost *2N* statements. One call, one guard, one insert.

        The ownership guard runs on every call, an empty ``contact_ids``
        included — asking to link nothing to somebody else's task is still a
        claim of ownership, and a method that answered it differently would be
        a hole in the contract. A caller with nothing to link is of course free
        not to call at all, and ``TaskService`` does exactly that.

        Args:
            task_id: The task to link
            contact_ids: The contacts to reference; an empty list writes nothing
            user_id: The acting user

        Returns:
            The ids for which a link row was created, so the caller can tell a
            fresh link from one that was already there. Ids that were already
            linked are absent.

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

    @abstractmethod
    async def find_tasks_for_journal(self, journal_id: int, user_id: str) -> list[Task]:
        """Find every one of the user's tasks linked to a journal, in any role.

        A task is linked to a journal when the journal is its creating anchor,
        its due anchor, or one of its intermediate journals. **Which** role a
        task holds is not returned and is not this query's business: both anchors
        are columns on the task and the mentions are read in the batch beside
        this one, so the roles are derived from data the caller already has
        rather than being a second answer that could disagree with the first.

        A task holding two of the journal's roles — the same journal as both
        anchors, or a retarget onto a journal it already mentioned — is returned
        **once**. The three link shapes are unioned rather than joined for that
        reason: a join would return such a task twice and it would be assembled
        twice.

        Args:
            journal_id: The journal being viewed. No ownership check is made on
                it here — this is scoped to the caller's *tasks*, and a journal
                that is not theirs simply anchors none of them. The surfaces
                resolve the journal itself, owner-scoped, and 404 on it.
            user_id: The acting user

        Returns:
            The linked tasks, ordered by id. The read surfaces re-order by due
            date before showing them, so this order exists only to be
            deterministic.
        """

    @abstractmethod
    async def list_intermediate_journal_ids_for_tasks(
        self, task_ids: list[int], user_id: str
    ) -> dict[int, list[int]]:
        """List several tasks' intermediate journals in one statement.

        The batched form of :meth:`list_intermediate_journal_ids`, and the
        reason a journal's task list is not an N+1: a read surface assembling
        *N* tasks calls this once instead of once per task.

        It **returns rather than raises** for a task that is absent or not the
        caller's, unlike its singular form. The singular one answers a caller
        that named one task and must be told it was wrong; this one is given a
        set that an owner-scoped query produced, so a missing key means "no
        links", and raising would make one deleted task fail a whole page.

        Args:
            task_ids: The tasks to read. An empty list reads nothing at all.
            user_id: The acting user; another user's links are never returned

        Returns:
            A mapping of task id to its linked journal ids, oldest link first
            with ties broken by journal id. **Tasks with no links are absent**
            from the mapping rather than present with an empty list, so callers
            read through ``.get(task_id, [])``.
        """

    @abstractmethod
    async def list_contact_ids_for_tasks(
        self, task_ids: list[int], user_id: str
    ) -> dict[int, list[int]]:
        """List several tasks' contact links in one statement.

        The batched form of :meth:`list_contact_ids`, with the same contract as
        :meth:`list_intermediate_journal_ids_for_tasks`: absent rather than
        empty for a task with no links, and no raising for a task that is not
        the caller's.

        Args:
            task_ids: The tasks to read. An empty list reads nothing at all.
            user_id: The acting user; another user's links are never returned

        Returns:
            A mapping of task id to its linked contact ids, oldest link first
            with ties broken by contact id.
        """


class TaskAnchorRepository(ABC):
    """The tasks a journal anchors, for the journal domain's two anchor rules.

    Deleting a journal that anchors a task is refused, and merging one moves the
    links instead. Both are the journal domain asking about task rows it does not
    own, so both live here.

    Kept apart from :class:`TaskRepository` because it answers a different
    domain's question. Its consumer is the journal domain, which must not be
    handed the ability to *write tasks* — to change a task's text, status or
    contacts, or to delete one — in order to find out whether it may delete a
    journal, or to keep its own foreign keys intact through a merge. Re-pointing
    writes task rows, but only their journal columns, and only to the extent the
    foreign keys demand.

    **Nothing here is owner-scoped, and deliberately so.** Every method stands in
    for a foreign-key check, so each has to see every row the
    ``ON DELETE RESTRICT`` anchors see: a row filtered away would come back as
    the raw ``IntegrityError`` the guard exists to replace, or as a link left
    pointing at a journal that no longer exists. Nothing is exposed that the
    delete path did not already reach — ``JournalService.delete_journal`` and the
    journal lookup before it are themselves unscoped — and a task can only anchor
    to a journal the acting user owns, because task creation resolves both
    anchors owner-scoped.
    """

    @abstractmethod
    async def find_tasks_anchored_to_journal(
        self, journal_id: int
    ) -> list[BlockingTask]:
        """Find every task this journal is the creating or due journal of.

        One query for all of them, each already carrying the journal it can be
        actioned from, so an explanatory failure costs the same whether one task
        blocks or twenty.

        Tasks that merely *mention* the journal are not returned: an
        intermediate link never blocks a deletion, and its row cascades away
        with the journal.

        Args:
            journal_id: The journal about to be deleted

        Returns:
            The blocking tasks, ordered by task id, or an empty list when the
            journal anchors nothing.
        """

    @abstractmethod
    async def repoint_journal_links(
        self, *, source_journal_id: int, target_journal_id: int
    ) -> None:
        """Move every task link off one journal and onto another.

        Called by a journal merge before it deletes the absorbed journal. Unlike
        a delete, a merge is never refused — it is what makes calendar sync
        usable — so all three kinds of link move: the creating anchor, the due
        anchor and intermediate links. The resulting shape obeys the
        specification's rules:

        - a task is never linked twice to the same journal in the same role;
        - a survivor that becomes both the creating **and** the due journal of a
          task is permitted, and the task is otherwise unaffected;
        - an intermediate link that has become redundant with one of the task's
          own anchors is dropped, because the anchor role already says more —
          but only for a task this merge actually touched, since a task can
          reach that shape without any merge (retargeting keeps the previous due
          journal as an intermediate link);
        - no task's ``status`` or ``text`` changes. ``updated_at`` does move on
          a task whose anchors were re-pointed: its links really did change.

        An implementation must hold **both** journals for the rest of the
        transaction, in a consistent order across callers. The absorbed journal
        so that a task cannot be anchored to it after the re-point and before
        the caller's delete, which would fail the delete on the anchor foreign
        key; the survivor so that two merges into the same journal cannot both
        move a link onto it and collide. Either way the result would be a merge
        blocked by task rows.

        **Call this before writing either journal row.** The lock order only
        buys anything if it is the transaction's first claim on the pair — a
        caller that updates the survivor first has already taken that lock out
        of order, and two callers running in opposite directions will deadlock
        on each other however carefully this method sorts.

        Idempotent: running it again with the same pair changes nothing, and
        passing the same journal as both source and target is a no-op rather
        than a self-collapse.

        Args:
            source_journal_id: The journal being absorbed, which is about to be
                deleted
            target_journal_id: The surviving journal the links move onto
        """
