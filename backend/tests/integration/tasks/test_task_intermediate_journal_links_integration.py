"""Integration tests for the intermediate-journal link service, against real PostgreSQL.

Four of this phase's properties are only real against a database:

- **idempotency is the composite primary key's**, not the service's. Attaching
  twice leaves one row because ``ON CONFLICT (task_id, journal_id) DO NOTHING``
  says so, and there is no "is it already linked?" read anywhere to make it look
  otherwise.
- **deleting a journal that is only an intermediate link is permitted**, and the
  link goes with it. That is the ``ON DELETE CASCADE`` migration 0105 put on
  ``task_intermediate_journals.journal_id``. Asserted here through a link **this
  surface created**, rather than a hand-inserted row: a service writing somewhere
  else would pass ``test_task_tables_constraints.py``'s schema test and fail this
  one. The other half of that pair — the ``ON DELETE RESTRICT`` that makes
  deleting an *anchor* journal impossible — is a property of the schema with no
  bearing on this surface, and lives in
  ``test_task_tables_constraints.py::TestAnchorJournalDeletionIsRefused``.
- **the anchors really are columns**, so a detach aimed at one has no row to
  remove and would answer a misleading ``False``. The refusal is asserted
  against a task whose anchors are live foreign keys rather than a stub.
- **a journal that vanishes between the check and the insert** still answers
  404 rather than surfacing a raw ``IntegrityError`` as a 500.

Owner scoping is asserted against a **real second user's rows** rather than an
absent id, because a query that dropped its ``user_id`` filter would still
return nothing for an id that never existed.
"""

import pytest
from core_shared.models.journals import Journal, JournalNotFoundError
from core_shared.models.tasks import TaskJournalIsAnchorError, TaskNotFoundError
from core_shared.models.tasks import TaskStatus as Status
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_repository import SqlContactRepository
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_date_resolver import JournalDateResolver
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.tasks.adapters.sql.task_repository import SqlTaskRepository
from app.core.tasks.services.task_service import TaskService
from tests.integration.tasks.task_seeding import (
    COUNT_INTERMEDIATE_JOURNALS,
    OTHER_USER_ID,
    USER_ID,
    count,
    create_contact,
    create_journal,
    create_task,
    delete_journal,
    intermediate_journal_ids,
    link_intermediate_journal,
    stored_anchors,
    stored_status,
)

pytestmark = pytest.mark.integration

ALL_STATUSES = list(Status)


async def _link_count(conn: AsyncConnection) -> int:
    return await count(conn, COUNT_INTERMEDIATE_JOURNALS, {})


