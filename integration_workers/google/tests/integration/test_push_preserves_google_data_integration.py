"""A contact push keeps the Google data the local model cannot represent (#1732).

The push names ``names``, ``events`` and ``organizations`` in
``updatePersonFields``, and Google replaces each wholesale. Driven through the
event push (the path that loads company and job title) against the real database, with only the Google client mocked, the
update must carry the local contact's values merged into the person Google
holds: its honorifics, custom events and other organizations survive.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from core_shared.testing.seeding import seed_contact
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from worker import process_contact_event

# The connected Google user these tests push for, and so the owner of
# every contact they seed.
CONTACT_OWNER = "1"

_REMOTE = "people/cMERGE"
_CONTACT_SOURCE = {"source": {"type": "CONTACT", "id": "cMERGE"}}

# The person as Google holds it: values the local model cannot represent sit
# beside the ones it owns.
_CURRENT_PERSON: dict[str, Any] = {
    "resourceName": _REMOTE,
    "etag": "etag_current",
    "names": [
        {
            "metadata": {"primary": True, **_CONTACT_SOURCE},
            "givenName": "Old",
            "familyName": "Name",
            "honorificPrefix": "Dr",
        }
    ],
    "events": [
        {
            "metadata": _CONTACT_SOURCE,
            "date": {"year": 2001, "month": 2, "day": 3},
            "type": "anniversary",
        },
        {
            "metadata": _CONTACT_SOURCE,
            "date": {"year": 2010, "month": 3, "day": 4},
            "type": "Graduation",
        },
    ],
    "organizations": [
        {
            "metadata": _CONTACT_SOURCE,
            "name": "Old Engines",
            "department": "R&D",
            "current": True,
        },
        {"metadata": _CONTACT_SOURCE, "name": "Previous Co", "current": False},
    ],
}


def _ctx(db_session: AsyncSession) -> dict[str, Any]:
    """An ARQ context whose session factory yields the test's session."""

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    return {"session_factory": factory, "job_id": "evt-merge-it"}


@pytest.mark.asyncio
async def test_update_push_merges_into_the_person_google_holds(
    db_session: AsyncSession,
) -> None:
    contact_id = await seed_contact(
        db_session,
        user_id=CONTACT_OWNER,
        first_name="Ada",
        last_name="Lovelace",
        company="Analytical Engines",
        job_title="Analyst",
    )
    await db_session.execute(
        text(
            """
            INSERT INTO contact_important_dates
                (contact_id, date_type, precision, year, month, day)
            VALUES (:cid, 'marriage_anniversary', 'full', 1835, 7, 8)
            """
        ),
        {"cid": contact_id},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO sync_metadata
                (user_id, internal_id, integration_source, external_id,
                 version_hash, sync_status, last_synced_at,
                 created_at, updated_at)
            VALUES
                (:owner, :cid, 'google', :ext, 'etag_stored', 'success',
                 NOW(), NOW(), NOW())
            """
        ),
        {"owner": CONTACT_OWNER, "cid": contact_id, "ext": _REMOTE},
    )
    await db_session.flush()

    client = AsyncMock()
    client.get_person.return_value = _CURRENT_PERSON
    client.update_contact.return_value = {"resourceName": _REMOTE, "etag": "new"}
    client.list_contact_groups.return_value = {"contactGroups": []}

    await db_session.execute(
        text(
            """
            INSERT INTO user_google_auth (
                user_id, google_account_email,
                encrypted_access_token, encrypted_refresh_token,
                expires_at, created_at, updated_at
            ) VALUES (:owner, 'merge-it@example.com', :token, :refresh,
                      NOW(), NOW(), NOW())
            ON CONFLICT (user_id, google_account_email) DO NOTHING
            """
        ),
        {"owner": CONTACT_OWNER, "token": b"x", "refresh": b"y"},
    )
    await db_session.flush()

    with (
        patch("worker.GoogleAuthService"),
        patch("worker.GoogleAPIClient", return_value=client),
    ):
        result = await process_contact_event(
            ctx=_ctx(db_session),
            event_type="ContactUpdated",
            event_data={
                "user_id": CONTACT_OWNER,
                "contact_id": contact_id,
                "changed_fields": {},
            },
        )

    assert result["results"] == [{"status": "updated", "resource_name": _REMOTE}]
    client.get_person.assert_awaited_once_with(_REMOTE)
    update = client.update_contact.await_args.kwargs
    assert update["etag"] == "etag_current"
    person = update["contact_data"]
    assert person["names"] == [
        {"givenName": "Ada", "familyName": "Lovelace", "honorificPrefix": "Dr"}
    ]
    assert person["events"] == [
        {"date": {"year": 1835, "month": 7, "day": 8}, "type": "anniversary"},
        {"date": {"year": 2010, "month": 3, "day": 4}, "type": "Graduation"},
    ]
    assert person["organizations"] == [
        {
            "department": "R&D",
            "current": True,
            "name": "Analytical Engines",
            "title": "Analyst",
        },
        {"name": "Previous Co", "current": False},
    ]
