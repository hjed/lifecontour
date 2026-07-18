"""
Integration tests for journal tag endpoints.

Tests the POST /api/journals/tags endpoint for creating journal tags,
tag assignment to journals, and filtering journals by tags.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest


def create_journal_request_data(
    title: str,
    content: str,
    types: list[str] | None = None,
    type_data: dict[str, Any] | None = None,
    relationships: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Helper to create journal request data."""
    now = datetime.now(UTC)
    data: dict[str, Any] = {
        "data": {
            "type": "journals",
            "attributes": {
                "title": title,
                "content": content,
                "event_date_range": {
                    "start": now.isoformat(),
                    "end": (now + timedelta(hours=1)).isoformat(),
                },
            },
        }
    }

    if types:
        data["data"]["attributes"]["types"] = types

    if type_data:
        data["data"]["attributes"]["type_data"] = type_data

    if relationships:
        data["data"]["relationships"] = relationships

    return data


@pytest.mark.integration
class TestJournalTagEndpoints:
    """Tests for POST /api/journals/tags endpoint."""

    async def test_create_journal_tag_minimal(self, integration_api_client):
        """Test creating a journal tag with minimal fields (name only)."""
        tag_data = {
            "data": {
                "type": "journal-tags",
                "attributes": {
                    "name": "work",
                },
            }
        }

        response = await integration_api_client.post(
            "/api/journals/tags", json=tag_data
        )

        assert response.status_code == 201
        tag_json = response.json()
        assert tag_json["data"]["type"] == "journal-tags"
        assert tag_json["data"]["attributes"]["name"] == "work"
        assert tag_json["data"]["id"] is not None
        assert tag_json["data"]["links"]["self"] is not None

    async def test_create_journal_tag_with_all_fields(self, integration_api_client):
        """Test creating a journal tag with all fields."""
        # First create a parent tag
        parent_tag_data = {
            "data": {
                "type": "journal-tags",
                "attributes": {
                    "name": "projects",
                    "color": "#FF0000",
                },
            }
        }

        parent_response = await integration_api_client.post(
            "/api/journals/tags", json=parent_tag_data
        )
        assert parent_response.status_code == 201
        parent_id = parent_response.json()["data"]["id"]

        # Create child tag
        child_tag_data = {
            "data": {
                "type": "journal-tags",
                "attributes": {
                    "name": "work-projects",
                    "color": "#00FF00",
                    "parent_id": parent_id,
                },
            }
        }

        response = await integration_api_client.post(
            "/api/journals/tags", json=child_tag_data
        )

        assert response.status_code == 201
        tag_json = response.json()
        assert tag_json["data"]["type"] == "journal-tags"
        assert tag_json["data"]["attributes"]["name"] == "work-projects"
        assert tag_json["data"]["attributes"]["color"] == "#00FF00"
        assert tag_json["data"]["attributes"]["parent_id"] == parent_id
        assert tag_json["data"]["id"] is not None

    async def test_create_journal_tag_with_description(self, integration_api_client):
        """Test POST echoes the description back in the created resource."""
        tag_data = {
            "data": {
                "type": "journal-tags",
                "attributes": {
                    "name": "training",
                    "color": "#00FF00",
                    "description": "Structured training sessions",
                },
            }
        }

        response = await integration_api_client.post(
            "/api/journals/tags", json=tag_data
        )

        assert response.status_code == 201
        attributes = response.json()["data"]["attributes"]
        assert attributes["description"] == "Structured training sessions"

    async def test_create_journal_tag_without_description_is_null(
        self, integration_api_client
    ):
        """Test description is optional and serialises as null when omitted."""
        tag_data = {
            "data": {
                "type": "journal-tags",
                "attributes": {"name": "training"},
            }
        }

        response = await integration_api_client.post(
            "/api/journals/tags", json=tag_data
        )

        assert response.status_code == 201
        attributes = response.json()["data"]["attributes"]
        assert attributes["description"] is None

    async def test_list_journal_tags_includes_description(self, integration_api_client):
        """Test GET returns the persisted description for each tag."""
        create_response = await integration_api_client.post(
            "/api/journals/tags",
            json={
                "data": {
                    "type": "journal-tags",
                    "attributes": {
                        "name": "training",
                        "description": "Structured training sessions",
                    },
                }
            },
        )
        assert create_response.status_code == 201
        tag_id = create_response.json()["data"]["id"]

        response = await integration_api_client.get("/api/journals/tags")

        assert response.status_code == 200
        tags = response.json()["data"]
        tag = next(t for t in tags if t["id"] == tag_id)
        assert tag["attributes"]["description"] == "Structured training sessions"

    async def test_create_journal_tag_missing_name(self, integration_api_client):
        """Test creating a journal tag without a name returns validation error."""
        tag_data = {
            "data": {
                "type": "journal-tags",
                "attributes": {},
            }
        }

        response = await integration_api_client.post(
            "/api/journals/tags", json=tag_data
        )

        # FastAPI returns 400 for validation errors in request body
        assert response.status_code == 400

    async def test_create_duplicate_tag_name(self, integration_api_client):
        """Test creating a journal tag with duplicate name returns 400 error."""
        # Create first tag
        tag_data = {
            "data": {
                "type": "journal-tags",
                "attributes": {
                    "name": "duplicate-test",
                    "color": "#FF0000",
                },
            }
        }

        first_response = await integration_api_client.post(
            "/api/journals/tags", json=tag_data
        )
        assert first_response.status_code == 201

        # Try to create second tag with same name
        second_response = await integration_api_client.post(
            "/api/journals/tags", json=tag_data
        )

        # Should return 400 with clear error message
        assert second_response.status_code == 400
        error_json = second_response.json()
        assert "errors" in error_json
        assert len(error_json["errors"]) > 0
        error = error_json["errors"][0]
        assert "name" in error["detail"].lower()
        assert "already exists" in error["detail"].lower()

    async def test_created_tag_appears_in_list(self, integration_api_client):
        """Test that created tags appear in GET /api/journals/tags."""
        # Create a tag
        tag_data = {
            "data": {
                "type": "journal-tags",
                "attributes": {
                    "name": "personal",
                    "color": "#0000FF",
                },
            }
        }

        create_response = await integration_api_client.post(
            "/api/journals/tags", json=tag_data
        )
        assert create_response.status_code == 201
        created_tag_id = create_response.json()["data"]["id"]

        # List tags
        list_response = await integration_api_client.get("/api/journals/tags")
        assert list_response.status_code == 200

        # Verify our tag is in the list
        tags = list_response.json()["data"]
        tag_ids = [tag["id"] for tag in tags]
        assert created_tag_id in tag_ids


