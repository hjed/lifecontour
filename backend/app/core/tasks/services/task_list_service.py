"""Writing task lists: the service every list write passes through.

Each write is a ``@transactional`` unit of work that changes the list and
publishes its domain event on the same connection, so the two commit or roll
back together. Reads live in :class:`TaskListReadService`, which takes no event
publisher and opens no unit of work — the same split ``TaskService`` and
``TaskReadService`` make.

Creation, the field update (rename, set or clear the icon, associate the list
with a journal, change or remove that association), reordering,
archiving and unarchiving, and deletion live here. Every write locks what it reads inside its
unit of work before writing: the field update and the archive pair their one
list with ``find_by_id_for_update``, a move all the owner's lists. Reordering is
the one write that publishes no event: the specification keeps it out of
history.

**An archived list is read-only until it is unarchived.** Every write but
unarchive consults ``TaskList.ensure_writable`` right after its locked read, and
archiving an archived list (or unarchiving an active one) is a no-op rather than
a refusal, so a retried request succeeds.
"""

from dataclasses import replace
from datetime import UTC, datetime

from core_shared.models.history import Provenance
from core_shared.models.tasks import (
    TaskIcon,
    TaskList,
    TaskListArchiveFilter,
    TaskListDeletion,
    TaskListJournalNotFoundError,
    TaskListListing,
    TaskListNotFoundError,
    reorder_task_lists,
)
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import JournalRepository
from app.core.tasks.models.events import TaskDeleted, TaskListMembershipChanged
from app.core.tasks.models.repositories import TaskListRepository, TaskRepository
from app.core.tasks.models.task_list_events import (
    TaskListCreated,
    TaskListDeleted,
    TaskListFieldChange,
    TaskListUpdated,
)
from app.core.tasks.services.task_list_patch import TaskListPatch
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.unit_of_work import transactional


