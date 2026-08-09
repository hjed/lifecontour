"""Unit tests for the task read service.

The service is the read model's *fetching* half: it loads the task, its links,
its journals and its contacts, resolves the user's timezone **once**, and hands
the pieces to the pure assembler. It writes nothing, publishes nothing and opens
no transaction.

Two things are worth testing here that neither the rule nor the assembler can
prove on its own. The first is **which timezone the derivation is anchored on**:
the rule takes dates, so only this layer decides whether they came from the
user's configured zone or from UTC, and the cases below are all cases where
those two disagree. The second is **how many round trips one read costs** — a
journal's task list calls this shape once per task, so a per-journal or
per-contact read here becomes an N+1 there.

This file keeps its own doubles rather than the ones in ``conftest.py``, as
``test_task_service_create.py`` does and for the same reason: those exist so a
member-route test can assert nothing went near a journal, and this service's
whole job is to go near several.

**The timezone cases, worked out rather than asserted by feel.** Every one is an
instant where the user's local day and UTC's have already diverged:

- *Sydney (UTC+10).* A journal at 13:00Z on 9 Aug is 23:00 on the 9th there;
  ``now`` at 14:30Z the same day is already 00:30 on the **10th**. So Sydney has
  turned the page and the task has lapsed, while UTC is still on the 9th and
  says it has not.
- *New York (UTC-4 in August).* A journal at 23:00Z on 9 Aug is 19:00 on the 9th
  there; ``now`` at 02:00Z on the 10th is 22:00 on the **same** 9th. So New York
  is still inside the day the task was due, while UTC has moved on and would
  call it lapsed.
"""

import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from core_shared.models.journals import (
    EventDateRange,
    Journal,
    JournalNotFoundError,
)
from core_shared.models.tasks import (
    LapseReason,
    Task,
    TaskNotFoundError,
    TaskStatus,
)

from app.core.journal.services.journal_date_resolver import JournalDateResolver
from app.core.tasks.services.task_read_service import TaskReadService
from tests.unit.tasks.task_doubles import (
    CREATING_JOURNAL_ID,
    DUE_JOURNAL_ID,
    OTHER_USER_ID,
    TASK_ID,
    USER_ID,
    make_task,
)

MENTIONED_JOURNAL_ID = 33

SYDNEY = "Australia/Sydney"
NEW_YORK = "America/New_York"

# 23:00 on 9 August in Sydney; 19:00 on 9 August in New York.
JOURNAL_AT_SYDNEY_LATE_EVENING = datetime.datetime(
    2026, 8, 9, 13, 0, tzinfo=datetime.UTC
)
# 00:30 on 10 August in Sydney, while UTC is still on the 9th.
NOW_PAST_SYDNEY_MIDNIGHT = datetime.datetime(2026, 8, 9, 14, 30, tzinfo=datetime.UTC)

# 19:00 on 9 August in New York, and 09:00 on the 10th in Sydney.
JOURNAL_AT_NEW_YORK_EVENING = datetime.datetime(2026, 8, 9, 23, 0, tzinfo=datetime.UTC)
# 22:00 on 9 August in New York, while UTC has already reached the 10th.
NOW_BEFORE_NEW_YORK_MIDNIGHT = datetime.datetime(2026, 8, 10, 2, 0, tzinfo=datetime.UTC)


def make_journal(
    journal_id: int,
    start: datetime.datetime,
    *,
    title: str = "Permit Meeting",
) -> Journal:
    """A persisted journal, as the repository hands it back."""
    return Journal(
        id=journal_id,
        user_id=USER_ID,
        title=title,
        content="content",
        event_date_range=EventDateRange(start=start, end=start),
    )


@pytest.fixture
def read_task_repo() -> AsyncMock:
    """A task repository holding one not-done task with no links."""
    repo = AsyncMock()
    repo.find_by_id.return_value = make_task()
    repo.list_intermediate_journal_ids.return_value = []
    repo.list_contact_ids.return_value = []
    return repo


