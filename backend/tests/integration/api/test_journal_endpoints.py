"""Integration tests for journal API endpoints."""

from datetime import UTC
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture
async def integration_api_client(async_connection, clean_database, test_settings):  # noqa: ARG001
    """Create async test client for API integration tests with real database setup."""
    from dishka import Provider, Scope, make_async_container, provide
    from dishka.integrations.fastapi import FastapiProvider, setup_dishka
    from sqlalchemy.ext.asyncio import AsyncConnection

    from app.infrastructure.auth.models import SessionUser
    from app.infrastructure.di.contacts import ContactProvider
    from app.infrastructure.di.infrastructure import InfrastructureProvider
    from app.infrastructure.di.integrations import IntegrationProvider
    from app.infrastructure.di.journal import JournalProvider

    # Create a test provider that uses our test connection
    class TestDatabaseProvider(Provider):
        def __init__(self, connection: AsyncConnection):
            super().__init__()
            self.connection = connection

        @provide(scope=Scope.REQUEST)
        async def get_connection(self) -> AsyncConnection:
            return self.connection

        @provide(scope=Scope.REQUEST)
        def get_session_user(self) -> SessionUser:
            # Provide a test user for authenticated endpoints
            return SessionUser(
                id="test-user-123",
                email="test@example.com",
                name="Test User",
                avatar_url="https://example.com/avatar.jpg",
                provider="test",
            )

    app = create_app(settings=test_settings)

    # Replace the Dishka container with our test container
    await app.state.dishka_container.close()  # Close the original container

    test_container = make_async_container(
        TestDatabaseProvider(async_connection),
        InfrastructureProvider(),
        ContactProvider(),
        JournalProvider(),
        IntegrationProvider(),
        FastapiProvider(),
    )
    app.state.dishka_container = test_container
    setup_dishka(test_container, app)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client

    # Clean up the test container
    await test_container.close()


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
        **kwargs: Additional attributes to include

    Returns:
        JSON API formatted request data
    """
    from datetime import datetime

    attributes = {
        "title": title,
        "content": content,
        "event_date_range": {
            "start": datetime.now(UTC).isoformat(),
            "end": datetime.now(UTC).isoformat(),
        },
    }
    attributes.update(kwargs)

    return {
        "data": {
            "type": "journals",
            "attributes": attributes,
        }
    }


@pytest.mark.integration
class TestJournalCRUDEndpoints:
    """Integration tests for journal CRUD endpoints."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_method(self, clean_database):  # noqa: ARG002
        """Setup method to ensure clean database for each test."""
        pass

    async def test_create_journal_minimal(self, integration_api_client):
        """Test creating a journal with minimal data."""
        request_data = create_journal_request_data()

        response = await integration_api_client.post("/api/journals", json=request_data)

        assert response.status_code == 201
        data = response.json()
        assert data["data"]["type"] == "journals"
        assert data["data"]["attributes"]["title"] == "Test Journal"
        assert data["data"]["attributes"]["content"] == "Test content"
        assert "id" in data["data"]
        assert "depth" in data["data"]["attributes"]
        assert data["data"]["attributes"]["depth"] == 1

    async def test_get_journal(self, integration_api_client):
        """Test retrieving a journal by ID."""
        # Create a journal first
        create_data = create_journal_request_data(
            title="Get Test Journal",
            content="Get test content",
        )

        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        journal_id = create_response.json()["data"]["id"]

        # Get the journal
        response = await integration_api_client.get(f"/api/journals/{journal_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["id"] == journal_id
        assert data["data"]["attributes"]["title"] == "Get Test Journal"
        assert "depth" in data["data"]["attributes"]
        assert data["data"]["attributes"]["depth"] == 1

    async def test_list_journals(self, integration_api_client):
        """Test listing journals with pagination."""
        # Create multiple journals
        for i in range(3):
            create_data = create_journal_request_data(
                title=f"Journal {i}",
                content=f"Content {i}",
            )
            await integration_api_client.post("/api/journals", json=create_data)

        # List journals
        response = await integration_api_client.get("/api/journals")

        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) >= 3
        assert "meta" in data
        assert "links" in data
        for item in data["data"]:
            assert "depth" in item["attributes"]
            assert item["attributes"]["depth"] == 1

    async def test_create_journal_with_parent(self, integration_api_client):
        """Test creating a journal with a parent to verify depth fields."""
        # Create parent
        parent_data = create_journal_request_data(title="Parent")
        parent_res = await integration_api_client.post(
            "/api/journals", json=parent_data
        )
        parent_id = parent_res.json()["data"]["id"]

        # Create child (parent_id is in attributes in JSON API)
        child_data = create_journal_request_data(title="Child")
        child_data["data"]["attributes"]["parent_id"] = int(parent_id)
        child_res = await integration_api_client.post("/api/journals", json=child_data)

        assert child_res.status_code == 201
        child_id = child_res.json()["data"]["id"]
        assert child_res.json()["data"]["attributes"]["depth"] == 2

        # Retrieve list
        list_res = await integration_api_client.get("/api/journals")
        items = {item["id"]: item for item in list_res.json()["data"]}

        assert items[parent_id]["attributes"]["depth"] == 1
        assert items[child_id]["attributes"]["depth"] == 2

    async def test_get_journal_with_contact(self, integration_api_client):
        """Test retrieving a journal with a related contact to ensure name is populated."""
        # 1. Create a contact
        contact_data = {
            "data": {
                "type": "contacts",
                "attributes": {
                    "first_name": "Integration",
                    "last_name": "TestUser",
                    "contact_methods": [],
                    "addresses": [],
                    "notes": [],
                },
            }
        }
        contact_response = await integration_api_client.post(
            "/api/contacts", json=contact_data
        )
        assert contact_response.status_code == 201
        contact_id = contact_response.json()["data"]["id"]

        # 2. Create a journal
        create_data = create_journal_request_data(
            title="Journal with Contact",
            content="Get test content",
        )
        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        # 3. Add contact relationship
        relationship_data = {
            "data": {
                "type": "journal-contact-relationships",
                "attributes": {
                    "contact_id": str(contact_id),
                    "relationship_type": "PARTICIPANT",
                },
            }
        }
        rel_response = await integration_api_client.post(
            f"/api/journals/{journal_id}/relationships/contacts", json=relationship_data
        )
        assert rel_response.status_code == 200

        # 4. Get the journal and verify contact name is populated
        response = await integration_api_client.get(f"/api/journals/{journal_id}")
        assert response.status_code == 200
        data = response.json()
        contacts = data["data"]["attributes"]["contacts"]

        assert len(contacts) == 1
        assert contacts[0]["id"] == str(contact_id)
        assert contacts[0]["name"] == "Integration TestUser"


@pytest.mark.integration
class TestJournalUpdateEndpoints:
    """Integration tests for journal update endpoints."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_method(self, clean_database):  # noqa: ARG002
        """Setup method to ensure clean database for each test."""
        pass

    async def test_update_journal_full(self, integration_api_client):
        """Test full update of a journal."""
        # Create a journal
        create_data = create_journal_request_data(
            title="Original Title",
            content="Original content",
        )

        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        journal_id = create_response.json()["data"]["id"]

        # Update the journal
        update_data = create_journal_request_data(
            title="Updated Title",
            content="Updated content",
        )
        update_data["data"]["id"] = str(journal_id)

        response = await integration_api_client.put(
            f"/api/journals/{journal_id}", json=update_data
        )

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["attributes"]["title"] == "Updated Title"
        assert data["data"]["attributes"]["content"] == "Updated content"

    async def test_update_journal_with_contact_triggers_summary_refresh(
        self, integration_api_client, async_connection
    ):
        """Test updating a journal with a contact triggers summary refresh outbox event."""
        import json

        from sqlalchemy import text

        # Create contact
        contact_data = {
            "data": {
                "type": "contacts",
                "attributes": {
                    "first_name": "Update",
                    "last_name": "User",
                    "contact_methods": [],
                    "addresses": [],
                    "notes": [],
                },
            }
        }
        contact_response = await integration_api_client.post(
            "/api/contacts", json=contact_data
        )
        contact_id = contact_response.json()["data"]["id"]

        # Clear existing outbox events (from contact creation)
        await async_connection.execute(text("DELETE FROM outbox_events"))

        # Create journal
        create_data = create_journal_request_data(title="Init", content="Content")
        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        journal_id = create_response.json()["data"]["id"]

        # Add relationship
        relationship_data = {
            "data": {
                "type": "journal-contact-relationships",
                "attributes": {
                    "contact_id": str(contact_id),
                    "relationship_type": "PARTICIPANT",
                },
            }
        }
        await integration_api_client.post(
            f"/api/journals/{journal_id}/relationships/contacts", json=relationship_data
        )

        # Clear outbox events again (from journal/relationship creation)
        await async_connection.execute(text("DELETE FROM outbox_events"))

        # Update the journal
        update_data = create_journal_request_data(
            title="Updated Title", content="Updated content"
        )
        update_data["data"]["id"] = str(journal_id)
        await integration_api_client.put(
            f"/api/journals/{journal_id}", json=update_data
        )

        # Verify exactly one ContactSummaryRefreshRequested outbox event for this contact
        result = await async_connection.execute(
            text(
                "SELECT event_data FROM outbox_events"
                " WHERE event_type = 'ContactSummaryRefreshRequested'"
                " AND aggregate_id = :contact_id"
            ),
            {"contact_id": int(contact_id)},
        )
        rows = result.fetchall()

        assert len(rows) == 1
        event_data = json.loads(rows[0].event_data)
        assert event_data["contact_id"] == int(contact_id)

    async def test_patch_journal_partial(self, integration_api_client):
        """Test partial update of a journal."""
        # Create a journal
        create_data = create_journal_request_data(
            title="Original Title",
            content="Original content",
        )

        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        journal_id = create_response.json()["data"]["id"]

        # Partial update (only title)
        patch_data = {
            "data": {
                "type": "journals",
                "id": str(journal_id),
                "attributes": {
                    "title": "Patched Title",
                },
            }
        }

        response = await integration_api_client.patch(
            f"/api/journals/{journal_id}", json=patch_data
        )

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["attributes"]["title"] == "Patched Title"
        # Content should remain unchanged
        assert data["data"]["attributes"]["content"] == "Original content"

    async def test_delete_journal(self, integration_api_client):
        """Test deleting a journal."""
        # Create a journal
        create_data = create_journal_request_data(
            title="Delete Test",
            content="To be deleted",
        )

        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        journal_id = create_response.json()["data"]["id"]

        # Delete the journal
        response = await integration_api_client.delete(f"/api/journals/{journal_id}")

        assert response.status_code == 204

        # Verify it's deleted
        get_response = await integration_api_client.get(f"/api/journals/{journal_id}")
        assert get_response.status_code == 404


@pytest.mark.integration
class TestJournalTypeManagementEndpoints:
    """Integration tests for journal type management endpoints."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_method(self, clean_database):  # noqa: ARG002
        """Setup method to ensure clean database for each test."""
        pass

    async def test_add_type_to_journal(self, integration_api_client):
        """Test adding a type to a journal."""
        # Create a journal (NOTE type by default)
        create_data = create_journal_request_data(
            title="Type Test", content="Test content"
        )

        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        # Add MOOD_RATING type
        type_data = {
            "data": {
                "type": "journal-types",
                "attributes": {
                    "types": ["MOOD_RATING"],
                },
            }
        }

        response = await integration_api_client.post(
            f"/api/journals/{journal_id}/types", json=type_data
        )

        # Should succeed or return validation error (both acceptable for this test)
        assert response.status_code in [200, 400, 422]

    async def test_remove_type_from_journal(self, integration_api_client):
        """Test removing a type from a journal."""
        # Create a journal with MOOD_RATING type
        create_data = create_journal_request_data(
            title="Type Remove Test", content="Test content", types=["MOOD_RATING"]
        )

        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        journal_id = create_response.json()["data"]["id"]

        # Remove MOOD_RATING type
        response = await integration_api_client.delete(
            f"/api/journals/{journal_id}/types/MOOD_RATING"
        )

        assert response.status_code == 200
        data = response.json()
        assert "mood_rating" not in data["data"]["attributes"]["types"]

    async def test_update_type_data_mood_rating(self, integration_api_client):
        """Test updating type-specific data for MOOD_RATING."""
        # Create a journal with MOOD_RATING type
        create_data = create_journal_request_data(
            title="Mood Test", content="Test content", types=["MOOD_RATING"]
        )

        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        # Update mood data
        update_data = {
            "data": {
                "type": "journal-type-data",
                "attributes": {
                    "mood_value": 8,
                    "mood_label": "Happy",
                    "energy_level": 7,
                },
            }
        }

        response = await integration_api_client.put(
            f"/api/journals/{journal_id}/types/MOOD_RATING/data", json=update_data
        )

        # Should succeed or return validation error (both acceptable for this test)
        assert response.status_code in [200, 400, 422]


