"""Unit tests for task creation and the specification's core invariants.

Every invariant the specification calls *absolute* is enforced in
:class:`TaskService`, so REST and MCP inherit it rather than re-implementing it.
These tests pin each one against mocked repositories:

1-3. both anchors are present and neither can ever be absent
4.   the due journal is future-dated **at the moment it is set**
5.   the due journal exists — and, per the phase, belongs to the acting user
6.   the creating and due journals may be the same journal

The date cases use fixed instants and an injected ``now`` rather than offsets
from the real clock, for the reason Phase 3 recorded: the behaviour under test is
the instant-to-local-date derivation, and there is no ``freezegun`` in this repo.
``JournalDateResolver`` is the **real** collaborator over a mocked settings
repository, because the timezone rule is part of the behaviour being tested.
"""

import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from core_shared.models.history import Provenance
from core_shared.models.journals import EventDateRange, Journal
from core_shared.models.tasks import (
    Task,
    TaskAnchorJournalNotFoundError,
    TaskDueJournalNotFutureError,
    TaskStatus,
    TaskValidationError,
)
from sqlalchemy.exc import IntegrityError

from app.core.contacts.models.exceptions import ContactNotFoundError
from app.core.journal.services.journal_date_resolver import JournalDateResolver
from app.core.tasks.services.task_service import TaskService
from tests.unit.tasks.task_doubles import published_events

USER_ID = "test-user-123"

CREATING_JOURNAL_ID = 11
DUE_JOURNAL_ID = 22

SYDNEY = "Australia/Sydney"

# A fixed "now" and the local dates around it, so every date case reads as
# arithmetic against one instant rather than against the wall clock.
NOW = datetime.datetime(2026, 8, 5, 12, 0, tzinfo=datetime.UTC)
TODAY = datetime.date(2026, 8, 5)
TOMORROW = datetime.date(2026, 8, 6)
YESTERDAY = datetime.date(2026, 8, 4)


def at(day: datetime.date, hour: int = 9) -> datetime.datetime:
    """A UTC instant on ``day``, the way the database hands timestamps back."""
    return datetime.datetime(day.year, day.month, day.day, hour, tzinfo=datetime.UTC)


def make_journal(
    journal_id: int,
    start: datetime.datetime,
    end: datetime.datetime | None = None,
    *,
    title: str = "A journal",
) -> Journal:
    """A journal spanning ``start`` to ``end`` (default: an instantaneous range)."""
    return Journal(
        id=journal_id,
        user_id=USER_ID,
        title=title,
        content="content",
        event_date_range=EventDateRange(start=start, end=end or start),
    )


@pytest.fixture
def creating_journal() -> Journal:
    """The journal the commitment arose in — its date is irrelevant."""
    return make_journal(CREATING_JOURNAL_ID, at(YESTERDAY), title="Where it arose")


@pytest.fixture
def due_journal() -> Journal:
    """A future-dated journal, valid as a due anchor."""
    return make_journal(DUE_JOURNAL_ID, at(TOMORROW), title="Where it matters")


@pytest.fixture
def mock_task_repo() -> AsyncMock:
    """A task repository whose save assigns an id, as the real one does."""
    repo = AsyncMock()

    async def save(task: Task) -> Task:
        return Task(
            id=task.id or 99,
            user_id=task.user_id,
            text=task.text,
            creating_journal_id=task.creating_journal_id,
            due_journal_id=task.due_journal_id,
            status=task.status,
        )

    repo.save.side_effect = save

    async def add_contacts(_task_id: int, contact_ids: list[int], _user_id: str):
        return list(contact_ids)

    repo.add_contacts.side_effect = add_contacts
    return repo


@pytest.fixture
def mock_journal_repo(creating_journal: Journal, due_journal: Journal) -> AsyncMock:
    """A journal repository holding both anchors, owner-scoped like the real one."""
    repo = AsyncMock()
    repo.find_by_ids_for_user.return_value = [creating_journal, due_journal]
    return repo


@pytest.fixture
def mock_contact_repo() -> AsyncMock:
    """A contact repository that knows no contacts until a test says otherwise."""
    repo = AsyncMock()
    repo.find_names_by_ids.return_value = {}
    return repo


@pytest.fixture
def mock_settings_repo() -> AsyncMock:
    """A settings repository reporting UTC unless a test configures otherwise."""
    repo = AsyncMock()
    repo.get_timezone.return_value = "UTC"
    return repo


