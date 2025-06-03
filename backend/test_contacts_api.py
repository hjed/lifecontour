"""
Simple test to verify the contacts API implementation.

This test verifies that our JSON API schemas and converters work correctly
without requiring a full server setup.
"""

from datetime import datetime

from app.api.contacts.converters import (
    contact_to_json_api,
    json_api_to_contact,
)
from app.api.contacts.schemas import (
    ContactAttributes,
    ContactData,
    ContactRequest,
    ContactResponse,
)
from app.core.contacts.models.entities import Contact


def test_contact_to_json_api_conversion():
    """Test converting a Contact domain entity to JSON API format."""
    # Create a test contact
    contact = Contact(
        id=1,
        first_name="John",
        last_name="Doe",
        middle_name="William",
        nick_name="Johnny",
        methods=[],
        addresses=[],
        notes=[],
        tags=[],
        created_at=datetime(2024, 1, 1, 12, 0, 0),
        updated_at=datetime(2024, 1, 2, 12, 0, 0),
    )

    # Convert to JSON API format
    json_data = contact_to_json_api(contact)

    # Verify the conversion
    assert json_data.type == "contact"
    assert json_data.id == "1"
    assert json_data.attributes.first_name == "John"
    assert json_data.attributes.last_name == "Doe"
    assert json_data.attributes.middle_name == "William"
    assert json_data.attributes.nick_name == "Johnny"
    assert json_data.attributes.full_name == "John William Doe"
    assert json_data.attributes.created_at == datetime(2024, 1, 1, 12, 0, 0)
    assert json_data.attributes.updated_at == datetime(2024, 1, 2, 12, 0, 0)


def test_json_api_to_contact_conversion():
    """Test converting JSON API format to a Contact domain entity."""
    # Create test JSON API data
    attributes = ContactAttributes(
        first_name="Jane",
        last_name="Smith",
        middle_name="Marie",
        nick_name="Janie",
        full_name="Jane Marie Smith",  # This will be ignored in conversion
        created_at=datetime(2024, 1, 1, 12, 0, 0),
        updated_at=datetime(2024, 1, 2, 12, 0, 0),
    )

    json_data = ContactData(
        id="2",
        attributes=attributes,
    )

    # Convert to domain entity
    contact = json_api_to_contact(json_data)

    # Verify the conversion
    assert contact.id == 2
    assert contact.first_name == "Jane"
    assert contact.last_name == "Smith"
    assert contact.middle_name == "Marie"
    assert contact.nick_name == "Janie"
    assert contact.methods == []
    assert contact.addresses == []
    assert contact.notes == []
    assert contact.tags == []


def test_contact_request_schema():
    """Test that ContactRequest schema works correctly."""
    from app.api.contacts.schemas import ContactDataRequest

    # Create test data
    attributes = ContactAttributes(
        first_name="Bob",
        last_name="Johnson",
        middle_name=None,
        nick_name=None,
    )

    data = ContactDataRequest(
        attributes=attributes,
    )

    request = ContactRequest(data=data)

    # Verify the schema
    assert request.data.type == "contact"
    assert request.data.attributes.first_name == "Bob"
    assert request.data.attributes.last_name == "Johnson"
    assert request.data.attributes.middle_name is None
    assert request.data.attributes.nick_name is None


def test_contact_response_schema():
    """Test that ContactResponse schema works correctly."""
    # Create test data
    attributes = ContactAttributes(
        first_name="Alice",
        last_name="Brown",
        full_name="Alice Brown",
    )

    data = ContactData(
        id="3",
        attributes=attributes,
    )

    response = ContactResponse(data=data)

    # Verify the schema
    assert response.data.type == "contact"
    assert response.data.id == "3"
    assert response.data.attributes.first_name == "Alice"
    assert response.data.attributes.last_name == "Brown"
    assert response.data.attributes.full_name == "Alice Brown"


def test_round_trip_conversion():
    """Test converting from domain entity to JSON API and back."""
    # Create original contact
    original = Contact(
        id=5,
        first_name="Charlie",
        last_name="Wilson",
        middle_name="Edward",
        nick_name="Chuck",
        methods=[],
        addresses=[],
        notes=[],
        tags=[],
    )

    # Convert to JSON API and back
    json_data = contact_to_json_api(original)
    converted = json_api_to_contact(json_data)

    # Verify the round trip
    assert converted.id == original.id
    assert converted.first_name == original.first_name
    assert converted.last_name == original.last_name
    assert converted.middle_name == original.middle_name
    assert converted.nick_name == original.nick_name