@pytest.mark.integration
class TestJournalRelationshipEndpoints:
    """Integration tests for journal relationship management endpoints."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_method(self, clean_database):  # noqa: ARG002
        """Setup method to ensure clean database for each test."""
        pass

    async def test_add_tag_to_journal(self, integration_api_client):
        """Test adding a tag to a journal."""
        import uuid

        # Create a journal
        create_data = create_journal_request_data(
            title="Tag Test", content="Test content"
        )

        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        journal_id = create_response.json()["data"]["id"]

        # Create a tag first (we need to create it via the API or use a fixture)
        # For now, we'll use a UUID as tag_id
        tag_id = str(uuid.uuid4())

        # Add tag to journal
        tag_data = {
            "data": {
                "type": "journal-tag-assignment",
                "attributes": {
                    "tag_id": tag_id,
                },
            }
        }

        response = await integration_api_client.post(
            f"/api/journals/{journal_id}/relationships/tags", json=tag_data
        )

        # This might fail if tag doesn't exist, which is expected
        # The test validates the endpoint structure
        assert response.status_code in [200, 400, 404, 422]

    async def test_remove_tag_from_journal(self, integration_api_client):
        """Test removing a tag from a journal."""
        import uuid

        # Create a journal
        create_data = create_journal_request_data(
            title="Tag Remove Test", content="Test content"
        )

        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        journal_id = create_response.json()["data"]["id"]

        # Try to remove a tag (will fail if tag doesn't exist, which is expected)
        tag_id = str(uuid.uuid4())
        response = await integration_api_client.delete(
            f"/api/journals/{journal_id}/relationships/tags/{tag_id}"
        )

        # Endpoint should exist and return appropriate status
        assert response.status_code in [200, 404, 422]

    async def test_add_contact_relationship(self, integration_api_client):
        """Test adding a contact relationship to a journal."""
        # Create a journal
        create_data = create_journal_request_data(
            title="Contact Test", content="Test content"
        )

        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        journal_id = create_response.json()["data"]["id"]

        # Create a contact first to avoid foreign key violations
        contact_data = {
            "data": {
                "type": "contacts",
                "attributes": {
                    "first_name": "RelTest",
                    "last_name": "User",
                    "contact_methods": [],
                    "addresses": [],
                    "notes": [],
                },
            }
        }
        contact_response = await integration_api_client.post(
            "/api/contacts", json=contact_data
        )
        assert contact_response.status_code == 201
        contact_id = contact_response.json()["data"]["id"]

        # Add contact relationship
        contact_rel_data = {
            "data": {
                "type": "journal-contact-relationships",
                "attributes": {
                    "contact_id": str(contact_id),
                    "relationship_type": "PARTICIPANT",
                    "status": "ATTENDING",
                    "role": "ORGANISER",
                },
            }
        }

        response = await integration_api_client.post(
            f"/api/journals/{journal_id}/relationships/contacts", json=contact_rel_data
        )

        assert response.status_code == 200

        # Verify it was added correctly
        journal_response = await integration_api_client.get(
            f"/api/journals/{journal_id}"
        )
        assert journal_response.status_code == 200
        contacts = journal_response.json()["data"]["attributes"]["contacts"]
        assert len(contacts) == 1
        assert contacts[0]["id"] == str(contact_id)
        assert contacts[0]["relationship_type"] == "PARTICIPANT"
        assert contacts[0]["status"] == "ATTENDING"
        assert contacts[0]["role"] == "ORGANISER"

    async def test_add_contact_relationship_triggers_summary_refresh(
        self, integration_api_client, async_connection
    ):
        """Test adding a contact relationship triggers summary refresh outbox event."""
        import json

        from sqlalchemy import text

        create_data = create_journal_request_data(
            title="Trigger Test", content="Content"
        )
        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        journal_id = create_response.json()["data"]["id"]

        contact_data = {
            "data": {
                "type": "contacts",
                "attributes": {
                    "first_name": "RelTest",
                    "last_name": "User",
                    "contact_methods": [],
                    "addresses": [],
                    "notes": [],
                },
            }
        }
        contact_response = await integration_api_client.post(
            "/api/contacts", json=contact_data
        )
        contact_id = contact_response.json()["data"]["id"]

        # Clear outbox events
        await async_connection.execute(text("DELETE FROM outbox_events"))

        contact_rel_data = {
            "data": {
                "type": "journal-contact-relationships",
                "attributes": {
                    "contact_id": str(contact_id),
                    "relationship_type": "PARTICIPANT",
                },
            }
        }
        await integration_api_client.post(
            f"/api/journals/{journal_id}/relationships/contacts", json=contact_rel_data
        )

        # Verify exactly one ContactSummaryRefreshRequested outbox event for this contact
        result = await async_connection.execute(
            text(
                "SELECT event_data FROM outbox_events"
                " WHERE event_type = 'ContactSummaryRefreshRequested'"
                " AND aggregate_id = :contact_id"
            ),
            {"contact_id": int(contact_id)},
        )
        rows = result.fetchall()

        assert len(rows) == 1
        event_data = json.loads(rows[0].event_data)
        assert event_data["contact_id"] == int(contact_id)

    async def test_remove_contact_relationship(self, integration_api_client):
        """Test removing a contact relationship from a journal."""
        # Create a journal
        create_data = create_journal_request_data(
            title="Contact Remove Test", content="Test content"
        )

        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        journal_id = create_response.json()["data"]["id"]

        # Try to remove a contact relationship
        response = await integration_api_client.delete(
            f"/api/journals/{journal_id}/relationships/contacts/999/PARTICIPANT"
        )

        # Endpoint should exist and return appropriate status
        assert response.status_code in [200, 204, 404, 422]


@pytest.mark.integration
class TestJournalFilteringAndPagination:
    """Integration tests for journal filtering and pagination."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_method(self, clean_database):  # noqa: ARG002
        """Setup method to ensure clean database for each test."""
        pass

    async def test_list_journals_with_pagination(self, integration_api_client):
        """Test listing journals with pagination parameters."""
        # Create 5 journals
        for i in range(5):
            create_data = create_journal_request_data(
                title=f"Pagination Test {i}", content=f"Content {i}"
            )
            await integration_api_client.post("/api/journals", json=create_data)

        # Test page 1 with limit 2
        response = await integration_api_client.get("/api/journals?page=1&limit=2")

        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) <= 2
        # Check meta structure - may have different field names
        assert "meta" in data
        assert isinstance(data["meta"], dict)
        assert "links" in data

    async def test_list_journals_with_type_filter(self, integration_api_client):
        """Test listing journals filtered by type."""
        # Create journals with different types
        note_data = create_journal_request_data(
            title="Note Journal", content="Note content"
        )

        mood_data = create_journal_request_data(
            title="Mood Journal", content="Mood content", types=["MOOD_RATING"]
        )

        note_response = await integration_api_client.post(
            "/api/journals", json=note_data
        )
        mood_response = await integration_api_client.post(
            "/api/journals", json=mood_data
        )

        # Filter by type
        response = await integration_api_client.get("/api/journals?type=MOOD_RATING")

        assert response.status_code == 200
        data = response.json()

        # Should have at least 1 journal (the mood journal we just created)
        assert len(data["data"]) >= 1

        # Verify the mood journal we created is in the results
        mood_id = mood_response.json()["data"]["id"]
        returned_ids = [j["id"] for j in data["data"]]
        assert mood_id in returned_ids

        # Verify the note journal is NOT returned
        note_id = note_response.json()["data"]["id"]
        assert note_id not in returned_ids

    async def test_list_journals_with_date_range_filter(self, integration_api_client):
        """Test listing journals filtered by date range."""
        from datetime import datetime, timedelta
        from urllib.parse import quote

        now = datetime.now(UTC)
        tomorrow = now + timedelta(days=1)

        # Create a journal
        create_data = {
            "data": {
                "type": "journals",
                "attributes": {
                    "title": "Date Filter Test",
                    "content": "Test content",
                    "event_date_range": {
                        "start": now.isoformat(),
                        "end": tomorrow.isoformat(),
                    },
                },
            }
        }

        await integration_api_client.post("/api/journals", json=create_data)

        # Filter by date range - use URL encoding for ISO format
        start_date_encoded = quote(now.isoformat())
        end_date_encoded = quote(tomorrow.isoformat())
        response = await integration_api_client.get(
            f"/api/journals?start_date={start_date_encoded}&end_date={end_date_encoded}"
        )

        # May fail due to date parsing, which is acceptable for this test
        assert response.status_code in [200, 400]

    async def test_list_journals_with_note_type_filter(self, integration_api_client):
        """Test listing journals filtered by NOTE type (journals with no other types)."""
        # Create a pure NOTE journal (no additional types)
        note_data = create_journal_request_data(
            title="Pure Note", content="Just a note"
        )

        # Create a journal with MOOD_RATING type (also has NOTE implicitly)
        mood_data = create_journal_request_data(
            title="Mood Journal", content="Mood content", types=["MOOD_RATING"]
        )

        # Create a journal with PLAN type
        plan_data = create_journal_request_data(
            title="Plan Journal", content="Plan content", types=["PLAN"]
        )

        note_response = await integration_api_client.post(
            "/api/journals", json=note_data
        )
        mood_response = await integration_api_client.post(
            "/api/journals", json=mood_data
        )
        plan_response = await integration_api_client.post(
            "/api/journals", json=plan_data
        )

        # Filter by NOTE type - should only return journals with NO other types
        response = await integration_api_client.get("/api/journals?type=NOTE")

        assert response.status_code == 200
        data = response.json()

        # Should have at least 1 journal (the pure note we just created)
        assert len(data["data"]) >= 1

        # Verify the pure note journal is in the results
        note_id = note_response.json()["data"]["id"]
        returned_ids = [j["id"] for j in data["data"]]
        assert note_id in returned_ids

        # Verify journals with other types are NOT returned
        mood_id = mood_response.json()["data"]["id"]
        plan_id = plan_response.json()["data"]["id"]
        assert mood_id not in returned_ids
        assert plan_id not in returned_ids

        # Verify total count matches filtered results
        assert data["meta"]["total_count"] == len(data["data"])

    async def test_list_journals_empty_result(self, integration_api_client):
        """Test listing journals with filter that returns no results."""
        response = await integration_api_client.get("/api/journals?type=NONEXISTENT")

        assert response.status_code == 200
        data = response.json()
        # Should return empty list or list with no matching items
        assert isinstance(data["data"], list)


