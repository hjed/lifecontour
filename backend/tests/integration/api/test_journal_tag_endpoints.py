"""
Integration tests for journal tag endpoints.

Tests the POST /api/journals/tags endpoint for creating journal tags,
tag assignment to journals, and filtering journals by tags.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text


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


async def create_tag(client: Any, name: str, **attributes: Any) -> dict[str, Any]:
    """Create a journal tag via the API and return its resource."""
    response = await client.post(
        "/api/journals/tags",
        json={
            "data": {
                "type": "journal-tags",
                "attributes": {"name": name, **attributes},
            }
        },
    )
    assert response.status_code == 201, response.text
    resource: dict[str, Any] = response.json()["data"]
    return resource


async def patch_tag(client: Any, tag_id: str, **attributes: Any) -> Any:
    """PATCH a journal tag with the supplied attributes."""
    return await client.patch(
        f"/api/journals/tags/{tag_id}",
        json={
            "data": {
                "type": "journal-tags",
                "id": tag_id,
                "attributes": attributes,
            }
        },
    )


@pytest.mark.integration
class TestUpdateJournalTagEndpoint:
    """Tests for PATCH /api/journals/tags/{tag_id}."""

    async def test_patch_updates_name_colour_and_description(
        self, integration_api_client
    ):
        """Test PATCH updates all editable fields and persists them."""
        tag = await create_tag(
            integration_api_client, "training", color="#00FF00", description="Old"
        )

        response = await patch_tag(
            integration_api_client,
            tag["id"],
            name="conditioning",
            color="#123456",
            description="Structured conditioning work",
        )

        assert response.status_code == 200, response.text
        attributes = response.json()["data"]["attributes"]
        assert attributes["name"] == "conditioning"
        assert attributes["color"] == "#123456"
        assert attributes["description"] == "Structured conditioning work"

        # Re-read to prove the write committed before the response was sent.
        list_response = await integration_api_client.get("/api/journals/tags")
        persisted = next(
            t for t in list_response.json()["data"] if t["id"] == tag["id"]
        )
        assert persisted["attributes"]["name"] == "conditioning"
        assert persisted["attributes"]["description"] == "Structured conditioning work"

    async def test_patch_partial_update_leaves_other_fields(
        self, integration_api_client
    ):
        """Test omitted attributes are left untouched."""
        tag = await create_tag(
            integration_api_client, "training", color="#00FF00", description="Keep me"
        )

        response = await patch_tag(integration_api_client, tag["id"], name="cardio")

        assert response.status_code == 200
        attributes = response.json()["data"]["attributes"]
        assert attributes["name"] == "cardio"
        assert attributes["color"] == "#00FF00"
        assert attributes["description"] == "Keep me"

    async def test_patch_duplicate_name_returns_400(self, integration_api_client):
        """Test the case-insensitive unique index is enforced on update."""
        await create_tag(integration_api_client, "training")
        other = await create_tag(integration_api_client, "reflection")

        response = await patch_tag(integration_api_client, other["id"], name="TRAINING")

        assert response.status_code == 400
        error = response.json()["errors"][0]
        assert "already exists" in error["detail"].lower()

    async def test_patch_rename_to_own_name_different_case_succeeds(
        self, integration_api_client
    ):
        """Test re-casing a tag's own name is not a uniqueness conflict."""
        tag = await create_tag(integration_api_client, "training")

        response = await patch_tag(integration_api_client, tag["id"], name="Training")

        assert response.status_code == 200
        assert response.json()["data"]["attributes"]["name"] == "Training"

    async def test_patch_reparent_then_clear_parent(self, integration_api_client):
        """Test a tag can be re-parented and then moved back to the root."""
        parent = await create_tag(integration_api_client, "outdoors")
        child = await create_tag(integration_api_client, "climbing")

        reparent = await patch_tag(
            integration_api_client, child["id"], parent_id=parent["id"]
        )
        assert reparent.status_code == 200
        assert reparent.json()["data"]["attributes"]["parent_id"] == parent["id"]

        cleared = await patch_tag(integration_api_client, child["id"], parent_id=None)
        assert cleared.status_code == 200
        assert cleared.json()["data"]["attributes"]["parent_id"] is None

    async def test_patch_cycle_returns_400(self, integration_api_client):
        """Test a tag cannot become its own ancestor."""
        parent = await create_tag(integration_api_client, "outdoors")
        child = await create_tag(integration_api_client, "climbing")
        assert (
            await patch_tag(integration_api_client, child["id"], parent_id=parent["id"])
        ).status_code == 200

        response = await patch_tag(
            integration_api_client, parent["id"], parent_id=child["id"]
        )

        assert response.status_code == 400
        assert "circular" in response.json()["errors"][0]["detail"].lower()

    async def test_patch_self_parent_returns_400(self, integration_api_client):
        """Test a tag cannot be its own parent."""
        tag = await create_tag(integration_api_client, "training")

        response = await patch_tag(
            integration_api_client, tag["id"], parent_id=tag["id"]
        )

        assert response.status_code == 400

    async def test_patch_invalid_colour_returns_400(self, integration_api_client):
        """Test a malformed colour is rejected."""
        tag = await create_tag(integration_api_client, "training")

        response = await patch_tag(integration_api_client, tag["id"], color="green")

        assert response.status_code == 400

    async def test_patch_unknown_tag_returns_404(self, integration_api_client):
        """Test updating a tag that does not exist returns 404."""
        response = await patch_tag(
            integration_api_client,
            "00000000-0000-0000-0000-000000000000",
            name="ghost",
        )

        assert response.status_code == 404

    async def test_patch_unknown_parent_returns_404(self, integration_api_client):
        """Test re-parenting under a tag that does not exist returns 404."""
        tag = await create_tag(integration_api_client, "training")

        response = await patch_tag(
            integration_api_client,
            tag["id"],
            parent_id="00000000-0000-0000-0000-000000000000",
        )

        assert response.status_code == 404

    async def test_patch_invalid_id_format_returns_400(self, integration_api_client):
        """Test a non-UUID path id is rejected."""
        response = await patch_tag(integration_api_client, "not-a-uuid", name="x")

        assert response.status_code == 400

    async def test_patch_wrong_resource_type_returns_400(self, integration_api_client):
        """Test the JSON:API resource type is validated."""
        tag = await create_tag(integration_api_client, "training")

        response = await integration_api_client.patch(
            f"/api/journals/tags/{tag['id']}",
            json={
                "data": {
                    "type": "tags",
                    "id": tag["id"],
                    "attributes": {"name": "renamed"},
                }
            },
        )

        assert response.status_code == 400

    async def test_patch_empty_resource_type_returns_400(self, integration_api_client):
        """Test a falsy but invalid resource type is rejected, not skipped."""
        tag = await create_tag(integration_api_client, "training")

        response = await integration_api_client.patch(
            f"/api/journals/tags/{tag['id']}",
            json={
                "data": {
                    "type": "",
                    "id": tag["id"],
                    "attributes": {"name": "renamed"},
                }
            },
        )

        assert response.status_code == 400

    async def test_patch_body_id_case_insensitive_match(self, integration_api_client):
        """Test a body id differing only in case is accepted as the same UUID."""
        tag = await create_tag(integration_api_client, "training")

        response = await integration_api_client.patch(
            f"/api/journals/tags/{tag['id']}",
            json={
                "data": {
                    "type": "journal-tags",
                    "id": tag["id"].upper(),
                    "attributes": {"name": "renamed"},
                }
            },
        )

        assert response.status_code == 200
        assert response.json()["data"]["attributes"]["name"] == "renamed"

    async def test_patch_malformed_body_id_returns_400(self, integration_api_client):
        """Test a non-UUID body id is rejected."""
        tag = await create_tag(integration_api_client, "training")

        response = await integration_api_client.patch(
            f"/api/journals/tags/{tag['id']}",
            json={
                "data": {
                    "type": "journal-tags",
                    "id": "not-a-uuid",
                    "attributes": {"name": "renamed"},
                }
            },
        )

        assert response.status_code == 400

    async def test_patch_body_id_mismatch_returns_400(self, integration_api_client):
        """Test a body id that disagrees with the path is rejected."""
        tag = await create_tag(integration_api_client, "training")
        other = await create_tag(integration_api_client, "reflection")

        response = await integration_api_client.patch(
            f"/api/journals/tags/{tag['id']}",
            json={
                "data": {
                    "type": "journal-tags",
                    "id": other["id"],
                    "attributes": {"name": "renamed"},
                }
            },
        )

        assert response.status_code == 400

    async def test_patch_empty_parent_id_returns_400(self, integration_api_client):
        """Test an empty-string parent_id is rejected, not silently ignored."""
        tag = await create_tag(integration_api_client, "training")

        response = await patch_tag(integration_api_client, tag["id"], parent_id="")

        assert response.status_code == 400

    async def test_patch_explicit_null_name_returns_400(self, integration_api_client):
        """Test an explicit null name is rejected rather than clearing the name."""
        tag = await create_tag(integration_api_client, "training")

        response = await patch_tag(integration_api_client, tag["id"], name=None)

        assert response.status_code == 400


