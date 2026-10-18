"""``PATCH /api/contacts/{id}/fields/{field}`` changes the one field it names."""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.parametrize("field_name", ["first_name", "nick_name"])
async def test_editing_one_field_keeps_every_other_field(
    integration_api_client: AsyncClient, field_name: str
) -> None:
    """Inline-editing a name must not clear the company or job title beside it."""
    created = await integration_api_client.post(
        "/api/contacts",
        json={
            "data": {
                "type": "contacts",
                "attributes": {
                    "first_name": "Ada",
                    "nick_name": "Countess",
                    "company": "Analytical Engines Ltd",
                    "job_title": "Programmer",
                    "contact_methods": [],
                    "addresses": [],
                    "notes": [],
                },
            }
        },
    )
    assert created.status_code == 201, created.text[:400]
    contact_id = created.json()["data"]["id"]

    response = await integration_api_client.patch(
        f"/api/contacts/{contact_id}/fields/{field_name}",
        json={"data": {"type": "contact_fields", "attributes": {"value": "Augusta"}}},
    )

    assert response.status_code == 200, response.text[:400]
    attributes = (
        await integration_api_client.get(f"/api/contacts/{contact_id}")
    ).json()["data"]["attributes"]
    assert attributes[field_name] == "Augusta"
    assert attributes["company"] == "Analytical Engines Ltd"
    assert attributes["job_title"] == "Programmer"
