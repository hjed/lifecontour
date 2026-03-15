"""End-to-end integration test for the Google Calendar → Journal sync flow.

Mirrors the contacts sync E2E test pattern: loads the worker module, sets up
a real database with test data, runs the ARQ worker in burst mode, and
validates that outbox events are created and processed into journals.
"""

import importlib.util
import os
import sys
from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlparse
from uuid import UUID, uuid4

import pytest
from arq import create_pool
from arq.connections import RedisSettings
from arq.jobs import Job, JobStatus
from arq.worker import Worker
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.core.integrations.database import IntegrationDatabaseManager
from app.core.integrations.task_queue_service import ARQ_QUEUE_NAME

TEST_REDIS_DATABASE = 15
WORKER_DIRECTORY = (
    Path(__file__).resolve().parents[5] / "integration_workers" / "google"
)
WORKER_TEST_MODULE_PREFIX = "google_calendar_e2e_"
WORKER_ENVIRONMENT_VARIABLES = (
    "DATABASE_URL",
    "REDIS_URL",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "ENCRYPTION_KEY",
    "WORKER_ID",
    "LOG_LEVEL",
)


# ── Helpers (shared with contacts E2E test) ──────────────────────────


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
        import asyncio

        await asyncio.sleep(0)

    def __getattr__(self, name: str) -> Any:
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
        "WORKER_ID": "google-calendar-e2e-test-worker",
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
        module_name, WORKER_DIRECTORY / "worker.py"
    )
    if module_spec is None or module_spec.loader is None:
        raise ImportError("Could not load Google worker module spec")
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
    parsed = urlparse(redis_url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=database,
    )


# ── Calendar-specific helpers ────────────────────────────────────────


TEST_CALENDAR_UUID = UUID("aaaabbbb-cccc-dddd-eeee-ffffffffffff")


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
        text("""
            INSERT INTO user_google_auth (
                user_id, google_account_email,
                encrypted_access_token, encrypted_refresh_token,
                expires_at, created_at, updated_at
            ) VALUES (
                :user_id, :email, :access_token, :refresh_token,
                :expires_at, :created_at, :updated_at
            )
        """),
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


async def _insert_synced_calendar(
    connection: AsyncConnection,
    *,
    user_id: str,
    calendar_id: UUID,
    google_calendar_id: str = "primary",
) -> None:
    """Insert a calendar that is synced to Google."""
    await connection.execute(
        text("""
            INSERT INTO calendars (
                id, user_id, name, color,
                is_synced_to_google, google_calendar_id
            ) VALUES (
                :id, :user_id, :name, :color,
                true, :google_calendar_id
            )
        """),
        {
            "id": calendar_id,
            "user_id": user_id,
            "name": "Test Calendar",
            "color": "#3B82F6",
            "google_calendar_id": google_calendar_id,
        },
    )


async def _insert_google_integration(
    connection: AsyncConnection,
    *,
    email: str,
    user_id: str,
) -> None:
    """Insert user_google_integration row."""
    await connection.execute(
        text("""
            INSERT INTO user_google_integration (
                google_account_email, user_id,
                created_at, updated_at
            ) VALUES (
                :email, :user_id,
                NOW(), NOW()
            )
        """),
        {"email": email, "user_id": user_id},
    )


def _build_mock_calendar_list_events() -> dict[str, Any]:
    """Build a mock response for Google Calendar events list API."""
    return {
        "items": [
            {
                "id": "google-event-e2e-1",
                "summary": "E2E Team Standup",
                "description": "Daily standup meeting",
                "status": "confirmed",
                "etag": '"etag-e2e-123"',
                "start": {"dateTime": "2026-03-20T09:00:00+10:00"},
                "end": {"dateTime": "2026-03-20T09:30:00+10:00"},
                "location": "Room 42",
                "attendees": [
                    {
                        "email": "invitee-e2e@example.com",
                        "responseStatus": "accepted",
                    },
                    {
                        "email": "unknown-e2e@example.com",
                        "responseStatus": "needsAction",
                    },
                ],
            }
        ],
        "nextSyncToken": "calendar-sync-token-after-e2e",
    }


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
        await OutboxProcessor(AsyncMock()).process_events()


