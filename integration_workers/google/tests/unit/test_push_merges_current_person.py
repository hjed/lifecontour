"""An update push reads the Google person first and merges into it (#1732).

``_update_or_recreate_contact_in_google`` is the one update path shared by the
cron push and the event push. It fetches the person as Google holds it, keeps
the values the local model cannot represent, and updates against the etag of
the version it merged with.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from google_client import GoogleContactNotFoundError
from worker import LinkSyncState, _update_or_recreate_contact_in_google

_REMOTE = "people/c1"


def _client(current: dict[str, Any]) -> AsyncMock:
    client = AsyncMock()
    client.get_person.return_value = current
    client.update_contact.return_value = {"resourceName": _REMOTE, "etag": "new"}
    return client


async def _push(
    client: AsyncMock,
    person_data: dict[str, Any],
    *,
    recorded_fallback: str | None = None,
) -> bool:
    """Push, with the link recording ``recorded_fallback`` from the last pull.

    The link records no base, and was synced at the person's current etag, so
    the person is its own base: these tests are about the read and the merge,
    not about entries Google gained since a pull (``test_push_three_way.py``).
    """
    current = client.get_person.return_value
    synced_at = (
        current.get("etag", "stored_etag") if isinstance(current, dict) else None
    )
    with patch(
        "worker._read_link_sync_state",
        new_callable=AsyncMock,
        return_value=LinkSyncState(address_fallback_country=recorded_fallback),
    ) as recorded:
        outcome = await _update_or_recreate_contact_in_google(
            AsyncMock(),
            client,
            contact_id=1,
            external_id=_REMOTE,
            person_data=person_data,
            etag=synced_at,
            user_id="1",
        )
    recorded.assert_awaited_once()
    return outcome.recreated


@pytest.mark.asyncio
async def test_update_keeps_the_values_google_holds_that_local_cannot() -> None:
    client = _client(
        {
            "etag": "fetched_etag",
            "names": [{"givenName": "Ada", "honorificPrefix": "Dr"}],
            "events": [{"type": "Graduation", "date": {"year": 2010}}],
        }
    )

    await _push(client, {"names": [{"givenName": "Augusta"}], "events": []})

    client.get_person.assert_awaited_once_with(_REMOTE)
    update = client.update_contact.await_args.kwargs
    assert update["resource_name"] == _REMOTE
    assert update["etag"] == "fetched_etag"
    assert update["contact_data"] == {
        "names": [{"givenName": "Augusta", "honorificPrefix": "Dr"}],
        "events": [{"type": "Graduation", "date": {"year": 2010}}],
    }


@pytest.mark.asyncio
async def test_a_conflict_retry_merges_into_the_refetched_person() -> None:
    """The client rebuilds the payload from the person it refetches (#1789).

    Google can change between the push's read and its write; the retry must
    keep what it gained, not resend the merge with the older read.
    """
    client = _client({"names": [{"honorificPrefix": "Dr"}]})

    await _push(client, {"names": [{"givenName": "Ada"}]})

    rebase = client.update_contact.await_args.kwargs["rebase"]
    refetched = {"etag": "e2", "names": [{"honorificPrefix": "Prof"}]}
    assert rebase(refetched) == {
        "names": [{"givenName": "Ada", "honorificPrefix": "Prof"}]
    }


@pytest.mark.asyncio
async def test_update_falls_back_to_the_stored_etag() -> None:
    client = _client({})

    await _push(client, {"names": [{"givenName": "Ada"}]})

    assert client.update_contact.await_args.kwargs["etag"] == "stored_etag"


@pytest.mark.asyncio
async def test_person_deleted_in_google_is_recreated_from_the_payload() -> None:
    client = AsyncMock()
    client.get_person.side_effect = GoogleContactNotFoundError(_REMOTE)
    client.create_contact.return_value = {"resourceName": "people/c2", "etag": "e"}

    recreated = await _push(client, {"names": [{"givenName": "Ada"}]})

    assert recreated is True
    client.update_contact.assert_not_awaited()
    client.create_contact.assert_awaited_once_with({"names": [{"givenName": "Ada"}]})


@pytest.mark.asyncio
async def test_update_merges_with_the_fallback_the_last_pull_recorded() -> None:
    """The merge owns what the last pull imported (#1820).

    Otherwise the countryless original is kept beside its pushed copy.
    """
    client = _client({"etag": "e", "addresses": [{"streetAddress": "1 Rd"}]})
    pushed = {"streetAddress": "1 Rd", "countryCode": "NZ"}

    await _push(client, {"addresses": [pushed]}, recorded_fallback="NZ")

    update = client.update_contact.await_args.kwargs
    assert update["contact_data"] == {"addresses": [pushed]}
    assert update["rebase"]({"addresses": [{"streetAddress": "1 Rd"}]}) == {
        "addresses": [pushed]
    }
