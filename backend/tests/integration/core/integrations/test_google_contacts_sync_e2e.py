"""End-to-end integration test for the Google Contacts sync flow."""

import importlib.util
import os
import sys
from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import cast
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

import pytest
from arq import create_pool
from arq.connections import RedisSettings
from arq.jobs import Job, JobStatus
from arq.worker import Worker
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.core.integrations.database import IntegrationDatabaseManager
from app.core.integrations.task_queue_service import ARQ_QUEUE_NAME, TaskQueueService

TEST_REDIS_DATABASE = 15
WORKER_DIRECTORY = (
    Path(__file__).resolve().parents[5] / "integration_workers" / "google"
)
WORKER_TEST_MODULE_PREFIX = "google_worker_test_"
WORKER_ENVIRONMENT_VARIABLES = (
    "DATABASE_URL",
    "REDIS_URL",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "ENCRYPTION_KEY",
    "WORKER_ID",
    "LOG_LEVEL",
)


class _SavepointDbManager(IntegrationDatabaseManager):
    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        async with AsyncSession(
            self._connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        ) as session:
            yield session


class _NoCommitConnectionProxy:
    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection

    async def commit(self) -> None:
        return None

    def __getattr__(self, name: str):
        return getattr(self._connection, name)


def _worker_environment_overrides(
    database_url: str, redis_url: str, encryption_key: str
) -> dict[str, str]:
    return {
        "DATABASE_URL": database_url,
        "REDIS_URL": redis_url,
        "GOOGLE_CLIENT_ID": "test-client-id",
        "GOOGLE_CLIENT_SECRET": "test-client-secret",
        "ENCRYPTION_KEY": encryption_key,
        "WORKER_ID": "google-e2e-test-worker",
        "LOG_LEVEL": "INFO",
    }


def _get_worker_directory_module_names() -> set[str]:
    module_names: set[str] = set()

    for module_name, module in sys.modules.items():
        module_file = getattr(module, "__file__", None)
        if module_file is None:
            continue

        try:
            if Path(module_file).resolve().parent == WORKER_DIRECTORY:
                module_names.add(module_name)
        except OSError:
            continue

    return module_names


@contextmanager
def _temporary_worker_import_environment(
    database_url: str, redis_url: str, encryption_key: str
) -> Iterator[None]:
    original_sys_path = list(sys.path)
    original_env = {key: os.environ.get(key) for key in WORKER_ENVIRONMENT_VARIABLES}

    sys.path.insert(0, str(WORKER_DIRECTORY))
    os.environ.update(
        _worker_environment_overrides(database_url, redis_url, encryption_key)
    )

    try:
        yield
    finally:
        sys.path[:] = original_sys_path
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _load_worker_module(
    database_url: str, redis_url: str, encryption_key: str
) -> ModuleType:
    module_name = f"{WORKER_TEST_MODULE_PREFIX}{uuid4().hex}"
    original_worker_module_names = _get_worker_directory_module_names()
    module_spec = importlib.util.spec_from_file_location(
        module_name,
        WORKER_DIRECTORY / "worker.py",
    )
    if module_spec is None or module_spec.loader is None:
        raise ImportError("Could not load Google Contacts worker module spec")

    worker_module = importlib.util.module_from_spec(module_spec)

    try:
        with _temporary_worker_import_environment(
            database_url, redis_url, encryption_key
        ):
            sys.modules[module_name] = worker_module
            module_spec.loader.exec_module(worker_module)
    finally:
        sys.modules.pop(module_name, None)
        current_worker_module_names = _get_worker_directory_module_names()
        for loaded_module_name in (
            current_worker_module_names - original_worker_module_names
        ):
            sys.modules.pop(loaded_module_name, None)

    return worker_module


def _build_test_redis_settings(
    redis_url: str, *, database: int = TEST_REDIS_DATABASE
) -> RedisSettings:
    parsed_redis_url = urlparse(redis_url)
    return RedisSettings(
        host=parsed_redis_url.hostname or "localhost",
        port=parsed_redis_url.port or 6379,
        database=database,
    )


def _build_test_redis_url(
    redis_url: str, *, database: int = TEST_REDIS_DATABASE
) -> str:
    parsed_redis_url = urlparse(redis_url)
    return urlunparse(parsed_redis_url._replace(path=f"/{database}"))


