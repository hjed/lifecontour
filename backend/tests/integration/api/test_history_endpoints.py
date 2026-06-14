"""Integration tests for contact history API endpoints."""

import pytest

from tests.integration.conftest import ContactFactory


class TestContactHistoryEndpoints:
    """Test contact history API endpoints."""

    @pytest.mark.asyncio
    async def test_get_contact_history_empty(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
    ):
        """Test getting history for a contact with no changes."""
        # Create a contact (only create, no updates)
        contact = await contact_factory.create_contact(
            first_name="John", last_name="Doe"
        )

        # Get history - should be empty initially (creation may not track changes)
        response = await authenticated_client.get(
            f"/api/contacts/{contact['id']}/history"
        )

        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert isinstance(data["data"], list)
        # History should exist and be a list (may or may not be empty)

    @pytest.mark.asyncio
    async def test_get_contact_history_returns_entry(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
        async_connection,
    ):
        """The endpoint returns a contact's history with the JSON:API shape.

        ITER12-003 Phase 2: history is produced by the event-driven projection
        (covered end-to-end in ``test_contact_history_projection_integration.py``),
        so this endpoint test seeds the read model directly via the repository —
        mirroring a projected first_name change — rather than relying on the async
        projection to have run after an HTTP update.
        """
        from core_shared.models.contacts.value_objects import Provenance

        from app.core.contacts.adapters.sql.contact_field_history_repository import (
            SqlContactFieldHistoryRepository,
        )
        from app.core.contacts.models.repositories import ContactFieldHistoryEntry

        contact = await contact_factory.create_contact(
            first_name="John", last_name="Doe"
        )
        contact_id = int(contact["id"])

        repo = SqlContactFieldHistoryRepository(async_connection)
        await repo.record_change(
            ContactFieldHistoryEntry(
                entity_type="contact",
                entity_id=contact_id,
                field_name="first_name",
                old_value="John",
                new_value="Jane",
                changed_by="ui",
                source=Provenance.UI,
            )
        )

        response = await authenticated_client.get(f"/api/contacts/{contact_id}/history")

        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert isinstance(data["data"], list)
        assert len(data["data"]) >= 1

        # Verify history entry structure
        history_entry = data["data"][0]
        assert history_entry["type"] == "contact_history"
        assert "id" in history_entry
        assert "attributes" in history_entry
        assert history_entry["attributes"]["entity_type"] == "contact"
        assert history_entry["attributes"]["field_name"] == "first_name"
        assert "created_at" in history_entry["attributes"]

    @pytest.mark.asyncio
    async def test_get_contact_history_pagination(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
    ):
        """Test history pagination with page and limit parameters."""
        # Create a contact
        contact = await contact_factory.create_contact(
            first_name="John", last_name="Doe"
        )

        # Get history with pagination params
        response = await authenticated_client.get(
            f"/api/contacts/{contact['id']}/history?page=1&limit=10"
        )

        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert "meta" in data
        # Meta should contain pagination info
        if data["meta"]:
            assert "current_page" in data["meta"]
            assert "per_page" in data["meta"]

    @pytest.mark.asyncio
    async def test_get_contact_history_not_found(
        self,
        authenticated_client,
    ):
        """Test getting history for non-existent contact returns 404."""
        response = await authenticated_client.get("/api/contacts/99999/history")

        assert response.status_code == 404
        data = response.json()
        assert "errors" in data

    @pytest.mark.asyncio
    async def test_get_contact_history_structure(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
    ):
        """Test that history response follows JSON API structure."""
        # Create and update contact
        contact = await contact_factory.create_contact(
            first_name="Original", last_name="Name"
        )

        update_data = {
            "data": {
                "type": "contacts",
                "id": contact["id"],
                "attributes": {
                    "first_name": "Updated",
                    "last_name": "Name",
                    "contact_methods": [],
                    "addresses": [],
                    "notes": [],
                },
            }
        }
        await authenticated_client.put(
            f"/api/contacts/{contact['id']}", json=update_data
        )

        response = await authenticated_client.get(
            f"/api/contacts/{contact['id']}/history"
        )

        assert response.status_code == 200
        data = response.json()

        # Verify JSON API structure
        assert "data" in data
        if len(data["data"]) > 0:
            entry = data["data"][0]
            # Required JSON API fields
            assert "type" in entry
            assert "id" in entry
            assert "attributes" in entry
            # Application-specific attributes
            attrs = entry["attributes"]
            assert "entity_type" in attrs
            assert "entity_id" in attrs
            assert "field_name" in attrs
            assert "old_value" in attrs or attrs.get("old_value") is None
            assert "new_value" in attrs or attrs.get("new_value") is None
            assert "created_at" in attrs

    @pytest.mark.asyncio
    async def test_get_contact_history_mixed_source(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
        async_connection,
    ):
        """Test chronological ordering of mixed source (UI, MCP, Sync, Summary) history."""

        from core_shared.models.contacts.value_objects import Provenance

        from app.core.contacts.adapters.sql.contact_field_history_repository import (
            SqlContactFieldHistoryRepository,
        )
        from app.core.contacts.models.repositories import ContactFieldHistoryEntry

        contact = await contact_factory.create_contact(
            first_name="Mixed", last_name="Source"
        )

        contact_id = int(contact["id"])

        # ITER12-003 Phase 2: the synchronous record_* service methods were removed
        # (history is projected from events). Seed the read model directly via the
        # repository, mirroring the rows the projection would write.
        repo = SqlContactFieldHistoryRepository(async_connection)

        async def _seed(
            field_name: str,
            old: str | None,
            new: str | None,
            *,
            changed_by: str,
            source: Provenance,
            entity_type: str = "contact",
        ) -> None:
            await repo.record_change(
                ContactFieldHistoryEntry(
                    entity_type=entity_type,
                    entity_id=contact_id,
                    field_name=field_name,
                    old_value=old,
                    new_value=new,
                    changed_by=changed_by,
                    source=source,
                )
            )

        # Ordering follows insertion (created_at + id tiebreaker), newest first.
        await _seed("first_name", "Mixed", "UI", changed_by="ui", source=Provenance.UI)
        await _seed(
            "last_name", "Source", "MCP", changed_by="mcp", source=Provenance.MCP
        )
        await _seed(
            "company",
            None,
            "Google",
            changed_by="system",
            source=Provenance.GOOGLE_CONTACTS,
        )
        await _seed(
            "summary_text",
            None,
            "AI generated summary",
            changed_by="system",
            source=Provenance.SUMMARY_REGENERATION,
            entity_type="contact_summary",
        )

        response = await authenticated_client.get(f"/api/contacts/{contact_id}/history")
        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        entries = data["data"]

        # Verify all sources are present
        sources = [entry["attributes"]["source"] for entry in entries]
        assert "summary_regeneration" in sources
        assert "google_contacts" in sources
        assert "mcp" in sources
        assert "ui" in sources

        # Verify chronological ordering (newest first)
        # We find the indices of each source in the response
        idx_summary = sources.index("summary_regeneration")
        idx_sync = sources.index("google_contacts")
        idx_mcp = sources.index("mcp")
        idx_ui = sources.index("ui")

        # Since API returns newest first (DESC), summary should be before sync, etc.
        assert idx_summary < idx_sync
        assert idx_sync < idx_mcp
        assert idx_mcp < idx_ui
