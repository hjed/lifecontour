"""Unit tests for contacts domain entities."""

from datetime import datetime

import pytest
from core_shared.models.contacts.entities import (
    Contact,
    ContactAddress,
    ContactMethod,
    ContactNote,
    MethodType,
    Tag,
)
from core_shared.models.contacts.value_objects import TagName

from tests.integration.contact_seeding import TEST_USER_ID


@pytest.mark.unit
class TestTag:
    """Test Tag entity."""

    def test_create_tag_minimal(self):
        """Test creating tag with minimal required fields."""
        tag = Tag(name=TagName("work"))
        assert str(tag.name) == "work"
        assert tag.id is None
        assert tag.parent_id is None
        assert tag.color is None
        assert tag.description is None

    def test_create_tag_complete(self):
        """Test creating tag with all fields."""
        now = datetime.now()
        tag = Tag(
            name=TagName("work"),
            id=1,
            parent_id=2,
            color="#FF0000",
            description="Work-related contacts",
            created_at=now,
            updated_at=now,
        )
        assert str(tag.name) == "work"
        assert tag.id == 1
        assert tag.parent_id == 2
        assert tag.color == "#FF0000"
        assert tag.description == "Work-related contacts"
        assert tag.created_at == now
        assert tag.updated_at == now

    def test_invalid_color_format_raises_error(self):
        """Test invalid color format raises ValueError."""
        with pytest.raises(
            ValueError, match="Color must be a hex color code starting with #"
        ):
            Tag(name=TagName("work"), color="FF0000")

    def test_invalid_color_length_raises_error(self):
        """Test invalid color length raises ValueError."""
        with pytest.raises(
            ValueError, match="Color must be a 7-character hex color code"
        ):
            Tag(name=TagName("work"), color="#FF00")


@pytest.mark.unit
class TestContactMethod:
    """Test ContactMethod entity."""

    def test_create_email_method(self):
        """Test creating email contact method."""
        method = ContactMethod(
            method_type=MethodType.EMAIL,
            value="test@example.com",
            contact_id=1,
            label="work",
            is_primary=True,
        )
        assert method.method_type == MethodType.EMAIL
        assert method.value == "test@example.com"
        assert method.contact_id == 1
        assert method.label == "work"
        assert method.is_primary is True

    def test_create_phone_method(self):
        """Test creating phone contact method."""
        method = ContactMethod(
            method_type=MethodType.PHONE,
            value="+61 2 1234 5678",
            contact_id=1,
            label="mobile",
        )
        assert method.method_type == MethodType.PHONE
        assert method.value == "+61 2 1234 5678"
        assert method.contact_id == 1
        assert method.label == "mobile"
        assert method.is_primary is False

    def test_invalid_method_type_raises_error(self):
        """Test invalid method type raises ValueError."""
        with pytest.raises(ValueError, match="Invalid method type: address"):
            ContactMethod(method_type="address", value="123 Main St", contact_id=1)  # type: ignore[arg-type]

    def test_invalid_email_value_raises_error(self):
        """Test invalid email value raises ValueError."""
        with pytest.raises(ValueError, match="Invalid email format"):
            ContactMethod(
                method_type=MethodType.EMAIL, value="invalid-email", contact_id=1
            )

    def test_invalid_phone_value_raises_error(self):
        """Test invalid phone value raises ValueError."""
        with pytest.raises(
            ValueError, match="Phone number must contain at least one digit"
        ):
            ContactMethod(
                method_type=MethodType.PHONE, value="abc-def-ghij", contact_id=1
            )

    def test_label_too_long_raises_error(self):
        """Test label too long raises ValueError."""
        with pytest.raises(ValueError, match="Label cannot exceed 50 characters"):
            ContactMethod(
                method_type=MethodType.EMAIL,
                value="test@example.com",
                contact_id=1,
                label="x" * 51,
            )

    def test_method_is_not_archived_by_default(self) -> None:
        method = ContactMethod(
            method_type=MethodType.EMAIL, value="test@example.com", contact_id=1
        )
        assert method.is_archived is False

    def test_archived_method_cannot_be_primary(self) -> None:
        with pytest.raises(ValueError, match="archived .* cannot be primary"):
            ContactMethod(
                method_type=MethodType.EMAIL,
                value="test@example.com",
                contact_id=1,
                is_primary=True,
                is_archived=True,
            )


