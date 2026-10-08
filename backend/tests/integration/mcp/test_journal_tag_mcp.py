"""
Integration tests for MCP journal tag tools.

Mirrors the contact `list_contact_tags` coverage in
`test_contact_tools_integration.py` for the journal tag namespace.
"""

import json
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_tag_repository import SqlJournalTagRepository
from app.core.journal.models.journal_tag import JournalTag
from tests.integration.contact_seeding import TEST_USER_ID
from tests.integration.mcp.http_helpers import (
    call_mcp_tool,
    extract_mcp_json_payload,
    post_mcp_tool,
)


@pytest_asyncio.fixture
async def journal_tag_repo(
    async_connection: AsyncConnection,
) -> SqlJournalTagRepository:
    """Create a journal tag repository bound to the test connection."""
    return SqlJournalTagRepository(async_connection)


async def _create_journal(connection: AsyncConnection) -> int:
    """Insert a journal for a tag to be assigned to, returning its id."""
    now = datetime.now(UTC)
    result = await connection.execute(
        text(
            """
            INSERT INTO journals
                (user_id, title, content,
                 event_date_range_start, event_date_range_end)
            VALUES (:user_id, :title, :content, :start, :end)
            RETURNING id
            """
        ),
        {
            "user_id": "test-user-123",
            "title": "MCP tag rename subject",
            "content": "Carries the renamed tag",
            "start": now,
            "end": now,
        },
    )
    row = result.fetchone()
    assert row is not None
    return int(row[0])