async def create_journal_with_tag(
    client: Any, title: str, tag_id: str
) -> dict[str, Any]:
    """Create a journal and assign ``tag_id`` to it, returning the journal resource."""
    journal_response = await client.post(
        "/api/journals",
        json=create_journal_request_data(title=title, content="content"),
    )
    assert journal_response.status_code == 201, journal_response.text
    journal: dict[str, Any] = journal_response.json()["data"]

    assign_response = await client.post(
        f"/api/journals/{journal['id']}/relationships/tags",
        json={"data": {"type": "journal-tag", "attributes": {"tag_id": tag_id}}},
    )
    assert assign_response.status_code == 200, assign_response.text
    assigned: dict[str, Any] = assign_response.json()["data"]
    return assigned


@pytest.mark.integration
class TestDeleteJournalTagEndpoint:
    """Tests for DELETE /api/journals/tags/{tag_id}.

    Delete mirrors contact tag delete: it always succeeds, un-assigning the tag
    from every journal rather than returning 409 when the tag is in use.
    """

    async def test_delete_unused_tag_returns_204(self, integration_api_client):
        """Test deleting an unassigned tag removes it from the tag list."""
        tag = await create_tag(integration_api_client, "obsolete")

        response = await integration_api_client.delete(
            f"/api/journals/tags/{tag['id']}"
        )

        assert response.status_code == 204, response.text

        list_response = await integration_api_client.get("/api/journals/tags")
        tag_ids = [t["id"] for t in list_response.json()["data"]]
        assert tag["id"] not in tag_ids

    async def test_delete_tag_in_use_removes_it_from_journals(
        self, integration_api_client
    ):
        """Test deleting an assigned tag succeeds and un-assigns it.

        This is the parity change: the endpoint previously returned 409 here.
        """
        tag = await create_tag(integration_api_client, "in-use", color="#FF0000")
        journal = await create_journal_with_tag(
            integration_api_client, "Tagged journal", tag["id"]
        )
        assert len(journal["attributes"]["tags"]) == 1

        response = await integration_api_client.delete(
            f"/api/journals/tags/{tag['id']}"
        )

        assert response.status_code == 204, response.text

        journal_response = await integration_api_client.get(
            f"/api/journals/{journal['id']}"
        )
        assert journal_response.status_code == 200
        assert journal_response.json()["data"]["attributes"]["tags"] == []

    async def test_delete_parent_tag_reparents_children_to_null(
        self, integration_api_client
    ):
        """Test children of a deleted tag survive as root tags."""
        parent = await create_tag(integration_api_client, "outdoors")
        child = await create_tag(
            integration_api_client, "climbing", parent_id=parent["id"]
        )

        response = await integration_api_client.delete(
            f"/api/journals/tags/{parent['id']}"
        )

        assert response.status_code == 204, response.text

        list_response = await integration_api_client.get("/api/journals/tags")
        tags = {t["id"]: t for t in list_response.json()["data"]}
        assert parent["id"] not in tags
        assert child["id"] in tags
        assert tags[child["id"]]["attributes"]["parent_id"] is None

    async def test_delete_missing_tag_returns_404(self, integration_api_client):
        """Test deleting an unknown tag id returns 404."""
        response = await integration_api_client.delete(f"/api/journals/tags/{uuid4()}")

        assert response.status_code == 404

    async def test_delete_invalid_uuid_returns_400(self, integration_api_client):
        """Test a malformed tag id is rejected before any lookup."""
        response = await integration_api_client.delete("/api/journals/tags/not-a-uuid")

        assert response.status_code == 400


