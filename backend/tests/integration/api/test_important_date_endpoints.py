"""
Integration tests for ImportantDate and CustomDateType API endpoints.
"""

import pytest
from httpx import AsyncClient, Response


@pytest.fixture
async def setup_custom_date_type(
    integration_api_client: AsyncClient,
) -> int:
    """Create a custom date type and return its ID."""
    payload = {
        "data": {"type": "custom_date_types", "attributes": {"name": "Anniversary"}}
    }
    response = await integration_api_client.post("/api/custom-date-types", json=payload)
    return int(response.json()["data"]["id"])


@pytest.mark.asyncio
async def test_get_custom_date_types(
    integration_api_client: AsyncClient,
    setup_custom_date_type: int,
) -> None:
    """Test retrieving custom date types."""
    response = await integration_api_client.get("/api/custom-date-types")

    assert response.status_code == 200
    data = response.json()["data"]

    assert len(data) == 1
    names = [d["attributes"]["name"] for d in data]
    assert "Anniversary" in names


@pytest.mark.asyncio
async def test_create_custom_date_type(
    integration_api_client: AsyncClient,
) -> None:
    """Test creating a custom date type."""
    payload = {
        "data": {"type": "custom_date_types", "attributes": {"name": "Graduation"}}
    }
    response = await integration_api_client.post("/api/custom-date-types", json=payload)

    assert response.status_code == 201
    data = response.json()["data"]

    assert data["attributes"]["name"] == "Graduation"
    assert "id" in data


@pytest.mark.asyncio
async def test_create_contact_with_important_dates(
    integration_api_client: AsyncClient,
) -> None:
    """Test creating a contact with an important date."""
    payload = {
        "data": {
            "type": "contacts",
            "attributes": {
                "first_name": "Test",
                "last_name": "Dates",
                "important_dates": [
                    {
                        "attributes": {
                            "date_type": "birthday",
                            "precision": "full",
                            "year": 1990,
                            "month": 5,
                            "day": 15,
                        }
                    }
                ],
            },
        }
    }

    response = await integration_api_client.post("/api/contacts", json=payload)

    assert response.status_code == 201
    data = response.json()["data"]

    dates = data["attributes"]["important_dates"]
    assert len(dates) == 1
    assert dates[0]["attributes"]["date_type"] == "birthday"
    assert dates[0]["attributes"]["precision"] == "full"
    assert dates[0]["attributes"]["year"] == 1990
    assert dates[0]["attributes"]["month"] == 5
    assert dates[0]["attributes"]["day"] == 15


@pytest.mark.asyncio
async def test_update_contact_with_important_dates(
    integration_api_client: AsyncClient,
) -> None:
    """Test updating a contact to add important dates."""
    # First create
    contact_payload = {
        "data": {
            "type": "contacts",
            "attributes": {"first_name": "Update", "last_name": "Dates"},
        }
    }
    response = await integration_api_client.post("/api/contacts", json=contact_payload)
    assert response.status_code == 201
    contact_id = response.json()["data"]["id"]

    # Then update
    payload = {
        "data": {
            "type": "contacts",
            "id": str(contact_id),
            "attributes": {
                "first_name": "Update",
                "last_name": "Dates",
                "important_dates": [
                    {
                        "attributes": {
                            "date_type": "work_anniversary",
                            "precision": "year",
                            "year": 2020,
                        }
                    }
                ],
            },
        }
    }

    response = await integration_api_client.put(
        f"/api/contacts/{contact_id}", json=payload
    )

    assert response.status_code == 200
    data = response.json()["data"]

    dates = data["attributes"]["important_dates"]
    assert len(dates) == 1
    assert dates[0]["attributes"]["date_type"] == "work_anniversary"
    assert dates[0]["attributes"]["year"] == 2020

    # Ensure retrieval works
    response = await integration_api_client.get(f"/api/contacts/{contact_id}")
    assert response.status_code == 200
    dates = response.json()["data"]["attributes"]["important_dates"]
    assert len(dates) == 1
    assert dates[0]["attributes"]["date_type"] == "work_anniversary"


@pytest.mark.asyncio
async def test_invalid_precision_combination(
    integration_api_client: AsyncClient,
) -> None:
    """Test validation fails for invalid precision combinations."""
    payload = {
        "data": {
            "type": "contacts",
            "attributes": {
                "first_name": "Test",
                "last_name": "Dates",
                "important_dates": [
                    {
                        "attributes": {
                            "date_type": "birthday",
                            "precision": "full",
                            "year": 1990,
                            # intentionally missing month and day
                        }
                    }
                ],
            },
        }
    }

    response = await integration_api_client.post("/api/contacts", json=payload)

    assert response.status_code == 400
    data = response.json()
    assert "errors" in data


