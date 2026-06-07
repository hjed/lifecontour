"""Integration tests for tag API endpoints with hierarchical tag support."""

from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection

from app.main import create_app


@pytest_asyncio.fixture
async def tag_api_client(async_connection, clean_database, test_settings):  # noqa: ARG001
    """Create async test client for tag API integration tests with real database setup."""
    from dishka import Provider, Scope, make_async_container, provide
    from dishka.integrations.fastapi import FastapiProvider, setup_dishka

    from app.infrastructure.auth.models import SessionUser
    from app.infrastructure.di.contacts import ContactProvider
    from app.infrastructure.di.infrastructure import InfrastructureProvider
    from app.infrastructure.di.integrations import IntegrationProvider
    from app.infrastructure.di.journal import JournalProvider
    from app.infrastructure.di.settings import SettingsProvider

    class TestDatabaseProvider(Provider):
        def __init__(self, connection: AsyncConnection):
            super().__init__()
            self.connection = connection

        @provide(scope=Scope.REQUEST)
        async def get_connection(self) -> AsyncConnection:
            return self.connection

        @provide(scope=Scope.REQUEST)
        def get_session_user(self) -> SessionUser:
            return SessionUser(
                id="test-user-123",
                email="test@example.com",
                name="Test User",
                avatar_url="https://example.com/avatar.jpg",
                provider="test",
            )

    app = create_app(settings=test_settings)
    await app.state.dishka_container.close()

    test_container = make_async_container(
        TestDatabaseProvider(async_connection),
        InfrastructureProvider(),
        ContactProvider(),
        JournalProvider(),
        SettingsProvider(),
        IntegrationProvider(),
        FastapiProvider(),
    )
    app.state.dishka_container = test_container
    setup_dishka(test_container, app)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client

    await test_container.close()


