"""A push merges against the link's synced base and records the next one (#1861).

Against the real database, with only the Google client mocked:

* an email added in Google since the last pull survives a push of a local edit,
  and the link is marked ``pending_import`` so the next pull imports it;
* the base the push records comes from the person Google returns - what Google
  holds after the write, as Google formats it - less what local does not hold;
* the link's etag is the push's own, and ``last_synced_at`` moves on, so the
  contact is not pushed again until it changes.
"""

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest
from core_shared.sync_base import serialise_synced_entries
from core_shared.testing.seeding import seed_contact
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from google_client import GoogleContactNotFoundError
from synced_entries import raw_entry_keys, raw_synced_entries
from worker import find_contacts_to_push, push_contacts_to_google

CONTACT_OWNER = "1"
_REMOTE = "people/cBASE"
_CONTACT_SOURCE = {"source": {"type": "CONTACT", "id": "cBASE"}}

_HELD = {"value": "ada@example.com"}
_ADDED_IN_GOOGLE = {"value": "new@example.com"}


def _google(*entries: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"metadata": _CONTACT_SOURCE, **entry} for entry in entries]


def _key(field: Any, entry: dict[str, Any]) -> str:
    """The one key of an entry written only one way (an email)."""
    [key] = raw_entry_keys(field, entry, None)
    return key


async def _seed(
    db_session: AsyncSession,
    *,
    phone: str | None = None,
    base: dict[str, list[str]] | None = None,
) -> int:
    """A linked contact holding ``ada@example.com``, last synced an hour ago."""
    contact_id = await seed_contact(db_session, user_id=CONTACT_OWNER, first_name="Ada")
    await db_session.execute(
        text(
            "INSERT INTO contact_methods (contact_id, method_type, value, is_primary) "
            "VALUES (:cid, 'email', 'ada@example.com', true)"
        ),
        {"cid": contact_id},
    )
    if phone is not None:
        await db_session.execute(
            text(
                "INSERT INTO contact_methods (contact_id, method_type, value) "
                "VALUES (:cid, 'phone', :phone)"
            ),
            {"cid": contact_id, "phone": phone},
        )
    await db_session.execute(
        text(
            """
            INSERT INTO sync_metadata
                (user_id, internal_id, integration_source, external_id,
                 version_hash, sync_status, last_synced_at, reference_data,
                 created_at, updated_at)
            VALUES
                (:owner, :cid, 'google', :ext, 'etag_synced', 'success',
                 NOW() - interval '1 hour', :ref, NOW(), NOW())
            """
        ),
        {
            "owner": CONTACT_OWNER,
            "cid": contact_id,
            "ext": _REMOTE,
            "ref": None if base is None else json.dumps({"synced_entries": base}),
        },
    )
    await db_session.flush()
    return contact_id


def _client(current: dict[str, Any], returned: dict[str, Any]) -> AsyncMock:
    client = AsyncMock()
    client.get_person.return_value = {"resourceName": _REMOTE, **current}
    client.update_contact.return_value = {"resourceName": _REMOTE, **returned}
    client.create_contact.return_value = {"resourceName": "people/cNEW", **returned}
    return client


async def _push(db_session: AsyncSession, client: AsyncMock) -> dict[str, Any]:
    contacts = await find_contacts_to_push(db_session, user_id=CONTACT_OWNER)
    assert len(contacts) == 1
    return await push_contacts_to_google(
        session=db_session,
        client=client,
        contacts=contacts,
        google_account_email="base-it@example.com",
        user_id=CONTACT_OWNER,
    )


async def _link(db_session: AsyncSession) -> Any:
    result = await db_session.execute(
        text(
            """
            SELECT external_id, version_hash, reference_data
            FROM sync_metadata
            WHERE user_id = :owner AND integration_source = 'google'
            """
        ),
        {"owner": CONTACT_OWNER},
    )
    return result.one()


@pytest.mark.asyncio
async def test_an_email_added_in_google_since_the_pull_survives_the_push(
    db_session: AsyncSession,
) -> None:
    await _seed(db_session, base={"emailAddresses": [_key("emailAddresses", _HELD)]})
    after = _google(_HELD, _ADDED_IN_GOOGLE)
    client = _client(
        {"etag": "etag_google_edit", "emailAddresses": after},
        {"etag": "etag_pushed", "emailAddresses": after},
    )

    metrics = await _push(db_session, client)

    assert metrics["updated_count"] == 1
    pushed = client.update_contact.await_args.kwargs["contact_data"]
    assert pushed["emailAddresses"] == [
        {"value": "ada@example.com", "metadata": {"primary": True}},
        _ADDED_IN_GOOGLE,
    ]
    link = await _link(db_session)
    assert link.version_hash == "etag_pushed"
    recorded = json.loads(link.reference_data)
    # The kept email is not local's: it is the pull's to import, not the base's.
    assert recorded["synced_entries"]["emailAddresses"] == [
        _key("emailAddresses", _HELD)
    ]
    assert recorded["pending_import"] is True
    assert await find_contacts_to_push(db_session, user_id=CONTACT_OWNER) == []