def test_load_worker_module_restores_process_state(test_settings) -> None:
    """Worker module loading should not leak import or environment state."""
    original_sys_path = list(sys.path)
    original_env = {key: os.environ.get(key) for key in WORKER_ENVIRONMENT_VARIABLES}
    original_worker_module_names = _get_worker_directory_module_names()

    try:
        worker_module = _load_worker_module(
            str(test_settings.database_url),
            test_settings.redis_url,
            Fernet.generate_key().decode(),
        )

        assert worker_module.__name__.startswith(WORKER_TEST_MODULE_PREFIX)
        assert sys.path == original_sys_path
        assert str(WORKER_DIRECTORY) not in sys.path
        for key, value in original_env.items():
            assert os.environ.get(key) == value
        assert _get_worker_directory_module_names() == original_worker_module_names
    finally:
        while str(WORKER_DIRECTORY) in sys.path:
            sys.path.remove(str(WORKER_DIRECTORY))

        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        current_worker_module_names = _get_worker_directory_module_names()
        for loaded_module_name in (
            current_worker_module_names - original_worker_module_names
        ):
            sys.modules.pop(loaded_module_name, None)


def _build_mock_google_service() -> MagicMock:
    mock_list = MagicMock()
    mock_list.execute.return_value = {
        "connections": [
            {
                "resourceName": "people/c123456789",
                "etag": "etag123",
                "names": [{"givenName": "John", "familyName": "Doe"}],
                "emailAddresses": [
                    {"value": "john.doe@example.com", "formattedType": "Work"}
                ],
                "phoneNumbers": [
                    {
                        "value": "+1-555-123-4567",
                        "canonicalForm": "+15551234567",
                        "formattedType": "Mobile",
                    }
                ],
                "metadata": {"sources": [{"type": "CONTACT"}]},
            }
        ],
        "nextSyncToken": "sync-token-after-full-sync",
    }

    mock_connections = MagicMock()
    mock_connections.list.return_value = mock_list
    mock_people = MagicMock()
    mock_people.connections.return_value = mock_connections
    mock_service = MagicMock()
    mock_service.people.return_value = mock_people
    return mock_service


async def _insert_google_auth_tokens(
    connection: AsyncConnection,
    *,
    user_id: str,
    email: str,
    fernet: Fernet,
    expires_at: datetime,
    now: datetime,
) -> None:
    await connection.execute(
        text(
            """
            INSERT INTO user_google_auth (
                user_id,
                google_account_email,
                encrypted_access_token,
                encrypted_refresh_token,
                expires_at,
                created_at,
                updated_at
            ) VALUES (
                :user_id,
                :email,
                :access_token,
                :refresh_token,
                :expires_at,
                :created_at,
                :updated_at
            )
            """
        ),
        {
            "user_id": user_id,
            "email": email,
            "access_token": fernet.encrypt(b"access-token"),
            "refresh_token": fernet.encrypt(b"refresh-token"),
            "expires_at": expires_at,
            "created_at": now,
            "updated_at": now,
        },
    )


@asynccontextmanager
async def _authenticated_client_with_savepoint_db_manager(
    async_connection: AsyncConnection,
    test_settings,
    test_user,
) -> AsyncGenerator[AsyncClient, None]:
    from dishka import Provider, Scope, make_async_container, provide
    from dishka.integrations.fastapi import FastapiProvider, setup_dishka

    from app.infrastructure.auth.models import SessionUser
    from app.infrastructure.auth.oauth_service import OAuthService
    from app.infrastructure.config import Settings
    from app.infrastructure.di.contacts import ContactProvider
    from app.infrastructure.di.infrastructure import InfrastructureProvider
    from app.infrastructure.di.integrations import IntegrationProvider
    from app.infrastructure.di.journal import JournalProvider
    from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
    from app.infrastructure.search.search_service import SearchService
    from app.main import create_app

    db_manager = _SavepointDbManager(async_connection)

    class TestAuthProvider(Provider):
        @provide(scope=Scope.APP)
        def get_settings(self) -> Settings:
            return cast(Settings, test_settings)

        @provide(scope=Scope.REQUEST)
        def get_session_user(self) -> SessionUser:
            return cast(SessionUser, test_user)

        @provide(scope=Scope.REQUEST)
        def get_oauth_service(self, settings: Settings) -> OAuthService:
            return OAuthService(settings)

        @provide(scope=Scope.APP)
        def get_search_service(self) -> SearchService:
            return SearchService()

        @provide(scope=Scope.REQUEST)
        def get_outbox_event_publisher(
            self, connection: AsyncConnection
        ) -> OutboxEventPublisher:
            return OutboxEventPublisher(connection)

    class TestDatabaseProvider(Provider):
        def __init__(self, connection: AsyncConnection) -> None:
            super().__init__()
            self.connection = connection

        @provide(scope=Scope.REQUEST)
        def get_connection(self) -> AsyncConnection:
            return self.connection

        @provide(scope=Scope.REQUEST)
        def get_integration_database_manager(self) -> IntegrationDatabaseManager:
            return db_manager

    app = create_app(settings=test_settings)
    test_container = make_async_container(
        InfrastructureProvider(),
        TestAuthProvider(),
        ContactProvider(),
        JournalProvider(),
        IntegrationProvider(),
        TestDatabaseProvider(async_connection),
        FastapiProvider(),
    )

    try:
        await app.state.dishka_container.close()
    except (RuntimeError, AttributeError):
        pass

    app.state.dishka_container = test_container
    setup_dishka(test_container, app)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    await test_container.close()