async def merge_tag(client: Any, source_id: str, target_id: str) -> Any:
    """POST the merge of ``source_id`` into ``target_id``."""
    return await client.post(
        f"/api/journals/tags/{source_id}/merge",
        json={
            "data": {
                "type": "journal-tags",
                "attributes": {"target_tag_id": target_id},
            }
        },
    )


@pytest.mark.integration
class TestMergeJournalTagEndpoint:
    """Tests for POST /api/journals/tags/{tag_id}/merge.

    Merge mirrors the contact tag merge: the source's assignments and children
    move to the target and the source tag is deleted.
    """

    async def test_merge_moves_assignments_and_deletes_source(
        self, integration_api_client
    ):
        """Test a journal tagged with the source ends up tagged with the target."""
        source = await create_tag(integration_api_client, "hiking")
        target = await create_tag(
            integration_api_client, "bushwalking", color="#00FF00"
        )
        journal = await create_journal_with_tag(
            integration_api_client, "Blue Mountains", source["id"]
        )

        response = await merge_tag(integration_api_client, source["id"], target["id"])

        assert response.status_code == 204, response.text

        journal_response = await integration_api_client.get(
            f"/api/journals/{journal['id']}"
        )
        tag_ids = [
            t["id"] for t in journal_response.json()["data"]["attributes"]["tags"]
        ]
        assert tag_ids == [target["id"]]

        list_response = await integration_api_client.get("/api/journals/tags")
        remaining = [t["id"] for t in list_response.json()["data"]]
        assert source["id"] not in remaining
        assert target["id"] in remaining

    async def test_merge_dedupes_when_journal_holds_both_tags(
        self, integration_api_client
    ):
        """Test a journal already carrying both tags keeps one assignment."""
        source = await create_tag(integration_api_client, "hiking")
        target = await create_tag(integration_api_client, "bushwalking")
        journal = await create_journal_with_tag(
            integration_api_client, "Both tags", source["id"]
        )
        assign = await integration_api_client.post(
            f"/api/journals/{journal['id']}/relationships/tags",
            json={
                "data": {"type": "journal-tag", "attributes": {"tag_id": target["id"]}}
            },
        )
        assert assign.status_code == 200, assign.text

        response = await merge_tag(integration_api_client, source["id"], target["id"])

        assert response.status_code == 204, response.text

        journal_response = await integration_api_client.get(
            f"/api/journals/{journal['id']}"
        )
        tag_ids = [
            t["id"] for t in journal_response.json()["data"]["attributes"]["tags"]
        ]
        assert tag_ids == [target["id"]]

    async def test_merge_reparents_source_children_to_target(
        self, integration_api_client
    ):
        """Test the source's children are adopted by the target."""
        source = await create_tag(integration_api_client, "hiking")
        target = await create_tag(integration_api_client, "bushwalking")
        child = await create_tag(
            integration_api_client, "day walks", parent_id=source["id"]
        )

        response = await merge_tag(integration_api_client, source["id"], target["id"])

        assert response.status_code == 204, response.text

        list_response = await integration_api_client.get("/api/journals/tags")
        tags = {t["id"]: t for t in list_response.json()["data"]}
        assert tags[child["id"]]["attributes"]["parent_id"] == target["id"]

    async def test_merge_into_self_returns_400(self, integration_api_client):
        """Test merging a tag into itself is rejected."""
        tag = await create_tag(integration_api_client, "hiking")

        response = await merge_tag(integration_api_client, tag["id"], tag["id"])

        assert response.status_code == 400

    async def test_merge_into_descendant_returns_400(self, integration_api_client):
        """Test merging a tag into its own child is rejected."""
        parent = await create_tag(integration_api_client, "outdoors")
        child = await create_tag(
            integration_api_client, "climbing", parent_id=parent["id"]
        )

        response = await merge_tag(integration_api_client, parent["id"], child["id"])

        assert response.status_code == 400

    async def test_merge_unknown_source_returns_404(self, integration_api_client):
        """Test an unknown source tag returns 404."""
        target = await create_tag(integration_api_client, "bushwalking")

        response = await merge_tag(integration_api_client, str(uuid4()), target["id"])

        assert response.status_code == 404

    async def test_merge_unknown_target_returns_404(self, integration_api_client):
        """Test an unknown target tag returns 404 and leaves the source alone."""
        source = await create_tag(integration_api_client, "hiking")

        response = await merge_tag(integration_api_client, source["id"], str(uuid4()))

        assert response.status_code == 404

        list_response = await integration_api_client.get("/api/journals/tags")
        assert source["id"] in [t["id"] for t in list_response.json()["data"]]

    async def test_merge_invalid_source_uuid_returns_400(self, integration_api_client):
        """Test a malformed source id is rejected before any lookup."""
        target = await create_tag(integration_api_client, "bushwalking")

        response = await merge_tag(integration_api_client, "not-a-uuid", target["id"])

        assert response.status_code == 400

    async def test_merge_invalid_target_uuid_returns_400(self, integration_api_client):
        """Test a malformed target id is rejected."""
        source = await create_tag(integration_api_client, "hiking")

        response = await merge_tag(integration_api_client, source["id"], "not-a-uuid")

        assert response.status_code == 400

    async def test_merge_wrong_resource_type_returns_400(self, integration_api_client):
        """Test the JSON:API resource type is validated."""
        source = await create_tag(integration_api_client, "hiking")
        target = await create_tag(integration_api_client, "bushwalking")

        response = await integration_api_client.post(
            f"/api/journals/tags/{source['id']}/merge",
            json={
                "data": {
                    "type": "tags",
                    "attributes": {"target_tag_id": target["id"]},
                }
            },
        )

        assert response.status_code == 400


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
class TestJournalTagAssignmentHistoryEvents:
    """The relationship endpoints publish tag history events with UI provenance.

    Asserted on the ``outbox_events`` rows the request wrote, which is where the
    endpoint's responsibility ends — the relay and projection that turn them into
    feed entries are covered by
    ``tests/integration/infrastructure/events/test_journal_history_projection_e2e.py``.

    Note the fixture substitutes a SAVEPOINT for the real commit, so these tests
    show the event was written in the request's unit of work, not that it committed
    before the response; the ``@transactional`` service is what ties the two
    writes together.
    """

    @pytest_asyncio.fixture
    async def subject(
        self, integration_api_client, async_connection
    ) -> tuple[dict[str, Any], str]:
        """A journal and a uniquely-named tag, with the outbox cleared.

        Clearing last means every test starts with only the events its own action
        produces, so the assertions can be on exact counts.
        """
        tag = await create_tag(
            integration_api_client, f"history-{uuid4().hex[:8]}", color="#FF0000"
        )
        journal_response = await integration_api_client.post(
            "/api/journals",
            json=create_journal_request_data(
                title="Tag history subject", content="Carries the tag"
            ),
        )
        assert journal_response.status_code == 201

        await async_connection.execute(text("DELETE FROM outbox_events"))
        return tag, journal_response.json()["data"]["id"]

    @staticmethod
    async def tag_events(async_connection) -> list[tuple[str, dict[str, Any]]]:
        """(event_type, event_data) for every journal tag event in the outbox."""
        result = await async_connection.execute(
            text(
                "SELECT event_type, event_data FROM outbox_events "
                "WHERE event_type IN ('JournalTagAssigned', 'JournalTagRemoved') "
                "ORDER BY id"
            )
        )
        return [
            (row[0], json.loads(row[1]) if isinstance(row[1], str) else row[1])
            for row in result.fetchall()
        ]

    @staticmethod
    async def assign(client, journal_id: str, tag_id: str):
        return await client.post(
            f"/api/journals/{journal_id}/relationships/tags",
            json={"data": {"type": "journal-tag", "attributes": {"tag_id": tag_id}}},
        )

    async def test_assign_publishes_journal_tag_assigned_with_ui_provenance(
        self, integration_api_client, async_connection, subject
    ):
        tag, journal_id = subject

        response = await self.assign(integration_api_client, journal_id, tag["id"])
        assert response.status_code == 200

        events = await self.tag_events(async_connection)
        assert len(events) == 1
        event_type, data = events[0]
        assert event_type == "JournalTagAssigned"
        assert data["journal_id"] == int(journal_id)
        assert data["tag_id"] == tag["id"]
        assert data["tag_name"] == tag["attributes"]["name"]
        assert data["source"] == "ui"
        assert data["changed_by"] == "ui"

    async def test_remove_publishes_journal_tag_removed_with_ui_provenance(
        self, integration_api_client, async_connection, subject
    ):
        tag, journal_id = subject
        await self.assign(integration_api_client, journal_id, tag["id"])
        await async_connection.execute(text("DELETE FROM outbox_events"))

        remove_response = await integration_api_client.delete(
            f"/api/journals/{journal_id}/relationships/tags/{tag['id']}"
        )
        assert remove_response.status_code == 200

        events = await self.tag_events(async_connection)
        assert len(events) == 1
        event_type, data = events[0]
        assert event_type == "JournalTagRemoved"
        assert data["journal_id"] == int(journal_id)
        assert data["tag_id"] == tag["id"]
        assert data["tag_name"] == tag["attributes"]["name"]
        assert data["source"] == "ui"
        assert data["changed_by"] == "ui"

    async def test_reassigning_the_same_tag_publishes_nothing(
        self, integration_api_client, async_connection, subject
    ):
        """A repeat POST is a no-op, so it must not add an "Added Tags" entry.

        The endpoint answers 200 either way (assignment is idempotent), so the
        outbox is the only place the difference is observable.
        """
        tag, journal_id = subject
        await self.assign(integration_api_client, journal_id, tag["id"])
        await async_connection.execute(text("DELETE FROM outbox_events"))

        repeat = await self.assign(integration_api_client, journal_id, tag["id"])
        assert repeat.status_code == 200

        assert await self.tag_events(async_connection) == []

    async def test_removing_an_unassigned_tag_publishes_nothing(
        self, integration_api_client, async_connection, subject
    ):
        tag, journal_id = subject

        remove_response = await integration_api_client.delete(
            f"/api/journals/{journal_id}/relationships/tags/{tag['id']}"
        )
        assert remove_response.status_code == 200

        assert await self.tag_events(async_connection) == []

    async def test_removing_a_nonexistent_tag_stays_a_successful_no_op(
        self, integration_api_client, async_connection, subject
    ):
        """An unknown tag id is indistinguishable from an unassigned one here.

        Pinned because the service now loads the tag to name it in the event, and
        raising for a missing row would have turned this long-standing 200 into a
        404.
        """
        _, journal_id = subject

        remove_response = await integration_api_client.delete(
            f"/api/journals/{journal_id}/relationships/tags/{uuid4()}"
        )
        assert remove_response.status_code == 200

        assert await self.tag_events(async_connection) == []


