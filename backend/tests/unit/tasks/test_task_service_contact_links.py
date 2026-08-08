"""Unit tests for ``TaskService.link_contact`` and ``unlink_contact``.

The specification's stance on contacts is deliberately thin: *"a plain
reference"* with no relationship type, role or attendance status, editable *"at
any time, in any status"*. Almost everything under test here is therefore a rule
about what the service does **not** do.

- No status is read and none is written, so a link works on a done or cancelled
  task exactly as it does on an open one.
- No journal is involved, so neither the journal nor the settings repository is
  touched on any path — asserted on ``mock_calls`` rather than on named methods,
  the Phase 6 idiom, so a method added to either port later cannot slip through.
- Linking is idempotent and unlinking is too. The service reports *whether a row
  moved*, which is what lets a surface answer the same way either time without
  losing the information an agent might want.

The one asymmetry is deliberate: **linking proves the contact exists, unlinking
does not.** A link whose contact was deleted is already gone through the
``ON DELETE CASCADE`` on ``task_contacts.contact_id``, so demanding that the
contact still exist would make cleanup fail in exactly the case the phase's
fourth acceptance criterion is about.

Repositories are mocked. The SQL these methods lean on — the idempotent insert,
the owner-scoped guard, the cascade — is proved against a real database in
``tests/integration/tasks/test_task_contact_links_integration.py``.
"""

from unittest.mock import AsyncMock

import pytest
from core_shared.models.tasks import Task, TaskNotFoundError, TaskStatus
from sqlalchemy.exc import IntegrityError

from app.core.contacts.models.exceptions import ContactNotFoundError
from app.core.journal.services.journal_date_resolver import JournalDateResolver
from app.core.tasks.services.task_service import TaskService

USER_ID = "test-user-123"
OTHER_USER_ID = "other-user-456"

TASK_ID = 7
CREATING_JOURNAL_ID = 11
DUE_JOURNAL_ID = 22
CONTACT_ID = 3


def make_task(status: TaskStatus = TaskStatus.NOT_DONE) -> Task:
    """A persisted task in ``status``, as the repository would hand it back."""
    return Task(
        id=TASK_ID,
        user_id=USER_ID,
        text="return Sarah's book",
        creating_journal_id=CREATING_JOURNAL_ID,
        due_journal_id=DUE_JOURNAL_ID,
        status=status,
    )


def integrity_error(constraint: str) -> IntegrityError:
    """An ``IntegrityError`` shaped like the driver's, naming ``constraint``.

    The driver's own message is what the service matches on, so the fabricated
    ``orig`` carries the constraint name and the statement carries the full
    column list — the shape that caught the ``str(error)`` bug in Phase 4.
    """
    return IntegrityError(
        statement="INSERT INTO task_contacts (task_id, contact_id) VALUES (...)",
        params=None,
        orig=Exception(f'violates foreign key constraint "{constraint}"'),
    )


@pytest.fixture
def mock_task_repo() -> AsyncMock:
    """A task repository that links and unlinks successfully."""
    repo = AsyncMock()
    repo.add_contacts.return_value = [CONTACT_ID]
    repo.remove_contact.return_value = True
    return repo


@pytest.fixture
def mock_journal_repo() -> AsyncMock:
    """A journal repository no contact link may touch."""
    return AsyncMock()


@pytest.fixture
def mock_contact_repo() -> AsyncMock:
    """A contact repository that knows the contact under test."""
    repo = AsyncMock()
    repo.find_names_by_ids.return_value = {CONTACT_ID: ("Sarah", None, None)}
    return repo


@pytest.fixture
def mock_settings_repo() -> AsyncMock:
    """A settings repository; a contact link never needs a timezone."""
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


async def link(
    service: TaskService,
    transaction: AsyncMock,
    *,
    user_id: str = USER_ID,
    task_id: int = TASK_ID,
    contact_id: int = CONTACT_ID,
) -> bool:
    """Call ``link_contact`` with the ordinary arguments, overriding as needed."""
    return await service.link_contact(
        user_id=user_id,
        task_id=task_id,
        contact_id=contact_id,
        transaction=transaction,
    )


