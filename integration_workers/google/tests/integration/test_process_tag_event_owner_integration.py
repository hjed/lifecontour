"""A tag rename or delete reaches only its owner's Google accounts.

Contact tags are per user, so two users may each hold a ``Work`` tag mirrored
as a ``Work`` contact group. ``process_tag_event`` must rename or delete the
group in the tag owner's account only: the other user's ``Work`` group is a
different group that merely shares the name. Two real ``user_google_auth`` rows
prove the owner filter is in the SQL; only the Google client is mocked.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from worker import process_tag_event

_OWNER = "tag-owner"
_OTHER = "other-user"


def _ctx(db_session: AsyncSession) -> dict[str, Any]:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    return {"session_factory": factory, "job_id": "tag-owner-it"}


async def _seed_google_account(db_session: AsyncSession, user_id: str) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO user_google_auth (
                user_id, google_account_email,
                encrypted_access_token, encrypted_refresh_token,
                expires_at, created_at, updated_at
            ) VALUES (:user_id, :email, :token, :refresh, NOW(), NOW(), NOW())
            """
        ),
        {
            "user_id": user_id,
            "email": f"{user_id}@example.com",
            "token": b"x",
            "refresh": b"y",
        },
    )


async def _run(
    db_session: AsyncSession, event_type: str, event_data: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, MagicMock]]:
    """Run the task with one mocked client per account; return them by owner."""
    await _seed_google_account(db_session, _OWNER)
    await _seed_google_account(db_session, _OTHER)
    clients: dict[str, MagicMock] = {}

    def make_client(**kwargs: Any) -> AsyncMock:
        client = AsyncMock()
        clients[kwargs["user_id"]] = client
        return client

    with (
        patch("worker.GoogleAuthService"),
        patch("worker.GoogleAPIClient", side_effect=make_client),
        patch(
            "worker._build_contact_group_mapping",
            new_callable=AsyncMock,
            return_value={"contactGroups/work": "Work"},
        ),
    ):
        result = await process_tag_event(
            _ctx(db_session), event_type=event_type, event_data=event_data
        )
    return result, clients


@pytest.mark.integration
@pytest.mark.asyncio
class TestTagEventsReachOnlyTheOwner:
    async def test_a_rename_touches_only_the_owners_account(
        self, db_session: AsyncSession
    ) -> None:
        result, clients = await _run(
            db_session,
            "TagUpdated",
            {
                "tag_id": 1,
                "tag_name": "Office",
                "changed_fields": {"full_path": ("Work", "Office")},
                "user_id": _OWNER,
            },
        )

        assert result["status"] == "success"
        assert list(clients) == [_OWNER]
        clients[_OWNER].update_contact_group.assert_awaited_once_with(
            "contactGroups/work", "Office"
        )

    async def test_a_delete_touches_only_the_owners_account(
        self, db_session: AsyncSession
    ) -> None:
        result, clients = await _run(
            db_session,
            "TagDeleted",
            {"tag_id": 1, "tag_name": "Work", "user_id": _OWNER},
        )

        assert result["status"] == "success"
        assert list(clients) == [_OWNER]
        clients[_OWNER].delete_contact_group.assert_awaited_once_with(
            "contactGroups/work"
        )

    async def test_an_event_without_an_owner_touches_no_account(
        self, db_session: AsyncSession
    ) -> None:
        result, clients = await _run(
            db_session, "TagDeleted", {"tag_id": 1, "tag_name": "Work"}
        )

        assert result == {"status": "skipped", "reason": "no_owner"}
        assert clients == {}