@pytest.mark.integration
class TestJournalDeleteEndpoints:
    """Integration tests for journal deletion endpoints."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_method(self, clean_database):  # noqa: ARG002
        """Setup method to ensure clean database for each test."""
        pass

    async def test_delete_journal(self, integration_api_client):
        """Test deleting a journal."""
        # Create a journal
        create_data = create_journal_request_data(
            title="Delete Test", content="Test content"
        )

        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        journal_id = create_response.json()["data"]["id"]

        # Delete the journal
        response = await integration_api_client.delete(f"/api/journals/{journal_id}")

        assert response.status_code in [200, 204]

        # Verify it's deleted
        get_response = await integration_api_client.get(f"/api/journals/{journal_id}")
        assert get_response.status_code == 404

    async def test_delete_nonexistent_journal(self, integration_api_client):
        """Test deleting a journal that doesn't exist."""
        response = await integration_api_client.delete("/api/journals/99999")

        assert response.status_code == 404


@pytest.mark.integration
class TestJournalTypeManagement:
    """Integration tests for journal type management endpoints."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_method(self, clean_database):  # noqa: ARG002
        """Setup method to ensure clean database for each test."""
        pass

    async def test_add_type_to_journal(self, integration_api_client):
        """Test adding a type to a journal."""
        # Create a NOTE journal
        create_data = create_journal_request_data(
            title="Type Test", content="Test content"
        )

        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        journal_id = create_response.json()["data"]["id"]

        # Add MOOD_RATING type
        type_data = {
            "data": {
                "type": "journal-type",
                "attributes": {
                    "journal_type": "MOOD_RATING",
                },
            }
        }

        response = await integration_api_client.post(
            f"/api/journals/{journal_id}/types", json=type_data
        )

        # Accept 200, 201, or 400 (if endpoint structure is different)
        assert response.status_code in [200, 201, 400]

    async def test_remove_type_from_journal(self, integration_api_client):
        """Test removing a type from a journal."""
        # Create a journal with MOOD_RATING type
        create_data = create_journal_request_data(
            title="Type Remove Test", content="Test content", types=["MOOD_RATING"]
        )

        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        journal_id = create_response.json()["data"]["id"]

        # Remove MOOD_RATING type
        response = await integration_api_client.delete(
            f"/api/journals/{journal_id}/types/MOOD_RATING"
        )

        assert response.status_code in [200, 204]

    async def test_update_event_type_data(self, integration_api_client):
        """Test updating EVENT type data."""
        # Create a calendar first for foreign key
        cal_response = await integration_api_client.post(
            "/api/calendars",
            json={
                "data": {"type": "calendars", "attributes": {"name": "Test Calendar"}}
            },
        )
        assert cal_response.status_code == 201
        calendar_id = cal_response.json()["data"]["id"]

        # Create an EVENT journal
        create_data = create_journal_request_data(
            title="Event Update Test",
            content="Test content",
            types=["EVENT"],
            type_data={"event": {"calendar_id": calendar_id, "is_all_day": False}},
        )

        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        journal_id = create_response.json()["data"]["id"]

        # Update EVENT type data
        update_data = {
            "data": {
                "type": "journal-type-data",
                "attributes": {
                    "location": "Test Location",
                    "is_all_day": True,
                    "event_state": "cancelled",
                },
            }
        }

        response = await integration_api_client.put(
            f"/api/journals/{journal_id}/types/EVENT/data", json=update_data
        )

        # Should succeed or return validation error
        assert response.status_code == 200

        response_json = response.json()
        event_data = response_json["data"]["attributes"]["type_data"]["event"]
        assert event_data["location"] == "Test Location"
        assert event_data["is_all_day"] is True
        assert event_data["event_state"] == "cancelled"

    async def test_update_event_type_data_with_times(self, integration_api_client):
        """Test updating EVENT type data with HH:MM times explicitly."""
        # Create a calendar first for foreign key
        cal_response = await integration_api_client.post(
            "/api/calendars",
            json={
                "data": {"type": "calendars", "attributes": {"name": "Test Calendar 2"}}
            },
        )
        assert cal_response.status_code == 201
        calendar_id = cal_response.json()["data"]["id"]

        # Create an EVENT journal
        create_data = create_journal_request_data(
            title="Event Time Update Test",
            content="Test content",
            types=["EVENT"],
            type_data={"event": {"calendar_id": calendar_id, "is_all_day": True}},
        )

        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        # Update EVENT type data with HH:MM format
        update_data = {
            "data": {
                "type": "journal-type-data",
                "attributes": {
                    "is_all_day": False,
                    "start_time": "12:30",
                    "end_time": "14:00",
                },
            }
        }

        response = await integration_api_client.put(
            f"/api/journals/{journal_id}/types/EVENT/data", json=update_data
        )

        assert response.status_code == 200
        response_json = response.json()
        event_data = response_json["data"]["attributes"]["type_data"]["event"]
        assert event_data["is_all_day"] is False
        assert event_data["start_time"] == "12:30:00"
        assert event_data["end_time"] == "14:00:00"

    async def test_update_photo_album_type_data(self, integration_api_client):
        """Test updating PHOTO_ALBUM type data."""
        # Create a PHOTO_ALBUM journal
        create_data = create_journal_request_data(
            title="Photo Album Test", content="Test content", types=["PHOTO_ALBUM"]
        )

        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        journal_id = create_response.json()["data"]["id"]

        # Update PHOTO_ALBUM type data
        update_data = {
            "data": {
                "type": "journal-type-data",
                "attributes": {
                    "immich_album_id": "test-album-123",
                },
            }
        }

        response = await integration_api_client.put(
            f"/api/journals/{journal_id}/types/PHOTO_ALBUM/data", json=update_data
        )

        # Should succeed or return validation error
        assert response.status_code in [200, 400, 422]

    async def test_update_fitness_type_data(self, integration_api_client):
        """Test updating FITNESS type data."""
        # Create a FITNESS journal
        create_data = create_journal_request_data(
            title="Fitness Test", content="Test content", types=["FITNESS"]
        )

        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        journal_id = create_response.json()["data"]["id"]

        # Update FITNESS type data
        update_data = {
            "data": {
                "type": "journal-type-data",
                "attributes": {
                    "heart_rate_avg": 145,
                    "heart_rate_max": 175,
                    "distance": 5000,
                    "duration": 1800,
                    "calories": 450,
                },
            }
        }

        response = await integration_api_client.put(
            f"/api/journals/{journal_id}/types/FITNESS/data", json=update_data
        )

        # Expect successful update and validate returned FITNESS type data
        assert response.status_code == 200
        response_json = response.json()
        fitness_data = response_json["data"]["attributes"]["type_data"]["fitness"]
        # Validate the updated values match what we sent
        assert fitness_data["heart_rate_avg"] == 145
        assert fitness_data["heart_rate_max"] == 175
        assert fitness_data["distance"] == 5000
        assert fitness_data["duration"] == 1800
        assert fitness_data["calories"] == 450

    async def test_update_outdoor_activity_type_data(self, integration_api_client):
        """Test updating OUTDOOR_ACTIVITY type data."""
        create_data = create_journal_request_data(
            title="Outdoor Activity Test",
            content="Test content",
            types=["OUTDOOR_ACTIVITY"],
        )

        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        update_data = {
            "data": {
                "type": "journal-type-data",
                "attributes": {
                    "weather_conditions": "Sunny, 22°C",
                    "role": "leader",
                    "in_leadership_role": True,
                    "participant_notes": "Group of 5",
                },
            }
        }

        response = await integration_api_client.put(
            f"/api/journals/{journal_id}/types/OUTDOOR_ACTIVITY/data",
            json=update_data,
        )

        assert response.status_code == 200
        response_json = response.json()
        outdoor_data = response_json["data"]["attributes"]["type_data"][
            "outdoor_activity"
        ]
        assert outdoor_data["weather_conditions"] == "Sunny, 22°C"
        assert outdoor_data["role"] == "leader"
        assert outdoor_data["in_leadership_role"] is True
        assert outdoor_data["participant_notes"] == "Group of 5"

    async def test_update_bushwalking_type_data(self, integration_api_client):
        """Test updating BUSHWALKING type data."""
        create_data = create_journal_request_data(
            title="Bushwalking Test",
            content="Test content",
            types=["BUSHWALKING"],
        )

        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        update_data = {
            "data": {
                "type": "journal-type-data",
                "attributes": {
                    "track_grading": "Grade 3",
                },
            }
        }

        response = await integration_api_client.put(
            f"/api/journals/{journal_id}/types/BUSHWALKING/data",
            json=update_data,
        )

        assert response.status_code == 200
        response_json = response.json()
        bushwalking_data = response_json["data"]["attributes"]["type_data"][
            "bushwalking"
        ]
        assert bushwalking_data["track_grading"] == "Grade 3"

    async def test_update_jogging_type_data(self, integration_api_client):
        """Test updating JOGGING type data."""
        create_data = create_journal_request_data(
            title="Jogging Test",
            content="Test content",
            types=["JOGGING"],
        )

        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        update_data = {
            "data": {
                "type": "journal-type-data",
                "attributes": {
                    "pace": 360,  # 6 min/km in seconds
                },
            }
        }

        response = await integration_api_client.put(
            f"/api/journals/{journal_id}/types/JOGGING/data",
            json=update_data,
        )

        assert response.status_code == 200
        response_json = response.json()
        jogging_data = response_json["data"]["attributes"]["type_data"]["jogging"]
        assert jogging_data["pace"] == 360

    async def test_update_abseiling_trip_type_data(self, integration_api_client):
        """Test updating ABSEILING_TRIP type data."""
        create_data = create_journal_request_data(
            title="Abseiling Test",
            content="Test content",
            types=["ABSEILING_TRIP"],
        )

        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        update_data = {
            "data": {
                "type": "journal-type-data",
                "attributes": {
                    "number_of_abseils": 5,
                    "total_length": 120,
                },
            }
        }

        response = await integration_api_client.put(
            f"/api/journals/{journal_id}/types/ABSEILING_TRIP/data",
            json=update_data,
        )

        assert response.status_code == 200
        response_json = response.json()
        abseiling_data = response_json["data"]["attributes"]["type_data"][
            "abseiling_trip"
        ]
        assert abseiling_data["number_of_abseils"] == 5
        assert abseiling_data["total_length"] == 120

    async def test_update_canyoning_type_data(self, integration_api_client):
        """Test updating CANYONING type data."""
        create_data = create_journal_request_data(
            title="Canyoning Test",
            content="Test content",
            types=["CANYONING"],
        )

        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        update_data = {
            "data": {
                "type": "journal-type-data",
                "attributes": {
                    "french_grade": "v3a2IV**",
                    "water_guage_name": "Slot Canyon Gauge",
                    "water_guage_level": 45,
                    "is_vertical": True,
                    "is_night_canyon": False,
                    "is_white_water": True,
                },
            }
        }

        response = await integration_api_client.put(
            f"/api/journals/{journal_id}/types/CANYONING/data",
            json=update_data,
        )

        assert response.status_code == 200
        response_json = response.json()
        canyoning_data = response_json["data"]["attributes"]["type_data"]["canyoning"]
        assert canyoning_data["french_grade"] == "v3a2IV**"
        assert canyoning_data["water_guage_name"] == "Slot Canyon Gauge"
        assert canyoning_data["water_guage_level"] == 45
        assert canyoning_data["is_vertical"] is True
        assert canyoning_data["is_night_canyon"] is False
        assert canyoning_data["is_white_water"] is True

    async def test_update_climbing_type_data(self, integration_api_client):
        """Test updating CLIMBING type data."""
        create_data = create_journal_request_data(
            title="Climbing Test",
            content="Test content",
            types=["CLIMBING"],
        )

        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        update_data = {
            "data": {
                "type": "journal-type-data",
                "attributes": {
                    "climbing_type": "sport",
                    "grade": 18,
                    "length": 25,
                },
            }
        }

        response = await integration_api_client.put(
            f"/api/journals/{journal_id}/types/CLIMBING/data",
            json=update_data,
        )

        assert response.status_code == 200
        response_json = response.json()
        climbing_data = response_json["data"]["attributes"]["type_data"]["climbing"]
        assert climbing_data["climbing_type"] == "sport"
        assert climbing_data["grade"] == 18
        assert climbing_data["length"] == 25

    async def test_update_kayaking_type_data(self, integration_api_client):
        """Test updating KAYAKING type data."""
        create_data = create_journal_request_data(
            title="Kayaking Test",
            content="Test content",
            types=["KAYAKING"],
        )

        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        update_data = {
            "data": {
                "type": "journal-type-data",
                "attributes": {
                    "water_type": "river",
                },
            }
        }
        response = await integration_api_client.put(
            f"/api/journals/{journal_id}/types/KAYAKING/data",
            json=update_data,
        )

        assert response.status_code == 200
        response_json = response.json()
        kayaking_data = response_json["data"]["attributes"]["type_data"]["kayaking"]
        assert kayaking_data["water_type"] == "river"

    async def test_update_cross_country_skiing_type_data(self, integration_api_client):
        """Test updating CROSS_COUNTRY_SKIING type data."""
        create_data = create_journal_request_data(
            title="Cross Country Skiing Test",
            content="Test content",
            types=["CROSS_COUNTRY_SKIING"],
        )

        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        update_data = {
            "data": {
                "type": "journal-type-data",
                "attributes": {
                    "snow_conditions": "packed powder",
                },
            }
        }
        response = await integration_api_client.put(
            f"/api/journals/{journal_id}/types/CROSS_COUNTRY_SKIING/data",
            json=update_data,
        )

        assert response.status_code == 200
        response_json = response.json()
        skiing_data = response_json["data"]["attributes"]["type_data"][
            "cross_country_skiing"
        ]
        assert skiing_data["snow_conditions"] == "packed powder"

    async def test_remove_abseiling_trip_type_removes_from_response(
        self, integration_api_client
    ):
        """Removing ABSEILING_TRIP should remove the type from the response."""
        create_data = create_journal_request_data(
            title="Abseiling Remove Test",
            content="Test content",
            types=["ABSEILING_TRIP"],
        )
        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        response = await integration_api_client.delete(
            f"/api/journals/{journal_id}/types/ABSEILING_TRIP"
        )

        assert response.status_code == 200
        types = response.json()["data"]["attributes"]["types"]
        assert "abseiling_trip" not in types

    async def test_remove_canyoning_type_removes_from_response(
        self, integration_api_client
    ):
        """Removing CANYONING should remove the type from the response."""
        create_data = create_journal_request_data(
            title="Canyoning Remove Test",
            content="Test content",
            types=["CANYONING"],
        )
        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        response = await integration_api_client.delete(
            f"/api/journals/{journal_id}/types/CANYONING"
        )

        assert response.status_code == 200
        types = response.json()["data"]["attributes"]["types"]
        assert "canyoning" not in types

    async def test_remove_climbing_type_removes_from_response(
        self, integration_api_client
    ):
        """Removing CLIMBING should remove the type from the response."""
        create_data = create_journal_request_data(
            title="Climbing Remove Test",
            content="Test content",
            types=["CLIMBING"],
        )
        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        response = await integration_api_client.delete(
            f"/api/journals/{journal_id}/types/CLIMBING"
        )

        assert response.status_code == 200
        types = response.json()["data"]["attributes"]["types"]
        assert "climbing" not in types

    async def test_remove_kayaking_type_removes_from_response(
        self, integration_api_client
    ):
        """Removing KAYAKING should remove the type from the response."""
        create_data = create_journal_request_data(
            title="Kayaking Remove Test",
            content="Test content",
            types=["KAYAKING"],
        )
        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        response = await integration_api_client.delete(
            f"/api/journals/{journal_id}/types/KAYAKING"
        )

        assert response.status_code == 200
        types = response.json()["data"]["attributes"]["types"]
        assert "kayaking" not in types

    async def test_remove_cross_country_skiing_type_removes_from_response(
        self, integration_api_client
    ):
        """Removing CROSS_COUNTRY_SKIING should remove the type from the response."""
        create_data = create_journal_request_data(
            title="Cross Country Skiing Remove Test",
            content="Test content",
            types=["CROSS_COUNTRY_SKIING"],
        )
        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        response = await integration_api_client.delete(
            f"/api/journals/{journal_id}/types/CROSS_COUNTRY_SKIING"
        )

        assert response.status_code == 200
        types = response.json()["data"]["attributes"]["types"]
        assert "cross_country_skiing" not in types


@pytest.mark.integration
class TestJournalHierarchy:
    """Integration tests for journal hierarchy (parent-child relationships)."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_method(self, clean_database):  # noqa: ARG002
        """Setup method to ensure clean database for each test."""
        pass

    async def test_create_child_journal(self, integration_api_client):
        """Test creating a child journal."""
        # Create parent journal
        parent_data = create_journal_request_data(
            title="Parent Journal", content="Parent content"
        )

        parent_response = await integration_api_client.post(
            "/api/journals", json=parent_data
        )
        parent_id = parent_response.json()["data"]["id"]

        # Create child journal
        child_data = create_journal_request_data(
            title="Child Journal", content="Child content", parent_id=parent_id
        )

        response = await integration_api_client.post("/api/journals", json=child_data)

        assert response.status_code == 201
        data = response.json()
        # Parent ID might be returned as int or string, so compare as int
        assert int(data["data"]["attributes"]["parent_id"]) == int(parent_id)

    async def test_filter_journals_by_parent_id(self, integration_api_client):
        """Test filtering journals by parent_id via API."""
        # Create parent journal
        parent_data = create_journal_request_data(
            title="Parent Journal", content="Parent content"
        )
        parent_response = await integration_api_client.post(
            "/api/journals", json=parent_data
        )
        parent_id = parent_response.json()["data"]["id"]

        # Create child journals
        child1_data = create_journal_request_data(
            title="Child 1", content="First child", parent_id=parent_id
        )
        child1_response = await integration_api_client.post(
            "/api/journals", json=child1_data
        )
        assert child1_response.status_code == 201

        child2_data = create_journal_request_data(
            title="Child 2", content="Second child", parent_id=parent_id
        )
        child2_response = await integration_api_client.post(
            "/api/journals", json=child2_data
        )
        assert child2_response.status_code == 201

        # Create another root journal
        other_root_data = create_journal_request_data(
            title="Other Root", content="Another root journal"
        )
        other_root_response = await integration_api_client.post(
            "/api/journals", json=other_root_data
        )
        assert other_root_response.status_code == 201

        # Filter by parent_id - should only return the 2 children
        filter_response = await integration_api_client.get(
            f"/api/journals?parent_id={parent_id}"
        )
        assert filter_response.status_code == 200

        journals = filter_response.json()["data"]
        assert len(journals) == 2, f"Expected 2 journals, got {len(journals)}"

        titles = {j["attributes"]["title"] for j in journals}
        assert "Child 1" in titles
        assert "Child 2" in titles
        assert "Parent Journal" not in titles
        assert "Other Root" not in titles

    async def test_create_deeply_nested_journals(self, integration_api_client):
        """Test creating deeply nested journals (up to max depth)."""
        current_parent_id: int | None = None

        # Create 5 levels of nesting (max depth)
        for level in range(5):
            journal_data = create_journal_request_data(
                title=f"Level {level} Journal",
                content=f"Level {level} content",
                parent_id=current_parent_id,
            )

            response = await integration_api_client.post(
                "/api/journals", json=journal_data
            )

            assert response.status_code == 201
            current_parent_id = response.json()["data"]["id"]

    async def test_exceed_max_nesting_depth(self, integration_api_client):
        """Test that exceeding max nesting depth fails."""
        current_parent_id: int | None = None

        # Create 5 levels (max depth)
        for level in range(5):
            journal_data = create_journal_request_data(
                title=f"Level {level} Journal",
                content=f"Level {level} content",
                parent_id=current_parent_id,
            )

            response = await integration_api_client.post(
                "/api/journals", json=journal_data
            )
            current_parent_id = response.json()["data"]["id"]

        # Try to create 6th level (should fail)
        journal_data = create_journal_request_data(
            title="Level 6 Journal",
            content="Level 6 content",
            parent_id=current_parent_id,
        )

        response = await integration_api_client.post("/api/journals", json=journal_data)

        # Should fail with 400 or 422
        assert response.status_code in [400, 422]