async def call_list_journal_tags(
    authenticated_lifespan_client: Any, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Call the list_journal_tags MCP tool and return its payload."""
    async with authenticated_lifespan_client() as authenticated_client:
        return await call_mcp_tool(
            authenticated_client,
            "list_journal_tags",
            arguments if arguments is not None else {},
            request_id=2,
        )


async def call_update_journal_tag(
    authenticated_lifespan_client: Any, arguments: dict[str, Any]
) -> str:
    """Call the update_journal_tag MCP tool and return the raw response text."""
    async with authenticated_lifespan_client() as authenticated_client:
        response = await post_mcp_tool(
            authenticated_client, "update_journal_tag", arguments, request_id=2
        )

    assert response.status_code == 200
    return str(response.text)


async def call_delete_journal_tag(
    authenticated_lifespan_client: Any, arguments: dict[str, Any]
) -> str:
    """Call the delete_journal_tag MCP tool and return the raw response text."""
    async with authenticated_lifespan_client() as authenticated_client:
        response = await post_mcp_tool(
            authenticated_client, "delete_journal_tag", arguments, request_id=2
        )

    assert response.status_code == 200
    return str(response.text)


async def call_merge_journal_tag(
    authenticated_lifespan_client: Any, arguments: dict[str, Any]
) -> str:
    """Call the merge_journal_tag MCP tool and return the raw response text."""
    async with authenticated_lifespan_client() as authenticated_client:
        response = await post_mcp_tool(
            authenticated_client, "merge_journal_tag", arguments, request_id=2
        )

    assert response.status_code == 200
    return str(response.text)


@pytest.mark.integration
class TestUpdateJournalTagMCPTool:
    """Integration tests for the update_journal_tag MCP tool."""

    @pytest.mark.asyncio
    async def test_update_journal_tag_via_mounted_http_session(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
    ):
        """The tool updates a tag and the write is committed."""
        tag = await journal_tag_repo.save(
            JournalTag(
                user_id=TEST_USER_ID,
                name="training",
                color="#00FF00",
                description="Old",
            )
        )

        raw = await call_update_journal_tag(
            authenticated_lifespan_client,
            {
                "tag_id": str(tag.id),
                "name": "conditioning",
                "color": "#123456",
                "description": "Structured conditioning work",
            },
        )
        payload = extract_mcp_json_payload(raw)

        assert payload["name"] == "conditioning"
        assert payload["color"] == "#123456"
        assert payload["description"] == "Structured conditioning work"

        persisted = await journal_tag_repo.find_by_id(tag.id)
        assert persisted is not None
        assert persisted.name == "conditioning"
        assert persisted.description == "Structured conditioning work"

    @pytest.mark.asyncio
    async def test_update_journal_tag_partial_update(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
    ):
        """Omitted arguments leave the corresponding fields untouched."""
        tag = await journal_tag_repo.save(
            JournalTag(
                user_id=TEST_USER_ID,
                name="training",
                color="#00FF00",
                description="Keep me",
            )
        )

        await call_update_journal_tag(
            authenticated_lifespan_client, {"tag_id": str(tag.id), "name": "cardio"}
        )

        persisted = await journal_tag_repo.find_by_id(tag.id)
        assert persisted is not None
        assert persisted.name == "cardio"
        assert persisted.color == "#00FF00"
        assert persisted.description == "Keep me"

    @pytest.mark.asyncio
    async def test_update_journal_tag_move_to_root(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
    ):
        """move_to_root clears the parent, since an omitted parent_id means no change."""
        parent = await journal_tag_repo.save(
            JournalTag(user_id=TEST_USER_ID, name="outdoors")
        )
        child = await journal_tag_repo.save(
            JournalTag(user_id=TEST_USER_ID, name="climbing", parent_id=parent.id)
        )

        await call_update_journal_tag(
            authenticated_lifespan_client,
            {"tag_id": str(child.id), "move_to_root": True},
        )

        persisted = await journal_tag_repo.find_by_id(child.id)
        assert persisted is not None
        assert persisted.parent_id is None

    @pytest.mark.asyncio
    async def test_update_journal_tag_reparent(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
    ):
        """A tag can be re-parented under another tag."""
        parent = await journal_tag_repo.save(
            JournalTag(user_id=TEST_USER_ID, name="outdoors")
        )
        child = await journal_tag_repo.save(
            JournalTag(user_id=TEST_USER_ID, name="climbing")
        )

        await call_update_journal_tag(
            authenticated_lifespan_client,
            {"tag_id": str(child.id), "parent_id": str(parent.id)},
        )

        persisted = await journal_tag_repo.find_by_id(child.id)
        assert persisted is not None
        assert persisted.parent_id == parent.id

    @pytest.mark.asyncio
    async def test_update_journal_tag_duplicate_name_errors(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
    ):
        """A name held by another tag is rejected and nothing is written."""
        await journal_tag_repo.save(JournalTag(user_id=TEST_USER_ID, name="training"))
        other = await journal_tag_repo.save(
            JournalTag(user_id=TEST_USER_ID, name="reflection")
        )

        raw = await call_update_journal_tag(
            authenticated_lifespan_client,
            {"tag_id": str(other.id), "name": "TRAINING"},
        )

        assert "already exists" in raw.lower()
        persisted = await journal_tag_repo.find_by_id(other.id)
        assert persisted is not None
        assert persisted.name == "reflection"

    @pytest.mark.asyncio
    async def test_update_journal_tag_cycle_errors(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
    ):
        """A tag cannot become its own ancestor."""
        parent = await journal_tag_repo.save(
            JournalTag(user_id=TEST_USER_ID, name="outdoors")
        )
        child = await journal_tag_repo.save(
            JournalTag(user_id=TEST_USER_ID, name="climbing", parent_id=parent.id)
        )

        raw = await call_update_journal_tag(
            authenticated_lifespan_client,
            {"tag_id": str(parent.id), "parent_id": str(child.id)},
        )

        assert "circular" in raw.lower()
        persisted = await journal_tag_repo.find_by_id(parent.id)
        assert persisted is not None
        assert persisted.parent_id is None

    @pytest.mark.asyncio
    async def test_update_journal_tag_unknown_tag_errors(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ):
        """Updating a tag that does not exist reports a not-found error."""
        raw = await call_update_journal_tag(
            authenticated_lifespan_client,
            {
                "tag_id": "00000000-0000-0000-0000-000000000000",
                "name": "ghost",
            },
        )

        assert "not found" in raw.lower()

    @pytest.mark.asyncio
    async def test_update_journal_tag_empty_parent_id_errors(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
    ):
        """An empty-string parent_id is rejected, not silently ignored."""
        tag = await journal_tag_repo.save(
            JournalTag(user_id=TEST_USER_ID, name="training")
        )

        raw = await call_update_journal_tag(
            authenticated_lifespan_client,
            {"tag_id": str(tag.id), "parent_id": ""},
        )

        assert "invalid parent tag uuid" in raw.lower()

    @pytest.mark.asyncio
    async def test_update_journal_tag_invalid_uuid_errors(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ):
        """A malformed tag id is reported rather than raising an unhandled error."""
        raw = await call_update_journal_tag(
            authenticated_lifespan_client, {"tag_id": "not-a-uuid", "name": "x"}
        )

        assert "invalid tag uuid" in raw.lower()

    @pytest.mark.asyncio
    async def test_rename_publishes_a_rename_event_with_mcp_provenance(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
        async_connection,
    ):
        """An AI-agent rename must be attributable in the journal's feed.

        The REST path is covered by ``TestJournalTagRenameHistoryEvents``; this
        pins that the MCP tool carries its own provenance rather than falling
        back to the service's ``system`` default.
        """
        tag = await journal_tag_repo.save(
            JournalTag(user_id=TEST_USER_ID, name="mcp-rename-source")
        )
        journal_id = await _create_journal(async_connection)
        await journal_tag_repo.assign_tag(journal_id, tag.id)
        await async_connection.execute(text("DELETE FROM outbox_events"))

        await call_update_journal_tag(
            authenticated_lifespan_client,
            {"tag_id": str(tag.id), "name": "mcp-rename-target"},
        )

        result = await async_connection.execute(
            text(
                "SELECT event_data FROM outbox_events "
                "WHERE event_type = 'JournalTagRenamed' ORDER BY id"
            )
        )
        rows = result.fetchall()
        assert len(rows) == 1
        data = json.loads(rows[0][0]) if isinstance(rows[0][0], str) else rows[0][0]
        assert data["journal_id"] == journal_id
        assert data["tag_id"] == str(tag.id)
        assert data["old_name"] == "mcp-rename-source"
        assert data["new_name"] == "mcp-rename-target"
        assert data["source"] == "mcp"
        assert data["changed_by"] == "mcp"


@pytest.mark.integration
class TestDeleteJournalTagMCPTool:
    """Integration tests for the delete_journal_tag MCP tool."""

    @pytest.mark.asyncio
    async def test_delete_journal_tag_via_mounted_http_session(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
    ):
        """The tool deletes an unused tag and the write is committed."""
        tag = await journal_tag_repo.save(
            JournalTag(user_id=TEST_USER_ID, name="obsolete")
        )

        raw = await call_delete_journal_tag(
            authenticated_lifespan_client, {"tag_id": str(tag.id)}
        )
        payload = extract_mcp_json_payload(raw)

        assert payload["status"] == "success"
        assert await journal_tag_repo.find_by_id(tag.id) is None

    @pytest.mark.asyncio
    async def test_delete_journal_tag_in_use_unassigns_it(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
        async_connection: AsyncConnection,
    ):
        """Deleting an assigned tag succeeds and leaves the journal untagged."""
        from core_shared.models.journals import EventDateRange, Journal

        from app.core.journal.adapters.sql.journal_repository import (
            SqlJournalRepository,
        )

        journal = await SqlJournalRepository(async_connection).save(
            Journal(
                user_id="test-user",
                title="Tagged Journal",
                content="Test content",
                event_date_range=EventDateRange(
                    start=datetime.now(UTC), end=datetime.now(UTC)
                ),
            )
        )
        tag = await journal_tag_repo.save(
            JournalTag(user_id=TEST_USER_ID, name="in-use")
        )
        await journal_tag_repo.assign_tag(journal.id, tag.id)

        raw = await call_delete_journal_tag(
            authenticated_lifespan_client, {"tag_id": str(tag.id)}
        )

        assert extract_mcp_json_payload(raw)["status"] == "success"
        assert await journal_tag_repo.find_by_id(tag.id) is None
        assert await journal_tag_repo.get_tags_for_journal(journal.id) == []

    @pytest.mark.asyncio
    async def test_delete_journal_tag_unknown_tag_errors(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ):
        """An unknown tag id reports not-found, not a generic failure.

        Asserted on the parsed payload rather than the raw response envelope so a
        success response that merely mentions the phrase cannot pass.
        """
        tag_id = "00000000-0000-0000-0000-000000000000"
        raw = await call_delete_journal_tag(
            authenticated_lifespan_client, {"tag_id": tag_id}
        )

        payload = extract_mcp_json_payload(raw)
        assert payload["error"] == "Not found"
        assert str(tag_id) in payload["message"]

    @pytest.mark.asyncio
    async def test_delete_publishes_a_delete_event_with_mcp_provenance(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
        async_connection,
    ):
        """An AI-agent delete must be attributable in each journal's feed.

        The REST path is covered by ``TestJournalTagDeleteHistoryEvents``; this
        pins that the MCP tool carries its own provenance rather than falling
        back to the service's ``system`` default.
        """
        tag = await journal_tag_repo.save(
            JournalTag(user_id=TEST_USER_ID, name="mcp-delete-subject")
        )
        journal_id = await _create_journal(async_connection)
        await journal_tag_repo.assign_tag(journal_id, tag.id)
        await async_connection.execute(text("DELETE FROM outbox_events"))

        await call_delete_journal_tag(
            authenticated_lifespan_client, {"tag_id": str(tag.id)}
        )

        result = await async_connection.execute(
            text(
                "SELECT event_data FROM outbox_events "
                "WHERE event_type = 'JournalTagDeleted' ORDER BY id"
            )
        )
        rows = result.fetchall()
        assert len(rows) == 1
        data = json.loads(rows[0][0]) if isinstance(rows[0][0], str) else rows[0][0]
        assert data["journal_id"] == journal_id
        assert data["tag_id"] == str(tag.id)
        assert data["tag_name"] == "mcp-delete-subject"
        assert data["source"] == "mcp"
        assert data["changed_by"] == "mcp"

    @pytest.mark.asyncio
    async def test_delete_journal_tag_invalid_uuid_errors(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ):
        """A malformed tag id is reported rather than raising an unhandled error."""
        raw = await call_delete_journal_tag(
            authenticated_lifespan_client, {"tag_id": "not-a-uuid"}
        )

        payload = extract_mcp_json_payload(raw)
        assert payload["error"] == "Journal error"
        assert "invalid tag uuid" in payload["message"].lower()


@pytest.mark.integration
class TestMergeJournalTagMCPTool:
    """Integration tests for the merge_journal_tag MCP tool."""

    @pytest.mark.asyncio
    async def test_merge_journal_tag_moves_assignments_and_children(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
        async_connection: AsyncConnection,
    ):
        """The tool re-points assignments, adopts children, and deletes the source."""
        from core_shared.models.journals import EventDateRange, Journal

        from app.core.journal.adapters.sql.journal_repository import (
            SqlJournalRepository,
        )

        journal = await SqlJournalRepository(async_connection).save(
            Journal(
                user_id="test-user",
                title="Blue Mountains",
                content="Test content",
                event_date_range=EventDateRange(
                    start=datetime.now(UTC), end=datetime.now(UTC)
                ),
            )
        )
        source = await journal_tag_repo.save(
            JournalTag(user_id=TEST_USER_ID, name="hiking")
        )
        target = await journal_tag_repo.save(
            JournalTag(user_id=TEST_USER_ID, name="bushwalking")
        )
        child = await journal_tag_repo.save(
            JournalTag(user_id=TEST_USER_ID, name="day walks", parent_id=source.id)
        )
        await journal_tag_repo.assign_tag(journal.id, source.id)

        raw = await call_merge_journal_tag(
            authenticated_lifespan_client,
            {"source_tag_id": str(source.id), "target_tag_id": str(target.id)},
        )
        payload = extract_mcp_json_payload(raw)

        assert payload["status"] == "success"
        # The summary is what an AI caller reads back, so pin it names both
        # tags and says the source is gone rather than only checking status.
        assert str(source.id) in payload["summary"]
        assert str(target.id) in payload["summary"]
        assert "deleted" in payload["summary"].lower()

        assert await journal_tag_repo.find_by_id(source.id) is None
        assigned = await journal_tag_repo.get_tags_for_journal(journal.id)
        assert [tag.id for tag in assigned] == [target.id]
        surviving_child = await journal_tag_repo.find_by_id(child.id)
        assert surviving_child is not None
        assert surviving_child.parent_id == target.id

    @pytest.mark.asyncio
    async def test_merge_journal_tag_into_self_errors(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
    ):
        """Merging a tag into itself is reported rather than silently deleting it."""
        tag = await journal_tag_repo.save(
            JournalTag(user_id=TEST_USER_ID, name="hiking")
        )

        raw = await call_merge_journal_tag(
            authenticated_lifespan_client,
            {"source_tag_id": str(tag.id), "target_tag_id": str(tag.id)},
        )

        payload = extract_mcp_json_payload(raw)
        assert payload["error"] == "Journal error"
        assert "itself" in payload["message"].lower()
        # The tag must survive a rejected merge.
        assert await journal_tag_repo.find_by_id(tag.id) is not None

    @pytest.mark.asyncio
    async def test_merge_journal_tag_into_descendant_errors(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
    ):
        """Merging a tag into its own child is reported and changes nothing."""
        parent = await journal_tag_repo.save(
            JournalTag(user_id=TEST_USER_ID, name="outdoors")
        )
        child = await journal_tag_repo.save(
            JournalTag(user_id=TEST_USER_ID, name="climbing", parent_id=parent.id)
        )

        raw = await call_merge_journal_tag(
            authenticated_lifespan_client,
            {"source_tag_id": str(parent.id), "target_tag_id": str(child.id)},
        )

        payload = extract_mcp_json_payload(raw)
        assert payload["error"] == "Journal error"
        assert "descendant" in payload["message"].lower()
        assert await journal_tag_repo.find_by_id(parent.id) is not None

    @pytest.mark.asyncio
    async def test_merge_journal_tag_unknown_target_errors(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
    ):
        """An unknown target reports not-found and leaves the source in place."""
        source = await journal_tag_repo.save(
            JournalTag(user_id=TEST_USER_ID, name="hiking")
        )

        raw = await call_merge_journal_tag(
            authenticated_lifespan_client,
            {
                "source_tag_id": str(source.id),
                "target_tag_id": "00000000-0000-0000-0000-000000000000",
            },
        )

        payload = extract_mcp_json_payload(raw)
        assert payload["error"] == "Not found"
        assert await journal_tag_repo.find_by_id(source.id) is not None

    @pytest.mark.asyncio
    async def test_merge_journal_tag_unknown_source_errors(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
    ):
        """An unknown source reports not-found and leaves the target in place."""
        target = await journal_tag_repo.save(
            JournalTag(user_id=TEST_USER_ID, name="bushwalking")
        )

        raw = await call_merge_journal_tag(
            authenticated_lifespan_client,
            {
                "source_tag_id": "00000000-0000-0000-0000-000000000000",
                "target_tag_id": str(target.id),
            },
        )

        payload = extract_mcp_json_payload(raw)
        assert payload["error"] == "Not found"
        assert await journal_tag_repo.find_by_id(target.id) is not None

    @pytest.mark.asyncio
    async def test_merge_publishes_a_merge_event_with_mcp_provenance(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
        async_connection,
    ):
        """An AI-agent merge must be attributable in each journal's feed.

        The REST path is covered by ``TestJournalTagMergeHistoryEvents``; this
        pins that the MCP tool carries its own provenance rather than falling
        back to the service's ``system`` default.
        """
        source = await journal_tag_repo.save(
            JournalTag(user_id=TEST_USER_ID, name="mcp-merge-source")
        )
        target = await journal_tag_repo.save(
            JournalTag(user_id=TEST_USER_ID, name="mcp-merge-target")
        )
        journal_id = await _create_journal(async_connection)
        await journal_tag_repo.assign_tag(journal_id, source.id)
        await async_connection.execute(text("DELETE FROM outbox_events"))

        await call_merge_journal_tag(
            authenticated_lifespan_client,
            {"source_tag_id": str(source.id), "target_tag_id": str(target.id)},
        )

        result = await async_connection.execute(
            text(
                "SELECT event_data FROM outbox_events "
                "WHERE event_type = 'JournalTagMerged' ORDER BY id"
            )
        )
        rows = result.fetchall()
        assert len(rows) == 1
        data = json.loads(rows[0][0]) if isinstance(rows[0][0], str) else rows[0][0]
        assert data["journal_id"] == journal_id
        assert data["source_tag_id"] == str(source.id)
        assert data["target_tag_id"] == str(target.id)
        assert data["source_tag_name"] == "mcp-merge-source"
        assert data["target_tag_name"] == "mcp-merge-target"
        assert data["already_had_target"] is False
        assert data["source"] == "mcp"
        assert data["changed_by"] == "mcp"

    @pytest.mark.asyncio
    async def test_merge_journal_tag_invalid_uuid_errors(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ):
        """A malformed tag id is reported rather than raising an unhandled error."""
        raw = await call_merge_journal_tag(
            authenticated_lifespan_client,
            {"source_tag_id": "not-a-uuid", "target_tag_id": "also-not-a-uuid"},
        )

        payload = extract_mcp_json_payload(raw)
        assert payload["error"] == "Journal error"
        assert "invalid tag uuid" in payload["message"].lower()


@pytest.mark.integration
class TestListJournalTagsMCPTool:
    """Integration tests for the list_journal_tags MCP tool."""

    @pytest.mark.asyncio
    async def test_list_journal_tags_via_mounted_http_session(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
    ):
        """Mounted MCP HTTP calls should resolve request-scoped dependencies."""
        await journal_tag_repo.save(JournalTag(user_id=TEST_USER_ID, name="training"))
        await journal_tag_repo.save(JournalTag(user_id=TEST_USER_ID, name="reflection"))

        payload = await call_list_journal_tags(
            authenticated_lifespan_client, {"limit": 10}
        )

        assert payload["total_count"] == 2
        # Repository orders by name, so this ordering is deterministic
        assert [tag["name"] for tag in payload["tags"]] == ["reflection", "training"]

    @pytest.mark.asyncio
    async def test_list_journal_tags_returns_colour_and_description(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
    ):
        """The tool exposes colour and description for each tag."""
        await journal_tag_repo.save(
            JournalTag(
                user_id=TEST_USER_ID,
                name="training",
                color="#00FF00",
                description="Structured training sessions",
            )
        )

        payload = await call_list_journal_tags(authenticated_lifespan_client)

        tag = payload["tags"][0]
        assert tag["color"] == "#00FF00"
        assert tag["description"] == "Structured training sessions"

    @pytest.mark.asyncio
    async def test_list_journal_tags_returns_hierarchy(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
    ):
        """The tool exposes parent_id so AI callers can reconstruct the tree."""
        parent = await journal_tag_repo.save(
            JournalTag(user_id=TEST_USER_ID, name="activities")
        )
        await journal_tag_repo.save(
            JournalTag(
                user_id=TEST_USER_ID, name="activities-climbing", parent_id=parent.id
            )
        )

        payload = await call_list_journal_tags(authenticated_lifespan_client)

        tags_by_name = {tag["name"]: tag for tag in payload["tags"]}
        assert tags_by_name["activities"]["parent_id"] is None
        assert tags_by_name["activities-climbing"]["parent_id"] == str(parent.id)

    @pytest.mark.asyncio
    async def test_list_journal_tags_without_description_returns_null(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
    ):
        """Tags created without a description serialise it as null."""
        await journal_tag_repo.save(JournalTag(user_id=TEST_USER_ID, name="training"))

        payload = await call_list_journal_tags(authenticated_lifespan_client)

        assert payload["tags"][0]["description"] is None

    @pytest.mark.asyncio
    async def test_list_journal_tags_respects_limit(
        self,
        authenticated_lifespan_client,
        journal_tag_repo,
    ):
        """The limit argument bounds how many tags are returned."""
        await journal_tag_repo.save(JournalTag(user_id=TEST_USER_ID, name="alpha"))
        await journal_tag_repo.save(JournalTag(user_id=TEST_USER_ID, name="beta"))
        await journal_tag_repo.save(JournalTag(user_id=TEST_USER_ID, name="gamma"))

        payload = await call_list_journal_tags(
            authenticated_lifespan_client, {"limit": 2}
        )

        assert payload["total_count"] == 2
        assert [tag["name"] for tag in payload["tags"]] == ["alpha", "beta"]

    @pytest.mark.asyncio
    async def test_list_journal_tags_with_no_tags(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ):
        """An empty tag namespace returns an empty list, not an error."""
        payload = await call_list_journal_tags(authenticated_lifespan_client)

        assert payload["total_count"] == 0
        assert payload["tags"] == []
