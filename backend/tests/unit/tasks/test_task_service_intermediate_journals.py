"""Unit tests for ``TaskService.attach_intermediate_journal`` and ``detach_...``.

An intermediate journal is one the task was *"discussed, revisited, or previously
due"* in. The specification gives the link three properties and this file pins
each of them against mocked repositories:

- **explicit only.** Nothing infers a link from an edit, so the only way one
  appears is this method or the automatic retention on a retarget. Most of what
  is asserted here is therefore an *absence*: no status is read or written, no
  contact is touched, no timezone is resolved.
- **idempotent.** Attaching a journal that is already attached is accepted and
  changes nothing. The service does not ask first — idempotency is the composite
  primary key's, so there is no window between the question and the answer — and
  the boolean is the only thing that distinguishes the two calls.
- **anchors are not intermediate links.** A journal that is already the task's
  creating or due journal cannot be attached — it is already linked in a stronger
  role — and an anchor with **no link row** cannot be detached, because the
  creating journal never changes and the due journal is changed by retargeting.
  One rule, so one error, carrying which anchor it was. The "no link row" half is
  load-bearing rather than pedantic: a journal can legitimately be both an anchor
  and an intermediate link, and refusing on the anchor alone made such a row
  permanently unremovable.

The deliberate asymmetry mirrors ``unlink_contact``: **attaching proves the
journal exists and is the acting user's; detaching does not.**
``task_intermediate_journals.journal_id`` cascades from the journal side, so a
deleted journal's links are already gone, and the specification says deleting a
journal that is only an intermediate link is permitted.

Repositories are mocked. The SQL these methods lean on — the idempotent insert,
the owner-scoped guard, the cascade — is proved against a real database in
``tests/integration/tasks/test_task_intermediate_journal_links_integration.py``.
"""

import datetime
from unittest.mock import AsyncMock

import pytest
from core_shared.models.journals import EventDateRange, Journal, JournalNotFoundError
from core_shared.models.tasks import (
    Task,
    TaskJournalIsAnchorError,
    TaskNotFoundError,
    TaskStatus,
)
from sqlalchemy.exc import IntegrityError

from app.core.journal.services.journal_date_resolver import JournalDateResolver
from app.core.tasks.models.repositories import TaskRepository
from app.core.tasks.services.task_service import TaskService

USER_ID = "test-user-123"
OTHER_USER_ID = "other-user-456"

TASK_ID = 7
CREATING_JOURNAL_ID = 11
DUE_JOURNAL_ID = 22
JOURNAL_ID = 33
UNKNOWN_JOURNAL_ID = 404

WHENEVER = datetime.datetime(2026, 8, 5, 9, 0, tzinfo=datetime.UTC)


def make_journal(journal_id: int = JOURNAL_ID) -> Journal:
    """An instantaneous journal, as the owner-scoped read hands it back.

    Its *date* is never consulted on either path — an intermediate link carries
    no future-dated rule, unlike a due anchor — so one fixed instant serves every
    test here.
    """
    return Journal(
        id=journal_id,
        user_id=USER_ID,
        title="Where it came up again",
        content="content",
        event_date_range=EventDateRange(start=WHENEVER, end=WHENEVER),
    )


def make_task(
    status: TaskStatus = TaskStatus.NOT_DONE,
    *,
    creating_journal_id: int = CREATING_JOURNAL_ID,
    due_journal_id: int = DUE_JOURNAL_ID,
) -> Task:
    """A persisted task in ``status``, as the repository would hand it back."""
    return Task(
        id=TASK_ID,
        user_id=USER_ID,
        text="return Sarah's book",
        creating_journal_id=creating_journal_id,
        due_journal_id=due_journal_id,
        status=status,
    )


def integrity_error(constraint: str) -> IntegrityError:
    """An ``IntegrityError`` shaped like the driver's, naming ``constraint``.

    The driver's own message is what the service matches on, so the fabricated
    ``orig`` carries the constraint name while the statement carries the full
    column list — the shape that caught the ``str(error)`` bug in Phase 4, where
    matching against the statement reported whichever column was tested first.
    """
    return IntegrityError(
        statement=(
            "INSERT INTO task_intermediate_journals (task_id, journal_id) VALUES (...)"
        ),
        params=None,
        orig=Exception(f'violates foreign key constraint "{constraint}"'),
    )