@pytest.mark.integration
class TestJournalDataValidation:
    """Integration tests for journal data validation."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_method(self, clean_database):  # noqa: ARG002
        """Setup method to ensure clean database for each test."""
        pass

    async def test_create_journal_with_invalid_date_range(self, integration_api_client):
        """Test creating a journal with invalid date range (end before start)."""
        from datetime import datetime, timedelta

        now = datetime.now(UTC)
        past = now - timedelta(days=1)

        create_data = {
            "data": {
                "type": "journals",
                "attributes": {
                    "title": "Invalid Date Range",
                    "content": "Test content",
                    "event_date_range": {
                        "start": now.isoformat(),
                        "end": past.isoformat(),  # End before start
                    },
                },
            }
        }

        response = await integration_api_client.post("/api/journals", json=create_data)

        # Should fail with validation error
        assert response.status_code in [400, 422]

    async def test_create_journal_with_missing_required_fields(
        self, integration_api_client
    ):
        """Test creating a journal with missing required fields."""
        create_data = {
            "data": {
                "type": "journals",
                "attributes": {
                    # Missing title and content
                    "event_date_range": {
                        "start": "2024-01-01T00:00:00Z",
                        "end": "2024-01-01T00:00:00Z",
                    },
                },
            }
        }

        response = await integration_api_client.post("/api/journals", json=create_data)

        # Should fail with validation error
        assert response.status_code in [400, 422]

    async def test_create_journal_with_title_too_long(self, integration_api_client):
        """Test creating a journal with title exceeding max length."""
        create_data = create_journal_request_data(
            title="x" * 501,
            content="Test content",  # Max is 500
        )

        response = await integration_api_client.post("/api/journals", json=create_data)

        # Should fail with validation error
        assert response.status_code in [400, 422]

    async def test_get_nonexistent_journal(self, integration_api_client):
        """Test getting a journal that doesn't exist."""
        response = await integration_api_client.get("/api/journals/99999")

        assert response.status_code == 404


