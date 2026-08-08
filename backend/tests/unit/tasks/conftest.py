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
    """The service under test, over mocked ports."""
    return TaskService(
        task_repo=mock_task_repo,
        journal_repo=mock_journal_repo,
        contact_repo=mock_contact_repo,
        date_resolver=JournalDateResolver(mock_settings_repo),
    )
