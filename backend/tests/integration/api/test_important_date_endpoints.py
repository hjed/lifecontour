"""
Integration tests for ImportantDate and CustomDateType API endpoints.
"""

import pytest
from httpx import AsyncClient


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
    response = await integration_api_client.get("/api/contacts")
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert "meta" in data
    # Ensure important dates are accessible if any exist
    if len(data["data"]) > 0:
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