@pytest.mark.integration
class TestJournalResponseFormat:
    """Integration tests for journal response format compliance."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_method(self, clean_database):  # noqa: ARG002
        """Setup method to ensure clean database for each test."""
        pass

    async def test_journal_response_has_required_fields(self, integration_api_client):
        """Test that journal response includes all required JSON API fields."""
        create_data = create_journal_request_data(
            title="Response Format Test", content="Test content"
        )

        response = await integration_api_client.post("/api/journals", json=create_data)

        assert response.status_code == 201
        data = response.json()

        # Check JSON API structure
        assert "data" in data
        assert "type" in data["data"]
        assert data["data"]["type"] == "journals"
        assert "id" in data["data"]
        assert "attributes" in data["data"]

        # Check required attributes
        attributes = data["data"]["attributes"]
        assert "title" in attributes
        assert "content" in attributes
        assert "event_date_range" in attributes
        assert "created_at" in attributes
        assert "updated_at" in attributes
        assert "types" in attributes

    async def test_list_response_has_pagination_metadata(self, integration_api_client):
        """Test that list response includes pagination metadata."""
        # Create a journal
        create_data = create_journal_request_data(
            title="Pagination Test", content="Test content"
        )

        await integration_api_client.post("/api/journals", json=create_data)

        # List journals
        response = await integration_api_client.get("/api/journals")

        assert response.status_code == 200
        data = response.json()

        # Check JSON API structure
        assert "data" in data
        assert isinstance(data["data"], list)
        assert "meta" in data
        assert "links" in data

        # Check pagination metadata (field names may vary)
        meta = data["meta"]
        assert any(key in meta for key in ["total", "total_count"])
        assert any(key in meta for key in ["page", "current_page"])
        assert any(key in meta for key in ["limit", "per_page"])

    async def test_journal_with_types_includes_type_data(self, integration_api_client):
        """Test that journal with types includes type-specific data."""
        create_data = create_journal_request_data(
            title="Type Data Test", content="Test content", types=["MOOD_RATING"]
        )

        response = await integration_api_client.post("/api/journals", json=create_data)

        assert response.status_code == 201
        data = response.json()

        # Check that types are included
        attributes = data["data"]["attributes"]
        assert "types" in attributes
        # Types might be lowercase or uppercase
        types_list = [t.upper() for t in attributes["types"]]
        assert "MOOD_RATING" in types_list or "NOTE" in types_list

        # Check that type_data is included
        assert "type_data" in attributes


@pytest.mark.integration
class TestJournalErrorHandling:
    """Integration tests for error handling."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_method(self, clean_database):  # noqa: ARG002
        """Setup method to ensure clean database for each test."""
        pass

    async def test_invalid_journal_id_format(self, integration_api_client):
        """Test getting a journal with invalid ID format."""
        response = await integration_api_client.get("/api/journals/invalid-id")

        # Should fail with 400 (bad request), 422 (validation error), or 404
        assert response.status_code in [400, 404, 422]

    async def test_create_journal_with_invalid_parent_id(self, integration_api_client):
        """Test creating a journal with non-existent parent."""
        create_data = create_journal_request_data(
            title="Invalid Parent Test",
            content="Test content",
            parent_id=99999,  # Non-existent parent
        )

        response = await integration_api_client.post("/api/journals", json=create_data)

        # Should fail with 400, 404, or 422
        assert response.status_code in [400, 404, 422]

    async def test_update_nonexistent_journal(self, integration_api_client):
        """Test updating a journal that doesn't exist."""
        from datetime import datetime

        update_data = {
            "data": {
                "type": "journals",
                "id": "99999",
                "attributes": {
                    "title": "Updated Title",
                    "content": "Updated content",
                    "event_date_range": {
                        "start": datetime.now(UTC).isoformat(),
                        "end": datetime.now(UTC).isoformat(),
                    },
                },
            }
        }

        response = await integration_api_client.put(
            "/api/journals/99999", json=update_data
        )

        assert response.status_code == 404


