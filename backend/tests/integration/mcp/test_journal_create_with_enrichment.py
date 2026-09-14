"""
Integration tests for MCP journal creation with types, tags, contacts, and parent.

Reproduces production bugs where:
- Creating journals with types (NOTE, valid/invalid) caused InFailedSQLTransactionError
- Invalid type names (TRIP, CANYON) were silently ignored instead of returning errors
- Tags were silently swallowed on error
- Contact relationships silently failed
- Parent_id was not reflected when the transaction rolled back
"""

from typing import Any

import pytest
from core_shared.models.journals import JournalType
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from tests.integration.mcp.http_helpers import (
    call_mcp_tool,
)
from tests.integration.tasks.task_seeding import OTHER_USER_ID, create_journal


@pytest.fixture
def _create_journal_via_mcp():
    """Helper to create a journal via the MCP create_journal_entry tool."""

    async def _create(
        authenticated_client: Any, journal_data: dict[str, object]
    ) -> dict[str, Any]:
        return await call_mcp_tool(
            authenticated_client,
            "create_journal_entry",
            {
                "request": journal_data,
            },
            request_id=2,
        )

    return _create


@pytest.fixture
def _update_journal_via_mcp():
    """Helper to update a journal via the MCP update_journal_entry tool."""

    async def _update(
        authenticated_client: Any,
        journal_id: int,
        journal_data: dict[str, object],
    ) -> dict[str, Any]:
        return await call_mcp_tool(
            authenticated_client,
            "update_journal_entry",
            {
                "journal_id": journal_id,
                "request": journal_data,
            },
            request_id=3,
        )

    return _update


