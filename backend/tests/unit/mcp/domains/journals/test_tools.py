"""
Unit tests for journal domain MCP tools.

Tests the MCP tools for journal management functionality.
Note: Full functionality testing with mocked services is done in integration tests.
These unit tests focus on tool registration and basic structure.
"""

from datetime import UTC, datetime, time
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from core_shared.models.history import Provenance
from fastmcp import Client, FastMCP

from app.core.history.models import FieldHistoryEntry
from app.mcp.domains.journals.tools import (
    _fetch_activity_overall_stats_row,
    _fetch_activity_personal_record_row,
    _fetch_activity_rows,
    _fetch_activity_trend_rows,
    _fetch_activity_type_stats_rows,
    _journal_history_entry_to_schema,
    _parse_optional_datetime_filter,
    _update_event_data,
    register_journal_tools,
)


class TestJournalTools:
    """Test journal MCP tools registration and functionality."""

    @pytest.fixture
    def mcp_server(self):
        """Create FastMCP server for testing."""
        from typing import Any

        mcp: Any = FastMCP("TestServer")
        register_journal_tools(mcp)
        return mcp

    @pytest.mark.asyncio
    async def test_list_tools(self, mcp_server):
        """Test that journal tools are properly registered and listed."""
        # Use FastMCP Client for in-memory testing
        async with Client(mcp_server) as client:
            # List available tools
            tools_response = await client.list_tools()

            # Extract tools list - the response might be a list or have a tools attribute
            if hasattr(tools_response, "tools"):
                tools = tools_response.tools
            else:
                tools = tools_response

            # Verify journal tools are registered
            tool_names = [tool.name for tool in tools]
            expected_tools = [
                "create_journal_entry",
                "update_journal_entry",
                "get_journal",
                "search_journals",
                "search_activities",
                "get_activity_stats",
                "analyze_activity_trends",
                "get_route_history",
                "get_journal_history",
                "delete_journal",
                "get_contact_journals",
                "link_journal_to_contact",
                "merge_journals",
                "get_merge_candidates",
                "get_daily_summary",
            ]

            for expected_tool in expected_tools:
                assert expected_tool in tool_names, (
                    f"Tool {expected_tool} not found in registered tools"
                )

    @pytest.mark.asyncio
    async def test_create_journal_entry_tool_registration(self, mcp_server):
        """Test that create_journal_entry tool is properly registered with correct schema."""
        async with Client(mcp_server) as client:
            # List available tools
            tools_response = await client.list_tools()

            # Extract tools list
            if hasattr(tools_response, "tools"):
                tools = tools_response.tools
            else:
                tools = tools_response

            # Find the create_journal_entry tool
            create_tool = None
            for tool in tools:
                if tool.name == "create_journal_entry":
                    create_tool = tool
                    break

            assert create_tool is not None, "create_journal_entry tool not found"
            assert create_tool.description is not None
            assert "create" in create_tool.description.lower()
            assert create_tool.inputSchema is not None

            # Verify the tool has the expected parameter
            properties = create_tool.inputSchema.get("properties", {})
            assert "request" in properties

    @pytest.mark.asyncio
    async def test_update_journal_entry_tool_registration(self, mcp_server):
        """Test that update_journal_entry tool is properly registered with correct schema."""
        async with Client(mcp_server) as client:
            # List available tools
            tools_response = await client.list_tools()

            # Extract tools list
            if hasattr(tools_response, "tools"):
                tools = tools_response.tools
            else:
                tools = tools_response

            # Find the update_journal_entry tool
            update_tool = None
            for tool in tools:
                if tool.name == "update_journal_entry":
                    update_tool = tool
                    break

            assert update_tool is not None, "update_journal_entry tool not found"
            assert update_tool.description is not None
            assert "update" in update_tool.description.lower()
            assert update_tool.inputSchema is not None

            # Verify the tool has the expected parameters
            properties = update_tool.inputSchema.get("properties", {})
            assert "journal_id" in properties
            assert "request" in properties

    @pytest.mark.asyncio
    async def test_get_journal_tool_registration(self, mcp_server):
        """Test that get_journal tool is properly registered with correct schema."""
        async with Client(mcp_server) as client:
            # List available tools
            tools_response = await client.list_tools()

            # Extract tools list
            if hasattr(tools_response, "tools"):
                tools = tools_response.tools
            else:
                tools = tools_response

            # Find the get_journal tool
            get_tool = None
            for tool in tools:
                if tool.name == "get_journal":
                    get_tool = tool
                    break

            assert get_tool is not None, "get_journal tool not found"
            assert get_tool.description is not None
            assert get_tool.inputSchema is not None

            # Verify the tool has the expected parameters
            properties = get_tool.inputSchema.get("properties", {})
            assert "journal_id" in properties
            assert "include_children" in properties

    @pytest.mark.asyncio
    async def test_get_daily_summary_tool_registration(self, mcp_server):
        """Test that get_daily_summary tool is properly registered with correct schema."""
        async with Client(mcp_server) as client:
            tools_response = await client.list_tools()
            tools = (
                tools_response.tools
                if hasattr(tools_response, "tools")
                else tools_response
            )

            summary_tool = next(
                (t for t in tools if t.name == "get_daily_summary"), None
            )

            assert summary_tool is not None, "get_daily_summary tool not found"
            assert summary_tool.description is not None
            assert summary_tool.inputSchema is not None

            # Verify the tool has the expected parameters
            properties = summary_tool.inputSchema.get("properties", {})
            assert "summary_date" in properties

    @pytest.mark.asyncio
    async def test_get_journal_history_tool_registration(self, mcp_server):
        """Test that get_journal_history is registered with the expected schema."""
        async with Client(mcp_server) as client:
            tools_response = await client.list_tools()
            tools = (
                tools_response.tools
                if hasattr(tools_response, "tools")
                else tools_response
            )

            history_tool = next(
                (t for t in tools if t.name == "get_journal_history"), None
            )

            assert history_tool is not None, "get_journal_history tool not found"
            assert history_tool.description is not None
            assert "history" in history_tool.description.lower()
            assert history_tool.inputSchema is not None

            # Verify the tool exposes journal_id plus pagination params.
            properties = history_tool.inputSchema.get("properties", {})
            assert "journal_id" in properties
            assert "page" in properties
            assert "limit" in properties


