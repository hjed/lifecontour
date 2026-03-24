"""Unit tests for contact API converters."""

from datetime import UTC, datetime

from core_shared.models.contacts.entities import (
    Contact,
    ContactAddress,
    ContactMethod,
    ContactNote,
    ContactRelationship,
    MethodType,
    RelationshipType,
    Tag,
)
from core_shared.models.contacts.value_objects import TagName

from app.api.contacts.converters import (
    ContactConverter,
    ContactRequestConverter,
    TagConverter,
)
from app.api.contacts.schemas import (
    ContactAddressAttributes,
    ContactAddressResource,
    ContactAttributes,
    ContactCreateData,
    ContactMethodAttributes,
    ContactMethodResource,
    ContactNoteAttributes,
    ContactNoteResource,
)


class TestContactConverter:
    """Test ContactConverter methods."""

    def test_to_method_resource(self):
        """Test converting ContactMethod to API resource."""
        method = ContactMethod(
            id=1,
            contact_id=1,
            method_type=MethodType.EMAIL,
            value="test@example.com",
            label="Work",
            is_primary=True,
        )

        resource = ContactConverter.to_method_resource(method)

        assert resource.id == 1
        assert resource.attributes.method_type == "email"
        assert resource.attributes.value == "test@example.com"
        assert resource.attributes.label == "Work"
        assert resource.attributes.is_primary is True

    def test_to_address_resource(self):
        """Test converting ContactAddress to API resource."""
        address = ContactAddress(
            id=1,
            contact_id=1,
            label="Home",
            street_line_1="123 Main St",
            street_line_2="Apt 4B",
            locality="Sydney",
            region="NSW",
            postal_code="2000",
            country_code="AU",
            is_primary=True,
        )

        resource = ContactConverter.to_address_resource(address)

        assert resource.id == 1
        assert resource.attributes.label == "Home"
        assert resource.attributes.street_line_1 == "123 Main St"
        assert resource.attributes.street_line_2 == "Apt 4B"
        assert resource.attributes.locality == "Sydney"
        assert resource.attributes.region == "NSW"
        assert resource.attributes.postal_code == "2000"
        assert resource.attributes.country_code == "AU"
        assert resource.attributes.is_primary is True

    def test_to_note_resource(self):
        """Test converting ContactNote to API resource."""
        now = datetime.now(UTC)
        note = ContactNote(
            id=1,
            contact_id=1,
            content="Test note",
            created_at=now,
            updated_at=now,
        )

        resource = ContactConverter.to_note_resource(note)

        assert resource.id == 1
        assert resource.attributes.content == "Test note"
        assert resource.attributes.created_at == now
        assert resource.attributes.updated_at == now

    def test_to_resource_minimal_contact(self):
        """Test converting minimal Contact to API resource."""
        contact = Contact(
            id=1,
            first_name="John",
        )

        resource = ContactConverter.to_resource(contact)

        assert resource.type == "contacts"
        assert resource.id == "1"
        assert resource.attributes.first_name == "John"
        assert resource.attributes.last_name is None
        assert resource.attributes.is_favourite is False  # Default value
        assert resource.attributes.contact_methods == []
        assert resource.attributes.addresses == []
        assert resource.attributes.notes == []
        assert resource.relationships is None

    def test_to_resource_full_contact(self):
        """Test converting full Contact to API resource."""
        # Create contact with methods, addresses, notes, and tags
        method = ContactMethod(
            id=1,
            contact_id=1,
            method_type=MethodType.EMAIL,
            value="test@example.com",
            is_primary=True,
        )
        address = ContactAddress(
            id=1,
            contact_id=1,
            street_line_1="123 Main St",
            country_code="AU",
            is_primary=True,
        )
        note = ContactNote(id=1, contact_id=1, content="Test note")
        tag = Tag(id=1, name=TagName("work"))

        contact = Contact(
            id=1,
            first_name="John",
            last_name="Doe",
            is_favourite=True,  # Test with favourite contact
            methods=[method],
            addresses=[address],
            notes=[note],
            tags=[tag],
        )

        resource = ContactConverter.to_resource(contact, "http://localhost:8000")

        assert resource.type == "contacts"
        assert resource.id == "1"
        assert resource.attributes.first_name == "John"
        assert resource.attributes.last_name == "Doe"
        assert resource.attributes.is_favourite is True  # Test favourite contact
        assert len(resource.attributes.contact_methods) == 1
        assert len(resource.attributes.addresses) == 1
        assert len(resource.attributes.notes) == 1
        assert resource.relationships is not None
        assert resource.relationships.tags is not None
        # Verify tag relationships include full attributes (not just type/id)
        tag_data = resource.relationships.tags["data"]
        assert len(tag_data) == 1
        assert tag_data[0]["type"] == "tags"
        assert tag_data[0]["id"] == "1"
        assert tag_data[0]["attributes"]["name"] == "work"
        assert "color" not in tag_data[0]["attributes"]  # None values excluded
        assert resource.links is not None
        assert resource.links.self == "http://localhost:8000/api/contacts/1"

    def test_to_resource_with_relationships(self):
        """Test converting contact with relationships to API resource."""
        contact = Contact(
            id=1,
            first_name="John",
            last_name="Doe",
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
            updated_at=datetime(2024, 1, 2, tzinfo=UTC),
        )

        # Add a relationship
        relationship = ContactRelationship(
            id=1,
            from_contact_id=1,
            to_contact_id=2,
            relationship_type=RelationshipType.FRIEND,
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        if contact.relationships is None:
            contact.relationships = []
        contact.relationships.append(relationship)

        resource = ContactConverter.to_resource(contact, "http://example.com")

        assert resource.id == "1"
        assert resource.attributes.first_name == "John"
        assert resource.attributes.last_name == "Doe"
        assert len(resource.attributes.relationships) == 1
        assert resource.attributes.relationships[0].id == "1"
        assert (
            resource.attributes.relationships[0].attributes.relationship_type
            == "friend"
        )
        assert resource.attributes.relationships[0].attributes.from_contact_id == 1
        assert resource.attributes.relationships[0].attributes.to_contact_id == 2


class TestTagConverter:
    """Test TagConverter methods."""

    def test_to_resource(self):
        """Test converting Tag to API resource."""
        tag = Tag(
            id=1,
            name=TagName("work"),
            color="#FF0000",
            description="Work related contacts",
        )

        resource = TagConverter.to_resource(tag, "http://localhost:8000")

        assert resource.type == "tags"
        assert resource.id == "1"
        assert resource.attributes.name == "work"
        assert resource.attributes.color == "#FF0000"
        assert resource.attributes.description == "Work related contacts"
        assert resource.links is not None
        assert resource.links.self == "http://localhost:8000/api/tags/1"

    def test_to_resource_with_parent_id(self):
        """Test that TagConverter includes parent_id when set."""
        tag = Tag(
            id=2,
            name=TagName("extended"),
            parent_id=1,
        )

        resource = TagConverter.to_resource(tag)

        assert resource.attributes.parent_id == 1

    def test_to_resource_without_parent_id(self):
        """Test that TagConverter includes parent_id as None for root tags."""
        tag = Tag(
            id=1,
            name=TagName("family"),
        )

        resource = TagConverter.to_resource(tag)

        assert resource.attributes.parent_id is None


class TestContactRequestConverter:
    """Test ContactRequestConverter methods."""

    def test_from_method_resource(self):
        """Test converting API method resource to domain entity."""
        attrs = ContactMethodAttributes(
            method_type="email",
            value="test@example.com",
            label="Work",
            is_primary=True,
        )
        resource = ContactMethodResource(id=1, attributes=attrs)

        method = ContactRequestConverter.from_method_resource(resource, 123)

        assert method.id == 1
        assert method.contact_id == 123
        assert method.method_type == MethodType.EMAIL
        assert method.value == "test@example.com"
        assert method.label == "Work"
        assert method.is_primary is True

    def test_from_address_resource(self):
        """Test converting API address resource to domain entity."""
        attrs = ContactAddressAttributes(
            label="Home",
            street_line_1="123 Main St",
            country_code="AU",
            is_primary=True,
        )
        resource = ContactAddressResource(id=1, attributes=attrs)

        address = ContactRequestConverter.from_address_resource(resource, 123)

        assert address.id == 1
        assert address.contact_id == 123
        assert address.label == "Home"
        assert address.street_line_1 == "123 Main St"
        assert address.country_code == "AU"
        assert address.is_primary is True

    def test_from_note_resource(self):
        """Test converting API note resource to domain entity."""
        now = datetime.now(UTC)
        attrs = ContactNoteAttributes(
            content="Test note",
            created_at=now,
            updated_at=now,
        )
        resource = ContactNoteResource(id=1, attributes=attrs)

        note = ContactRequestConverter.from_note_resource(resource, 123)

        assert note.id == 1
        assert note.contact_id == 123
        assert note.content == "Test note"
        assert note.created_at == now
        assert note.updated_at == now

    def test_from_create_request(self):
        """Test converting API create request to domain entity."""
        attrs = ContactAttributes(
            first_name="John",
            last_name="Doe",
            middle_name="William",
            is_favourite=True,
        )
        data = ContactCreateData(attributes=attrs)

        contact = ContactRequestConverter.from_create_request(data)

        assert contact.id is None
        assert contact.first_name == "John"
        assert contact.last_name == "Doe"
        assert contact.middle_name == "William"
        assert contact.is_favourite is True
        assert not contact.methods
        assert not contact.addresses
        assert not contact.notes
