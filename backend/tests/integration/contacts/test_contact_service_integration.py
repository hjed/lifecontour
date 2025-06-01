"""Integration tests for ContactService with real database connections."""

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql import (
    SqlContactEditEventRepository,
    SqlContactEventPublisher,
    SqlContactFieldHistoryRepository,
    SqlContactRepository,
    SqlTagRepository,
)
from app.core.contacts.models.entities import (
    Contact,
    ContactAddress,
    ContactMethod,
    ContactNote,
    MethodType,
    Tag,
)
from app.core.contacts.models.exceptions import (
    ContactNotFoundError,
    ContactValidationError,
    DuplicateEmailError,
)
from app.core.contacts.models.value_objects import TagName
from app.core.contacts.services import ContactService


class TestContactServiceIntegration:
    """Integration tests for ContactService with real database."""

    @pytest.fixture
    def contact_repo(self, clean_database: AsyncConnection):
        """Create real contact repository."""
        return SqlContactRepository(clean_database)

    @pytest.fixture
    def tag_repo(self, clean_database: AsyncConnection):
        """Create real tag repository."""
        return SqlTagRepository(clean_database)

    @pytest.fixture
    def history_repo(self, clean_database: AsyncConnection):
        """Create real field history repository."""
        return SqlContactFieldHistoryRepository(clean_database)

    @pytest.fixture
    def event_repo(self, clean_database: AsyncConnection):
        """Create real event repository."""
        return SqlContactEditEventRepository(clean_database)

    @pytest.fixture
    def event_publisher(self, clean_database: AsyncConnection):
        """Create real event publisher."""
        return SqlContactEventPublisher(clean_database)

    @pytest.fixture
    def contact_service(self, contact_repo, tag_repo, history_repo, event_publisher):
        """Create ContactService instance with real dependencies."""
        return ContactService(
            contact_repo=contact_repo,
            tag_repo=tag_repo,
            history_repo=history_repo,
            event_publisher=event_publisher
        )

    @pytest.mark.asyncio
    async def test_create_contact_success(self, contact_service, clean_database: AsyncConnection):
        """Test successful contact creation with real database."""
        # Arrange
        contact = Contact(first_name="John", last_name="Doe")

        # Act
        result = await contact_service.create_contact(contact, clean_database)

        # Assert
        assert result.id is not None
        assert result.first_name == "John"
        assert result.last_name == "Doe"
        assert result.created_at is not None

        # Verify contact was actually saved to database
        saved_contact = await contact_service.get_contact_by_id(result.id)
        assert saved_contact is not None
        assert saved_contact.first_name == "John"
        assert saved_contact.last_name == "Doe"

    @pytest.mark.asyncio
    async def test_create_contact_with_email_method(self, contact_service, clean_database: AsyncConnection):
        """Test contact creation with email method."""
        # Arrange
        contact = Contact(first_name="John", last_name="Doe")

        # Act - Create contact first
        saved_contact = await contact_service.create_contact(contact, clean_database)

        # Add email method
        email_method = ContactMethod(
            method_type=MethodType.EMAIL,
            value="john.doe@example.com",
            contact_id=saved_contact.id,
            is_primary=True
        )
        saved_method = await contact_service.add_contact_method(saved_contact.id, email_method, clean_database)

        # Assert
        assert saved_method.id is not None
        assert saved_method.method_type == MethodType.EMAIL
        assert saved_method.value == "john.doe@example.com"
        assert saved_method.is_primary is True

        # Verify contact can be found by email
        found_contact = await contact_service.get_contact_by_email("john.doe@example.com")
        assert found_contact is not None
        assert found_contact.id == saved_contact.id

    @pytest.mark.asyncio
    async def test_create_contact_duplicate_email_raises_error(self, contact_service, clean_database: AsyncConnection):
        """Test contact creation raises error for duplicate email."""
        # Arrange - Create first contact with email
        contact1 = Contact(first_name="John", last_name="Doe")
        saved_contact1 = await contact_service.create_contact(contact1, clean_database)

        email_method1 = ContactMethod(
            method_type=MethodType.EMAIL,
            value="duplicate@example.com",
            contact_id=saved_contact1.id,
            is_primary=True
        )
        await contact_service.add_contact_method(saved_contact1.id, email_method1, clean_database)

        # Create second contact
        contact2 = Contact(first_name="Jane", last_name="Smith")
        saved_contact2 = await contact_service.create_contact(contact2, clean_database)

        # Try to add same email to second contact
        email_method2 = ContactMethod(
            method_type=MethodType.EMAIL,
            value="duplicate@example.com",
            contact_id=saved_contact2.id,
            is_primary=True
        )

        # Act & Assert
        with pytest.raises(DuplicateEmailError):
            await contact_service.add_contact_method(saved_contact2.id, email_method2, clean_database)

    @pytest.mark.asyncio
    async def test_update_contact_success(self, contact_service, clean_database: AsyncConnection, history_repo):
        """Test successful contact update with field history tracking."""
        # Arrange - Create contact
        contact = Contact(first_name="John", last_name="Smith")
        saved_contact = await contact_service.create_contact(contact, clean_database)

        # Update contact
        saved_contact.last_name = "Doe"
        changed_fields = {"last_name": ("Smith", "Doe")}

        # Act
        result = await contact_service.update_contact(saved_contact, changed_fields, clean_database)

        # Assert
        assert result.id == saved_contact.id
        assert result.first_name == "John"
        assert result.last_name == "Doe"

        # Verify field history was recorded
        history = await history_repo.get_contact_history(saved_contact.id)
        assert len(history) == 1
        assert history[0].entity_type == "contact"
        assert history[0].entity_id == saved_contact.id
        assert history[0].field_name == "last_name"
        assert history[0].old_value == "Smith"
        assert history[0].new_value == "Doe"

    @pytest.mark.asyncio
    async def test_update_contact_no_id_raises_error(self, contact_service, clean_database: AsyncConnection):
        """Test contact update raises error when no ID."""
        # Arrange
        contact = Contact(first_name="John", id=None)
        changed_fields = {"last_name": ("Smith", "Doe")}

        # Act & Assert
        with pytest.raises(ContactValidationError) as exc_info:
            await contact_service.update_contact(contact, changed_fields, clean_database)

        assert exc_info.value.field == "id"

    @pytest.mark.asyncio
    async def test_delete_contact_success(self, contact_service, clean_database: AsyncConnection):
        """Test successful contact deletion."""
        # Arrange - Create contact
        contact = Contact(first_name="John", last_name="Doe")
        saved_contact = await contact_service.create_contact(contact, clean_database)

        # Act
        await contact_service.delete_contact(saved_contact.id, clean_database)

        # Assert - Contact should no longer exist
        deleted_contact = await contact_service.get_contact_by_id(saved_contact.id)
        assert deleted_contact is None

    @pytest.mark.asyncio
    async def test_delete_contact_not_found_raises_error(self, contact_service, clean_database: AsyncConnection):
        """Test contact deletion raises error when contact not found."""
        # Act & Assert
        with pytest.raises(ContactNotFoundError):
            await contact_service.delete_contact(999, clean_database)

    @pytest.mark.asyncio
    async def test_assign_tag_to_contact_success(self, contact_service, tag_repo, clean_database: AsyncConnection, history_repo):
        """Test successful tag assignment with real database."""
        # Arrange - Create contact and tag
        contact = Contact(first_name="John", last_name="Doe")
        saved_contact = await contact_service.create_contact(contact, clean_database)

        tag = Tag(name=TagName("work"))
        saved_tag = await tag_repo.save(tag)

        # Act
        await contact_service.assign_tag_to_contact(saved_contact.id, saved_tag.id, clean_database)

        # Assert - Verify tag assignment
        contact_with_tags = await contact_service.get_contact_by_id(saved_contact.id)
        assert len(contact_with_tags.tags) == 1
        assert contact_with_tags.tags[0].id == saved_tag.id
        assert str(contact_with_tags.tags[0].name) == "work"

        # Verify field history was recorded for tag assignment
        history = await history_repo.get_contact_history(saved_contact.id)
        tag_history = [h for h in history if h.entity_type == "contact_tag"]
        assert len(tag_history) == 1
        assert tag_history[0].field_name == "contact_id"
        assert tag_history[0].new_value == str(saved_contact.id)

    @pytest.mark.asyncio
    async def test_comprehensive_contact_workflow(self, contact_service, tag_repo, clean_database: AsyncConnection, history_repo, event_repo):
        """Test comprehensive contact workflow with all features."""
        # Create contact
        contact = Contact(first_name="John", last_name="Doe", middle_name="William")
        saved_contact = await contact_service.create_contact(contact, clean_database)
        assert saved_contact.id is not None

        # Add email method
        email_method = ContactMethod(
            method_type=MethodType.EMAIL,
            value="john.doe@example.com",
            contact_id=saved_contact.id,
            is_primary=True,
            label="Work"
        )
        saved_email = await contact_service.add_contact_method(saved_contact.id, email_method, clean_database)
        assert saved_email.id is not None

        # Add phone method
        phone_method = ContactMethod(
            method_type=MethodType.PHONE,
            value="+1-555-123-4567",
            contact_id=saved_contact.id,
            is_primary=True,
            label="Mobile"
        )
        saved_phone = await contact_service.add_contact_method(saved_contact.id, phone_method, clean_database)
        assert saved_phone.id is not None

        # Add address
        address = ContactAddress(
            street_line_1="123 Main Street",
            street_line_2="Apt 4B",
            locality="New York",
            region="NY",
            postal_code="10001",
            country_code="US",
            contact_id=saved_contact.id,
            is_primary=True,
            label="Home"
        )
        saved_address = await contact_service.add_contact_address(saved_contact.id, address, clean_database)
        assert saved_address.id is not None

        # Add note
        note = ContactNote(
            content="Important client - prefers email communication",
            contact_id=saved_contact.id
        )
        saved_note = await contact_service.add_contact_note(saved_contact.id, note, clean_database)
        assert saved_note.id is not None

        # Create and assign tags
        work_tag = Tag(name=TagName("work"))
        client_tag = Tag(name=TagName("client"))
        saved_work_tag = await tag_repo.save(work_tag)
        saved_client_tag = await tag_repo.save(client_tag)

        await contact_service.assign_tag_to_contact(saved_contact.id, saved_work_tag.id, clean_database)
        await contact_service.assign_tag_to_contact(saved_contact.id, saved_client_tag.id, clean_database)

        # Update contact
        saved_contact.nick_name = "Johnny"
        changed_fields = {"nick_name": (None, "Johnny")}
        await contact_service.update_contact(saved_contact, changed_fields, clean_database)

        # Verify final state
        final_contact = await contact_service.get_contact_by_id(saved_contact.id)
        assert final_contact.first_name == "John"
        assert final_contact.last_name == "Doe"
        assert final_contact.middle_name == "William"
        assert final_contact.nick_name == "Johnny"
        assert len(final_contact.methods) == 2
        assert len(final_contact.addresses) == 1
        assert len(final_contact.notes) == 1
        assert len(final_contact.tags) == 2

        # Verify contact can be found by email
        found_by_email = await contact_service.get_contact_by_email("john.doe@example.com")
        assert found_by_email.id == saved_contact.id

        # Verify field history tracking
        history = await history_repo.get_contact_history(saved_contact.id)
        assert len(history) >= 3  # nick_name update + tag assignments

        # Verify domain events were recorded
        events = await event_repo.get_events_for_contact(saved_contact.id)
        assert len(events) >= 6  # create, add method x2, add address, add note, update