@pytest.fixture
def mock_task_repo() -> AsyncMock:
    """A task repository that finds the task and links successfully.

    Built with ``spec=TaskRepository`` rather than bare, which review asked for
    and the rest of this domain's unit tests do not yet do. Several assertions
    here are of the form ``some_method.assert_not_awaited()`` — the direct proof
    that there is no "is it already attached?" read — and on a bare ``AsyncMock``
    every one of those passes **vacuously** the moment the port method is
    renamed, since the mock would happily invent the old name. The spec makes a
    rename a failure instead of a silent pass.
    """
    repo = AsyncMock(spec=TaskRepository)
    repo.find_by_id.return_value = make_task()
    repo.add_intermediate_journal.return_value = True
    repo.remove_intermediate_journal.return_value = True
    return repo


@pytest.fixture
def mock_journal_repo() -> AsyncMock:
    """A journal repository holding the journal under test, owner-scoped."""
    repo = AsyncMock()
    repo.find_by_ids_for_user.return_value = [make_journal()]
    return repo


@pytest.fixture
def mock_contact_repo() -> AsyncMock:
    """A contact repository no journal link may touch."""
    return AsyncMock()


@pytest.fixture
def mock_settings_repo() -> AsyncMock:
    """A settings repository; an intermediate link never needs a timezone."""
    repo = AsyncMock()
    repo.get_timezone.return_value = "UTC"
    return repo


@pytest.fixture
def mock_transaction() -> AsyncMock:
    """A stand-in connection; ``@transactional`` runs unwrapped for a non-real one."""
    return AsyncMock()


@pytest.fixture
def service(
    mock_task_repo: AsyncMock,
    mock_journal_repo: AsyncMock,
    mock_contact_repo: AsyncMock,
    mock_settings_repo: AsyncMock,
) -> TaskService:
    """The service under test."""
    return TaskService(
        task_repo=mock_task_repo,
        journal_repo=mock_journal_repo,
        contact_repo=mock_contact_repo,
        date_resolver=JournalDateResolver(mock_settings_repo),
    )


async def attach(
    service: TaskService,
    transaction: AsyncMock,
    *,
    user_id: str = USER_ID,
    task_id: int = TASK_ID,
    journal_id: int = JOURNAL_ID,
) -> bool:
    """Call ``attach_intermediate_journal`` with the ordinary arguments."""
    return await service.attach_intermediate_journal(
        user_id=user_id,
        task_id=task_id,
        journal_id=journal_id,
        transaction=transaction,
    )


async def detach(
    service: TaskService,
    transaction: AsyncMock,
    *,
    user_id: str = USER_ID,
    task_id: int = TASK_ID,
    journal_id: int = JOURNAL_ID,
) -> bool:
    """Call ``detach_intermediate_journal`` with the ordinary arguments."""
    return await service.detach_intermediate_journal(
        user_id=user_id,
        task_id=task_id,
        journal_id=journal_id,
        transaction=transaction,
    )