async def _run_calendar_sync_worker(
    *,
    worker_module: ModuleType,
    redis_pool: Any,
    db_manager: IntegrationDatabaseManager,
    job_id: str,
    mock_events: dict[str, Any],
) -> None:
    """Run the sync_calendar_events ARQ task in burst mode."""
    arq_worker = Worker(
        functions=[worker_module.sync_calendar_events],
        redis_pool=redis_pool,
        queue_name=ARQ_QUEUE_NAME,
        burst=True,
        max_jobs=1,
        handle_signals=False,
        ctx={"session_factory": db_manager.get_session, "redis": redis_pool},
    )

    # Mock _create_google_client to return a client with mocked list_events
    mock_client = MagicMock()
    mock_client.list_events = AsyncMock(return_value=mock_events)

    # Ensure worker directory is in sys.path for imports like calendar_models
    sys.path.insert(0, str(WORKER_DIRECTORY))
    try:
        with patch.object(
            worker_module,
            "_create_google_client",
            new_callable=AsyncMock,
            return_value=mock_client,
        ):
            await arq_worker.async_run()
    finally:
        while str(WORKER_DIRECTORY) in sys.path:
            sys.path.remove(str(WORKER_DIRECTORY))

    arq_job = Job(job_id, redis=redis_pool)
    assert await arq_job.status() == JobStatus.complete
    result = await arq_job.result(timeout=1)
    assert result["status"] == "success"