async def unlink(
    service: TaskService,
    transaction: AsyncMock,
    *,
    user_id: str = USER_ID,
    task_id: int = TASK_ID,
    contact_id: int = CONTACT_ID,
) -> bool:
    """Call ``unlink_contact`` with the ordinary arguments, overriding as needed."""
    return await service.unlink_contact(
        user_id=user_id,
        task_id=task_id,
        contact_id=contact_id,
        transaction=transaction,
    )


@pytest.mark.unit
class TestLinkingAContact:
    """One contact, one batched write, no relationship data of any kind."""

    @pytest.mark.asyncio
    async def test_writes_the_link_through_the_batched_call(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The single-link surface reuses the batch write rather than a second path."""
        assert await link(service, mock_transaction) is True

        mock_task_repo.add_contacts.assert_awaited_once_with(
            TASK_ID, [CONTACT_ID], USER_ID
        )

    @pytest.mark.asyncio
    async def test_linking_again_is_accepted_and_reports_no_change(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Idempotency: the repeat succeeds, and says a row was already there.

        The boolean is the *only* difference between the two calls. A surface is
        free to ignore it — an idempotent operation should look identical to its
        caller — but an agent that wants to know whether it changed anything can.
        """
        mock_task_repo.add_contacts.return_value = []

        assert await link(service, mock_transaction) is False

    @pytest.mark.asyncio
    async def test_proves_the_contact_exists_before_writing(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_contact_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """An unknown contact fails the link rather than being written blindly."""
        mock_contact_repo.find_names_by_ids.return_value = {}

        with pytest.raises(ContactNotFoundError) as exc_info:
            await link(service, mock_transaction, contact_id=404)

        assert exc_info.value.contact_id == 404
        assert exc_info.value.status_code == 404
        mock_task_repo.add_contacts.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_journal_or_timezone_is_involved(
        self,
        service: TaskService,
        mock_journal_repo: AsyncMock,
        mock_settings_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """A contact link is not a journal link and needs no local day.

        Asserted on ``mock_calls`` rather than on named methods: naming them
        would pass for any method somebody adds to either port later, which is
        the opposite of what "no journal is involved" is meant to guarantee.
        """
        await link(service, mock_transaction)

        assert mock_journal_repo.mock_calls == []
        assert mock_settings_repo.mock_calls == []

    @pytest.mark.asyncio
    async def test_no_status_is_read_or_written(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Links are editable in any status, so no status is consulted at all."""
        await link(service, mock_transaction)

        mock_task_repo.save.assert_not_awaited()
        mock_task_repo.find_by_id_for_update.assert_not_awaited()


@pytest.mark.unit
class TestUnlinkingAContact:
    """Removal is idempotent and asks nothing of the contact."""

    @pytest.mark.asyncio
    async def test_removes_the_link(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        assert await unlink(service, mock_transaction) is True

        mock_task_repo.remove_contact.assert_awaited_once_with(
            TASK_ID, CONTACT_ID, USER_ID
        )

    @pytest.mark.asyncio
    async def test_unlinking_again_reports_no_change(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """A link that was not there is not an error — ``DELETE`` is idempotent."""
        mock_task_repo.remove_contact.return_value = False

        assert await unlink(service, mock_transaction) is False

    @pytest.mark.asyncio
    async def test_does_not_require_the_contact_to_still_exist(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_contact_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The deliberate asymmetry with linking.

        ``task_contacts.contact_id`` cascades, so a deleted contact's links are
        already gone; requiring the contact here would make the cleanup path
        fail for the one case the phase's fourth criterion exists to protect.
        """
        mock_task_repo.remove_contact.return_value = False

        assert await unlink(service, mock_transaction, contact_id=404) is False

        assert mock_contact_repo.mock_calls == []

    @pytest.mark.asyncio
    async def test_no_journal_or_timezone_is_involved(
        self,
        service: TaskService,
        mock_journal_repo: AsyncMock,
        mock_settings_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        await unlink(service, mock_transaction)

        assert mock_journal_repo.mock_calls == []
        assert mock_settings_repo.mock_calls == []


# The "editable in any status" rule has **no unit test here, deliberately.**
# A parametrised one would have to stub a status somewhere the service never
# reads — it calls no status-bearing method at all — so the three runs would be
# byte-identical and the test would pass however the rule regressed. What the
# rule really rests on is the *absence* of a status read, which
# ``test_no_status_is_read_or_written`` asserts directly, and the three real
# matrices against a database in
# ``tests/integration/tasks/test_task_contact_links_integration.py``,
# ``tests/integration/api/test_task_endpoints.py`` and
# ``tests/integration/mcp/test_task_tools_mcp.py``, each of which seeds a task in
# every status and checks the stored status is unmoved afterwards.


@pytest.mark.unit
class TestUnreachableTasks:
    """Somebody else's task and a nonexistent one are one answer, on both calls.

    These are narrow on purpose. Ownership itself belongs to the owner-scoped
    repository, which is where it is tested against a real second user's rows;
    what is asserted here is only that the service **passes the acting user
    through and adds no branch of its own** — it never re-wraps, softens or
    enriches the repository's answer, which is what would let a message start
    saying whether a task was absent or somebody else's.
    """

    @pytest.mark.asyncio
    async def test_link_reports_an_unknown_task_as_not_found(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Ownership is the repository's, so the service adds no branch of its own."""
        mock_task_repo.add_contacts.side_effect = TaskNotFoundError(TASK_ID)

        with pytest.raises(TaskNotFoundError) as exc_info:
            await link(service, mock_transaction)

        assert exc_info.value.task_id == TASK_ID

    @pytest.mark.asyncio
    async def test_link_to_another_users_task_is_indistinguishable(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The owner-scoped guard returns nothing, so the message cannot leak."""
        mock_task_repo.add_contacts.side_effect = TaskNotFoundError(TASK_ID)

        with pytest.raises(TaskNotFoundError) as exc_info:
            await link(service, mock_transaction, user_id=OTHER_USER_ID)

        assert str(exc_info.value) == str(TaskNotFoundError(TASK_ID))
        mock_task_repo.add_contacts.assert_awaited_once_with(
            TASK_ID, [CONTACT_ID], OTHER_USER_ID
        )

    @pytest.mark.asyncio
    async def test_unlink_reports_an_unknown_task_as_not_found(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        mock_task_repo.remove_contact.side_effect = TaskNotFoundError(TASK_ID)

        with pytest.raises(TaskNotFoundError) as exc_info:
            await unlink(service, mock_transaction, user_id=OTHER_USER_ID)

        assert str(exc_info.value) == str(TaskNotFoundError(TASK_ID))


@pytest.mark.unit
class TestAVanishedContact:
    """The Phase 4 race, kept alive through the batched write."""

    @pytest.mark.asyncio
    async def test_a_contact_deleted_after_the_check_keeps_its_404(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_contact_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The contact existed a statement ago; the caller was promised a 404.

        The insert runs inside a ``SAVEPOINT`` precisely so this recovery read is
        possible: a foreign-key violation aborts the enclosing transaction in
        PostgreSQL, and without the savepoint the lookup that names *which*
        contact vanished could not run at all.
        """
        mock_task_repo.add_contacts.side_effect = integrity_error(
            "task_contacts_contact_id_fkey"
        )
        mock_contact_repo.find_names_by_ids.side_effect = [
            {CONTACT_ID: ("Sarah", None, None)},
            {},
        ]

        with pytest.raises(ContactNotFoundError) as exc_info:
            await link(service, mock_transaction)

        assert exc_info.value.contact_id == CONTACT_ID

    @pytest.mark.asyncio
    async def test_a_violation_naming_anything_else_is_re_raised(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """A genuine bug must not be dressed up as an actionable rejection."""
        mock_task_repo.add_contacts.side_effect = integrity_error("task_contacts_pkey")

        with pytest.raises(IntegrityError):
            await link(service, mock_transaction)

    @pytest.mark.asyncio
    async def test_a_contact_violation_with_nothing_missing_is_re_raised(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_contact_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """If every contact is still there, the 404 would be a lie.

        Mapping unconditionally would name an arbitrary id and send the caller
        looking for a contact that exists. The violation is re-raised instead, so
        whatever really went wrong is visible.
        """
        mock_task_repo.add_contacts.side_effect = integrity_error(
            "task_contacts_contact_id_fkey"
        )

        with pytest.raises(IntegrityError):
            await link(service, mock_transaction)

        # The recovery read ran and found the contact still there, which is what
        # makes re-raising the honest answer rather than a guess at an id.
        assert mock_contact_repo.find_names_by_ids.await_count == 2