@pytest.fixture
def read_journal_repo() -> AsyncMock:
    """A journal repository holding both anchors, dated in the far future."""
    far_future = datetime.datetime(2030, 1, 1, tzinfo=datetime.UTC)
    repo = AsyncMock()
    repo.find_by_ids_for_user.return_value = [
        make_journal(CREATING_JOURNAL_ID, far_future, title="Monday Planning"),
        make_journal(DUE_JOURNAL_ID, far_future, title="Permit Meeting"),
    ]
    return repo


@pytest.fixture
def read_contact_repo() -> AsyncMock:
    """A contact repository that knows nobody unless a test says otherwise."""
    repo = AsyncMock()
    repo.find_names_by_ids.return_value = {}
    return repo


@pytest.fixture
def read_calendar_info_repo() -> AsyncMock:
    """A calendar-info repository reporting nothing cancelled."""
    repo = AsyncMock()
    repo.find_cancelled_journal_ids.return_value = set()
    return repo


@pytest.fixture
def read_settings_repo() -> AsyncMock:
    """A settings repository with no configured timezone — the UTC fallback."""
    repo = AsyncMock()
    repo.get_timezone.return_value = None
    return repo


@pytest.fixture
def read_service(
    read_task_repo: AsyncMock,
    read_journal_repo: AsyncMock,
    read_contact_repo: AsyncMock,
    read_calendar_info_repo: AsyncMock,
    read_settings_repo: AsyncMock,
) -> TaskReadService:
    """The service under test, over mocked ports."""
    return TaskReadService(
        task_repo=read_task_repo,
        journal_repo=read_journal_repo,
        contact_repo=read_contact_repo,
        calendar_info_repo=read_calendar_info_repo,
        date_resolver=JournalDateResolver(read_settings_repo),
    )


@pytest.mark.unit
class TestOwnerScoping:
    """A task the caller does not own is a task that is not there."""

    async def test_an_unknown_task_raises_task_not_found(
        self, read_service: TaskReadService, read_task_repo: AsyncMock
    ) -> None:
        """The repository answers ``None``; the service turns that into the 404."""
        read_task_repo.find_by_id.return_value = None

        with pytest.raises(TaskNotFoundError):
            await read_service.read_model(USER_ID, TASK_ID)

    async def test_another_users_task_is_reached_the_same_way(
        self, read_service: TaskReadService, read_task_repo: AsyncMock
    ) -> None:
        """Ownership is the query's, so a foreign task is simply absent.

        The service passes the acting user through and never compares a
        ``user_id`` itself, which is what keeps "not yours" and "not there"
        indistinguishable.
        """
        read_task_repo.find_by_id.return_value = None

        with pytest.raises(TaskNotFoundError):
            await read_service.read_model(OTHER_USER_ID, TASK_ID)

        read_task_repo.find_by_id.assert_awaited_once_with(TASK_ID, OTHER_USER_ID)

    async def test_a_vanished_anchor_raises_rather_than_reporting_a_wrong_lapse(
        self,
        read_service: TaskReadService,
        read_journal_repo: AsyncMock,
    ) -> None:
        """A due journal that is not there fails loudly.

        Both anchors are ``ON DELETE RESTRICT`` foreign keys, so this is
        unreachable in practice; if it ever happens the read model cannot say
        whether the task lapsed, and inventing an answer would be worse than
        failing.
        """
        read_journal_repo.find_by_ids_for_user.return_value = [
            make_journal(
                CREATING_JOURNAL_ID,
                datetime.datetime(2030, 1, 1, tzinfo=datetime.UTC),
            )
        ]

        with pytest.raises(JournalNotFoundError):
            await read_service.read_model(USER_ID, TASK_ID)


