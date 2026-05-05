"""Integration tests for Gear Maintenance API endpoints."""

import pytest
from core_shared.models.journals import JournalType
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
class TestGearMaintenanceEndpoints:
    """Integration tests for Gear Maintenance specific journal features."""

    async def test_create_and_update_gear_maintenance_journal(
        self,
        authenticated_client: AsyncClient,
    ) -> None:
        """Test creating a journal with gear maintenance data and updating it."""
        # 0. Create a gear item
        gear_data = {
            "data": {
                "type": "gear-items",
                "attributes": {
                    "name": "Test Harness",
                    "model": "Altitude",
                    "manufacturer": "Petzl",
                },
            }
        }
        gear_resp = await authenticated_client.post("/api/gear-items", json=gear_data)
        assert gear_resp.status_code == 201
        gear_item_id = gear_resp.json()["data"]["id"]

        # 1. Create a journal with gear maintenance type and data
        journal_data = {
            "data": {
                "type": "journals",
                "attributes": {
                    "title": "Gear Inspection",
                    "content": "Annual inspection of climbing gear.",
                    "event_date_range": {
                        "start": "2024-01-01T10:00:00Z",
                        "end": "2024-01-01T12:00:00Z",
                    },
                    "types": [JournalType.GEAR_MAINTENANCE.value],
                    "type_data": {
                        JournalType.GEAR_MAINTENANCE.value: {
                            "gear_item_id": str(gear_item_id),
                            "maintenance_type": "routine inspection",
                            "activity_types": ["climbing", "canyoning"],
                        }
                    },
                },
            }
        }
        create_response = await authenticated_client.post(
            "/api/journals", json=journal_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        # Verify data was saved correctly
        attributes = create_response.json()["data"]["attributes"]
        assert JournalType.GEAR_MAINTENANCE.value in attributes["types"]
        type_data = attributes["type_data"][JournalType.GEAR_MAINTENANCE.value]
        assert type_data["gear_item_id"] == str(gear_item_id)
        assert type_data["maintenance_type"] == "routine inspection"
        assert type_data["activity_types"] == ["climbing", "canyoning"]
        assert (
            "retirement_reason" not in type_data
            or type_data["retirement_reason"] is None
        )

        # 2. Update data to test retiring
        retire_data = {
            "data": {
                "type": "journal-type-data",
                "attributes": {
                    "gear_item_id": str(gear_item_id),
                    "maintenance_type": "retiring gear",
                    "retirement_reason": "Worn out core",
                    "activity_types": [],
                },
            }
        }
        retire_response = await authenticated_client.put(
            f"/api/journals/{journal_id}/types/{JournalType.GEAR_MAINTENANCE.value}/data",
            json=retire_data,
        )
        assert retire_response.status_code == 200

        # Verify update
        updated_attributes = retire_response.json()["data"]["attributes"]
        updated_type_data = updated_attributes["type_data"][
            JournalType.GEAR_MAINTENANCE.value
        ]
        assert updated_type_data["maintenance_type"] == "retiring gear"
        assert updated_type_data["retirement_reason"] == "Worn out core"

    async def test_validation_error_on_missing_retirement_reason(
        self,
        authenticated_client: AsyncClient,
    ) -> None:
        """Test validation fails when retirement reason is missing for retiring gear."""
        # 0. Create a gear item
        gear_data = {
            "data": {
                "type": "gear-items",
                "attributes": {
                    "name": "Test Rope",
                    "manufacturer": "Edelrid",
                },
            }
        }
        gear_resp = await authenticated_client.post("/api/gear-items", json=gear_data)
        assert gear_resp.status_code == 201
        gear_item_id = gear_resp.json()["data"]["id"]

        # 1. Attempt to create a journal with retiring gear but no reason
        journal_data = {
            "data": {
                "type": "journals",
                "attributes": {
                    "title": "Gear Retirement",
                    "content": "Retiring harness.",
                    "event_date_range": {
                        "start": "2024-01-01T10:00:00Z",
                        "end": "2024-01-01T12:00:00Z",
                    },
                    "types": [JournalType.GEAR_MAINTENANCE.value],
                    "type_data": {
                        JournalType.GEAR_MAINTENANCE.value: {
                            "gear_item_id": str(gear_item_id),
                            "maintenance_type": "retiring gear",
                        }
                    },
                },
            }
        }
        create_response = await authenticated_client.post(
            "/api/journals", json=journal_data
        )

        # Should fail validation
        assert create_response.status_code == 400