# ── E2E Test ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_calendar_sync_flow_runs_through_arq_and_outbox(
    async_connection: AsyncConnection,
    clean_database: None,
    test_settings: Any,
) -> None:
    """Full E2E: Google Calendar API → worker → outbox → processor → journal in DB."""
    _ = clean_database
    now = datetime.now(UTC)
    future_expiry = now + timedelta(hours=1)
    test_email = "calendar-sync-e2e@example.com"
    test_user_id = "456"
    fernet_key = Fernet.generate_key()
    fernet = Fernet(fernet_key)

    worker = _load_worker_module(
        str(test_settings.database_url),
        test_settings.redis_url,
        fernet_key.decode(),
    )
    redis_settings = _build_test_redis_settings(test_settings.redis_url)
    redis_pool = await create_pool(redis_settings)
    db_manager = _SavepointDbManager(async_connection)

    try:
        await redis_pool.flushdb()

        # ── Step 1: Set up test data ─────────────────────────────────
        await _insert_google_auth_tokens(
            async_connection,
            user_id=test_user_id,
            email=test_email,
            fernet=fernet,
            expires_at=future_expiry,
            now=now,
        )
        await _insert_google_integration(
            async_connection,
            email=test_email,
            user_id=test_user_id,
        )
        await _insert_synced_calendar(
            async_connection,
            user_id=test_user_id,
            calendar_id=TEST_CALENDAR_UUID,
            google_calendar_id="primary",
        )

        # Insert a test contact whose email matches the mock attendee
        await async_connection.execute(
            text("""
                INSERT INTO contacts (first_name, last_name)
                VALUES ('E2E', 'Invitee')
            """),
        )
        contact_id = (
            await async_connection.execute(
                text("""
                    SELECT id FROM contacts
                    WHERE first_name = 'E2E'
                """),
            )
        ).scalar_one()
        await async_connection.execute(
            text("""
                INSERT INTO contact_methods (contact_id, method_type, value, is_primary)
                VALUES (:contact_id, 'email', :email, true)
            """),
            {"contact_id": contact_id, "email": "invitee-e2e@example.com"},
        )

        # ── Step 2: Enqueue the sync task ────────────────────────────
        job = await redis_pool.enqueue_job(
            "sync_calendar_events",
            test_email,
            test_user_id,
            "full",
            _queue_name=ARQ_QUEUE_NAME,
        )
        assert job is not None
        job_id = job.job_id

        # ── Step 3: Run the worker ────────────────────────────────────
        mock_events = _build_mock_calendar_list_events()
        await _run_calendar_sync_worker(
            worker_module=worker,
            redis_pool=redis_pool,
            db_manager=db_manager,
            job_id=job_id,
            mock_events=mock_events,
        )

        # ── Step 4: Assert outbox events were created ────────────────
        outbox_rows = list(
            (
                await async_connection.execute(
                    text("""
                        SELECT event_type, processed_at
                        FROM outbox_events
                        WHERE event_type LIKE 'journal_event.%'
                        ORDER BY event_type
                    """)
                )
            ).fetchall()
        )
        assert len(outbox_rows) >= 1, (
            f"Expected journal_event outbox events, got: {outbox_rows}"
        )
        assert outbox_rows[0][0] == "journal_event.created"
        assert outbox_rows[0][1] is None  # Not yet processed

        # ── Step 5: Run the outbox processor ─────────────────────────
        await _run_outbox_processor(async_connection)

        # ── Step 6: Assert journal created in DB ─────────────────────
        journal_row = (
            await async_connection.execute(
                text("""
                    SELECT id, title, content
                    FROM journals
                    WHERE user_id = :user_id AND title = :title
                """),
                {"user_id": test_user_id, "title": "E2E Team Standup"},
            )
        ).fetchone()
        assert journal_row is not None, "Expected journal to be created"
        assert journal_row.title == "E2E Team Standup"
        assert journal_row.content == "Daily standup meeting"

        # ── Step 7: Assert external event link created ───────────────
        link_row = (
            await async_connection.execute(
                text("""
                    SELECT external_event_id, external_version, sync_status
                    FROM journal_external_event_links
                    WHERE journal_id = :journal_id
                      AND calendar_id = :calendar_id
                """),
                {
                    "journal_id": journal_row.id,
                    "calendar_id": TEST_CALENDAR_UUID,
                },
            )
        ).fetchone()
        assert link_row is not None, "Expected external event link"
        assert link_row.external_event_id == "google-event-e2e-1"
        assert link_row.external_version == '"etag-e2e-123"'
        assert link_row.sync_status == "synced"

        # ── Step 8: Assert sync token saved ──────────────────────────
        sync_token = (
            await async_connection.execute(
                text("""
                    SELECT calendar_events_sync_token
                    FROM user_google_integration
                    WHERE google_account_email = :email
                """),
                {"email": test_email},
            )
        ).scalar_one()
        assert sync_token == "calendar-sync-token-after-e2e"

        # ── Step 9: Assert outbox events now processed ───────────────
        processed_rows = list(
            (
                await async_connection.execute(
                    text("""
                        SELECT event_type, processed_at IS NOT NULL
                        FROM outbox_events
                        WHERE event_type LIKE 'journal_event.%'
                        ORDER BY event_type
                    """)
                )
            ).fetchall()
        )
        assert all(row[1] for row in processed_rows), (
            f"All journal_event outbox events should be processed: {processed_rows}"
        )

        # ── Step 10: Assert invitee relationship created ─────────────
        invitee_rows = list(
            (
                await async_connection.execute(
                    text("""
                        SELECT contact_id, relationship_type
                        FROM journal_contact_relationships
                        WHERE journal_id = :journal_id
                    """),
                    {"journal_id": journal_row.id},
                )
            ).fetchall()
        )
        # Only the known contact (invitee-e2e@example.com) should appear
        assert len(invitee_rows) == 1, (
            f"Expected 1 INVITEE relationship, got: {invitee_rows}"
        )
        assert invitee_rows[0].contact_id == contact_id
        assert invitee_rows[0].relationship_type == "INVITEE"

    finally:
        await redis_pool.flushdb()
        await redis_pool.close()
