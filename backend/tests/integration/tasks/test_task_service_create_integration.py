"""Integration tests for ``TaskService.create_task`` against real PostgreSQL.

The unit tests own the invariant logic. What only a real database can show is
that the logic is wired to real data:

- **ownership is enforced by the query, not by a comparison** — another user's
  journal is unreachable through the owner-scoped read, and reads exactly like a
  journal that never existed;
- **the future-dated rule uses the timezone stored in ``user_settings``**,
  decided on the user's local day where a UTC reading disagrees;
- **the write is one unit of work** — a task and its contact links land together,
  and a rejected invariant leaves nothing behind at all;
- **the check happens only when the anchor is set**, which is what makes a
  lapsed task reachable in the first place.

Journals whose *date* is asserted are seeded at fixed instants with an injected
``now``; journals that merely need to be future-dated use the ``days_offset``
helper against the real clock.
"""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from core_shared.models.tasks import (
    Task,
    TaskAnchorJournalNotFoundError,
    TaskDueJournalNotFutureError,
    TaskStatus,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_repository import SqlContactRepository
from app.core.contacts.models.exceptions import ContactNotFoundError
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_date_resolver import JournalDateResolver
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.settings.models import UserSettings
from app.core.tasks.adapters.sql.task_repository import SqlTaskRepository
from app.core.tasks.services.task_service import TaskService
from tests.integration.tasks.task_seeding import (
    COUNT_CONTACT_LINKS,
    COUNT_TASKS,
    OTHER_USER_ID,
    USER_ID,
    count,
    create_contact,
    create_journal,
    make_task_container,
)

# 06:00 on 6 August in Sydney (+10) — the 5th is still running in UTC.
SYDNEY_MORNING = datetime(2026, 8, 5, 20, 0, tzinfo=UTC)
# 20:00 on the *same* Sydney day, and the 6th in UTC as well.
SYDNEY_EVENING = datetime(2026, 8, 6, 10, 0, tzinfo=UTC)


@pytest.mark.integration
class TestCreateTaskAgainstRealJournals:
    """A created task is a real row anchored to real journals."""

    async def test_persists_the_task_and_its_anchors(
        self,
        service: TaskService,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The row survives the round trip with both anchors and the default status."""
        creating_id, due_id = task_anchors

        created = await service.create_task(
            user_id=USER_ID,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="print out the permit",
            transaction=async_connection,
        )

        assert created.id is not None
        assert created.created_at is not None
        persisted = await task_repository.find_by_id(created.id, USER_ID)
        assert persisted is not None
        assert persisted.text == "print out the permit"
        assert persisted.creating_journal_id == creating_id
        assert persisted.due_journal_id == due_id
        assert persisted.status == TaskStatus.NOT_DONE

    async def test_links_contacts_in_the_same_unit_of_work(
        self,
        service: TaskService,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """The task and its links are both visible once the create returns."""
        creating_id, due_id = task_anchors
        sarah = await create_contact(async_connection, first_name="Sarah")
        tom = await create_contact(async_connection, first_name="Tom")

        created = await service.create_task(
            user_id=USER_ID,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="return Sarah's book",
            contact_ids=[sarah, tom],
            transaction=async_connection,
        )

        assert created.id is not None
        assert await task_repository.list_contact_ids(created.id, USER_ID) == [
            sarah,
            tom,
        ]

    async def test_accepts_the_same_journal_as_both_anchors(
        self,
        service: TaskService,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """Invariant 6 against a real row: one future journal can be both anchors."""
        journal_id = await create_journal(
            journal_repository, title="Next week's meeting", days_offset=7
        )

        created = await service.create_task(
            user_id=USER_ID,
            creating_journal_id=journal_id,
            due_journal_id=journal_id,
            text="bring the permit",
            transaction=async_connection,
        )

        assert created.creating_journal_id == created.due_journal_id == journal_id


@pytest.mark.integration
class TestTheWriteIsOneUnitOfWork:
    """A failure *after* the first write takes the whole create with it.

    Every other rejection in this file happens before anything is written, so
    "no partial task" holds for them structurally, whether or not the service
    opens a unit of work. This is the one case that distinguishes the two: the
    task row exists when the link fails, so only the ``@transactional`` rollback
    can remove it. Deleting the decorator makes this test — and only this test —
    fail.
    """

    async def test_a_failure_while_linking_rolls_the_task_back(
        self,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        user_settings_repository: SqlUserSettingsRepository,
        task_anchors: tuple[int, int],
    ):
        """The task is inserted, the link raises, and the row is gone again."""
        creating_id, due_id = task_anchors
        sarah = await create_contact(async_connection, first_name="Sarah")

        class _FailingLinkRepository(SqlTaskRepository):
            async def add_contacts(
                self, task_id: int, contact_ids: list[int], user_id: str
            ) -> list[int]:
                raise RuntimeError("the link write failed")

        service = TaskService(
            task_repo=_FailingLinkRepository(async_connection),
            journal_repo=journal_repository,
            contact_repo=SqlContactRepository(async_connection),
            date_resolver=JournalDateResolver(
                user_settings_repo=user_settings_repository
            ),
        )

        with pytest.raises(RuntimeError):
            await service.create_task(
                user_id=USER_ID,
                creating_journal_id=creating_id,
                due_journal_id=due_id,
                text="return Sarah's book",
                contact_ids=[sarah],
                transaction=async_connection,
            )

        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 0


@pytest.mark.integration
class TestAnAnchorThatVanishesMidCreate:
    """A journal deleted between the anchor check and the insert still 404s.

    The anchor checks are a plain read, so the foreign key is what catches a
    journal deleted in the window before the insert. Left alone that surfaces a
    raw ``IntegrityError`` — a 500 where the caller was promised a 404. The
    error is raised by real PostgreSQL here rather than hand-built, so the
    mapping is proved against the message the database actually produces.
    """

    async def test_a_deleted_due_journal_still_reports_the_domain_error(
        self,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        user_settings_repository: SqlUserSettingsRepository,
        task_anchors: tuple[int, int],
    ):
        """The due anchor is named, not leaked as an integrity error."""
        creating_id, due_id = task_anchors

        class _VanishingJournalRepository(SqlTaskRepository):
            async def save(self, task: Task) -> Task:
                await async_connection.execute(
                    text("DELETE FROM journals WHERE id = :id"), {"id": due_id}
                )
                return await super().save(task)

        service = TaskService(
            task_repo=_VanishingJournalRepository(async_connection),
            journal_repo=journal_repository,
            contact_repo=SqlContactRepository(async_connection),
            date_resolver=JournalDateResolver(
                user_settings_repo=user_settings_repository
            ),
        )

        with pytest.raises(TaskAnchorJournalNotFoundError) as exc_info:
            await service.create_task(
                user_id=USER_ID,
                creating_journal_id=creating_id,
                due_journal_id=due_id,
                text="print the permit",
                transaction=async_connection,
            )

        assert exc_info.value.anchor == "due"
        assert exc_info.value.journal_id == due_id
        assert exc_info.value.status_code == 404

    async def test_a_deleted_creating_journal_names_that_anchor(
        self,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        user_settings_repository: SqlUserSettingsRepository,
        task_anchors: tuple[int, int],
    ):
        """Each anchor is told apart by the column the violation names."""
        creating_id, due_id = task_anchors

        class _VanishingJournalRepository(SqlTaskRepository):
            async def save(self, task: Task) -> Task:
                await async_connection.execute(
                    text("DELETE FROM journals WHERE id = :id"), {"id": creating_id}
                )
                return await super().save(task)

        service = TaskService(
            task_repo=_VanishingJournalRepository(async_connection),
            journal_repo=journal_repository,
            contact_repo=SqlContactRepository(async_connection),
            date_resolver=JournalDateResolver(
                user_settings_repo=user_settings_repository
            ),
        )

        with pytest.raises(TaskAnchorJournalNotFoundError) as exc_info:
            await service.create_task(
                user_id=USER_ID,
                creating_journal_id=creating_id,
                due_journal_id=due_id,
                text="print the permit",
                transaction=async_connection,
            )

        assert exc_info.value.anchor == "creating"
        assert exc_info.value.journal_id == creating_id


@pytest.mark.integration
class TestOwnershipIsAnInvariant:
    """A task can never span owners, and rejection leaks nothing."""

    async def test_rejects_another_users_journal_as_the_due_anchor(
        self,
        service: TaskService,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """A real journal belonging to somebody else cannot become a due anchor."""
        creating_id = await create_journal(journal_repository, title="Mine")
        theirs = await create_journal(
            journal_repository,
            title="Theirs",
            days_offset=7,
            user_id=OTHER_USER_ID,
        )

        with pytest.raises(TaskAnchorJournalNotFoundError) as exc_info:
            await service.create_task(
                user_id=USER_ID,
                creating_journal_id=creating_id,
                due_journal_id=theirs,
                text="reach across owners",
                transaction=async_connection,
            )

        assert exc_info.value.anchor == "due"
        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 0

    async def test_rejects_another_users_journal_as_the_creating_anchor(
        self,
        service: TaskService,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """The creating anchor is owner-scoped too, not just the due one."""
        theirs = await create_journal(
            journal_repository, title="Theirs", user_id=OTHER_USER_ID
        )
        due_id = await create_journal(
            journal_repository, title="Mine, later", days_offset=7
        )

        with pytest.raises(TaskAnchorJournalNotFoundError) as exc_info:
            await service.create_task(
                user_id=USER_ID,
                creating_journal_id=theirs,
                due_journal_id=due_id,
                text="reach across owners",
                transaction=async_connection,
            )

        assert exc_info.value.anchor == "creating"
        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 0

    async def test_a_foreign_journal_is_indistinguishable_from_a_missing_one(
        self,
        service: TaskService,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """Existence and ownership answer with the same error, as the port does."""
        creating_id = await create_journal(journal_repository, title="Mine")
        theirs = await create_journal(
            journal_repository,
            title="Theirs",
            days_offset=7,
            user_id=OTHER_USER_ID,
        )

        async def rejection(due_journal_id: int) -> TaskAnchorJournalNotFoundError:
            with pytest.raises(TaskAnchorJournalNotFoundError) as exc_info:
                await service.create_task(
                    user_id=USER_ID,
                    creating_journal_id=creating_id,
                    due_journal_id=due_journal_id,
                    text="a commitment",
                    transaction=async_connection,
                )
            return exc_info.value

        foreign = await rejection(theirs)
        absent = await rejection(999_999)

        assert type(foreign) is type(absent)
        assert foreign.status_code == absent.status_code
        assert str(foreign).replace(str(theirs), "") == str(absent).replace(
            "999999", ""
        )


@pytest.mark.integration
class TestFutureDatedAgainstStoredSettings:
    """The rule is judged on the user's local day, from the stored timezone."""

    async def test_decides_on_the_users_local_day_where_utc_disagrees(
        self,
        service: TaskService,
        journal_repository: SqlJournalRepository,
        user_settings_repository: SqlUserSettingsRepository,
        async_connection: AsyncConnection,
    ):
        """Sydney calls this journal today and rejects it; UTC would accept it.

        At 20:00Z on 5 August it is already the 6th in Sydney, so a journal
        starting 10:00Z on the 6th is *today* there — while UTC still reads
        "now" as the 5th and the journal as the 6th, which is tomorrow.
        """
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone="Australia/Sydney")
        )
        creating_id = await create_journal(journal_repository, title="Where it arose")
        due_id = await create_journal(
            journal_repository, title="Later today in Sydney", start=SYDNEY_EVENING
        )

        with pytest.raises(TaskDueJournalNotFutureError) as exc_info:
            await service.create_task(
                user_id=USER_ID,
                creating_journal_id=creating_id,
                due_journal_id=due_id,
                text="too soon",
                transaction=async_connection,
                now=SYDNEY_MORNING,
            )

        assert exc_info.value.journal_date == date(2026, 8, 6)
        assert exc_info.value.today == date(2026, 8, 6)
        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 0

    async def test_falls_back_to_utc_for_a_user_with_no_settings_row(
        self,
        service: TaskService,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """Without a stored timezone the same pair is decided in UTC — and accepted."""
        user_id = f"no-settings-{uuid4()}"
        creating_id = await create_journal(
            journal_repository, title="Where it arose", user_id=user_id
        )
        due_id = await create_journal(
            journal_repository,
            title="Tomorrow in UTC",
            start=SYDNEY_EVENING,
            user_id=user_id,
        )

        created = await service.create_task(
            user_id=user_id,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="fine in UTC",
            transaction=async_connection,
            now=SYDNEY_MORNING,
        )

        assert created.id is not None

    async def test_the_rule_is_applied_only_when_the_anchor_is_set(
        self,
        service: TaskService,
        task_repository: SqlTaskRepository,
        journal_repository: SqlJournalRepository,
        async_connection: AsyncConnection,
    ):
        """A task whose due journal has since passed is lapsed, not invalid.

        This is the recipe Phase 22's lapsed fixtures need: create against a
        backdated ``now``, so the due journal was future *then* and is past now.
        Nothing re-validates on read, so the task remains reachable.
        """
        creating_id = await create_journal(journal_repository, title="Where it arose")
        due_id = await create_journal(
            journal_repository, title="Already gone", days_offset=-3
        )

        created = await service.create_task(
            user_id=USER_ID,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="a commitment that slid",
            transaction=async_connection,
            now=datetime.now(UTC) - timedelta(days=10),
        )

        assert created.id is not None
        persisted = await task_repository.find_by_id(created.id, USER_ID)
        assert persisted is not None
        assert persisted.status == TaskStatus.NOT_DONE


@pytest.mark.integration
class TestContactLinks:
    """Contacts must exist before they can be referenced.

    The phase's acceptance criterion asks for a contact *owned by another user*
    to be rejected. The ``contacts`` table has no owner column — see the Phase 4
    divergence in the iteration document — so the enforceable rule, and the one
    tested here, is existence.
    """

    async def test_rejects_a_contact_that_does_not_exist(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """An unknown contact id fails the create and writes nothing at all."""
        creating_id, due_id = task_anchors

        with pytest.raises(ContactNotFoundError) as exc_info:
            await service.create_task(
                user_id=USER_ID,
                creating_journal_id=creating_id,
                due_journal_id=due_id,
                text="return the book",
                contact_ids=[999_999],
                transaction=async_connection,
            )

        assert exc_info.value.contact_id == 999_999
        assert await count(async_connection, COUNT_TASKS, {"user_id": USER_ID}) == 0
        assert await count(async_connection, COUNT_CONTACT_LINKS, {}) == 0

    async def test_rejects_the_whole_create_when_one_contact_is_unknown(
        self,
        service: TaskService,
        async_connection: AsyncConnection,
        task_anchors: tuple[int, int],
    ):
        """A valid contact alongside an invalid one does not get linked anyway."""
        creating_id, due_id = task_anchors
        sarah = await create_contact(async_connection, first_name="Sarah")

        with pytest.raises(ContactNotFoundError):
            await service.create_task(
                user_id=USER_ID,
                creating_journal_id=creating_id,
                due_journal_id=due_id,
                text="return the book",
                contact_ids=[sarah, 999_999],
                transaction=async_connection,
            )

        assert await count(async_connection, COUNT_CONTACT_LINKS, {}) == 0


@pytest.mark.integration
class TestDependencyInjection:
    """The service is reachable through the container, not just importable."""

    async def test_task_provider_supplies_the_service(
        self, async_connection: AsyncConnection
    ):
        """Resolving it wires all four collaborators on the request connection."""
        container = make_task_container(async_connection)
        try:
            async with container() as request_container:
                service = await request_container.get(TaskService)

                assert isinstance(service, TaskService)
        finally:
            await container.close()