@pytest.mark.integration
class TestJournalTagAssignment:
    """Tests for assigning tags to journals."""

    async def test_assign_tag_to_journal(self, integration_api_client):
        """Test assigning a tag to a journal."""
        # Create a tag
        tag_data = {
            "data": {
                "type": "journal-tags",
                "attributes": {
                    "name": "important",
                    "color": "#FF0000",
                },
            }
        }

        tag_response = await integration_api_client.post(
            "/api/journals/tags", json=tag_data
        )
        assert tag_response.status_code == 201
        tag_id = tag_response.json()["data"]["id"]

        # Create a journal
        journal_data = create_journal_request_data(
            title="Important Meeting", content="Discuss quarterly goals"
        )

        journal_response = await integration_api_client.post(
            "/api/journals", json=journal_data
        )
        assert journal_response.status_code == 201
        journal_id = journal_response.json()["data"]["id"]

        # Assign tag to journal
        assignment_data = {
            "data": {
                "type": "journal-tag",
                "attributes": {
                    "tag_id": tag_id,
                },
            }
        }

        assign_response = await integration_api_client.post(
            f"/api/journals/{journal_id}/relationships/tags", json=assignment_data
        )

        assert assign_response.status_code == 200
        journal_json = assign_response.json()

        # Verify tag is in the journal's tags
        tags = journal_json["data"]["attributes"]["tags"]
        assert len(tags) == 1
        assert tags[0]["id"] == tag_id
        assert tags[0]["name"] == "important"

    async def test_remove_tag_from_journal(self, integration_api_client):
        """Test removing a tag from a journal."""
        # Create a tag
        tag_data = {
            "data": {
                "type": "journal-tags",
                "attributes": {
                    "name": "draft",
                },
            }
        }

        tag_response = await integration_api_client.post(
            "/api/journals/tags", json=tag_data
        )
        assert tag_response.status_code == 201
        tag_id = tag_response.json()["data"]["id"]

        # Create a journal
        journal_data = create_journal_request_data(
            title="Draft Document", content="Work in progress"
        )

        journal_response = await integration_api_client.post(
            "/api/journals", json=journal_data
        )
        assert journal_response.status_code == 201
        journal_id = journal_response.json()["data"]["id"]

        # Assign tag to journal
        assignment_data = {
            "data": {
                "type": "journal-tag",
                "attributes": {
                    "tag_id": tag_id,
                },
            }
        }

        await integration_api_client.post(
            f"/api/journals/{journal_id}/relationships/tags", json=assignment_data
        )

        # Remove tag from journal
        remove_response = await integration_api_client.delete(
            f"/api/journals/{journal_id}/relationships/tags/{tag_id}"
        )

        assert remove_response.status_code == 200
        journal_json = remove_response.json()

        # Verify tag is removed
        tags = journal_json["data"]["attributes"]["tags"]
        assert len(tags) == 0


