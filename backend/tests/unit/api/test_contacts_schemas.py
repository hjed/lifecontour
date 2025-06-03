"""
Unit tests for contacts API schemas and converters.

Tests the JSON API schema validation and conversion logic
for embedded contact methods and addresses.
"""

from datetime import datetime

from app.api.contacts.converters import (
    build_included_data,
    contact_address_to_json_api,
    contact_method_to_json_api,
    contact_to_json_api,
    json_api_to_contact,
)
from app.api.contacts.schemas import (
    ContactAddressAttributes,
    ContactAddressData,
    ContactAttributes,
    ContactData,
    ContactDataRequest,
    ContactListResponse,
    ContactMethodAttributes,
    ContactMethodData,
    ContactRelationshipsRequest,
    ContactRequest,
    ContactResponse,
)
from app.core.contacts.models.entities import (
    Contact,
    ContactAddress,
    ContactMethod,
    MethodType,
)


class TestContactSchemas:
    """Test contact JSON API schemas."""

    def test_contact_attributes_schema(self):
        """Test ContactAttributes schema validation."""
        attrs = ContactAttributes(
            first_name="John",
            last_name="Doe",
            middle_name="William",
            nick_name="Johnny",
            full_name="John William Doe",
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 2),
        )

        assert attrs.first_name == "John"
        assert attrs.last_name == "Doe"
        assert attrs.middle_name == "William"
        assert attrs.nick_name == "Johnny"
        assert attrs.full_name == "John William Doe"

    def test_contact_method_attributes_schema(self):
        """Test ContactMethodAttributes schema validation."""
        attrs = ContactMethodAttributes(
            method_type=MethodType.EMAIL,
            value="john@example.com",
            label="Work",
            is_primary=True,
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 2),
        )

        assert attrs.method_type == MethodType.EMAIL
        assert attrs.value == "john@example.com"
        assert attrs.label == "Work"
        assert attrs.is_primary is True

    def test_contact_address_attributes_schema(self):
        """Test ContactAddressAttributes schema validation."""
        attrs = ContactAddressAttributes(
            label="Home",
            street_line_1="123 Main St",
            street_line_2="Apt 4B",
            locality="Anytown",
            region="CA",
            postal_code="12345",
            country_code="US",
            is_primary=True,
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 2),
        )

        assert attrs.label == "Home"
        assert attrs.street_line_1 == "123 Main St"
        assert attrs.street_line_2 == "Apt 4B"
        assert attrs.locality == "Anytown"
        assert attrs.region == "CA"
        assert attrs.postal_code == "12345"
        assert attrs.country_code == "US"
        assert attrs.is_primary is True

    def test_contact_request_with_embedded_data(self):
        """Test ContactRequest schema with embedded methods and addresses."""
        # Create method data
        method_attrs = ContactMethodAttributes(
            method_type=MethodType.EMAIL,
            value="john@example.com",
            is_primary=True,
        )
        method_data = ContactMethodData(attributes=method_attrs)

        # Create address data
        address_attrs = ContactAddressAttributes(
            street_line_1="123 Main St",
            country_code="US",
            is_primary=True,
        )
        address_data = ContactAddressData(attributes=address_attrs)

        # Create relationships
        relationships = ContactRelationshipsRequest(
            methods=[method_data],
            addresses=[address_data],
        )

        # Create contact data
        contact_attrs = ContactAttributes(
            first_name="John",
            last_name="Doe",
        )
        contact_data = ContactDataRequest(
            attributes=contact_attrs,
            relationships=relationships,
        )

        # Create request
        request = ContactRequest(data=contact_data)

        # Verify structure
        assert request.data.type == "contact"
        assert request.data.attributes.first_name == "John"
        assert request.data.attributes.last_name == "Doe"
        assert len(request.data.relationships.methods) == 1
        assert len(request.data.relationships.addresses) == 1
        assert request.data.relationships.methods[0].attributes.method_type == MethodType.EMAIL
        assert request.data.relationships.addresses[0].attributes.street_line_1 == "123 Main St"

    def test_contact_response_with_included_data(self):
        """Test ContactResponse schema with included data."""
        # Create main contact data
        contact_attrs = ContactAttributes(
            first_name="John",
            last_name="Doe",
            full_name="John Doe",
        )
        contact_data = ContactData(
            id="1",
            attributes=contact_attrs,
        )

        # Create included method data
        method_attrs = ContactMethodAttributes(
            method_type=MethodType.EMAIL,
            value="john@example.com",
            is_primary=True,
        )
        method_data = ContactMethodData(
            id="1",
            attributes=method_attrs,
        )

        # Create included address data
        address_attrs = ContactAddressAttributes(
            street_line_1="123 Main St",
            country_code="US",
            is_primary=True,
        )
        address_data = ContactAddressData(
            id="1",
            attributes=address_attrs,
        )

        # Create response
        response = ContactResponse(
            data=contact_data,
            included=[method_data, address_data],
        )

        # Verify structure
        assert response.data.type == "contact"
        assert response.data.id == "1"
        assert response.data.attributes.first_name == "John"
        assert len(response.included) == 2
        assert response.included[0].type == "contact_method"
        assert response.included[1].type == "contact_address"

    def test_contact_list_response(self):
        """Test ContactListResponse schema."""
        # Create contact data
        contact_attrs = ContactAttributes(
            first_name="John",
            last_name="Doe",
            full_name="John Doe",
        )
        contact_data = ContactData(
            id="1",
            attributes=contact_attrs,
        )

        # Create list response
        response = ContactListResponse(
            data=[contact_data],
        )

        # Verify structure
        assert len(response.data) == 1
        assert response.data[0].type == "contact"
        assert response.data[0].id == "1"