@pytest.fixture
def date_resolver(mock_settings_repo: AsyncMock) -> JournalDateResolver:
    """The real resolver: the future-dated rule is part of what is under test."""
    return JournalDateResolver(mock_settings_repo)


@pytest.fixture
def mock_event_publisher() -> AsyncMock:
    """The outbox publisher, recording what the creation announced."""
    return AsyncMock()


@pytest.fixture
def mock_transaction() -> AsyncMock:
    """A stand-in connection; ``@transactional`` runs unwrapped for a non-real one."""
    return AsyncMock()


@pytest.fixture
def service(
    mock_task_repo: AsyncMock,
    mock_journal_repo: AsyncMock,
    mock_contact_repo: AsyncMock,
    date_resolver: JournalDateResolver,
    mock_event_publisher: AsyncMock,
) -> TaskService:
    """The service under test."""
    return TaskService(
        task_repo=mock_task_repo,
        journal_repo=mock_journal_repo,
        contact_repo=mock_contact_repo,
        date_resolver=date_resolver,
        event_publisher=mock_event_publisher,
    )


async def create(
    service: TaskService,
    transaction: AsyncMock,
    *,
    text: str = "return Sarah's book",
    creating_journal_id: int = CREATING_JOURNAL_ID,
    due_journal_id: int = DUE_JOURNAL_ID,
    contact_ids: list[int] | None = None,
    now: datetime.datetime | None = NOW,
    source: Provenance = Provenance.SYSTEM,
    changed_by: str = "system",
) -> Task:
    """Call ``create_task`` with the ordinary arguments, overriding as needed."""
    return await service.create_task(
        user_id=USER_ID,
        creating_journal_id=creating_journal_id,
        due_journal_id=due_journal_id,
        text=text,
        contact_ids=contact_ids,
        transaction=transaction,
        now=now,
        source=source,
        changed_by=changed_by,
    )


