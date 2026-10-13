"""An update push reads the Google person first and merges into it (#1732).

``_update_or_recreate_contact_in_google`` is the one update path shared by the
cron push and the event push. It fetches the person as Google holds it, keeps
the values the local model cannot represent, and updates against the etag of
the version it merged with.
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest

from google_client import GoogleContactNotFoundError
from worker import _update_or_recreate_contact_in_google

_REMOTE = "people/c1"


def _client(current: dict[str, Any]) -> AsyncMock:
    client = AsyncMock()
    client.get_person.return_value = current
    client.update_contact.return_value = {"resourceName": _REMOTE, "etag": "new"}
    return client


async def _push(client: AsyncMock, person_data: dict[str, Any]) -> bool:
    _, recreated = await _update_or_recreate_contact_in_google(
        AsyncMock(),
        client,
        contact_id=1,
        external_id=_REMOTE,
        person_data=person_data,
        etag="stored_etag",
        user_id="1",
    )
    return recreated


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
    client.update_contact.assert_awaited_once_with(
        resource_name=_REMOTE,
        contact_data={
            "names": [{"givenName": "Augusta", "honorificPrefix": "Dr"}],
            "events": [{"type": "Graduation", "date": {"year": 2010}}],
        },
        etag="fetched_etag",
    )


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
