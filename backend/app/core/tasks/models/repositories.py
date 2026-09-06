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
from datetime import datetime

from core_shared.models.journals import BlockingTask
from core_shared.models.tasks import (
    Task,
    TaskContactRepointing,
    TaskJournalRepointing,
)


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
    async def find_upcoming_tasks(
        self,
        user_id: str,
        *,
        window_start: datetime,
        window_end: datetime,
    ) -> list[Task]:
        """The user's not-done tasks whose due journal starts inside a window.

        The query behind the dashboard's tasks section. It is the **only**
        listing that reaches across journals, and it is bounded by the window
        rather than paginated: the product has no "every task" screen, and this
        must not become one by accident.

        **The window arrives as instants, not dates.** A journal's date is the
        local date of ``event_date_range_start`` in the acting user's timezone,
        and that conversion belongs to the caller who resolved the timezone —
        pushing it into SQL would put a second definition of "a journal's date"
        in the database, and one that could not be unit-tested. So the caller
        sends local midnight on the first day and the last microsecond of the
        last, and this compares timestamps to timestamps.

        **Cancellation is not filtered here.** A not-done task whose due journal
        was cancelled is *lapsed* and must not reach the dashboard, but that
        verdict is the read model's and depends on a batched lookup the caller
        already makes. Filtering it here would be a second definition of lapsed
        sitting in SQL, so the status and the window are all this statement
        knows about.

        Args:
            user_id: The acting user; the statement filters on it, so another
                user's task is unreachable even with its id
            window_start: The first instant in the window
            window_end: The last instant in the window, inclusive

        Returns:
            The matching tasks, ordered by due-journal start then task id. The
            caller re-orders by the resolved date before showing them, so this
            order exists to make the query deterministic rather than to be the
            display order.
        """

    @abstractmethod
    async def find_tasks_due_in_journals(
        self, journal_ids: list[int], user_id: str
    ) -> list[Task]:
        """The user's tasks due in any of these journals, in **every** status.

        The daily summary's past-day read: *what was due on this day, and what
        became of it*. Its subject is a journal rather than a task, like
        :meth:`count_not_done_tasks_by_due_journal` and unlike everything else
        here — but the two ask different questions, which is why this is a
        sibling rather than a widening of either it or :meth:`find_upcoming_tasks`.

        **Nothing is filtered by status, and that absence is the method.** The
        other two listings drop everything but ``NOT_DONE``, because a finished
        commitment is neither live nor upcoming. Here a finished commitment is
        the answer: a summary reporting how a day resolved has to be able to say
        *done* and *cancelled*.

        **The status returned is the current one**, read from the row as it
        stands. There is no reconstruction of what was true on the day and no
        replay of ``field_history`` — so a past day regenerated after a lapsed
        task was finally completed reports it as done. That is the honest answer
        to "what became of this", and it is what the user sees on the journal.

        **Only the due anchor qualifies.** A journal a task was created in or
        merely mentions did not have it *due* in it, and the creating journal is
        nearly always in the past — a query reading it would attribute half a
        user's commitments to whatever day they were first written down. A task
        holding two roles in one journal is therefore returned once without
        needing to be de-duplicated.

        **Journal ids rather than a date window**, unlike
        :meth:`find_upcoming_tasks`. The caller — the summary's input assembler —
        has already selected the day's journals, by *overlap* rather than by
        start date, so a multi-day journal running through the day is one of
        them. Taking a window here would be a second and quietly different
        definition of "that day's journals" than the one the prompt is
        describing.

        **Lapsing is not filtered here**, matching both siblings' reasoning: it
        depends on the user's timezone and on a batched cancellation lookup the
        caller already makes, so the verdict belongs to ``TaskReadService``. On
        this read it is not an exclusion at all but part of the answer — *how*
        an unfinished commitment lapsed is what the summary reports.

        Args:
            journal_ids: The day's journals. An empty list reads nothing at all.
            user_id: The acting user. Load-bearing, as on
                :meth:`count_not_done_tasks_by_due_journal`: nothing in the
                schema stops a task being anchored to a journal somebody else
                owns, so without the predicate one user's commitments could
                reach another's summary.

        Returns:
            The matching tasks, ordered by due-journal start then task id — the
            day's own order, so a caller renders down the day rather than down
            the ``tasks`` table. The tie-break makes the order total: a journal
            commonly holds several tasks sharing one start.
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

    @abstractmethod
    async def count_not_done_tasks_by_due_journal(
        self, journal_ids: list[int], user_id: str
    ) -> dict[int, int]:
        """How many not-done tasks are due in each of these journals.

        The journal list's "tasks due" indicator, and the only read here whose
        subject is a *journal* rather than a task. One statement for a whole
        page, because the alternative is a query per row on the busiest listing
        in the product — the same reason the batched link reads above exist.

        **Only the due anchor counts.** A journal a task was created in or
        merely mentions is not waiting on it, so neither
        ``creating_journal_id`` nor ``task_intermediate_journals`` is consulted.
        A task holding two roles in one journal is therefore counted once
        without needing to be de-duplicated.

        **Lapsing is not filtered here**, matching
        :meth:`find_upcoming_tasks`'s reasoning. Whether a journal's date has
        passed depends on the acting user's timezone, and whether it is a
        cancelled event depends on a batched lookup the caller already makes —
        so the verdict belongs to
        ``TaskReadService.due_task_counts``, and putting it in SQL would be a
        second definition of *lapsed* that no unit test could reach. The status
        and the anchor are all this statement knows about.

        Args:
            journal_ids: The journals to count for — a listing's page. An empty
                list reads nothing at all.
            user_id: The acting user. Load-bearing here, unlike on the joins
                elsewhere in this repository: nothing in the schema stops a task
                being anchored to a journal somebody else owns, so without the
                predicate one user's commitments could count towards another's
                indicator.

        Returns:
            A mapping of journal id to its count. **Journals with none are
            absent** rather than present with a zero, as the batched link reads
            are, so callers read through ``.get(journal_id, 0)``.
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
    ) -> list[TaskJournalRepointing]:
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

        **It reports what it moved, per task**, because the tasks domain
        publishes an event for each one and no caller can reconstruct the answer
        afterwards: two of the four statements are deletes, and the anchor roles
        are overwritten by the re-point itself. The summaries carry the *net*
        effect rather than a statement-by-statement account — see
        :class:`~core_shared.models.tasks.TaskJournalRepointing` — and an
        implementation must report a task **only** if it actually moved
        something for it, since the caller turns each summary into a line in a
        user's history.

        That last rule is about **concurrency**, not only about arithmetic. The
        locks above hold the two journals, not the tasks: a task can be deleted,
        or its link to the absorbed journal detached, between an implementation
        deciding which tasks it is about and the statements that move them. Such
        a task moved nothing and must not be reported — reporting it either
        writes a change into the history of a task that no longer exists, or
        (worse) fails the merge on a task, which this operation may never do.

        Args:
            source_journal_id: The journal being absorbed, which is about to be
                deleted
            target_journal_id: The surviving journal the links move onto

        Returns:
            One summary per task this call moved, ordered by task id so a merge's
            events go out in the same order every time. Empty when the absorbed
            journal has no task on it, which is most merges.
        """


class TaskContactRepository(ABC):
    """The tasks a contact is referenced by, for the contacts domain's merge.

    Merging two contacts moves every link a task holds on the absorbed person
    onto the survivor. That is the contacts domain asking about task rows it does
    not own, so it lives here — the same seam, and for the same reason, as
    :class:`TaskAnchorRepository` is for the journal domain.

    **Kept apart from :class:`TaskRepository` because it answers a different
    domain's question.** Its consumer is the contacts domain, which must not be
    handed the ability to *write tasks* — to change a task's text, status or
    anchors, or to delete one — in order to keep a merge from destroying its own
    links. Re-pointing writes task link rows, and only their ``contact_id``.

    **Nothing here is owner-scoped, and it could not be.** ``contacts`` has no
    ``user_id`` column, so a contact merge has no acting user's tasks to scope
    to; the operation stands in for a foreign-key cascade, and a row filtered
    away would come back as the silent data loss this port exists to prevent.
    Nothing is exposed that ``DELETE FROM contacts`` did not already reach.
    """

    @abstractmethod
    async def repoint_contact_links(
        self, *, source_contact_id: int, survivor_contact_id: int
    ) -> list[TaskContactRepointing]:
        """Move every task link off one contact and onto another.

        Called by a contact merge **before** it deletes the absorbed contact.
        ``task_contacts.contact_id`` is ``ON DELETE CASCADE``, which is right for
        deleting a contact and silently wrong for merging one: after the delete
        there is nothing left to move, and nothing failed to say so.

        The resulting shape obeys the specification's rule that a merge produces
        one unified record:

        - a task that referenced the absorbed contact references the survivor;
        - a task that referenced **both** references the survivor **once** — the
          ``PRIMARY KEY (task_id, contact_id)`` makes the duplicate a hard error,
          so the collapse is a correctness requirement rather than a tidy-up;
        - a task that referenced neither is untouched;
        - no task's ``status``, ``text`` or anchors change. A merge is a change
          of who a task references, and nothing else.

        An implementation must hold **both** contacts that exist for the rest of
        the transaction, in a consistent order across callers. Inserting a task
        link takes ``FOR KEY SHARE`` on the contact row to hold its own foreign
        key, so without the lock a concurrent ``link_contact`` could attach to
        the absorbed contact after the re-point and before the caller's delete —
        and the cascade would then destroy that link, which is the whole defect
        again by another route.

        **Call this before the merge's other re-points, not merely before the
        delete.** The lock order only buys anything if it is the transaction's
        first claim on the pair, and every re-point that writes the survivor's
        id into a table referencing ``contacts`` has already taken
        ``FOR KEY SHARE`` on the survivor's row — after which two merges into
        one survivor deadlock instead of queueing. This is the merge's *first*
        write for the same reason ``repoint_journal_links`` is.

        Idempotent: running it again with the same pair changes nothing, and
        passing the same contact as both source and survivor is a no-op rather
        than a self-collapse.

        **It reports what it moved, per task**, because the tasks domain
        publishes an event for each one and no caller can reconstruct the answer
        afterwards: one of the two statements is a delete, and the rows the other
        writes are indistinguishable from links the task already held. An
        implementation must report a task **only** if it actually moved something
        for it, since the caller turns each summary into a line in a user's
        history — and a merge may never fail on a task, so a task that has been
        deleted concurrently is one that moved nothing rather than an error.

        Args:
            source_contact_id: The contact being absorbed, which is about to be
                deleted
            survivor_contact_id: The surviving contact the links move onto

        Returns:
            One summary per task this call moved, ordered by task id so a merge's
            events go out in the same order every time. Empty when the absorbed
            contact is on no task, which is most merges.
        """
