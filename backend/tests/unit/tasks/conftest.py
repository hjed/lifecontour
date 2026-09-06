"""Fixtures shared by the task service's member-route unit tests.

A member-route operation — changing a status, rewording a task, deleting one —
reaches the task by its own id and touches **no other domain**. So the doubles
are the same in every case: a task repository that echoes back what it saves,
and journal, contact and settings repositories that exist only so a test can
assert nothing went near them.

``test_task_service_create.py`` shadows these with its own, because creation
genuinely needs journals loaded and contacts resolved. Local fixtures win over
a conftest, so that file is unaffected by what is defined here.
"""

from unittest.mock import AsyncMock

import pytest
from core_shared.models.tasks import Task

from app.core.journal.services.journal_date_resolver import JournalDateResolver
from app.core.tasks.services.task_read_service import TaskReadService
from app.core.tasks.services.task_service import TaskService
from tests.unit.tasks.task_doubles import make_task


@pytest.fixture
def mock_task_repo() -> AsyncMock:
    """A task repository that echoes back whatever it is asked to save."""
    repo = AsyncMock()

    async def save(task: Task) -> Task:
        return task

    repo.save.side_effect = save
    repo.find_by_id_for_update.return_value = make_task()
    return repo


@pytest.fixture
def mock_journal_repo() -> AsyncMock:
    """A journal repository no member-route operation may touch."""
    return AsyncMock()


@pytest.fixture
def mock_contact_repo() -> AsyncMock:
    """A contact repository no member-route operation may touch."""
    return AsyncMock()


@pytest.fixture
def mock_settings_repo() -> AsyncMock:
    """A settings repository; no member-route operation needs a timezone."""
    repo = AsyncMock()
    repo.get_timezone.return_value = "UTC"
    return repo


@pytest.fixture
def mock_event_publisher() -> AsyncMock:
    """The outbox publisher, recording what the operation announced.

    A double rather than the real ``OutboxEventPublisher`` because that one's
    job is a single ``INSERT``: what it does with an event belongs to the
    integration tests, and what the service hands it belongs here.
    """
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
    mock_settings_repo: AsyncMock,
    mock_event_publisher: AsyncMock,
) -> TaskService:
    """The service under test, over mocked ports."""
    return TaskService(
        task_repo=mock_task_repo,
        journal_repo=mock_journal_repo,
        contact_repo=mock_contact_repo,
        date_resolver=JournalDateResolver(mock_settings_repo),
        event_publisher=mock_event_publisher,
    )


# ---------------------------------------------------------------------------
# The read service's ports.
#
# Three suites drive ``TaskReadService`` over mocked ports — a journal's task
# list, the upcoming window and the past-day resolutions. The three doubles
# below hold no per-file data, so all three files had byte-identical copies of
# them, and of the service they are wired into. One definition each, here.
#
# ``task_repo`` and ``journal_repo`` stay in the files: what a task repository
# is *seeded with* is the whole subject of each suite, and a shared default
# would be one no file actually wanted. ``read_service`` picks whichever
# definitions its module supplies.
# ---------------------------------------------------------------------------


@pytest.fixture
def contact_repo() -> AsyncMock:
    """A contact repository that knows nobody unless a test says otherwise."""
    repo = AsyncMock()
    repo.find_names_by_ids.return_value = {}
    return repo


@pytest.fixture
def calendar_info_repo() -> AsyncMock:
    """A calendar-info repository reporting nothing cancelled."""
    repo = AsyncMock()
    repo.find_cancelled_journal_ids.return_value = set()
    return repo


@pytest.fixture
def settings_repo() -> AsyncMock:
    """A settings repository with no configured timezone — the UTC fallback."""
    repo = AsyncMock()
    repo.get_timezone.return_value = None
    return repo


@pytest.fixture
def read_service(
    task_repo: AsyncMock,
    journal_repo: AsyncMock,
    contact_repo: AsyncMock,
    calendar_info_repo: AsyncMock,
    settings_repo: AsyncMock,
) -> TaskReadService:
    """The read service under test, over mocked ports.

    Named ``read_service`` rather than ``service`` because ``service`` is
    already this conftest's *write* service, and the two are not
    interchangeable. The suites that predate this move keep ``service`` as a
    one-line alias, so ~100 test signatures did not have to change for a
    fixture to stop being copied three times.
    """
    return TaskReadService(
        task_repo=task_repo,
        journal_repo=journal_repo,
        contact_repo=contact_repo,
        calendar_info_repo=calendar_info_repo,
        date_resolver=JournalDateResolver(settings_repo),
    )
