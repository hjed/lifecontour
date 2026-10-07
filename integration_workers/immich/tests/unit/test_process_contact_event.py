# ruff: noqa: E402
"""Unit tests for the Immich outbound contact push (``process_contact_event``).

A contact event names the contact's owner in ``user_id``. The push goes to that
user's Immich account only, and an event that names no owner is skipped rather
than pushed to every connected account.
"""

import os

db_port = os.environ.get("DB_TEST_PORT", "5432")
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = (
        f"postgresql+asyncpg://postgres:postgres@localhost:{db_port}"
        "/personal_management_test"
    )
os.environ.setdefault("ENCRYPTION_KEY", "testkey")

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from core_shared.testing import make_session_factory_mock


def _make_ctx(session_factory: Any) -> dict[str, Any]:
    return {"session_factory": session_factory, "job_id": "evt-contact-unit"}


@pytest.mark.asyncio
class TestPushGoesToTheOwnerOnly:
    """The owner's Immich account is the only one read or written."""

    async def test_event_without_owner_is_skipped(self) -> None:
        """No owner: no session, no credentials read, no push."""
        from worker import process_contact_event

        factory = make_session_factory_mock()

        with (
            patch("worker.ImmichAuthService") as auth_cls,
            patch("worker.ImmichSyncService") as sync_cls,
        ):
            result = await process_contact_event(
                ctx=_make_ctx(factory),
                event_type="ContactUpdated",
                event_data={"contact_id": 42},
            )

        assert result == {"status": "skipped", "reason": "no_owner"}
        factory.assert_not_called()
        auth_cls.assert_not_called()
        sync_cls.assert_not_called()

    async def test_pushes_with_the_owners_account_only(self) -> None:
        """Credentials are read for the owner and the push runs as the owner."""
        from worker import process_contact_event

        factory = make_session_factory_mock()
        auth = MagicMock()
        auth.get_api_key = AsyncMock(return_value="key")
        auth.get_server_url = AsyncMock(return_value="https://immich.example")
        sync_service = MagicMock()
        sync_service.sync_contact_outbound = AsyncMock(return_value={"ok": True})

        with (
            patch("worker.ImmichAuthService", return_value=auth),
            patch("worker.ImmichApiClient") as client_cls,
            patch("worker.ImmichSyncService", return_value=sync_service) as sync_cls,
        ):
            client_cls.create.return_value = AsyncMock()
            result = await process_contact_event(
                ctx=_make_ctx(factory),
                event_type="ContactUpdated",
                event_data={"user_id": "owner-a", "contact_id": 42},
            )

        assert result["status"] == "success"
        assert [r["user_id"] for r in result["results"]] == ["owner-a"]
        assert [c.args[0] for c in auth.get_api_key.await_args_list] == ["owner-a"]
        sync_cls.assert_called_once()
        assert sync_cls.call_args.kwargs["user_id"] == "owner-a"
        sync_service.sync_contact_outbound.assert_awaited_once_with(42)

    async def test_owner_without_immich_is_skipped(self) -> None:
        """An owner with no Immich credentials gets no push."""
        from worker import process_contact_event

        factory = make_session_factory_mock()
        auth = MagicMock()
        auth.get_api_key = AsyncMock(return_value=None)
        auth.get_server_url = AsyncMock(return_value=None)

        with (
            patch("worker.ImmichAuthService", return_value=auth),
            patch("worker.ImmichSyncService") as sync_cls,
        ):
            result = await process_contact_event(
                ctx=_make_ctx(factory),
                event_type="ContactUpdated",
                event_data={"user_id": "owner-a", "contact_id": 42},
            )

        assert result["results"] == [{"user_id": "owner-a", "status": "skipped"}]
        sync_cls.assert_not_called()