def test_search_api_schemas() -> None:
    """Test that search API schemas work correctly."""
    from app.api.common.schemas import JsonApiLinks
    from app.api.search.schemas import ContactSearchResponse, SearchMeta

    # Create test search metadata
    meta = SearchMeta(
        query="test query",
        total_count=10,
        current_page=1,
        processing_time_ms=25,
        facets={"tags": {"work": 5, "personal": 3}},
        available_tags=["work", "personal", "family"],
    )

    # Create test search response
    response = ContactSearchResponse(
        data=[],  # Empty for this test
        meta=meta,
        links=JsonApiLinks(
            self="/api/search/contacts?q=test&limit=20&offset=0",
            next="/api/search/contacts?q=test&limit=20&offset=20",
        ),
    )

    # Verify the schema
    assert response.meta.query == "test query"
    assert response.meta.total_count == 10
    assert response.meta.processing_time_ms == 25
    assert response.links is not None
    assert response.links.self == "/api/search/contacts?q=test&limit=20&offset=0"


def test_contact_with_nested_data() -> None:
    """Test creating a contact with nested methods and addresses."""
    from app.api.contacts.converters import json_api_to_contact
    from app.api.contacts.schemas import (
        ContactAddressAttributes,
        ContactAddressData,
        ContactAttributes,
        ContactDataRequest,
        ContactMethodAttributes,
        ContactMethodData,
        ContactRelationshipsRequest,
    )
    from app.core.contacts.models.entities import MethodType

    # Create contact with nested method and address
    method_attrs = ContactMethodAttributes(
        method_type=MethodType.EMAIL,
        value="john@example.com",
        label="Work",
        is_primary=True,
    )
    method_data = ContactMethodData(attributes=method_attrs)

    address_attrs = ContactAddressAttributes(
        label="Home",
        street_line_1="123 Main St",
        locality="Anytown",
        region="CA",
        postal_code="12345",
        country_code="US",
        is_primary=True,
    )
    address_data = ContactAddressData(attributes=address_attrs)

    relationships = ContactRelationshipsRequest(
        methods=[method_data],
        addresses=[address_data],
    )

    contact_attrs = ContactAttributes(
        first_name="John",
        last_name="Doe",
        middle_name="William",
    )

    contact_data = ContactDataRequest(
        attributes=contact_attrs,
        relationships=relationships,
    )

    # Convert to domain entity
    contact = json_api_to_contact(contact_data)

    # Verify the conversion
    assert contact.first_name == "John"
    assert contact.last_name == "Doe"
    assert contact.middle_name == "William"
    assert len(contact.methods) == 1
    assert contact.methods[0].method_type == MethodType.EMAIL
    assert contact.methods[0].value == "john@example.com"
    assert contact.methods[0].is_primary is True
    assert len(contact.addresses) == 1
    assert contact.addresses[0].street_line_1 == "123 Main St"
    assert contact.addresses[0].country_code == "US"
    assert contact.addresses[0].is_primary is True


def test_change_detection() -> None:
    """Test that the service can detect changes between contacts."""
    from app.core.contacts.services.contact_service import ContactService

    # Create service instance (we'll just test the change detection method)
    service = ContactService(None, None, None, None, None, None)  # type: ignore

    # Create two contacts with differences
    old_contact = Contact(
        id=1,
        first_name="John",
        last_name="Smith",
        middle_name=None,
        nick_name=None,
        methods=[],
        addresses=[],
        notes=[],
        tags=[],
    )

    new_contact = Contact(
        id=1,
        first_name="John",
        last_name="Doe",  # Changed
        middle_name="William",  # Added
        nick_name="Johnny",  # Added
        methods=[],
        addresses=[],
        notes=[],
        tags=[],
    )

    # Test change detection
    changes = service._calculate_changed_fields(old_contact, new_contact)

    # Verify detected changes
    assert "last_name" in changes
    assert changes["last_name"] == ("Smith", "Doe")
    assert "middle_name" in changes
    assert changes["middle_name"] == (None, "William")
    assert "nick_name" in changes
    assert changes["nick_name"] == (None, "Johnny")
    assert "first_name" not in changes  # Unchanged


if __name__ == "__main__":
    # Run the tests
    test_contact_to_json_api_conversion()
    test_json_api_to_contact_conversion()
    test_contact_request_schema()
    test_contact_response_schema()
    test_round_trip_conversion()
    test_search_api_schemas()
    test_contact_with_nested_data()
    test_change_detection()
    print("All tests passed!")