class TestJournalHistoryEntryMapping:
    """The MCP mapping must preserve field-level detail and provenance,
    matching the REST ``HistoryConverter`` value coercion."""

    def test_maps_all_fields_and_coerces_provenance_enum(self) -> None:
        entry = FieldHistoryEntry(
            entity_type="journal",
            entity_id=42,
            field_name="title",
            old_value="Old",
            new_value="New",
            changed_by="user@example.com",
            source=Provenance.UI,
            created_at=datetime(2024, 1, 15, 10, 30, tzinfo=UTC),
            id=7,
        )

        schema = _journal_history_entry_to_schema(entry)

        assert schema.entity_type == "journal"
        assert schema.entity_id == 42
        assert schema.field_name == "title"
        assert schema.old_value == "Old"
        assert schema.new_value == "New"
        assert schema.changed_by == "user@example.com"
        # Provenance enum is coerced to its string value (parity with the API).
        assert schema.source == "ui"
        assert schema.created_at == datetime(2024, 1, 15, 10, 30, tzinfo=UTC)

    def test_parses_iso_string_created_at(self) -> None:
        entry = FieldHistoryEntry(
            entity_type="journal",
            entity_id=1,
            field_name="content",
            source=Provenance.MCP,
            created_at="2024-03-11T08:00:00+00:00",
            id=9,
        )

        schema = _journal_history_entry_to_schema(entry)

        assert schema.source == "mcp"
        assert schema.created_at == datetime.fromisoformat("2024-03-11T08:00:00+00:00")
        assert schema.old_value is None
        assert schema.new_value is None


class TestDatetimeFilterParsing:
    def test_normalizes_date_only_filters_to_utc_bounds(self) -> None:
        assert _parse_optional_datetime_filter("2024-03-11", "start_date") == datetime(
            2024, 3, 11, 0, 0, 0, tzinfo=UTC
        )
        assert _parse_optional_datetime_filter(
            "2024-03-11", "end_date", is_end=True
        ) == datetime(2024, 3, 11, 23, 59, 59, 999999, tzinfo=UTC)

    def test_preserves_timezone_aware_datetime_filters(self) -> None:
        assert _parse_optional_datetime_filter(
            "2024-03-11T09:15:00Z", "start_date"
        ) == datetime(2024, 3, 11, 9, 15, 0, tzinfo=UTC)


