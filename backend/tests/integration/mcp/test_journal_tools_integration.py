"""
Integration tests for MCP journal tools.

Tests the full MCP journal tools with real database integration
using Dishka dependency injection patterns.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import Mock

import pytest
import pytest_asyncio
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
from app.core.journal.adapters.sql.outdoor_activity_data_repository import (
    SqlOutdoorActivityDataRepository,
)
from app.core.journal.models.entities import Journal
from app.core.journal.models.journal_contact_relationship import (
    JournalContactRelationship,
)
from app.core.journal.models.journal_relationship_types import (
    JournalContactRelationshipType,
)
from app.core.journal.models.value_objects import EventDateRange
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
        from unittest.mock import AsyncMock

        mock_publisher = Mock(spec=OutboxEventPublisher)
        mock_publisher.publish = AsyncMock(return_value=None)
        return mock_publisher

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
        return JournalService(
            journal_repo=journal_repository,
            event_publisher=event_publisher,
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
                "link_journal_to_contact",
                "get_contact_journals",
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


class TestFetchJournalTypesAndDataNewActivityTypes:
    """
    Integration tests verifying _fetch_journal_types_and_data detects
    FITNESS, OUTDOOR_ACTIVITY, BUSHWALKING, JOGGING, ABSEILING_TRIP,
    CANYONING, and CLIMBING types.
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
        from app.core.journal.adapters.sql.climbing_data_repository import (
            SqlClimbingDataRepository,
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
            SqlClimbingDataRepository(conn),
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

        types, type_data = await self._call_fetch(journal_id, clean_database)

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
                    (journal_id, activity_type, weather_conditions, role, in_leadership_role)
                VALUES (:journal_id, 'Hiking', 'Sunny, 22°C', 'leader', true)
            """),
            {"journal_id": journal_id},
        )

        types, type_data = await self._call_fetch(journal_id, clean_database)

        assert "outdoor_activity" in types
        outdoor = type_data["outdoor_activity"]
        assert outdoor["activity_type"] == "Hiking"
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
        assert bushwalking["route_id"] is None

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
        assert canyoning["route_id"] is None

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
        assert climbing["route_id"] is None

    @pytest.mark.asyncio
    async def test_journal_with_no_activity_data_is_note(
        self, journal_id: int, clean_database: AsyncConnection
    ) -> None:
        """A journal with no type-specific data is detected as NOTE."""
        types, type_data = await self._call_fetch(journal_id, clean_database)

        assert types == ["note"]
        assert type_data == {}