@pytest.fixture
def _link_contact_via_mcp():
    """Helper to link a contact to a journal via MCP link_journal_to_contact tool."""

    async def _link(
        authenticated_client: Any,
        journal_id: int,
        contact_id: int,
        relationship_type: str = "PARTICIPANT",
    ) -> dict[str, Any]:
        return await call_mcp_tool(
            authenticated_client,
            "link_journal_to_contact",
            {
                "journal_id": journal_id,
                "contact_id": contact_id,
                "relationship_type": relationship_type,
            },
            request_id=4,
        )

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
            payload = await _create_journal_via_mcp(
                authenticated_client,
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
            payload = await _create_journal_via_mcp(
                authenticated_client,
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
            payload = await _create_journal_via_mcp(
                authenticated_client,
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
            search_payload = await call_mcp_tool(
                authenticated_client,
                "search_journals",
                {"query": "Utah Trip 2025"},
                request_id=3,
            )
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
            payload = await _create_journal_via_mcp(
                authenticated_client,
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
            payload = await _create_journal_via_mcp(
                authenticated_client,
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
            payload = await _create_journal_via_mcp(
                authenticated_client,
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
            # First create a journal
            create_payload = await _create_journal_via_mcp(
                authenticated_client,
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
            # Create parent journal
            parent_payload = await _create_journal_via_mcp(
                authenticated_client,
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

    @pytest.mark.asyncio
    async def test_another_users_journal_cannot_be_used_as_a_parent(
        self,
        authenticated_lifespan_client,
        async_connection: AsyncConnection,
        _create_journal_via_mcp,
    ) -> None:
        """A ``parent_id`` owned by somebody else reads as an absent one (#1312).

        The hierarchy validation resolved the parent unscoped, so an agent
        holding any journal id could hang its user's entry off it. Nothing in
        the response revealed the link — the parent is read back owner-scoped,
        so it serialised as ``null`` — while the row was written all the same.
        """
        theirs = await create_journal(
            SqlJournalRepository(async_connection),
            title="Somebody Else's Trip",
            user_id=OTHER_USER_ID,
        )

        async with authenticated_lifespan_client() as authenticated_client:
            payload = await _create_journal_via_mcp(
                authenticated_client,
                {
                    "title": "Day 1 - Under Their Trip",
                    "content": "Should never be written.",
                    "event_date_range": {
                        "start": "2025-04-09",
                        "end": "2025-04-09",
                    },
                    "types": ["NOTE"],
                    "parent_id": theirs,
                },
            )
            absent_payload = await _create_journal_via_mcp(
                authenticated_client,
                {
                    "title": "Day 1 - Under Nothing",
                    "content": "Should never be written.",
                    "event_date_range": {
                        "start": "2025-04-09",
                        "end": "2025-04-09",
                    },
                    "types": ["NOTE"],
                    "parent_id": 999999,
                },
            )

        # Refused, and refused in the words an id that never existed gets, so
        # the tool cannot be used to find out which ids are real.
        assert payload["error"] == absent_payload["error"] == "Journal not found"
        assert payload["message"] == absent_payload["message"].replace(
            "999999", str(theirs)
        )
        assert "Somebody Else's Trip" not in str(payload)

        written = await async_connection.execute(
            text(
                "SELECT COUNT(*) FROM journals WHERE title = 'Day 1 - Under Their Trip'"
            )
        )
        assert written.scalar_one() == 0

    @pytest.mark.asyncio
    async def test_a_journal_cannot_be_moved_under_another_users_journal(
        self,
        authenticated_lifespan_client,
        async_connection: AsyncConnection,
        _create_journal_via_mcp,
        _update_journal_via_mcp,
    ) -> None:
        """The same refusal on the update path (#1312)."""
        theirs = await create_journal(
            SqlJournalRepository(async_connection),
            title="Somebody Else's Trip",
            user_id=OTHER_USER_ID,
        )

        async with authenticated_lifespan_client() as authenticated_client:
            mine = await _create_journal_via_mcp(
                authenticated_client,
                {
                    "title": "My Own Trip",
                    "content": "Mine.",
                    "event_date_range": {
                        "start": "2025-04-09",
                        "end": "2025-04-09",
                    },
                    "types": ["NOTE"],
                },
            )
            assert "error" not in mine, f"Setup error: {mine}"

            payload = await _update_journal_via_mcp(
                authenticated_client,
                mine["id"],
                {"parent_id": theirs},
            )

        assert payload["error"] == "Journal not found"
        assert str(theirs) in payload["message"]
        assert "Somebody Else's Trip" not in str(payload)

        stored = await async_connection.execute(
            text("SELECT parent_id FROM journals WHERE id = :id"), {"id": mine["id"]}
        )
        assert stored.scalar_one() is None


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
            # Create journal without tags
            create_payload = await _create_journal_via_mcp(
                authenticated_client,
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
            # Create journal
            create_payload = await _create_journal_via_mcp(
                authenticated_client,
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
            # Create journal without contacts
            create_payload = await _create_journal_via_mcp(
                authenticated_client,
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
            payload = await call_mcp_tool(
                authenticated_client, "list_journal_types", {}, request_id=2
            )

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


class TestCreateJournalServicifiedParity:
    """Parity coverage for the servicified create tool (issue #967).

    The composite write now goes through ``JournalWriteService`` instead of the
    tool opening its own ``unit_of_work``. These tests guard the two capabilities
    that were unique to the MCP tool: GEAR_USAGE type-data and find-or-create
    tag reuse.
    """

    async def _create_gear_item(self, authenticated_client: Any) -> str:
        payload = await call_mcp_tool(
            authenticated_client,
            "create_gear_item",
            {"name": "Test Harness", "model": "Altitude"},
            request_id=10,
        )
        assert "error" not in payload, f"gear item create failed: {payload}"
        return str(payload["id"])

    @pytest.mark.asyncio
    async def test_create_journal_with_gear_usage_persists_type_data(
        self,
        authenticated_lifespan_client,
        _create_journal_via_mcp,
    ) -> None:
        """GEAR_USAGE type_data round-trips through the servicified create path."""
        async with authenticated_lifespan_client() as authenticated_client:
            gear_item_id = await self._create_gear_item(authenticated_client)

            payload = await _create_journal_via_mcp(
                authenticated_client,
                {
                    "title": "Harness check-out",
                    "content": "Borrowed the harness for the weekend.",
                    "event_date_range": {
                        "start": "2025-04-09",
                        "end": "2025-04-10",
                    },
                    "types": ["GEAR_USAGE"],
                    "type_data": {
                        "GEAR_USAGE": {
                            "gear_item_id": gear_item_id,
                            "checkout_date": "2025-04-09T08:00:00+00:00",
                        }
                    },
                },
            )

            assert "error" not in payload, f"Unexpected error: {payload}"
            assert "gear_usage" in payload["types"]

    @pytest.mark.asyncio
    async def test_create_journal_missing_gear_usage_type_data_rejected(
        self,
        authenticated_lifespan_client,
        _create_journal_via_mcp,
    ) -> None:
        """Adding GEAR_USAGE without type_data is rejected (validation in the tool)."""
        async with authenticated_lifespan_client() as authenticated_client:
            payload = await _create_journal_via_mcp(
                authenticated_client,
                {
                    "title": "Bad gear usage",
                    "content": "No gear data.",
                    "event_date_range": {
                        "start": "2025-04-09",
                        "end": "2025-04-10",
                    },
                    "types": ["GEAR_USAGE"],
                },
            )

            assert "error" in payload
            assert "GEAR_USAGE" in payload.get("message", "")

    @pytest.mark.asyncio
    async def test_shared_tag_name_is_reused_not_duplicated(
        self,
        authenticated_lifespan_client,
        _create_journal_via_mcp,
        clean_database: AsyncConnection,
    ) -> None:
        """Two journals sharing a tag name reuse one tag row (find-or-create)."""
        async with authenticated_lifespan_client() as authenticated_client:
            for title in ("First entry", "Second entry"):
                payload = await _create_journal_via_mcp(
                    authenticated_client,
                    {
                        "title": title,
                        "content": "shared tag content",
                        "event_date_range": {
                            "start": "2025-04-09",
                            "end": "2025-04-09",
                        },
                        "tags": ["shared-tag"],
                    },
                )
                assert "error" not in payload, f"Unexpected error: {payload}"
                assert payload["tags"] == ["shared-tag"]

        # Exactly one tag row exists for the shared name (find-or-create reuse).
        count = (
            await clean_database.execute(
                text("SELECT COUNT(*) FROM journal_tags WHERE name = :name"),
                {"name": "shared-tag"},
            )
        ).scalar()
        assert count == 1, f"expected exactly one 'shared-tag' row, got {count}"


class TestUpdateJournalServicifiedParity:
    """Tri-state replace-all parity for the servicified update tool (issue #967)."""

    @pytest.mark.asyncio
    async def test_update_title_only_leaves_types_and_tags_intact(
        self,
        authenticated_lifespan_client,
        _create_journal_via_mcp,
        _update_journal_via_mcp,
    ) -> None:
        """Omitted associations (None) are untouched by a core-field-only update."""
        async with authenticated_lifespan_client() as authenticated_client:
            create_payload = await _create_journal_via_mcp(
                authenticated_client,
                {
                    "title": "Original",
                    "content": "c",
                    "event_date_range": {"start": "2025-04-09", "end": "2025-04-09"},
                    "types": ["MOOD_RATING"],
                    "tags": ["keep-me"],
                },
            )
            assert "error" not in create_payload
            journal_id = create_payload["id"]

            update_payload = await _update_journal_via_mcp(
                authenticated_client,
                journal_id,
                {"title": "Renamed"},
            )

            assert "error" not in update_payload, f"error: {update_payload}"
            assert update_payload["title"] == "Renamed"
            assert "mood_rating" in update_payload["types"]
            assert update_payload["tags"] == ["keep-me"]

    @pytest.mark.asyncio
    async def test_update_tags_empty_list_clears_all(
        self,
        authenticated_lifespan_client,
        _create_journal_via_mcp,
        _update_journal_via_mcp,
    ) -> None:
        """tags=[] clears all tags (distinct from omitting tags)."""
        async with authenticated_lifespan_client() as authenticated_client:
            create_payload = await _create_journal_via_mcp(
                authenticated_client,
                {
                    "title": "Tagged",
                    "content": "c",
                    "event_date_range": {"start": "2025-04-09", "end": "2025-04-09"},
                    "tags": ["alpha", "beta"],
                },
            )
            assert "error" not in create_payload
            journal_id = create_payload["id"]

            update_payload = await _update_journal_via_mcp(
                authenticated_client,
                journal_id,
                {"tags": []},
            )

            assert "error" not in update_payload, f"error: {update_payload}"
            assert update_payload["tags"] == []

    @pytest.mark.asyncio
    async def test_update_replace_types_removes_old_type_data(
        self,
        authenticated_lifespan_client,
        _create_journal_via_mcp,
        _update_journal_via_mcp,
    ) -> None:
        """Replacing types removes the old type (and its data) and adds the new one."""
        async with authenticated_lifespan_client() as authenticated_client:
            create_payload = await _create_journal_via_mcp(
                authenticated_client,
                {
                    "title": "Mood entry",
                    "content": "c",
                    "event_date_range": {"start": "2025-04-09", "end": "2025-04-09"},
                    "types": ["MOOD_RATING"],
                    "type_data": {"MOOD_RATING": {"mood_value": 4}},
                },
            )
            assert "error" not in create_payload
            assert "mood_rating" in create_payload["types"]
            journal_id = create_payload["id"]

            update_payload = await _update_journal_via_mcp(
                authenticated_client,
                journal_id,
                {"types": ["FITNESS"]},
            )

            assert "error" not in update_payload, f"error: {update_payload}"
            assert "fitness" in update_payload["types"]
            assert "mood_rating" not in update_payload["types"]


class TestRetypePreservesSharedTypeData:
    """Changing a journal's types must not wipe data of types that remain."""

    @pytest.mark.asyncio
    async def test_bushwalking_to_canyoning_keeps_fitness_and_strava_link(
        self,
        authenticated_lifespan_client,
        _create_journal_via_mcp,
        _update_journal_via_mcp,
    ) -> None:
        async with authenticated_lifespan_client() as authenticated_client:
            created = await _create_journal_via_mcp(
                authenticated_client,
                {
                    "title": "Imlay",
                    "content": "Walk in.",
                    "event_date_range": {
                        "start": "2025-10-15",
                        "end": "2025-10-15",
                    },
                    "types": ["BUSHWALKING"],
                    "type_data": {
                        "FITNESS": {
                            "distance": 16,
                            "strava_activity_id": "16152597201",
                        },
                        "OUTDOOR_ACTIVITY": {"weather_conditions": "Rain"},
                    },
                },
            )
            assert "error" not in created, created

            updated = await _update_journal_via_mcp(
                authenticated_client,
                created["id"],
                {"types": ["CANYONING"]},
            )

            assert "error" not in updated, updated
            assert "canyoning" in updated["types"]
            assert updated["type_data"]["fitness"]["strava_activity_id"] == (
                "16152597201"
            )
            assert updated["type_data"]["fitness"]["distance"] == 16
            assert (
                updated["type_data"]["outdoor_activity"]["weather_conditions"] == "Rain"
            )
            assert updated["types_removed"] == []
            assert updated["type_data_discarded"] == {}

    @pytest.mark.asyncio
    async def test_dropping_a_type_reports_what_was_discarded(
        self,
        authenticated_lifespan_client,
        _create_journal_via_mcp,
        _update_journal_via_mcp,
    ) -> None:
        async with authenticated_lifespan_client() as authenticated_client:
            created = await _create_journal_via_mcp(
                authenticated_client,
                {
                    "title": "Imlay",
                    "content": "Walk in.",
                    "event_date_range": {
                        "start": "2025-10-15",
                        "end": "2025-10-15",
                    },
                    "types": ["BUSHWALKING"],
                    "type_data": {
                        "FITNESS": {"strava_activity_id": "16152597201"},
                    },
                },
            )
            assert "error" not in created, created

            updated = await _update_journal_via_mcp(
                authenticated_client,
                created["id"],
                {"types": ["MOOD_RATING"]},
            )

            assert "error" not in updated, updated
            assert set(updated["types_removed"]) == {
                "bushwalking",
                "outdoor_activity",
                "fitness",
            }
            assert updated["type_data_discarded"]["fitness"] == ["strava_activity_id"]


# Every type an agent can request on its own: NOTE is implicit, PHOTO_ALBUM is
# Immich-managed, EVENT/OUTDOOR_PLANNING need a calendar_id and GEAR_* need a
# gear item, so those are covered by their own tests.
_SELF_CONTAINED_TYPES = sorted(
    set(JournalType)
    - {
        JournalType.NOTE,
        JournalType.PHOTO_ALBUM,
        JournalType.EVENT,
        JournalType.OUTDOOR_PLANNING,
        JournalType.GEAR_MAINTENANCE,
        JournalType.GEAR_USAGE,
    },
    key=lambda t: t.value,
)


class TestEveryTypeRoundTrips:
    """A type that is written must be read back by the MCP tools."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("journal_type", _SELF_CONTAINED_TYPES)
    async def test_created_type_is_present_on_read_back(
        self,
        authenticated_lifespan_client,
        _create_journal_via_mcp,
        journal_type: JournalType,
    ) -> None:
        async with authenticated_lifespan_client() as authenticated_client:
            created = await _create_journal_via_mcp(
                authenticated_client,
                {
                    "title": f"{journal_type.value} round trip",
                    "content": "x",
                    "event_date_range": {
                        "start": "2025-05-01",
                        "end": "2025-05-01",
                    },
                    "types": [journal_type.name],
                },
            )
            assert "error" not in created, created
            assert journal_type.value in created["types"]

            read_back = await call_mcp_tool(
                authenticated_client,
                "get_journal",
                {"journal_id": created["id"]},
            )
            assert journal_type.value in read_back["types"]
            assert journal_type.value in read_back["type_data"]

    @pytest.mark.asyncio
    async def test_note_with_other_types_is_implied_and_explained(
        self,
        authenticated_lifespan_client,
        _create_journal_via_mcp,
    ) -> None:
        async with authenticated_lifespan_client() as authenticated_client:
            created = await _create_journal_via_mcp(
                authenticated_client,
                {
                    "title": "Goblin Valley -> Moab",
                    "content": "x",
                    "event_date_range": {
                        "start": "2025-10-09",
                        "end": "2025-10-09",
                    },
                    "types": ["NOTE", "TRAVEL"],
                },
            )
            assert "error" not in created, created
            assert created["types"] == ["travel"]
            assert "NOTE is implicit" in created["summary"]


class TestExternalLinksOnWriteResponses:
    """Create and update responses carry external_links, not just get_journal."""

    @pytest.mark.asyncio
    async def test_create_and_update_responses_include_strava_link(
        self,
        authenticated_lifespan_client,
        _create_journal_via_mcp,
        _update_journal_via_mcp,
    ) -> None:
        async with authenticated_lifespan_client() as authenticated_client:
            created = await _create_journal_via_mcp(
                authenticated_client,
                {
                    "title": "Echo Canyon",
                    "content": "x",
                    "event_date_range": {
                        "start": "2025-10-13",
                        "end": "2025-10-13",
                    },
                    "types": ["CANYONING"],
                    "type_data": {"FITNESS": {"strava_activity_id": "16135"}},
                },
            )
            assert "error" not in created, created
            assert created["external_links"] == [
                {
                    "source": "strava",
                    "url": "https://www.strava.com/activities/16135",
                    "external_id": "16135",
                }
            ]
            assert created["external_links_preserved"] is None

            updated = await _update_journal_via_mcp(
                authenticated_client,
                created["id"],
                {"title": "Echo Canyon — Zion"},
            )
            assert "error" not in updated, updated
            assert updated["external_links"] == created["external_links"]
            assert updated["external_links_preserved"] is True

    @pytest.mark.asyncio
    async def test_dropping_fitness_reports_link_not_preserved(
        self,
        authenticated_lifespan_client,
        _create_journal_via_mcp,
        _update_journal_via_mcp,
    ) -> None:
        async with authenticated_lifespan_client() as authenticated_client:
            created = await _create_journal_via_mcp(
                authenticated_client,
                {
                    "title": "Echo Canyon",
                    "content": "x",
                    "event_date_range": {
                        "start": "2025-10-13",
                        "end": "2025-10-13",
                    },
                    "types": ["BUSHWALKING"],
                    "type_data": {"FITNESS": {"strava_activity_id": "16135"}},
                },
            )
            assert "error" not in created, created

            updated = await _update_journal_via_mcp(
                authenticated_client,
                created["id"],
                {"types": ["MOOD_RATING"]},
            )
            assert "error" not in updated, updated
            assert updated["external_links"] == []
            assert updated["external_links_preserved"] is False
            assert updated["type_data_discarded"]["fitness"] == ["strava_activity_id"]