@pytest.mark.unit
class TestContactAddress:
    """Test ContactAddress entity."""

    def test_create_address_minimal(self):
        """Test creating address with minimal required fields."""
        address = ContactAddress(
            street_line_1="123 Main St", country_code="AU", contact_id=1
        )
        assert address.street_line_1 == "123 Main St"
        assert address.country_code == "AU"
        assert address.contact_id == 1
        assert address.street_line_2 is None
        assert address.locality is None
        assert address.region is None
        assert address.postal_code is None
        assert address.is_primary is False

    def test_create_address_complete(self):
        """Test creating address with all fields."""
        address = ContactAddress(
            street_line_1="123 Main St",
            street_line_2="Apt 4B",
            locality="Sydney",
            region="NSW",
            postal_code="2000",
            country_code="AU",
            contact_id=1,
            label="home",
            is_primary=True,
        )
        assert address.street_line_1 == "123 Main St"
        assert address.street_line_2 == "Apt 4B"
        assert address.locality == "Sydney"
        assert address.region == "NSW"
        assert address.postal_code == "2000"
        assert address.country_code == "AU"
        assert address.contact_id == 1
        assert address.label == "home"
        assert address.is_primary is True

    def test_invalid_country_code_raises_error(self):
        """Test invalid country code raises ValueError."""
        with pytest.raises(
            ValueError, match="Country code must be 2 uppercase letters"
        ):
            ContactAddress(
                street_line_1="123 Main St", country_code="aus", contact_id=1
            )

    def test_empty_street_line_1_raises_error(self):
        """Test empty street line 1 raises ValueError."""
        with pytest.raises(ValueError, match="Street line 1 is required"):
            ContactAddress(street_line_1="", country_code="AU", contact_id=1)

    def test_label_too_long_raises_error(self):
        """Test label too long raises ValueError."""
        with pytest.raises(ValueError, match="Label cannot exceed 50 characters"):
            ContactAddress(
                street_line_1="123 Main St",
                country_code="AU",
                contact_id=1,
                label="x" * 51,
            )

    def test_address_is_not_archived_by_default(self) -> None:
        address = ContactAddress(
            street_line_1="1 Main St", country_code="AU", contact_id=1
        )
        assert address.is_archived is False

    def test_archived_address_cannot_be_primary(self) -> None:
        with pytest.raises(ValueError, match="archived .* cannot be primary"):
            ContactAddress(
                street_line_1="1 Main St",
                country_code="AU",
                contact_id=1,
                is_primary=True,
                is_archived=True,
            )

    def test_to_address_value_object(self):
        """Test conversion to Address value object."""
        address = ContactAddress(
            street_line_1="123 Main St",
            street_line_2="Apt 4B",
            locality="Sydney",
            region="NSW",
            postal_code="2000",
            country_code="AU",
            contact_id=1,
        )
        value_object = address.to_address_value_object()
        assert value_object.street_line_1 == "123 Main St"
        assert value_object.street_line_2 == "Apt 4B"
        assert value_object.locality == "Sydney"
        assert value_object.region == "NSW"
        assert value_object.postal_code == "2000"
        assert value_object.country_code.value == "AU"


@pytest.mark.unit
class TestContactNote:
    """Test ContactNote entity."""

    def test_create_note(self):
        """Test creating contact note."""
        note = ContactNote(content="This is a test note", contact_id=1)
        assert note.content == "This is a test note"
        assert note.contact_id == 1
        assert note.id is None

    def test_empty_content_raises_error(self):
        """Test empty content raises ValueError."""
        with pytest.raises(ValueError, match="Note content cannot be empty"):
            ContactNote(content="", contact_id=1)

    def test_whitespace_only_content_raises_error(self):
        """Test whitespace-only content raises ValueError."""
        with pytest.raises(ValueError, match="Note content cannot be empty"):
            ContactNote(content="   ", contact_id=1)


