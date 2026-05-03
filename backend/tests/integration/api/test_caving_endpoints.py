import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_caving_journal(authenticated_client: AsyncClient):
    payload = {
        "data": {
            "type": "journals",
            "attributes": {
                "title": "Caving test",
                "content": "test",
                "event_date_range": {
                    "start": "2026-05-02T10:00:00Z",
                    "end": "2026-05-02T12:00:00Z",
                },
                "types": ["caving", "abseiling_trip", "outdoor_activity", "fitness"],
                "type_data": {
                    "caving": {"is_vertical": True, "is_horizontal": True},
                    "abseiling_trip": {},
                    "outdoor_activity": {},
                    "fitness": {},
                },
            },
        }
    }

    response = await authenticated_client.post("/api/journals", json=payload)
    assert response.status_code == 201

    response_data = response.json()["data"]
    assert "caving" in response_data["attributes"]["types"]
    assert response_data["attributes"]["type_data"]["caving"]["is_vertical"] is True
    assert response_data["attributes"]["type_data"]["caving"]["is_horizontal"] is True