@pytest.mark.asyncio
async def test_a_push_google_takes_whole_records_its_response_as_the_base(
    db_session: AsyncSession,
) -> None:
    """A phone typed locally comes back canonical; the base keys Google's copy."""
    await _seed(
        db_session,
        phone="0412 345 678",
        base={"emailAddresses": [_key("emailAddresses", _HELD)], "phoneNumbers": []},
    )
    returned = {
        "etag": "etag_pushed",
        "emailAddresses": _google(_HELD),
        "phoneNumbers": _google(
            {"value": "0412 345 678", "canonicalForm": "+61412345678"}
        ),
    }
    client = _client(
        {"etag": "etag_synced", "emailAddresses": _google(_HELD)}, returned
    )

    await _push(db_session, client)

    recorded = json.loads((await _link(db_session)).reference_data)
    assert recorded["synced_entries"] == serialise_synced_entries(
        raw_synced_entries(returned, None)
    )
    assert "pending_import" not in recorded


@pytest.mark.asyncio
async def test_a_phone_pushed_again_before_a_pull_is_not_duplicated(
    db_session: AsyncSession,
) -> None:
    """The second push merges into what the first left, keyed as Google holds it."""
    canonical = {"value": "0412 345 678", "canonicalForm": "+61412345678"}
    await _seed(
        db_session,
        phone="0412 345 678",
        base={
            "emailAddresses": [_key("emailAddresses", _HELD)],
            "phoneNumbers": sorted(raw_entry_keys("phoneNumbers", canonical, None)),
        },
    )
    held = {
        "etag": "etag_synced",
        "emailAddresses": _google(_HELD),
        "phoneNumbers": _google(canonical),
    }
    client = _client(held, {**held, "etag": "etag_pushed"})

    await _push(db_session, client)

    pushed = client.update_contact.await_args.kwargs["contact_data"]
    assert [phone["value"] for phone in pushed["phoneNumbers"]] == ["0412 345 678"]


@pytest.mark.asyncio
async def test_a_link_with_no_base_and_an_unchanged_person_owns_what_it_imports(
    db_session: AsyncSession,
) -> None:
    """Before bases were recorded: the etag still says nothing changed in Google."""
    await _seed(db_session)
    deleted_locally = {"value": "old@example.com"}
    client = _client(
        {"etag": "etag_synced", "emailAddresses": _google(_HELD, deleted_locally)},
        {"etag": "etag_pushed", "emailAddresses": _google(_HELD)},
    )

    await _push(db_session, client)

    pushed = client.update_contact.await_args.kwargs["contact_data"]
    assert [email["value"] for email in pushed["emailAddresses"]] == ["ada@example.com"]


@pytest.mark.asyncio
async def test_a_link_with_no_base_and_a_changed_person_keeps_every_entry(
    db_session: AsyncSession,
) -> None:
    """Nothing tells an addition in Google from a local deletion: keep both."""
    await _seed(db_session)
    client = _client(
        {
            "etag": "etag_google_edit",
            "emailAddresses": _google(_HELD, _ADDED_IN_GOOGLE),
        },
        {"etag": "etag_pushed", "emailAddresses": _google(_HELD, _ADDED_IN_GOOGLE)},
    )

    await _push(db_session, client)

    pushed = client.update_contact.await_args.kwargs["contact_data"]
    assert _ADDED_IN_GOOGLE in pushed["emailAddresses"]
    assert json.loads((await _link(db_session)).reference_data)["pending_import"]


@pytest.mark.asyncio
async def test_a_conflict_retry_records_what_the_retry_merged(
    db_session: AsyncSession,
) -> None:
    """Google gained the email between the read and the write (#1789)."""
    await _seed(db_session, base={"emailAddresses": [_key("emailAddresses", _HELD)]})
    refetched = {
        "resourceName": _REMOTE,
        "etag": "etag_raced",
        "emailAddresses": _google(_HELD, _ADDED_IN_GOOGLE),
    }
    client = _client(
        {"etag": "etag_synced", "emailAddresses": _google(_HELD)},
        {"etag": "etag_pushed", "emailAddresses": refetched["emailAddresses"]},
    )

    async def update_after_a_race(**kwargs: Any) -> dict[str, Any]:
        kwargs["rebase"](refetched)
        return client.update_contact.return_value

    client.update_contact.side_effect = update_after_a_race

    await _push(db_session, client)

    recorded = json.loads((await _link(db_session)).reference_data)
    assert recorded["synced_entries"]["emailAddresses"] == [
        _key("emailAddresses", _HELD)
    ]
    assert recorded["pending_import"] is True


@pytest.mark.asyncio
async def test_a_recreated_person_starts_a_fresh_base(
    db_session: AsyncSession,
) -> None:
    """The dead person's base described entries the new one never had."""
    await _seed(
        db_session,
        base={"emailAddresses": [_key("emailAddresses", _ADDED_IN_GOOGLE)]},
    )
    returned = {"etag": "etag_created", "emailAddresses": _google(_HELD)}
    client = _client({}, returned)
    client.get_person.side_effect = GoogleContactNotFoundError(_REMOTE)

    metrics = await _push(db_session, client)

    assert metrics["created_count"] == 1
    link = await _link(db_session)
    assert link.external_id == "people/cNEW"
    assert json.loads(link.reference_data)["synced_entries"] == (
        serialise_synced_entries(raw_synced_entries(returned, None))
    )