@pytest.mark.unit
class TestContact:
    """Test Contact entity."""

    def test_create_contact_minimal(self):
        """Test creating contact with minimal required fields."""
        contact = Contact(user_id=TEST_USER_ID, first_name="John")
        assert contact.first_name == "John"
        assert contact.id is None
        assert contact.last_name is None
        assert contact.middle_name is None
        assert contact.nick_name is None
        assert contact.is_favourite is False  # Default should be False
        assert not contact.methods
        assert not contact.addresses
        assert not contact.notes
        assert not contact.tags

    def test_create_contact_complete(self):
        """Test creating contact with all fields."""
        now = datetime.now()
        contact = Contact(
            user_id=TEST_USER_ID,
            first_name="John",
            last_name="Doe",
            middle_name="Michael",
            nick_name="Johnny",
            id=1,
            is_favourite=True,
            created_at=now,
            updated_at=now,
        )
        assert contact.first_name == "John"
        assert contact.last_name == "Doe"
        assert contact.middle_name == "Michael"
        assert contact.nick_name == "Johnny"
        assert contact.id == 1
        assert contact.is_favourite is True
        assert contact.created_at == now
        assert contact.updated_at == now

    def test_empty_first_name_raises_error(self):
        """Test empty first name raises ValueError."""
        with pytest.raises(ValueError, match="First name is required"):
            Contact(user_id=TEST_USER_ID, first_name="")

    def test_whitespace_only_first_name_raises_error(self):
        """Test whitespace-only first name raises ValueError."""
        with pytest.raises(ValueError, match="First name is required"):
            Contact(user_id=TEST_USER_ID, first_name="   ")

    def test_name_length_validation(self):
        """Test name field length validation."""
        # Test first_name too long
        with pytest.raises(ValueError, match="First name cannot exceed 100 characters"):
            Contact(user_id=TEST_USER_ID, first_name="x" * 101)

        # Test last_name too long
        with pytest.raises(ValueError, match="Last name cannot exceed 100 characters"):
            Contact(user_id=TEST_USER_ID, first_name="John", last_name="x" * 101)

        # Test middle_name too long
        with pytest.raises(
            ValueError, match="Middle name cannot exceed 100 characters"
        ):
            Contact(user_id=TEST_USER_ID, first_name="John", middle_name="x" * 101)

        # Test nick_name too long
        with pytest.raises(ValueError, match="Nick name cannot exceed 100 characters"):
            Contact(user_id=TEST_USER_ID, first_name="John", nick_name="x" * 101)

    def test_get_full_name(self):
        """Test get_full_name method."""
        # First name only
        contact = Contact(user_id=TEST_USER_ID, first_name="John")
        assert contact.get_full_name() == "John"

        # First and last name
        contact = Contact(user_id=TEST_USER_ID, first_name="John", last_name="Doe")
        assert contact.get_full_name() == "John Doe"

        # All names
        contact = Contact(
            user_id=TEST_USER_ID,
            first_name="John",
            middle_name="Michael",
            last_name="Doe",
        )
        assert contact.get_full_name() == "John Michael Doe"

    def test_get_display_name(self):
        """Test get_display_name method."""
        # No nick name - returns full name
        contact = Contact(user_id=TEST_USER_ID, first_name="John", last_name="Doe")
        assert contact.get_display_name() == "John Doe"

        # With nick name - returns nick name
        contact = Contact(
            user_id=TEST_USER_ID, first_name="John", last_name="Doe", nick_name="Johnny"
        )
        assert contact.get_display_name() == "Johnny"

    def test_get_primary_email(self):
        """Test get_primary_email method."""
        contact = Contact(user_id=TEST_USER_ID, first_name="John")

        # No methods - returns None
        assert contact.get_primary_email() is None

        # Non-primary email - returns None
        if contact.methods is None:
            contact.methods = []
        contact.methods.append(
            ContactMethod(
                method_type=MethodType.EMAIL,
                value="test@example.com",
                contact_id=1,
                is_primary=False,
            )
        )
        assert contact.get_primary_email() is None

        # Primary email - returns email
        if contact.methods is None:
            contact.methods = []
        contact.methods.append(
            ContactMethod(
                method_type=MethodType.EMAIL,
                value="primary@example.com",
                contact_id=1,
                is_primary=True,
            )
        )
        assert contact.get_primary_email() == "primary@example.com"

    def test_get_primary_phone(self):
        """Test get_primary_phone method."""
        contact = Contact(user_id=TEST_USER_ID, first_name="John")

        # No methods - returns None
        assert contact.get_primary_phone() is None

        # Non-primary phone - returns None
        if contact.methods is None:
            contact.methods = []
        contact.methods.append(
            ContactMethod(
                method_type=MethodType.PHONE,
                value="+61 2 1234 5678",
                contact_id=1,
                is_primary=False,
            )
        )
        assert contact.get_primary_phone() is None

        # Primary phone - returns phone
        if contact.methods is None:
            contact.methods = []
        contact.methods.append(
            ContactMethod(
                method_type=MethodType.PHONE,
                value="+61 412 345 678",
                contact_id=1,
                is_primary=True,
            )
        )
        assert contact.get_primary_phone() == "+61 412 345 678"

    def test_get_primary_address(self):
        """Test get_primary_address method."""
        contact = Contact(user_id=TEST_USER_ID, first_name="John")

        # No addresses - returns None
        assert contact.get_primary_address() is None

        # Non-primary address - returns None
        if contact.addresses is None:
            contact.addresses = []
        contact.addresses.append(
            ContactAddress(
                street_line_1="123 Main St",
                country_code="AU",
                contact_id=1,
                is_primary=False,
            )
        )
        assert contact.get_primary_address() is None

        # Primary address - returns address
        primary_address = ContactAddress(
            street_line_1="456 Primary St",
            country_code="AU",
            contact_id=1,
            is_primary=True,
        )
        if contact.addresses is None:
            contact.addresses = []
        contact.addresses.append(primary_address)
        assert contact.get_primary_address() == primary_address

    def test_add_tag(self):
        """Test add_tag method."""
        contact = Contact(user_id=TEST_USER_ID, first_name="John")
        tag = Tag(name=TagName("work"), id=1)

        # Add first tag
        contact.add_tag(tag)
        assert contact.tags is not None
        assert len(contact.tags) == 1
        assert contact.tags[0] == tag

        # Add duplicate tag - should not add
        contact.add_tag(tag)
        assert contact.tags is not None
        assert len(contact.tags) == 1

        # Add different tag
        tag2 = Tag(name=TagName("family"), id=2)
        contact.add_tag(tag2)
        assert contact.tags is not None
        assert len(contact.tags) == 2

    def test_add_tag_limit_exceeded(self):
        """Test add_tag raises error when limit exceeded."""
        contact = Contact(user_id=TEST_USER_ID, first_name="John")

        # Add 25 tags (maximum)
        for i in range(25):
            tag = Tag(name=TagName(f"tag{i}"), id=i)
            contact.add_tag(tag)

        assert contact.tags is not None
        assert len(contact.tags) == 25

        # Try to add 26th tag - should raise error
        with pytest.raises(ValueError, match="Contact cannot have more than 25 tags"):
            tag26 = Tag(name=TagName("tag25"), id=25)
            contact.add_tag(tag26)

    def test_remove_tag(self):
        """Test remove_tag method."""
        contact = Contact(user_id=TEST_USER_ID, first_name="John")
        tag1 = Tag(name=TagName("work"), id=1)
        tag2 = Tag(name=TagName("family"), id=2)

        contact.add_tag(tag1)
        contact.add_tag(tag2)
        assert contact.tags is not None
        assert len(contact.tags) == 2

        # Remove existing tag
        contact.remove_tag(1)
        assert contact.tags is not None
        assert len(contact.tags) == 1
        assert contact.tags[0] == tag2

        # Remove non-existing tag - should not error
        contact.remove_tag(999)
        assert contact.tags is not None
        assert len(contact.tags) == 1

    def test_favourite_default_false(self):
        """Test that is_favourite defaults to False."""
        contact = Contact(user_id=TEST_USER_ID, first_name="John")
        assert contact.is_favourite is False

    def test_favourite_can_be_set_true(self):
        """Test that is_favourite can be set to True."""
        contact = Contact(user_id=TEST_USER_ID, first_name="John", is_favourite=True)
        assert contact.is_favourite is True

    def test_favourite_can_be_set_false_explicitly(self):
        """Test that is_favourite can be explicitly set to False."""
        contact = Contact(user_id=TEST_USER_ID, first_name="John", is_favourite=False)
        assert contact.is_favourite is False

    def test_toggle_favourite_method(self):
        """Test toggle_favourite method."""
        contact = Contact(user_id=TEST_USER_ID, first_name="John")
        assert contact.is_favourite is False

        # Toggle to True
        contact.toggle_favourite()
        assert contact.is_favourite is True

        # Toggle back to False
        contact.toggle_favourite()
        assert contact.is_favourite is False

    def test_set_favourite_method(self):
        """Test set_favourite method."""
        contact = Contact(user_id=TEST_USER_ID, first_name="John")
        assert contact.is_favourite is False

        # Set to True
        contact.set_favourite(True)
        assert contact.is_favourite is True

        # Set to False
        contact.set_favourite(False)
        assert contact.is_favourite is False

        # Set to True again
        contact.set_favourite(True)
        assert contact.is_favourite is True