class TaskListService:
    """Creates, changes, reorders, archives, unarchives and deletes task lists
    for their owner.

    Every write but a move announces itself. The task repository is here for
    the delete alone, which deletes or keeps the list's tasks in its own unit
    of work; the journal repository for the association alone, which checks
    and locks the journal a list joins.
    """

    def __init__(
        self,
        task_list_repo: TaskListRepository,
        task_repo: TaskRepository,
        journal_repo: JournalRepository,
        event_publisher: OutboxEventPublisher,
    ) -> None:
        self.task_list_repo = task_list_repo
        self.task_repo = task_repo
        self.journal_repo = journal_repo
        self.event_publisher = event_publisher

    @transactional
    async def create_task_list(
        self,
        *,
        user_id: str,
        name: str,
        icon: TaskIcon | None,
        transaction: AsyncConnection,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> TaskList:
        """Create a list at the bottom of the owner's lists.

        The entity refuses a blank or over-long name before anything is
        written, so a refused create leaves neither a row nor an event. The
        event is built from the list *as persisted*, after the repository has
        assigned its id and position.

        Raises:
            TaskListValidationError: The name is blank or too long.
        """
        created = await self.task_list_repo.save(
            TaskList(user_id=user_id, name=name, icon=icon)
        )
        assert created.id is not None, "Task list ID must be set after save"

        await self.event_publisher.publish(
            TaskListCreated(
                task_list_id=created.id,
                user_id=created.user_id,
                name=created.name,
                icon=created.icon,
                source=source,
                changed_by=changed_by,
                transaction=transaction,
            )
        )
        return created

    @transactional
    async def update_task_list(
        self,
        *,
        user_id: str,
        task_list_id: int,
        patch: TaskListPatch,
        transaction: AsyncConnection,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> TaskList:
        """Rename a list, set or clear its icon, associate it with a journal or
        change or remove that association — any of them, as one change.

        **The read takes a row lock** and the patch is applied to the list as
        read under it, so two overlapping updates serialise and neither can
        put back a field only the other one changed.

        **Only what actually moved is written and announced.** A patch naming
        values the list already has — or naming nothing — is a no-op: nothing
        is saved and no event is published. Otherwise one ``TaskListUpdated``
        carries ``changed_fields`` for exactly the fields that differ, after
        the save, so it announces a change that finished.

        The patch is applied with one ``replace``, which re-runs the entity's
        validation, so a refused name is refused before anything is written.

        **An archived list refuses every patch**, a no-op one included: the
        refusal comes before the comparison, because read-only means "not
        writable", not "unchanged".

        **A journal the list joins is locked before the list.** It is held
        ``FOR KEY SHARE`` — the weakest lock a journal delete or merge still
        waits behind — and those take the journal ``FOR UPDATE`` before they
        touch any list, so the two queue at the journal instead of
        deadlocking. The journal being left is not locked: a delete or merge of
        it waits on this list's row, then skips a list no longer associated with
        it. The refusals keep their own order whatever the lock order: a list
        that is not the user's, then an archived one, then the journal.

        Raises:
            TaskListValidationError: The new name is blank or too long.
            TaskListNotFoundError: The list does not exist or is not the acting
                user's; the two are indistinguishable by design.
            TaskListArchivedError: The list is archived, and so read-only.
            TaskListJournalNotFoundError: The journal to associate does not
                exist or is not the acting user's.
        """
        joining_found = await self._lock_associated_journal(user_id, patch)
        stored = await self._locked(user_id, task_list_id)
        stored.ensure_writable()
        if not joining_found:
            assert isinstance(patch.associated_journal_id, int)
            raise TaskListJournalNotFoundError(patch.associated_journal_id)

        changed_fields = _changed_fields(stored, patch)
        if not changed_fields:
            return stored

        saved = await self.task_list_repo.save(patch.applied_to(stored))

        await self.event_publisher.publish(
            TaskListUpdated(
                task_list_id=task_list_id,
                user_id=user_id,
                changed_fields=changed_fields,
                source=source,
                changed_by=changed_by,
                transaction=transaction,
            )
        )
        return saved

    @transactional
    async def move_task_list(
        self,
        *,
        user_id: str,
        task_list_id: int,
        index: int,
        transaction: AsyncConnection,
    ) -> list[TaskList]:
        """Move one of the owner's lists to a new place among their active lists.

        Every one of the owner's lists is locked first, so a concurrent move
        waits and then builds on this one's order rather than writing back the
        order it read before. ``index`` counts active lists only, the view a
        person reorders; archived lists keep their place relative to their
        neighbours, and an index past the end moves the list to the bottom (see
        :func:`reorder_task_lists`). Every list is then renumbered densely.

        Publishes no event: reordering is not part of a list's history.

        Returns:
            The owner's active lists in their new order.

        Raises:
            TaskListNotFoundError: No such list, or it belongs to someone else.
            TaskListArchivedError: The list is archived, and so read-only.
        """
        locked = await self.task_list_repo.list_for_user_for_update(user_id)
        moved = next((each for each in locked if each.id == task_list_id), None)
        if moved is None:
            raise TaskListNotFoundError(task_list_id)
        moved.ensure_writable()

        await self.task_list_repo.reposition(
            user_id, reorder_task_lists(locked, task_list_id, index)
        )
        active = await self.task_list_repo.list_for_user(
            user_id, TaskListListing(archived=TaskListArchiveFilter.ACTIVE)
        )
        return list(active.task_lists)

    @transactional
    async def archive_task_list(
        self,
        *,
        user_id: str,
        task_list_id: int,
        transaction: AsyncConnection,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> TaskList:
        """Archive one of the owner's lists, making it read-only.

        The list's tasks are left exactly as they are — open ones included —
        and so is its position, so unarchiving later returns it to its place.
        A list already archived keeps the instant it was first archived:
        nothing is written and nothing is announced.

        Raises:
            TaskListNotFoundError: No such list, or it belongs to someone else.
        """
        return await self._set_archived_at(
            user_id=user_id,
            task_list_id=task_list_id,
            archive=True,
            transaction=transaction,
            source=source,
            changed_by=changed_by,
        )

    @transactional
    async def unarchive_task_list(
        self,
        *,
        user_id: str,
        task_list_id: int,
        transaction: AsyncConnection,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> TaskList:
        """Unarchive one of the owner's lists, restoring it.

        The list rejoins the active lists in the place it kept while archived
        and accepts writes again. Unarchiving an active list writes and
        announces nothing.

        Raises:
            TaskListNotFoundError: No such list, or it belongs to someone else.
        """
        return await self._set_archived_at(
            user_id=user_id,
            task_list_id=task_list_id,
            archive=False,
            transaction=transaction,
            source=source,
            changed_by=changed_by,
        )

    @transactional
    async def delete_task_list(
        self,
        *,
        user_id: str,
        task_list_id: int,
        transaction: AsyncConnection,
        source: Provenance = Provenance.SYSTEM,
        changed_by: str = "system",
    ) -> TaskListDeletion:
        """Hard-delete one of the owner's lists, and its tasks with it.

        **What survives.** A task holding both a creating and a due journal
        stays, as a journal-only task: off the list, with no position and no due
        date, everything else as it was. Its lapse is derived on read, so it
        reads as lapsed if its due journal has ended. Every other task on the
        list — open or closed — is deleted, its contact and intermediate links
        with it.

        **An archived list is refused**, as every other write to it is: it is
        read-only until unarchived, and deleting it is a write.

        **Locks, in order.** Deletes of this list are serialised first, so a
        second delete waits holding nothing and then finds the list gone. The
        list is then read under a *share* lock, which keeps
        out every writer that would add a task to it (they lock the list
        exclusively) while letting task edits and reorders — which share-lock it
        too — go on. The repository then locks the list's tasks in id order and
        releases them, and the list row is deleted last, which the ``RESTRICT``
        foreign key requires. That last step takes the list exclusively without
        waiting: another holder then may be queued behind a task this delete
        holds, so waiting could deadlock, and the delete refuses any holder
        with a retryable conflict instead.

        **What it announces**, after everything is written, in this order: a
        ``TaskDeleted`` per deleted task, a ``TaskListMembershipChanged`` from
        the list to none per kept task, and one ``TaskListDeleted`` closing the
        list's history.

        Returns:
            Which tasks were deleted and which were kept.

        Raises:
            TaskListNotFoundError: No such list, or it belongs to someone else.
            TaskListArchivedError: The list is archived, and so read-only.
            TaskListBusyError: Another request held the list when the delete
                came to remove it; reading it again and retrying succeeds.
        """
        await self.task_list_repo.serialize_deletes(task_list_id)
        stored = await self.task_list_repo.find_by_id_for_share(task_list_id, user_id)
        if stored is None:
            raise TaskListNotFoundError(task_list_id)
        stored.ensure_writable()

        released = await self.task_repo.release_list_tasks(task_list_id, user_id)
        await self.task_list_repo.delete(task_list_id, user_id)

        for task_id in released.deleted_task_ids:
            await self.event_publisher.publish(
                TaskDeleted(
                    task_id=task_id,
                    user_id=user_id,
                    source=source,
                    changed_by=changed_by,
                    transaction=transaction,
                )
            )
        for task_id in released.kept_task_ids:
            await self.event_publisher.publish(
                TaskListMembershipChanged(
                    task_id=task_id,
                    user_id=user_id,
                    previous_task_list_id=task_list_id,
                    task_list_id=None,
                    source=source,
                    changed_by=changed_by,
                    transaction=transaction,
                )
            )
        await self.event_publisher.publish(
            TaskListDeleted(
                task_list_id=task_list_id,
                user_id=user_id,
                name=stored.name,
                deleted_task_count=len(released.deleted_task_ids),
                kept_task_count=len(released.kept_task_ids),
                source=source,
                changed_by=changed_by,
                transaction=transaction,
            )
        )
        return released

    async def _lock_associated_journal(
        self, user_id: str, patch: TaskListPatch
    ) -> bool:
        """Hold the journal ``patch`` associates the list with, if it names one.

        ``False`` only when it names a journal that is absent or somebody
        else's: the read is owner-scoped, so such a journal is never locked.
        The caller decides when that is refused, after the list's own refusals.
        """
        journal_id = patch.associated_journal_id
        if not isinstance(journal_id, int):
            return True
        locked = await self.journal_repo.find_and_lock_by_ids_for_user(
            user_id, [journal_id]
        )
        return any(journal.id == journal_id for journal in locked)

    async def _locked(self, user_id: str, task_list_id: int) -> TaskList:
        """The owner's list read under its row lock, or not found."""
        stored = await self.task_list_repo.find_by_id_for_update(task_list_id, user_id)
        if stored is None:
            raise TaskListNotFoundError(task_list_id)
        return stored

    async def _set_archived_at(
        self,
        *,
        user_id: str,
        task_list_id: int,
        archive: bool,
        transaction: AsyncConnection,
        source: Provenance,
        changed_by: str,
    ) -> TaskList:
        """Archive or unarchive a list under its row lock.

        The lock is what makes the pair idempotent under concurrency: a second
        archive racing the first waits, then reads the list as archived and
        returns it untouched. The archive instant is taken *after* the lock, so
        it is when the archive took effect rather than when it started waiting.

        A list already in the asked-for state is returned untouched. Otherwise
        one ``TaskListUpdated`` carries ``archived_at`` as ``(old, new)`` ISO
        strings or ``None``, built from the rows as stored so it records the
        instant the database holds.
        """
        stored = await self._locked(user_id, task_list_id)
        if stored.is_archived == archive:
            return stored

        archived_at = datetime.now(tz=UTC) if archive else None
        saved = await self.task_list_repo.save(replace(stored, archived_at=archived_at))

        await self.event_publisher.publish(
            TaskListUpdated(
                task_list_id=task_list_id,
                user_id=user_id,
                changed_fields={
                    "archived_at": (_iso(stored.archived_at), _iso(saved.archived_at))
                },
                source=source,
                changed_by=changed_by,
                transaction=transaction,
            )
        )
        return saved


def _iso(instant: datetime | None) -> str | None:
    """An archive instant as the event payload carries it."""
    return instant.isoformat() if instant is not None else None


def _wire(value: object) -> str | int | None:
    """A field value as the event payload carries it: a plain string, a journal
    id, or null.

    ``TaskIcon`` is checked first: it is a ``StrEnum``, so it is also a ``str``,
    and the payload must hold the bare key rather than the member. ``bool`` is
    refused although it is an ``int``: no list field is one.
    """
    if isinstance(value, TaskIcon):
        return value.value
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise TypeError(f"No wire form for a task list field value: {value!r}")


def _changed_fields(
    stored: TaskList, patch: TaskListPatch
) -> dict[str, TaskListFieldChange]:
    """``{field: (old, new)}`` for each patched field whose value differs."""
    return {
        field: (_wire(old), _wire(new))
        for field, new in patch.changes().items()
        if (old := getattr(stored, field)) != new
    }