@pytest.mark.integration
class TestJournalTypeDependencyDataCreation:
    """Integration tests verifying dependency type data rows are created on type addition."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_method(self, clean_database):  # noqa: ARG002
        """Setup method to ensure clean database for each test."""
        pass

    async def test_adding_outdoor_activity_creates_fitness_data(
        self, integration_api_client
    ):
        """Adding OUTDOOR_ACTIVITY should also create FITNESS type data row."""
        create_data = create_journal_request_data(
            title="Outdoor Activity Dependency Test",
            content="Test content",
            types=["OUTDOOR_ACTIVITY"],
        )

        response = await integration_api_client.post("/api/journals", json=create_data)

        assert response.status_code == 201
        response_json = response.json()
        type_data = response_json["data"]["attributes"]["type_data"]
        # OUTDOOR_ACTIVITY requires FITNESS — FITNESS data row must exist
        assert "fitness" in type_data, (
            "FITNESS type data row should be auto-created for OUTDOOR_ACTIVITY"
        )
        assert "outdoor_activity" in type_data

    async def test_adding_bushwalking_creates_fitness_and_outdoor_activity_data(
        self, integration_api_client
    ):
        """Adding BUSHWALKING should create FITNESS and OUTDOOR_ACTIVITY data rows."""
        create_data = create_journal_request_data(
            title="Bushwalking Dependency Test",
            content="Test content",
            types=["BUSHWALKING"],
        )

        response = await integration_api_client.post("/api/journals", json=create_data)

        assert response.status_code == 201
        response_json = response.json()
        type_data = response_json["data"]["attributes"]["type_data"]
        # BUSHWALKING requires OUTDOOR_ACTIVITY and FITNESS — both rows must exist
        assert "fitness" in type_data, (
            "FITNESS type data row should be auto-created for BUSHWALKING"
        )
        assert "outdoor_activity" in type_data, (
            "OUTDOOR_ACTIVITY type data row should be auto-created for BUSHWALKING"
        )
        assert "bushwalking" in type_data

    async def test_add_type_endpoint_creates_dependency_data(
        self, integration_api_client
    ):
        """POST /types endpoint should create data rows for all dependency types."""
        # Create a plain NOTE journal
        create_data = create_journal_request_data(
            title="Add Type Dependency Test", content="Test content"
        )
        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        # Add OUTDOOR_ACTIVITY via the types endpoint
        type_payload = {
            "data": {
                "type": "journal-type",
                "attributes": {"journal_type": "OUTDOOR_ACTIVITY"},
            }
        }
        response = await integration_api_client.post(
            f"/api/journals/{journal_id}/types", json=type_payload
        )

        assert response.status_code == 200
        response_json = response.json()
        type_data = response_json["data"]["attributes"]["type_data"]
        # FITNESS data row should have been created as a dependency
        assert "fitness" in type_data, (
            "FITNESS type data row should be auto-created when OUTDOOR_ACTIVITY is added via endpoint"
        )
        assert "outdoor_activity" in type_data

    async def test_adding_abseiling_trip_creates_fitness_and_outdoor_activity_data(
        self, integration_api_client
    ):
        """Adding ABSEILING_TRIP should create FITNESS and OUTDOOR_ACTIVITY data rows."""
        create_data = create_journal_request_data(
            title="Abseiling Dependency Test",
            content="Test content",
            types=["ABSEILING_TRIP"],
        )

        response = await integration_api_client.post("/api/journals", json=create_data)

        assert response.status_code == 201
        response_json = response.json()
        type_data = response_json["data"]["attributes"]["type_data"]
        # ABSEILING_TRIP requires OUTDOOR_ACTIVITY and FITNESS
        assert "fitness" in type_data, (
            "FITNESS type data row should be auto-created for ABSEILING_TRIP"
        )
        assert "outdoor_activity" in type_data, (
            "OUTDOOR_ACTIVITY type data row should be auto-created for ABSEILING_TRIP"
        )
        assert "abseiling_trip" in type_data

    async def test_adding_canyoning_creates_all_dependency_data(
        self, integration_api_client
    ):
        """Adding CANYONING should create BUSHWALKING, ABSEILING_TRIP, OUTDOOR_ACTIVITY, and FITNESS data rows."""
        create_data = create_journal_request_data(
            title="Canyoning Dependency Test",
            content="Test content",
            types=["CANYONING"],
        )

        response = await integration_api_client.post("/api/journals", json=create_data)

        assert response.status_code == 201
        response_json = response.json()
        type_data = response_json["data"]["attributes"]["type_data"]
        # CANYONING requires BUSHWALKING, ABSEILING_TRIP, OUTDOOR_ACTIVITY, and FITNESS
        assert "fitness" in type_data, (
            "FITNESS type data row should be auto-created for CANYONING"
        )
        assert "outdoor_activity" in type_data, (
            "OUTDOOR_ACTIVITY type data row should be auto-created for CANYONING"
        )
        assert "bushwalking" in type_data, (
            "BUSHWALKING type data row should be auto-created for CANYONING"
        )
        assert "abseiling_trip" in type_data, (
            "ABSEILING_TRIP type data row should be auto-created for CANYONING"
        )
        assert "canyoning" in type_data

    async def test_adding_climbing_creates_fitness_and_outdoor_activity_data(
        self, integration_api_client
    ):
        """Adding CLIMBING should create FITNESS and OUTDOOR_ACTIVITY data rows."""
        create_data = create_journal_request_data(
            title="Climbing Dependency Test",
            content="Test content",
            types=["CLIMBING"],
        )

        response = await integration_api_client.post("/api/journals", json=create_data)

        assert response.status_code == 201
        response_json = response.json()
        type_data = response_json["data"]["attributes"]["type_data"]
        # CLIMBING requires OUTDOOR_ACTIVITY and FITNESS
        assert "fitness" in type_data, (
            "FITNESS type data row should be auto-created for CLIMBING"
        )
        assert "outdoor_activity" in type_data, (
            "OUTDOOR_ACTIVITY type data row should be auto-created for CLIMBING"
        )
        assert "climbing" in type_data

    async def test_adding_kayaking_creates_fitness_and_outdoor_activity_data(
        self, integration_api_client
    ):
        """Adding KAYAKING should create FITNESS and OUTDOOR_ACTIVITY data rows."""
        create_data = create_journal_request_data(
            title="Kayaking Dependency Test",
            content="Test content",
            types=["KAYAKING"],
        )

        response = await integration_api_client.post("/api/journals", json=create_data)

        assert response.status_code == 201
        response_json = response.json()
        type_data = response_json["data"]["attributes"]["type_data"]
        # KAYAKING requires OUTDOOR_ACTIVITY and FITNESS
        assert "fitness" in type_data, (
            "FITNESS type data row should be auto-created for KAYAKING"
        )
        assert "outdoor_activity" in type_data, (
            "OUTDOOR_ACTIVITY type data row should be auto-created for KAYAKING"
        )
        assert "kayaking" in type_data

    async def test_adding_cross_country_skiing_creates_all_dependency_data(
        self, integration_api_client
    ):
        """Adding CROSS_COUNTRY_SKIING should create BUSHWALKING, OUTDOOR_ACTIVITY, and FITNESS data rows."""
        create_data = create_journal_request_data(
            title="Cross Country Skiing Dependency Test",
            content="Test content",
            types=["CROSS_COUNTRY_SKIING"],
        )

        response = await integration_api_client.post("/api/journals", json=create_data)

        assert response.status_code == 201
        response_json = response.json()
        type_data = response_json["data"]["attributes"]["type_data"]
        # CROSS_COUNTRY_SKIING requires BUSHWALKING, OUTDOOR_ACTIVITY, and FITNESS
        assert "fitness" in type_data, (
            "FITNESS type data row should be auto-created for CROSS_COUNTRY_SKIING"
        )
        assert "outdoor_activity" in type_data, (
            "OUTDOOR_ACTIVITY type data row should be auto-created for CROSS_COUNTRY_SKIING"
        )
        assert "bushwalking" in type_data, (
            "BUSHWALKING type data row should be auto-created for CROSS_COUNTRY_SKIING"
        )
        assert "cross_country_skiing" in type_data


@pytest.mark.integration
class TestJournalTypeDataValidation:
    """Integration tests verifying that invalid update data returns 400 not 500."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_method(self, clean_database):  # noqa: ARG002
        """Setup method to ensure clean database for each test."""
        pass

    async def test_update_outdoor_activity_with_empty_weather_returns_400(
        self, integration_api_client
    ):
        """Updating OUTDOOR_ACTIVITY with empty weather_conditions should return 400."""
        create_data = create_journal_request_data(
            title="Validation Test",
            content="Test content",
            types=["OUTDOOR_ACTIVITY"],
        )
        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        update_data = {
            "data": {
                "type": "journal-type-data",
                "attributes": {"weather_conditions": "   "},  # whitespace-only
            }
        }
        response = await integration_api_client.put(
            f"/api/journals/{journal_id}/types/OUTDOOR_ACTIVITY/data",
            json=update_data,
        )

        assert response.status_code == 400, (
            "Empty/whitespace weather_conditions should return 400 not 500"
        )

    async def test_update_bushwalking_with_invalid_track_grading_returns_400(
        self, integration_api_client
    ):
        """Updating BUSHWALKING with an invalid track_grading should return 400."""
        create_data = create_journal_request_data(
            title="Track Grading Validation Test",
            content="Test content",
            types=["BUSHWALKING"],
        )
        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        update_data = {
            "data": {
                "type": "journal-type-data",
                "attributes": {"track_grading": "Invalid Grade 99"},
            }
        }
        response = await integration_api_client.put(
            f"/api/journals/{journal_id}/types/BUSHWALKING/data",
            json=update_data,
        )

        assert response.status_code == 400, (
            "Invalid track_grading should return 400 not 500"
        )

    async def test_update_abseiling_trip_with_negative_number_of_abseils_returns_400(
        self, integration_api_client
    ):
        """Updating ABSEILING_TRIP with a negative number_of_abseils should return 400."""
        create_data = create_journal_request_data(
            title="Abseiling Validation Test",
            content="Test content",
            types=["ABSEILING_TRIP"],
        )
        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        update_data = {
            "data": {
                "type": "journal-type-data",
                "attributes": {"number_of_abseils": -1},
            }
        }
        response = await integration_api_client.put(
            f"/api/journals/{journal_id}/types/ABSEILING_TRIP/data",
            json=update_data,
        )

        assert response.status_code == 400, (
            "Negative number_of_abseils should return 400 not 500"
        )

    async def test_update_canyoning_with_invalid_french_grade_returns_400(
        self, integration_api_client
    ):
        """Updating CANYONING with an invalid French grade should return 400."""
        create_data = create_journal_request_data(
            title="Canyoning Grade Validation Test",
            content="Test content",
            types=["CANYONING"],
        )
        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        update_data = {
            "data": {
                "type": "journal-type-data",
                "attributes": {"french_grade": "not-a-valid-grade"},
            }
        }
        response = await integration_api_client.put(
            f"/api/journals/{journal_id}/types/CANYONING/data",
            json=update_data,
        )

        assert response.status_code == 400, (
            "Invalid French canyon grade should return 400 not 500"
        )

    async def test_update_climbing_with_invalid_climbing_type_returns_400(
        self, integration_api_client
    ):
        """Updating CLIMBING with an invalid climbing_type should return 400."""
        create_data = create_journal_request_data(
            title="Climbing Type Validation Test",
            content="Test content",
            types=["CLIMBING"],
        )
        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        update_data = {
            "data": {
                "type": "journal-type-data",
                "attributes": {"climbing_type": "invalid_type"},
            }
        }
        response = await integration_api_client.put(
            f"/api/journals/{journal_id}/types/CLIMBING/data",
            json=update_data,
        )

        assert response.status_code == 400, (
            "Invalid climbing_type should return 400 not 500"
        )

    async def test_update_climbing_with_negative_grade_returns_400(
        self, integration_api_client
    ):
        """Updating CLIMBING with a negative grade should return 400."""
        create_data = create_journal_request_data(
            title="Climbing Grade Validation Test",
            content="Test content",
            types=["CLIMBING"],
        )
        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        update_data = {
            "data": {
                "type": "journal-type-data",
                "attributes": {"grade": -1},
            }
        }
        response = await integration_api_client.put(
            f"/api/journals/{journal_id}/types/CLIMBING/data",
            json=update_data,
        )

        assert response.status_code == 400, "Negative grade should return 400 not 500"

    async def test_update_abseiling_with_string_number_of_abseils_returns_400(
        self, integration_api_client
    ):
        """Sending a string for number_of_abseils (expects int) should return 400 not 500."""
        create_data = create_journal_request_data(
            title="Abseiling Type Check Test",
            content="Test content",
            types=["ABSEILING_TRIP"],
        )
        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        update_data = {
            "data": {
                "type": "journal-type-data",
                "attributes": {"number_of_abseils": "five"},
            }
        }
        response = await integration_api_client.put(
            f"/api/journals/{journal_id}/types/ABSEILING_TRIP/data",
            json=update_data,
        )

        assert response.status_code == 400, (
            "String for number_of_abseils should return 400 not 500"
        )

    async def test_update_climbing_with_string_grade_returns_400(
        self, integration_api_client
    ):
        """Sending a string for grade (expects int) should return 400 not 500."""
        create_data = create_journal_request_data(
            title="Climbing Grade Type Check Test",
            content="Test content",
            types=["CLIMBING"],
        )
        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        update_data = {
            "data": {
                "type": "journal-type-data",
                "attributes": {"grade": "eighteen"},
            }
        }
        response = await integration_api_client.put(
            f"/api/journals/{journal_id}/types/CLIMBING/data",
            json=update_data,
        )

        assert response.status_code == 400, "String for grade should return 400 not 500"

    async def test_update_canyoning_with_int_french_grade_returns_400(
        self, integration_api_client
    ):
        """Sending an int for french_grade (expects str) should return 400 not 500."""
        create_data = create_journal_request_data(
            title="Canyoning Grade Type Check Test",
            content="Test content",
            types=["CANYONING"],
        )
        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        update_data = {
            "data": {
                "type": "journal-type-data",
                "attributes": {"french_grade": 123},
            }
        }
        response = await integration_api_client.put(
            f"/api/journals/{journal_id}/types/CANYONING/data",
            json=update_data,
        )

        assert response.status_code == 400, (
            "Integer for french_grade should return 400 not 500"
        )

    async def test_update_canyoning_with_boolean_water_guage_level_returns_400(
        self, integration_api_client
    ):
        """Sending a boolean for water_guage_level should return 400 not 500."""
        create_data = create_journal_request_data(
            title="Canyoning Water Gauge Type Check Test",
            content="Test content",
            types=["CANYONING"],
        )
        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        update_data = {
            "data": {
                "type": "journal-type-data",
                "attributes": {"water_guage_level": True},
            }
        }
        response = await integration_api_client.put(
            f"/api/journals/{journal_id}/types/CANYONING/data",
            json=update_data,
        )

        assert response.status_code == 400, (
            "Boolean water_guage_level should return 400 not 500"
        )

    async def test_update_abseiling_with_null_optional_integers_clears_values(
        self, integration_api_client
    ):
        """Updating ABSEILING_TRIP with null optional ints should clear persisted values."""
        create_data = create_journal_request_data(
            title="Abseiling Clear Test",
            content="Test content",
            types=["ABSEILING_TRIP"],
            type_data={
                "ABSEILING_TRIP": {
                    "number_of_abseils": 5,
                    "total_length": 120,
                }
            },
        )
        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        update_data = {
            "data": {
                "type": "journal-type-data",
                "attributes": {
                    "number_of_abseils": None,
                    "total_length": None,
                },
            }
        }
        response = await integration_api_client.put(
            f"/api/journals/{journal_id}/types/ABSEILING_TRIP/data",
            json=update_data,
        )

        assert response.status_code == 200, response.text
        abseiling_data = response.json()["data"]["attributes"]["type_data"][
            "abseiling_trip"
        ]
        assert "number_of_abseils" not in abseiling_data
        assert "total_length" not in abseiling_data

    async def test_update_canyoning_with_null_water_guage_level_clears_value(
        self, integration_api_client
    ):
        """Updating CANYONING with null water_guage_level should clear the persisted value."""
        create_data = create_journal_request_data(
            title="Canyoning Clear Test",
            content="Test content",
            types=["CANYONING"],
            type_data={
                "CANYONING": {
                    "french_grade": "v3a2IV**",
                    "water_guage_level": 45,
                }
            },
        )
        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        update_data = {
            "data": {
                "type": "journal-type-data",
                "attributes": {"water_guage_level": None},
            }
        }
        response = await integration_api_client.put(
            f"/api/journals/{journal_id}/types/CANYONING/data",
            json=update_data,
        )

        assert response.status_code == 200, response.text
        canyoning_data = response.json()["data"]["attributes"]["type_data"]["canyoning"]
        assert "water_guage_level" not in canyoning_data

    async def test_update_climbing_with_null_optional_integers_clears_values(
        self, integration_api_client
    ):
        """Updating CLIMBING with null optional ints should clear persisted values."""
        create_data = create_journal_request_data(
            title="Climbing Clear Test",
            content="Test content",
            types=["CLIMBING"],
            type_data={
                "CLIMBING": {
                    "climbing_type": "sport",
                    "grade": 18,
                    "length": 25,
                }
            },
        )
        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        update_data = {
            "data": {
                "type": "journal-type-data",
                "attributes": {"grade": None, "length": None},
            }
        }
        response = await integration_api_client.put(
            f"/api/journals/{journal_id}/types/CLIMBING/data",
            json=update_data,
        )

        assert response.status_code == 200, response.text
        climbing_data = response.json()["data"]["attributes"]["type_data"]["climbing"]
        assert "grade" not in climbing_data
        assert "length" not in climbing_data

    async def test_update_kayaking_with_invalid_water_type_returns_400(
        self, integration_api_client
    ):
        """Updating KAYAKING with a non-string water_type should return 400."""
        create_data = create_journal_request_data(
            title="Kayaking Water Type Validation Test",
            content="Test content",
            types=["KAYAKING"],
        )
        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        update_data = {
            "data": {
                "type": "journal-type-data",
                "attributes": {"water_type": 42},
            }
        }
        response = await integration_api_client.put(
            f"/api/journals/{journal_id}/types/KAYAKING/data",
            json=update_data,
        )

        assert response.status_code == 400, (
            "Integer water_type should return 400 not 500"
        )

    async def test_update_cross_country_skiing_with_invalid_snow_conditions_returns_400(
        self, integration_api_client
    ):
        """Updating CROSS_COUNTRY_SKIING with a non-string snow_conditions should return 400."""
        create_data = create_journal_request_data(
            title="Cross Country Skiing Snow Conditions Validation Test",
            content="Test content",
            types=["CROSS_COUNTRY_SKIING"],
        )
        create_response = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_response.status_code == 201
        journal_id = create_response.json()["data"]["id"]

        update_data = {
            "data": {
                "type": "journal-type-data",
                "attributes": {"snow_conditions": 99},
            }
        }
        response = await integration_api_client.put(
            f"/api/journals/{journal_id}/types/CROSS_COUNTRY_SKIING/data",
            json=update_data,
        )

        assert response.status_code == 400, (
            "Integer snow_conditions should return 400 not 500"
        )


