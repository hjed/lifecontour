import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_outdoor_planning_journal(authenticated_client: AsyncClient):
    payload = {
        "data": {
            "type": "journals",
            "attributes": {
                "title": "Planning for canyoning trip",
                "content": "Discussed logistics",
                "event_date_range": {
                    "start": "2026-05-02T10:00:00Z",
                    "end": "2026-05-02T12:00:00Z",
                },
                "types": ["outdoor_planning"],
                "type_data": {
                    "outdoor_planning": {
                        "topics": "Weather, Gear, Ropes",
                        "activity_types": ["canyoning", "bushwalking"],
                    }
                },
            },
        }
    }

    response = await authenticated_client.post("/api/journals", json=payload)
    assert response.status_code == 201

    response_data = response.json()["data"]
    assert "outdoor_planning" in response_data["attributes"]["types"]
    assert (
        response_data["attributes"]["type_data"]["outdoor_planning"]["topics"]
        == "Weather, Gear, Ropes"
    )
    assert response_data["attributes"]["type_data"]["outdoor_planning"][
        "activity_types"
    ] == ["canyoning", "bushwalking"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_outdoor_planning_type_data(authenticated_client: AsyncClient):
    # Create
    create_payload = {
        "data": {
            "type": "journals",
            "attributes": {
                "title": "Planning for canyoning trip",
                "content": "Discussed logistics",
                "event_date_range": {
                    "start": "2026-05-02T10:00:00Z",
                    "end": "2026-05-02T12:00:00Z",
                },
                "types": ["outdoor_planning"],
                "type_data": {
                    "outdoor_planning": {
                        "topics": "Initial topic",
                        "activity_types": ["canyoning"],
                    }
                },
            },
        }
    }

    create_response = await authenticated_client.post(
        "/api/journals", json=create_payload
    )
    assert create_response.status_code == 201
    journal_id = create_response.json()["data"]["id"]

    # Update type data
    update_payload = {
        "data": {
            "type": "journal-type-data",
            "attributes": {
                "topics": "Updated weather, Gear, Ropes",
                "activity_types": ["canyoning", "bushwalking", "climbing"],
            },
        }
    }

    update_response = await authenticated_client.put(
        f"/api/journals/{journal_id}/types/outdoor_planning/data", json=update_payload
    )
    assert update_response.status_code == 200

    updated_data = update_response.json()["data"]
    outdoor_planning_data = updated_data["attributes"]["type_data"]["outdoor_planning"]
    assert outdoor_planning_data["topics"] == "Updated weather, Gear, Ropes"
    assert outdoor_planning_data["activity_types"] == [
        "canyoning",
        "bushwalking",
        "climbing",
    ]