@pytest.mark.unit
class TestCreateTask:
    """The happy paths: what a created task is, and what it links to."""

    @pytest.mark.asyncio
    async def test_persists_a_not_done_task_with_both_anchors(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """A new task carries its text, both anchors and the default status."""
        result = await create(service, mock_transaction)

        saved = mock_task_repo.save.await_args.args[0]
        assert saved.user_id == USER_ID
        assert saved.text == "return Sarah's book"
        assert saved.creating_journal_id == CREATING_JOURNAL_ID
        assert saved.due_journal_id == DUE_JOURNAL_ID
        assert saved.status == TaskStatus.NOT_DONE
        assert saved.id is None
        assert result.id == 99

    @pytest.mark.asyncio
    async def test_returns_the_persisted_task(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The caller gets the row the repository wrote, not the entity it built."""
        persisted = Task(
            id=7,
            user_id=USER_ID,
            text="print the permit",
            creating_journal_id=CREATING_JOURNAL_ID,
            due_journal_id=DUE_JOURNAL_ID,
        )
        mock_task_repo.save.side_effect = None
        mock_task_repo.save.return_value = persisted

        assert await create(service, mock_transaction) is persisted

    @pytest.mark.asyncio
    async def test_links_each_contact_to_the_saved_task(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_contact_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Optional contacts become link rows against the id the save assigned.

        **One call, not one per contact.** Phase 4 wrote them in a loop and each
        ``add_contact`` re-proved task ownership with its own
        ``SELECT … FOR KEY SHARE``, so N contacts cost 2N statements to link a
        task the service had created three lines earlier. Phase 11 owns the
        contact-link surface and batched it; asserting the *shape* of the call
        here is what stops the loop coming back.
        """
        mock_contact_repo.find_names_by_ids.return_value = {
            3: ("Sarah", None, None),
            5: ("Tom", None, None),
        }

        await create(service, mock_transaction, contact_ids=[3, 5])

        mock_task_repo.add_contacts.assert_awaited_once_with(99, [3, 5], USER_ID)

    @pytest.mark.asyncio
    async def test_creates_no_links_without_contacts(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_contact_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Contacts are optional: no ids means no link rows and no contact read."""
        await create(service, mock_transaction, contact_ids=None)

        mock_task_repo.add_contacts.assert_not_awaited()
        mock_contact_repo.find_names_by_ids.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_deduplicates_contacts_keeping_first_mention_order(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_contact_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """A repeated contact is linked once, in the order it was first named."""
        mock_contact_repo.find_names_by_ids.return_value = {
            3: ("Sarah", None, None),
            5: ("Tom", None, None),
        }

        await create(service, mock_transaction, contact_ids=[5, 3, 5])

        assert mock_task_repo.add_contacts.await_args.args[1] == [5, 3]

    @pytest.mark.asyncio
    async def test_checks_every_contact_in_one_call(
        self,
        service: TaskService,
        mock_contact_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Contact existence is one batched read, never one query per contact."""
        mock_contact_repo.find_names_by_ids.return_value = {
            3: ("Sarah", None, None),
            5: ("Tom", None, None),
        }

        await create(service, mock_transaction, contact_ids=[3, 5])

        mock_contact_repo.find_names_by_ids.assert_awaited_once_with([3, 5])

    @pytest.mark.asyncio
    async def test_accepts_the_same_journal_as_both_anchors(
        self,
        service: TaskService,
        mock_journal_repo: AsyncMock,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
        due_journal: Journal,
    ) -> None:
        """Invariant 6: creating and due may be one journal, if it is future-dated."""
        mock_journal_repo.find_by_ids_for_user.return_value = [due_journal]

        await create(
            service,
            mock_transaction,
            creating_journal_id=DUE_JOURNAL_ID,
            due_journal_id=DUE_JOURNAL_ID,
        )

        saved = mock_task_repo.save.await_args.args[0]
        assert saved.creating_journal_id == saved.due_journal_id == DUE_JOURNAL_ID
        assert mock_journal_repo.find_by_ids_for_user.await_args.args[1] == [
            DUE_JOURNAL_ID
        ]


@pytest.mark.unit
class TestAnchorInvariants:
    """Invariants 1-3 and 5: both anchors, and they must be the user's own."""

    @pytest.mark.asyncio
    async def test_rejects_a_missing_creating_journal(
        self,
        service: TaskService,
        mock_journal_repo: AsyncMock,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
        due_journal: Journal,
    ) -> None:
        """No creating journal, no task — and the error names that anchor."""
        mock_journal_repo.find_by_ids_for_user.return_value = [due_journal]

        with pytest.raises(TaskAnchorJournalNotFoundError) as exc_info:
            await create(service, mock_transaction)

        assert exc_info.value.anchor == "creating"
        assert exc_info.value.journal_id == CREATING_JOURNAL_ID
        assert exc_info.value.status_code == 404
        mock_task_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rejects_a_missing_due_journal(
        self,
        service: TaskService,
        mock_journal_repo: AsyncMock,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
        creating_journal: Journal,
    ) -> None:
        """Invariant 5: the due journal must be an existing journal."""
        mock_journal_repo.find_by_ids_for_user.return_value = [creating_journal]

        with pytest.raises(TaskAnchorJournalNotFoundError) as exc_info:
            await create(service, mock_transaction)

        assert exc_info.value.anchor == "due"
        assert exc_info.value.journal_id == DUE_JOURNAL_ID
        mock_task_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_names_the_creating_anchor_when_neither_exists(
        self,
        service: TaskService,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """With both anchors missing the report is deterministic, not arbitrary."""
        mock_journal_repo.find_by_ids_for_user.return_value = []

        with pytest.raises(TaskAnchorJournalNotFoundError) as exc_info:
            await create(service, mock_transaction)

        assert exc_info.value.anchor == "creating"

    @pytest.mark.asyncio
    async def test_resolves_both_anchors_through_the_owner_scoped_read(
        self,
        service: TaskService,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Ownership is an invariant: the lookup is scoped to the acting user.

        One batched call answers existence and ownership together, so another
        user's journal is unreachable rather than merely rejected later.
        """
        await create(service, mock_transaction)

        mock_journal_repo.find_by_ids_for_user.assert_awaited_once_with(
            USER_ID, [CREATING_JOURNAL_ID, DUE_JOURNAL_ID]
        )
        mock_journal_repo.find_by_id.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_does_not_attribute_an_unreachable_anchor_to_ownership(
        self,
        service: TaskService,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The message states the constraint but never says which half failed.

        Naming the constraint — a journal must exist *and* be yours — is what
        makes the error actionable for someone who picked a journal they cannot
        use. What would leak is *attribution*: telling the user that this
        particular journal is somebody else's answers a question about another
        user's data. The integration suite pins the stronger form of the same
        property, that a foreign journal and an absent one produce an identical
        message.
        """
        mock_journal_repo.find_by_ids_for_user.return_value = []

        with pytest.raises(TaskAnchorJournalNotFoundError) as exc_info:
            await create(service, mock_transaction)

        message = str(exc_info.value).lower()
        for attribution in (
            "another user",
            "someone else",
            "not yours",
            "permission",
            "forbidden",
        ):
            assert attribution not in message

    @pytest.mark.asyncio
    async def test_rejects_empty_text_before_touching_a_repository(
        self,
        service: TaskService,
        mock_journal_repo: AsyncMock,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The entity's own rules run first, so no I/O is spent on a bad request."""
        with pytest.raises(TaskValidationError) as exc_info:
            await create(service, mock_transaction, text="   ")

        assert exc_info.value.field == "text"
        mock_journal_repo.find_by_ids_for_user.assert_not_awaited()
        mock_task_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rejects_an_absent_anchor_id(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Invariants 1-3: a task can never exist with only one anchor."""
        with pytest.raises(TaskValidationError) as exc_info:
            await create(service, mock_transaction, due_journal_id=0)

        assert exc_info.value.field == "due_journal_id"
        mock_task_repo.save.assert_not_awaited()


@pytest.mark.unit
class TestFutureDatedInvariant:
    """Invariant 4: the due journal's date must be in the future when it is set."""

    @pytest.mark.asyncio
    async def test_accepts_a_journal_dated_tomorrow(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The ordinary case: the commitment lands on a day still ahead."""
        await create(service, mock_transaction)

        mock_task_repo.save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rejects_a_journal_dated_today(
        self,
        service: TaskService,
        mock_journal_repo: AsyncMock,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
        creating_journal: Journal,
    ) -> None:
        """The boundary is strict: today is not the future (settled in Phase 3)."""
        today_journal = make_journal(DUE_JOURNAL_ID, at(TODAY, hour=23))
        mock_journal_repo.find_by_ids_for_user.return_value = [
            creating_journal,
            today_journal,
        ]

        with pytest.raises(TaskDueJournalNotFutureError) as exc_info:
            await create(service, mock_transaction)

        assert exc_info.value.journal_id == DUE_JOURNAL_ID
        assert exc_info.value.journal_date == TODAY
        assert exc_info.value.today == TODAY
        assert exc_info.value.status_code == 400
        mock_task_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rejects_a_journal_dated_yesterday(
        self,
        service: TaskService,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
        creating_journal: Journal,
    ) -> None:
        """A past journal cannot be a due anchor at the moment it is set."""
        mock_journal_repo.find_by_ids_for_user.return_value = [
            creating_journal,
            make_journal(DUE_JOURNAL_ID, at(YESTERDAY)),
        ]

        with pytest.raises(TaskDueJournalNotFutureError):
            await create(service, mock_transaction)

    @pytest.mark.asyncio
    async def test_rejects_a_multi_day_journal_that_has_already_started(
        self,
        service: TaskService,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
        creating_journal: Journal,
    ) -> None:
        """A journal is dated by its start: a trip in progress is past, not future."""
        straddling = make_journal(DUE_JOURNAL_ID, at(YESTERDAY), at(TOMORROW))
        mock_journal_repo.find_by_ids_for_user.return_value = [
            creating_journal,
            straddling,
        ]

        with pytest.raises(TaskDueJournalNotFutureError) as exc_info:
            await create(service, mock_transaction)

        assert exc_info.value.journal_date == YESTERDAY

    @pytest.mark.asyncio
    async def test_error_names_both_dates_so_the_user_can_act_on_it(
        self,
        service: TaskService,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
        creating_journal: Journal,
    ) -> None:
        """The message states the constraint, the journal's date and today's."""
        mock_journal_repo.find_by_ids_for_user.return_value = [
            creating_journal,
            make_journal(DUE_JOURNAL_ID, at(YESTERDAY)),
        ]

        with pytest.raises(TaskDueJournalNotFutureError) as exc_info:
            await create(service, mock_transaction)

        message = str(exc_info.value)
        assert str(YESTERDAY) in message
        assert str(TODAY) in message
        assert "future" in message.lower()

    @pytest.mark.asyncio
    async def test_judges_the_boundary_on_the_users_local_day_not_utc(
        self,
        service: TaskService,
        mock_journal_repo: AsyncMock,
        mock_settings_repo: AsyncMock,
        mock_transaction: AsyncMock,
        creating_journal: Journal,
    ) -> None:
        """A UTC reading would accept this journal; the Sydney reading rejects it.

        Sydney is +10 in August. 20:00Z on the 5th is already 06:00 on the 6th
        there, so today is the 6th — while UTC still says the 5th. A journal
        starting 10:00Z on the 6th is the 6th in both readings, which makes it
        *today* in Sydney (rejected) but *tomorrow* in UTC (accepted).
        """
        mock_settings_repo.get_timezone.return_value = SYDNEY
        mock_journal_repo.find_by_ids_for_user.return_value = [
            creating_journal,
            make_journal(
                DUE_JOURNAL_ID,
                datetime.datetime(2026, 8, 6, 10, 0, tzinfo=datetime.UTC),
            ),
        ]
        now = datetime.datetime(2026, 8, 5, 20, 0, tzinfo=datetime.UTC)

        with pytest.raises(TaskDueJournalNotFutureError) as exc_info:
            await create(service, mock_transaction, now=now)

        assert exc_info.value.journal_date == datetime.date(2026, 8, 6)
        assert exc_info.value.today == datetime.date(2026, 8, 6)

    @pytest.mark.asyncio
    async def test_accepts_the_mirror_of_the_local_day_boundary(
        self,
        service: TaskService,
        mock_journal_repo: AsyncMock,
        mock_settings_repo: AsyncMock,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
        creating_journal: Journal,
    ) -> None:
        """The mirror: the same UTC date as "now", but tomorrow in Sydney.

        20:00Z on the 5th is the 6th in Sydney, while "now" at 10:00Z is still
        the 5th there. UTC reads both as the 5th and would reject; Sydney reads
        the journal as tomorrow and accepts. The pair is decided the opposite
        way round by a UTC reading, which is the whole point of anchoring on the
        user's timezone.
        """
        mock_settings_repo.get_timezone.return_value = SYDNEY
        mock_journal_repo.find_by_ids_for_user.return_value = [
            creating_journal,
            make_journal(
                DUE_JOURNAL_ID,
                datetime.datetime(2026, 8, 5, 20, 0, tzinfo=datetime.UTC),
            ),
        ]
        now = datetime.datetime(2026, 8, 5, 10, 0, tzinfo=datetime.UTC)

        await create(service, mock_transaction, now=now)

        mock_task_repo.save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rejects_the_same_journal_when_it_is_not_future_dated(
        self,
        service: TaskService,
        mock_journal_repo: AsyncMock,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Invariant 6's proviso: same journal is allowed *if* invariant 4 holds.

        The anchors are de-duplicated before the read, so this is the case where
        an implementation could collapse the two roles and skip the date check
        along with the second lookup.
        """
        today_journal = make_journal(DUE_JOURNAL_ID, at(TODAY))
        mock_journal_repo.find_by_ids_for_user.return_value = [today_journal]

        with pytest.raises(TaskDueJournalNotFutureError):
            await create(
                service,
                mock_transaction,
                creating_journal_id=DUE_JOURNAL_ID,
                due_journal_id=DUE_JOURNAL_ID,
            )

        mock_task_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reads_the_users_timezone_once(
        self,
        service: TaskService,
        mock_settings_repo: AsyncMock,
        mock_contact_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """One settings read per create, however many journals are involved."""
        mock_contact_repo.find_names_by_ids.return_value = {
            3: ("Sarah", None, None),
            5: ("Tom", None, None),
        }

        await create(service, mock_transaction, contact_ids=[3, 5])

        mock_settings_repo.get_timezone.assert_awaited_once_with(USER_ID)

    @pytest.mark.asyncio
    async def test_reads_the_clock_once_when_no_instant_is_given(
        self,
        service: TaskService,
        mock_journal_repo: AsyncMock,
        mock_transaction: AsyncMock,
        creating_journal: Journal,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The decision and the error's "today" come from the same instant.

        Left to a bare ``now=None`` the predicate and the error would each read
        the clock, and a create landing on local midnight could be refused
        against one day while being told about another. Asserting the resolved
        instant reaches the predicate is what pins that, since the alternative —
        actually straddling midnight — is not something a test can arrange.
        """
        seen: list[datetime.datetime | None] = []

        def recording_is_future_dated(
            journal: Journal,
            tz: ZoneInfo,
            now: datetime.datetime | None = None,
        ) -> bool:
            seen.append(now)
            return False

        monkeypatch.setattr(
            "app.core.tasks.services.task_service.is_future_dated",
            recording_is_future_dated,
        )
        mock_journal_repo.find_by_ids_for_user.return_value = [
            creating_journal,
            make_journal(DUE_JOURNAL_ID, at(YESTERDAY)),
        ]

        with pytest.raises(TaskDueJournalNotFutureError) as exc_info:
            await create(service, mock_transaction, now=None)

        assert len(seen) == 1
        resolved = seen[0]
        assert resolved is not None, "the clock must be resolved before the predicate"
        # The settings mock reports UTC, so the error's "today" must be that very
        # instant's date — not a second, later reading of the clock.
        assert exc_info.value.today == resolved.astimezone(datetime.UTC).date()

    @pytest.mark.asyncio
    async def test_checks_the_future_rule_once_at_creation(
        self,
        service: TaskService,
        mock_settings_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The check belongs to the moment the anchor is set, not to every read.

        Nothing here re-validates after the save; a task whose due journal later
        moves into the past is lapsed, not invalid.
        """
        await create(service, mock_transaction)

        assert mock_settings_repo.get_timezone.await_count == 1


@pytest.mark.unit
class TestRowsThatVanishMidCreate:
    """A row deleted between its check and the write keeps its domain error.

    The integration suite proves the mapping against the message PostgreSQL
    really produces; these pin the dispatch itself, including the case that must
    **not** be mapped.
    """

    @staticmethod
    def integrity_error(constraint: str) -> IntegrityError:
        """An integrity error shaped like the one a violated foreign key raises.

        The statement carries the **full column list**, exactly as the real one
        does, because that is what makes this test able to fail: matching the
        constraint against ``str(error)`` would find both anchor columns in the
        ``INSERT`` and report whichever was tested first. Only the driver's own
        message names the one constraint that was actually violated.
        """
        return IntegrityError(
            "INSERT INTO tasks (user_id, text, creating_journal_id, due_journal_id) "
            "VALUES ($1, $2, $3, $4)",
            {},
            Exception(
                f'insert or update on table "tasks" violates foreign key '
                f'constraint "{constraint}"'
            ),
        )

    @pytest.mark.asyncio
    async def test_a_vanished_due_journal_is_reported_as_its_anchor(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The promised 404 survives, rather than a raw integrity error escaping."""
        mock_task_repo.save.side_effect = self.integrity_error(
            "tasks_due_journal_id_fkey"
        )

        with pytest.raises(TaskAnchorJournalNotFoundError) as exc_info:
            await create(service, mock_transaction)

        assert exc_info.value.anchor == "due"
        assert exc_info.value.journal_id == DUE_JOURNAL_ID

    @pytest.mark.asyncio
    async def test_a_vanished_creating_journal_is_reported_as_its_anchor(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The two anchors are told apart by the column the violation names."""
        mock_task_repo.save.side_effect = self.integrity_error(
            "tasks_creating_journal_id_fkey"
        )

        with pytest.raises(TaskAnchorJournalNotFoundError) as exc_info:
            await create(service, mock_transaction)

        assert exc_info.value.anchor == "creating"
        assert exc_info.value.journal_id == CREATING_JOURNAL_ID

    @pytest.mark.asyncio
    async def test_an_unrelated_integrity_error_is_left_alone(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Only anchor violations are translated; anything else must surface as-is.

        Swallowing every integrity error into a 404 would turn a genuine bug —
        a broken constraint, a bad migration — into a plausible-looking "not
        found" the caller would act on.
        """
        mock_task_repo.save.side_effect = self.integrity_error("ck_tasks_status")

        with pytest.raises(IntegrityError):
            await create(service, mock_transaction)

    @pytest.mark.asyncio
    async def test_a_vanished_contact_is_reported_as_a_missing_contact(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_contact_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The same race one row over: the link's own violation keeps its 404.

        The batched insert cannot say *which* contact vanished, so the service
        re-reads the requested ids to find out. That read is only possible
        because the insert runs inside a ``SAVEPOINT`` — a foreign-key violation
        aborts the enclosing transaction otherwise, and the recovery lookup would
        fail before it could answer.
        """
        mock_contact_repo.find_names_by_ids.side_effect = [
            {3: ("Sarah", None, None)},
            {},
        ]
        mock_task_repo.add_contacts.side_effect = self.integrity_error(
            "task_contacts_contact_id_fkey"
        )

        with pytest.raises(ContactNotFoundError) as exc_info:
            await create(service, mock_transaction, contact_ids=[3])

        assert exc_info.value.contact_id == 3


@pytest.mark.unit
class TestContactLinks:
    """Contacts are optional plain references, validated before anything is written."""

    @pytest.mark.asyncio
    async def test_rejects_a_contact_that_does_not_exist(
        self,
        service: TaskService,
        mock_contact_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """An unknown contact fails the create rather than being dropped silently."""
        mock_contact_repo.find_names_by_ids.return_value = {3: ("Sarah", None, None)}

        with pytest.raises(ContactNotFoundError) as exc_info:
            await create(service, mock_transaction, contact_ids=[3, 404])

        assert exc_info.value.contact_id == 404
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_writes_nothing_when_a_contact_is_rejected(
        self,
        service: TaskService,
        mock_contact_repo: AsyncMock,
        mock_task_repo: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Validation precedes persistence, so a bad contact leaves no task behind."""
        mock_contact_repo.find_names_by_ids.return_value = {}

        with pytest.raises(ContactNotFoundError):
            await create(service, mock_transaction, contact_ids=[404])

        mock_task_repo.save.assert_not_awaited()
        mock_task_repo.add_contacts.assert_not_awaited()


@pytest.mark.unit
class TestCreationPublishesAnEvent:
    """A create announces itself, once, with the id it was actually given."""

    @pytest.mark.asyncio
    async def test_publishes_exactly_one_task_created_event(
        self,
        service: TaskService,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """One write, one event.

        Counted rather than searched for: a second event would still satisfy
        "a ``TaskCreated`` was published", and would put two entries in the
        history feed for one thing that happened.
        """
        await create(service, mock_transaction)

        (event,) = published_events(mock_event_publisher)
        assert event.event_type == "TaskCreated"

    @pytest.mark.asyncio
    async def test_the_event_carries_the_persisted_id(
        self,
        service: TaskService,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Published after the save, which is the only place the id comes from.

        An event built before persistence would carry ``None``, and the history
        projection keys its rows on this id — so the trail would belong to no
        task at all.
        """
        created = await create(service, mock_transaction)

        (event,) = published_events(mock_event_publisher)
        assert event.aggregate_id == created.id
        assert event.event_data["task_id"] == created.id

    @pytest.mark.asyncio
    async def test_the_event_describes_the_task_that_was_saved(
        self,
        service: TaskService,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The payload is read off the persisted task, not the request."""
        created = await create(service, mock_transaction, text="print the permit")

        (event,) = published_events(mock_event_publisher)
        assert event.event_data["user_id"] == USER_ID
        assert event.event_data["text"] == "print the permit"
        assert event.event_data["status"] == TaskStatus.NOT_DONE.value
        assert event.event_data["creating_journal_id"] == created.creating_journal_id
        assert event.event_data["due_journal_id"] == created.due_journal_id

    @pytest.mark.asyncio
    async def test_the_event_is_built_with_the_callers_connection(
        self,
        service: TaskService,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Protocol conformance, not the mechanism that makes the two atomic.

        ``OutboxEventPublisher`` never reads ``event.transaction``; it writes on
        the connection it was constructed with. This asserts only that the
        service passes the connection it was handed, the way every other domain
        does. That the outbox row really shares the task's transaction is a
        property of a live connection, and is asserted against one in
        ``test_task_events_integration.py``.
        """
        await create(service, mock_transaction)

        (event,) = published_events(mock_event_publisher)
        assert event.transaction is mock_transaction

    @pytest.mark.asyncio
    async def test_publishing_follows_the_contact_links(
        self,
        service: TaskService,
        mock_task_repo: AsyncMock,
        mock_contact_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The event names a create that finished, links included.

        Shown by breaking the link write: if publishing came first, the event
        would already have been handed over by the time the failure surfaced.
        The ordering matters because the event is the announcement of a
        completed create, and half a create is not one.
        """
        mock_contact_repo.find_names_by_ids.return_value = {5: ("Sarah", None, None)}
        mock_task_repo.add_contacts.side_effect = RuntimeError("link write failed")

        with pytest.raises(RuntimeError):
            await create(service, mock_transaction, contact_ids=[5])

        assert published_events(mock_event_publisher) == []

    @pytest.mark.asyncio
    async def test_the_payload_says_nothing_about_contacts(
        self,
        service: TaskService,
        mock_contact_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """Contact links get their own event type in a later phase.

        Carrying the ids here would answer that phase's question — whether a
        create with contacts publishes one event or two — in the wrong place and
        without the tests that decision needs.
        """
        mock_contact_repo.find_names_by_ids.return_value = {5: ("Sarah", None, None)}

        await create(service, mock_transaction, contact_ids=[5])

        (event,) = published_events(mock_event_publisher)
        assert "contact_ids" not in event.event_data


@pytest.mark.unit
class TestCreationProvenance:
    """Where the create came from travels with it."""

    @pytest.mark.asyncio
    async def test_defaults_to_system(
        self,
        service: TaskService,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """A caller that names no origin is a system one, never a silent UI one."""
        await service.create_task(
            user_id=USER_ID,
            creating_journal_id=CREATING_JOURNAL_ID,
            due_journal_id=DUE_JOURNAL_ID,
            text="return Sarah's book",
            transaction=mock_transaction,
            now=NOW,
        )

        (event,) = published_events(mock_event_publisher)
        assert event.event_data["source"] == Provenance.SYSTEM.value
        assert event.event_data["changed_by"] == "system"

    @pytest.mark.asyncio
    async def test_records_the_ui_as_the_origin(
        self,
        service: TaskService,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        await create(service, mock_transaction, source=Provenance.UI, changed_by="ui")

        (event,) = published_events(mock_event_publisher)
        assert event.event_data["source"] == Provenance.UI.value
        assert event.event_data["changed_by"] == "ui"

    @pytest.mark.asyncio
    async def test_records_an_ai_agent_as_the_origin(
        self,
        service: TaskService,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        """The distinction the activity-history specification asks for."""
        await create(service, mock_transaction, source=Provenance.MCP, changed_by="mcp")

        (event,) = published_events(mock_event_publisher)
        assert event.event_data["source"] == Provenance.MCP.value
        assert event.event_data["changed_by"] == "mcp"


@pytest.mark.unit
class TestRejectedCreatesAnnounceNothing:
    """Integrity by construction: no event for a change that did not happen."""

    @pytest.mark.asyncio
    async def test_empty_text_publishes_nothing(
        self,
        service: TaskService,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        with pytest.raises(TaskValidationError):
            await create(service, mock_transaction, text="   ")

        assert published_events(mock_event_publisher) == []

    @pytest.mark.asyncio
    async def test_an_unreachable_anchor_publishes_nothing(
        self,
        service: TaskService,
        mock_journal_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        mock_journal_repo.find_by_ids_for_user.return_value = []

        with pytest.raises(TaskAnchorJournalNotFoundError):
            await create(service, mock_transaction)

        assert published_events(mock_event_publisher) == []

    @pytest.mark.asyncio
    async def test_a_due_journal_in_the_past_publishes_nothing(
        self,
        service: TaskService,
        mock_journal_repo: AsyncMock,
        creating_journal: Journal,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        mock_journal_repo.find_by_ids_for_user.return_value = [
            creating_journal,
            make_journal(DUE_JOURNAL_ID, at(YESTERDAY)),
        ]

        with pytest.raises(TaskDueJournalNotFutureError):
            await create(service, mock_transaction)

        assert published_events(mock_event_publisher) == []

    @pytest.mark.asyncio
    async def test_an_unknown_contact_publishes_nothing(
        self,
        service: TaskService,
        mock_contact_repo: AsyncMock,
        mock_event_publisher: AsyncMock,
        mock_transaction: AsyncMock,
    ) -> None:
        mock_contact_repo.find_names_by_ids.return_value = {}

        with pytest.raises(ContactNotFoundError):
            await create(service, mock_transaction, contact_ids=[404])

        assert published_events(mock_event_publisher) == []