@pytest.mark.asyncio
async def test_get_contacts_list_payload(
    integration_api_client: AsyncClient,
) -> None:
    """Test the list endpoint retains existing payload structure."""
    # Guarantee a contact exists for deterministic testing
    contact_payload = {
        "data": {
            "type": "contacts",
            "attributes": {"first_name": "List", "last_name": "Test"},
        }
    }
    await integration_api_client.post("/api/contacts", json=contact_payload)

    response = await integration_api_client.get("/api/contacts")
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert "meta" in data

    assert len(data["data"]) > 0
    first = data["data"][0]
    assert "important_dates" in first["attributes"]


@pytest.mark.asyncio
async def test_create_contact_with_custom_date(
    integration_api_client: AsyncClient,
    setup_custom_date_type: int,
) -> None:
    """Test creating a contact with a custom date type requires valid config."""
    payload = {
        "data": {
            "type": "contacts",
            "attributes": {
                "first_name": "Custom",
                "last_name": "Dates",
                "important_dates": [
                    {
                        "attributes": {
                            "date_type": "custom",
                            "precision": "year",
                            "year": 2020,
                            "custom_date_type_id": setup_custom_date_type,
                        }
                    }
                ],
            },
        }
    }

    response = await integration_api_client.post("/api/contacts", json=payload)
    assert response.status_code == 201
    dates = response.json()["data"]["attributes"]["important_dates"]
    assert len(dates) == 1
    assert dates[0]["attributes"]["date_type"] == "custom"
    assert dates[0]["attributes"]["custom_date_type_id"] == setup_custom_date_type


# Important Date Sub-Resource Endpoints
#
# Important dates are the last contact sub-resource without endpoints of their
# own; until these existed the only way to change one was the whole-contact PUT,
# which replaces every date and so churns their ids. See LOCAL-176.


async def _create_contact(
    client: AsyncClient, first_name: str = "Date", last_name: str = "Owner"
) -> int:
    """Create a bare contact and return its id."""
    response = await client.post(
        "/api/contacts",
        json={
            "data": {
                "type": "contacts",
                "attributes": {"first_name": first_name, "last_name": last_name},
            }
        },
    )
    assert response.status_code == 201
    return int(response.json()["data"]["id"])


async def _date_ids(client: AsyncClient, contact_id: int) -> set[int]:
    """Every important-date id currently on a contact."""
    response = await client.get(f"/api/contacts/{contact_id}")
    assert response.status_code == 200
    dates = response.json()["data"]["attributes"]["important_dates"]
    return {int(date["id"]) for date in dates}


async def _add_date(client: AsyncClient, contact_id: int, **attributes: object) -> int:
    """Add an important date to a contact and return the new date's id.

    Identified as the id that was not there before, rather than by position:
    ``get_important_dates`` orders by ``created_at``, and this fixture runs
    every request in one transaction, so every row this test writes shares a
    ``NOW()`` to the microsecond and the ordering between them is arbitrary.
    """
    before = await _date_ids(client, contact_id)

    response = await client.post(
        f"/api/contacts/{contact_id}/important-dates",
        json={"data": {"type": "contact_important_dates", "attributes": attributes}},
    )
    assert response.status_code == 201, response.text

    added = {
        int(date["id"])
        for date in response.json()["data"]["attributes"]["important_dates"]
    } - before
    assert len(added) == 1, "exactly one date should have appeared"
    return added.pop()


def _error_code(response: Response) -> str:
    """The JSON:API error code from a failed response."""
    return str(response.json()["errors"][0]["code"])


@pytest.mark.asyncio
async def test_add_important_date_returns_updated_contact(
    integration_api_client: AsyncClient,
) -> None:
    """POST adds a date and answers with the whole contact, as addresses do."""
    contact_id = await _create_contact(integration_api_client)

    response = await integration_api_client.post(
        f"/api/contacts/{contact_id}/important-dates",
        json={
            "data": {
                "type": "contact_important_dates",
                "attributes": {
                    "date_type": "birthday",
                    "precision": "full",
                    "year": 1990,
                    "month": 5,
                    "day": 15,
                },
            }
        },
    )

    assert response.status_code == 201
    dates = response.json()["data"]["attributes"]["important_dates"]
    assert len(dates) == 1
    assert dates[0]["attributes"]["date_type"] == "birthday"
    assert dates[0]["attributes"]["year"] == 1990
    assert dates[0]["id"] is not None


@pytest.mark.asyncio
async def test_add_important_date_rejects_a_second_birthday(
    integration_api_client: AsyncClient,
) -> None:
    """A contact has at most one birthday."""
    contact_id = await _create_contact(integration_api_client)
    await _add_date(
        integration_api_client,
        contact_id,
        date_type="birthday",
        precision="day_month",
        month=5,
        day=15,
    )

    response = await integration_api_client.post(
        f"/api/contacts/{contact_id}/important-dates",
        json={
            "data": {
                "type": "contact_important_dates",
                "attributes": {
                    "date_type": "birthday",
                    "precision": "day_month",
                    "month": 6,
                    "day": 1,
                },
            }
        },
    )

    assert response.status_code == 409
    assert _error_code(response) == "DUPLICATE_BIRTHDAY"


