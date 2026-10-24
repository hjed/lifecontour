"""Listing and dismissing the addresses an import skipped (#1820)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.config import Settings
from tests.integration.contact_import_issue_seeding import seed_skipped_address
from tests.integration.contact_seeding import OTHER_USER_ID, seed_contact

pytestmark = pytest.mark.integration

_ISSUES = "/api/integrations/import-issues"


async def test_lists_the_users_pending_issues_with_their_contact(
    authenticated_client: AsyncClient, async_connection: AsyncConnection
) -> None:
    kiri = await seed_contact(
        async_connection, first_name="Kiri", last_name="Te Kanawa"
    )
    issue_id = await seed_skipped_address(async_connection, kiri)
    await seed_skipped_address(async_connection, kiri, street="Old", status="dismissed")
    theirs = await seed_contact(async_connection, user_id=OTHER_USER_ID)
    await seed_skipped_address(async_connection, theirs, user_id=OTHER_USER_ID)

    response = await authenticated_client.get(_ISSUES)

    assert response.status_code == 200
    [issue] = response.json()["data"]
    assert issue["type"] == "contact-import-issues"
    assert issue["id"] == str(issue_id)
    attributes = issue["attributes"]
    assert attributes["contact_id"] == kiri
    assert attributes["contact_name"] == "Kiri Te Kanawa"
    assert attributes["integration_source"] == "google"
    assert attributes["reason"] == "unrecognised_region"
    assert attributes["address"]["street_line_1"] == "10 Downing St"
    assert attributes["address"]["region"] == "London"
    assert attributes["address"]["country_code"] == "AU"


async def test_filters_by_contact(
    authenticated_client: AsyncClient, async_connection: AsyncConnection
) -> None:
    kiri = await seed_contact(async_connection, first_name="Kiri")
    ana = await seed_contact(async_connection, first_name="Ana")
    await seed_skipped_address(async_connection, kiri)
    await seed_skipped_address(async_connection, ana)

    response = await authenticated_client.get(_ISSUES, params={"contact_id": ana})

    assert [i["attributes"]["contact_id"] for i in response.json()["data"]] == [ana]


async def test_another_users_contact_lists_nothing(
    authenticated_client: AsyncClient, async_connection: AsyncConnection
) -> None:
    theirs = await seed_contact(async_connection, user_id=OTHER_USER_ID)
    await seed_skipped_address(async_connection, theirs, user_id=OTHER_USER_ID)

    response = await authenticated_client.get(_ISSUES, params={"contact_id": theirs})

    assert response.status_code == 200
    assert response.json()["data"] == []


async def test_dismissing_an_issue_takes_it_off_the_list(
    authenticated_client: AsyncClient, async_connection: AsyncConnection
) -> None:
    kiri = await seed_contact(async_connection, first_name="Kiri")
    issue_id = await seed_skipped_address(async_connection, kiri)

    response = await authenticated_client.post(f"{_ISSUES}/{issue_id}/dismiss")

    assert response.status_code == 204
    assert (await authenticated_client.get(_ISSUES)).json()["data"] == []


@pytest.mark.parametrize("owner", ["missing", "other-user"])
async def test_dismissing_an_issue_the_user_does_not_hold_is_not_found(
    authenticated_client: AsyncClient, async_connection: AsyncConnection, owner: str
) -> None:
    """Another user's issue answers exactly as a missing one does."""
    if owner == "missing":
        issue_id = 999_999
    else:
        theirs = await seed_contact(async_connection, user_id=OTHER_USER_ID)
        issue_id = await seed_skipped_address(
            async_connection, theirs, user_id=OTHER_USER_ID
        )

    response = await authenticated_client.post(f"{_ISSUES}/{issue_id}/dismiss")

    assert response.status_code == 404


def _seed_body(contact_id: int) -> dict[str, object]:
    return {
        "data": {
            "type": "contact-import-issues",
            "attributes": {
                "contact_id": contact_id,
                "address": {
                    "street_line_1": "10 Downing St",
                    "region": "London",
                    "country_code": "AU",
                },
            },
        }
    }


async def test_the_test_only_create_is_off_by_default(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    test_settings: Settings,
) -> None:
    test_settings.enable_test_import_issues = False
    kiri = await seed_contact(async_connection, first_name="Kiri")

    response = await authenticated_client.post(_ISSUES, json=_seed_body(kiri))

    assert response.status_code == 404


async def test_the_test_only_create_records_a_skipped_address(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    test_settings: Settings,
) -> None:
    """For the e2e stack, which has no Google to skip one."""
    test_settings.enable_test_import_issues = True
    kiri = await seed_contact(async_connection, first_name="Kiri")

    response = await authenticated_client.post(_ISSUES, json=_seed_body(kiri))

    assert response.status_code == 201
    [issue] = (await authenticated_client.get(_ISSUES)).json()["data"]
    assert issue["id"] == response.json()["data"]["id"]
    assert issue["attributes"]["address"]["region"] == "London"


async def test_the_test_only_create_refuses_another_users_contact(
    authenticated_client: AsyncClient,
    async_connection: AsyncConnection,
    test_settings: Settings,
) -> None:
    test_settings.enable_test_import_issues = True
    theirs = await seed_contact(async_connection, user_id=OTHER_USER_ID)

    response = await authenticated_client.post(_ISSUES, json=_seed_body(theirs))

    assert response.status_code == 404