@pytest.mark.unit
class TestRoundTrips:
    """One read per collection, because a list surface calls this per task."""

    async def test_the_timezone_is_resolved_once(
        self,
        read_service: TaskReadService,
        read_task_repo: AsyncMock,
        read_journal_repo: AsyncMock,
        read_settings_repo: AsyncMock,
    ) -> None:
        """Three journals, one settings read.

        The date resolver splits into pure functions and an async wrapper
        precisely so a caller with several journals pays for the timezone once;
        calling the per-journal wrapper instead would be a settings read per
        row.
        """
        far_future = datetime.datetime(2030, 1, 1, tzinfo=datetime.UTC)
        read_task_repo.list_intermediate_journal_ids.return_value = [
            MENTIONED_JOURNAL_ID
        ]
        read_journal_repo.find_by_ids_for_user.return_value = [
            make_journal(CREATING_JOURNAL_ID, far_future),
            make_journal(DUE_JOURNAL_ID, far_future),
            make_journal(MENTIONED_JOURNAL_ID, far_future),
        ]

        await read_service.read_model(USER_ID, TASK_ID)

        assert read_settings_repo.get_timezone.await_count == 1

    async def test_every_journal_is_fetched_in_one_call(
        self,
        read_service: TaskReadService,
        read_task_repo: AsyncMock,
        read_journal_repo: AsyncMock,
    ) -> None:
        """All three roles arrive together, not one query per role."""
        far_future = datetime.datetime(2030, 1, 1, tzinfo=datetime.UTC)
        read_task_repo.list_intermediate_journal_ids.return_value = [
            MENTIONED_JOURNAL_ID
        ]
        read_journal_repo.find_by_ids_for_user.return_value = [
            make_journal(CREATING_JOURNAL_ID, far_future),
            make_journal(DUE_JOURNAL_ID, far_future),
            make_journal(MENTIONED_JOURNAL_ID, far_future),
        ]

        await read_service.read_model(USER_ID, TASK_ID)

        read_journal_repo.find_by_ids_for_user.assert_awaited_once()
        _, requested = read_journal_repo.find_by_ids_for_user.await_args.args
        assert sorted(requested) == sorted(
            [CREATING_JOURNAL_ID, DUE_JOURNAL_ID, MENTIONED_JOURNAL_ID]
        )

    async def test_a_journal_in_two_roles_is_asked_for_once(
        self,
        read_service: TaskReadService,
        read_task_repo: AsyncMock,
        read_journal_repo: AsyncMock,
    ) -> None:
        """Invariant 6's shared journal costs one id, not two.

        Also covers the retarget-onto-an-attached-journal shape, where the due
        anchor is an intermediate link as well.
        """
        far_future = datetime.datetime(2030, 1, 1, tzinfo=datetime.UTC)
        read_task_repo.find_by_id.return_value = Task(
            id=TASK_ID,
            user_id=USER_ID,
            text="return Sarah's book",
            creating_journal_id=DUE_JOURNAL_ID,
            due_journal_id=DUE_JOURNAL_ID,
        )
        read_task_repo.list_intermediate_journal_ids.return_value = [DUE_JOURNAL_ID]
        read_journal_repo.find_by_ids_for_user.return_value = [
            make_journal(DUE_JOURNAL_ID, far_future)
        ]

        model = await read_service.read_model(USER_ID, TASK_ID)

        _, requested = read_journal_repo.find_by_ids_for_user.await_args.args
        assert requested == [DUE_JOURNAL_ID]
        assert model.creating_journal.id == DUE_JOURNAL_ID
        assert [ref.id for ref in model.intermediate_journals] == [DUE_JOURNAL_ID]

    async def test_contacts_are_fetched_in_one_call(
        self,
        read_service: TaskReadService,
        read_task_repo: AsyncMock,
        read_contact_repo: AsyncMock,
    ) -> None:
        """Two contacts, one name lookup."""
        read_task_repo.list_contact_ids.return_value = [5, 9]
        read_contact_repo.find_names_by_ids.return_value = {
            5: ("Sarah", "Chen", "https://example.com/s.jpg"),
            9: ("Mo", "Farah", None),
        }

        model = await read_service.read_model(USER_ID, TASK_ID)

        read_contact_repo.find_names_by_ids.assert_awaited_once_with([5, 9])
        assert [contact.display_name for contact in model.contacts] == [
            "Sarah Chen",
            "Mo Farah",
        ]
        assert model.contacts[0].photo_url == "https://example.com/s.jpg"

    async def test_no_contacts_asks_for_none(
        self, read_service: TaskReadService, read_contact_repo: AsyncMock
    ) -> None:
        """A task with nobody on it still costs at most the one call."""
        model = await read_service.read_model(USER_ID, TASK_ID)

        assert model.contacts == ()
        assert read_contact_repo.find_names_by_ids.await_count <= 1


