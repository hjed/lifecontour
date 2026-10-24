"""A contact push keeps the Google data the local model cannot represent.

Google replaces every field the push names in ``updatePersonFields``
wholesale. Driven through the event push (the path that loads company and job
title) against the real database, with only the Google client mocked, the
update must carry the local contact's values merged into the person Google
holds: its honorifics, custom events and other organizations survive (#1732),
and so do the entries inbound sync never imported - an address with no country
code and none to infer (#1820), and a text-only birthday, which leaves the
update mask (#1788).
"""

import json
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
    "addresses": [
        {
            "metadata": _CONTACT_SOURCE,
            "streetAddress": "1 Old St",
            "countryCode": "AU",
        },
        {"metadata": _CONTACT_SOURCE, "streetAddress": "2 Nowhere Rd", "city": "Leeds"},
    ],
    "birthdays": [{"metadata": _CONTACT_SOURCE, "text": "sometime in December"}],
}


def _ctx(db_session: AsyncSession) -> dict[str, Any]:
    """An ARQ context whose session factory yields the test's session."""

    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    return {"session_factory": factory, "job_id": "evt-merge-it"}


async def _seed_linked_contact(db_session: AsyncSession) -> int:
    """The local contact linked to ``_REMOTE``, with a GB address of its own."""
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
            INSERT INTO contact_addresses
                (contact_id, street_line_1, country_code, is_primary)
            VALUES (:cid, '12 St James Sq', 'GB', true)
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
                (:owner, :cid, 'google', :ext, 'etag_current', 'success',
                 NOW(), NOW(), NOW())
            """
        ),
        {"owner": CONTACT_OWNER, "cid": contact_id, "ext": _REMOTE},
    )
    await db_session.flush()
    return contact_id


async def _push_update(db_session: AsyncSession, contact_id: int) -> AsyncMock:
    """Run the event push for ``contact_id``; the Google client it used."""
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
    return client


@pytest.mark.asyncio
async def test_update_push_merges_into_the_person_google_holds(
    db_session: AsyncSession,
) -> None:
    client = await _push_update(db_session, await _seed_linked_contact(db_session))

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
    assert person["addresses"] == [
        {
            "streetAddress": "12 St James Sq",
            "countryCode": "GB",
            "metadata": {"primary": True},
        },
        {"streetAddress": "2 Nowhere Rd", "city": "Leeds"},
    ]
    assert "birthdays" not in person
    # A conflict retry merges the same local values into the person the client
    # refetches, keeping what Google gained after the first read.
    refetched = {**_CURRENT_PERSON, "names": [{"honorificPrefix": "Prof"}]}
    assert update["rebase"](refetched)["names"] == [
        {"givenName": "Ada", "familyName": "Lovelace", "honorificPrefix": "Prof"}
    ]


@pytest.mark.asyncio
async def test_a_countryless_address_the_last_pull_imported_is_not_kept(
    db_session: AsyncSession,
) -> None:
    """The link records the pull gave it a country, so the push owns it (#1820).

    The pull imported it with that country and the push sends the local list,
    so keeping Google's countryless copy would hold the address twice.
    """
    contact_id = await _seed_linked_contact(db_session)
    await db_session.execute(
        text(
            """
            UPDATE sync_metadata SET reference_data = :ref
            WHERE user_id = :owner AND external_id = :ext
            """
        ),
        {
            "owner": CONTACT_OWNER,
            "ext": _REMOTE,
            "ref": json.dumps({"address_fallback_country": "GB"}),
        },
    )

    client = await _push_update(db_session, contact_id)

    person = client.update_contact.await_args.kwargs["contact_data"]
    assert person["addresses"] == [
        {
            "streetAddress": "12 St James Sq",
            "countryCode": "GB",
            "metadata": {"primary": True},
        }
    ]


@pytest.mark.asyncio
async def test_a_default_country_no_pull_has_applied_keeps_the_address(
    db_session: AsyncSession,
) -> None:
    """A default set since the last pull imports nothing yet: keep the address."""
    contact_id = await _seed_linked_contact(db_session)
    await db_session.execute(
        text(
            "INSERT INTO user_settings (user_id, default_country) VALUES (:owner, 'GB')"
        ),
        {"owner": CONTACT_OWNER},
    )

    client = await _push_update(db_session, contact_id)

    person = client.update_contact.await_args.kwargs["contact_data"]
    assert {"streetAddress": "2 Nowhere Rd", "city": "Leeds"} in person["addresses"]