@pytest.mark.asyncio
async def test_add_important_date_rejects_invalid_precision(
    integration_api_client: AsyncClient,
) -> None:
    """Precision and components have to agree, as they do on contact create."""
    contact_id = await _create_contact(integration_api_client)

    response = await integration_api_client.post(
        f"/api/contacts/{contact_id}/important-dates",
        json={
            "data": {
                "type": "contact_important_dates",
                "attributes": {
                    "date_type": "birthday",
                    "precision": "full",
                    "year": 1990,
                    # intentionally missing month and day
                },
            }
        },
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_add_important_date_to_unknown_contact(
    integration_api_client: AsyncClient,
) -> None:
    """A date cannot be hung off a contact that does not exist."""
    response = await integration_api_client.post(
        "/api/contacts/999999/important-dates",
        json={
            "data": {
                "type": "contact_important_dates",
                "attributes": {
                    "date_type": "birthday",
                    "precision": "year",
                    "year": 1990,
                },
            }
        },
    )

    assert response.status_code == 404
    assert _error_code(response) == "CONTACT_NOT_FOUND"


@pytest.mark.asyncio
async def test_update_important_date_edits_in_place(
    integration_api_client: AsyncClient,
) -> None:
    """The headline fix: an existing date can be changed, keeping its id."""
    contact_id = await _create_contact(integration_api_client)
    date_id = await _add_date(
        integration_api_client,
        contact_id,
        date_type="birthday",
        precision="full",
        year=1990,
        month=5,
        day=15,
    )

    response = await integration_api_client.put(
        f"/api/contacts/{contact_id}/important-dates/{date_id}",
        json={
            "data": {
                "type": "contact_important_dates",
                "id": str(date_id),
                "attributes": {
                    "date_type": "birthday",
                    "precision": "full",
                    "year": 1991,
                    "month": 5,
                    "day": 15,
                },
            }
        },
    )

    assert response.status_code == 200
    dates = response.json()["data"]["attributes"]["important_dates"]
    assert len(dates) == 1, "an edit must not leave a second date behind"
    assert int(dates[0]["id"]) == date_id, "the date keeps its id across an edit"
    assert dates[0]["attributes"]["year"] == 1991


@pytest.mark.asyncio
async def test_update_important_date_can_change_type_and_precision(
    integration_api_client: AsyncClient,
) -> None:
    """Type and precision move together, which a per-field PATCH could not do."""
    contact_id = await _create_contact(integration_api_client)
    date_id = await _add_date(
        integration_api_client,
        contact_id,
        date_type="work_anniversary",
        precision="year",
        year=2020,
    )

    response = await integration_api_client.put(
        f"/api/contacts/{contact_id}/important-dates/{date_id}",
        json={
            "data": {
                "type": "contact_important_dates",
                "id": str(date_id),
                "attributes": {
                    "date_type": "first_met",
                    "precision": "full",
                    "year": 2015,
                    "month": 3,
                    "day": 9,
                },
            }
        },
    )

    assert response.status_code == 200
    attributes = response.json()["data"]["attributes"]["important_dates"][0][
        "attributes"
    ]
    assert attributes["date_type"] == "first_met"
    assert attributes["precision"] == "full"
    assert attributes["year"] == 2015
    assert attributes["month"] == 3
    assert attributes["day"] == 9


@pytest.mark.asyncio
async def test_update_important_date_rejects_unknown_date(
    integration_api_client: AsyncClient,
) -> None:
    """A date id that does not exist is refused."""
    contact_id = await _create_contact(integration_api_client)

    response = await integration_api_client.put(
        f"/api/contacts/{contact_id}/important-dates/999999",
        json={
            "data": {
                "type": "contact_important_dates",
                "id": "999999",
                "attributes": {
                    "date_type": "birthday",
                    "precision": "year",
                    "year": 1990,
                },
            }
        },
    )

    assert response.status_code == 422
    assert _error_code(response) == "CONTACT_VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_update_important_date_rejects_another_contacts_date(
    integration_api_client: AsyncClient,
) -> None:
    """A date is only reachable through the contact that owns it."""
    owner_id = await _create_contact(integration_api_client, "Rightful", "Owner")
    stranger_id = await _create_contact(integration_api_client, "Some", "Stranger")
    date_id = await _add_date(
        integration_api_client,
        owner_id,
        date_type="first_met",
        precision="year",
        year=2015,
    )

    response = await integration_api_client.put(
        f"/api/contacts/{stranger_id}/important-dates/{date_id}",
        json={
            "data": {
                "type": "contact_important_dates",
                "id": str(date_id),
                "attributes": {
                    "date_type": "first_met",
                    "precision": "year",
                    "year": 2016,
                },
            }
        },
    )

    assert response.status_code == 422

    # And the owner's date is untouched.
    owner = await integration_api_client.get(f"/api/contacts/{owner_id}")
    assert (
        owner.json()["data"]["attributes"]["important_dates"][0]["attributes"]["year"]
        == 2015
    )


