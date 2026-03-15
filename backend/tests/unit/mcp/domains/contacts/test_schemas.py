"""
Unit tests for contact domain MCP schemas.

Tests the AI-friendly data formats and validation for contact MCP tools.
"""

import pytest
from pydantic import ValidationError

from app.mcp.domains.contacts.schemas import ContactResponse


class TestContactResponse:
    """Test ContactResponse schema for AI-friendly contact data."""

    def test_contact_response_basic_fields(self):
        """Test basic contact response fields."""
        contact_data = {
            "id": "contact-123",
            "name": "John Doe",
            "email": "john@example.com",
            "phone": "+1234567890",
            "tags": ["friend", "work"],
            "summary": "John is a software engineer and close friend.",
        }

        response = ContactResponse(
            id=str(contact_data["id"]),
            name=str(contact_data["name"]),
            email=str(contact_data["email"]),
            phone=str(contact_data["phone"]),
            tags=list(contact_data["tags"]),
            summary=str(contact_data["summary"]),
        )

        assert response.id == "contact-123"
        assert response.name == "John Doe"
        assert response.email == "john@example.com"
        assert response.phone == "+1234567890"
        assert response.tags == ["friend", "work"]
        assert response.is_favourite is False  # Default value
        assert response.summary == "John is a software engineer and close friend."

    def test_contact_response_optional_fields(self):
        """Test contact response with optional fields."""
        contact_data = {
            "id": "contact-456",
            "name": "Jane Smith",
            "summary": "Jane is a colleague from the marketing department.",
        }

        response = ContactResponse(
            id=str(contact_data["id"]),
            name=str(contact_data["name"]),
            summary=str(contact_data["summary"]),
        )

        assert response.id == "contact-456"
        assert response.name == "Jane Smith"
        assert response.email is None
        assert response.phone is None
        assert not response.tags
        assert response.summary == "Jane is a colleague from the marketing department."

    def test_contact_response_empty_tags(self):
        """Test contact response with empty tags list."""
        contact_data = {
            "id": "contact-789",
            "name": "Bob Wilson",
            "tags": [],
            "summary": "Bob is a new contact with no tags yet.",
        }

        response = ContactResponse(
            id=str(contact_data["id"]),
            name=str(contact_data["name"]),
            tags=list(contact_data["tags"]),
            summary=str(contact_data["summary"]),
        )

        assert not response.tags

    def test_contact_response_validation_required_fields(self):
        """Test validation behavior for required fields."""
        # Test that required fields must be provided (but can be empty strings)
        # This tests the Pydantic model validation, not business logic validation

        # These should work (empty strings are valid)
        response1 = ContactResponse(id="", name="John Doe", summary="test")
        assert response1.id == ""

        response2 = ContactResponse(id="contact-123", name="", summary="test")
        assert response2.name == ""

        response3 = ContactResponse(id="contact-123", name="John Doe", summary="")
        assert response3.summary == ""

        # These should fail (missing required fields entirely)
        with pytest.raises(ValidationError):
            ContactResponse(name="John Doe", summary="test")  # type: ignore[call-arg]

        with pytest.raises(ValidationError):
            ContactResponse(id="contact-123", summary="test")  # type: ignore[call-arg]

        with pytest.raises(ValidationError):
            ContactResponse(id="contact-123", name="John Doe")  # type: ignore[call-arg]

    def test_contact_response_json_serialization(self):
        """Test contact response can be serialized to JSON."""
        contact_data = {
            "id": "contact-123",
            "name": "John Doe",
            "email": "john@example.com",
            "phone": "+1234567890",
            "tags": ["friend", "work"],
            "summary": "John is a software engineer and close friend.",
        }

        response = ContactResponse(
            id=str(contact_data["id"]),
            name=str(contact_data["name"]),
            email=str(contact_data["email"]),
            phone=str(contact_data["phone"]),
            tags=list(contact_data["tags"]),
            summary=str(contact_data["summary"]),
        )
        json_data = response.model_dump()

        assert json_data["id"] == "contact-123"
        assert json_data["name"] == "John Doe"
        assert json_data["email"] == "john@example.com"
        assert json_data["phone"] == "+1234567890"
        assert json_data["tags"] == ["friend", "work"]
        assert json_data["summary"] == "John is a software engineer and close friend."

    def test_contact_response_with_is_favourite_true(self):
        """Test contact response with is_favourite set to true."""
        contact_data = {
            "id": "contact-123",
            "name": "John Doe",
            "email": "john@example.com",
            "is_favourite": True,
            "summary": "John is a favourite contact.",
        }

        response = ContactResponse(
            id=str(contact_data["id"]),
            name=str(contact_data["name"]),
            email=str(contact_data["email"]),
            is_favourite=bool(contact_data["is_favourite"]),
            summary=str(contact_data["summary"]),
        )

        assert response.id == "contact-123"
        assert response.name == "John Doe"
        assert response.email == "john@example.com"
        assert response.is_favourite is True
        assert response.summary == "John is a favourite contact."

    def test_contact_response_with_is_favourite_false(self):
        """Test contact response with is_favourite set to false."""
        contact_data = {
            "id": "contact-456",
            "name": "Jane Smith",
            "is_favourite": False,
            "summary": "Jane is not a favourite contact.",
        }

        response = ContactResponse(
            id=str(contact_data["id"]),
            name=str(contact_data["name"]),
            is_favourite=bool(contact_data["is_favourite"]),
            summary=str(contact_data["summary"]),
        )

        assert response.id == "contact-456"
        assert response.name == "Jane Smith"
        assert response.is_favourite is False
        assert response.summary == "Jane is not a favourite contact."

    def test_contact_response_is_favourite_default_false(self):
        """Test that is_favourite defaults to False when not provided."""
        contact_data = {
            "id": "contact-789",
            "name": "Bob Wilson",
            "summary": "Bob is a contact with default favourite status.",
        }

        response = ContactResponse(
            id=str(contact_data["id"]),
            name=str(contact_data["name"]),
            summary=str(contact_data["summary"]),
        )

        assert response.is_favourite is False

    def test_contact_response_json_serialization_with_is_favourite(self):
        """Test contact response JSON serialization includes is_favourite field."""
        contact_data = {
            "id": "contact-123",
            "name": "John Doe",
            "email": "john@example.com",
            "phone": "+1234567890",
            "tags": ["friend", "work"],
            "is_favourite": True,
            "summary": "John is a favourite software engineer and close friend.",
        }

        response = ContactResponse(
            id=str(contact_data["id"]),
            name=str(contact_data["name"]),
            email=str(contact_data["email"]),
            phone=str(contact_data["phone"]),
            tags=contact_data["tags"],  # type: ignore[arg-type]
            is_favourite=bool(contact_data["is_favourite"]),
            summary=str(contact_data["summary"]),
        )
        json_data = response.model_dump()

        assert json_data["id"] == "contact-123"
        assert json_data["name"] == "John Doe"
        assert json_data["email"] == "john@example.com"
        assert json_data["phone"] == "+1234567890"
        assert json_data["tags"] == ["friend", "work"]
        assert json_data["is_favourite"] is True
        assert (
            json_data["summary"]
            == "John is a favourite software engineer and close friend."
        )