@pytest.mark.integration
class TestJournalTagRenameHistoryEvents:
    """PATCH publishes a rename event for every journal carrying the tag.

    Asserted on the ``outbox_events`` rows the request wrote, matching
    ``TestJournalTagAssignmentHistoryEvents``; the relay and projection that turn
    them into feed entries are covered by
    ``tests/integration/infrastructure/events/test_journal_history_projection_e2e.py``.
    """

    @pytest_asyncio.fixture
    async def tag_on_two_journals(
        self, integration_api_client, async_connection
    ) -> tuple[dict[str, Any], list[int]]:
        """A tag assigned to two journals, with the outbox cleared afterwards.

        Two journals rather than one so the fan-out is observable: a single
        journal would pass even if the service published exactly one event
        regardless of how many journals carry the tag.
        """
        tag = await create_tag(
            integration_api_client, f"rename-{uuid4().hex[:8]}", color="#FF0000"
        )
        journal_ids = []
        for index in range(2):
            journal_response = await integration_api_client.post(
                "/api/journals",
                json=create_journal_request_data(
                    title=f"Rename subject {index}", content="Carries the tag"
                ),
            )
            assert journal_response.status_code == 201
            journal_id = journal_response.json()["data"]["id"]
            journal_ids.append(int(journal_id))

            assign = await integration_api_client.post(
                f"/api/journals/{journal_id}/relationships/tags",
                json={
                    "data": {
                        "type": "journal-tag",
                        "attributes": {"tag_id": tag["id"]},
                    }
                },
            )
            assert assign.status_code == 200

        await async_connection.execute(text("DELETE FROM outbox_events"))
        return tag, journal_ids

    @staticmethod
    async def rename_events(async_connection) -> list[dict[str, Any]]:
        """The ``event_data`` of every rename event in the outbox, in order."""
        result = await async_connection.execute(
            text(
                "SELECT event_data FROM outbox_events "
                "WHERE event_type = 'JournalTagRenamed' ORDER BY id"
            )
        )
        return [
            json.loads(row[0]) if isinstance(row[0], str) else row[0]
            for row in result.fetchall()
        ]

    async def test_rename_publishes_one_event_per_journal_with_ui_provenance(
        self, integration_api_client, async_connection, tag_on_two_journals
    ):
        tag, journal_ids = tag_on_two_journals
        old_name = tag["attributes"]["name"]
        new_name = f"{old_name}-renamed"

        response = await patch_tag(integration_api_client, tag["id"], name=new_name)
        assert response.status_code == 200

        events = await self.rename_events(async_connection)
        assert [event["journal_id"] for event in events] == journal_ids
        for event in events:
            assert event["tag_id"] == tag["id"]
            assert event["old_name"] == old_name
            assert event["new_name"] == new_name
            assert event["source"] == "ui"
            assert event["changed_by"] == "ui"

    async def test_colour_only_change_publishes_nothing(
        self, integration_api_client, async_connection, tag_on_two_journals
    ):
        """A recolour is invisible on a journal, so it must leave no history."""
        tag, _ = tag_on_two_journals

        response = await patch_tag(integration_api_client, tag["id"], color="#00FF00")
        assert response.status_code == 200

        assert await self.rename_events(async_connection) == []

    async def test_resending_the_same_name_publishes_nothing(
        self, integration_api_client, async_connection, tag_on_two_journals
    ):
        """The endpoint answers 200 either way, so the outbox is the only tell."""
        tag, _ = tag_on_two_journals

        response = await patch_tag(
            integration_api_client, tag["id"], name=tag["attributes"]["name"]
        )
        assert response.status_code == 200

        assert await self.rename_events(async_connection) == []

    async def test_renaming_an_unassigned_tag_publishes_nothing(
        self, integration_api_client, async_connection
    ):
        """No journal carries the tag, so no journal's feed changed."""
        tag = await create_tag(integration_api_client, f"lonely-{uuid4().hex[:8]}")
        await async_connection.execute(text("DELETE FROM outbox_events"))

        response = await patch_tag(
            integration_api_client, tag["id"], name=f"lonely-{uuid4().hex[:8]}"
        )
        assert response.status_code == 200

        assert await self.rename_events(async_connection) == []

    async def test_a_rejected_rename_publishes_nothing(
        self, integration_api_client, async_connection, tag_on_two_journals
    ):
        """A duplicate name is refused, so it must not reach the activity feed."""
        tag, _ = tag_on_two_journals
        taken = await create_tag(integration_api_client, f"taken-{uuid4().hex[:8]}")
        await async_connection.execute(text("DELETE FROM outbox_events"))

        response = await patch_tag(
            integration_api_client, tag["id"], name=taken["attributes"]["name"]
        )
        assert response.status_code == 400

        assert await self.rename_events(async_connection) == []


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


