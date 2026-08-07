"""Fixtures shared by the tasks domain's service integration tests.

Both service test files — creation and the status lifecycle — assemble the same
service over real adapters. It lives here rather than being copied per file.

This conftest is scoped to ``tests/integration/tasks/``, because only the
service tests construct a service. Fixtures whose consumers also sit under
``api/`` and ``mcp/`` (``task_repository``, ``task_anchors``,
``journal_repository``, ``user_settings_repository``) stay in the root
integration conftest, which is the only one those three directories share.
"""

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_repository import SqlContactRepository
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_date_resolver import JournalDateResolver
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.tasks.adapters.sql.task_repository import SqlTaskRepository
from app.core.tasks.services.task_service import TaskService


@pytest_asyncio.fixture
async def service(
    async_connection: AsyncConnection,
    task_repository: SqlTaskRepository,
    journal_repository: SqlJournalRepository,
    user_settings_repository: SqlUserSettingsRepository,
) -> TaskService:
    """The service over real adapters on the test's single connection."""
    return TaskService(
        task_repo=task_repository,
        journal_repo=journal_repository,
        contact_repo=SqlContactRepository(async_connection),
        date_resolver=JournalDateResolver(user_settings_repo=user_settings_repository),
    )