async def _run_google_worker(
    *,
    worker_module,
    redis_pool,
    db_manager: IntegrationDatabaseManager,
    job_id: str,
) -> None:
    arq_worker = Worker(
        functions=[worker_module.sync_google],
        redis_pool=redis_pool,
        queue_name=ARQ_QUEUE_NAME,
        burst=True,
        max_jobs=1,
        handle_signals=False,
        ctx={"session_factory": db_manager.get_session, "redis": redis_pool},
    )

    with patch.dict(
        worker_module.GoogleAPIClient._get_service.__globals__,
        {"build": MagicMock(return_value=_build_mock_google_service())},
    ):
        await arq_worker.async_run()

    arq_job = Job(job_id, redis=redis_pool)
    assert await arq_job.status() == JobStatus.complete
    assert (await arq_job.result(timeout=1))["status"] == "success"


async def _run_outbox_processor(connection: AsyncConnection) -> None:
    from app.infrastructure.events.outbox_processor import OutboxProcessor

    proxied_connection = _NoCommitConnectionProxy(connection)

    @asynccontextmanager
    async def mock_begin():
        yield proxied_connection

    class _TestEngine:
        def begin(self):
            return mock_begin()

    with patch(
        "app.infrastructure.events.outbox_processor.get_async_database_engine",
        return_value=_TestEngine(),
    ):
        await OutboxProcessor().process_events()


async def _assert_google_sync_side_effects(
    connection: AsyncConnection, *, job_id: str, google_account_email: str
) -> None:
    sync_job = (
        await connection.execute(
            text(
                """
                SELECT status, started_at, completed_at, contacts_processed,
                       contacts_created, contacts_updated, progress
                FROM sync_jobs
                WHERE job_id = :job_id
                """
            ),
            {"job_id": job_id},
        )
    ).one()
    assert sync_job[0] == "completed"
    assert sync_job[1] is not None
    assert sync_job[2] is not None
    assert sync_job[3:] == (1, 1, 0, 100)

    outbox_rows = list(
        (
            await connection.execute(
                text(
                    """
                    SELECT event_type, processed_at
                    FROM outbox_events
                    WHERE event_type IN ('contact.created', 'sync.completed')
                    ORDER BY event_type
                    """
                )
            )
        ).fetchall()
    )
    assert outbox_rows == [
        ("contact.created", None),
        ("sync.completed", None),
    ]

    sync_completed_metrics = (
        await connection.execute(
            text(
                """
                SELECT ((event_data::jsonb)->'metrics'->>'contacts_created')::int
                FROM outbox_events
                WHERE event_type = 'sync.completed'
                """
            )
        )
    ).scalar_one()
    assert sync_completed_metrics == 1

    await _run_outbox_processor(connection)

    contact_row = (
        await connection.execute(
            text(
                "SELECT id, first_name, last_name FROM contacts WHERE first_name = 'John' AND last_name = 'Doe'"
            )
        )
    ).one()
    contact_methods = list(
        (
            await connection.execute(
                text(
                    "SELECT value FROM contact_methods WHERE contact_id = :contact_id ORDER BY value"
                ),
                {"contact_id": contact_row.id},
            )
        ).scalars()
    )
    assert contact_methods == ["+15551234567", "john.doe@example.com"]

    external_reference = (
        await connection.execute(
            text(
                """
                SELECT external_system, external_entity_id
                FROM external_references
                WHERE internal_entity_type = 'contact' AND internal_entity_id = :contact_id
                """
            ),
            {"contact_id": contact_row.id},
        )
    ).one()
    assert external_reference == ("google", "people/c123456789")

    sync_token = (
        await connection.execute(
            text(
                "SELECT contacts_sync_token FROM user_google_integration WHERE google_account_email = :email"
            ),
            {"email": google_account_email},
        )
    ).scalar_one()
    assert sync_token == "sync-token-after-full-sync"

    processed_rows = list(
        (
            await connection.execute(
                text(
                    """
                    SELECT event_type, processed_at IS NOT NULL
                    FROM outbox_events
                    WHERE event_type IN ('contact.created', 'sync.completed')
                    ORDER BY event_type
                    """
                )
            )
        ).fetchall()
    )
    assert processed_rows == [
        ("contact.created", True),
        ("sync.completed", True),
    ]