@pytest.mark.integration
class TestJournalHierarchicalTagFiltering:
    """GET /api/journals multi-tag and descendant-expanding filtering.

    Mirrors the contact list behaviour: repeated ``tag_ids`` params combine as a
    logical OR, and each requested tag expands to its descendants.
    """

    @staticmethod
    async def _create_tag(client, name: str, parent_id: str | None = None) -> str:
        attributes: dict[str, Any] = {"name": name, "color": "#FF0000"}
        if parent_id is not None:
            attributes["parent_id"] = parent_id
        response = await client.post(
            "/api/journals/tags",
            json={"data": {"type": "journal-tags", "attributes": attributes}},
        )
        assert response.status_code == 201, response.text
        return str(response.json()["data"]["id"])

    @staticmethod
    async def _create_journal(client, title: str) -> str:
        response = await client.post(
            "/api/journals",
            json=create_journal_request_data(title=title, content="content"),
        )
        assert response.status_code == 201, response.text
        return str(response.json()["data"]["id"])

    @staticmethod
    async def _assign_tag(client, journal_id: str, tag_id: str) -> None:
        response = await client.post(
            f"/api/journals/{journal_id}/relationships/tags",
            json={"data": {"type": "journal-tag", "attributes": {"tag_id": tag_id}}},
        )
        assert response.status_code in (200, 201), response.text

    async def test_parent_tag_returns_child_tagged_journal(
        self, integration_api_client
    ):
        parent_id = await self._create_tag(integration_api_client, "outdoors")
        child_id = await self._create_tag(
            integration_api_client, "climbing", parent_id=parent_id
        )
        journal_id = await self._create_journal(integration_api_client, "Child Tagged")
        await self._assign_tag(integration_api_client, journal_id, child_id)

        response = await integration_api_client.get(
            f"/api/journals?tag_ids={parent_id}"
        )

        assert response.status_code == 200
        assert [j["id"] for j in response.json()["data"]] == [journal_id]

    async def test_grandchild_tagged_journal_matches_root_tag(
        self, integration_api_client
    ):
        root_id = await self._create_tag(integration_api_client, "outdoors")
        child_id = await self._create_tag(
            integration_api_client, "climbing", parent_id=root_id
        )
        grandchild_id = await self._create_tag(
            integration_api_client, "sport-climbing", parent_id=child_id
        )
        journal_id = await self._create_journal(
            integration_api_client, "Grandchild Tagged"
        )
        await self._assign_tag(integration_api_client, journal_id, grandchild_id)

        response = await integration_api_client.get(f"/api/journals?tag_ids={root_id}")

        assert response.status_code == 200
        assert [j["id"] for j in response.json()["data"]] == [journal_id]

    async def test_leaf_tag_does_not_expand_upwards(self, integration_api_client):
        parent_id = await self._create_tag(integration_api_client, "outdoors")
        child_id = await self._create_tag(
            integration_api_client, "climbing", parent_id=parent_id
        )
        parent_journal_id = await self._create_journal(
            integration_api_client, "Parent Tagged"
        )
        child_journal_id = await self._create_journal(
            integration_api_client, "Child Tagged"
        )
        await self._assign_tag(integration_api_client, parent_journal_id, parent_id)
        await self._assign_tag(integration_api_client, child_journal_id, child_id)

        response = await integration_api_client.get(f"/api/journals?tag_ids={child_id}")

        assert response.status_code == 200
        assert [j["id"] for j in response.json()["data"]] == [child_journal_id]

    async def test_multiple_tag_ids_return_the_union(self, integration_api_client):
        work_id = await self._create_tag(integration_api_client, "work")
        personal_id = await self._create_tag(integration_api_client, "personal")
        other_id = await self._create_tag(integration_api_client, "other")
        work_journal_id = await self._create_journal(
            integration_api_client, "Work Journal"
        )
        personal_journal_id = await self._create_journal(
            integration_api_client, "Personal Journal"
        )
        other_journal_id = await self._create_journal(
            integration_api_client, "Other Journal"
        )
        await self._assign_tag(integration_api_client, work_journal_id, work_id)
        await self._assign_tag(integration_api_client, personal_journal_id, personal_id)
        await self._assign_tag(integration_api_client, other_journal_id, other_id)

        response = await integration_api_client.get(
            f"/api/journals?tag_ids={work_id}&tag_ids={personal_id}"
        )

        assert response.status_code == 200
        body = response.json()
        assert {j["id"] for j in body["data"]} == {
            work_journal_id,
            personal_journal_id,
        }
        assert body["meta"]["total_count"] == 2

    async def test_journal_with_both_filter_tags_counted_once(
        self, integration_api_client
    ):
        work_id = await self._create_tag(integration_api_client, "work")
        personal_id = await self._create_tag(integration_api_client, "personal")
        journal_id = await self._create_journal(integration_api_client, "Both Tags")
        await self._assign_tag(integration_api_client, journal_id, work_id)
        await self._assign_tag(integration_api_client, journal_id, personal_id)

        response = await integration_api_client.get(
            f"/api/journals?tag_ids={work_id}&tag_ids={personal_id}"
        )

        assert response.status_code == 200
        body = response.json()
        assert [j["id"] for j in body["data"]] == [journal_id]
        assert body["meta"]["total_count"] == 1

    async def test_legacy_singular_tag_id_still_filters_and_expands(
        self, integration_api_client
    ):
        """``tag_id`` is retained for the frontend until ITER17-002 Phase 2."""
        parent_id = await self._create_tag(integration_api_client, "outdoors")
        child_id = await self._create_tag(
            integration_api_client, "climbing", parent_id=parent_id
        )
        journal_id = await self._create_journal(integration_api_client, "Child Tagged")
        await self._assign_tag(integration_api_client, journal_id, child_id)
        untagged_id = await self._create_journal(integration_api_client, "Untagged")

        response = await integration_api_client.get(f"/api/journals?tag_id={parent_id}")

        assert response.status_code == 200
        journal_ids = [j["id"] for j in response.json()["data"]]
        assert journal_ids == [journal_id]
        assert untagged_id not in journal_ids

    async def test_tag_id_and_tag_ids_are_unioned(self, integration_api_client):
        work_id = await self._create_tag(integration_api_client, "work")
        personal_id = await self._create_tag(integration_api_client, "personal")
        work_journal_id = await self._create_journal(
            integration_api_client, "Work Journal"
        )
        personal_journal_id = await self._create_journal(
            integration_api_client, "Personal Journal"
        )
        await self._assign_tag(integration_api_client, work_journal_id, work_id)
        await self._assign_tag(integration_api_client, personal_journal_id, personal_id)

        response = await integration_api_client.get(
            f"/api/journals?tag_id={work_id}&tag_ids={personal_id}"
        )

        assert response.status_code == 200
        assert {j["id"] for j in response.json()["data"]} == {
            work_journal_id,
            personal_journal_id,
        }

    async def test_tag_filter_ands_with_type_filter(self, integration_api_client):
        parent_id = await self._create_tag(integration_api_client, "outdoors")
        child_id = await self._create_tag(
            integration_api_client, "climbing", parent_id=parent_id
        )
        note_journal_id = await self._create_journal(
            integration_api_client, "Note Journal"
        )
        await self._assign_tag(integration_api_client, note_journal_id, child_id)

        matching = await integration_api_client.get(
            f"/api/journals?tag_ids={parent_id}&type=NOTE"
        )
        non_matching = await integration_api_client.get(
            f"/api/journals?tag_ids={parent_id}&type=MOOD_RATING"
        )

        assert [j["id"] for j in matching.json()["data"]] == [note_journal_id]
        assert non_matching.json()["data"] == []

    async def test_malformed_tag_id_is_rejected(self, integration_api_client):
        """Malformed ids are a client error, not a database failure."""
        assert (
            await integration_api_client.get("/api/journals?tag_ids=not-a-uuid")
        ).status_code == 400
        assert (
            await integration_api_client.get("/api/journals?tag_id=not-a-uuid")
        ).status_code == 400

    async def test_unknown_tag_id_returns_no_journals(self, integration_api_client):
        await self._create_journal(integration_api_client, "Untagged")

        response = await integration_api_client.get(f"/api/journals?tag_ids={uuid4()}")

        assert response.status_code == 200
        assert response.json()["data"] == []