class TestContactConverters:
    """Test contact JSON API converters."""

    def test_contact_to_json_api_basic(self):
        """Test converting basic contact to JSON API format."""
        contact = Contact(
            id=1,
            first_name="John",
            last_name="Doe",
            middle_name="William",
            nick_name="Johnny",
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 2),
        )

        json_data = contact_to_json_api(contact)

        assert json_data.type == "contact"
        assert json_data.id == "1"
        assert json_data.attributes.first_name == "John"
        assert json_data.attributes.last_name == "Doe"
        assert json_data.attributes.middle_name == "William"
        assert json_data.attributes.nick_name == "Johnny"
        assert json_data.attributes.full_name == "John William Doe"
        assert json_data.attributes.created_at == datetime(2024, 1, 1)
        assert json_data.attributes.updated_at == datetime(2024, 1, 2)

    def test_contact_to_json_api_with_relationships(self):
        """Test converting contact with methods and addresses to JSON API format."""
        # Create contact with methods and addresses
        method = ContactMethod(
            id=1,
            method_type=MethodType.EMAIL,
            value="john@example.com",
            contact_id=1,
            is_primary=True,
            label="Work",
        )

        address = ContactAddress(
            id=1,
            street_line_1="123 Main St",
            country_code="US",
            contact_id=1,
            is_primary=True,
            label="Home",
        )

        contact = Contact(
            id=1,
            first_name="John",
            last_name="Doe",
            methods=[method],
            addresses=[address],
        )

        json_data = contact_to_json_api(contact, include_relationships=True)

        assert json_data.type == "contact"
        assert json_data.id == "1"
        assert json_data.relationships is not None

    def test_json_api_to_contact_basic(self):
        """Test converting JSON API format to contact entity."""
        attrs = ContactAttributes(
            first_name="Jane",
            last_name="Smith",
            middle_name="Marie",
            nick_name="Janie",
        )

        json_data = ContactDataRequest(
            id="2",
            attributes=attrs,
        )

        contact = json_api_to_contact(json_data)

        assert contact.id == 2
        assert contact.first_name == "Jane"
        assert contact.last_name == "Smith"
        assert contact.middle_name == "Marie"
        assert contact.nick_name == "Janie"

    def test_json_api_to_contact_with_embedded_data(self):
        """Test converting JSON API with embedded data to contact entity."""
        # Create method data
        method_attrs = ContactMethodAttributes(
            method_type=MethodType.EMAIL,
            value="jane@example.com",
            is_primary=True,
        )
        method_data = ContactMethodData(attributes=method_attrs)

        # Create address data
        address_attrs = ContactAddressAttributes(
            street_line_1="456 Oak St",
            country_code="US",
            is_primary=True,
        )
        address_data = ContactAddressData(attributes=address_attrs)

        # Create relationships
        relationships = ContactRelationshipsRequest(
            methods=[method_data],
            addresses=[address_data],
        )

        # Create contact data
        contact_attrs = ContactAttributes(
            first_name="Jane",
            last_name="Smith",
        )
        contact_data = ContactDataRequest(
            attributes=contact_attrs,
            relationships=relationships,
        )

        contact = json_api_to_contact(contact_data)

        assert contact.first_name == "Jane"
        assert contact.last_name == "Smith"
        assert len(contact.methods) == 1
        assert contact.methods[0].method_type == MethodType.EMAIL
        assert contact.methods[0].value == "jane@example.com"
        assert len(contact.addresses) == 1
        assert contact.addresses[0].street_line_1 == "456 Oak St"

    def test_contact_method_to_json_api(self):
        """Test converting contact method to JSON API format."""
        method = ContactMethod(
            id=1,
            method_type=MethodType.PHONE,
            value="+1-555-123-4567",
            contact_id=1,
            is_primary=False,
            label="Mobile",
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 2),
        )

        json_data = contact_method_to_json_api(method)

        assert json_data.type == "contact_method"
        assert json_data.id == "1"
        assert json_data.attributes.method_type == MethodType.PHONE
        assert json_data.attributes.value == "+1-555-123-4567"
        assert json_data.attributes.is_primary is False
        assert json_data.attributes.label == "Mobile"

    def test_contact_address_to_json_api(self):
        """Test converting contact address to JSON API format."""
        address = ContactAddress(
            id=1,
            street_line_1="789 Pine St",
            street_line_2="Unit 5",
            locality="Somewhere",
            region="TX",
            postal_code="67890",
            country_code="US",
            contact_id=1,
            is_primary=True,
            label="Work",
            created_at=datetime(2024, 1, 1),
            updated_at=datetime(2024, 1, 2),
        )

        json_data = contact_address_to_json_api(address)

        assert json_data.type == "contact_address"
        assert json_data.id == "1"
        assert json_data.attributes.street_line_1 == "789 Pine St"
        assert json_data.attributes.street_line_2 == "Unit 5"
        assert json_data.attributes.locality == "Somewhere"
        assert json_data.attributes.region == "TX"
        assert json_data.attributes.postal_code == "67890"
        assert json_data.attributes.country_code == "US"
        assert json_data.attributes.is_primary is True
        assert json_data.attributes.label == "Work"

    def test_build_included_data(self):
        """Test building included data from contact entity."""
        # Create contact with methods and addresses
        method = ContactMethod(
            id=1,
            method_type=MethodType.EMAIL,
            value="test@example.com",
            contact_id=1,
        )

        address = ContactAddress(
            id=1,
            street_line_1="123 Test St",
            country_code="US",
            contact_id=1,
        )

        contact = Contact(
            id=1,
            first_name="Test",
            last_name="User",
            methods=[method],
            addresses=[address],
        )

        included_data = build_included_data(contact)

        assert len(included_data) == 2

        # Find method and address in included data
        method_data = next(item for item in included_data if item.type == "contact_method")
        address_data = next(item for item in included_data if item.type == "contact_address")

        assert method_data.attributes.method_type == MethodType.EMAIL
        assert method_data.attributes.value == "test@example.com"
        assert address_data.attributes.street_line_1 == "123 Test St"
        assert address_data.attributes.country_code == "US"