@pytest.mark.unit
class TestTheTimezoneTheDerivationIsAnchoredOn:
    """The rule takes dates; this layer decides whose day they belong to."""

    async def test_a_user_ahead_of_utc_has_already_lapsed(
        self,
        read_service: TaskReadService,
        read_journal_repo: AsyncMock,
        read_settings_repo: AsyncMock,
    ) -> None:
        """Sydney has turned the page while UTC has not, and Sydney wins."""
        read_settings_repo.get_timezone.return_value = SYDNEY
        read_journal_repo.find_by_ids_for_user.return_value = [
            make_journal(CREATING_JOURNAL_ID, JOURNAL_AT_SYDNEY_LATE_EVENING),
            make_journal(DUE_JOURNAL_ID, JOURNAL_AT_SYDNEY_LATE_EVENING),
        ]

        model = await read_service.read_model(
            USER_ID, TASK_ID, now=NOW_PAST_SYDNEY_MIDNIGHT
        )

        assert model.lapse_reason == LapseReason.DATE_PASSED

    async def test_the_same_instants_read_in_utc_have_not(
        self,
        read_service: TaskReadService,
        read_journal_repo: AsyncMock,
    ) -> None:
        """The control for the case above: UTC is still inside the due day.

        Without this the Sydney test proves only that *something* lapsed. The
        pair is what proves the configured timezone is the one being used.
        """
        read_journal_repo.find_by_ids_for_user.return_value = [
            make_journal(CREATING_JOURNAL_ID, JOURNAL_AT_SYDNEY_LATE_EVENING),
            make_journal(DUE_JOURNAL_ID, JOURNAL_AT_SYDNEY_LATE_EVENING),
        ]

        model = await read_service.read_model(
            USER_ID, TASK_ID, now=NOW_PAST_SYDNEY_MIDNIGHT
        )

        assert model.lapse_reason is None

    async def test_a_user_behind_utc_has_not_lapsed_yet(
        self,
        read_service: TaskReadService,
        read_journal_repo: AsyncMock,
        read_settings_repo: AsyncMock,
    ) -> None:
        """New York is still on the due day while UTC has moved past it.

        The mirror of the Sydney case, so the rule cannot be "corrected" into
        UTC in one direction and still pass.
        """
        read_settings_repo.get_timezone.return_value = NEW_YORK
        read_journal_repo.find_by_ids_for_user.return_value = [
            make_journal(CREATING_JOURNAL_ID, JOURNAL_AT_NEW_YORK_EVENING),
            make_journal(DUE_JOURNAL_ID, JOURNAL_AT_NEW_YORK_EVENING),
        ]

        model = await read_service.read_model(
            USER_ID, TASK_ID, now=NOW_BEFORE_NEW_YORK_MIDNIGHT
        )

        assert model.lapse_reason is None

    async def test_the_same_instants_read_in_utc_have_lapsed(
        self,
        read_service: TaskReadService,
        read_journal_repo: AsyncMock,
    ) -> None:
        """The control for the New York case, in the opposite direction."""
        read_journal_repo.find_by_ids_for_user.return_value = [
            make_journal(CREATING_JOURNAL_ID, JOURNAL_AT_NEW_YORK_EVENING),
            make_journal(DUE_JOURNAL_ID, JOURNAL_AT_NEW_YORK_EVENING),
        ]

        model = await read_service.read_model(
            USER_ID, TASK_ID, now=NOW_BEFORE_NEW_YORK_MIDNIGHT
        )

        assert model.lapse_reason == LapseReason.DATE_PASSED

    async def test_the_journal_ref_carries_the_user_local_date(
        self,
        read_service: TaskReadService,
        read_journal_repo: AsyncMock,
        read_settings_repo: AsyncMock,
    ) -> None:
        """The date on the ref is the Sydney date, not the UTC one."""
        read_settings_repo.get_timezone.return_value = SYDNEY
        read_journal_repo.find_by_ids_for_user.return_value = [
            make_journal(CREATING_JOURNAL_ID, JOURNAL_AT_NEW_YORK_EVENING),
            make_journal(DUE_JOURNAL_ID, JOURNAL_AT_NEW_YORK_EVENING),
        ]

        model = await read_service.read_model(USER_ID, TASK_ID)

        # 23:00Z on 9 August is 09:00 on the 10th in Sydney.
        assert model.due_journal.date == datetime.date(2026, 8, 10)
        assert model.due_journal.date != JOURNAL_AT_NEW_YORK_EVENING.date()

    async def test_now_defaults_to_the_real_clock(
        self,
        read_service: TaskReadService,
        read_journal_repo: AsyncMock,
    ) -> None:
        """Omitting ``now`` reads the clock rather than silently never lapsing.

        A journal a fortnight behind the real today must lapse without a test
        supplying an anchor, because production never supplies one.
        """
        long_past = datetime.datetime.now(ZoneInfo("UTC")) - datetime.timedelta(days=14)
        read_journal_repo.find_by_ids_for_user.return_value = [
            make_journal(CREATING_JOURNAL_ID, long_past),
            make_journal(DUE_JOURNAL_ID, long_past),
        ]

        model = await read_service.read_model(USER_ID, TASK_ID)

        assert model.lapse_reason == LapseReason.DATE_PASSED


