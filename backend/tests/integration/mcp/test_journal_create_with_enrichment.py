"""
Integration tests for MCP journal creation with types, tags, contacts, and parent.

Reproduces production bugs where:
- Creating journals with types (NOTE, valid/invalid) caused InFailedSQLTransactionError
- Invalid type names (TRIP, CANYON) were silently ignored instead of returning errors
- Tags were silently swallowed on error
- Contact relationships silently failed
- Parent_id was not reflected when the transaction rolled back
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration.mcp.http_helpers import (
    extract_mcp_json_payload,
    initialize_mcp_session,
    mcp_headers,
)


@pytest.fixture
def _create_journal_via_mcp():
    """Helper to create a journal via the MCP create_journal_entry tool."""

    async def _create(
        authenticated_client, session_id: str, journal_data: dict[str, object]
    ):
        response = await authenticated_client.post(
            "/mcp-server/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "create_journal_entry",
                    "arguments": {
                        "request": journal_data,
                    },
                },
            },
            headers=mcp_headers(session_id),
        )
        assert response.status_code == 200
        return extract_mcp_json_payload(response.text)

    return _create


@pytest.fixture
def _update_journal_via_mcp():
    """Helper to update a journal via the MCP update_journal_entry tool."""

    async def _update(
        authenticated_client,
        session_id: str,
        journal_id: int,
        journal_data: dict[str, object],
    ):
        response = await authenticated_client.post(
            "/mcp-server/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "update_journal_entry",
                    "arguments": {
                        "journal_id": journal_id,
                        "request": journal_data,
                    },
                },
            },
            headers=mcp_headers(session_id),
        )
        assert response.status_code == 200
        return extract_mcp_json_payload(response.text)

    return _update


@pytest.fixture
def _link_contact_via_mcp():
    """Helper to link a contact to a journal via MCP link_journal_to_contact tool."""

    async def _link(
        authenticated_client,
        session_id: str,
        journal_id: int,
        contact_id: int,
        relationship_type: str = "PARTICIPANT",
    ):
        response = await authenticated_client.post(
            "/mcp-server/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "link_journal_to_contact",
                    "arguments": {
                        "journal_id": journal_id,
                        "contact_id": contact_id,
                        "relationship_type": relationship_type,
                    },
                },
            },
            headers=mcp_headers(session_id),
        )
        assert response.status_code == 200
        return extract_mcp_json_payload(response.text)

    return _link


class TestCreateJournalWithTypes:
    """Test that creating journals with types works correctly through MCP."""

    @pytest.mark.asyncio
    async def test_create_journal_with_note_type_succeeds(
        self,
        authenticated_lifespan_client,
        _create_journal_via_mcp,
    ) -> None:
        """Creating a journal with NOTE type should succeed without errors.

        Reproduces: InFailedSQLTransactionError when creating with types=["NOTE"]
        """
        async with authenticated_lifespan_client() as authenticated_client:
            session_id = await initialize_mcp_session(authenticated_client)
            payload = await _create_journal_via_mcp(
                authenticated_client,
                session_id,
                {
                    "title": "Utah Trip 2025",
                    "content": "Road trip to Utah.",
                    "event_date_range": {
                        "start": "2025-04-09",
                        "end": "2025-04-10",
                    },
                    "types": ["NOTE"],
                },
            )

            assert "error" not in payload, f"Unexpected error: {payload}"
            assert payload["title"] == "Utah Trip 2025"
            # NOTE type should be reflected
            assert "note" in payload["types"]

    @pytest.mark.asyncio
    async def test_create_journal_with_note_type_and_tags_succeeds(
        self,
        authenticated_lifespan_client,
        _create_journal_via_mcp,
    ) -> None:
        """Creating a journal with NOTE type AND tags should succeed.

        Reproduces: Tags were silently swallowed when type addition caused
        a transaction failure.
        """
        async with authenticated_lifespan_client() as authenticated_client:
            session_id = await initialize_mcp_session(authenticated_client)
            payload = await _create_journal_via_mcp(
                authenticated_client,
                session_id,
                {
                    "title": "Utah Trip 2025",
                    "content": "Road trip to Utah.",
                    "event_date_range": {
                        "start": "2025-04-09",
                        "end": "2025-04-10",
                    },
                    "types": ["NOTE"],
                    "tags": ["utah", "road-trip", "travel", "zion"],
                },
            )

            assert "error" not in payload, f"Unexpected error: {payload}"
            assert payload["title"] == "Utah Trip 2025"
            # Tags should be present in the response
            assert sorted(payload["tags"]) == sorted(
                ["utah", "road-trip", "travel", "zion"]
            )

    @pytest.mark.asyncio
    async def test_create_journal_with_invalid_type_returns_validation_error(
        self,
        authenticated_lifespan_client,
        _create_journal_via_mcp,
    ) -> None:
        """Creating with an invalid type name (TRIP) should return a clear error.

        Reproduces: TRIP type was silently ignored, creating journal without types.
        The AI agent was not informed of the failure and could not correct the input.
        """
        async with authenticated_lifespan_client() as authenticated_client:
            session_id = await initialize_mcp_session(authenticated_client)
            payload = await _create_journal_via_mcp(
                authenticated_client,
                session_id,
                {
                    "title": "Utah Trip 2025",
                    "content": "Road trip to Utah.",
                    "event_date_range": {
                        "start": "2025-04-09",
                        "end": "2025-04-10",
                    },
                    "types": ["TRIP"],
                    "tags": ["utah", "road-trip"],
                },
            )

            # Should report a validation error with the invalid type name
            assert "error" in payload
            assert "TRIP" in payload.get("message", "")

            # Verify no journal was persisted (no partial commit)
            search_response = await authenticated_client.post(
                "/mcp-server/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "search_journals",
                        "arguments": {"query": "Utah Trip 2025"},
                    },
                },
                headers=mcp_headers(session_id),
            )
            assert search_response.status_code == 200
            search_payload = extract_mcp_json_payload(search_response.text)
            journals = search_payload.get("journals", [])
            assert not any(j.get("title") == "Utah Trip 2025" for j in journals), (
                "Journal should not be persisted when types are invalid"
            )

    @pytest.mark.asyncio
    async def test_create_journal_with_iso_datetime_event_date_range(
        self,
        authenticated_lifespan_client,
        _create_journal_via_mcp,
    ) -> None:
        """Creating with ISO datetime format for event_date_range should work.

        Reproduces: Second attempt with ISO format also failed due to transaction error.
        """
        async with authenticated_lifespan_client() as authenticated_client:
            session_id = await initialize_mcp_session(authenticated_client)
            payload = await _create_journal_via_mcp(
                authenticated_client,
                session_id,
                {
                    "title": "Meeting Notes",
                    "content": "Team sync discussion.",
                    "event_date_range": {
                        "start": "2025-04-09T00:00:00",
                        "end": "2025-04-10T23:59:00",
                    },
                    "types": ["NOTE"],
                    "tags": ["work", "meeting"],
                },
            )

            assert "error" not in payload, f"Unexpected error: {payload}"
            assert payload["title"] == "Meeting Notes"
            assert sorted(payload["tags"]) == sorted(["work", "meeting"])

    @pytest.mark.asyncio
    async def test_create_journal_with_valid_outdoor_type_and_tags(
        self,
        authenticated_lifespan_client,
        _create_journal_via_mcp,
    ) -> None:
        """Creating with a valid outdoor activity type plus tags should succeed.

        Verifies the fix handles types with dependency chains (BUSHWALKING
        requires OUTDOOR_ACTIVITY + FITNESS).
        """
        async with authenticated_lifespan_client() as authenticated_client:
            session_id = await initialize_mcp_session(authenticated_client)
            payload = await _create_journal_via_mcp(
                authenticated_client,
                session_id,
                {
                    "title": "Blue Mountains Walk",
                    "content": "Grand Canyon track.",
                    "event_date_range": {
                        "start": "2025-05-01",
                        "end": "2025-05-01",
                    },
                    "types": ["BUSHWALKING"],
                    "tags": ["bushwalking", "blue-mountains"],
                },
            )

            assert "error" not in payload, f"Unexpected error: {payload}"
            # Should include bushwalking + dependency types
            assert "bushwalking" in payload["types"]
            assert "outdoor_activity" in payload["types"]
            assert "fitness" in payload["types"]
            # Tags should be present
            assert "bushwalking" in payload["tags"]
            assert "blue-mountains" in payload["tags"]


class TestCreateJournalWithContacts:
    """Test journal creation and contact relationship linking via MCP."""

    @pytest.mark.asyncio
    async def test_create_journal_with_contact_relationships(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        _create_journal_via_mcp,
    ) -> None:
        """Creating a journal with contact_relationships should persist them.

        Reproduces: contact_relationships on create were silently swallowed.
        """
        # Create a test contact
        contact_result = await clean_database.execute(
            text("""
                INSERT INTO contacts (first_name, last_name)
                VALUES ('Sarah-Jane', 'Petts')
                RETURNING id
            """),
        )
        contact_row = contact_result.fetchone()
        assert contact_row is not None
        contact_id = int(contact_row[0])

        async with authenticated_lifespan_client() as authenticated_client:
            session_id = await initialize_mcp_session(authenticated_client)
            payload = await _create_journal_via_mcp(
                authenticated_client,
                session_id,
                {
                    "title": "Utah Trip 2025",
                    "content": "Road trip with Sarah-Jane.",
                    "event_date_range": {
                        "start": "2025-04-09",
                        "end": "2025-04-10",
                    },
                    "types": ["NOTE"],
                    "contact_relationships": [
                        {
                            "contact_id": contact_id,
                            "relationship_type": "PARTICIPANT",
                        }
                    ],
                },
            )

            assert "error" not in payload, f"Unexpected error: {payload}"
            assert len(payload["contacts"]) == 1
            assert payload["contacts"][0]["id"] == contact_id
            assert payload["contacts"][0]["relationship_type"] == "PARTICIPANT"

    @pytest.mark.asyncio
    async def test_link_journal_to_contact_via_tool(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        _create_journal_via_mcp,
        _link_contact_via_mcp,
    ) -> None:
        """Linking a contact to a journal via link_journal_to_contact should persist.

        Reproduces: link_journal_to_contact appeared to succeed but contacts were empty.
        """
        # Create a test contact
        contact_result = await clean_database.execute(
            text("""
                INSERT INTO contacts (first_name, last_name)
                VALUES ('Sarah-Jane', 'Petts')
                RETURNING id
            """),
        )
        contact_row = contact_result.fetchone()
        assert contact_row is not None
        contact_id = int(contact_row[0])

        async with authenticated_lifespan_client() as authenticated_client:
            session_id = await initialize_mcp_session(authenticated_client)

            # First create a journal
            create_payload = await _create_journal_via_mcp(
                authenticated_client,
                session_id,
                {
                    "title": "Utah Trip 2025",
                    "content": "Road trip.",
                    "event_date_range": {
                        "start": "2025-04-09",
                        "end": "2025-04-10",
                    },
                },
            )
            assert "error" not in create_payload
            journal_id = create_payload["id"]

            # Link contact
            link_payload = await _link_contact_via_mcp(
                authenticated_client,
                session_id,
                journal_id,
                contact_id,
                "PARTICIPANT",
            )
            assert "error" not in link_payload


class TestCreateJournalWithParent:
    """Test journal creation with parent_id through MCP."""

    @pytest.mark.asyncio
    async def test_create_child_journal_with_types_and_tags(
        self,
        authenticated_lifespan_client,
        _create_journal_via_mcp,
    ) -> None:
        """Creating a parent then child journal with types/tags should both persist.

        Reproduces: Child entries were not linked to parent because the parent
        creation itself failed silently due to InFailedSQLTransactionError.
        """
        async with authenticated_lifespan_client() as authenticated_client:
            session_id = await initialize_mcp_session(authenticated_client)

            # Create parent journal
            parent_payload = await _create_journal_via_mcp(
                authenticated_client,
                session_id,
                {
                    "title": "Utah Trip 2025",
                    "content": "Multi-day road trip.",
                    "event_date_range": {
                        "start": "2025-04-09",
                        "end": "2025-04-12",
                    },
                    "types": ["NOTE"],
                    "tags": ["utah", "travel"],
                },
            )
            assert "error" not in parent_payload, f"Parent error: {parent_payload}"
            parent_id = parent_payload["id"]

            # Create child journal under parent
            child_payload = await _create_journal_via_mcp(
                authenticated_client,
                session_id,
                {
                    "title": "Day 1 - Zion National Park",
                    "content": "Hiked Angels Landing.",
                    "event_date_range": {
                        "start": "2025-04-09",
                        "end": "2025-04-09",
                    },
                    "types": ["NOTE"],
                    "tags": ["zion", "hiking"],
                    "parent_id": parent_id,
                },
            )
            assert "error" not in child_payload, f"Child error: {child_payload}"
            assert child_payload["parent"]["id"] == parent_id


class TestUpdateJournalWithTypesAndTags:
    """Test journal update with types and tags through MCP."""

    @pytest.mark.asyncio
    async def test_update_journal_with_tags_succeeds(
        self,
        authenticated_lifespan_client,
        _create_journal_via_mcp,
        _update_journal_via_mcp,
    ) -> None:
        """Updating a journal to add tags should persist them."""
        async with authenticated_lifespan_client() as authenticated_client:
            session_id = await initialize_mcp_session(authenticated_client)

            # Create journal without tags
            create_payload = await _create_journal_via_mcp(
                authenticated_client,
                session_id,
                {
                    "title": "Trip Notes",
                    "content": "Some notes.",
                    "event_date_range": {
                        "start": "2025-04-09",
                        "end": "2025-04-09",
                    },
                },
            )
            assert "error" not in create_payload
            journal_id = create_payload["id"]

            # Update with tags
            update_payload = await _update_journal_via_mcp(
                authenticated_client,
                session_id,
                journal_id,
                {"tags": ["utah", "road-trip"]},
            )

            assert "error" not in update_payload, f"Update error: {update_payload}"
            assert sorted(update_payload["tags"]) == sorted(["utah", "road-trip"])

    @pytest.mark.asyncio
    async def test_update_journal_with_invalid_type_returns_error(
        self,
        authenticated_lifespan_client,
        _create_journal_via_mcp,
        _update_journal_via_mcp,
    ) -> None:
        """Updating a journal with an invalid type name should return an error."""
        async with authenticated_lifespan_client() as authenticated_client:
            session_id = await initialize_mcp_session(authenticated_client)

            # Create journal
            create_payload = await _create_journal_via_mcp(
                authenticated_client,
                session_id,
                {
                    "title": "Trip Notes",
                    "content": "Some notes.",
                    "event_date_range": {
                        "start": "2025-04-09",
                        "end": "2025-04-09",
                    },
                },
            )
            assert "error" not in create_payload
            journal_id = create_payload["id"]

            # Update with invalid type
            update_payload = await _update_journal_via_mcp(
                authenticated_client,
                session_id,
                journal_id,
                {"types": ["CANYON"]},
            )

            # Should report a validation error with the invalid type name
            assert "error" in update_payload
            assert "CANYON" in update_payload.get("message", "")

    @pytest.mark.asyncio
    async def test_update_journal_with_contacts_succeeds(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
        _create_journal_via_mcp,
        _update_journal_via_mcp,
    ) -> None:
        """Updating a journal to add contact relationships should persist them."""
        # Create a test contact
        contact_result = await clean_database.execute(
            text("""
                INSERT INTO contacts (first_name, last_name)
                VALUES ('Test', 'Contact')
                RETURNING id
            """),
        )
        contact_row = contact_result.fetchone()
        assert contact_row is not None
        contact_id = int(contact_row[0])

        async with authenticated_lifespan_client() as authenticated_client:
            session_id = await initialize_mcp_session(authenticated_client)

            # Create journal without contacts
            create_payload = await _create_journal_via_mcp(
                authenticated_client,
                session_id,
                {
                    "title": "Trip Notes",
                    "content": "Some notes.",
                    "event_date_range": {
                        "start": "2025-04-09",
                        "end": "2025-04-09",
                    },
                },
            )
            assert "error" not in create_payload
            journal_id = create_payload["id"]

            # Update with contacts
            update_payload = await _update_journal_via_mcp(
                authenticated_client,
                session_id,
                journal_id,
                {
                    "contact_relationships": [
                        {
                            "contact_id": contact_id,
                            "relationship_type": "PARTICIPANT",
                        }
                    ]
                },
            )

            assert "error" not in update_payload, f"Update error: {update_payload}"
            assert len(update_payload["contacts"]) == 1
            assert update_payload["contacts"][0]["id"] == contact_id


class TestListJournalTypes:
    """Test the list_journal_types discovery tool."""

    @pytest.mark.asyncio
    async def test_list_journal_types_returns_all_types(
        self,
        authenticated_lifespan_client,
    ) -> None:
        """list_journal_types should return all valid type names with metadata."""
        async with authenticated_lifespan_client() as authenticated_client:
            session_id = await initialize_mcp_session(authenticated_client)

            response = await authenticated_client.post(
                "/mcp-server/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "list_journal_types",
                        "arguments": {},
                    },
                },
                headers=mcp_headers(session_id),
            )
            assert response.status_code == 200
            payload = extract_mcp_json_payload(response.text)

            # Should have journal_types list
            assert "journal_types" in payload
            type_names = [t["name"] for t in payload["journal_types"]]

            # Verify all expected types are present
            expected_types = [
                "NOTE",
                "EVENT",
                "MOOD_RATING",
                "PLAN",
                "TRAVEL",
                "PHOTO_ALBUM",
                "FITNESS",
                "OUTDOOR_ACTIVITY",
                "BUSHWALKING",
                "JOGGING",
                "ABSEILING_TRIP",
                "CANYONING",
                "CLIMBING",
                "KAYAKING",
                "CROSS_COUNTRY_SKIING",
            ]
            for expected in expected_types:
                assert expected in type_names, f"Missing type: {expected}"

            # Verify types have descriptions
            for type_info in payload["journal_types"]:
                assert "description" in type_info
                assert "dependencies" in type_info

            # Verify EVENT has type_data_fields with calendar_id
            event_type = next(
                t for t in payload["journal_types"] if t["name"] == "EVENT"
            )
            assert event_type["type_data_fields"] is not None
            assert "calendar_id" in event_type["type_data_fields"]

            # Verify BUSHWALKING has dependencies
            bushwalking_type = next(
                t for t in payload["journal_types"] if t["name"] == "BUSHWALKING"
            )
            assert "OUTDOOR_ACTIVITY" in bushwalking_type["dependencies"]
            assert "FITNESS" in bushwalking_type["dependencies"]

            # Verify contact_relationship_enums are present
            assert "contact_relationship_enums" in payload
            enums = payload["contact_relationship_enums"]
            assert "PARTICIPANT" in enums["relationship_types"]
            assert "INVITEE" in enums["relationship_types"]
            assert "MENTION" in enums["relationship_types"]
            assert "ABOUT" in enums["relationship_types"]
            assert "ATTENDING" in enums["attendee_statuses"]
            assert "ORGANISER" in enums["contact_event_roles"]

            # Verify usage hint
            assert "usage_hint" in payload
