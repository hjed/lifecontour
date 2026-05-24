"""
Integration tests for MCP journal tools.

Tests the full MCP journal tools with real database integration
using Dishka dependency injection patterns.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from core_shared.models.journals import (
    EventDateRange,
    Journal,
    JournalContactRelationship,
    JournalContactRelationshipType,
)
from dishka import Provider, Scope, make_async_container, provide
from fastmcp import FastMCP
from fastmcp.client import Client
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.bushwalking_data_repository import (
    SqlBushwalkingDataRepository,
)
from app.core.journal.adapters.sql.fitness_data_repository import (
    SqlFitnessDataRepository,
)
from app.core.journal.adapters.sql.jogging_data_repository import (
    SqlJoggingDataRepository,
)
from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.journal.adapters.sql.outdoor_activity_data_repository import (
    SqlOutdoorActivityDataRepository,
)
from app.core.journal.services.journal_service import JournalService
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.mcp.domains.journals.tools import (
    _fetch_journal_types_and_data,
    register_journal_tools,
)
from tests.integration.mcp.http_helpers import (
    extract_mcp_json_payload,
    initialize_mcp_session,
    mcp_headers,
)


class JournalTestProvider(Provider):
    """Test provider for journal services with mocked dependencies."""

    def __init__(self, connection: AsyncConnection):
        super().__init__()
        self.connection = connection

    @provide(scope=Scope.REQUEST)
    def get_connection(self) -> AsyncConnection:
        return self.connection

    @provide(scope=Scope.REQUEST)
    def get_event_publisher(self, connection: AsyncConnection) -> OutboxEventPublisher:
        # Return a mock event publisher for testing
        mock_publisher = Mock(spec=OutboxEventPublisher)
        mock_publisher.publish = AsyncMock(return_value=None)
        return cast(OutboxEventPublisher, mock_publisher)

    @provide(scope=Scope.REQUEST)
    def get_journal_service(
        self, connection: AsyncConnection, event_publisher: OutboxEventPublisher
    ) -> JournalService:
        # Create JournalService using the same factory logic
        from app.core.journal.adapters.sql.journal_repository import (
            SqlJournalRepository,
        )

        # Create repositories
        journal_repository = SqlJournalRepository(connection)

        # Create and return journal service
        contact_relationship_repo = SqlJournalContactRelationshipRepository(connection)
        return JournalService(
            journal_repo=journal_repository,
            event_publisher=event_publisher,
            contact_relationship_repo=contact_relationship_repo,
        )


class TestJournalToolsIntegration:
    """Integration tests for MCP journal tools with real services."""

    @pytest_asyncio.fixture
    async def test_container(self, clean_database: AsyncConnection):
        """Create test container with mocked dependencies."""
        container = make_async_container(JournalTestProvider(clean_database))
        yield container
        await container.close()

    @pytest_asyncio.fixture
    async def journal_service(self, test_container):
        """Get journal service from test container."""
        async with test_container() as request_container:
            return await request_container.get(JournalService)

    @pytest_asyncio.fixture
    async def sample_journal_id(self, clean_database: AsyncConnection) -> int:
        """Create a sample journal for testing and return its ID."""
        from sqlalchemy import text

        now = datetime.now(UTC)
        query = text("""
            INSERT INTO journals (user_id, title, content, event_date_range_start, event_date_range_end)
            VALUES (:user_id, :title, :content, :start, :end)
            RETURNING id
        """)

        result = await clean_database.execute(
            query,
            {
                "user_id": "current_user",
                "title": "Test Journal",
                "content": "Test content for integration testing",
                "start": now,
                "end": now + timedelta(hours=1),
            },
        )
        row = result.fetchone()
        assert row is not None
        return int(row[0])

    @pytest.mark.asyncio
    async def test_mcp_server_tool_registration_integration(self):
        """Test that all journal tools are properly registered with the MCP server."""
        # Create MCP server and register tools
        mcp: FastMCP[None] = FastMCP("TestServer")
        register_journal_tools(mcp)

        # Use FastMCP Client to test tool registration
        async with Client(mcp) as client:
            # Get list of available tools
            tools = await client.list_tools()

            # Verify all expected tools are registered
            tool_names = [tool.name for tool in tools]
            expected_tools = [
                "create_journal_entry",
                "get_journal",
                "update_journal_entry",
                "delete_journal",
                "search_journals",
                "search_activities",
                "get_activity_stats",
                "analyze_activity_trends",
                "get_route_history",
                "link_journal_to_contact",
                "get_contact_journals",
                "merge_journals",
                "get_merge_candidates",
            ]

            for expected_tool in expected_tools:
                assert expected_tool in tool_names, (
                    f"Tool {expected_tool} not registered"
                )

            # Verify tool descriptions are present
            for tool in tools:
                assert tool.description is not None
                assert len(tool.description) > 0
                assert tool.inputSchema is not None

    @pytest.mark.asyncio
    async def test_create_journal_integration_real_db(
        self, journal_service: JournalService, clean_database: AsyncConnection
    ):
        """Test creating a journal entry with real database integration."""
        # Test creating a journal directly with the service
        now = datetime.now(UTC)

        # Create a test journal
        journal = Journal(
            user_id="current_user",
            title="Integration Test Journal",
            content="This is a test journal entry",
            event_date_range=EventDateRange(
                start=now,
                end=now + timedelta(hours=2),
            ),
        )

        # Save the journal
        saved_journal = await journal_service.create_journal(journal, clean_database)

        # Verify the journal was created
        assert saved_journal is not None
        assert saved_journal.id is not None
        assert saved_journal.title == "Integration Test Journal"
        assert saved_journal.content == "This is a test journal entry"
        assert saved_journal.user_id == "current_user"

    @pytest.mark.asyncio
    async def test_get_journal_integration_real_db(
        self, journal_service: JournalService, sample_journal_id: int
    ):
        """Test getting a journal entry with real database integration."""
        # Retrieve the journal
        retrieved_journal = await journal_service.get_journal(sample_journal_id)

        # Verify the journal was retrieved
        assert retrieved_journal is not None
        assert retrieved_journal.id == sample_journal_id
        assert retrieved_journal.title == "Test Journal"
        assert retrieved_journal.content == "Test content for integration testing"

    @pytest.mark.asyncio
    async def test_update_journal_integration_real_db(
        self,
        journal_service: JournalService,
        sample_journal_id: int,
        clean_database: AsyncConnection,
    ):
        """Test updating a journal entry with real database integration."""
        # Get the existing journal
        existing_journal = await journal_service.get_journal(sample_journal_id)
        assert existing_journal is not None

        # Update the journal fields
        existing_journal.title = "Updated Test Journal"
        existing_journal.content = "Updated content via integration test"

        # Track changed fields
        changed_fields = {
            "title": "Updated Test Journal",
            "content": "Updated content via integration test",
        }

        # Save the updated journal
        updated_journal = await journal_service.update_journal(
            existing_journal, changed_fields, clean_database
        )

        # Verify the journal was updated
        assert updated_journal is not None
        assert updated_journal.id == sample_journal_id
        assert updated_journal.title == "Updated Test Journal"
        assert updated_journal.content == "Updated content via integration test"

        # Retrieve the journal again to verify persistence
        retrieved_journal = await journal_service.get_journal(sample_journal_id)
        assert retrieved_journal is not None
        assert retrieved_journal.title == "Updated Test Journal"
        assert retrieved_journal.content == "Updated content via integration test"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("tool_name", "arguments"),
        [
            (
                "update_calendar",
                {"calendar_id": "not-a-uuid", "name": "Updated name"},
            ),
            ("delete_calendar", {"calendar_id": "not-a-uuid"}),
        ],
    )
    async def test_calendar_tools_invalid_uuid_use_validation_error_response(
        self,
        authenticated_lifespan_client,
        tool_name: str,
        arguments: dict[str, str],
    ) -> None:
        async with authenticated_lifespan_client() as authenticated_client:
            session_id = await initialize_mcp_session(authenticated_client)

            response = await authenticated_client.post(
                "/mcp-server/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments},
                },
                headers=mcp_headers(session_id),
            )

            assert response.status_code == 200
            payload = extract_mcp_json_payload(response.text)
            assert payload["error"] == "Validation error"
            assert payload["field"] == "Input"
            assert payload["message"] == (
                "Validation failed for Input: Invalid calendar_id 'not-a-uuid'. "
                "Must be a valid UUID."
            )

    @pytest.mark.asyncio
    async def test_delete_calendar_returns_conflict_payload_for_in_use_calendar(
        self, authenticated_lifespan_client
    ) -> None:
        async with authenticated_lifespan_client() as authenticated_client:
            session_id = await initialize_mcp_session(authenticated_client)

            calendar_response = await authenticated_client.post(
                "/api/calendars",
                json={
                    "data": {
                        "type": "calendars",
                        "attributes": {
                            "name": "Work Calendar",
                            "color": "#3B82F6",
                        },
                    }
                },
            )
            assert calendar_response.status_code == 201
            calendar_id = calendar_response.json()["data"]["id"]

            journal_response = await authenticated_client.post(
                "/api/journals",
                json={
                    "data": {
                        "type": "journals",
                        "attributes": {
                            "title": "Team Meeting",
                            "content": "Discuss Q1 goals",
                            "event_date_range": {
                                "start": "2024-01-15T00:00:00Z",
                                "end": "2024-01-15T00:00:00Z",
                            },
                            "types": ["EVENT"],
                            "type_data": {
                                "EVENT": {
                                    "calendar_id": calendar_id,
                                }
                            },
                        },
                    }
                },
            )
            assert journal_response.status_code == 201

            response = await authenticated_client.post(
                "/mcp-server/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "delete_calendar",
                        "arguments": {"calendar_id": calendar_id},
                    },
                },
                headers=mcp_headers(session_id),
            )

            assert response.status_code == 200
            payload = extract_mcp_json_payload(response.text)
            assert payload["error"] == "CONFLICT"
            assert payload["message"] == "Calendar is in use by 1 journal(s)"

    @pytest.mark.asyncio
    async def test_delete_journal_integration_real_db(
        self,
        journal_service: JournalService,
        sample_journal_id: int,
        clean_database: AsyncConnection,
    ):
        """Test deleting a journal entry with real database integration."""
        # Delete the journal
        await journal_service.delete_journal(sample_journal_id, clean_database)

        # Verify the journal was deleted
        deleted_journal = await journal_service.get_journal(sample_journal_id)
        assert deleted_journal is None

    @pytest.mark.asyncio
    async def test_link_journal_to_contact_integration_real_db(
        self,
        journal_service: JournalService,
        sample_journal_id: int,
        clean_database: AsyncConnection,
    ):
        """Test linking a journal to a contact with real database integration."""
        from sqlalchemy import text

        from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
            SqlJournalContactRelationshipRepository,
        )

        # Create a sample contact first
        contact_query = text("""
            INSERT INTO contacts (first_name, last_name)
            VALUES (:first_name, :last_name)
            RETURNING id
        """)

        contact_result = await clean_database.execute(
            contact_query,
            {
                "first_name": "Test",
                "last_name": "Contact",
            },
        )
        contact_row = contact_result.fetchone()
        assert contact_row is not None
        contact_id = int(contact_row[0])

        # Create a journal-contact relationship
        relationship_repo = SqlJournalContactRelationshipRepository(clean_database)
        relationship = JournalContactRelationship(
            journal_id=sample_journal_id,
            contact_id=contact_id,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
        )

        # Save the relationship using create method
        saved_relationship = await relationship_repo.create(relationship)

        # Verify the relationship was created
        assert saved_relationship is not None
        assert saved_relationship.journal_id == sample_journal_id
        assert saved_relationship.contact_id == contact_id
        assert (
            saved_relationship.relationship_type
            == JournalContactRelationshipType.PARTICIPANT
        )

    @pytest.mark.asyncio
    async def test_get_contact_journals_integration_real_db(
        self,
        journal_service: JournalService,
        sample_journal_id: int,
        clean_database: AsyncConnection,
    ):
        """Test getting journal relationships for a contact with real database integration."""
        from sqlalchemy import text

        from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
            SqlJournalContactRelationshipRepository,
        )

        # Create a sample contact first
        contact_query = text("""
            INSERT INTO contacts (first_name, last_name)
            VALUES (:first_name, :last_name)
            RETURNING id
        """)

        contact_result = await clean_database.execute(
            contact_query,
            {
                "first_name": "Test",
                "last_name": "Contact",
            },
        )
        contact_row = contact_result.fetchone()
        assert contact_row is not None
        contact_id = int(contact_row[0])

        # Create a journal-contact relationship
        relationship_repo = SqlJournalContactRelationshipRepository(clean_database)
        relationship = JournalContactRelationship(
            journal_id=sample_journal_id,
            contact_id=contact_id,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
        )

        # Save the relationship using create method
        await relationship_repo.create(relationship)

        # Get relationships for the contact
        relationships = await relationship_repo.get_by_contact(contact_id)

        # Verify the relationships were retrieved
        assert len(relationships) >= 1
        assert any(r.journal_id == sample_journal_id for r in relationships)

    @pytest.mark.asyncio
    async def test_create_journal_with_parent_id_integration(
        self, authenticated_lifespan_client, sample_journal_id: int
    ) -> None:
        async with authenticated_lifespan_client() as authenticated_client:
            session_id = await initialize_mcp_session(authenticated_client)

            response = await authenticated_client.post(
                "/mcp-server/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "create_journal_entry",
                        "arguments": {
                            "request": {
                                "title": "Child Journal",
                                "content": "This is a child journal",
                                "event_date_range": {
                                    "start": "2024-01-15T00:00:00Z",
                                    "end": "2024-01-15T01:00:00Z",
                                },
                                "parent_id": sample_journal_id,
                            }
                        },
                    },
                },
                headers=mcp_headers(session_id),
            )

            assert response.status_code == 200
            payload = extract_mcp_json_payload(response.text)

            assert "error" not in payload
            assert payload["title"] == "Child Journal"
            assert payload["parent"]["id"] == sample_journal_id

    @pytest.mark.asyncio
    async def test_update_journal_parent_id_integration(
        self, authenticated_lifespan_client, sample_journal_id: int
    ) -> None:
        # First create a child journal
        async with authenticated_lifespan_client() as authenticated_client:
            session_id = await initialize_mcp_session(authenticated_client)

            create_response = await authenticated_client.post(
                "/mcp-server/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "create_journal_entry",
                        "arguments": {
                            "request": {
                                "title": "Independent Journal",
                                "content": "Will be moved to under parent",
                                "event_date_range": {
                                    "start": "2024-01-15T00:00:00Z",
                                    "end": "2024-01-15T01:00:00Z",
                                },
                            }
                        },
                    },
                },
                headers=mcp_headers(session_id),
            )

            create_payload = extract_mcp_json_payload(create_response.text)
            child_id = create_payload["id"]

            # Now update the parent_id
            update_response = await authenticated_client.post(
                "/mcp-server/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "update_journal_entry",
                        "arguments": {
                            "journal_id": child_id,
                            "request": {"parent_id": sample_journal_id},
                        },
                    },
                },
                headers=mcp_headers(session_id),
            )

            assert update_response.status_code == 200
            update_payload = extract_mcp_json_payload(update_response.text)

            assert "error" not in update_payload
            assert update_payload["title"] == "Independent Journal"
            assert update_payload["parent"]["id"] == sample_journal_id

    @pytest.mark.asyncio
    async def test_update_journal_parent_id_cycle_rejected(
        self, authenticated_lifespan_client, sample_journal_id: int
    ) -> None:
        async with authenticated_lifespan_client() as authenticated_client:
            session_id = await initialize_mcp_session(authenticated_client)

            # Try to set the journal as its own parent
            response = await authenticated_client.post(
                "/mcp-server/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "update_journal_entry",
                        "arguments": {
                            "journal_id": sample_journal_id,
                            "request": {"parent_id": sample_journal_id},
                        },
                    },
                },
                headers=mcp_headers(session_id),
            )

            assert response.status_code == 200
            payload = extract_mcp_json_payload(response.text)

            # Since JournalCycleError maps to 400 Bad Request in API, it should map to Journal error in MCP
            assert payload["error"] == "Journal error"
            assert "would create a cycle" in payload["message"]

    @pytest.mark.asyncio
    async def test_get_daily_summary_integration(
        self, authenticated_lifespan_client, clean_database: AsyncConnection
    ) -> None:
        """Test retrieving a daily summary via MCP tool."""
        # Create a few journals for the day to make it eligible
        from sqlalchemy import text

        now = datetime.now(UTC)
        summary_date = now.date().isoformat()

        await clean_database.execute(
            text("""
                INSERT INTO journals (user_id, title, content, event_date_range_start, event_date_range_end)
                VALUES
                ('current_user', 'Journal 1', 'Content 1', :now, :now),
                ('current_user', 'Journal 2', 'Content 2', :now, :now)
            """),
            {"now": now},
        )

        async with authenticated_lifespan_client() as authenticated_client:
            from unittest.mock import AsyncMock, patch

            from core_shared.models.journals.daily_summary import (
                JournalDailySummary,
                SummaryStatus,
            )

            mock_summary = JournalDailySummary(
                user_id="current_user",
                summary_date=now.date(),
                summary_text="Mocked summary",
                journal_count=2,
                event_count=0,
                contact_count=0,
                status=SummaryStatus.GENERATED,
            )

            with patch(
                "app.core.journal.services.daily_summary_service.DailySummaryService.get_or_generate",
                new_callable=AsyncMock,
            ) as mock_get:
                mock_get.return_value = mock_summary
                session_id = await initialize_mcp_session(authenticated_client)

                response = await authenticated_client.post(
                    "/mcp-server/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {
                            "name": "get_daily_summary",
                            "arguments": {"summary_date": summary_date},
                        },
                    },
                    headers=mcp_headers(session_id),
                )

            assert response.status_code == 200
            payload = extract_mcp_json_payload(response.text)

            assert "error" not in payload
            assert payload["summary_date"] == summary_date
            assert payload["status"] == "generated"
            assert payload["journal_count"] == 2


class TestFetchJournalTypesAndDataNewActivityTypes:
    """
    Integration tests verifying _fetch_journal_types_and_data detects
    FITNESS, OUTDOOR_ACTIVITY, BUSHWALKING, JOGGING, ABSEILING_TRIP,
    CANYONING, CLIMBING, KAYAKING, and CROSS_COUNTRY_SKIING types.
    """

    @pytest_asyncio.fixture
    async def journal_id(self, clean_database: AsyncConnection) -> int:
        """Create a base journal and return its ID."""
        now = datetime.now(UTC)
        result = await clean_database.execute(
            text("""
                INSERT INTO journals
                    (user_id, title, content, event_date_range_start, event_date_range_end)
                VALUES (:user_id, :title, :content, :start, :end)
                RETURNING id
            """),
            {
                "user_id": "test_user",
                "title": "Activity Test Journal",
                "content": "Integration test content",
                "start": now,
                "end": now + timedelta(hours=1),
            },
        )
        row = result.fetchone()
        assert row is not None
        return int(row[0])

    async def _call_fetch(
        self, journal_id: int, conn: AsyncConnection
    ) -> tuple[list[str], dict[str, Any]]:
        """Helper: call _fetch_journal_types_and_data with all repos."""
        from app.core.journal.adapters.sql.abseiling_data_repository import (
            SqlAbseilingDataRepository,
        )
        from app.core.journal.adapters.sql.calendar_info_repository import (
            SqlCalendarInfoRepository,
        )
        from app.core.journal.adapters.sql.canyoning_data_repository import (
            SqlCanyoningDataRepository,
        )
        from app.core.journal.adapters.sql.caving_data_repository import (
            SqlCavingDataRepository,
        )
        from app.core.journal.adapters.sql.climbing_data_repository import (
            SqlClimbingDataRepository,
        )
        from app.core.journal.adapters.sql.cross_country_skiing_data_repository import (
            SqlCrossCountrySkiingDataRepository,
        )
        from app.core.journal.adapters.sql.kayaking_data_repository import (
            SqlKayakingDataRepository,
        )
        from app.core.journal.adapters.sql.mood_data_repository import (
            SqlMoodDataRepository,
        )
        from app.core.journal.adapters.sql.photo_album_data_repository import (
            SqlPhotoAlbumDataRepository,
        )
        from app.core.journal.adapters.sql.plan_data_repository import (
            SqlPlanDataRepository,
        )
        from app.core.journal.adapters.sql.travel_data_repository import (
            SqlTravelDataRepository,
        )

        return await _fetch_journal_types_and_data(
            journal_id,
            SqlCalendarInfoRepository(conn),
            SqlMoodDataRepository(conn),
            SqlPlanDataRepository(conn),
            SqlTravelDataRepository(conn),
            SqlPhotoAlbumDataRepository(conn),
            SqlFitnessDataRepository(conn),
            SqlOutdoorActivityDataRepository(conn),
            SqlBushwalkingDataRepository(conn),
            SqlJoggingDataRepository(conn),
            SqlAbseilingDataRepository(conn),
            SqlCanyoningDataRepository(conn),
            SqlCavingDataRepository(conn),
            SqlClimbingDataRepository(conn),
            SqlKayakingDataRepository(conn),
            SqlCrossCountrySkiingDataRepository(conn),
            None,  # type: ignore[arg-type] # gear_maintenance_data_repo
            None,  # type: ignore[arg-type] # gear_usage_data_repo
        )

    @pytest.mark.asyncio
    async def test_fetch_detects_fitness_type(
        self, journal_id: int, clean_database: AsyncConnection
    ) -> None:
        """FITNESS type is detected when journal_fitness_data row exists."""
        await clean_database.execute(
            text("""
                INSERT INTO journal_fitness_data (journal_id)
                VALUES (:journal_id)
            """),
            {"journal_id": journal_id},
        )

        types, type_data = await self._call_fetch(journal_id, clean_database)

        assert "fitness" in types
        assert "fitness" in type_data

    @pytest.mark.asyncio
    async def test_fetch_fitness_data_fields(
        self, journal_id: int, clean_database: AsyncConnection
    ) -> None:
        """FITNESS type_data contains expected fields."""
        await clean_database.execute(
            text("""
                INSERT INTO journal_fitness_data
                    (journal_id, heart_rate_avg, heart_rate_max, distance, duration, calories)
                VALUES (:journal_id, 145, 175, 10000, 3600, 550)
            """),
            {"journal_id": journal_id},
        )

        _, type_data = await self._call_fetch(journal_id, clean_database)

        fitness = type_data["fitness"]
        assert fitness["heart_rate_avg"] == 145
        assert fitness["heart_rate_max"] == 175
        assert fitness["distance"] == 10000
        assert fitness["duration"] == 3600
        assert fitness["calories"] == 550

    @pytest.mark.asyncio
    async def test_fetch_detects_outdoor_activity_type(
        self, journal_id: int, clean_database: AsyncConnection
    ) -> None:
        """OUTDOOR_ACTIVITY type is detected when journal_outdoor_activity_data row exists."""
        await clean_database.execute(
            text("""
                INSERT INTO journal_outdoor_activity_data
                    (journal_id, weather_conditions, role, in_leadership_role)
                VALUES (:journal_id, 'Sunny, 22°C', 'leader', true)
            """),
            {"journal_id": journal_id},
        )

        types, type_data = await self._call_fetch(journal_id, clean_database)

        assert "outdoor_activity" in types
        outdoor = type_data["outdoor_activity"]
        assert outdoor["weather_conditions"] == "Sunny, 22°C"
        assert outdoor["role"] == "leader"
        assert outdoor["in_leadership_role"] is True

    @pytest.mark.asyncio
    async def test_fetch_detects_bushwalking_type(
        self, journal_id: int, clean_database: AsyncConnection
    ) -> None:
        """BUSHWALKING type is detected when journal_bushwalking_data row exists."""
        await clean_database.execute(
            text("""
                INSERT INTO journal_bushwalking_data (journal_id, track_grading)
                VALUES (:journal_id, 'Grade 3')
            """),
            {"journal_id": journal_id},
        )

        types, type_data = await self._call_fetch(journal_id, clean_database)

        assert "bushwalking" in types
        bushwalking = type_data["bushwalking"]
        assert bushwalking["track_grading"] == "Grade 3"

    @pytest.mark.asyncio
    async def test_fetch_detects_jogging_type(
        self, journal_id: int, clean_database: AsyncConnection
    ) -> None:
        """JOGGING type is detected when journal_jogging_data row exists."""
        await clean_database.execute(
            text("""
                INSERT INTO journal_jogging_data (journal_id, pace)
                VALUES (:journal_id, 360)
            """),
            {"journal_id": journal_id},
        )

        types, type_data = await self._call_fetch(journal_id, clean_database)

        assert "jogging" in types
        jogging = type_data["jogging"]
        assert jogging["pace"] == 360

    @pytest.mark.asyncio
    async def test_fetch_detects_abseiling_trip_type(
        self, journal_id: int, clean_database: AsyncConnection
    ) -> None:
        """ABSEILING_TRIP type is detected when journal_abseiling_data row exists."""
        await clean_database.execute(
            text("""
                INSERT INTO journal_abseiling_data (journal_id, number_of_abseils, total_length)
                VALUES (:journal_id, 5, 120)
            """),
            {"journal_id": journal_id},
        )

        types, type_data = await self._call_fetch(journal_id, clean_database)

        assert "abseiling_trip" in types
        abseiling = type_data["abseiling_trip"]
        assert abseiling["number_of_abseils"] == 5
        assert abseiling["total_length"] == 120

    @pytest.mark.asyncio
    async def test_fetch_detects_canyoning_type(
        self, journal_id: int, clean_database: AsyncConnection
    ) -> None:
        """CANYONING type is detected when journal_canyoning_data row exists."""
        await clean_database.execute(
            text("""
                INSERT INTO journal_canyoning_data
                    (journal_id, french_grade, water_guage_name, water_guage_level,
                     is_vertical, is_night_canyon, is_white_water)
                VALUES (:journal_id, 'v3a2IV**', 'Slot Creek Gauge', 42,
                        true, false, true)
            """),
            {"journal_id": journal_id},
        )

        types, type_data = await self._call_fetch(journal_id, clean_database)

        assert "canyoning" in types
        canyoning = type_data["canyoning"]
        assert canyoning["french_grade"] == "v3a2IV**"
        assert canyoning["water_guage_name"] == "Slot Creek Gauge"
        assert canyoning["water_guage_level"] == 42
        assert canyoning["is_vertical"] is True
        assert canyoning["is_night_canyon"] is False
        assert canyoning["is_white_water"] is True

    @pytest.mark.asyncio
    async def test_fetch_detects_climbing_type(
        self, journal_id: int, clean_database: AsyncConnection
    ) -> None:
        """CLIMBING type is detected when journal_climbing_data row exists."""
        await clean_database.execute(
            text("""
                INSERT INTO journal_climbing_data (journal_id, climbing_type, grade, length)
                VALUES (:journal_id, 'sport', 18, 25)
            """),
            {"journal_id": journal_id},
        )

        types, type_data = await self._call_fetch(journal_id, clean_database)

        assert "climbing" in types
        climbing = type_data["climbing"]
        assert climbing["climbing_type"] == "sport"
        assert climbing["grade"] == 18
        assert climbing["length"] == 25

    @pytest.mark.asyncio
    async def test_fetch_detects_kayaking_type(
        self, journal_id: int, clean_database: AsyncConnection
    ) -> None:
        """KAYAKING type is detected when journal_kayaking_data row exists."""
        await clean_database.execute(
            text("""
                INSERT INTO journal_kayaking_data (journal_id, water_type)
                VALUES (:journal_id, 'river')
            """),
            {"journal_id": journal_id},
        )

        types, type_data = await self._call_fetch(journal_id, clean_database)

        assert "kayaking" in types
        kayaking = type_data["kayaking"]
        assert kayaking["water_type"] == "river"

    @pytest.mark.asyncio
    async def test_fetch_detects_cross_country_skiing_type(
        self, journal_id: int, clean_database: AsyncConnection
    ) -> None:
        """CROSS_COUNTRY_SKIING type is detected when journal_skiing_data row exists."""
        await clean_database.execute(
            text("""
                INSERT INTO journal_skiing_data (journal_id, snow_conditions)
                VALUES (:journal_id, 'packed powder')
            """),
            {"journal_id": journal_id},
        )

        types, type_data = await self._call_fetch(journal_id, clean_database)

        assert "cross_country_skiing" in types
        skiing = type_data["cross_country_skiing"]
        assert skiing["snow_conditions"] == "packed powder"

    @pytest.mark.asyncio
    async def test_journal_with_no_activity_data_is_note(
        self, journal_id: int, clean_database: AsyncConnection
    ) -> None:
        """A journal with no type-specific data is detected as NOTE."""
        types, type_data = await self._call_fetch(journal_id, clean_database)

        assert types == ["note"]
        assert type_data == {}


class TestActivityMcpToolsMountedIntegration:
    """Mounted MCP tests for activity search and analytics tools."""

    async def _call_tool(
        self,
        authenticated_client: Any,
        session_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        response = await authenticated_client.post(
            "/mcp-server/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            },
            headers=mcp_headers(session_id),
        )
        assert response.status_code == 200
        return extract_mcp_json_payload(response.text)

    async def _insert_journal(
        self,
        conn: AsyncConnection,
        *,
        title: str,
        content: str,
        start: datetime,
        user_id: str = "test-user-123",
    ) -> int:
        result = await conn.execute(
            text("""
                INSERT INTO journals
                    (user_id, title, content, event_date_range_start, event_date_range_end)
                VALUES (:user_id, :title, :content, :start, :end)
                RETURNING id
            """),
            {
                "user_id": user_id,
                "title": title,
                "content": content,
                "start": start,
                "end": start + timedelta(hours=2),
            },
        )
        row = result.fetchone()
        assert row is not None
        return int(row[0])

    async def _insert_route(
        self,
        conn: AsyncConnection,
        *,
        name: str,
        journal_id: int,
    ) -> str:
        result = await conn.execute(
            text("""
                INSERT INTO routes (journal_id, name, description)
                VALUES (:journal_id, :name, :description)
                RETURNING id
            """),
            {
                "journal_id": journal_id,
                "name": name,
                "description": f"Route for {name}",
            },
        )
        row = result.fetchone()
        assert row is not None
        return str(row[0])

    async def _insert_fitness_data(
        self,
        conn: AsyncConnection,
        *,
        journal_id: int,
        distance: int,
        elevation_gain: int,
        duration: int,
        calories: int,
    ) -> None:
        await conn.execute(
            text("""
                INSERT INTO journal_fitness_data (
                    journal_id, distance, elevation_gain, duration, calories
                )
                VALUES (
                    :journal_id, :distance, :elevation_gain, :duration, :calories
                )
            """),
            {
                "journal_id": journal_id,
                "distance": distance,
                "elevation_gain": elevation_gain,
                "duration": duration,
                "calories": calories,
            },
        )

    async def _insert_outdoor_activity_data(
        self,
        conn: AsyncConnection,
        *,
        journal_id: int,
    ) -> None:
        await conn.execute(
            text("""
                INSERT INTO journal_outdoor_activity_data (
                    journal_id, weather_conditions, role,
                    in_leadership_role, participant_notes
                )
                VALUES (
                    :journal_id, 'Clear', 'participant',
                    false, 'Test activity'
                )
            """),
            {"journal_id": journal_id},
        )

    async def _insert_kayaking_data(
        self,
        conn: AsyncConnection,
        *,
        journal_id: int,
        water_type: str = "river",
    ) -> None:
        await conn.execute(
            text("""
                INSERT INTO journal_kayaking_data (journal_id, water_type)
                VALUES (:journal_id, :water_type)
            """),
            {
                "journal_id": journal_id,
                "water_type": water_type,
            },
        )

    async def _insert_jogging_data(
        self,
        conn: AsyncConnection,
        *,
        journal_id: int,
        pace: int = 330,
    ) -> None:
        await conn.execute(
            text("""
                INSERT INTO journal_jogging_data (journal_id, pace)
                VALUES (:journal_id, :pace)
            """),
            {
                "journal_id": journal_id,
                "pace": pace,
            },
        )

    async def _insert_bushwalking_data(
        self,
        conn: AsyncConnection,
        *,
        journal_id: int,
        track_grading: str = "Grade 3",
    ) -> None:
        await conn.execute(
            text("""
                INSERT INTO journal_bushwalking_data (journal_id, track_grading)
                VALUES (:journal_id, :track_grading)
            """),
            {
                "journal_id": journal_id,
                "track_grading": track_grading,
            },
        )

    async def _insert_cross_country_skiing_data(
        self,
        conn: AsyncConnection,
        *,
        journal_id: int,
        snow_conditions: str = "packed powder",
    ) -> None:
        await conn.execute(
            text("""
                INSERT INTO journal_skiing_data (journal_id, snow_conditions)
                VALUES (:journal_id, :snow_conditions)
            """),
            {
                "journal_id": journal_id,
                "snow_conditions": snow_conditions,
            },
        )

    @pytest.mark.asyncio
    async def test_search_journals_applies_query_and_types_filters(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ) -> None:
        river_note_id = await self._insert_journal(
            clean_database,
            title="River reflections",
            content="A quiet river note",
            start=datetime(2024, 2, 1, tzinfo=UTC),
        )
        assert river_note_id > 0

        kayaking_journal_id = await self._insert_journal(
            clean_database,
            title="Harbour paddle",
            content="Strong river current and steady pace",
            start=datetime(2024, 2, 2, tzinfo=UTC),
        )
        await self._insert_fitness_data(
            clean_database,
            journal_id=kayaking_journal_id,
            distance=12000,
            elevation_gain=20,
            duration=4200,
            calories=700,
        )
        await self._insert_outdoor_activity_data(
            clean_database,
            journal_id=kayaking_journal_id,
        )
        await self._insert_kayaking_data(
            clean_database,
            journal_id=kayaking_journal_id,
            water_type="river",
        )

        jogging_journal_id = await self._insert_journal(
            clean_database,
            title="River run",
            content="Tempo effort along the river",
            start=datetime(2024, 2, 3, tzinfo=UTC),
        )
        await self._insert_fitness_data(
            clean_database,
            journal_id=jogging_journal_id,
            distance=8000,
            elevation_gain=110,
            duration=2400,
            calories=500,
        )
        await self._insert_jogging_data(clean_database, journal_id=jogging_journal_id)

        async with authenticated_lifespan_client() as authenticated_client:
            session_id = await initialize_mcp_session(authenticated_client)
            payload = await self._call_tool(
                authenticated_client,
                session_id,
                "search_journals",
                {"query": "river", "types": "kayaking", "limit": 10},
            )

        assert payload["query"] == "river"
        assert payload["total_hits"] == 1
        assert [result["title"] for result in payload["results"]] == ["Harbour paddle"]

    @pytest.mark.asyncio
    async def test_search_activities_filters_by_activity_type(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ) -> None:
        kayaking_journal_id = await self._insert_journal(
            clean_database,
            title="River paddle",
            content="Training lap",
            start=datetime(2024, 3, 1, tzinfo=UTC),
        )
        await self._insert_fitness_data(
            clean_database,
            journal_id=kayaking_journal_id,
            distance=10000,
            elevation_gain=15,
            duration=3600,
            calories=650,
        )
        await self._insert_outdoor_activity_data(
            clean_database,
            journal_id=kayaking_journal_id,
        )
        await self._insert_kayaking_data(clean_database, journal_id=kayaking_journal_id)

        jogging_journal_id = await self._insert_journal(
            clean_database,
            title="Morning run",
            content="Easy aerobic run",
            start=datetime(2024, 3, 2, tzinfo=UTC),
        )
        await self._insert_fitness_data(
            clean_database,
            journal_id=jogging_journal_id,
            distance=6000,
            elevation_gain=80,
            duration=1800,
            calories=400,
        )
        await self._insert_jogging_data(clean_database, journal_id=jogging_journal_id)

        async with authenticated_lifespan_client() as authenticated_client:
            session_id = await initialize_mcp_session(authenticated_client)
            payload = await self._call_tool(
                authenticated_client,
                session_id,
                "search_activities",
                {"activity_type": "kayaking", "limit": 10},
            )

        assert payload["total_hits"] == 1
        assert [result["title"] for result in payload["results"]] == ["River paddle"]

    @pytest.mark.asyncio
    async def test_search_activities_applies_overlapping_date_range_filters(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ) -> None:
        overlapping_journal_id = await self._insert_journal(
            clean_database,
            title="Midday run",
            content="Tempo block through lunch",
            start=datetime(2024, 3, 10, 10, 0, tzinfo=UTC),
        )
        await self._insert_fitness_data(
            clean_database,
            journal_id=overlapping_journal_id,
            distance=9000,
            elevation_gain=120,
            duration=2700,
            calories=580,
        )
        await self._insert_jogging_data(
            clean_database, journal_id=overlapping_journal_id
        )

        later_journal_id = await self._insert_journal(
            clean_database,
            title="Afternoon run",
            content="Later steady session",
            start=datetime(2024, 3, 10, 14, 0, tzinfo=UTC),
        )
        await self._insert_fitness_data(
            clean_database,
            journal_id=later_journal_id,
            distance=7000,
            elevation_gain=90,
            duration=2100,
            calories=460,
        )
        await self._insert_jogging_data(clean_database, journal_id=later_journal_id)

        async with authenticated_lifespan_client() as authenticated_client:
            session_id = await initialize_mcp_session(authenticated_client)
            payload = await self._call_tool(
                authenticated_client,
                session_id,
                "search_activities",
                {
                    "start_date": "2024-03-10T11:00:00Z",
                    "end_date": "2024-03-10T11:00:00Z",
                    "limit": 10,
                },
            )

        assert payload["total_hits"] == 1
        assert [result["title"] for result in payload["results"]] == ["Midday run"]

    @pytest.mark.asyncio
    async def test_search_activities_reports_total_hits_beyond_limited_results(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ) -> None:
        earlier_journal_id = await self._insert_journal(
            clean_database,
            title="Earlier run",
            content="Steady aerobic session",
            start=datetime(2024, 3, 8, 7, 0, tzinfo=UTC),
        )
        await self._insert_fitness_data(
            clean_database,
            journal_id=earlier_journal_id,
            distance=8000,
            elevation_gain=60,
            duration=2400,
            calories=500,
        )
        await self._insert_jogging_data(clean_database, journal_id=earlier_journal_id)

        later_journal_id = await self._insert_journal(
            clean_database,
            title="Later run",
            content="Progression finish",
            start=datetime(2024, 3, 9, 7, 0, tzinfo=UTC),
        )
        await self._insert_fitness_data(
            clean_database,
            journal_id=later_journal_id,
            distance=10000,
            elevation_gain=90,
            duration=3000,
            calories=620,
        )
        await self._insert_jogging_data(clean_database, journal_id=later_journal_id)

        async with authenticated_lifespan_client() as authenticated_client:
            session_id = await initialize_mcp_session(authenticated_client)
            payload = await self._call_tool(
                authenticated_client,
                session_id,
                "search_activities",
                {"activity_type": "jogging", "limit": 1},
            )

        assert payload["total_hits"] == 2
        assert [result["title"] for result in payload["results"]] == ["Later run"]

    @pytest.mark.asyncio
    async def test_get_activity_stats_returns_grouped_totals_and_personal_records(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ) -> None:
        long_run_id = await self._insert_journal(
            clean_database,
            title="Long run",
            content="Steady long effort",
            start=datetime(2024, 1, 10, tzinfo=UTC),
        )
        await self._insert_fitness_data(
            clean_database,
            journal_id=long_run_id,
            distance=18000,
            elevation_gain=220,
            duration=5400,
            calories=1100,
        )
        await self._insert_jogging_data(
            clean_database, journal_id=long_run_id, pace=300
        )

        recovery_run_id = await self._insert_journal(
            clean_database,
            title="Recovery run",
            content="Easy shakeout",
            start=datetime(2024, 1, 12, tzinfo=UTC),
        )
        await self._insert_fitness_data(
            clean_database,
            journal_id=recovery_run_id,
            distance=7000,
            elevation_gain=60,
            duration=2100,
            calories=450,
        )
        await self._insert_jogging_data(
            clean_database, journal_id=recovery_run_id, pace=360
        )

        paddle_id = await self._insert_journal(
            clean_database,
            title="Lake paddle",
            content="Flatwater technique session",
            start=datetime(2024, 1, 20, tzinfo=UTC),
        )
        await self._insert_fitness_data(
            clean_database,
            journal_id=paddle_id,
            distance=12000,
            elevation_gain=10,
            duration=4000,
            calories=700,
        )
        await self._insert_outdoor_activity_data(
            clean_database,
            journal_id=paddle_id,
        )
        await self._insert_kayaking_data(clean_database, journal_id=paddle_id)

        async with authenticated_lifespan_client() as authenticated_client:
            session_id = await initialize_mcp_session(authenticated_client)
            payload = await self._call_tool(
                authenticated_client,
                session_id,
                "get_activity_stats",
                {},
            )

        assert payload["total_activities"] == 3
        assert payload["overall_totals"]["distance"] == 37000
        assert payload["overall_totals"]["duration"] == 11500

        stats_by_type = {
            stat["activity_type"]: stat for stat in payload["activity_types"]
        }
        assert stats_by_type["jogging"]["count"] == 2
        assert stats_by_type["jogging"]["total_distance"] == 25000
        assert stats_by_type["kayaking"]["count"] == 1
        assert stats_by_type["kayaking"]["total_distance"] == 12000

        assert (
            payload["personal_records"]["longest_distance"]["journal_title"]
            == "Long run"
        )
        assert payload["personal_records"]["longest_distance"]["value"] == 18000

    @pytest.mark.asyncio
    async def test_get_journal_hierarchy_returns_tree(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ) -> None:
        """Verify the get_journal_hierarchy MCP tool returns a nested tree."""
        # Create root journal
        root_id = await self._insert_journal(
            clean_database,
            title="Root Trip",
            content="Main trip journal",
            start=datetime(2024, 6, 1, tzinfo=UTC),
        )
        assert root_id > 0

        # Create child journal
        child_id = await self._insert_journal(
            clean_database,
            title="Day 1",
            content="First day of trip",
            start=datetime(2024, 6, 1, tzinfo=UTC),
        )
        # Update parent_id of child
        from sqlalchemy import text

        await clean_database.execute(
            text("UPDATE journals SET parent_id = :parent_id WHERE id = :id"),
            {"parent_id": root_id, "id": child_id},
        )

        async with authenticated_lifespan_client() as authenticated_client:
            session_id = await initialize_mcp_session(authenticated_client)
            payload = await self._call_tool(
                authenticated_client,
                session_id,
                "get_journal_hierarchy",
                {"start_date": "2024-06-01"},
            )

        print("DEBUG PAYLOAD:", payload)
        assert "error" not in payload, (
            f"MCP tool returned error: {payload.get('message')}"
        )
        assert payload["total_nodes"] >= 2

        # Find the root node in the payload
        root_node = next(n for n in payload["nodes"] if n["id"] == root_id)
        assert root_node["title"] == "Root Trip"
        assert root_node["depth"] == 1
        assert root_node["children_count"] == 1
        assert len(root_node["children"]) == 1

        child_node = root_node["children"][0]
        assert child_node["id"] == child_id
        assert child_node["title"] == "Day 1"
        assert child_node["depth"] == 2
        assert child_node["children_count"] == 0
        assert len(child_node["children"]) == 0

    @pytest.mark.asyncio
    async def test_analyze_activity_trends_returns_monthly_frequency_buckets(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ) -> None:
        january_run_id = await self._insert_journal(
            clean_database,
            title="January run",
            content="Base run",
            start=datetime(2024, 1, 5, tzinfo=UTC),
        )
        await self._insert_fitness_data(
            clean_database,
            journal_id=january_run_id,
            distance=10000,
            elevation_gain=100,
            duration=3200,
            calories=650,
        )
        await self._insert_jogging_data(clean_database, journal_id=january_run_id)

        february_paddle_id = await self._insert_journal(
            clean_database,
            title="February paddle",
            content="Skills session",
            start=datetime(2024, 2, 8, tzinfo=UTC),
        )
        await self._insert_fitness_data(
            clean_database,
            journal_id=february_paddle_id,
            distance=14000,
            elevation_gain=20,
            duration=4300,
            calories=750,
        )
        await self._insert_outdoor_activity_data(
            clean_database,
            journal_id=february_paddle_id,
        )
        await self._insert_kayaking_data(clean_database, journal_id=february_paddle_id)

        february_ski_id = await self._insert_journal(
            clean_database,
            title="February ski",
            content="Snowy trails",
            start=datetime(2024, 2, 20, tzinfo=UTC),
        )
        await self._insert_fitness_data(
            clean_database,
            journal_id=february_ski_id,
            distance=9000,
            elevation_gain=180,
            duration=3900,
            calories=680,
        )
        await self._insert_outdoor_activity_data(
            clean_database,
            journal_id=february_ski_id,
        )
        await self._insert_bushwalking_data(clean_database, journal_id=february_ski_id)
        await self._insert_cross_country_skiing_data(
            clean_database,
            journal_id=february_ski_id,
        )

        async with authenticated_lifespan_client() as authenticated_client:
            session_id = await initialize_mcp_session(authenticated_client)
            payload = await self._call_tool(
                authenticated_client,
                session_id,
                "analyze_activity_trends",
                {"interval": "month"},
            )

        assert payload["interval"] == "month"
        assert payload["total_activities"] == 3

        periods = {period["period_start"]: period for period in payload["periods"]}
        assert periods["2024-01-01"]["activity_count"] == 1
        assert periods["2024-02-01"]["activity_count"] == 2
        assert periods["2024-02-01"]["total_distance"] == 23000

    @pytest.mark.asyncio
    async def test_get_route_history_returns_usage_stats_and_entries(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ) -> None:
        kayaking_journal_id = await self._insert_journal(
            clean_database,
            title="Harbour paddle",
            content="Route session by kayak",
            start=datetime(2024, 4, 1, tzinfo=UTC),
        )
        await self._insert_fitness_data(
            clean_database,
            journal_id=kayaking_journal_id,
            distance=11000,
            elevation_gain=10,
            duration=3800,
            calories=680,
        )
        await self._insert_outdoor_activity_data(
            clean_database,
            journal_id=kayaking_journal_id,
        )
        await self._insert_kayaking_data(
            clean_database,
            journal_id=kayaking_journal_id,
        )

        # Route belongs to the journal
        route_id = await self._insert_route(
            clean_database, name="Harbour Loop", journal_id=kayaking_journal_id
        )

        async with authenticated_lifespan_client() as authenticated_client:
            session_id = await initialize_mcp_session(authenticated_client)
            payload = await self._call_tool(
                authenticated_client,
                session_id,
                "get_route_history",
                {"route_id": route_id},
            )

        assert payload["route"]["id"] == route_id
        assert payload["route"]["name"] == "Harbour Loop"
        assert payload["usage_count"] == 1
        assert payload["activity_types"] == ["ROUTE"]
        assert [entry["journal_title"] for entry in payload["entries"]] == [
            "Harbour paddle",
        ]

    @pytest.mark.asyncio
    async def test_get_route_history_uses_route_matching_activity_type(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ) -> None:
        mixed_activity_journal_id = await self._insert_journal(
            clean_database,
            title="Brick workout",
            content="Run on one route, paddle on another",
            start=datetime(2024, 4, 5, tzinfo=UTC),
        )
        target_route_id = await self._insert_route(
            clean_database, name="River Run", journal_id=mixed_activity_journal_id
        )

        await self._insert_fitness_data(
            clean_database,
            journal_id=mixed_activity_journal_id,
            distance=15000,
            elevation_gain=150,
            duration=5400,
            calories=900,
        )
        await self._insert_jogging_data(
            clean_database,
            journal_id=mixed_activity_journal_id,
        )

        async with authenticated_lifespan_client() as authenticated_client:
            session_id = await initialize_mcp_session(authenticated_client)
            payload = await self._call_tool(
                authenticated_client,
                session_id,
                "get_route_history",
                {"route_id": target_route_id},
            )

        assert payload["usage_count"] == 1
        assert payload["activity_types"] == ["ROUTE"]
        assert payload["entries"][0]["journal_title"] == "Brick workout"
        assert payload["entries"][0]["activity_type"] == "ROUTE"


class TestMergeMcpToolsMountedIntegration:
    """Mounted MCP tests for merge tools."""

    async def _call_tool(
        self,
        authenticated_client: Any,
        session_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        response = await authenticated_client.post(
            "/mcp-server/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            },
            headers=mcp_headers(session_id),
        )
        assert response.status_code == 200
        return extract_mcp_json_payload(response.text)

    @pytest.mark.asyncio
    async def test_merge_journals_simple(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ) -> None:
        """Merge two simple journals via MCP — target absorbs source content."""
        async with authenticated_lifespan_client() as authenticated_client:
            # Create target journal via REST API
            target_response = await authenticated_client.post(
                "/api/journals",
                json={
                    "data": {
                        "type": "journals",
                        "attributes": {
                            "title": "Target Journal",
                            "content": "Target content",
                            "event_date_range": {
                                "start": "2024-06-01T00:00:00Z",
                                "end": "2024-06-01T23:59:59Z",
                            },
                        },
                    }
                },
            )
            assert target_response.status_code == 201
            target_id = int(target_response.json()["data"]["id"])

            # Create source journal via REST API
            source_response = await authenticated_client.post(
                "/api/journals",
                json={
                    "data": {
                        "type": "journals",
                        "attributes": {
                            "title": "Source Journal",
                            "content": "Source content",
                            "event_date_range": {
                                "start": "2024-06-01T00:00:00Z",
                                "end": "2024-06-01T23:59:59Z",
                            },
                        },
                    }
                },
            )
            assert source_response.status_code == 201
            source_id = int(source_response.json()["data"]["id"])

            # Merge via MCP
            session_id = await initialize_mcp_session(authenticated_client)
            import json

            payload = await self._call_tool(
                authenticated_client,
                session_id,
                "merge_journals",
                {
                    "target_journal_id": target_id,
                    "merge_data": json.dumps({"source_journal_id": source_id}),
                },
            )

        # Target should have combined content
        assert payload["id"] == target_id
        assert "Target content" in payload["content"]
        assert "Source content" in payload["content"]

    @pytest.mark.asyncio
    async def test_merge_journals_with_title_override(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ) -> None:
        """Merge with explicit title override via MCP."""
        async with authenticated_lifespan_client() as authenticated_client:
            target_response = await authenticated_client.post(
                "/api/journals",
                json={
                    "data": {
                        "type": "journals",
                        "attributes": {
                            "title": "Original Target Title",
                            "content": "Target body",
                            "event_date_range": {
                                "start": "2024-07-01T00:00:00Z",
                                "end": "2024-07-01T23:59:59Z",
                            },
                        },
                    }
                },
            )
            assert target_response.status_code == 201
            target_id = int(target_response.json()["data"]["id"])

            source_response = await authenticated_client.post(
                "/api/journals",
                json={
                    "data": {
                        "type": "journals",
                        "attributes": {
                            "title": "Source Title",
                            "content": "Source body",
                            "event_date_range": {
                                "start": "2024-07-01T00:00:00Z",
                                "end": "2024-07-01T23:59:59Z",
                            },
                        },
                    }
                },
            )
            assert source_response.status_code == 201
            source_id = int(source_response.json()["data"]["id"])

            session_id = await initialize_mcp_session(authenticated_client)
            import json

            payload = await self._call_tool(
                authenticated_client,
                session_id,
                "merge_journals",
                {
                    "target_journal_id": target_id,
                    "merge_data": json.dumps(
                        {
                            "source_journal_id": source_id,
                            "overrides": {"title": "Custom Merged Title"},
                        }
                    ),
                },
            )

        assert payload["id"] == target_id
        assert payload["title"] == "Custom Merged Title"

    @pytest.mark.asyncio
    async def test_merge_journals_self_merge_returns_error(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ) -> None:
        """Self-merge returns a domain error payload."""
        async with authenticated_lifespan_client() as authenticated_client:
            target_response = await authenticated_client.post(
                "/api/journals",
                json={
                    "data": {
                        "type": "journals",
                        "attributes": {
                            "title": "Self Merge",
                            "content": "Body",
                            "event_date_range": {
                                "start": "2024-08-01T00:00:00Z",
                                "end": "2024-08-01T23:59:59Z",
                            },
                        },
                    }
                },
            )
            assert target_response.status_code == 201
            journal_id = int(target_response.json()["data"]["id"])

            session_id = await initialize_mcp_session(authenticated_client)
            import json

            payload = await self._call_tool(
                authenticated_client,
                session_id,
                "merge_journals",
                {
                    "target_journal_id": journal_id,
                    "merge_data": json.dumps({"source_journal_id": journal_id}),
                },
            )

        assert "error" in payload
        assert (
            "merge" in payload["message"].lower()
            or "itself" in payload["message"].lower()
        )

    @pytest.mark.asyncio
    async def test_merge_journals_not_found_returns_error(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ) -> None:
        """Merging with a non-existent source returns not-found."""
        async with authenticated_lifespan_client() as authenticated_client:
            target_response = await authenticated_client.post(
                "/api/journals",
                json={
                    "data": {
                        "type": "journals",
                        "attributes": {
                            "title": "Existing",
                            "content": "Body",
                            "event_date_range": {
                                "start": "2024-09-01T00:00:00Z",
                                "end": "2024-09-01T23:59:59Z",
                            },
                        },
                    }
                },
            )
            assert target_response.status_code == 201
            target_id = int(target_response.json()["data"]["id"])

            session_id = await initialize_mcp_session(authenticated_client)
            import json

            payload = await self._call_tool(
                authenticated_client,
                session_id,
                "merge_journals",
                {
                    "target_journal_id": target_id,
                    "merge_data": json.dumps({"source_journal_id": 999999}),
                },
            )

        assert "error" in payload

    @pytest.mark.asyncio
    async def test_get_merge_candidates_returns_overlapping_journals(
        self,
        authenticated_lifespan_client,
        clean_database: AsyncConnection,
    ) -> None:
        """get_merge_candidates returns journals with overlapping date ranges."""
        async with authenticated_lifespan_client() as authenticated_client:
            # Create target journal
            target_response = await authenticated_client.post(
                "/api/journals",
                json={
                    "data": {
                        "type": "journals",
                        "attributes": {
                            "title": "Target for candidates",
                            "content": "Looking for candidates",
                            "event_date_range": {
                                "start": "2024-10-01T00:00:00Z",
                                "end": "2024-10-01T23:59:59Z",
                            },
                        },
                    }
                },
            )
            assert target_response.status_code == 201
            target_id = int(target_response.json()["data"]["id"])

            # Create overlapping journal
            overlap_response = await authenticated_client.post(
                "/api/journals",
                json={
                    "data": {
                        "type": "journals",
                        "attributes": {
                            "title": "Overlapping Journal",
                            "content": "Same day event",
                            "event_date_range": {
                                "start": "2024-10-01T10:00:00Z",
                                "end": "2024-10-01T12:00:00Z",
                            },
                        },
                    }
                },
            )
            assert overlap_response.status_code == 201
            overlap_id = int(overlap_response.json()["data"]["id"])

            # Create non-overlapping journal (different date)
            nonoverlap_response = await authenticated_client.post(
                "/api/journals",
                json={
                    "data": {
                        "type": "journals",
                        "attributes": {
                            "title": "Different Day",
                            "content": "Not a candidate",
                            "event_date_range": {
                                "start": "2024-12-01T00:00:00Z",
                                "end": "2024-12-01T23:59:59Z",
                            },
                        },
                    }
                },
            )
            assert nonoverlap_response.status_code == 201

            session_id = await initialize_mcp_session(authenticated_client)
            payload = await self._call_tool(
                authenticated_client,
                session_id,
                "get_merge_candidates",
                {"journal_id": target_id},
            )

        assert payload["target_journal_id"] == target_id
        assert payload["target_title"] == "Target for candidates"
        candidate_ids = [c["id"] for c in payload["candidates"]]
        assert overlap_id in candidate_ids
        assert len(payload["candidates"]) >= 1
        # Verify candidate has expected structure
        candidate = next(c for c in payload["candidates"] if c["id"] == overlap_id)
        assert candidate["title"] == "Overlapping Journal"
        assert "content_excerpt" in candidate
        assert "event_date_range" in candidate
        assert "summary" in candidate
