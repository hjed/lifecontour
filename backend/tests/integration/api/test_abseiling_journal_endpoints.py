"""Integration tests for Abseiling journal API endpoints."""

from typing import Any

import pytest
from core_shared.models.journals import JournalType
from httpx import AsyncClient


@pytest.fixture
def base_journal_payload():
    """Base payload for creating a journal."""
    return {
        "data": {
            "type": "journals",
            "attributes": {
                "title": "Test Abseiling Trip",
                "content": "A great day out abseiling.",
                "event_date_range": {
                    "start": "2024-03-20T00:00:00Z",
                    "end": "2024-03-20T05:00:00Z",
                },
                "types": [JournalType.ABSEILING_TRIP.value],
                "type_data": {},
            },
        }
    }


async def test_create_abseiling_journal_with_pitches(
    authenticated_client: AsyncClient,
    base_journal_payload: dict[str, Any],
):
    """Test creating an abseiling journal with pitches and auto-calculation."""
    payload = base_journal_payload.copy()
    payload["data"]["attributes"]["type_data"] = {
        JournalType.ABSEILING_TRIP.value: {
            "pitches": [
                {
                    "pitch_number": 1,
                    "height": 20,
                    "anchor_location": "Centre",
                    "anchor_type": "sling on tree",
                    "did_setup": True,
                    "did_rescue": False,
                },
                {
                    "pitch_number": 2,
                    "height": 30,
                    "anchor_location": "TL",
                    "anchor_type": "double bolt",
                    "did_setup": False,
                    "did_rescue": True,
                },
            ]
        }
    }

    response = await authenticated_client.post("/api/journals", json=payload)
    assert response.status_code == 201

    data = response.json()["data"]
    assert JournalType.ABSEILING_TRIP.value in data["attributes"]["types"]

    type_data = data["attributes"]["type_data"][JournalType.ABSEILING_TRIP.value]
    assert type_data["number_of_abseils"] == 2
    assert type_data["total_length"] == 50
    assert type_data["number_of_setups"] == 1
    assert type_data["number_of_rescues"] == 1

    pitches = type_data["pitches"]
    assert len(pitches) == 2
    assert pitches[0]["height"] == 20
    assert pitches[1]["height"] == 30


async def test_update_abseiling_journal_with_pitches(
    authenticated_client: AsyncClient,
    base_journal_payload: dict[str, Any],
):
    """Test updating an abseiling journal to add/modify pitches."""
    # Create journal without pitches but with a manual override
    payload = base_journal_payload.copy()
    payload["data"]["attributes"]["type_data"] = {
        JournalType.ABSEILING_TRIP.value: {
            "number_of_abseils": 5,
            "total_length": 100,
        }
    }
    create_resp = await authenticated_client.post("/api/journals", json=payload)
    assert create_resp.status_code == 201
    journal_id = create_resp.json()["data"]["id"]

    # Update journal to replace pitches, but omit manual overrides
    # The empty/None values in type_data update won't automatically clear
    # the manual overrides unless we explicitly set them to None, but PATCH
    # merge semantics in our API generally apply what is provided.
    # Wait, the AbseilingDataSchema allows setting them to None? Let's just update
    # pitches and see if it respects the existing overrides or updates them.
    # Actually, our API controller for `_update_abseiling_type_data` only updates
    # fields that are present in `attrs`. So if we only send `pitches`,
    # the manual overrides (5 and 100) will be preserved, and setups/rescues will be auto-calculated.

    update_payload = {
        "data": {
            "type": "journal-type-data",
            "attributes": {
                "pitches": [
                    {
                        "pitch_number": 1,
                        "height": 10,
                        "did_setup": True,
                        "did_rescue": True,
                    }
                ]
            },
        }
    }

    update_resp = await authenticated_client.put(
        f"/api/journals/{journal_id}/types/{JournalType.ABSEILING_TRIP.value}/data",
        json=update_payload,
    )
    assert update_resp.status_code == 200

    data = update_resp.json()["data"]
    type_data = data["attributes"]["type_data"][JournalType.ABSEILING_TRIP.value]

    # Manual overrides should persist for number_of_abseils and total_length
    assert type_data["number_of_abseils"] == 5
    assert type_data["total_length"] == 100
    # Auto-calculated fields for setups and rescues
    assert type_data["number_of_setups"] == 1
    assert type_data["number_of_rescues"] == 1

    pitches = type_data["pitches"]
    assert len(pitches) == 1
    assert pitches[0]["height"] == 10