@pytest.mark.integration
class TestJournalTagFiltering:
    """Tests for filtering journals by tags."""

    async def test_filter_journals_by_tag(self, integration_api_client):
        """Test filtering journals by tag_id."""
        # Create two tags
        work_tag_data = {
            "data": {
                "type": "journal-tags",
                "attributes": {
                    "name": "work",
                    "color": "#FF0000",
                },
            }
        }

        work_tag_response = await integration_api_client.post(
            "/api/journals/tags", json=work_tag_data
        )
        assert work_tag_response.status_code == 201
        work_tag_id = work_tag_response.json()["data"]["id"]

        personal_tag_data = {
            "data": {
                "type": "journal-tags",
                "attributes": {
                    "name": "personal",
                    "color": "#00FF00",
                },
            }
        }

        personal_tag_response = await integration_api_client.post(
            "/api/journals/tags", json=personal_tag_data
        )
        assert personal_tag_response.status_code == 201
        personal_tag_id = personal_tag_response.json()["data"]["id"]

        # Create work journal
        work_journal_data = create_journal_request_data(
            title="Work Meeting", content="Quarterly review"
        )

        work_journal_response = await integration_api_client.post(
            "/api/journals", json=work_journal_data
        )
        assert work_journal_response.status_code == 201
        work_journal_id = work_journal_response.json()["data"]["id"]

        # Create personal journal
        personal_journal_data = create_journal_request_data(
            title="Personal Note", content="Birthday ideas"
        )

        personal_journal_response = await integration_api_client.post(
            "/api/journals", json=personal_journal_data
        )
        assert personal_journal_response.status_code == 201
        personal_journal_id = personal_journal_response.json()["data"]["id"]

        # Assign work tag to work journal
        work_assignment_data = {
            "data": {
                "type": "journal-tag",
                "attributes": {
                    "tag_id": work_tag_id,
                },
            }
        }

        await integration_api_client.post(
            f"/api/journals/{work_journal_id}/relationships/tags",
            json=work_assignment_data,
        )

        # Assign personal tag to personal journal
        personal_assignment_data = {
            "data": {
                "type": "journal-tag",
                "attributes": {
                    "tag_id": personal_tag_id,
                },
            }
        }

        await integration_api_client.post(
            f"/api/journals/{personal_journal_id}/relationships/tags",
            json=personal_assignment_data,
        )

        # Filter by work tag
        filter_response = await integration_api_client.get(
            f"/api/journals?tag_id={work_tag_id}"
        )

        assert filter_response.status_code == 200
        journals = filter_response.json()["data"]

        # Should only return work journal
        journal_ids = [j["id"] for j in journals]
        assert work_journal_id in journal_ids
        assert personal_journal_id not in journal_ids

    async def test_filter_journals_by_tag_and_type(self, integration_api_client):
        """Test combined filtering by tag and journal type."""
        # Create a tag
        tag_data = {
            "data": {
                "type": "journal-tags",
                "attributes": {
                    "name": "project",
                    "color": "#0000FF",
                },
            }
        }

        tag_response = await integration_api_client.post(
            "/api/journals/tags", json=tag_data
        )
        assert tag_response.status_code == 201
        tag_id = tag_response.json()["data"]["id"]

        # Create a calendar for EVENT journals
        calendar_data = {
            "data": {
                "type": "calendars",
                "attributes": {
                    "name": "Project Calendar",
                    "color": "#3B82F6",
                },
            }
        }

        calendar_response = await integration_api_client.post(
            "/api/calendars", json=calendar_data
        )
        assert calendar_response.status_code == 201
        calendar_id = calendar_response.json()["data"]["id"]

        # Create NOTE journal with tag
        note_journal_data = create_journal_request_data(
            title="Project Notes", content="Initial planning"
        )

        note_response = await integration_api_client.post(
            "/api/journals", json=note_journal_data
        )
        assert note_response.status_code == 201
        note_journal_id = note_response.json()["data"]["id"]

        # Create EVENT journal with tag
        event_journal_data = create_journal_request_data(
            title="Project Kickoff",
            content="Team meeting",
            types=["EVENT"],
            type_data={
                "EVENT": {
                    "calendar_id": calendar_id,
                    "start_time": "09:00:00",
                    "end_time": "10:00:00",
                    "is_all_day": False,
                    "sync_invitees": False,
                }
            },
        )

        event_response = await integration_api_client.post(
            "/api/journals", json=event_journal_data
        )
        assert event_response.status_code == 201
        event_journal_id = event_response.json()["data"]["id"]

        # Assign tag to both journals
        assignment_data = {
            "data": {
                "type": "journal-tag",
                "attributes": {
                    "tag_id": tag_id,
                },
            }
        }

        await integration_api_client.post(
            f"/api/journals/{note_journal_id}/relationships/tags", json=assignment_data
        )

        await integration_api_client.post(
            f"/api/journals/{event_journal_id}/relationships/tags", json=assignment_data
        )

        # Filter by tag + NOTE type
        filter_response = await integration_api_client.get(
            f"/api/journals?tag_id={tag_id}&type=NOTE"
        )

        assert filter_response.status_code == 200
        journals = filter_response.json()["data"]

        # Should only return NOTE journal
        journal_ids = [j["id"] for j in journals]
        assert note_journal_id in journal_ids
        assert event_journal_id not in journal_ids
