"""Unit tests for journal MCP converters."""

from datetime import UTC, datetime
from uuid import UUID

from app.core.contacts.models.entities import Contact
from app.core.journal.models.calendar import Calendar
from app.core.journal.models.entities import Journal
from app.core.journal.models.journal_contact_relationship import (
    JournalContactRelationship,
)
from app.core.journal.models.journal_relationship_types import (
    JournalContactRelationshipType,
)
from app.core.journal.models.journal_tag import JournalTag
from app.core.journal.models.value_objects import EventDateRange
from app.mcp.domains.journals.converters import JournalConverter


class TestJournalConverter:
    """Test JournalConverter class."""

    def test_to_journal_response_basic(self) -> None:
        """Test converting a basic journal to response format."""
        # Arrange
        start_date = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        end_date = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)
        journal = Journal(
            id=123,
            user_id="user-123",
            title="Test Journal",
            content="This is test content",
            event_date_range=EventDateRange(start=start_date, end=end_date),
        )

        # Act
        response = JournalConverter.to_journal_response(
            journal=journal,
            types=["NOTE"],
            type_data={},
            contacts=[],
            tags=[],
            calendar=None,
        )

        # Assert
        assert response.id == "123"
        assert response.title == "Test Journal"
        assert response.content == "This is test content"
        assert response.types == ["NOTE"]
        assert response.contacts == []
        assert response.tags == []
        assert response.calendar is None
        assert "Test Journal" in response.summary

    def test_to_journal_response_with_contacts(self) -> None:
        """Test converting a journal with contacts to response format."""
        # Arrange
        start_date = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        end_date = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)
        journal = Journal(
            id=123,
            user_id="user-123",
            title="Meeting Notes",
            content="Discussed project timeline",
            event_date_range=EventDateRange(start=start_date, end=end_date),
        )

        contact = Contact(
            id=456,
            first_name="John",
            last_name="Doe",
        )

        relationship = JournalContactRelationship(
            journal_id=123,
            contact_id=456,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
        )

        # Act
        response = JournalConverter.to_journal_response(
            journal=journal,
            types=["EVENT", "NOTE"],
            type_data={},
            contacts=[(relationship, contact)],
            tags=[],
            calendar=None,
        )

        # Assert
        assert len(response.contacts) == 1
        assert response.contacts[0].contact_id == "456"
        assert response.contacts[0].contact_name == "John Doe"
        assert response.contacts[0].relationship_type == "PARTICIPANT"
        assert "John Doe" in response.summary

    def test_to_journal_response_with_tags(self) -> None:
        """Test converting a journal with tags to response format."""
        # Arrange
        start_date = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        end_date = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)
        journal = Journal(
            id=123,
            user_id="user-123",
            title="Work Meeting",
            content="Q4 planning",
            event_date_range=EventDateRange(start=start_date, end=end_date),
        )

        tag_id = UUID("12345678-1234-5678-1234-567812345789")
        tag = JournalTag(id=tag_id, name="work", color="#FF5733")

        # Act
        response = JournalConverter.to_journal_response(
            journal=journal,
            types=["EVENT"],
            type_data={},
            contacts=[],
            tags=[tag],
            calendar=None,
        )

        # Assert
        assert len(response.tags) == 1
        assert response.tags[0].tag_id == str(tag_id)
        assert response.tags[0].tag_name == "work"
        assert response.tags[0].tag_color == "#FF5733"
        assert "work" in response.summary

    def test_to_journal_response_with_calendar(self) -> None:
        """Test converting a journal with calendar info to response format."""
        # Arrange
        start_date = datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)
        end_date = datetime(2024, 1, 15, 15, 0, 0, tzinfo=UTC)
        journal = Journal(
            id=123,
            user_id="user-123",
            title="Team Standup",
            content="Daily sync",
            event_date_range=EventDateRange(start=start_date, end=end_date),
        )

        calendar_id = UUID("12345678-1234-5678-1234-567812345678")
        calendar = Calendar(
            id=calendar_id,
            user_id="user-123",
            name="Work Calendar",
            color="#FF5733",
        )

        type_data = {
            "EVENT": {
                "calendar_id": str(calendar_id),
                "start_time": start_date.isoformat(),
                "end_time": end_date.isoformat(),
                "is_all_day": False,
                "location": "Conference Room A",
            }
        }

        # Act
        response = JournalConverter.to_journal_response(
            journal=journal,
            types=["EVENT"],
            type_data=type_data,
            contacts=[],
            tags=[],
            calendar=calendar,
        )

        # Assert
        assert response.calendar is not None
        assert response.calendar.calendar_id == str(calendar_id)
        assert response.calendar.calendar_name == "Work Calendar"
        assert response.calendar.location == "Conference Room A"
        assert response.calendar.is_all_day is False
