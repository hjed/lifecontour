"""Unit tests for journal contact relationship schemas and converters."""

import typing

from core_shared.models.journals.attendee_status import AttendeeStatus
from core_shared.models.journals.contact_event_role import ContactEventRole
from core_shared.models.journals.journal_contact_relationship import (
    JournalContactRelationship,
)
from core_shared.models.journals.journal_relationship_types import (
    JournalContactRelationshipType,
)

from app.api.journals.converters import JournalConverter
from app.api.journals.schemas import (
    JournalContactRelationshipAddAttributes,
    JournalContactRelationshipSchema,
)
from app.mcp.domains.journals.schemas import (
    ContactRelationshipSchema as MCPContactRelationshipSchema,
)
from app.mcp.domains.journals.schemas import (
    ContactRelationshipSummary,
)


class TestJournalContactRelationshipSchema:
    def test_schema_with_status_and_role(self):
        """Test schema serialization with status and role."""
        data = {
            "id": "123",
            "name": "Test User",
            "relationship_type": "PARTICIPANT",
            "status": "ATTENDING",
            "role": "ORGANISER",
        }

        schema = JournalContactRelationshipSchema(**data)

        assert schema.id == "123"
        assert schema.name == "Test User"
        assert schema.relationship_type == "PARTICIPANT"
        assert schema.status == "ATTENDING"
        assert schema.role == "ORGANISER"

    def test_schema_without_status_and_role(self):
        """Test schema serialization without status and role (backward compatibility)."""
        data = {
            "id": "123",
            "name": "Test User",
            "relationship_type": "PARTICIPANT",
        }

        schema = JournalContactRelationshipSchema(**data)

        assert schema.id == "123"
        assert schema.name == "Test User"
        assert schema.relationship_type == "PARTICIPANT"
        assert schema.status is None
        assert schema.role is None


class TestJournalContactRelationshipAddAttributes:
    def test_add_attributes_with_status_and_role(self):
        """Test adding contact with status and role."""
        data = {
            "contact_id": "123",
            "relationship_type": "PARTICIPANT",
            "status": "ATTENDING",
            "role": "ORGANISER",
        }

        schema = JournalContactRelationshipAddAttributes(**data)

        assert schema.contact_id == "123"
        assert schema.relationship_type == "PARTICIPANT"
        assert schema.status == "ATTENDING"
        assert schema.role == "ORGANISER"

    def test_add_attributes_without_status_and_role(self):
        """Test adding contact without status and role."""
        data = {
            "contact_id": "123",
            "relationship_type": "PARTICIPANT",
        }

        schema = JournalContactRelationshipAddAttributes(**data)

        assert schema.contact_id == "123"
        assert schema.relationship_type == "PARTICIPANT"
        assert schema.status is None
        assert schema.role is None


class TestJournalConverterContacts:
    def test_convert_contacts_with_status_role(self):
        """Test that converter correctly maps status and role from domain entities."""
        rel1 = JournalContactRelationship(
            journal_id=1,
            contact_id=101,
            relationship_type=JournalContactRelationshipType.PARTICIPANT,
            status=AttendeeStatus.ATTENDING,
            role=ContactEventRole.ORGANISER,
        )

        converted = JournalConverter._convert_contacts([rel1])
        assert len(converted) == 1
        result_schema = converted[0]

        # Name is populated differently so setting it directly here for completeness
        result_schema.name = "Alice"

        assert result_schema.id == "101"
        assert result_schema.name == "Alice"
        assert result_schema.relationship_type == "PARTICIPANT"
        assert result_schema.status == "ATTENDING"
        assert result_schema.role == "ORGANISER"


class TestMCPContactRelationshipSchema:
    def test_mcp_schema_with_status_and_role(self):
        """Test MCP schema serialization with status and role."""
        data: dict[str, typing.Any] = {
            "id": 123,
            "name": "Test User",
            "relationship_type": "PARTICIPANT",
            "status": "ATTENDING",
            "role": "ORGANISER",
        }

        schema = MCPContactRelationshipSchema(**data)

        assert schema.id == 123
        assert schema.name == "Test User"
        assert schema.relationship_type == "PARTICIPANT"
        assert schema.status == "ATTENDING"
        assert schema.role == "ORGANISER"

    def test_mcp_contact_relationship_schema_has_status_and_role(self):
        """Verify the MCP schema has status and role fields."""

        # Replace data dict definition with correct keys:
        valid_data: dict[str, typing.Any] = {
            "id": 1,
            "name": "Test Contact",
            "relationship_type": "PARTICIPANT",
            "status": "ATTENDING",
            "role": "ORGANISER",
        }
        schema = MCPContactRelationshipSchema(**valid_data)

        assert schema.status == "ATTENDING"
        assert schema.role == "ORGANISER"


class TestContactRelationshipSummary:
    def test_summary_dataclass(self):
        """Test ContactRelationshipSummary correctly handles the input data."""
        summary = ContactRelationshipSummary(
            id=123,
            name="Bob",
            relationship_type="PARTICIPANT",
            status="MAYBE",
            role="FACILITATOR_HELPER",
        )

        assert summary.id == 123
        assert summary.name == "Bob"
        assert summary.relationship_type == "PARTICIPANT"
        assert summary.status == "MAYBE"
        assert summary.role == "FACILITATOR_HELPER"