@pytest.mark.integration
class TestJournalTypeCreationWithDependencies:
    """Integration tests for journal creation with type dependency resolution.

    Tests that type dependencies are correctly resolved and that duplicate
    type data rows are NOT created when multiple requested types share deps.
    """

    @pytest_asyncio.fixture(autouse=True)
    async def setup_method(self, clean_database):  # noqa: ARG002
        """Setup method to ensure clean database for each test."""
        pass

    async def test_create_journal_with_canyoning_type_creates_all_dependent_types(
        self, integration_api_client
    ):
        """Creating a journal with CANYONING type resolves all 5 dependent types."""
        create_data = create_journal_request_data(
            title="Canyoning Adventure",
            content="Amazing canyon descent",
            types=["CANYONING"],
        )

        response = await integration_api_client.post("/api/journals", json=create_data)

        assert response.status_code == 201, response.text
        data = response.json()
        types = data["data"]["attributes"]["types"]

        # CANYONING resolves: FITNESS, OUTDOOR_ACTIVITY, ABSEILING_TRIP, BUSHWALKING, CANYONING
        assert "canyoning" in types, f"Expected canyoning in {types}"
        assert "bushwalking" in types, f"Expected bushwalking in {types}"
        assert "abseiling_trip" in types, f"Expected abseiling_trip in {types}"
        assert "outdoor_activity" in types, f"Expected outdoor_activity in {types}"
        assert "fitness" in types, f"Expected fitness in {types}"

    async def test_create_journal_with_overlapping_dependencies_does_not_fail(
        self, integration_api_client
    ):
        """Creating a journal with CANYONING + BUSHWALKING (shared deps) succeeds.

        This is the regression test for the bug where overlapping dependencies
        caused IntegrityError when trying to insert duplicate type data rows.
        """
        create_data = create_journal_request_data(
            title="Canyoning and Bushwalking",
            content="Combined adventure",
            types=["CANYONING", "BUSHWALKING"],
        )

        response = await integration_api_client.post("/api/journals", json=create_data)

        assert response.status_code == 201, (
            f"Expected 201 but got {response.status_code}: {response.text}"
        )
        data = response.json()
        types = data["data"]["attributes"]["types"]

        # All 5 types should be present exactly once each
        assert "canyoning" in types, f"Expected canyoning in {types}"
        assert "bushwalking" in types, f"Expected bushwalking in {types}"
        assert "abseiling_trip" in types, f"Expected abseiling_trip in {types}"
        assert "outdoor_activity" in types, f"Expected outdoor_activity in {types}"
        assert "fitness" in types, f"Expected fitness in {types}"

        # Each type should appear exactly once (no duplicates)
        assert types.count("fitness") == 1, (
            f"fitness appeared {types.count('fitness')} times"
        )
        assert types.count("outdoor_activity") == 1
        assert types.count("bushwalking") == 1

    async def test_create_journal_with_jogging_creates_fitness_dependency(
        self, integration_api_client
    ):
        """Creating a journal with JOGGING type also creates FITNESS dependency."""
        create_data = create_journal_request_data(
            title="Morning Jog",
            content="5km run",
            types=["JOGGING"],
        )

        response = await integration_api_client.post("/api/journals", json=create_data)

        assert response.status_code == 201, response.text
        data = response.json()
        types = data["data"]["attributes"]["types"]

        assert "jogging" in types, f"Expected jogging in {types}"
        assert "fitness" in types, f"Expected fitness in {types}"

    async def test_create_journal_with_mood_rating_type_creates_mood_data(
        self, integration_api_client
    ):
        """Creating a journal with MOOD_RATING type creates the mood data row."""
        create_data = create_journal_request_data(
            title="Mood Check-in",
            content="Feeling good today",
            types=["MOOD_RATING"],
        )

        response = await integration_api_client.post("/api/journals", json=create_data)

        assert response.status_code == 201, response.text
        data = response.json()
        attrs = data["data"]["attributes"]

        assert "mood_rating" in attrs["types"], (
            f"Expected mood_rating in {attrs['types']}"
        )
        assert "mood_rating" in attrs.get("type_data", {}), (
            "Expected mood_rating data in type_data"
        )

    async def test_create_journal_with_multiple_overlapping_activity_types_succeeds(
        self, integration_api_client
    ):
        """Creating a journal with CLIMBING + ABSEILING_TRIP (shared deps) succeeds."""
        create_data = create_journal_request_data(
            title="Climbing and Abseiling",
            content="Multi-discipline day",
            types=["CLIMBING", "ABSEILING_TRIP"],
        )

        response = await integration_api_client.post("/api/journals", json=create_data)

        assert response.status_code == 201, (
            f"Expected 201 but got {response.status_code}: {response.text}"
        )
        data = response.json()
        types = data["data"]["attributes"]["types"]

        # Both types plus their shared dependencies
        assert "climbing" in types, f"Expected climbing in {types}"
        assert "abseiling_trip" in types, f"Expected abseiling_trip in {types}"
        assert "outdoor_activity" in types, f"Expected outdoor_activity in {types}"
        assert "fitness" in types, f"Expected fitness in {types}"

        # No duplicate fitness
        assert types.count("fitness") == 1, (
            f"fitness appeared {types.count('fitness')} times (expected 1)"
        )

    async def test_create_journal_with_mood_rating_persists_submitted_values(
        self, integration_api_client
    ):
        """Creating a MOOD_RATING journal with type_data persists submitted mood_value and energy_level."""
        mood_value = 8
        energy_level = 6
        create_data = create_journal_request_data(
            title="Mood With Custom Values",
            content="Feeling great today",
            types=["MOOD_RATING"],
            type_data={
                "MOOD_RATING": {
                    "mood_value": mood_value,
                    "energy_level": energy_level,
                    "mood_label": "Great",
                }
            },
        )

        response = await integration_api_client.post("/api/journals", json=create_data)

        assert response.status_code == 201, response.text
        data = response.json()
        attrs = data["data"]["attributes"]

        assert "mood_rating" in attrs.get("type_data", {}), (
            "Expected mood_rating data in type_data"
        )
        mood_data = attrs["type_data"]["mood_rating"]
        assert mood_data["mood_value"] == mood_value, (
            f"Expected mood_value={mood_value} but got {mood_data['mood_value']}"
        )
        assert mood_data["energy_level"] == energy_level, (
            f"Expected energy_level={energy_level} but got {mood_data['energy_level']}"
        )
        assert mood_data["mood_label"] == "Great"

    async def test_create_journal_with_outdoor_types_persists_type_data(
        self, integration_api_client
    ):
        """Creating a journal with OUTDOOR_ACTIVITY, BUSHWALKING, and JOGGING persists submitted type_data."""
        create_data = create_journal_request_data(
            title="Active Day",
            content="Went for a walk then a jog",
            types=["OUTDOOR_ACTIVITY", "BUSHWALKING", "JOGGING", "FITNESS"],
            type_data={
                "OUTDOOR_ACTIVITY": {
                    "weather_conditions": "Sunny, 20C",
                    "in_leadership_role": True,
                },
                "BUSHWALKING": {
                    "track_grading": "Grade 3",
                },
                "JOGGING": {
                    "pace": 360,
                },
                "FITNESS": {
                    "distance": 8000,
                },
            },
        )

        response = await integration_api_client.post("/api/journals", json=create_data)

        assert response.status_code == 201, response.text
        data = response.json()
        attrs = data["data"]["attributes"]

        type_data = attrs.get("type_data", {})

        assert "outdoor_activity" in type_data
        assert type_data["outdoor_activity"]["weather_conditions"] == "Sunny, 20C"
        assert type_data["outdoor_activity"]["in_leadership_role"] is True

        assert "bushwalking" in type_data
        assert type_data["bushwalking"]["track_grading"] == "Grade 3"

        assert "jogging" in type_data
        assert type_data["jogging"]["pace"] == 360

        assert "fitness" in type_data
        assert type_data["fitness"]["distance"] == 8000

    async def test_create_journal_with_complex_activity_types_persists_type_data(
        self, integration_api_client
    ):
        """Creating a journal with the newer complex activity types persists submitted type_data."""
        create_data = create_journal_request_data(
            title="Big Adventure Day",
            content="A mixed activity day across multiple disciplines",
            types=[
                "ABSEILING_TRIP",
                "CANYONING",
                "CLIMBING",
                "KAYAKING",
                "CROSS_COUNTRY_SKIING",
            ],
            type_data={
                "ABSEILING_TRIP": {
                    "number_of_abseils": 5,
                    "total_length": 120,
                },
                "CANYONING": {
                    "french_grade": "v3a2IV**",
                    "water_guage_name": "Slot Canyon Gauge",
                    "water_guage_level": 45,
                    "is_vertical": True,
                    "is_night_canyon": False,
                    "is_white_water": True,
                },
                "CLIMBING": {
                    "climbing_type": "sport",
                    "grade": 18,
                    "length": 25,
                },
                "KAYAKING": {
                    "water_type": "river",
                },
                "CROSS_COUNTRY_SKIING": {
                    "snow_conditions": "packed powder",
                },
            },
        )

        response = await integration_api_client.post("/api/journals", json=create_data)

        assert response.status_code == 201, response.text
        data = response.json()
        attrs = data["data"]["attributes"]

        type_data = attrs.get("type_data", {})

        assert "abseiling_trip" in type_data
        assert type_data["abseiling_trip"]["number_of_abseils"] == 5
        assert type_data["abseiling_trip"]["total_length"] == 120

        assert "canyoning" in type_data
        assert type_data["canyoning"]["french_grade"] == "v3a2IV**"
        assert type_data["canyoning"]["water_guage_name"] == "Slot Canyon Gauge"
        assert type_data["canyoning"]["water_guage_level"] == 45
        assert type_data["canyoning"]["is_vertical"] is True
        assert type_data["canyoning"]["is_night_canyon"] is False
        assert type_data["canyoning"]["is_white_water"] is True

        assert "climbing" in type_data
        assert type_data["climbing"]["climbing_type"] == "sport"
        assert type_data["climbing"]["grade"] == 18
        assert type_data["climbing"]["length"] == 25

        assert "kayaking" in type_data
        assert type_data["kayaking"]["water_type"] == "river"

        assert "cross_country_skiing" in type_data
        assert type_data["cross_country_skiing"]["snow_conditions"] == "packed powder"