@pytest.mark.unit
class TestAttachingAnIntermediateJournal:
    """One journal, one idempotent insert, no role of any kind."""

    @pytest.mark.asyncio
    async def test_writes_the_link(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        assert await attach(service, mock_transaction) is True

        mock_task_repo.add_intermediate_journal.assert_awaited_once_with(
            TASK_ID, JOURNAL_ID, USER_ID
        )

    @pytest.mark.asyncio
    async def test_attaching_again_is_accepted_and_reports_no_change(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Idempotency: the repeat succeeds and says a row was already there."""
        mock_task_repo.add_intermediate_journal.return_value = False

        assert await attach(service, mock_transaction) is False

    @pytest.mark.asyncio
    async def test_does_not_ask_whether_the_link_already_exists(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """De-duplication is the primary key's, not a read-then-add.

        A read-then-add would leave a window between the question and the answer
        in which a concurrent attach could land, and would cost a query on every
        call to close a case the constraint closes for free. Phase 7 made the
        same choice for the automatic link.
        """
        await attach(service, mock_transaction)

        mock_task_repo.list_intermediate_journal_ids.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_unknown_journal_is_refused_and_writes_nothing(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The specification requires the journal to be the acting user's.

        The answer is the *journal domain's* not-found error rather than a
        task-shaped one, so it names the journal and the id the caller got wrong.
        """
        mock_journal_repo.find_by_ids_for_user.return_value = []

        with pytest.raises(JournalNotFoundError) as exc_info:
            await attach(service, mock_transaction, journal_id=UNKNOWN_JOURNAL_ID)

        assert exc_info.value.journal_id == UNKNOWN_JOURNAL_ID
        assert exc_info.value.status_code == 404
        mock_task_repo.add_intermediate_journal.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_another_users_journal_is_indistinguishable_from_an_absent_one(
        self,
        service: TaskService,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Ownership is enforced *by the query*, so the two produce one message.

        The read is asserted to carry the acting user, which is what makes
        somebody else's journal simply absent from the result rather than
        something the service has to compare and reject afterwards.
        """
        mock_journal_repo.find_by_ids_for_user.return_value = []

        with pytest.raises(JournalNotFoundError) as exc_info:
            await attach(service, mock_transaction)

        assert str(exc_info.value) == str(JournalNotFoundError(JOURNAL_ID))
        mock_journal_repo.find_by_ids_for_user.assert_awaited_once_with(
            USER_ID, [JOURNAL_ID]
        )

    @pytest.mark.asyncio
    async def test_the_creating_journal_is_refused(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """It is already linked, in a role an intermediate link cannot express."""
        mock_journal_repo.find_by_ids_for_user.return_value = [
            make_journal(CREATING_JOURNAL_ID)
        ]

        with pytest.raises(TaskJournalIsAnchorError) as exc_info:
            await attach(service, mock_transaction, journal_id=CREATING_JOURNAL_ID)

        assert exc_info.value.anchor == "creating"
        assert exc_info.value.journal_id == CREATING_JOURNAL_ID
        assert exc_info.value.task_id == TASK_ID
        assert exc_info.value.status_code == 409
        mock_task_repo.add_intermediate_journal.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_due_journal_is_refused(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        mock_journal_repo.find_by_ids_for_user.return_value = [
            make_journal(DUE_JOURNAL_ID)
        ]

        with pytest.raises(TaskJournalIsAnchorError) as exc_info:
            await attach(service, mock_transaction, journal_id=DUE_JOURNAL_ID)

        assert exc_info.value.anchor == "due"
        assert exc_info.value.status_code == 409
        mock_task_repo.add_intermediate_journal.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_message_names_the_way_the_anchor_is_really_changed(
        self,
        service: TaskService,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """A refusal an agent can act on says what to do instead.

        Retargeting is the operation that moves a due anchor, and the creating
        anchor moves for nobody; a message that only refused would leave a caller
        guessing which.
        """
        mock_journal_repo.find_by_ids_for_user.return_value = [
            make_journal(DUE_JOURNAL_ID)
        ]

        with pytest.raises(TaskJournalIsAnchorError) as due_info:
            await attach(service, mock_transaction, journal_id=DUE_JOURNAL_ID)

        assert "retarget" in due_info.value.message.lower()

        mock_journal_repo.find_by_ids_for_user.return_value = [
            make_journal(CREATING_JOURNAL_ID)
        ]

        with pytest.raises(TaskJournalIsAnchorError) as creating_info:
            await attach(service, mock_transaction, journal_id=CREATING_JOURNAL_ID)

        assert "never changes" in creating_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_a_task_anchored_twice_to_one_journal_reports_one_role(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Invariant 6 lets both anchors be the same journal; the answer is stable.

        Without a deliberate order this would report whichever anchor the
        implementation happened to test first, so it is pinned: the creating
        anchor is named, because it is the one that can never be moved and
        therefore the more useful half to tell the caller about.
        """
        mock_task_repo.find_by_id.return_value = make_task(
            creating_journal_id=JOURNAL_ID, due_journal_id=JOURNAL_ID
        )

        with pytest.raises(TaskJournalIsAnchorError) as exc_info:
            await attach(service, mock_transaction)

        assert exc_info.value.anchor == "creating"

    @pytest.mark.asyncio
    async def test_no_status_is_written(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Journal links, like contact links, are editable in any status.

        Named for what it actually asserts, which review corrected: the *write*
        half. The service does read a task, and that task carries a status, so no
        mock assertion here can prove it never branches on one — an
        implementation that read ``task.status`` and ignored it would pass. The
        read half is proved where it is observable: the three status matrices
        against a real database, each of which seeds every status and checks the
        stored status is unmoved afterwards.
        """
        await attach(service, mock_transaction)

        mock_task_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_read_does_not_lock_the_task_row(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The plain read is used, and the locking one is not — deliberately.

        ``set_status`` and ``retarget_due_journal`` lock because they decide a
        *rule* from the state they read and write that decision back. The rule
        here is different: the only state that can move underneath it is a
        concurrent retarget making this journal the due anchor, and the resulting
        shape — a due anchor that is also an intermediate link — is one
        ``retarget_due_journal`` produces on its own and Phase 7 explicitly
        declined to clean up. A lock would narrow a window onto an outcome that
        is legitimate either side of it.
        """
        await attach(service, mock_transaction)

        mock_task_repo.find_by_id.assert_awaited_once_with(TASK_ID, USER_ID)
        mock_task_repo.find_by_id_for_update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_contact_or_timezone_is_involved(
        self,
        service: TaskService,
        mock_contact_repo: AsyncMock,
        mock_settings_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """No contact, and no local day.

        An intermediate journal carries no future-dated rule — that is a rule
        about *setting a due journal* — so the timezone the whole date machinery
        needs is never fetched. Asserted on ``mock_calls`` rather than on named
        methods, the Phase 6 idiom, so a method added to either port later cannot
        slip through.
        """
        await attach(service, mock_transaction)

        assert mock_contact_repo.mock_calls == []
        assert mock_settings_repo.mock_calls == []


@pytest.mark.unit
class TestDetachingAnIntermediateJournal:
    """Removal is idempotent and asks nothing of the journal."""

    @pytest.mark.asyncio
    async def test_removes_the_link(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        assert await detach(service, mock_transaction) is True

        mock_task_repo.remove_intermediate_journal.assert_awaited_once_with(
            TASK_ID, JOURNAL_ID, USER_ID
        )

    @pytest.mark.asyncio
    async def test_detaching_again_reports_no_change(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """A link that was not there is not an error — ``DELETE`` is idempotent."""
        mock_task_repo.remove_intermediate_journal.return_value = False

        assert await detach(service, mock_transaction) is False

    @pytest.mark.asyncio
    async def test_does_not_require_the_journal_to_still_exist(
        self,
        service: TaskService,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The deliberate asymmetry with attaching.

        ``task_intermediate_journals.journal_id`` cascades, so a deleted
        journal's links are already gone — the specification's *"deleting a
        journal that is only an intermediate link is permitted"* — and demanding
        the journal here would fail exactly the tidy-up call. Asserted on
        ``mock_calls``: the journal port is not touched at all.
        """
        mock_journal_repo.find_by_ids_for_user.return_value = []

        assert (
            await detach(service, mock_transaction, journal_id=UNKNOWN_JOURNAL_ID)
            is True
        )

        assert mock_journal_repo.mock_calls == []

    @pytest.mark.asyncio
    async def test_the_creating_journal_cannot_be_detached(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The anchor role is a column, so a silent no-op would mislead.

        ``remove_intermediate_journal`` answers ``False`` for an anchor with no
        link row, and a caller would read that as "it was not attached" rather
        than "that link cannot be removed at all".
        """
        mock_task_repo.remove_intermediate_journal.return_value = False

        with pytest.raises(TaskJournalIsAnchorError) as exc_info:
            await detach(service, mock_transaction, journal_id=CREATING_JOURNAL_ID)

        assert exc_info.value.anchor == "creating"
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_the_due_journal_cannot_be_detached(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        mock_task_repo.remove_intermediate_journal.return_value = False

        with pytest.raises(TaskJournalIsAnchorError) as exc_info:
            await detach(service, mock_transaction, journal_id=DUE_JOURNAL_ID)

        assert exc_info.value.anchor == "due"

    @pytest.mark.asyncio
    async def test_an_anchor_that_also_has_a_link_row_is_detachable(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The correction a review of this phase forced, at its narrowest.

        The refusal is about the **missing row**, not about the anchor. A journal
        can legitimately be both: attach it, then retarget the task onto it, and
        the row this surface wrote survives while the journal becomes the due
        anchor — a shape ``retarget_due_journal`` deliberately leaves alone.
        Refusing there would make a link the user created through this very
        method permanently unremovable, contradicting the specification's
        *"intermediate links can be removed"*.

        The anchor column is untouched either way: the repository only ever
        deletes from the link table.
        """
        mock_task_repo.remove_intermediate_journal.return_value = True

        assert (
            await detach(service, mock_transaction, journal_id=DUE_JOURNAL_ID) is True
        )

        mock_task_repo.remove_intermediate_journal.assert_awaited_once_with(
            TASK_ID, DUE_JOURNAL_ID, USER_ID
        )
        mock_task_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_status_is_written(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        await detach(service, mock_transaction)

        mock_task_repo.save.assert_not_awaited()
        mock_task_repo.find_by_id_for_update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_contact_or_timezone_is_involved(
        self,
        service: TaskService,
        mock_contact_repo: AsyncMock,
        mock_settings_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        await detach(service, mock_transaction)

        assert mock_contact_repo.mock_calls == []
        assert mock_settings_repo.mock_calls == []


@pytest.mark.unit
class TestUnreachableTasks:
    """Somebody else's task and a nonexistent one are one answer, on both calls.

    Ownership itself belongs to the owner-scoped repository, which is where it is
    tested against a real second user's rows. What is asserted here is that the
    service **passes the acting user through and adds no branch of its own**, and
    that the task gate is reached *before* anything else — so a caller cannot
    learn about journals through a task that is not theirs.
    """

    @pytest.mark.asyncio
    async def test_attach_reports_an_unknown_task_as_not_found(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        mock_task_repo.find_by_id.return_value = None

        with pytest.raises(TaskNotFoundError) as exc_info:
            await attach(service, mock_transaction)

        assert exc_info.value.task_id == TASK_ID
        mock_task_repo.add_intermediate_journal.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_attach_to_another_users_task_is_indistinguishable(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        mock_task_repo.find_by_id.return_value = None

        with pytest.raises(TaskNotFoundError) as exc_info:
            await attach(service, mock_transaction, user_id=OTHER_USER_ID)

        assert str(exc_info.value) == str(TaskNotFoundError(TASK_ID))
        mock_task_repo.find_by_id.assert_awaited_once_with(TASK_ID, OTHER_USER_ID)

    @pytest.mark.asyncio
    async def test_detach_reports_an_unknown_task_as_not_found(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        mock_task_repo.find_by_id.return_value = None

        with pytest.raises(TaskNotFoundError) as exc_info:
            await detach(service, mock_transaction, user_id=OTHER_USER_ID)

        assert str(exc_info.value) == str(TaskNotFoundError(TASK_ID))
        mock_task_repo.remove_intermediate_journal.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_unreachable_task_is_answered_before_the_journal_is_read(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The task gate comes first, so a foreign task hides everything behind it.

        Both reads are scoped to the acting user, so neither ordering can leak
        another user's data. The tie is broken by which resource the caller named
        as the subject: a 404 on the task beats a 404 on the journal.
        """
        mock_task_repo.find_by_id.return_value = None
        mock_journal_repo.find_by_ids_for_user.return_value = []

        with pytest.raises(TaskNotFoundError):
            await attach(service, mock_transaction, journal_id=UNKNOWN_JOURNAL_ID)

        assert mock_journal_repo.mock_calls == []


@pytest.mark.unit
class TestAVanishedJournal:
    """The ``_save`` race, one table over.

    The journal was proved to exist a statement ago; a delete since then must
    still read as the ``JournalNotFoundError`` the method promises rather than as
    a raw integrity error rendered to the caller as a 500.
    """

    @pytest.mark.asyncio
    async def test_a_journal_deleted_after_the_check_keeps_its_404(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The id needs no recovery read, unlike the batched contact insert.

        One journal is named per call, so the violation can only be about that
        one — which is why this path needs no ``SAVEPOINT``: nothing runs after
        the failure, so the aborted transaction is never asked another question.
        """
        mock_task_repo.add_intermediate_journal.side_effect = integrity_error(
            "task_intermediate_journals_journal_id_fkey"
        )

        with pytest.raises(JournalNotFoundError) as exc_info:
            await attach(service, mock_transaction)

        assert exc_info.value.journal_id == JOURNAL_ID

    @pytest.mark.asyncio
    async def test_a_violation_naming_anything_else_is_re_raised(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """A genuine bug must not be dressed up as an actionable rejection."""
        mock_task_repo.add_intermediate_journal.side_effect = integrity_error(
            "task_intermediate_journals_task_id_fkey"
        )

        with pytest.raises(IntegrityError):
            await attach(service, mock_transaction)

    @pytest.mark.asyncio
    async def test_a_duplicate_key_is_not_mistaken_for_a_missing_journal(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Raised by review: the guard used to match the bare column name.

        A primary-key violation's ``DETAIL`` reads
        ``Key (task_id, journal_id)=(…) already exists``, so matching on
        ``journal_id`` alone would have reported a *duplicate* as a **missing
        journal** — a 404 for a row that is right there. Unreachable while the
        insert is ``ON CONFLICT DO NOTHING``, which is exactly the sort of "safe
        today" the ``str(error)`` bug in Phase 4 also was, so the guard now
        matches the foreign key by name and this pins it.
        """
        mock_task_repo.add_intermediate_journal.side_effect = IntegrityError(
            statement="INSERT INTO task_intermediate_journals ...",
            params=None,
            orig=Exception(
                "duplicate key value violates unique constraint "
                '"task_intermediate_journals_pkey"\n'
                "DETAIL:  Key (task_id, journal_id)=(7, 33) already exists."
            ),
        )

        with pytest.raises(IntegrityError):
            await attach(service, mock_transaction)