@pytest.mark.integration
class TestTagEndpointsHierarchy:
    """Integration tests for tag API endpoints with hierarchical tag support."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_method(self, clean_database):  # noqa: ARG002
        """Setup method to ensure clean database for each test."""

    async def _create_tag(
        self, client: AsyncClient, name: str, *, parent_id: int | None = None
    ) -> dict[str, Any]:
        """Helper to create a tag via API."""
        attributes: dict[str, Any] = {"name": name}
        if parent_id is not None:
            attributes["parent_id"] = parent_id

        request_data = {
            "data": {
                "type": "tags",
                "attributes": attributes,
            }
        }
        response = await client.post("/api/tags", json=request_data)
        assert response.status_code == 201, (
            f"Failed to create tag '{name}': {response.text}"
        )
        result: dict[str, Any] = response.json()["data"]
        return result

    async def _create_contact(
        self, client: AsyncClient, first_name: str
    ) -> dict[str, Any]:
        """Helper to create a contact via API."""
        request_data = {
            "data": {
                "type": "contacts",
                "attributes": {
                    "first_name": first_name,
                    "contact_methods": [],
                    "addresses": [],
                    "notes": [],
                },
            }
        }
        response = await client.post("/api/contacts", json=request_data)
        assert response.status_code == 201
        result: dict[str, Any] = response.json()["data"]
        return result

    async def _assign_tag_to_contact(
        self, client: AsyncClient, contact_id: int, tag_id: int
    ) -> None:
        """Helper to assign a tag to a contact via API."""
        request_data = {"data": {"type": "tags", "id": str(tag_id)}}
        response = await client.post(
            f"/api/contacts/{contact_id}/tags", json=request_data
        )
        assert response.status_code in (
            200,
            201,
            204,
        ), f"Failed to assign tag {tag_id} to contact {contact_id}: {response.text}"

    # ---- Test 1: POST /api/tags with parent_id ----

    async def test_create_tag_with_parent_id(self, tag_api_client):
        """Test creating a tag with a valid parent_id."""
        parent = await self._create_tag(tag_api_client, "family")
        parent_id = int(parent["id"])

        child = await self._create_tag(tag_api_client, "extended", parent_id=parent_id)

        assert int(child["attributes"]["parent_id"]) == parent_id
        assert child["attributes"]["name"] == "extended"

    # ---- Test 2: POST /api/tags without parent_id ----

    async def test_create_tag_without_parent_id(self, tag_api_client):
        """Test creating a tag without parent_id — should be a root tag."""
        tag = await self._create_tag(tag_api_client, "standalone")

        assert tag["attributes"]["parent_id"] is None
        assert tag["attributes"]["name"] == "standalone"

    # ---- Test 3: POST /api/tags with invalid parent_id ----

    async def test_create_tag_with_invalid_parent_id(self, tag_api_client):
        """Test creating a tag with a non-existent parent_id returns an error."""
        request_data = {
            "data": {
                "type": "tags",
                "attributes": {
                    "name": "orphan",
                    "parent_id": 999999,
                },
            }
        }
        response = await tag_api_client.post("/api/tags", json=request_data)
        assert response.status_code == 404

    # ---- Test 4: GET /api/tags returns parent_id ----

    async def test_list_tags_includes_parent_id(self, tag_api_client):
        """Test that GET /api/tags response includes parent_id for each tag."""
        parent = await self._create_tag(tag_api_client, "business")
        parent_id = int(parent["id"])
        await self._create_tag(tag_api_client, "client", parent_id=parent_id)

        response = await tag_api_client.get("/api/tags")
        assert response.status_code == 200

        data = response.json()
        tags = data["data"]

        # Find our tags by name
        parent_tag = next(t for t in tags if t["attributes"]["name"] == "business")
        child_tag = next(t for t in tags if t["attributes"]["name"] == "client")

        assert parent_tag["attributes"]["parent_id"] is None
        assert int(child_tag["attributes"]["parent_id"]) == parent_id

    # ---- Test 5: GET /api/contacts?tag_ids=<parent> — descendant filtering ----

    async def test_filter_contacts_by_parent_tag_includes_descendants(
        self, tag_api_client
    ):
        """Filtering by a parent tag returns contacts tagged with child tags only."""
        # Create parent + child tags
        parent = await self._create_tag(tag_api_client, "family")
        parent_id = int(parent["id"])
        child = await self._create_tag(tag_api_client, "extended", parent_id=parent_id)
        child_id = int(child["id"])

        # Create a contact, assign only the child tag
        contact = await self._create_contact(tag_api_client, "ChildOnly")
        contact_id = int(contact["id"])
        await self._assign_tag_to_contact(tag_api_client, contact_id, child_id)

        # Filter by parent tag — should return the child-tagged contact
        response = await tag_api_client.get(f"/api/contacts?tag_ids={parent_id}")
        assert response.status_code == 200

        data = response.json()
        returned_ids = [int(c["id"]) for c in data["data"]]
        assert contact_id in returned_ids

    # ---- Test 6: GET /api/contacts?tag_ids=<leaf> — exact match ----

    async def test_filter_contacts_by_leaf_tag_returns_directly_tagged_only(
        self, tag_api_client
    ):
        """Filtering by a leaf tag returns only directly-tagged contacts."""
        parent = await self._create_tag(tag_api_client, "work")
        parent_id = int(parent["id"])
        child = await self._create_tag(tag_api_client, "project-a", parent_id=parent_id)
        child_id = int(child["id"])

        # Contact tagged with parent only
        parent_contact = await self._create_contact(tag_api_client, "ParentTagged")
        parent_contact_id = int(parent_contact["id"])
        await self._assign_tag_to_contact(tag_api_client, parent_contact_id, parent_id)

        # Contact tagged with child only
        child_contact = await self._create_contact(tag_api_client, "ChildTagged")
        child_contact_id = int(child_contact["id"])
        await self._assign_tag_to_contact(tag_api_client, child_contact_id, child_id)

        # Filter by leaf tag — should only return the child-tagged contact
        response = await tag_api_client.get(f"/api/contacts?tag_ids={child_id}")
        assert response.status_code == 200

        data = response.json()
        returned_ids = [int(c["id"]) for c in data["data"]]
        assert child_contact_id in returned_ids
        assert parent_contact_id not in returned_ids

    # ---- Test 7: Hierarchical tag names with / persist correctly ----

    async def test_create_tag_with_slash_in_name(self, tag_api_client):
        """Test creating a tag with '/' in the name for hierarchical path."""
        tag = await self._create_tag(tag_api_client, "work/engineering")

        assert tag["attributes"]["name"] == "work/engineering"

        # Verify it appears in the tag list
        response = await tag_api_client.get("/api/tags")
        assert response.status_code == 200

        data = response.json()
        tag_names = [t["attributes"]["name"] for t in data["data"]]
        assert "work/engineering" in tag_names

    async def test_create_tag_with_deep_hierarchical_name(self, tag_api_client):
        """Test creating a tag with multi-level hierarchy in name."""
        tag = await self._create_tag(tag_api_client, "org/dept/team")

        assert tag["attributes"]["name"] == "org/dept/team"

    @pytest.mark.parametrize("invalid_name", ["/leading", "trailing/", "a//b"], ids=str)
    async def test_create_tag_with_invalid_hierarchical_name_rejected(
        self, tag_api_client, invalid_name
    ):
        """Test that invalid hierarchical tag names are rejected at the domain layer.

        TagName raises ValueError for invalid patterns, which propagates through
        the ASGI transport as an unhandled exception. The unit tests in
        test_value_objects.py verify the exact validation rules. This integration
        test confirms the API does not silently accept invalid names.
        """
        request_data = {
            "data": {
                "type": "tags",
                "attributes": {"name": invalid_name},
            }
        }
        with pytest.raises(ValueError):
            await tag_api_client.post("/api/tags", json=request_data)

    # ---- Test 8: Combined favourite + parent tag filter ----

    async def test_filter_by_parent_tag_and_favourite(self, tag_api_client):
        """Filtering by parent tag + favourite=true returns only favourite+descendant contacts."""
        parent = await self._create_tag(tag_api_client, "network")
        parent_id = int(parent["id"])
        child = await self._create_tag(
            tag_api_client, "professional", parent_id=parent_id
        )
        child_id = int(child["id"])

        # Create two contacts with child tag: one favourite, one not
        fav_contact = await self._create_contact(tag_api_client, "FavContact")
        fav_contact_id = int(fav_contact["id"])
        await self._assign_tag_to_contact(tag_api_client, fav_contact_id, child_id)
        # Toggle favourite on
        toggle_resp = await tag_api_client.post(
            f"/api/contacts/{fav_contact_id}/favourite"
        )
        assert toggle_resp.status_code == 200

        non_fav_contact = await self._create_contact(tag_api_client, "NonFavContact")
        non_fav_contact_id = int(non_fav_contact["id"])
        await self._assign_tag_to_contact(tag_api_client, non_fav_contact_id, child_id)

        # Filter: parent tag + favourite
        response = await tag_api_client.get(
            f"/api/contacts?tag_ids={parent_id}&favourite=true"
        )
        assert response.status_code == 200

        data = response.json()
        returned_ids = [int(c["id"]) for c in data["data"]]
        assert fav_contact_id in returned_ids
        assert non_fav_contact_id not in returned_ids

    # ---- Test 9: Flat tags still work ----

    async def test_flat_tag_filtering_unchanged(self, tag_api_client):
        """Flat tags without parents continue to work as before."""
        tag = await self._create_tag(tag_api_client, "flat-tag")
        tag_id = int(tag["id"])

        contact = await self._create_contact(tag_api_client, "FlatTagContact")
        contact_id = int(contact["id"])
        await self._assign_tag_to_contact(tag_api_client, contact_id, tag_id)

        response = await tag_api_client.get(f"/api/contacts?tag_ids={tag_id}")
        assert response.status_code == 200

        data = response.json()
        returned_ids = [int(c["id"]) for c in data["data"]]
        assert contact_id in returned_ids

    # ---- Test 10: PATCH /api/tags/{tag_id} ----

    async def test_update_tag_success(self, tag_api_client):
        """Test updating a tag's name and color."""
        tag = await self._create_tag(tag_api_client, "old-name")
        tag_id = int(tag["id"])

        request_data = {
            "data": {
                "type": "tags",
                "id": str(tag_id),
                "attributes": {
                    "name": "new-name",
                    "color": "#FF0000",
                },
            }
        }
        response = await tag_api_client.patch(f"/api/tags/{tag_id}", json=request_data)
        assert response.status_code == 200

        updated = response.json()["data"]
        assert updated["attributes"]["name"] == "new-name"
        assert updated["attributes"]["color"] == "#FF0000"

    async def test_update_tag_clear_parent(self, tag_api_client):
        """Test clearing a tag's parent_id by passing null."""
        parent = await self._create_tag(tag_api_client, "parent")
        parent_id = int(parent["id"])

        child = await self._create_tag(tag_api_client, "child", parent_id=parent_id)
        child_id = int(child["id"])

        # Update and pass explicit None for parent_id
        request_data = {
            "data": {
                "type": "tags",
                "id": str(child_id),
                "attributes": {
                    "parent_id": None,
                },
            }
        }
        response = await tag_api_client.patch(
            f"/api/tags/{child_id}", json=request_data
        )
        assert response.status_code == 200

        updated = response.json()["data"]
        assert updated["attributes"]["parent_id"] is None

    async def test_update_tag_cycle(self, tag_api_client):
        """Test updating a tag to create a cycle returns validation error."""
        parent = await self._create_tag(tag_api_client, "cycle-a")
        parent_id = int(parent["id"])

        child = await self._create_tag(tag_api_client, "cycle-b", parent_id=parent_id)
        child_id = int(child["id"])

        # Try to make child the parent of its parent
        request_data = {
            "data": {
                "type": "tags",
                "id": str(parent_id),
                "attributes": {
                    "parent_id": child_id,
                },
            }
        }
        response = await tag_api_client.patch(
            f"/api/tags/{parent_id}", json=request_data
        )
        assert response.status_code == 422

        # Verify unprocessable entity / validation error for cycle
        errors = response.json()["errors"]
        assert len(errors) > 0
        assert (
            "cycle" in errors[0]["detail"].lower()
            or "circular reference" in errors[0]["detail"].lower()
        )

    # ---- Test 11: DELETE /api/tags/{tag_id} ----

    async def test_delete_tag(self, tag_api_client):
        """Test safely deleting a tag."""
        tag = await self._create_tag(tag_api_client, "to-delete")
        tag_id = int(tag["id"])

        response = await tag_api_client.delete(f"/api/tags/{tag_id}")
        assert response.status_code == 204

        # Verify not found
        get_response = await tag_api_client.get(f"/api/tags/{tag_id}")
        assert get_response.status_code == 404

    # ---- Test 12: POST /api/tags/{tag_id}/merge ----

    async def test_merge_tags(self, tag_api_client):
        """Test merging two tags together."""
        # Create target tag
        target_tag = await self._create_tag(tag_api_client, "target-tag")
        target_id = int(target_tag["id"])

        # Create source tag
        source_tag = await self._create_tag(tag_api_client, "source-tag")
        source_id = int(source_tag["id"])

        # Create child tag of source tag to ensure reparenting works
        child_tag = await self._create_tag(
            tag_api_client, "child-tag", parent_id=source_id
        )
        child_id = int(child_tag["id"])

        # Create a contact with the source tag to ensure reassigning works
        contact = await self._create_contact(tag_api_client, "MergeContact")
        contact_id = int(contact["id"])
        await self._assign_tag_to_contact(tag_api_client, contact_id, source_id)

        # Merge source into target
        request_data = {
            "data": {
                "type": "tags",
                "attributes": {
                    "target_tag_id": target_id,
                },
            }
        }
        response = await tag_api_client.post(
            f"/api/tags/{source_id}/merge", json=request_data
        )
        assert response.status_code == 204

        # Verify source tag is deleted
        get_source_response = await tag_api_client.get(f"/api/tags/{source_id}")
        assert get_source_response.status_code == 404

        # Verify contact now has target tag
        contacts_response = await tag_api_client.get(
            f"/api/contacts?tag_ids={target_id}"
        )
        assert contacts_response.status_code == 200
        returned_ids = [int(c["id"]) for c in contacts_response.json()["data"]]
        assert contact_id in returned_ids

        # Verify child tag is now reparented to target tag
        get_child_response = await tag_api_client.get(f"/api/tags/{child_id}")
        assert get_child_response.status_code == 200
        assert (
            int(get_child_response.json()["data"]["attributes"]["parent_id"])
            == target_id
        )
