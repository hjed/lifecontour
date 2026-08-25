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


@pytest.mark.integration
class TestATaskAppearsOnAContactsHistoryEndpoint:
    """The read-only record the specification's *Contacts on tasks* asks for.

    The row is written by the projection onto the **task**; the contact
    aggregate reaches it by field name. These tests seed the read model directly
    for the reason the tests above give — projection is asynchronous and the
    end-to-end chain is asserted in
    ``tests/integration/infrastructure/events/test_task_history_projection_e2e.py``.
    """

    async def _seed_link_row(
        self,
        async_connection,
        *,
        task_id: int,
        contact_id: int,
        source,
        changed_by: str,
        linked: bool = True,
    ) -> None:
        from app.core.history.adapters.sql.field_history_repository import (
            SqlFieldHistoryRepository,
        )
        from app.core.history.models import FieldHistoryEntry
        from app.core.tasks.models.events import contact_field_name

        await SqlFieldHistoryRepository(async_connection).record_change(
            FieldHistoryEntry(
                entity_type="task",
                entity_id=task_id,
                field_name=contact_field_name(contact_id),
                old_value=None if linked else str(contact_id),
                new_value=str(contact_id) if linked else None,
                changed_by=changed_by,
                source=source,
                event_id=f"evt-{task_id}-{contact_id}-{changed_by}",
                user_id="test-user-123",
            )
        )

    @pytest.mark.asyncio
    async def test_the_record_is_returned_with_its_provenance(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
        async_connection,
        task_anchors,
    ):
        """Provenance is first-class: the entry says where the link came from."""
        from core_shared.models.history import Provenance

        from app.core.tasks.models.events import contact_field_name
        from tests.integration.tasks.task_seeding import create_task

        contact = await contact_factory.create_contact(
            first_name="Task", last_name="Linked"
        )
        contact_id = int(contact["id"])
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        await self._seed_link_row(
            async_connection,
            task_id=task_id,
            contact_id=contact_id,
            source=Provenance.UI,
            changed_by="ui",
        )

        response = await authenticated_client.get(f"/api/contacts/{contact_id}/history")

        assert response.status_code == 200
        entries = response.json()["data"]
        task_entries = [e for e in entries if e["attributes"]["entity_type"] == "task"]
        assert len(task_entries) == 1
        attrs = task_entries[0]["attributes"]
        assert attrs["entity_id"] == task_id
        assert attrs["field_name"] == contact_field_name(contact_id)
        assert attrs["source"] == "ui"
        assert attrs["changed_by"] == "ui"

    @pytest.mark.asyncio
    async def test_an_assistants_link_is_distinguishable_from_the_users(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
        async_connection,
        task_anchors,
    ):
        """``source`` and ``changed_by`` are separate facts and stay separate."""
        from core_shared.models.history import Provenance

        from tests.integration.tasks.task_seeding import create_task

        contact = await contact_factory.create_contact(
            first_name="Both", last_name="Origins"
        )
        contact_id = int(contact["id"])
        creating_id, due_id = task_anchors
        ui_task = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        mcp_task = await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="ask the assistant",
        )

        await self._seed_link_row(
            async_connection,
            task_id=ui_task,
            contact_id=contact_id,
            source=Provenance.UI,
            changed_by="ui",
        )
        await self._seed_link_row(
            async_connection,
            task_id=mcp_task,
            contact_id=contact_id,
            source=Provenance.MCP,
            changed_by="mcp",
        )

        response = await authenticated_client.get(f"/api/contacts/{contact_id}/history")

        assert response.status_code == 200
        entries = response.json()["data"]
        by_task = {
            e["attributes"]["entity_id"]: e["attributes"]
            for e in entries
            if e["attributes"]["entity_type"] == "task"
        }
        assert by_task[ui_task]["source"] == "ui"
        assert by_task[mcp_task]["source"] == "mcp"

    @pytest.mark.asyncio
    async def test_a_task_linked_to_someone_else_stays_off_this_contact(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
        async_connection,
        task_anchors,
    ):
        from core_shared.models.history import Provenance

        from tests.integration.tasks.task_seeding import create_task

        mine = await contact_factory.create_contact(first_name="Mine", last_name="Own")
        theirs = await contact_factory.create_contact(
            first_name="Someone", last_name="Else"
        )
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        await self._seed_link_row(
            async_connection,
            task_id=task_id,
            contact_id=int(theirs["id"]),
            source=Provenance.UI,
            changed_by="ui",
        )

        response = await authenticated_client.get(f"/api/contacts/{mine['id']}/history")

        assert response.status_code == 200
        entries = response.json()["data"]
        assert [e for e in entries if e["attributes"]["entity_type"] == "task"] == []

    @pytest.mark.asyncio
    async def test_the_pagination_meta_counts_the_task_record(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
        async_connection,
        task_anchors,
    ):
        """The count and the list share a predicate, so they share an answer.

        A branch that reached the list but not the count would advertise a
        "Load More" that returns nothing.
        """
        from core_shared.models.history import Provenance

        from tests.integration.tasks.task_seeding import create_task

        contact = await contact_factory.create_contact(
            first_name="Paged", last_name="Task"
        )
        contact_id = int(contact["id"])
        baseline = await authenticated_client.get(
            f"/api/contacts/{contact_id}/history?page=1&limit=10"
        )
        assert baseline.status_code == 200
        before = baseline.json()["meta"]["total_count"]

        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        await self._seed_link_row(
            async_connection,
            task_id=task_id,
            contact_id=contact_id,
            source=Provenance.UI,
            changed_by="ui",
        )

        response = await authenticated_client.get(
            f"/api/contacts/{contact_id}/history?page=1&limit=10"
        )

        assert response.status_code == 200
        body = response.json()
        # Pinned against a measured baseline rather than against the length of
        # the list beside it: ``total == len(data)`` is satisfied by a count and
        # a list that are wrong in the same way, which is exactly what a branch
        # reaching only one of the two statements produces.
        assert body["meta"]["total_count"] == before + 1
        assert len(body["data"]) == before + 1
        task_entries = [
            e for e in body["data"] if e["attributes"]["entity_type"] == "task"
        ]
        assert len(task_entries) == 1

    @pytest.mark.asyncio
    async def test_the_record_names_the_task_it_is_about(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
        async_connection,
        task_anchors,
    ):
        """Without a name the entry points at nothing the reader can identify.

        Both of the row's values are this contact's own id, and a task has no
        route of its own to link to instead, so the name is the only thing that
        makes the record a record *of something*.
        """
        from core_shared.models.history import Provenance

        from app.core.history.adapters.sql.field_history_repository import (
            SqlFieldHistoryRepository,
        )
        from app.core.history.models import CREATED_MARKER, FieldHistoryEntry
        from tests.integration.tasks.task_seeding import create_task

        contact = await contact_factory.create_contact(
            first_name="Named", last_name="Task"
        )
        contact_id = int(contact["id"])
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        await SqlFieldHistoryRepository(async_connection).record_change(
            FieldHistoryEntry(
                entity_type="task",
                entity_id=task_id,
                field_name=CREATED_MARKER,
                old_value=None,
                new_value="Return the borrowed harness",
                source=Provenance.UI,
                event_id=f"evt-created-{task_id}",
            )
        )
        await self._seed_link_row(
            async_connection,
            task_id=task_id,
            contact_id=contact_id,
            source=Provenance.UI,
            changed_by="ui",
        )

        response = await authenticated_client.get(f"/api/contacts/{contact_id}/history")

        assert response.status_code == 200
        entries = response.json()["data"]
        task_entries = [e for e in entries if e["attributes"]["entity_type"] == "task"]
        assert len(task_entries) == 1
        assert (
            task_entries[0]["attributes"]["entity_label"]
            == "Return the borrowed harness"
        )

    @pytest.mark.asyncio
    async def test_a_contacts_own_row_carries_no_label(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
        async_connection,
    ):
        """The field exists for rows whose subject is not the aggregate read.

        A contact's own row names itself, so a label there would be the reader
        telling themselves who they are.
        """
        from core_shared.models.history import Provenance

        from app.core.contacts.adapters.sql.contact_field_history_repository import (
            SqlContactFieldHistoryRepository,
        )
        from app.core.contacts.models.repositories import ContactFieldHistoryEntry

        contact = await contact_factory.create_contact(
            first_name="Plain", last_name="Row"
        )
        contact_id = int(contact["id"])
        await SqlContactFieldHistoryRepository(async_connection).record_change(
            ContactFieldHistoryEntry(
                entity_type="contact",
                entity_id=contact_id,
                field_name="first_name",
                old_value="Plain",
                new_value="Plainer",
                changed_by="ui",
                source=Provenance.UI,
                event_id=f"evt-plain-{contact_id}",
            )
        )

        response = await authenticated_client.get(f"/api/contacts/{contact_id}/history")

        assert response.status_code == 200
        entries = response.json()["data"]
        assert entries
        for entry in entries:
            if entry["attributes"]["entity_type"] != "task":
                assert entry["attributes"]["entity_label"] is None

    @pytest.mark.asyncio
    async def test_a_task_with_nothing_naming_it_yet_still_answers(
        self,
        authenticated_client,
        contact_factory: ContactFactory,
        async_connection,
        task_anchors,
    ):
        """Projection lags, so the link can land before the creation marker."""
        from core_shared.models.history import Provenance

        from tests.integration.tasks.task_seeding import create_task

        contact = await contact_factory.create_contact(
            first_name="Unnamed", last_name="Yet"
        )
        contact_id = int(contact["id"])
        creating_id, due_id = task_anchors
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )
        await self._seed_link_row(
            async_connection,
            task_id=task_id,
            contact_id=contact_id,
            source=Provenance.UI,
            changed_by="ui",
        )

        response = await authenticated_client.get(f"/api/contacts/{contact_id}/history")

        assert response.status_code == 200
        task_entries = [
            e
            for e in response.json()["data"]
            if e["attributes"]["entity_type"] == "task"
        ]
        assert len(task_entries) == 1
        assert task_entries[0]["attributes"]["entity_label"] is None