class TestFetchActivityRows:
    @pytest.mark.asyncio
    async def test_applies_sql_limit_and_offset(self) -> None:
        db_connection = AsyncMock()
        result = MagicMock()
        result.fetchall.return_value = []
        db_connection.execute.return_value = result

        await _fetch_activity_rows(
            db_connection,
            "user-123",
            activity_type="jogging",
            limit=5,
            offset=10,
        )

        query = db_connection.execute.await_args.args[0]
        params = db_connection.execute.await_args.args[1]

        assert "LIMIT :limit OFFSET :offset" in str(query)
        assert params["limit"] == 5
        assert params["offset"] == 10


class TestActivityAggregationQueries:
    @pytest.mark.asyncio
    async def test_fetches_overall_activity_stats_in_sql(self) -> None:
        db_connection = AsyncMock()
        result = MagicMock()
        result.fetchone.return_value = (0, 0, 0, 0, 0)
        db_connection.execute.return_value = result

        await _fetch_activity_overall_stats_row(
            db_connection,
            "user-123",
            activity_type="jogging",
            start_date="2024-01-01",
            end_date="2024-01-31",
        )

        query = db_connection.execute.await_args.args[0]
        params = db_connection.execute.await_args.args[1]

        assert "COUNT(*) AS total_activities" in str(query)
        assert "COALESCE(SUM(distance), 0) AS total_distance" in str(query)
        assert params["activity_type"] == "jogging"

    @pytest.mark.asyncio
    async def test_fetches_activity_type_breakdown_in_sql(self) -> None:
        db_connection = AsyncMock()
        result = MagicMock()
        result.fetchall.return_value = []
        db_connection.execute.return_value = result

        await _fetch_activity_type_stats_rows(db_connection, "user-123")

        query = db_connection.execute.await_args.args[0]

        assert "GROUP BY activity_type" in str(query)
        assert "ORDER BY activity_type" in str(query)
        assert "COUNT(*) AS count" in str(query)

    @pytest.mark.asyncio
    async def test_fetches_personal_record_with_sql_ordering_and_limit(self) -> None:
        db_connection = AsyncMock()
        result = MagicMock()
        result.fetchone.return_value = None
        db_connection.execute.return_value = result

        await _fetch_activity_personal_record_row(
            db_connection,
            "user-123",
            metric_name="distance",
        )

        query = db_connection.execute.await_args.args[0]

        assert "distance AS metric_value" in str(query)
        assert "ORDER BY distance DESC" in str(query)
        assert "LIMIT 1" in str(query)

    @pytest.mark.asyncio
    async def test_fetches_activity_trend_buckets_in_sql(self) -> None:
        db_connection = AsyncMock()
        result = MagicMock()
        result.fetchall.return_value = []
        db_connection.execute.return_value = result

        await _fetch_activity_trend_rows(
            db_connection,
            "user-123",
            interval="month",
        )

        query = db_connection.execute.await_args.args[0]
        params = db_connection.execute.await_args.args[1]

        assert "DATE_TRUNC(:interval_unit" in str(query)
        assert "GROUP BY period_start" in str(query)
        assert "ORDER BY period_start" in str(query)
        assert params["interval_unit"] == "month"


