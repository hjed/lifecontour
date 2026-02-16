"""Integration tests for calendar API endpoints and EVENT journal creation."""

import pytest
import pytest_asyncio


@pytest.mark.integration
class TestCalendarEndpoints:
    """Integration tests for calendar API endpoints."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_method(self, clean_database):  # noqa: ARG002
        """Setup method to ensure clean database for each test."""
        pass

    async def test_create_calendar_minimal(self, integration_api_client):
        """Test creating a calendar with minimal required fields."""
        request_data = {
            "data": {
                "type": "calendars",
                "attributes": {
                    "name": "Work Calendar",
                },
            }
        }

        response = await integration_api_client.post(
            "/api/calendars", json=request_data
        )

        assert response.status_code == 201
        data = response.json()
        assert data["data"]["type"] == "calendars"
        assert data["data"]["attributes"]["name"] == "Work Calendar"
        # Should have default color
        assert data["data"]["attributes"]["color"] == "#3B82F6"
        assert data["data"]["id"] is not None

    async def test_create_calendar_with_all_fields(self, integration_api_client):
        """Test creating a calendar with all optional fields."""
        request_data = {
            "data": {
                "type": "calendars",
                "attributes": {
                    "name": "Personal Calendar",
                    "description": "My personal events",
                    "color": "#FF5733",
                    "is_synced_to_google": True,
                    "google_calendar_id": "primary@example.com",
                },
            }
        }

        response = await integration_api_client.post(
            "/api/calendars", json=request_data
        )

        assert response.status_code == 201
        data = response.json()
        assert data["data"]["attributes"]["name"] == "Personal Calendar"
        assert data["data"]["attributes"]["description"] == "My personal events"
        assert data["data"]["attributes"]["color"] == "#FF5733"
        assert data["data"]["attributes"]["is_synced_to_google"] is True
        assert data["data"]["attributes"]["google_calendar_id"] == "primary@example.com"

    async def test_create_calendar_missing_name(self, integration_api_client):
        """Test that creating a calendar without name fails."""
        request_data = {
            "data": {
                "type": "calendars",
                "attributes": {},
            }
        }

        response = await integration_api_client.post(
            "/api/calendars", json=request_data
        )

        assert response.status_code == 400  # Validation error

    async def test_create_calendar_invalid_color(self, integration_api_client):
        """Test that creating a calendar with invalid color format fails."""
        request_data = {
            "data": {
                "type": "calendars",
                "attributes": {
                    "name": "Test Calendar",
                    "color": "invalid-color",  # Not hex format
                },
            }
        }

        response = await integration_api_client.post(
            "/api/calendars", json=request_data
        )

        assert response.status_code == 400  # Domain validation error

    async def test_list_calendars(self, integration_api_client):
        """Test listing all calendars for the authenticated user."""
        # Create multiple calendars
        calendar1_data = {
            "data": {
                "type": "calendars",
                "attributes": {
                    "name": "Work Calendar",
                    "color": "#FF0000",
                },
            }
        }
        calendar2_data = {
            "data": {
                "type": "calendars",
                "attributes": {
                    "name": "Personal Calendar",
                    "color": "#00FF00",
                },
            }
        }

        await integration_api_client.post("/api/calendars", json=calendar1_data)
        await integration_api_client.post("/api/calendars", json=calendar2_data)

        # List calendars
        response = await integration_api_client.get("/api/calendars")

        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert isinstance(data["data"], list)
        assert len(data["data"]) >= 2

        # Verify calendars are ordered by name
        calendar_names = [cal["attributes"]["name"] for cal in data["data"]]
        assert calendar_names == sorted(calendar_names)

        # Verify JSON API structure
        for calendar in data["data"]:
            assert calendar["type"] == "calendars"
            assert "id" in calendar
            assert "attributes" in calendar
            assert "name" in calendar["attributes"]
            assert "color" in calendar["attributes"]

    async def test_list_calendars_empty(self, integration_api_client):
        """Test listing calendars when user has no calendars."""
        response = await integration_api_client.get("/api/calendars")

        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert isinstance(data["data"], list)
        assert data["data"] == []


@pytest.mark.integration
class TestEventJournalCreation:
    """Integration tests for creating EVENT journals with calendar info."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_method(self, clean_database):  # noqa: ARG002
        """Setup method to ensure clean database for each test."""
        pass

    async def test_create_event_journal_with_calendar_info(
        self, integration_api_client
    ):
        """Test creating an EVENT journal with calendar info via API."""
        # First create a calendar
        calendar_data = {
            "data": {
                "type": "calendars",
                "attributes": {
                    "name": "Work Calendar",
                    "color": "#3B82F6",
                },
            }
        }
        calendar_response = await integration_api_client.post(
            "/api/calendars", json=calendar_data
        )
        assert calendar_response.status_code == 201
        calendar_id = calendar_response.json()["data"]["id"]

        # Create an EVENT journal with calendar info
        journal_data = {
            "data": {
                "type": "journals",
                "attributes": {
                    "title": "Team Meeting",
                    "content": "Discuss Q1 goals",
                    "event_date_range": {
                        "start": "2024-01-15T00:00:00Z",
                        "end": "2024-01-15T00:00:00Z",
                    },
                    "types": ["EVENT"],
                    "type_data": {
                        "EVENT": {
                            "calendar_id": calendar_id,
                            "start_time": "09:00:00",
                            "end_time": "10:00:00",
                            "is_all_day": False,
                            "location": "Conference Room A",
                            "sync_invitees": True,
                        }
                    },
                },
            }
        }

        response = await integration_api_client.post("/api/journals", json=journal_data)

        assert response.status_code == 201
        data = response.json()
        assert data["data"]["attributes"]["title"] == "Team Meeting"
        assert "event" in data["data"]["attributes"]["types"]

        # Verify calendar info is included in response
        assert data["data"]["attributes"]["calendar"] is not None
        assert data["data"]["attributes"]["calendar"]["id"] == calendar_id
        assert data["data"]["attributes"]["calendar"]["name"] == "Work Calendar"

    async def test_create_all_day_event_journal(self, integration_api_client):
        """Test creating an all-day EVENT journal."""
        # Create a calendar
        calendar_data = {
            "data": {
                "type": "calendars",
                "attributes": {
                    "name": "Personal Calendar",
                },
            }
        }
        calendar_response = await integration_api_client.post(
            "/api/calendars", json=calendar_data
        )
        calendar_id = calendar_response.json()["data"]["id"]

        # Create an all-day event
        journal_data = {
            "data": {
                "type": "journals",
                "attributes": {
                    "title": "Birthday",
                    "content": "Alice's birthday",
                    "event_date_range": {
                        "start": "2024-03-20T00:00:00Z",
                        "end": "2024-03-20T00:00:00Z",
                    },
                    "types": ["EVENT"],
                    "type_data": {
                        "EVENT": {
                            "calendar_id": calendar_id,
                            "is_all_day": True,
                        }
                    },
                },
            }
        }

        response = await integration_api_client.post("/api/journals", json=journal_data)

        assert response.status_code == 201
        data = response.json()
        assert "event" in data["data"]["attributes"]["types"]
        # All-day events should not have start_time/end_time
        assert data["data"]["attributes"]["calendar"] is not None

    async def test_event_journal_not_returned_by_note_filter(
        self, integration_api_client
    ):
        """Test that EVENT journals are NOT returned when filtering by NOTE type."""
        # Create a calendar
        calendar_data = {
            "data": {
                "type": "calendars",
                "attributes": {
                    "name": "Work Calendar",
                },
            }
        }
        calendar_response = await integration_api_client.post(
            "/api/calendars", json=calendar_data
        )
        calendar_id = calendar_response.json()["data"]["id"]

        # Create a NOTE journal (no types specified)
        note_data = {
            "data": {
                "type": "journals",
                "attributes": {
                    "title": "Note Journal",
                    "content": "Just a note",
                    "event_date_range": {
                        "start": "2024-01-10T00:00:00Z",
                        "end": "2024-01-10T00:00:00Z",
                    },
                },
            }
        }
        note_response = await integration_api_client.post(
            "/api/journals", json=note_data
        )
        assert note_response.status_code == 201
        note_journal_id = note_response.json()["data"]["id"]

        # Create an EVENT journal
        event_data = {
            "data": {
                "type": "journals",
                "attributes": {
                    "title": "Event Journal",
                    "content": "An event",
                    "event_date_range": {
                        "start": "2024-01-15T00:00:00Z",
                        "end": "2024-01-15T00:00:00Z",
                    },
                    "types": ["EVENT"],
                    "type_data": {
                        "EVENT": {
                            "calendar_id": calendar_id,
                        }
                    },
                },
            }
        }
        event_response = await integration_api_client.post(
            "/api/journals", json=event_data
        )
        assert event_response.status_code == 201

        # Filter by NOTE type - should only return the NOTE journal
        filter_response = await integration_api_client.get("/api/journals?type=NOTE")
        assert filter_response.status_code == 200

        journals = filter_response.json()["data"]
        assert len(journals) == 1
        assert journals[0]["id"] == note_journal_id
        assert journals[0]["attributes"]["title"] == "Note Journal"

    async def test_filter_journals_by_calendar(self, integration_api_client):
        """Test filtering journals by calendar_id."""
        # Create two calendars
        calendar1_data = {
            "data": {
                "type": "calendars",
                "attributes": {
                    "name": "Work Calendar",
                },
            }
        }
        calendar1_response = await integration_api_client.post(
            "/api/calendars", json=calendar1_data
        )
        calendar1_id = calendar1_response.json()["data"]["id"]

        calendar2_data = {
            "data": {
                "type": "calendars",
                "attributes": {
                    "name": "Personal Calendar",
                },
            }
        }
        calendar2_response = await integration_api_client.post(
            "/api/calendars", json=calendar2_data
        )
        calendar2_id = calendar2_response.json()["data"]["id"]

        # Create EVENT journal in calendar 1
        event1_data = {
            "data": {
                "type": "journals",
                "attributes": {
                    "title": "Work Meeting",
                    "content": "Team sync",
                    "event_date_range": {
                        "start": "2024-01-15T00:00:00Z",
                        "end": "2024-01-15T00:00:00Z",
                    },
                    "types": ["EVENT"],
                    "type_data": {
                        "EVENT": {
                            "calendar_id": calendar1_id,
                        }
                    },
                },
            }
        }
        event1_response = await integration_api_client.post(
            "/api/journals", json=event1_data
        )
        assert event1_response.status_code == 201
        event1_journal_id = event1_response.json()["data"]["id"]

        # Create EVENT journal in calendar 2
        event2_data = {
            "data": {
                "type": "journals",
                "attributes": {
                    "title": "Personal Appointment",
                    "content": "Doctor visit",
                    "event_date_range": {
                        "start": "2024-01-16T00:00:00Z",
                        "end": "2024-01-16T00:00:00Z",
                    },
                    "types": ["EVENT"],
                    "type_data": {
                        "EVENT": {
                            "calendar_id": calendar2_id,
                        }
                    },
                },
            }
        }
        event2_response = await integration_api_client.post(
            "/api/journals", json=event2_data
        )
        assert event2_response.status_code == 201

        # Filter by calendar 1 - should only return event1
        filter_response = await integration_api_client.get(
            f"/api/journals?calendar_id={calendar1_id}"
        )
        assert filter_response.status_code == 200

        journals = filter_response.json()["data"]
        assert len(journals) == 1
        assert journals[0]["id"] == event1_journal_id
        assert journals[0]["attributes"]["title"] == "Work Meeting"