@pytest.mark.unit
class TestCancellationThroughTheService:
    """The second cause, reached through the repository that reports it."""

    async def test_a_cancelled_due_journal_lapses_the_task(
        self,
        read_service: TaskReadService,
        read_calendar_info_repo: AsyncMock,
    ) -> None:
        """The due journal is future-dated, and cancelled, so the task lapsed."""
        read_calendar_info_repo.find_cancelled_journal_ids.return_value = {
            DUE_JOURNAL_ID
        }

        model = await read_service.read_model(USER_ID, TASK_ID)

        assert model.lapse_reason == LapseReason.DUE_JOURNAL_CANCELLED
        assert model.due_journal.cancelled is True

    async def test_a_cancelled_creating_journal_lapses_nothing(
        self,
        read_service: TaskReadService,
        read_calendar_info_repo: AsyncMock,
    ) -> None:
        """The cancellation is marked where it happened and changes no verdict."""
        read_calendar_info_repo.find_cancelled_journal_ids.return_value = {
            CREATING_JOURNAL_ID
        }

        model = await read_service.read_model(USER_ID, TASK_ID)

        assert model.creating_journal.cancelled is True
        assert model.due_journal.cancelled is False
        assert model.lapse_reason is None

    async def test_a_journal_with_no_calendar_info_is_not_cancelled(
        self, read_service: TaskReadService
    ) -> None:
        """The default fixture is a plain note journal, and it is not cancelled."""
        model = await read_service.read_model(USER_ID, TASK_ID)

        assert model.due_journal.cancelled is False
        assert model.lapse_reason is None

    @pytest.mark.parametrize("status", [TaskStatus.DONE, TaskStatus.CANCELLED])
    async def test_a_finished_task_is_not_lapsed_by_a_cancelled_journal(
        self,
        read_service: TaskReadService,
        read_task_repo: AsyncMock,
        read_calendar_info_repo: AsyncMock,
        status: TaskStatus,
    ) -> None:
        """The status gate holds through the whole read path, not just the rule."""
        read_task_repo.find_by_id.return_value = make_task(status)
        read_calendar_info_repo.find_cancelled_journal_ids.return_value = {
            DUE_JOURNAL_ID
        }

        model = await read_service.read_model(USER_ID, TASK_ID)

        assert model.lapsed is False