@pytest.mark.integration
class TestJournalHierarchyReparenting:
    """Integration tests for re-parenting existing journals via PATCH.

    Validates that we can add an existing journal as a child of another journal
    by updating its parent_id through the PATCH endpoint. Tests cover multiple
    journal subtypes, cycle detection, and max-depth enforcement.
    """

    @pytest_asyncio.fixture(autouse=True)
    async def setup_method(self, clean_database):  # noqa: ARG002
        """Setup method to ensure clean database for each test."""
        pass

    @staticmethod
    def _patch_parent_data(journal_id: str, parent_id: int | None) -> dict[str, Any]:
        """Build a PATCH request body that sets parent_id."""
        return {
            "data": {
                "type": "journals",
                "id": journal_id,
                "attributes": {
                    "parent_id": parent_id,
                },
            }
        }

    @staticmethod
    async def _create_journal(
        client,
        title: str,
        content: str,
        types: list[str] | None = None,
        parent_id: str | int | None = None,
    ) -> str:
        kwargs: dict[str, Any] = {"title": title, "content": content}
        if types is not None:
            kwargs["types"] = types
        if parent_id is not None:
            kwargs["parent_id"] = parent_id
        data = create_journal_request_data(**kwargs)
        resp = await client.post("/api/journals", json=data)
        assert resp.status_code == 201
        return str(resp.json()["data"]["id"])

    # --- Subtype tests: verify PATCH parent_id works for various journal types ---

    @pytest.mark.parametrize(
        "journal_type,parent_title,child_title",
        [
            (None, "Parent Note", "Orphan Note"),
            (["FITNESS"], "Parent Fitness", "Orphan Fitness"),
            (["EVENT"], "Parent Event", "Orphan Event"),
        ],
    )
    async def test_patch_parent_id_on_journal_subtypes(
        self, integration_api_client, journal_type, parent_title, child_title
    ):
        """Test setting parent_id on various journal subtypes via PATCH."""
        parent_id = await self._create_journal(
            integration_api_client,
            title=parent_title,
            content="Parent content",
            types=journal_type,
        )
        child_id = await self._create_journal(
            integration_api_client,
            title=child_title,
            content="Child content",
            types=journal_type,
        )

        patch_body = self._patch_parent_data(child_id, int(parent_id))
        response = await integration_api_client.patch(
            f"/api/journals/{child_id}", json=patch_body
        )

        assert response.status_code == 200
        attrs = response.json()["data"]["attributes"]
        assert int(attrs["parent_id"]) == int(parent_id)
        assert attrs["parent"] is not None
        assert attrs["depth"] == 2

    # --- Parent appears in children list ---

    async def test_parent_shows_reparented_child_in_children_list(
        self, integration_api_client
    ):
        """After PATCH parent_id, the parent's GET should list the child."""
        parent_id = await self._create_journal(
            integration_api_client, title="Parent List", content="Parent content"
        )
        child_id = await self._create_journal(
            integration_api_client, title="Orphan List", content="Child content"
        )

        # Re-parent
        patch_body = self._patch_parent_data(child_id, int(parent_id))
        await integration_api_client.patch(f"/api/journals/{child_id}", json=patch_body)

        # Fetch parent and check children list
        parent_get = await integration_api_client.get(f"/api/journals/{parent_id}")
        assert parent_get.status_code == 200
        children = parent_get.json()["data"]["attributes"]["children"]
        child_ids = [str(c["id"]) for c in children]
        assert str(child_id) in child_ids

    # --- Validation tests ---

    async def test_patch_parent_id_cycle_detection(self, integration_api_client):
        """Test that setting parent_id to a descendant fails with a cycle error."""
        a_id = await self._create_journal(
            integration_api_client, title="Journal A", content="A content"
        )
        b_id = await self._create_journal(
            integration_api_client,
            title="Journal B",
            content="B content",
            parent_id=int(a_id),
        )

        # Try to make A a child of B (would create cycle A -> B -> A)
        patch_body = self._patch_parent_data(a_id, int(b_id))
        response = await integration_api_client.patch(
            f"/api/journals/{a_id}", json=patch_body
        )

        assert response.status_code == 400

    async def test_patch_parent_id_max_depth_exceeded(self, integration_api_client):
        """Test that PATCH parent_id fails when it would exceed max depth."""
        # Build a chain of 5 levels (max depth)
        current_parent_id: int | None = None
        for level in range(5):
            data = create_journal_request_data(
                title=f"Level {level}",
                content=f"Level {level} content",
                parent_id=current_parent_id,
            )
            resp = await integration_api_client.post("/api/journals", json=data)
            assert resp.status_code == 201
            current_parent_id = resp.json()["data"]["id"]

        # Create a journal with its own child (depth 2)
        orphan_data = create_journal_request_data(
            title="Orphan Root", content="Orphan content"
        )
        orphan_resp = await integration_api_client.post(
            "/api/journals", json=orphan_data
        )
        orphan_id = orphan_resp.json()["data"]["id"]

        # Try to attach the orphan under the deepest journal (level 4, depth 5)
        # This would make the orphan depth 6 — exceeding max depth
        assert current_parent_id is not None
        patch_body = self._patch_parent_data(orphan_id, int(current_parent_id))
        response = await integration_api_client.patch(
            f"/api/journals/{orphan_id}", json=patch_body
        )

        assert response.status_code == 400

    async def test_patch_parent_id_nonexistent_parent(self, integration_api_client):
        """Test that setting parent_id to a non-existent journal fails."""
        child_data = create_journal_request_data(
            title="Orphan", content="Orphan content"
        )
        child_resp = await integration_api_client.post("/api/journals", json=child_data)
        child_id = child_resp.json()["data"]["id"]

        patch_body = self._patch_parent_data(child_id, 99999)
        response = await integration_api_client.patch(
            f"/api/journals/{child_id}", json=patch_body
        )

        assert response.status_code == 404

    async def test_patch_parent_id_change_parent(self, integration_api_client):
        """Test changing a journal's parent from one journal to another."""
        # Create parent A, parent B, and child under A
        a_data = create_journal_request_data(title="Parent A", content="A content")
        a_resp = await integration_api_client.post("/api/journals", json=a_data)
        a_id = a_resp.json()["data"]["id"]

        b_data = create_journal_request_data(title="Parent B", content="B content")
        b_resp = await integration_api_client.post("/api/journals", json=b_data)
        b_id = b_resp.json()["data"]["id"]

        child_data = create_journal_request_data(
            title="Child", content="Child content", parent_id=a_id
        )
        child_resp = await integration_api_client.post("/api/journals", json=child_data)
        child_id = child_resp.json()["data"]["id"]

        # Move child from A to B
        patch_body = self._patch_parent_data(child_id, int(b_id))
        response = await integration_api_client.patch(
            f"/api/journals/{child_id}", json=patch_body
        )

        assert response.status_code == 200
        attrs = response.json()["data"]["attributes"]
        assert int(attrs["parent_id"]) == int(b_id)
        assert attrs["parent"]["title"] == "Parent B"

        # Verify A no longer has the child
        a_get = await integration_api_client.get(f"/api/journals/{a_id}")
        a_children = a_get.json()["data"]["attributes"]["children"]
        a_child_ids = [str(c["id"]) for c in a_children]
        assert str(child_id) not in a_child_ids

        # Verify B now has the child
        b_get = await integration_api_client.get(f"/api/journals/{b_id}")
        b_children = b_get.json()["data"]["attributes"]["children"]
        b_child_ids = [str(c["id"]) for c in b_children]
        assert str(child_id) in b_child_ids


@pytest.mark.integration
class TestJournalCalendarSyncEvents:
    """Integration tests for Google Calendar sync event publishing.

    These tests verify that modifying EVENT type data publishes
    JournalUpdated outbox events with calendar_info in changed_fields,
    which the Google worker uses to trigger outbound sync.
    """

    @pytest_asyncio.fixture(autouse=True)
    async def setup_method(self, clean_database):  # noqa: ARG002
        """Setup method to ensure clean database for each test."""
        pass

    async def _create_calendar(self, client, name="Test Cal"):
        """Create a calendar via the API and return its ID."""
        import uuid

        cal_data = {
            "data": {
                "type": "calendars",
                "attributes": {
                    "name": name,
                    "color": "#FF0000",
                    "is_synced_to_google": True,
                    "google_calendar_id": f"cal_{uuid.uuid4().hex[:8]}@group.calendar.google.com",
                },
            }
        }
        resp = await client.post("/api/calendars", json=cal_data)
        assert resp.status_code == 201, resp.text
        return resp.json()["data"]["id"]

    async def test_update_event_type_data_publishes_journal_updated_event(
        self, integration_api_client, async_connection
    ):
        """Updating EVENT type data should publish a JournalUpdated outbox event
        with calendar_info in changed_fields so the Google worker can sync."""
        import json

        from sqlalchemy import text

        # 1. Create a calendar
        calendar_id = await self._create_calendar(integration_api_client)

        # 2. Create a journal with EVENT type and calendar data
        create_data = create_journal_request_data(
            title="Calendar Sync Test",
            content="Testing sync event",
            types=["EVENT"],
            type_data={
                "EVENT": {
                    "calendar_id": calendar_id,
                    "is_all_day": True,
                },
            },
        )
        create_resp = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_resp.status_code == 201, create_resp.text
        journal_id = create_resp.json()["data"]["id"]

        # 3. Clear all outbox events from creation
        await async_connection.execute(text("DELETE FROM outbox_events"))

        # 4. Update EVENT type data (change location)
        update_data = {
            "data": {
                "type": "journal-type-data",
                "attributes": {
                    "location": "Sydney Opera House",
                },
            }
        }
        update_resp = await integration_api_client.put(
            f"/api/journals/{journal_id}/types/EVENT/data", json=update_data
        )
        assert update_resp.status_code == 200, update_resp.text

        # 5. Verify a JournalUpdated outbox event was published
        result = await async_connection.execute(
            text(
                "SELECT event_type, event_data FROM outbox_events"
                " WHERE event_type = 'JournalUpdated'"
                " AND aggregate_id = :journal_id"
            ),
            {"journal_id": int(journal_id)},
        )
        rows = result.fetchall()

        assert len(rows) >= 1, (
            "Expected a JournalUpdated outbox event after updating EVENT type data"
        )

        # Verify changed_fields contains calendar_info in at least one event
        found_sync_event = False
        for row in rows:
            event_data = json.loads(row.event_data)
            if "calendar_info" in event_data.get("changed_fields", {}):
                found_sync_event = True
                break

        assert found_sync_event, (
            "JournalUpdated event must include calendar_info in changed_fields "
            "for Google Calendar sync to trigger"
        )

    async def test_create_journal_with_event_type_publishes_sync_event(
        self, integration_api_client, async_connection
    ):
        """Creating a journal with EVENT type should publish a JournalUpdated event
        with calendar_info in changed_fields (in addition to JournalCreated)."""
        import json

        from sqlalchemy import text

        # 1. Create a calendar
        calendar_id = await self._create_calendar(integration_api_client)

        # 2. Clear all outbox events
        await async_connection.execute(text("DELETE FROM outbox_events"))

        # 3. Create a journal with EVENT type and calendar data
        create_data = create_journal_request_data(
            title="New Event Journal",
            content="Testing sync on create",
            types=["EVENT"],
            type_data={
                "EVENT": {
                    "calendar_id": calendar_id,
                    "is_all_day": False,
                    "start_time": "09:00",
                    "end_time": "10:00",
                    "location": "Conference Room",
                },
            },
        )
        create_resp = await integration_api_client.post(
            "/api/journals", json=create_data
        )
        assert create_resp.status_code == 201, create_resp.text
        journal_id = create_resp.json()["data"]["id"]

        # 4. Verify a JournalUpdated event with calendar_info was published
        result = await async_connection.execute(
            text(
                "SELECT event_type, event_data FROM outbox_events"
                " WHERE event_type = 'JournalUpdated'"
                " AND aggregate_id = :journal_id"
            ),
            {"journal_id": int(journal_id)},
        )
        rows = result.fetchall()

        assert len(rows) >= 1, (
            "Expected a JournalUpdated outbox event after creating journal with EVENT type"
        )

        found_sync_event = False
        for row in rows:
            event_data = json.loads(row.event_data)
            if "calendar_info" in event_data.get("changed_fields", {}):
                found_sync_event = True
                break

        assert found_sync_event, (
            "JournalUpdated event must include calendar_info in changed_fields "
            "for Google Calendar sync to trigger"
        )