@pytest.mark.asyncio
async def test_update_important_date_rejects_a_second_birthday(
    integration_api_client: AsyncClient,
) -> None:
    """Re-typing a second date as the birthday collides with the first."""
    contact_id = await _create_contact(integration_api_client)
    await _add_date(
        integration_api_client,
        contact_id,
        date_type="birthday",
        precision="day_month",
        month=5,
        day=15,
    )
    other_id = await _add_date(
        integration_api_client,
        contact_id,
        date_type="work_anniversary",
        precision="year",
        year=2020,
    )

    response = await integration_api_client.put(
        f"/api/contacts/{contact_id}/important-dates/{other_id}",
        json={
            "data": {
                "type": "contact_important_dates",
                "id": str(other_id),
                "attributes": {
                    "date_type": "birthday",
                    "precision": "year",
                    "year": 2020,
                },
            }
        },
    )

    assert response.status_code == 409
    assert _error_code(response) == "DUPLICATE_BIRTHDAY"


@pytest.mark.asyncio
async def test_update_important_date_rejects_unknown_custom_type(
    integration_api_client: AsyncClient,
) -> None:
    """A custom type id with no row behind it is reported, not stored."""
    contact_id = await _create_contact(integration_api_client)
    date_id = await _add_date(
        integration_api_client,
        contact_id,
        date_type="first_met",
        precision="year",
        year=2015,
    )

    response = await integration_api_client.put(
        f"/api/contacts/{contact_id}/important-dates/{date_id}",
        json={
            "data": {
                "type": "contact_important_dates",
                "id": str(date_id),
                "attributes": {
                    "date_type": "custom",
                    "precision": "year",
                    "year": 2015,
                    "custom_date_type_id": 999999,
                },
            }
        },
    )

    assert response.status_code == 404
    assert _error_code(response) == "CUSTOM_DATE_TYPE_NOT_FOUND"


@pytest.mark.asyncio
async def test_update_important_date_to_a_custom_type(
    integration_api_client: AsyncClient,
    setup_custom_date_type: int,
) -> None:
    """A date can be retyped as custom, and reads back with the type's name."""
    contact_id = await _create_contact(integration_api_client)
    date_id = await _add_date(
        integration_api_client,
        contact_id,
        date_type="first_met",
        precision="year",
        year=2015,
    )

    response = await integration_api_client.put(
        f"/api/contacts/{contact_id}/important-dates/{date_id}",
        json={
            "data": {
                "type": "contact_important_dates",
                "id": str(date_id),
                "attributes": {
                    "date_type": "custom",
                    "precision": "year",
                    "year": 2015,
                    "custom_date_type_id": setup_custom_date_type,
                },
            }
        },
    )

    assert response.status_code == 200
    attributes = response.json()["data"]["attributes"]["important_dates"][0][
        "attributes"
    ]
    assert attributes["date_type"] == "custom"
    assert attributes["custom_date_type_name"] == "Anniversary"


@pytest.mark.asyncio
async def test_delete_important_date(
    integration_api_client: AsyncClient,
) -> None:
    """DELETE removes only the named date."""
    contact_id = await _create_contact(integration_api_client)
    birthday_id = await _add_date(
        integration_api_client,
        contact_id,
        date_type="birthday",
        precision="day_month",
        month=5,
        day=15,
    )
    await _add_date(
        integration_api_client,
        contact_id,
        date_type="work_anniversary",
        precision="year",
        year=2020,
    )

    response = await integration_api_client.delete(
        f"/api/contacts/{contact_id}/important-dates/{birthday_id}"
    )

    assert response.status_code == 204

    remaining = (
        await integration_api_client.get(f"/api/contacts/{contact_id}")
    ).json()["data"]["attributes"]["important_dates"]
    assert len(remaining) == 1
    assert remaining[0]["attributes"]["date_type"] == "work_anniversary"


@pytest.mark.asyncio
async def test_delete_important_date_rejects_unknown_date(
    integration_api_client: AsyncClient,
) -> None:
    """Deleting a date that does not exist is refused."""
    contact_id = await _create_contact(integration_api_client)

    response = await integration_api_client.delete(
        f"/api/contacts/{contact_id}/important-dates/999999"
    )

    assert response.status_code == 422