@pytest.mark.asyncio
async def test_a_second_push_before_the_pull_still_holds_back_a_google_deletion(
    db_session: AsyncSession,
) -> None:
    """The pull waits while local edits are unpushed, so pushes can repeat."""
    deleted_in_google = {"value": "old@example.com"}
    contact_id = await _seed(
        db_session,
        base={
            "emailAddresses": [
                _key("emailAddresses", _HELD),
                _key("emailAddresses", deleted_in_google),
            ]
        },
    )
    await db_session.execute(
        text(
            "INSERT INTO contact_methods (contact_id, method_type, value) "
            "VALUES (:cid, 'email', 'old@example.com')"
        ),
        {"cid": contact_id},
    )
    after = {"etag": "etag_pushed", "emailAddresses": _google(_HELD)}
    client = _client(
        {"etag": "etag_google_edit", **{k: v for k, v in after.items() if k != "etag"}},
        after,
    )
    await _push(db_session, client)

    # Another local edit lands before any pull is applied.
    await db_session.execute(
        text(
            "UPDATE sync_metadata SET last_synced_at = NOW() - interval '1 minute' "
            "WHERE external_id = :ext"
        ),
        {"ext": _REMOTE},
    )
    client.get_person.return_value = {"resourceName": _REMOTE, **after}
    await _push(db_session, client)

    pushed = client.update_contact.await_args.kwargs["contact_data"]
    assert [email["value"] for email in pushed["emailAddresses"]] == ["ada@example.com"]


@pytest.mark.asyncio
async def test_a_local_edit_landing_during_the_push_is_still_owed_a_push(
    db_session: AsyncSession,
) -> None:
    """The link records the version pushed, not when the push finished.

    Otherwise the edit reads as pushed: never sent, and a pull marked
    pending_import would apply Google's copy over it.
    """
    await _seed(db_session, base={"emailAddresses": [_key("emailAddresses", _HELD)]})
    after = _google(_HELD, _ADDED_IN_GOOGLE)
    client = _client(
        {"etag": "etag_google_edit", "emailAddresses": after},
        {"etag": "etag_pushed", "emailAddresses": after},
    )

    async def update_while_the_user_edits(**kwargs: Any) -> dict[str, Any]:
        await db_session.execute(
            text("UPDATE contacts SET updated_at = clock_timestamp()")
        )
        return client.update_contact.return_value

    client.update_contact.side_effect = update_while_the_user_edits

    await _push(db_session, client)

    assert len(await find_contacts_to_push(db_session, user_id=CONTACT_OWNER)) == 1


@pytest.mark.asyncio
async def test_a_conflict_retry_on_a_link_with_no_base_keeps_the_first_reads_base(
    db_session: AsyncSession,
) -> None:
    """The first read was the synced version; the retry's etag is Google's edit."""
    await _seed(db_session)
    deleted_locally = {"value": "old@example.com"}
    synced = {"etag": "etag_synced", "emailAddresses": _google(_HELD, deleted_locally)}
    raced = {
        "resourceName": _REMOTE,
        "etag": "etag_raced",
        "emailAddresses": _google(_HELD, deleted_locally),
        "names": [{"metadata": _CONTACT_SOURCE, "honorificPrefix": "Dr"}],
    }
    client = _client(synced, {"etag": "etag_pushed", "emailAddresses": _google(_HELD)})
    retried: list[dict[str, Any]] = []

    async def update_after_a_race(**kwargs: Any) -> dict[str, Any]:
        retried.append(kwargs["rebase"](raced))
        return client.update_contact.return_value

    client.update_contact.side_effect = update_after_a_race

    await _push(db_session, client)

    assert [email["value"] for email in retried[0]["emailAddresses"]] == [
        "ada@example.com"
    ]


@pytest.mark.asyncio
async def test_a_rename_after_the_push_read_the_name_is_still_owed_a_push(
    db_session: AsyncSession,
) -> None:
    """The cron reads names first; the version recorded must be that read's."""
    await _seed(db_session, base={"emailAddresses": [_key("emailAddresses", _HELD)]})
    contacts = await find_contacts_to_push(db_session, user_id=CONTACT_OWNER)
    await db_session.execute(
        text(
            "UPDATE contacts SET first_name = 'Augusta', updated_at = clock_timestamp()"
        )
    )
    held = {"etag": "etag_synced", "emailAddresses": _google(_HELD)}
    client = _client(held, {**held, "etag": "etag_pushed"})

    await push_contacts_to_google(
        session=db_session,
        client=client,
        contacts=contacts,
        google_account_email="base-it@example.com",
        user_id=CONTACT_OWNER,
    )

    assert len(await find_contacts_to_push(db_session, user_id=CONTACT_OWNER)) == 1
