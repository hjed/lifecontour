"""Integration tests for the contact-suggestion REST endpoints.

Exercises ``/api/integrations/contact-suggestions`` end-to-end through the
``authenticated_client``. Unmatched participant emails are seeded directly on
the test's savepoint connection, which the client's requests share.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.core.integrations.contact_suggestion_seeding import (
    create_contact,
    journal_relationships,
    seed_participant,
)

pytestmark = pytest.mark.asyncio

BASE_URL = "/api/integrations/contact-suggestions"
IGNORED_URL = f"{BASE_URL}/ignored"


def _accept_body(email: str, target: dict[str, Any]) -> dict[str, Any]:
    return {
        "data": {
            "type": "contact-suggestion-acceptances",
            "attributes": {"email": email, "target": target},
        }
    }


def _ignore_body(email: str) -> dict[str, Any]:
    return {
        "data": {"type": "ignored-contact-suggestions", "attributes": {"email": email}}
    }


async def test_list_returns_suggestions(
    authenticated_client: AsyncClient, async_connection: AsyncConnection
) -> None:
    await seed_participant(async_connection, "jane@x.com", 6, display_name="Jane S")
    await seed_participant(async_connection, "rare@x.com", 4)

    response = await authenticated_client.get(BASE_URL)

    assert response.status_code == 200
    [resource] = response.json()["data"]
    assert resource["type"] == "contact-suggestions"
    assert resource["id"] == "jane@x.com"
    attributes = resource["attributes"]
    assert attributes["email"] == "jane@x.com"
    assert attributes["display_name"] == "Jane S"
    assert attributes["event_count"] == 6
    assert attributes["last_seen_at"] is not None


async def test_accept_as_new_contact(
    authenticated_client: AsyncClient, async_connection: AsyncConnection
) -> None:
    journal_ids = await seed_participant(async_connection, "jane@x.com", 5)

    response = await authenticated_client.post(
        f"{BASE_URL}/accept",
        json=_accept_body(
            "jane@x.com", {"kind": "new", "first_name": "Jane", "last_name": "Smith"}
        ),
    )

    assert response.status_code == 201
    resource = response.json()["data"]
    assert resource["type"] == "contact-suggestion-acceptances"
    assert resource["id"] == "jane@x.com"
    attributes = resource["attributes"]
    assert attributes["linked_journal_count"] == 5
    contact_id = attributes["contact_id"]
    assert set(await journal_relationships(async_connection, contact_id)) == set(
        journal_ids
    )
    assert (await authenticated_client.get(BASE_URL)).json()["data"] == []


async def test_accept_into_existing_contact(
    authenticated_client: AsyncClient, async_connection: AsyncConnection
) -> None:
    contact_id = await create_contact(async_connection, first_name="Jane")
    await seed_participant(async_connection, "jane@x.com", 5)

    response = await authenticated_client.post(
        f"{BASE_URL}/accept",
        json=_accept_body("jane@x.com", {"kind": "existing", "contact_id": contact_id}),
    )

    assert response.status_code == 201
    assert response.json()["data"]["attributes"]["contact_id"] == contact_id


async def test_accept_into_unknown_contact_is_404(
    authenticated_client: AsyncClient,
) -> None:
    response = await authenticated_client.post(
        f"{BASE_URL}/accept",
        json=_accept_body("jane@x.com", {"kind": "existing", "contact_id": 999_999}),
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        _accept_body("not-an-email", {"kind": "new", "first_name": "Jane"}),
        _accept_body("jane@x.com", {"kind": "new", "first_name": "  "}),
        _accept_body("jane@x.com", {"kind": "merge", "contact_id": 1}),
    ],
    ids=["bad-email", "blank-name", "unknown-kind"],
)
async def test_accept_rejects_invalid_bodies(
    authenticated_client: AsyncClient, body: dict[str, Any]
) -> None:
    response = await authenticated_client.post(f"{BASE_URL}/accept", json=body)

    assert response.status_code == 400


async def test_ignore_hides_the_suggestion_until_restored(
    authenticated_client: AsyncClient, async_connection: AsyncConnection
) -> None:
    await seed_participant(async_connection, "noisy@x.com", 5)

    ignored = await authenticated_client.post(
        IGNORED_URL, json=_ignore_body("Noisy@X.com")
    )
    assert ignored.status_code == 201
    assert ignored.json()["data"]["id"] == "noisy@x.com"
    assert (await authenticated_client.get(BASE_URL)).json()["data"] == []

    listed = (await authenticated_client.get(IGNORED_URL)).json()["data"]
    assert [(r["type"], r["id"]) for r in listed] == [
        ("ignored-contact-suggestions", "noisy@x.com")
    ]

    restored = await authenticated_client.delete(f"{IGNORED_URL}/noisy@x.com")
    assert restored.status_code == 204
    assert [
        r["id"] for r in (await authenticated_client.get(BASE_URL)).json()["data"]
    ] == ["noisy@x.com"]
