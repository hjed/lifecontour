"""Archived emails, phones and addresses through the contacts API.

An archived value is one the person no longer uses: it is kept and read back,
it is never primary, and archiving the primary value demotes it.
"""

from typing import Any

import pytest
from httpx import AsyncClient


def _method(
    method_type: str, value: str, *, is_primary: bool = False, is_archived: bool = False
) -> dict[str, Any]:
    return {
        "type": "contact_methods",
        "attributes": {
            "method_type": method_type,
            "value": value,
            "is_primary": is_primary,
            "is_archived": is_archived,
        },
    }


def _address(
    street: str, *, is_primary: bool = False, is_archived: bool = False
) -> dict[str, Any]:
    return {
        "type": "contact_addresses",
        "attributes": {
            "street_line_1": street,
            "country_code": "AU",
            "is_primary": is_primary,
            "is_archived": is_archived,
        },
    }


async def _create(
    client: AsyncClient,
    *,
    methods: list[dict[str, Any]],
    addresses: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    response = await client.post(
        "/api/contacts",
        json={
            "data": {
                "type": "contacts",
                "attributes": {
                    "first_name": "Archie",
                    "contact_methods": methods,
                    "addresses": addresses or [],
                    "notes": [],
                },
            }
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]  # type: ignore[no-any-return]


async def _get(client: AsyncClient, contact_id: str) -> dict[str, Any]:
    response = await client.get(f"/api/contacts/{contact_id}")
    assert response.status_code == 200, response.text
    return response.json()["data"]["attributes"]  # type: ignore[no-any-return]


async def _patch_field(
    client: AsyncClient, path: str, value: object
) -> tuple[int, dict[str, Any]]:
    response = await client.patch(path, json={"data": {"attributes": {"value": value}}})
    return response.status_code, response.json()


@pytest.mark.integration
class TestArchivedContactFields:
    @pytest.mark.asyncio
    async def test_create_reads_archived_values_back(
        self, authenticated_client: AsyncClient
    ) -> None:
        created = await _create(
            authenticated_client,
            methods=[
                _method("email", "now@example.com", is_primary=True),
                _method("phone", "+61 2 1234 5678", is_archived=True),
            ],
            addresses=[_address("1 Childhood Rd", is_archived=True)],
        )

        attributes = await _get(authenticated_client, created["id"])

        archived = {
            m["attributes"]["value"]: m["attributes"]["is_archived"]
            for m in attributes["contact_methods"]
        }
        assert archived == {"now@example.com": False, "+61 2 1234 5678": True}
        assert [a["attributes"]["is_archived"] for a in attributes["addresses"]] == [
            True
        ]

    @pytest.mark.asyncio
    async def test_create_refuses_an_archived_primary(
        self, authenticated_client: AsyncClient
    ) -> None:
        response = await authenticated_client.post(
            "/api/contacts",
            json={
                "data": {
                    "type": "contacts",
                    "attributes": {
                        "first_name": "Archie",
                        "contact_methods": [
                            _method(
                                "email",
                                "x@example.com",
                                is_primary=True,
                                is_archived=True,
                            )
                        ],
                        "addresses": [],
                        "notes": [],
                    },
                }
            },
        )

        assert response.status_code == 400
        assert "cannot be primary" in response.text

    @pytest.mark.asyncio
    async def test_add_method_endpoint_accepts_is_archived(
        self, authenticated_client: AsyncClient
    ) -> None:
        created = await _create(authenticated_client, methods=[])

        response = await authenticated_client.post(
            f"/api/contacts/{created['id']}/methods",
            json={"data": _method("phone", "+44 20 7946 0000", is_archived=True)},
        )

        assert response.status_code == 201, response.text
        methods = response.json()["data"]["attributes"]["contact_methods"]
        assert [m["attributes"]["is_archived"] for m in methods] == [True]

    @pytest.mark.asyncio
    async def test_archiving_the_primary_method_demotes_it(
        self, authenticated_client: AsyncClient
    ) -> None:
        created = await _create(
            authenticated_client,
            methods=[_method("email", "only@example.com", is_primary=True)],
        )
        method_id = created["attributes"]["contact_methods"][0]["id"]

        status, _ = await _patch_field(
            authenticated_client,
            f"/api/contacts/{created['id']}/methods/{method_id}/fields/is_archived",
            True,
        )

        assert status == 200
        method = (await _get(authenticated_client, created["id"]))["contact_methods"][
            0
        ]["attributes"]
        assert method["is_archived"] is True
        assert method["is_primary"] is False

    @pytest.mark.asyncio
    async def test_restoring_a_method_does_not_make_it_primary(
        self, authenticated_client: AsyncClient
    ) -> None:
        created = await _create(
            authenticated_client,
            methods=[_method("phone", "+61 2 1234 5678", is_archived=True)],
        )
        method_id = created["attributes"]["contact_methods"][0]["id"]

        status, _ = await _patch_field(
            authenticated_client,
            f"/api/contacts/{created['id']}/methods/{method_id}/fields/is_archived",
            False,
        )

        assert status == 200
        method = (await _get(authenticated_client, created["id"]))["contact_methods"][
            0
        ]["attributes"]
        assert method["is_archived"] is False
        assert method["is_primary"] is False

    @pytest.mark.asyncio
    async def test_an_archived_method_cannot_be_made_primary(
        self, authenticated_client: AsyncClient
    ) -> None:
        created = await _create(
            authenticated_client,
            methods=[_method("phone", "+61 2 1234 5678", is_archived=True)],
        )
        method_id = created["attributes"]["contact_methods"][0]["id"]

        status, body = await _patch_field(
            authenticated_client,
            f"/api/contacts/{created['id']}/methods/{method_id}/fields/is_primary",
            True,
        )

        assert status == 422
        assert "archived" in str(body)

    @pytest.mark.asyncio
    async def test_archiving_the_primary_address_demotes_it(
        self, authenticated_client: AsyncClient
    ) -> None:
        created = await _create(
            authenticated_client,
            methods=[],
            addresses=[_address("1 Home St", is_primary=True)],
        )
        address_id = created["attributes"]["addresses"][0]["id"]

        status, _ = await _patch_field(
            authenticated_client,
            f"/api/contacts/{created['id']}/addresses/{address_id}/fields/is_archived",
            "true",
        )

        assert status == 200
        address = (await _get(authenticated_client, created["id"]))["addresses"][0][
            "attributes"
        ]
        assert address["is_archived"] is True
        assert address["is_primary"] is False

    @pytest.mark.asyncio
    async def test_an_archived_address_cannot_be_made_primary(
        self, authenticated_client: AsyncClient
    ) -> None:
        created = await _create(
            authenticated_client,
            methods=[],
            addresses=[_address("1 Old St", is_archived=True)],
        )
        address_id = created["attributes"]["addresses"][0]["id"]

        status, body = await _patch_field(
            authenticated_client,
            f"/api/contacts/{created['id']}/addresses/{address_id}/fields/is_primary",
            True,
        )

        assert status == 422
        assert "archived" in str(body)

    @pytest.mark.asyncio
    async def test_whole_contact_put_keeps_archived_values(
        self, authenticated_client: AsyncClient
    ) -> None:
        """The profile form sends the lists it read back; nothing is un-archived."""
        created = await _create(
            authenticated_client,
            methods=[
                _method("email", "now@example.com", is_primary=True),
                _method("email", "then@example.com", is_archived=True),
            ],
            addresses=[_address("1 Childhood Rd", is_archived=True)],
        )
        attributes = await _get(authenticated_client, created["id"])

        response = await authenticated_client.put(
            f"/api/contacts/{created['id']}",
            json={
                "data": {
                    "type": "contacts",
                    "id": created["id"],
                    "attributes": {**attributes, "first_name": "Archibald"},
                }
            },
        )

        assert response.status_code == 200, response.text
        after = await _get(authenticated_client, created["id"])
        assert after["first_name"] == "Archibald"
        assert {
            m["attributes"]["value"]: m["attributes"]["is_archived"]
            for m in after["contact_methods"]
        } == {"now@example.com": False, "then@example.com": True}
        assert [a["attributes"]["is_archived"] for a in after["addresses"]] == [True]
