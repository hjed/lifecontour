"""Integration tests for recreating a contact deleted on Google's side.

A contact linked to a Google person that no longer exists makes
``updateContact`` return 404. Rather than failing the push forever, the worker
recreates the person from the local contact and re-points the contact's single
``sync_metadata`` link at the new resource name.

Both outbound paths are covered — the event handler and the cron push — against
the real database, with only the Google API client mocked.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from core_shared.testing.seeding import seed_contact
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from google_client import GoogleContactNotFoundError
from worker import process_contact_event, push_contacts_to_google

_DELETED_REMOTE = "people/cDELETED"
_RECREATED_REMOTE = "people/cRECREATED"
# The backend's record of which tags were last synced; losing it makes an
# inbound Google tag removal look like a local-only tag to keep.
_REFERENCE_DATA = '{"synced_tags": ["friends"]}'


def _ctx(db_session: AsyncSession) -> dict[str, Any]:
    """An ARQ context whose session factory yields the test's session."""

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    return {"session_factory": factory, "job_id": "evt-recreate-it"}


def _client_for_deleted_remote() -> AsyncMock:
    """A Google client whose linked person was deleted on Google's side.

    ``update_contact`` stamps the etag onto the payload before the request
    fails, exactly as the real client does, so the recreate must strip it.
    """

    async def update_contact(
        resource_name: str, contact_data: dict[str, Any], etag: str | None = None
    ) -> dict[str, Any]:
        if etag:
            contact_data["etag"] = etag
        raise GoogleContactNotFoundError(resource_name)

    client = AsyncMock()
    client.update_contact.side_effect = update_contact
    client.create_contact.return_value = {
        "resourceName": _RECREATED_REMOTE,
        "etag": "etag_recreated",
    }
    client.list_contact_groups.return_value = {"contactGroups": []}
    return client


@pytest_asyncio.fixture
async def linked_contact_id(db_session: AsyncSession) -> int:
    """A local contact whose Google link points at a deleted person."""
    contact_id: int = await seed_contact(
        db_session, first_name="Recreate", last_name="Me"
    )
    await db_session.execute(
        text(
            """
            INSERT INTO sync_metadata
                (internal_id, integration_source, external_id,
                 version_hash, sync_status, last_synced_at, reference_data,
                 created_at, updated_at)
            VALUES
                (:cid, 'google', :ext, 'etag_stale', 'success', NOW(), :ref,
                 NOW(), NOW())
            """
        ),
        {"cid": contact_id, "ext": _DELETED_REMOTE, "ref": _REFERENCE_DATA},
    )
    await db_session.flush()
    return contact_id


async def _google_links(
    db_session: AsyncSession, contact_id: int
) -> list[tuple[str, str | None, str]]:
    """The contact's Google links as (external_id, reference_data, etag)."""
    result = await db_session.execute(
        text(
            """
            SELECT external_id, reference_data, version_hash FROM sync_metadata
            WHERE integration_source = 'google' AND internal_id = :cid
            """
        ),
        {"cid": contact_id},
    )
    return [
        (row.external_id, row.reference_data, row.version_hash)
        for row in result.fetchall()
    ]


def _created_payload(client: AsyncMock) -> dict[str, Any]:
    client.create_contact.assert_called_once()
    payload: dict[str, Any] = client.create_contact.call_args.args[0]
    return payload


@pytest.mark.asyncio
class TestRecreateContactDeletedOnGoogle:
    """A push to a deleted Google person recreates it and relinks the contact."""

    async def test_contact_event_recreates_and_relinks(
        self, db_session: AsyncSession, linked_contact_id: int
    ) -> None:
        """The event path recreates the person and replaces the dead link."""
        await db_session.execute(
            text(
                """
                INSERT INTO user_google_auth (
                    user_id, google_account_email,
                    encrypted_access_token, encrypted_refresh_token,
                    expires_at, created_at, updated_at
                ) VALUES ('1', 'recreate-it@example.com', :token, :refresh,
                          NOW(), NOW(), NOW())
                ON CONFLICT (user_id, google_account_email) DO NOTHING
                """
            ),
            {"token": b"x", "refresh": b"y"},
        )
        client = _client_for_deleted_remote()

        with (
            patch("worker.GoogleAuthService"),
            patch("worker.GoogleAPIClient", return_value=client),
        ):
            result = await process_contact_event(
                ctx=_ctx(db_session),
                event_type="ContactUpdated",
                event_data={"contact_id": linked_contact_id, "changed_fields": {}},
            )

        assert result["status"] == "success"
        assert result["results"] == [
            {"status": "recreated", "resource_name": _RECREATED_REMOTE}
        ]
        client.update_contact.assert_called_once()
        assert client.update_contact.call_args.kwargs["resource_name"] == (
            _DELETED_REMOTE
        )
        payload = _created_payload(client)
        assert "etag" not in payload
        assert "resourceName" not in payload
        assert payload["names"][0]["givenName"] == "Recreate"
        # One link, re-pointed at the new person, keeping its reference data.
        assert await _google_links(db_session, linked_contact_id) == [
            (_RECREATED_REMOTE, _REFERENCE_DATA, "etag_recreated")
        ]

    async def test_cron_push_recreates_and_relinks(
        self, db_session: AsyncSession, linked_contact_id: int
    ) -> None:
        """The cron push recreates the person, counts it created, and relinks."""
        client = _client_for_deleted_remote()

        metrics = await push_contacts_to_google(
            session=db_session,
            client=client,
            contacts=[
                {
                    "id": linked_contact_id,
                    "sync_action": "update",
                    "external_id": _DELETED_REMOTE,
                    "version_hash": "etag_stale",
                }
            ],
            google_account_email="recreate-it@example.com",
            group_name_to_resource={},
        )

        assert metrics["pushed_count"] == 1
        assert metrics["created_count"] == 1
        assert metrics["updated_count"] == 0
        assert metrics["error_count"] == 0
        payload = _created_payload(client)
        assert "etag" not in payload
        assert "resourceName" not in payload
        # One link, re-pointed at the new person, keeping its reference data.
        assert await _google_links(db_session, linked_contact_id) == [
            (_RECREATED_REMOTE, _REFERENCE_DATA, "etag_recreated")
        ]