class TestUpdateEventData:
    @pytest.mark.asyncio
    async def test_converts_uuid_and_time_strings(self) -> None:
        calendar_id = str(uuid4())
        calendar_info_repo = AsyncMock()

        await _update_event_data(
            journal_id=42,
            type_data_dict={
                "calendar_id": calendar_id,
                "start_time": "09:15",
                "end_time": "10:45:30",
                "is_all_day": False,
                "location": "Conference Room",
                "sync_invitees": True,
            },
            calendar_info_repo=calendar_info_repo,
        )

        calendar_info = calendar_info_repo.save.await_args.args[0]
        assert str(calendar_info.calendar_id) == calendar_id
        assert calendar_info.start_time == time(9, 15)
        assert calendar_info.end_time == time(10, 45, 30)
        assert calendar_info.location == "Conference Room"
        assert calendar_info.sync_invitees is True

    @pytest.mark.asyncio
    async def test_rejects_invalid_calendar_id_string(self) -> None:
        calendar_info_repo = AsyncMock()

        with pytest.raises(ValueError, match="Invalid calendar_id"):
            await _update_event_data(
                journal_id=42,
                type_data_dict={"calendar_id": "not-a-uuid"},
                calendar_info_repo=calendar_info_repo,
            )

        calendar_info_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rejects_invalid_calendar_id_type(self) -> None:
        calendar_info_repo = AsyncMock()

        with pytest.raises(ValueError, match="Invalid calendar_id"):
            await _update_event_data(
                journal_id=42,
                type_data_dict={"calendar_id": 123},
                calendar_info_repo=calendar_info_repo,
            )

        calendar_info_repo.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rejects_invalid_time_string(self) -> None:
        calendar_info_repo = AsyncMock()

        with pytest.raises(ValueError, match="Invalid start_time"):
            await _update_event_data(
                journal_id=42,
                type_data_dict={
                    "calendar_id": str(uuid4()),
                    "start_time": "not-a-time",
                    "end_time": "10:00",
                },
                calendar_info_repo=calendar_info_repo,
            )

        calendar_info_repo.save.assert_not_awaited()


class TestMergeToolRegistration:
    """Test merge tool registration and schema."""

    @pytest.fixture
    def mcp_server(self):
        from typing import Any

        mcp: Any = FastMCP("TestServer")
        register_journal_tools(mcp)
        return mcp

    @pytest.mark.asyncio
    async def test_merge_journals_tool_registration(self, mcp_server):
        """Test that merge_journals tool is registered with correct schema."""
        async with Client(mcp_server) as client:
            tools_response = await client.list_tools()
            tools = (
                tools_response.tools
                if hasattr(tools_response, "tools")
                else tools_response
            )

            merge_tool = next((t for t in tools if t.name == "merge_journals"), None)
            assert merge_tool is not None, "merge_journals tool not found"
            assert merge_tool.description is not None
            assert "merge" in merge_tool.description.lower()
            assert merge_tool.inputSchema is not None

            properties = merge_tool.inputSchema.get("properties", {})
            assert "target_journal_id" in properties
            assert "merge_data" in properties
            assert properties["merge_data"]["type"] == "string"

    @pytest.mark.asyncio
    async def test_get_merge_candidates_tool_registration(self, mcp_server):
        """Test that get_merge_candidates tool is registered with correct schema."""
        async with Client(mcp_server) as client:
            tools_response = await client.list_tools()
            tools = (
                tools_response.tools
                if hasattr(tools_response, "tools")
                else tools_response
            )

            candidates_tool = next(
                (t for t in tools if t.name == "get_merge_candidates"), None
            )
            assert candidates_tool is not None, "get_merge_candidates tool not found"
            assert candidates_tool.description is not None
            assert candidates_tool.inputSchema is not None

            properties = candidates_tool.inputSchema.get("properties", {})
            assert "journal_id" in properties
            assert "limit" in properties


class TestMergeJournalMCPRequestSchema:
    """Test MergeJournalMCPRequest Pydantic schema validation."""

    def test_valid_request_parses_correctly(self):
        from app.mcp.domains.journals.schemas import MergeJournalMCPRequest

        data = {"source_journal_id": 42}
        request = MergeJournalMCPRequest.model_validate(data)
        assert request.source_journal_id == 42
        assert request.overrides is None

    def test_request_with_overrides_parses_correctly(self):
        from app.mcp.domains.journals.schemas import MergeJournalMCPRequest

        data = {
            "source_journal_id": 42,
            "overrides": {
                "title": "Merged title",
                "content": "Merged content",
                "type_data": {"MOOD_RATING": {"mood_value": 8}},
            },
        }
        request = MergeJournalMCPRequest.model_validate(data)
        assert request.source_journal_id == 42
        assert request.overrides is not None
        assert request.overrides["title"] == "Merged title"
        assert request.overrides["type_data"]["MOOD_RATING"]["mood_value"] == 8

    def test_request_missing_source_journal_id_raises(self):
        from pydantic import ValidationError

        from app.mcp.domains.journals.schemas import MergeJournalMCPRequest

        with pytest.raises(ValidationError, match="source_journal_id"):
            MergeJournalMCPRequest.model_validate({})