@pytest.mark.unit
class TestWhatTheModelCarries:
    """The pieces a surface renders, assembled from real repository answers."""

    async def test_journals_arrive_under_their_roles_with_titles(
        self,
        read_service: TaskReadService,
        read_task_repo: AsyncMock,
        read_journal_repo: AsyncMock,
    ) -> None:
        """Titles come from the journals, so no surface needs a second read."""
        far_future = datetime.datetime(2030, 1, 1, tzinfo=datetime.UTC)
        read_task_repo.list_intermediate_journal_ids.return_value = [
            MENTIONED_JOURNAL_ID
        ]
        read_journal_repo.find_by_ids_for_user.return_value = [
            make_journal(CREATING_JOURNAL_ID, far_future, title="Monday Planning"),
            make_journal(DUE_JOURNAL_ID, far_future, title="Permit Meeting"),
            make_journal(MENTIONED_JOURNAL_ID, far_future, title="Standup"),
        ]

        model = await read_service.read_model(USER_ID, TASK_ID)

        assert model.creating_journal.title == "Monday Planning"
        assert model.due_journal.title == "Permit Meeting"
        assert [ref.title for ref in model.intermediate_journals] == ["Standup"]

    async def test_intermediate_journals_keep_the_repositorys_order(
        self,
        read_service: TaskReadService,
        read_task_repo: AsyncMock,
        read_journal_repo: AsyncMock,
    ) -> None:
        """Oldest link first, whatever order the journal query answered in.

        The journal repository is free to return rows however its plan likes,
        so the order has to come from the link list rather than from it.
        """
        far_future = datetime.datetime(2030, 1, 1, tzinfo=datetime.UTC)
        read_task_repo.list_intermediate_journal_ids.return_value = [
            MENTIONED_JOURNAL_ID,
            77,
        ]
        read_journal_repo.find_by_ids_for_user.return_value = [
            make_journal(77, far_future),
            make_journal(DUE_JOURNAL_ID, far_future),
            make_journal(MENTIONED_JOURNAL_ID, far_future),
            make_journal(CREATING_JOURNAL_ID, far_future),
        ]

        model = await read_service.read_model(USER_ID, TASK_ID)

        assert [ref.id for ref in model.intermediate_journals] == [
            MENTIONED_JOURNAL_ID,
            77,
        ]

    async def test_a_nameless_contact_still_renders(
        self,
        read_service: TaskReadService,
        read_task_repo: AsyncMock,
        read_contact_repo: AsyncMock,
    ) -> None:
        """A contact with no name parts gets a placeholder, not an empty string.

        The same fallback the journal controller uses for the same data, so a
        contact reads the same way on a task as it does on a journal.
        """
        read_task_repo.list_contact_ids.return_value = [5]
        read_contact_repo.find_names_by_ids.return_value = {5: (None, None, None)}

        model = await read_service.read_model(USER_ID, TASK_ID)

        assert model.contacts[0].display_name == "Contact 5"

    async def test_a_contact_with_only_a_first_name_is_not_padded(
        self,
        read_service: TaskReadService,
        read_task_repo: AsyncMock,
        read_contact_repo: AsyncMock,
    ) -> None:
        """One name part joins to itself, with no trailing space."""
        read_task_repo.list_contact_ids.return_value = [5]
        read_contact_repo.find_names_by_ids.return_value = {5: ("Sarah", None, None)}

        model = await read_service.read_model(USER_ID, TASK_ID)

        assert model.contacts[0].display_name == "Sarah"

    async def test_the_task_entity_is_carried_through(
        self, read_service: TaskReadService
    ) -> None:
        """Text and status reach the surface from the task, not re-fetched."""
        model = await read_service.read_model(USER_ID, TASK_ID)

        assert model.task.id == TASK_ID
        assert model.task.status is TaskStatus.NOT_DONE
