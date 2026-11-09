"""A person a push just created is removed when its link can't be recorded.

Creating a Google person and recording its link can't share one transaction.
Left in Google without a link, the person is imported as a new contact by the
next pull while the original contact stays unlinked and is pushed as new again,
so one database failure repeats as a new duplicate on every sync.

Run against the real database with only the Google API client mocked, and the
link write made to fail at the point under test.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from core_shared.testing.seeding import seed_contact
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from google_client import GoogleContactNotFoundError
from worker import _push_contact_to_google_for_event, push_contacts_to_google

pytestmark = pytest.mark.asyncio

_OWNER = "1"
_ACCOUNT = "link-failure@example.com"
_NEW_REMOTE = "people/cNEW"
_LINKED_REMOTE = "people/cLINKED"

_LINK_RECORD = "worker.IntegrationLinkRepository.patch_reference_data"
_LINK_REPOINT = "worker._repoint_sync_link"


class _LinkWriteFailedError(Exception):
    """The failure the tests make recording a link raise."""


def _failing_link_write(target: str) -> Any:
    return patch(target, AsyncMock(side_effect=_LinkWriteFailedError("no link")))


def _client(*, linked_person_deleted: bool = False) -> AsyncMock:
    client = AsyncMock()
    client.get_person.return_value = {}
    client.create_contact.return_value = {
        "resourceName": _NEW_REMOTE,
        "etag": "etag_new",
    }
    if linked_person_deleted:
        client.update_contact.side_effect = GoogleContactNotFoundError(_LINKED_REMOTE)
    else:
        client.update_contact.return_value = {
            "resourceName": _LINKED_REMOTE,
            "etag": "etag_updated",
        }
    return client


async def _links_to(session: AsyncSession, external_id: str) -> int:
    result = await session.execute(
        text(
            "SELECT count(*) FROM sync_metadata "
            "WHERE integration_source = 'google' AND external_id = :external_id"
        ),
        {"external_id": external_id},
    )
    return int(result.scalar_one())


@pytest_asyncio.fixture
async def unlinked_contact_id(db_session: AsyncSession) -> int:
    contact_id: int = await seed_contact(
        db_session, first_name="Never", last_name="Linked", user_id=_OWNER
    )
    await db_session.flush()
    return contact_id


@pytest_asyncio.fixture
async def linked_contact_id(db_session: AsyncSession) -> int:
    contact_id: int = await seed_contact(
        db_session, first_name="Already", last_name="Linked", user_id=_OWNER
    )
    await db_session.execute(
        text(
            """
            INSERT INTO sync_metadata
                (user_id, internal_id, integration_source, external_id,
                 version_hash, sync_status, last_synced_at)
            VALUES (:owner, :cid, 'google', :ext, 'etag_old', 'success', NOW())
            """
        ),
        {"owner": _OWNER, "cid": contact_id, "ext": _LINKED_REMOTE},
    )
    await db_session.flush()
    return contact_id


async def _push_update_for_event(
    session: AsyncSession, client: AsyncMock, contact_id: int
) -> dict[str, Any]:
    return await _push_contact_to_google_for_event(
        session,
        client,
        contact_id,
        "update",
        _ACCOUNT,
        _LINKED_REMOTE,
        "etag_old",
        user_id=_OWNER,
    )


async def test_cron_create_removes_the_person_when_the_link_fails(
    db_session: AsyncSession, unlinked_contact_id: int
) -> None:
    client = _client()

    with _failing_link_write(_LINK_RECORD):
        metrics = await push_contacts_to_google(
            session=db_session,
            client=client,
            contacts=[
                {
                    "id": unlinked_contact_id,
                    "first_name": "Never",
                    "last_name": "Linked",
                    "sync_action": "create",
                    "external_id": None,
                }
            ],
            google_account_email=_ACCOUNT,
            group_name_to_resource={},
            user_id=_OWNER,
        )

    client.delete_contact.assert_awaited_once_with(_NEW_REMOTE)
    assert metrics["error_count"] == 1
    assert metrics["created_count"] == 0
    assert await _links_to(db_session, _NEW_REMOTE) == 0


async def test_event_create_removes_the_person_and_reraises(
    db_session: AsyncSession, unlinked_contact_id: int
) -> None:
    client = _client()

    with (
        _failing_link_write(_LINK_RECORD),
        pytest.raises(_LinkWriteFailedError),
    ):
        await _push_contact_to_google_for_event(
            db_session,
            client,
            unlinked_contact_id,
            "create",
            _ACCOUNT,
            None,
            None,
            user_id=_OWNER,
        )

    client.delete_contact.assert_awaited_once_with(_NEW_REMOTE)


@pytest.mark.parametrize("failing_write", [_LINK_REPOINT, _LINK_RECORD])
async def test_recreate_removes_only_the_new_person_when_the_link_fails(
    db_session: AsyncSession, linked_contact_id: int, failing_write: str
) -> None:
    client = _client(linked_person_deleted=True)

    with (
        _failing_link_write(failing_write),
        pytest.raises(_LinkWriteFailedError),
    ):
        await _push_update_for_event(db_session, client, linked_contact_id)

    client.delete_contact.assert_awaited_once_with(_NEW_REMOTE)


async def test_ordinary_update_keeps_the_person_when_the_link_fails(
    db_session: AsyncSession, linked_contact_id: int
) -> None:
    client = _client()

    with (
        _failing_link_write(_LINK_RECORD),
        pytest.raises(_LinkWriteFailedError),
    ):
        await _push_update_for_event(db_session, client, linked_contact_id)

    client.update_contact.assert_awaited_once()
    client.delete_contact.assert_not_awaited()


async def test_failed_removal_does_not_hide_the_link_failure(
    db_session: AsyncSession, unlinked_contact_id: int
) -> None:
    client = _client()
    client.delete_contact.side_effect = RuntimeError("Google is unavailable")

    with (
        _failing_link_write(_LINK_RECORD),
        pytest.raises(_LinkWriteFailedError),
    ):
        await _push_contact_to_google_for_event(
            db_session,
            client,
            unlinked_contact_id,
            "create",
            _ACCOUNT,
            None,
            None,
            user_id=_OWNER,
        )

    client.delete_contact.assert_awaited_once_with(_NEW_REMOTE)
