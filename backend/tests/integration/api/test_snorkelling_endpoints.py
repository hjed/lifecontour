import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_snorkelling_journal(authenticated_client: AsyncClient):
    payload = {
        "data": {
            "type": "journals",
            "attributes": {
                "title": "Snorkelling test",
                "content": "test",
                "event_date_range": {
                    "start": "2026-05-02T10:00:00Z",
                    "end": "2026-05-02T12:00:00Z",
                },
                "types": ["snorkelling", "outdoor_activity", "fitness"],
                "type_data": {
                    "snorkelling": {},
                    "outdoor_activity": {},
                    "fitness": {},
                },
            },
        }
    }

    response = await authenticated_client.post("/api/journals", json=payload)
    assert response.status_code == 201

    response_data = response.json()["data"]
    assert "snorkelling" in response_data["attributes"]["types"]
    assert "snorkelling" in response_data["attributes"]["type_data"]
