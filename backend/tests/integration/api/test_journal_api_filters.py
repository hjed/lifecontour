"""
Integration tests for journal filtering with API-created data.

These tests verify that journals created via API endpoints can be properly
filtered, especially the NOTE type + contact filter combination that was
failing in E2E tests.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio


def create_journal_request_data(
    title: str = "Test Journal",
    content: str = "Test content",
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Create a journal request data structure.

    Args:
        title: Journal title
        content: Journal content
        **kwargs: Additional attributes or relationships to include

    Returns:
        JSON API formatted request data
    """
    now = datetime.now(UTC)

    attributes = {
        "title": title,
        "content": content,
        "event_date_range": {
            "start": now.isoformat(),
            "end": now.isoformat(),
        },
    }

    # Extract relationships if provided
    relationships = kwargs.pop("relationships", None)

    # Update attributes with remaining kwargs
    attributes.update(kwargs)

    request_data: dict[str, Any] = {
        "data": {
            "type": "journals",
            "attributes": attributes,
        }
    }

    if relationships:
        request_data["data"]["relationships"] = relationships

    return request_data


@pytest.mark.integration
class TestJournalAPIFilters:
    """Integration tests for journal filtering with API-created data."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_method(self, clean_database):  # noqa: ARG002
        """Setup method to ensure clean database for each test."""
        pass

    async def test_create_journal_with_contact_relationship(
        self, integration_api_client
    ):
        """Test creating a journal with contact relationship via API."""
        # First, create a contact
        contact_data = {
            "data": {
                "type": "contacts",
                "attributes": {
                    "first_name": "John",
                    "last_name": "Doe",
                    "email": "john.doe@example.com",
                },
            }
        }
        contact_response = await integration_api_client.post(
            "/api/contacts", json=contact_data
        )
        assert contact_response.status_code == 201
        contact_id = contact_response.json()["data"]["id"]

        # Create a journal with contact relationship
        journal_data = create_journal_request_data(
            title="Meeting with John",
            content="Discussed project plans",
            relationships={
                "contacts": {
                    "data": [
                        {
                            "type": "journal-contact-relationships",
                            "attributes": {
                                "contact_id": contact_id,
                                "relationship_type": "PARTICIPANT",
                            },
                        }
                    ]
                }
            },
        )

        journal_response = await integration_api_client.post(
            "/api/journals", json=journal_data
        )
        assert journal_response.status_code == 201

        # Verify the journal was created with the contact relationship
        journal_json = journal_response.json()
        assert journal_json["data"]["type"] == "journals"
        assert journal_json["data"]["attributes"]["title"] == "Meeting with John"

        # Verify contacts are included in the response
        contacts = journal_json["data"]["attributes"]["contacts"]
        assert len(contacts) == 1
        assert contacts[0]["id"] == contact_id
        assert contacts[0]["relationship_type"] == "PARTICIPANT"

    async def test_filter_note_type_with_contact(self, integration_api_client):
        """
        Test filtering by NOTE type + contact (regression test for bug).

        This test reproduces the bug where NOTE type + contact filter returns
        0 results when journals are created via API.
        """
        # Create a contact
        contact_data = {
            "data": {
                "type": "contacts",
                "attributes": {
                    "first_name": "Alice",
                    "last_name": "Smith",
                    "email": "alice@example.com",
                },
            }
        }
        contact_response = await integration_api_client.post(
            "/api/contacts", json=contact_data
        )
        assert contact_response.status_code == 201
        contact_id = contact_response.json()["data"]["id"]

        # Create a NOTE journal with contact (no types specified = NOTE type)
        note_journal_data = create_journal_request_data(
            title="Note with Alice",
            content="Meeting notes",
            relationships={
                "contacts": {
                    "data": [
                        {
                            "type": "journal-contact-relationships",
                            "attributes": {
                                "contact_id": contact_id,
                                "relationship_type": "PARTICIPANT",
                            },
                        }
                    ]
                }
            },
        )

        note_response = await integration_api_client.post(
            "/api/journals", json=note_journal_data
        )
        assert note_response.status_code == 201
        note_journal_id = note_response.json()["data"]["id"]

        # Create an EVENT journal with the same contact (should NOT be returned)
        # First create a calendar
        calendar_data = {
            "data": {
                "type": "calendars",
                "attributes": {
                    "name": "Test Calendar",
                    "color": "#FF0000",
                },
            }
        }
        calendar_response = await integration_api_client.post(
            "/api/calendars", json=calendar_data
        )
        assert calendar_response.status_code == 201
        calendar_id = calendar_response.json()["data"]["id"]

        # Create EVENT journal
        event_journal_data = create_journal_request_data(
            title="Event with Alice",
            content="Calendar event",
            types=["EVENT"],
            type_data={
                "EVENT": {
                    "calendar_id": calendar_id,
                    "is_all_day": False,
                    "sync_invitees": False,
                }
            },
            relationships={
                "contacts": {
                    "data": [
                        {
                            "type": "journal-contact-relationships",
                            "attributes": {
                                "contact_id": contact_id,
                                "relationship_type": "PARTICIPANT",
                            },
                        }
                    ]
                }
            },
        )

        event_response = await integration_api_client.post(
            "/api/journals", json=event_journal_data
        )
        assert event_response.status_code == 201

        # Filter by NOTE type + contact
        # Note: The query parameter is 'type', not 'journal_type' (see alias in controllers.py)
        filter_response = await integration_api_client.get(
            f"/api/journals?type=NOTE&contact_id={contact_id}"
        )
        assert filter_response.status_code == 200

        # Verify we get the NOTE journal but not the EVENT journal
        journals = filter_response.json()["data"]
        assert len(journals) == 1, f"Expected 1 journal, got {len(journals)}"
        assert journals[0]["id"] == note_journal_id
        assert journals[0]["attributes"]["title"] == "Note with Alice"