class TestAttachingAnIntermediateJournal:
    """The round trip, and the row the composite key allows exactly one of."""

    async def test_the_link_row_is_written(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        mentioned = await create_journal(journal_repository, title="Came up again")

        changed = await service.attach_intermediate_journal(
            user_id=USER_ID,
            task_id=task_id,
            journal_id=mentioned,
            transaction=async_connection,
        )

        assert changed is True
        assert await intermediate_journal_ids(async_connection, task_id) == [mentioned]

    async def test_attaching_again_leaves_one_row_and_reports_no_change(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """Idempotency comes from the primary key, not from a read-then-write.

        There is no "is it already attached?" query anywhere: the insert asks the
        database, which is what makes two concurrent attaches safe without a lock.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        mentioned = await create_journal(journal_repository, title="Came up again")

        first = await service.attach_intermediate_journal(
            user_id=USER_ID,
            task_id=task_id,
            journal_id=mentioned,
            transaction=async_connection,
        )
        second = await service.attach_intermediate_journal(
            user_id=USER_ID,
            task_id=task_id,
            journal_id=mentioned,
            transaction=async_connection,
        )

        assert (first, second) == (True, False)
        assert await intermediate_journal_ids(async_connection, task_id) == [mentioned]

    async def test_several_journals_accumulate_rather_than_replacing(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """A task may be linked to *any number* of journals; attaching is not setting.

        **The attach *order* is deliberately not asserted here, and cannot be.**
        ``task_intermediate_journals.created_at`` defaults to ``now()``, which in
        PostgreSQL is ``transaction_timestamp()`` and therefore identical for
        every row written inside one transaction — and every test in this file
        runs inside the fixture's single transaction. So
        ``ORDER BY created_at, journal_id`` degenerates to ``ORDER BY journal_id``
        here, and an assertion on "the order they were attached" would really be
        an assertion that the ids ascend, passing whatever the service did.
        Review caught exactly that, so the assertion is on the *set*.

        The same fact bounds what the trail can promise in production: two links
        written inside one request tie as well, so "oldest link first" is a
        partial order, not a total one. Phase 13's read model owns whatever
        ordering it needs to guarantee.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        first = await create_journal(journal_repository, title="First mention")
        second = await create_journal(journal_repository, title="Second mention")

        for journal_id in (first, second):
            await service.attach_intermediate_journal(
                user_id=USER_ID,
                task_id=task_id,
                journal_id=journal_id,
                transaction=async_connection,
            )

        assert sorted(await intermediate_journal_ids(async_connection, task_id)) == (
            sorted([first, second])
        )

    async def test_no_contact_link_is_written(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """A journal link touches the journal link table and nothing else."""
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        await create_contact(async_connection, first_name="Sarah")
        mentioned = await create_journal(journal_repository, title="Came up again")

        await service.attach_intermediate_journal(
            user_id=USER_ID,
            task_id=task_id,
            journal_id=mentioned,
            transaction=async_connection,
        )

        assert (
            await count(
                async_connection,
                "SELECT COUNT(*) FROM task_contacts WHERE task_id = :task_id",
                {"task_id": task_id},
            )
            == 0
        )


class TestDetachingAnIntermediateJournal:
    """Removal is idempotent and asks nothing of the journal."""

    async def test_the_link_row_is_removed(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        mentioned = await create_journal(journal_repository, title="Came up again")
        await link_intermediate_journal(
            async_connection, task_id=task_id, journal_id=mentioned
        )

        changed = await service.detach_intermediate_journal(
            user_id=USER_ID,
            task_id=task_id,
            journal_id=mentioned,
            transaction=async_connection,
        )

        assert changed is True
        assert await intermediate_journal_ids(async_connection, task_id) == []

    async def test_detaching_again_is_accepted_and_reports_no_change(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        mentioned = await create_journal(journal_repository, title="Came up again")
        await link_intermediate_journal(
            async_connection, task_id=task_id, journal_id=mentioned
        )

        first = await service.detach_intermediate_journal(
            user_id=USER_ID,
            task_id=task_id,
            journal_id=mentioned,
            transaction=async_connection,
        )
        second = await service.detach_intermediate_journal(
            user_id=USER_ID,
            task_id=task_id,
            journal_id=mentioned,
            transaction=async_connection,
        )

        assert (first, second) == (True, False)

    async def test_detaching_leaves_the_other_links_alone(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        kept = await create_journal(journal_repository, title="Still relevant")
        dropped = await create_journal(journal_repository, title="Not any more")
        for journal_id in (kept, dropped):
            await link_intermediate_journal(
                async_connection, task_id=task_id, journal_id=journal_id
            )

        await service.detach_intermediate_journal(
            user_id=USER_ID,
            task_id=task_id,
            journal_id=dropped,
            transaction=async_connection,
        )

        assert await intermediate_journal_ids(async_connection, task_id) == [kept]
        assert await stored_anchors(async_connection, task_id) == (creating_id, due_id)


class TestLinksAreEditableInAnyStatus:
    """The specification's "at any time, in any status", against a stored status.

    Seeded per status rather than parametrised over a stub, because the claim is
    that nothing reads or writes the status column — which only a real row can
    show.
    """

    @pytest.mark.parametrize("status", ALL_STATUSES)
    async def test_attaching_works_and_leaves_the_status_alone(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
        status: Status,
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=status,
        )
        mentioned = await create_journal(journal_repository, title="Came up again")

        assert (
            await service.attach_intermediate_journal(
                user_id=USER_ID,
                task_id=task_id,
                journal_id=mentioned,
                transaction=async_connection,
            )
            is True
        )

        assert await stored_status(async_connection, task_id) == status.value

    @pytest.mark.parametrize("status", ALL_STATUSES)
    async def test_detaching_works_and_leaves_the_status_alone(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
        status: Status,
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            status=status,
        )
        mentioned = await create_journal(journal_repository, title="Came up again")
        await link_intermediate_journal(
            async_connection, task_id=task_id, journal_id=mentioned
        )

        assert (
            await service.detach_intermediate_journal(
                user_id=USER_ID,
                task_id=task_id,
                journal_id=mentioned,
                transaction=async_connection,
            )
            is True
        )

        assert await stored_status(async_connection, task_id) == status.value


class TestTheAnchorsAreNotIntermediateLinks:
    """Both directions of the rule, against anchors that are live foreign keys."""

    @pytest.mark.parametrize("anchor", ["creating", "due"])
    async def test_attaching_an_anchor_is_refused_and_writes_nothing(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        anchor: str,
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        journal_id = creating_id if anchor == "creating" else due_id

        with pytest.raises(TaskJournalIsAnchorError) as exc_info:
            await service.attach_intermediate_journal(
                user_id=USER_ID,
                task_id=task_id,
                journal_id=journal_id,
                transaction=async_connection,
            )

        assert exc_info.value.anchor == anchor
        assert await _link_count(async_connection) == 0

    @pytest.mark.parametrize("anchor", ["creating", "due"])
    async def test_detaching_an_anchor_is_refused_rather_than_a_silent_no_op(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
        anchor: str,
    ):
        """The repository would answer ``False`` here, which reads as "not linked".

        That is the misleading answer the explicit refusal exists to replace: the
        anchor *is* linked, in a role this table does not hold, so "there was
        nothing to remove" would send the caller looking for a link they do not
        have rather than telling them the operation is the wrong one.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        journal_id = creating_id if anchor == "creating" else due_id

        with pytest.raises(TaskJournalIsAnchorError) as exc_info:
            await service.detach_intermediate_journal(
                user_id=USER_ID,
                task_id=task_id,
                journal_id=journal_id,
                transaction=async_connection,
            )

        assert exc_info.value.anchor == anchor
        assert await stored_anchors(async_connection, task_id) == (creating_id, due_id)

    async def test_a_task_anchored_twice_to_one_journal_is_still_refused(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """Invariant 6: the creating and due journal may be the same journal.

        Both anchor columns then point at one row, and the refusal names the
        creating role — the half that can never be moved.
        """
        both = await create_journal(
            journal_repository, title="Arose and due here", days_offset=7
        )
        task_id = await create_task(
            async_connection, creating_journal_id=both, due_journal_id=both
        )

        with pytest.raises(TaskJournalIsAnchorError) as exc_info:
            await service.attach_intermediate_journal(
                user_id=USER_ID,
                task_id=task_id,
                journal_id=both,
                transaction=async_connection,
            )

        assert exc_info.value.anchor == "creating"


class TestTheRetargetTrail:
    """Phase 7's automatic link meets this phase's manual one.

    Retargeting keeps the previous due journal as an intermediate link. That link
    is an ordinary one — the user may remove it — while the *new* due journal is
    an anchor and may not be. The two rules meet on the same task here, which is
    the only place the interaction is visible.
    """

    async def test_the_journal_a_task_was_deferred_from_can_be_detached(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        later = await create_journal(
            journal_repository, title="Deferred to here", days_offset=14
        )

        await service.retarget_due_journal(
            user_id=USER_ID,
            task_id=task_id,
            due_journal_id=later,
            transaction=async_connection,
        )
        assert await intermediate_journal_ids(async_connection, task_id) == [due_id]

        assert (
            await service.detach_intermediate_journal(
                user_id=USER_ID,
                task_id=task_id,
                journal_id=due_id,
                transaction=async_connection,
            )
            is True
        )
        assert await intermediate_journal_ids(async_connection, task_id) == []

    async def test_the_new_due_journal_cannot_be_detached(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        later = await create_journal(
            journal_repository, title="Deferred to here", days_offset=14
        )

        await service.retarget_due_journal(
            user_id=USER_ID,
            task_id=task_id,
            due_journal_id=later,
            transaction=async_connection,
        )

        with pytest.raises(TaskJournalIsAnchorError) as exc_info:
            await service.detach_intermediate_journal(
                user_id=USER_ID,
                task_id=task_id,
                journal_id=later,
                transaction=async_connection,
            )

        assert exc_info.value.anchor == "due"

    async def test_a_journal_retargeted_onto_keeps_its_own_link_removable(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """The regression a review of this phase found, end to end.

        Attach a journal, then retarget the task **onto** it. The row this
        surface wrote is still there — ``retarget_due_journal`` never unlinks,
        deliberately — while the journal has become the due anchor. Refusing the
        detach on the anchor alone made that row permanently unremovable, which
        contradicts the specification's *"intermediate links can be removed"* for
        a link the user created through this very method.

        So the detach succeeds, removes exactly the row, and leaves the due
        anchor exactly where the retarget put it. The anchor is still not
        detachable — the *next* call, with no row left to remove, is refused.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        later = await create_journal(
            journal_repository, title="Mentioned, then due", days_offset=14
        )

        await service.attach_intermediate_journal(
            user_id=USER_ID,
            task_id=task_id,
            journal_id=later,
            transaction=async_connection,
        )
        await service.retarget_due_journal(
            user_id=USER_ID,
            task_id=task_id,
            due_journal_id=later,
            transaction=async_connection,
        )
        # Both roles at once: the row from the attach, and the anchor from the
        # retarget, plus the journal the task was deferred *from*.
        assert sorted(await intermediate_journal_ids(async_connection, task_id)) == (
            sorted([later, due_id])
        )
        assert await stored_anchors(async_connection, task_id) == (creating_id, later)

        assert (
            await service.detach_intermediate_journal(
                user_id=USER_ID,
                task_id=task_id,
                journal_id=later,
                transaction=async_connection,
            )
            is True
        )

        assert await intermediate_journal_ids(async_connection, task_id) == [due_id]
        assert await stored_anchors(async_connection, task_id) == (creating_id, later)

        with pytest.raises(TaskJournalIsAnchorError) as exc_info:
            await service.detach_intermediate_journal(
                user_id=USER_ID,
                task_id=task_id,
                journal_id=later,
                transaction=async_connection,
            )

        assert exc_info.value.anchor == "due"


class TestDeletingAJournal:
    """The permitted half, through a link this surface created.

    The specification permits deleting a journal that is only an intermediate
    link, and the link goes with it. Asserted against the real constraint rather
    than through ``JournalService``'s delete guard, which would answer before the
    constraint could. The refused half — an anchor journal — is a schema property
    this surface cannot reach, and is covered in
    ``test_task_tables_constraints.py::TestAnchorJournalDeletionIsRefused``.
    """

    async def test_an_intermediate_journal_can_be_deleted_and_takes_its_link(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        mentioned = await create_journal(journal_repository, title="Came up again")
        await service.attach_intermediate_journal(
            user_id=USER_ID,
            task_id=task_id,
            journal_id=mentioned,
            transaction=async_connection,
        )

        await delete_journal(async_connection, mentioned)

        assert await intermediate_journal_ids(async_connection, task_id) == []
        assert await stored_anchors(async_connection, task_id) == (creating_id, due_id)

    async def test_detaching_a_deleted_journal_is_accepted(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """The asymmetry's whole point: the tidy-up call must not 404.

        A user who deleted the journal and then asks to detach it is asking for
        the state they already have, and demanding the journal exist would fail
        exactly that call.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        mentioned = await create_journal(journal_repository, title="Came up again")
        await service.attach_intermediate_journal(
            user_id=USER_ID,
            task_id=task_id,
            journal_id=mentioned,
            transaction=async_connection,
        )
        await delete_journal(async_connection, mentioned)

        assert (
            await service.detach_intermediate_journal(
                user_id=USER_ID,
                task_id=task_id,
                journal_id=mentioned,
                transaction=async_connection,
            )
            is False
        )


class TestRejections:
    """An unreachable journal, and an unreachable task, on both calls."""

    async def test_an_unknown_journal_is_refused_and_nothing_is_written(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        with pytest.raises(JournalNotFoundError) as exc_info:
            await service.attach_intermediate_journal(
                user_id=USER_ID,
                task_id=task_id,
                journal_id=999_999,
                transaction=async_connection,
            )

        assert exc_info.value.journal_id == 999_999
        assert await _link_count(async_connection) == 0

    async def test_another_users_journal_is_refused_byte_identically(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        task_anchors: tuple[int, int],
    ):
        """A real second user's journal, not an absent id.

        A read that dropped its ``user_id`` filter would still find nothing for
        an id that never existed, so only a row somebody else owns can show that
        ownership is enforced — and the two messages must be indistinguishable,
        or a rejection becomes a way to probe for other users' journals.
        """
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        theirs = await create_journal(
            journal_repository, title="Not yours", user_id=OTHER_USER_ID
        )

        with pytest.raises(JournalNotFoundError) as foreign:
            await service.attach_intermediate_journal(
                user_id=USER_ID,
                task_id=task_id,
                journal_id=theirs,
                transaction=async_connection,
            )

        assert str(foreign.value) == str(JournalNotFoundError(theirs))
        assert await _link_count(async_connection) == 0

    async def test_another_users_task_is_unreachable_on_both_calls(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """Their task keeps its links, and the answer says nothing about ownership."""
        their_journal = await create_journal(
            journal_repository, title="Theirs", user_id=OTHER_USER_ID
        )
        their_task = await create_task(
            async_connection,
            creating_journal_id=their_journal,
            due_journal_id=their_journal,
            user_id=OTHER_USER_ID,
        )
        their_mention = await create_journal(
            journal_repository, title="Their mention", user_id=OTHER_USER_ID
        )
        await link_intermediate_journal(
            async_connection, task_id=their_task, journal_id=their_mention
        )
        mine = await create_journal(journal_repository, title="Mine")

        with pytest.raises(TaskNotFoundError) as attaching:
            await service.attach_intermediate_journal(
                user_id=USER_ID,
                task_id=their_task,
                journal_id=mine,
                transaction=async_connection,
            )
        with pytest.raises(TaskNotFoundError) as detaching:
            await service.detach_intermediate_journal(
                user_id=USER_ID,
                task_id=their_task,
                journal_id=their_mention,
                transaction=async_connection,
            )

        assert str(attaching.value) == str(TaskNotFoundError(their_task))
        assert str(detaching.value) == str(TaskNotFoundError(their_task))
        assert await intermediate_journal_ids(async_connection, their_task) == [
            their_mention
        ]

    async def test_an_absent_task_answers_exactly_as_a_foreign_one(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """The two answers are compared with each other, not each with a template.

        Review caught the earlier version doing the latter: both cases were
        checked against a freshly-constructed ``TaskNotFoundError``, which passes
        for two answers that differ in any way the constructor also produces. The
        comparison that means something is between the *two rejections*, with the
        only legitimate difference — the id the caller supplied — normalised out.
        """
        their_journal = await create_journal(
            journal_repository, title="Theirs", user_id=OTHER_USER_ID
        )
        their_task = await create_task(
            async_connection,
            creating_journal_id=their_journal,
            due_journal_id=their_journal,
            user_id=OTHER_USER_ID,
        )
        mine = await create_journal(journal_repository, title="Mine")

        with pytest.raises(TaskNotFoundError) as foreign:
            await service.attach_intermediate_journal(
                user_id=USER_ID,
                task_id=their_task,
                journal_id=mine,
                transaction=async_connection,
            )
        with pytest.raises(TaskNotFoundError) as absent:
            await service.attach_intermediate_journal(
                user_id=USER_ID,
                task_id=999_999,
                journal_id=mine,
                transaction=async_connection,
            )

        assert str(foreign.value).replace(str(their_task), "X") == str(
            absent.value
        ).replace("999999", "X")
        assert type(foreign.value) is type(absent.value)


class TestAJournalThatVanishesMidWrite:
    """The ``_save`` race, one table over, against a real foreign key.

    The journal was proved to exist a statement ago; a delete in the window
    between that read and the insert fails the foreign key. The caller was
    promised a 404, so the violation is mapped back rather than escaping as the
    500 a raw ``IntegrityError`` becomes.

    Unlike the batched contact insert this needs **no savepoint**: one journal is
    named per call, so nothing has to run against the aborted transaction to work
    out which id went missing.
    """

    async def test_a_journal_deleted_after_the_check_still_answers_not_found(
        self,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        user_settings_repository: SqlUserSettingsRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        mentioned = await create_journal(journal_repository, title="About to go")

        class _VanishingJournalRepository(SqlJournalRepository):
            """Reports the journal, then deletes it before the link is written."""

            deleted = False

            async def find_by_ids_for_user(
                self, user_id: str, journal_ids: list[int]
            ) -> list[Journal]:
                found = await super().find_by_ids_for_user(user_id, journal_ids)
                if not self.deleted:
                    self.deleted = True
                    await delete_journal(async_connection, mentioned)
                return found

        service = TaskService(
            task_repo=SqlTaskRepository(async_connection),
            journal_repo=_VanishingJournalRepository(async_connection),
            contact_repo=SqlContactRepository(async_connection),
            date_resolver=JournalDateResolver(
                user_settings_repo=user_settings_repository
            ),
        )

        with pytest.raises(JournalNotFoundError) as exc_info:
            await service.attach_intermediate_journal(
                user_id=USER_ID,
                task_id=task_id,
                journal_id=mentioned,
                transaction=async_connection,
            )

        assert exc_info.value.journal_id == mentioned


class TestTheWritesAreUnitsOfWork:
    """What ``@transactional`` actually guarantees, asserted where it is visible.

    Reading a row back after the call proves nothing here: the fixture owns an
    outer transaction and marks the connection, so ``unit_of_work`` stands a
    SAVEPOINT in for the commit and the row is visible with or without the
    decorator. What *is* observable is the transaction open around the repository
    call.

    Both writes are watched at their own statement, which the contact-link tests
    could not do for the insert: that one wraps itself in a savepoint, so a nested
    transaction would be open there either way. Neither of these methods opens one
    of its own, so what is observed is the unit of work and nothing else.

    **Mutation-checked:** deleting ``@transactional`` from either method makes
    exactly its own test here fail.
    """

    async def test_attach_writes_inside_an_open_unit_of_work(
        self,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        user_settings_repository: SqlUserSettingsRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        mentioned = await create_journal(journal_repository, title="Came up again")
        observed: list[bool] = []

        class _ObservingRepository(SqlTaskRepository):
            async def add_intermediate_journal(
                self, task_id: int, journal_id: int, user_id: str
            ) -> bool:
                observed.append(async_connection.get_nested_transaction() is not None)
                return await super().add_intermediate_journal(
                    task_id, journal_id, user_id
                )

        service = TaskService(
            task_repo=_ObservingRepository(async_connection),
            journal_repo=journal_repository,
            contact_repo=SqlContactRepository(async_connection),
            date_resolver=JournalDateResolver(
                user_settings_repo=user_settings_repository
            ),
        )

        await service.attach_intermediate_journal(
            user_id=USER_ID,
            task_id=task_id,
            journal_id=mentioned,
            transaction=async_connection,
        )

        assert observed == [True]
        assert async_connection.get_nested_transaction() is None

    async def test_detach_writes_inside_an_open_unit_of_work(
        self,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        user_settings_repository: SqlUserSettingsRepository,
        task_anchors: tuple[int, int],
    ):
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        mentioned = await create_journal(journal_repository, title="Came up again")
        await link_intermediate_journal(
            async_connection, task_id=task_id, journal_id=mentioned
        )
        observed: list[bool] = []

        class _ObservingRepository(SqlTaskRepository):
            async def remove_intermediate_journal(
                self, task_id: int, journal_id: int, user_id: str
            ) -> bool:
                observed.append(async_connection.get_nested_transaction() is not None)
                return await super().remove_intermediate_journal(
                    task_id, journal_id, user_id
                )

        service = TaskService(
            task_repo=_ObservingRepository(async_connection),
            journal_repo=journal_repository,
            contact_repo=SqlContactRepository(async_connection),
            date_resolver=JournalDateResolver(
                user_settings_repo=user_settings_repository
            ),
        )

        await service.detach_intermediate_journal(
            user_id=USER_ID,
            task_id=task_id,
            journal_id=mentioned,
            transaction=async_connection,
        )

        assert observed == [True]
        assert async_connection.get_nested_transaction() is None
