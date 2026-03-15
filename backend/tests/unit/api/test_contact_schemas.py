"""Unit tests for contact API schemas."""

import pytest
from pydantic import ValidationError

from app.api.contacts.schemas import (
    ContactAddressAttributes,
    ContactAttributes,
    ContactCreateData,
    ContactCreateRequest,
    ContactMethodAttributes,
    ContactResource,
    ContactUpdateData,
    ContactUpdateRequest,
    TagAssignmentData,
    TagAssignmentRequest,
)


class TestContactMethodAttributes:
    """Test ContactMethodAttributes schema."""

    def test_valid_email_method(self):
        """Test valid email method attributes."""
        attrs = ContactMethodAttributes(
            method_type="email",
            value="test@example.com",
            label="Work",
            is_primary=True,
        )
        assert attrs.method_type == "email"
        assert attrs.value == "test@example.com"
        assert attrs.label == "Work"
        assert attrs.is_primary is True

    def test_valid_phone_method(self):
        """Test valid phone method attributes."""
        attrs = ContactMethodAttributes(
            method_type="phone",
            value="+1234567890",
            is_primary=False,
        )
        assert attrs.method_type == "phone"
        assert attrs.value == "+1234567890"
        assert attrs.label is None
        assert attrs.is_primary is False

    def test_missing_required_fields(self):
        """Test validation error for missing required fields."""
        with pytest.raises(ValidationError) as exc_info:
            ContactMethodAttributes()  # type: ignore

        errors = exc_info.value.errors()
        required_fields = {error["loc"][0] for error in errors}
        assert "method_type" in required_fields
        assert "value" in required_fields


class TestContactAddressAttributes:
    """Test ContactAddressAttributes schema."""

    def test_valid_address(self):
        """Test valid address attributes."""
        attrs = ContactAddressAttributes(
            label="Home",
            street_line_1="123 Main St",
            street_line_2="Apt 4B",
            locality="Sydney",
            region="NSW",
            postal_code="2000",
            country_code="AU",
            is_primary=True,
        )
        assert attrs.label == "Home"
        assert attrs.street_line_1 == "123 Main St"
        assert attrs.street_line_2 == "Apt 4B"
        assert attrs.locality == "Sydney"
        assert attrs.region == "NSW"
        assert attrs.postal_code == "2000"
        assert attrs.country_code == "AU"
        assert attrs.is_primary is True

    def test_minimal_address(self):
        """Test minimal valid address."""
        attrs = ContactAddressAttributes(
            street_line_1="123 Main St",
            country_code="AU",
        )
        assert attrs.street_line_1 == "123 Main St"
        assert attrs.country_code == "AU"
        assert attrs.label is None
        assert attrs.is_primary is False

    def test_missing_required_fields(self):
        """Test validation error for missing required fields."""
        with pytest.raises(ValidationError) as exc_info:
            ContactAddressAttributes()  # type: ignore

        errors = exc_info.value.errors()
        required_fields = {error["loc"][0] for error in errors}
        assert "street_line_1" in required_fields
        assert "country_code" in required_fields


class TestContactAttributes:
    """Test ContactAttributes schema."""

    def test_valid_contact_attributes(self):
        """Test valid contact attributes."""
        attrs = ContactAttributes(
            first_name="John",
            last_name="Doe",
            middle_name="William",
            nick_name="Johnny",
        )
        assert attrs.first_name == "John"
        assert attrs.last_name == "Doe"
        assert attrs.middle_name == "William"
        assert attrs.nick_name == "Johnny"
        assert attrs.contact_methods == []
        assert not attrs.addresses
        assert not attrs.notes

    def test_minimal_contact_attributes(self):
        """Test minimal valid contact attributes."""
        attrs = ContactAttributes(first_name="John")
        assert attrs.first_name == "John"
        assert attrs.last_name is None

    def test_missing_first_name(self):
        """Test validation error for missing first name."""
        with pytest.raises(ValidationError) as exc_info:
            ContactAttributes()  # type: ignore

        errors = exc_info.value.errors()
        assert any(error["loc"][0] == "first_name" for error in errors)


class TestContactResource:
    """Test ContactResource schema."""

    def test_valid_contact_resource(self):
        """Test valid contact resource."""
        attrs = ContactAttributes(first_name="John", last_name="Doe")
        resource = ContactResource(
            id="1",
            attributes=attrs,
        )
        assert resource.type == "contacts"
        assert resource.id == "1"
        assert resource.attributes.first_name == "John"
        assert resource.attributes.last_name == "Doe"


class TestContactCreateRequest:
    """Test ContactCreateRequest schema."""

    def test_valid_create_request(self):
        """Test valid contact create request."""
        attrs = ContactAttributes(first_name="John", last_name="Doe")
        data = ContactCreateData(attributes=attrs)
        request = ContactCreateRequest(data=data)

        assert request.data.type == "contacts"
        assert request.data.attributes.first_name == "John"
        assert request.data.attributes.last_name == "Doe"


class TestContactUpdateRequest:
    """Test ContactUpdateRequest schema."""

    def test_valid_update_request(self):
        """Test valid contact update request."""
        attrs = ContactAttributes(first_name="John", last_name="Smith")
        data = ContactUpdateData(id="1", attributes=attrs)
        request = ContactUpdateRequest(data=data)

        assert request.data.type == "contacts"
        assert request.data.id == "1"
        assert request.data.attributes.first_name == "John"
        assert request.data.attributes.last_name == "Smith"


class TestTagAssignmentRequest:
    """Test TagAssignmentRequest schema."""

    def test_valid_tag_assignment(self):
        """Test valid tag assignment request."""
        data = TagAssignmentData(id="1")
        request = TagAssignmentRequest(data=data)

        assert request.data.type == "tags"
        assert request.data.id == "1"

    def test_missing_tag_id(self):
        """Test validation error for missing tag ID."""
        with pytest.raises(ValidationError) as exc_info:
            TagAssignmentData()  # type: ignore

        errors = exc_info.value.errors()
        assert any(error["loc"][0] == "id" for error in errors)
