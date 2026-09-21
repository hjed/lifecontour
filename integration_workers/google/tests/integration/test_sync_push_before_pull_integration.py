"""Integration coverage for the push that runs before the inbound pull.

LOCAL-177: the periodic cron enqueued only the inbound ``sync_google_contacts``.
``push_local_contacts_to_google`` existed but nothing called it, so outbound sync
had no reconciliation path — a push lost to a worker restart or a Redis trim was
never retried, and the next pull applied Google's older copy over the local edit.

``sync_google_contacts`` now pushes pending local changes first. These tests run
the real task against a real database with only the Google API client mocked, so
they cover the query that finds pending contacts, the ordering against the pull,
and what happens when the push fails.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from worker import sync_google_contacts

_EMAIL = "push-before-pull@example.com"
_REMOTE = "people/c-push-before-pull"


def _ctx(db_session: AsyncSession) -> dict[str, Any]:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    return {
        "session_factory": factory,
        "redis": None,
        "job_id": "push-before-pull-it",
    }


def _mock_google_client() -> AsyncMock:
    """A client that reports no remote changes and accepts writes."""
    client = AsyncMock()
    client.update_contact.return_value = {
        "resourceName": _REMOTE,
        "etag": "etag-after-push",
    }
    client.create_contact.return_value = {
        "resourceName": _REMOTE,
        "etag": "etag-after-push",
    }
    client.list_contact_groups.return_value = {"contactGroups": []}
    client.list_connections.return_value = {
        "connections": [],
        "nextSyncToken": "token-1",
    }
    return client


@pytest_asyncio.fixture
async def contact_edited_since_last_sync(db_session: AsyncSession) -> int:
    """A Google-linked contact whose local edit has not been pushed yet.

    ``last_synced_at`` is backdated so ``find_contacts_to_push`` sees
    ``contacts.updated_at`` as newer — the state a lost outbound push leaves.
    """
    now = datetime.now(UTC)
    await db_session.execute(
        text(
            """
            INSERT INTO user_google_auth (
                user_id, google_account_email,
                encrypted_access_token, encrypted_refresh_token,
                expires_at, created_at, updated_at
            ) VALUES ('1', :email, :token, :refresh, :expiry, :now, :now)
            ON CONFLICT (user_id, google_account_email) DO NOTHING
            """
        ),
        {
            "email": _EMAIL,
            "token": b"x",
            "refresh": b"y",
            "expiry": now + timedelta(hours=1),
            "now": now,
        },
    )

    result = await db_session.execute(
        text(
            """
            INSERT INTO contacts (first_name, last_name, updated_at)
            VALUES ('Pending', 'Push', :now)
            RETURNING id
            """
        ),
        {"now": now},
    )
    contact_id = int(result.scalar_one())

    await db_session.execute(
        text(
            """
            INSERT INTO contact_methods (contact_id, method_type, value, is_primary)
            VALUES (:cid, 'email', 'edited-locally@example.com', true)
            """
        ),
        {"cid": contact_id},
    )

    await db_session.execute(
        text(
            """
            INSERT INTO sync_metadata
                (internal_id, integration_source, external_id,
                 version_hash, sync_status, last_synced_at,
                 internal_entity_type, external_entity_type,
                 created_at, updated_at)
            VALUES (:cid, 'google', :ext, 'etag-before', 'success', :stale,
                    'contact', 'person', :stale, :stale)
            """
        ),
        {
            "cid": contact_id,
            "ext": _REMOTE,
            "stale": now - timedelta(hours=1),
        },
    )
    await db_session.flush()

    return contact_id


@pytest.mark.asyncio
class TestSyncPushesPendingChangesFirst:
    """The inbound sync reconciles outbound work before it pulls."""

    async def test_pending_local_edit_is_pushed_during_the_sync(
        self, db_session: AsyncSession, contact_edited_since_last_sync: int
    ) -> None:
        """A contact modified since its last sync reaches Google.

        Before this change nothing pushed it: the cron was inbound-only, so the
        edit sat locally until a pull overwrote it.
        """
        mock_client = _mock_google_client()

        with (
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=mock_client),
        ):
            result = await sync_google_contacts(
                ctx=_ctx(db_session),
                google_account_email=_EMAIL,
                user_id=1,
                sync_type="incremental",
            )

        assert result["status"] == "success"
        assert result["pushed_count"] == 1
        assert result["push_failed"] is False

        pushed = mock_client.update_contact.call_args[1]["contact_data"]
        assert [entry["value"] for entry in pushed["emailAddresses"]] == [
            "edited-locally@example.com"
        ]

    async def test_push_happens_before_the_first_read_from_google(
        self, db_session: AsyncSession, contact_edited_since_last_sync: int
    ) -> None:
        """Ordering is what stops the pull clobbering the edit, so assert it."""
        mock_client = _mock_google_client()
        call_order: list[str] = []

        async def record_update(**_kwargs: Any) -> dict[str, str]:
            call_order.append("push")
            return {"resourceName": _REMOTE, "etag": "etag-after-push"}

        async def record_list(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            call_order.append("pull")
            return {"connections": [], "nextSyncToken": "token-1"}

        mock_client.update_contact.side_effect = record_update
        mock_client.list_connections.side_effect = record_list

        with (
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=mock_client),
        ):
            await sync_google_contacts(
                ctx=_ctx(db_session),
                google_account_email=_EMAIL,
                user_id=1,
                sync_type="incremental",
            )

        assert call_order[0] == "push"
        assert "pull" in call_order

    async def test_sync_metadata_is_advanced_so_the_pull_skips_the_contact(
        self, db_session: AsyncSession, contact_edited_since_last_sync: int
    ) -> None:
        """After the push, the stored etag matches Google's current one.

        That is what makes the following pull a no-op for this contact rather
        than a re-apply of Google's older copy.
        """
        mock_client = _mock_google_client()

        with (
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=mock_client),
        ):
            await sync_google_contacts(
                ctx=_ctx(db_session),
                google_account_email=_EMAIL,
                user_id=1,
                sync_type="incremental",
            )

        result = await db_session.execute(
            text(
                """
                SELECT version_hash FROM sync_metadata
                WHERE integration_source = 'google' AND internal_id = :cid
                """
            ),
            {"cid": contact_edited_since_last_sync},
        )
        assert result.scalar_one() == "etag-after-push"

    async def test_a_failing_push_does_not_stop_the_pull(
        self, db_session: AsyncSession, contact_edited_since_last_sync: int
    ) -> None:
        """Inbound sync must survive a Google write outage."""
        mock_client = _mock_google_client()
        mock_client.list_contact_groups.side_effect = RuntimeError("Google is down")

        with (
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=mock_client),
            patch(
                "worker._push_pending_local_contacts",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Google is down"),
            ),
        ):
            result = await sync_google_contacts(
                ctx=_ctx(db_session),
                google_account_email=_EMAIL,
                user_id=1,
                sync_type="incremental",
            )

        assert result["status"] == "success"
        assert result["push_failed"] is True
        mock_client.list_connections.assert_awaited()