@pytest.mark.asyncio
async def test_google_sync_flow_runs_through_arq_and_outbox(
    async_connection: AsyncConnection,
    clean_database,
    test_settings,
):
    _ = clean_database
    now = datetime.now(UTC)
    future_expiry = now + timedelta(hours=1)
    test_email = "google-sync-e2e@example.com"
    test_user_id = "123"
    fernet_key = Fernet.generate_key()
    fernet = Fernet(fernet_key)
    worker = _load_worker_module(
        str(test_settings.database_url),
        test_settings.redis_url,
        fernet_key.decode(),
    )
    redis_settings = _build_test_redis_settings(test_settings.redis_url)
    assert redis_settings.database == TEST_REDIS_DATABASE
    redis_pool = await create_pool(redis_settings)
    db_manager = _SavepointDbManager(async_connection)
    service = TaskQueueService(
        redis_pool=redis_pool,
        redis_settings=redis_settings,
        settings=test_settings,
        db_manager=db_manager,
    )

    try:
        await redis_pool.flushdb()
        await _insert_google_auth_tokens(
            async_connection,
            user_id=test_user_id,
            email=test_email,
            fernet=fernet,
            expires_at=future_expiry,
            now=now,
        )

        job_id = await service.enqueue_google_sync(
            google_account_email=test_email,
            user_id=test_user_id,
            sync_type="smart",
        )

        queued_job = (
            await async_connection.execute(
                text("SELECT status, sync_type FROM sync_jobs WHERE job_id = :job_id"),
                {"job_id": job_id},
            )
        ).one()
        assert queued_job == ("queued", "smart")

        await _run_google_worker(
            worker_module=worker,
            redis_pool=redis_pool,
            db_manager=db_manager,
            job_id=job_id,
        )

        await _assert_google_sync_side_effects(
            async_connection,
            job_id=job_id,
            google_account_email=test_email,
        )
    finally:
        await service.close()
        await redis_pool.flushdb()
        await redis_pool.close()


@pytest.mark.asyncio
async def test_google_sync_flow_runs_from_http_endpoint(
    async_connection: AsyncConnection,
    clean_database,
    test_settings,
    test_user,
):
    _ = clean_database
    now = datetime.now(UTC)
    future_expiry = now + timedelta(hours=1)
    session_user = test_user.model_copy(update={"email": "app-user@example.com"})
    google_account_email = "connected-google@example.com"
    assert session_user.email != google_account_email
    fernet_key = Fernet.generate_key()
    fernet = Fernet(fernet_key)
    http_test_settings = test_settings.model_copy(
        update={"redis_url": _build_test_redis_url(test_settings.redis_url)}
    )
    worker = _load_worker_module(
        str(http_test_settings.database_url),
        http_test_settings.redis_url,
        fernet_key.decode(),
    )
    redis_settings = _build_test_redis_settings(http_test_settings.redis_url)
    assert redis_settings.database == TEST_REDIS_DATABASE
    redis_pool = await create_pool(redis_settings)
    db_manager = _SavepointDbManager(async_connection)

    try:
        await redis_pool.flushdb()
        await _insert_google_auth_tokens(
            async_connection,
            user_id=str(session_user.id),
            email=google_account_email,
            fernet=fernet,
            expires_at=future_expiry,
            now=now,
        )

        async with _authenticated_client_with_savepoint_db_manager(
            async_connection,
            http_test_settings,
            session_user,
        ) as authenticated_client:
            response = await authenticated_client.post(
                "/api/integrations/google/contacts/sync",
                json={"sync_type": "smart"},
            )

        assert response.status_code == 200, response.text
        response_body = response.json()
        assert response_body["data"]["type"] == "sync-job"
        assert response_body["data"]["attributes"]["status"] == "queued"
        assert response_body["data"]["attributes"]["syncType"] == "smart"
        assert response_body["data"]["attributes"]["createdAt"] is not None
        assert response_body["data"]["attributes"]["startedAt"] is None

        job_id = response_body["data"]["id"]
        queued_job = (
            await async_connection.execute(
                text("SELECT status, sync_type FROM sync_jobs WHERE job_id = :job_id"),
                {"job_id": job_id},
            )
        ).one()
        assert queued_job == ("queued", "smart")

        await _run_google_worker(
            worker_module=worker,
            redis_pool=redis_pool,
            db_manager=db_manager,
            job_id=job_id,
        )

        await _assert_google_sync_side_effects(
            async_connection,
            job_id=job_id,
            google_account_email=google_account_email,
        )
    finally:
        await redis_pool.flushdb()
        await redis_pool.close()
