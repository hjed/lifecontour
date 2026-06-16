"""Integration tests for the ContactMerged handler against a real database.

ITER13-005 Phase 2: a contact merge that collides on the same external service
(both contacts linked to Google) surfaces the clash on
``ContactMerged.external_collisions``. The Google worker deletes the source
contact's orphaned *remote* record (using ``source_external_id`` from the
payload — the local sync_metadata was already removed by Phase 1) and reuses
the existing delete flow to clean any residual sync_metadata, while leaving the
survivor's link intact. A different-service merge triggers no Google deletion.

These tests exercise the real database via ``db_session`` (real sync_metadata /
user_google_auth rows) while mocking only the Google API client so no remote
call is made.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from worker import process_contact_event

_SURVIVOR_REMOTE = "people/survivor456"
_SOURCE_REMOTE = "people/source123"


def _session_factory(db_session: AsyncSession) -> Any:
    """Build a session_factory that yields the test's transactional session."""

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    return factory


def _ctx(db_session: AsyncSession) -> dict[str, Any]:
    return {"session_factory": _session_factory(db_session), "job_id": "evt-merge-it"}


def _google_collision() -> dict[str, str]:
    return {
        "external_system": "google",
        "external_entity_type": "person",
        "source_external_id": _SOURCE_REMOTE,
        "survivor_external_id": _SURVIVOR_REMOTE,
    }


async def _seed_google_account(db_session: AsyncSession) -> None:
    """Seed a single connected Google account (queryable by the handler)."""
    await db_session.execute(
        text(
            """
            INSERT INTO user_google_auth (
                user_id, google_account_email,
                encrypted_access_token, encrypted_refresh_token,
                expires_at, created_at, updated_at
            ) VALUES (
                :user_id, :email, :token, :refresh, NOW(), NOW(), NOW()
            )
            ON CONFLICT (user_id, google_account_email) DO NOTHING
            """
        ),
        {
            "user_id": "1",
            "email": "merge-it@example.com",
            "token": b"x",
            "refresh": b"y",
        },
    )


async def _seed_sync_metadata(
    db_session: AsyncSession, internal_id: int, external_id: str
) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO sync_metadata
                (internal_id, integration_source, external_id,
                 version_hash, sync_status, last_synced_at,
                 created_at, updated_at)
            VALUES
                (:cid, 'google', :ext, 'etag', 'success', NOW(), NOW(), NOW())
            """
        ),
        {"cid": internal_id, "ext": external_id},
    )


async def _external_ids(db_session: AsyncSession) -> set[str]:
    result = await db_session.execute(
        text(
            "SELECT external_id FROM sync_metadata WHERE integration_source = 'google'"
        )
    )
    return {row.external_id for row in result.fetchall()}


@pytest_asyncio.fixture
async def merge_setup(db_session: AsyncSession) -> AsyncSession:
    """Seed a Google account plus survivor and source sync_metadata rows."""
    await _seed_google_account(db_session)
    await _seed_sync_metadata(db_session, internal_id=1, external_id=_SURVIVOR_REMOTE)
    # In production Phase 1 removes the source's local row inline; we seed a
    # residual row here to deterministically prove the worker's reuse of the
    # existing delete flow cleans it (idempotent if it was already gone).
    await _seed_sync_metadata(db_session, internal_id=2, external_id=_SOURCE_REMOTE)
    await db_session.flush()
    return db_session


@pytest.mark.asyncio
class TestContactMergedGoogleReconciliation:
    """Real-DB coverage for the ContactMerged Google reconciliation handler."""

    async def test_same_service_merge_deletes_source_remote_and_cleans_metadata(
        self, merge_setup: AsyncSession
    ) -> None:
        """Same-service collision deletes the source remote and its sync metadata."""
        db_session = merge_setup
        mock_client = AsyncMock()

        with (
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=mock_client),
        ):
            result = await process_contact_event(
                ctx=_ctx(db_session),
                event_type="ContactMerged",
                event_data={
                    "survivor_contact_id": 1,
                    "source_contact_id": 2,
                    "external_collisions": [_google_collision()],
                },
            )

        assert result["status"] == "success"
        # The source remote — and only the source remote — was deleted.
        mock_client.delete_contact.assert_called_once_with(resource_name=_SOURCE_REMOTE)

        remaining = await _external_ids(db_session)
        assert _SOURCE_REMOTE not in remaining  # source sync_metadata cleaned
        assert _SURVIVOR_REMOTE in remaining  # survivor link preserved

    async def test_different_service_merge_triggers_no_google_deletion(
        self, merge_setup: AsyncSession
    ) -> None:
        """A collision on a non-Google service performs no Google deletion."""
        db_session = merge_setup
        mock_client = AsyncMock()

        immich_collision = {
            "external_system": "immich",
            "external_entity_type": "person",
            "source_external_id": "person-abc",
            "survivor_external_id": "person-def",
        }

        with (
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=mock_client),
        ):
            result = await process_contact_event(
                ctx=_ctx(db_session),
                event_type="ContactMerged",
                event_data={
                    "survivor_contact_id": 1,
                    "source_contact_id": 2,
                    "external_collisions": [immich_collision],
                },
            )

        assert result["status"] == "skipped"
        assert result["reason"] == "no_google_collisions"
        mock_client.delete_contact.assert_not_called()

        remaining = await _external_ids(db_session)
        # Both Google links untouched by an Immich-only collision.
        assert {_SURVIVOR_REMOTE, _SOURCE_REMOTE} <= remaining

    async def test_404_on_source_remote_treated_as_success(
        self, merge_setup: AsyncSession
    ) -> None:
        """A remote 404 (swallowed by the client) still cleans up and succeeds."""
        db_session = merge_setup
        # google_client.delete_contact swallows a 404 and returns normally; the
        # handler must treat that as success and still clean the local metadata.
        mock_client = AsyncMock()
        mock_client.delete_contact.return_value = None

        with (
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=mock_client),
        ):
            result = await process_contact_event(
                ctx=_ctx(db_session),
                event_type="ContactMerged",
                event_data={
                    "survivor_contact_id": 1,
                    "source_contact_id": 2,
                    "external_collisions": [_google_collision()],
                },
            )

        assert result["status"] == "success"
        remaining = await _external_ids(db_session)
        assert _SOURCE_REMOTE not in remaining
        assert _SURVIVOR_REMOTE in remaining
