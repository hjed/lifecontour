"""Tests for main ContactService."""

from unittest.mock import AsyncMock

import pytest
from core_shared.models.contacts.entities import (
    Contact,
    ContactAddress,
    ContactMethod,
    ContactNote,
    MethodType,
    Tag,
)
from core_shared.models.contacts.exceptions import ContactValidationError
from core_shared.models.contacts.value_objects import TagName

from app.core.contacts.services.contact_service import ContactService


class TestContactService:
    """Test main ContactService."""

    @pytest.fixture
    def mock_contact_repo(self):
        """Create mock contact repository."""
        return AsyncMock()

    @pytest.fixture
    def mock_tag_repo(self):
        """Create mock tag repository."""
        return AsyncMock()

    @pytest.fixture
    def mock_history_repo(self):
        """Create mock history repository."""
        return AsyncMock()

    @pytest.fixture
    def mock_event_publisher(self):
        """Create mock event publisher."""
        return AsyncMock()

    @pytest.fixture
    def mock_transaction(self):
        """Create mock transaction."""
        return AsyncMock()

    @pytest.fixture
    def contact_service(
        self, mock_contact_repo, mock_tag_repo, mock_history_repo, mock_event_publisher
    ):
        """Create ContactService instance with mocked dependencies."""
        from app.core.contacts.services import (
            AddressValidationService,
            ContactHistoryService,
            ContactValidationService,
            TagHierarchyService,
        )

        # Create service dependencies
        address_validation_service = AddressValidationService()
        contact_validation_service = ContactValidationService(mock_contact_repo)
        history_service = ContactHistoryService(mock_history_repo)
        tag_hierarchy_service = TagHierarchyService(mock_tag_repo)

        return ContactService(
            contact_repo=mock_contact_repo,
            tag_repo=mock_tag_repo,
            history_repo=mock_history_repo,
            event_publisher=mock_event_publisher,
            address_validation_service=address_validation_service,
            contact_validation_service=contact_validation_service,
            history_service=history_service,
            tag_hierarchy_service=tag_hierarchy_service,
        )

    @pytest.fixture
    def mock_tag_service(self):
        """Create a mock TagService (create_tag = race-safe create-or-get)."""
        return AsyncMock()

    @pytest.fixture
    def contact_service_with_tags(
        self,
        mock_contact_repo,
        mock_tag_repo,
        mock_history_repo,
        mock_event_publisher,
        mock_tag_service,
    ):
        """ContactService wired with a TagService so tag names can be resolved."""
        from app.core.contacts.services import (
            AddressValidationService,
            ContactHistoryService,
            ContactValidationService,
            TagHierarchyService,
        )

        return ContactService(
            contact_repo=mock_contact_repo,
            tag_repo=mock_tag_repo,
            history_repo=mock_history_repo,
            event_publisher=mock_event_publisher,
            address_validation_service=AddressValidationService(),
            contact_validation_service=ContactValidationService(mock_contact_repo),
            history_service=ContactHistoryService(mock_history_repo),
            tag_hierarchy_service=TagHierarchyService(mock_tag_repo),
            tag_service=mock_tag_service,
        )

    @pytest.mark.asyncio
    async def test_resolve_tag_names_uses_existing_and_creates_missing(
        self,
        contact_service_with_tags,
        mock_tag_repo,
        mock_tag_service,
        mock_transaction,
    ):
        """Existing names are reused; missing names go through TagService.create_tag."""
        existing = Tag(id=5, name=TagName("Friend"))
        created = Tag(id=9, name=TagName("Work"))

        async def _find(name):
            return existing if name == "Friend" else None

        mock_tag_repo.find_by_name.side_effect = _find
        mock_tag_service.create_tag.return_value = created

        contact = Contact(first_name="A", last_name="B", tags=[])
        await contact_service_with_tags._resolve_tag_names(
            contact, ["Friend", "Work"], mock_transaction
        )

        assert existing in (contact.tags or [])
        assert created in (contact.tags or [])
        # Only the missing name is created; the existing one is not.
        mock_tag_service.create_tag.assert_awaited_once_with(
            "Work", transaction=mock_transaction
        )

    @pytest.mark.asyncio
    async def test_resolve_tag_names_without_tag_service_raises(
        self, contact_service, mock_transaction
    ):
        """A service built without a TagService can't create tags by name."""
        contact = Contact(first_name="A", last_name="B", tags=[])
        with pytest.raises(ContactValidationError):
            await contact_service._resolve_tag_names(contact, ["X"], mock_transaction)

    # Phase 2 Tests: Favourite functionality
    @pytest.mark.asyncio
    async def test_toggle_contact_favourite_success(
        self, contact_service, mock_contact_repo, mock_transaction
    ):
        """Test successful contact favourite toggle."""
        # Arrange
        contact_id = 1
        existing_contact = Contact(
            first_name="John", last_name="Doe", id=contact_id, is_favourite=False
        )
        updated_contact = Contact(
            first_name="John", last_name="Doe", id=contact_id, is_favourite=True
        )

        mock_contact_repo.find_by_id.return_value = existing_contact
        mock_contact_repo.save.return_value = updated_contact

        # Act
        result = await contact_service.toggle_contact_favourite(
            contact_id, mock_transaction
        )

        # Assert
        assert result.is_favourite is True
        mock_contact_repo.find_by_id.assert_called_once_with(contact_id)
        mock_contact_repo.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_toggle_contact_favourite_contact_not_found(
        self, contact_service, mock_contact_repo, mock_transaction
    ):
        """Test toggle favourite when contact not found."""
        # Arrange
        contact_id = 999
        mock_contact_repo.find_by_id.return_value = None

        # Act & Assert
        with pytest.raises(ContactValidationError, match="Contact not found"):
            await contact_service.toggle_contact_favourite(contact_id, mock_transaction)

    @pytest.mark.asyncio
    async def test_get_favourite_contacts_success(
        self, contact_service, mock_contact_repo
    ):
        """Test successful retrieval of favourite contacts."""
        # Arrange
        favourite_contacts = [
            Contact(first_name="John", last_name="Doe", id=1, is_favourite=True),
            Contact(first_name="Jane", last_name="Smith", id=2, is_favourite=True),
        ]
        mock_contact_repo.get_favourite_contacts.return_value = favourite_contacts

        # Act
        result = await contact_service.get_favourite_contacts(limit=10, offset=0)

        # Assert
        assert result == favourite_contacts
        mock_contact_repo.get_favourite_contacts.assert_called_once_with(10, 0)

    @pytest.mark.asyncio
    async def test_get_contacts_paginated_with_favourite_filter(
        self, contact_service, mock_contact_repo
    ):
        """Test get_contacts_paginated with favourite filter."""
        # Arrange
        favourite_contacts = [
            Contact(first_name="John", last_name="Doe", id=1, is_favourite=True),
        ]
        mock_contact_repo.get_contacts_by_filters.return_value = favourite_contacts

        # Act
        result = await contact_service.get_contacts_paginated(
            limit=10, offset=0, is_favourite=True
        )

        # Assert
        assert result == favourite_contacts
        mock_contact_repo.get_contacts_by_filters.assert_called_once_with(
            is_favourite=True, tag_ids=None, limit=10, offset=0
        )

    @pytest.mark.asyncio
    async def test_get_contacts_paginated_with_tag_filter(
        self, contact_service, mock_contact_repo
    ):
        """Test get_contacts_paginated with tag filter."""
        # Arrange
        tag_contacts = [
            Contact(first_name="John", last_name="Doe", id=1),
        ]
        mock_contact_repo.get_contacts_by_filters.return_value = tag_contacts

        # Act
        result = await contact_service.get_contacts_paginated(
            limit=10, offset=0, tag_ids=[1, 2]
        )

        # Assert
        assert result == tag_contacts
        mock_contact_repo.get_contacts_by_filters.assert_called_once_with(
            is_favourite=None, tag_ids=[1, 2], limit=10, offset=0
        )

    @pytest.mark.asyncio
    async def test_get_contacts_paginated_no_filters_uses_get_all(
        self, contact_service, mock_contact_repo
    ):
        """Test get_contacts_paginated without filters uses get_all_contacts."""
        # Arrange
        all_contacts = [
            Contact(first_name="John", last_name="Doe", id=1),
            Contact(first_name="Jane", last_name="Smith", id=2),
        ]
        mock_contact_repo.get_all.return_value = all_contacts

        # Act
        result = await contact_service.get_contacts_paginated(limit=10, offset=0)

        # Assert
        assert result == all_contacts
        mock_contact_repo.get_all.assert_called_once_with(10, 0)
        # Ensure get_contacts_by_filters was not called
        mock_contact_repo.get_contacts_by_filters.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_contacts_count_without_filters_uses_total_count(
        self, contact_service, mock_contact_repo
    ):
        """Test get_contacts_count without filters uses the total count method."""
        # Arrange
        mock_contact_repo.get_count.return_value = 42

        # Act
        result = await contact_service.get_contacts_count()

        # Assert
        assert result == 42
        mock_contact_repo.get_count.assert_called_once_with()
        mock_contact_repo.get_contacts_count_by_filters.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_contacts_count_with_filters_uses_filtered_count(
        self, contact_service, mock_contact_repo
    ):
        """Test get_contacts_count with filters uses the filtered count method."""
        # Arrange
        mock_contact_repo.get_contacts_count_by_filters.return_value = 2

        # Act
        result = await contact_service.get_contacts_count(
            is_favourite=True,
            tag_ids=[1, 2],
        )

        # Assert
        assert result == 2
        mock_contact_repo.get_contacts_count_by_filters.assert_called_once_with(
            is_favourite=True,
            tag_ids=[1, 2],
        )
        mock_contact_repo.get_count.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_contact_success(
        self, contact_service, mock_contact_repo, mock_transaction
    ):
        """Test successful contact creation."""
        # Arrange
        contact = Contact(first_name="John", last_name="Doe")
        saved_contact = Contact(first_name="John", last_name="Doe", id=1)

        mock_contact_repo.save.return_value = saved_contact

        # Act
        result = await contact_service.create_contact(contact, mock_transaction)

        # Assert
        assert result == saved_contact
        mock_contact_repo.save.assert_called_once_with(contact)

    @pytest.mark.asyncio
    async def test_create_contact_no_id_after_save_raises_error(
        self, contact_service, mock_contact_repo, mock_transaction
    ):
        """Test contact creation raises error when no ID after save."""
        # Arrange
        contact = Contact(first_name="John")
        saved_contact = Contact(first_name="John", id=None)  # No ID assigned

        mock_contact_repo.save.return_value = saved_contact

        # Act & Assert
        with pytest.raises(ContactValidationError) as exc_info:
            await contact_service.create_contact(contact, mock_transaction)

        assert exc_info.value.field == "id"
        assert "Contact ID is required after save" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_create_contact_with_methods_success(
        self, contact_service, mock_contact_repo, mock_transaction
    ):
        """Test successful contact creation with attached methods."""
        # Arrange
        contact = Contact(first_name="John", last_name="Doe")

        # Add email method
        email_method = ContactMethod(
            method_type=MethodType.EMAIL,
            value="john@example.com",
            contact_id=0,
            is_primary=True,
        )
        if contact.methods is None:
            contact.methods = []
        contact.methods.append(email_method)

        # Add phone method
        phone_method = ContactMethod(
            method_type=MethodType.PHONE,
            value="+1234567890",
            contact_id=0,
            is_primary=True,
        )
        if contact.methods is None:
            contact.methods = []
        contact.methods.append(phone_method)

        saved_contact = Contact(first_name="John", last_name="Doe", id=1)
        saved_email = ContactMethod(
            method_type=MethodType.EMAIL,
            value="john@example.com",
            contact_id=1,
            is_primary=True,
            id=2,
        )
        saved_phone = ContactMethod(
            method_type=MethodType.PHONE,
            value="+1234567890",
            contact_id=1,
            is_primary=True,
            id=3,
        )

        mock_contact_repo.save.return_value = saved_contact
        mock_contact_repo.find_by_email.return_value = None  # No duplicate email
        mock_contact_repo.add_method.side_effect = [saved_email, saved_phone]

        # Act
        result = await contact_service.create_contact(contact, mock_transaction)

        # Assert
        assert result.id == 1
        assert result.first_name == "John"
        assert result.last_name == "Doe"
        assert len(result.methods) == 2

        # Verify repository calls
        mock_contact_repo.save.assert_called_once_with(contact)
        assert mock_contact_repo.add_method.call_count == 2
        mock_contact_repo.find_by_email.assert_called_once_with("john@example.com")

    @pytest.mark.asyncio
    async def test_create_contact_with_notes_success(
        self, contact_service, mock_contact_repo, mock_transaction
    ):
        """Test successful contact creation with attached notes."""
        # Arrange
        contact = Contact(first_name="Jane", last_name="Smith")

        # Add note
        note = ContactNote(
            content="Met at conference",
            contact_id=0,
        )
        if contact.notes is None:
            contact.notes = []
        contact.notes.append(note)

        saved_contact = Contact(first_name="Jane", last_name="Smith", id=1)
        saved_note = ContactNote(
            content="Met at conference",
            contact_id=1,
            id=2,
        )

        mock_contact_repo.save.return_value = saved_contact
        mock_contact_repo.add_note.return_value = saved_note

        # Act
        result = await contact_service.create_contact(contact, mock_transaction)

        # Assert
        assert result.id == 1
        assert result.first_name == "Jane"
        assert result.last_name == "Smith"
        assert len(result.notes) == 1

        # Verify repository calls
        mock_contact_repo.save.assert_called_once_with(contact)
        mock_contact_repo.add_note.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_contact_with_methods_and_notes_success(
        self, contact_service, mock_contact_repo, mock_transaction
    ):
        """Test successful contact creation with both methods and notes."""
        # Arrange
        contact = Contact(first_name="Bob", last_name="Wilson")

        # Add email method
        email_method = ContactMethod(
            method_type=MethodType.EMAIL,
            value="bob@example.com",
            contact_id=0,
            is_primary=True,
        )
        if contact.methods is None:
            contact.methods = []
        contact.methods.append(email_method)

        # Add note
        note = ContactNote(
            content="Important client",
            contact_id=0,
        )
        if contact.notes is None:
            contact.notes = []
        contact.notes.append(note)

        saved_contact = Contact(first_name="Bob", last_name="Wilson", id=1)
        saved_email = ContactMethod(
            method_type=MethodType.EMAIL,
            value="bob@example.com",
            contact_id=1,
            is_primary=True,
            id=2,
        )
        saved_note = ContactNote(
            content="Important client",
            contact_id=1,
            id=3,
        )

        mock_contact_repo.save.return_value = saved_contact
        mock_contact_repo.find_by_email.return_value = None  # No duplicate email
        mock_contact_repo.add_method.return_value = saved_email
        mock_contact_repo.add_note.return_value = saved_note

        # Act
        result = await contact_service.create_contact(contact, mock_transaction)

        # Assert
        assert result.id == 1
        assert result.first_name == "Bob"
        assert result.last_name == "Wilson"
        assert len(result.methods) == 1
        assert len(result.notes) == 1

        # Verify repository calls
        mock_contact_repo.save.assert_called_once_with(contact)
        mock_contact_repo.add_method.assert_called_once()
        mock_contact_repo.add_note.assert_called_once()
        mock_contact_repo.find_by_email.assert_called_once_with("bob@example.com")

    @pytest.mark.asyncio
    async def test_create_contact_with_method_no_id_after_save_raises_error(
        self, contact_service, mock_contact_repo, mock_transaction
    ):
        """Test contact creation with method raises error when method has no ID after save."""
        # Arrange
        contact = Contact(first_name="John", last_name="Doe")

        # Add email method
        email_method = ContactMethod(
            method_type=MethodType.EMAIL,
            value="john@example.com",
            contact_id=0,
            is_primary=True,
        )
        if contact.methods is None:
            contact.methods = []
        contact.methods.append(email_method)

        saved_contact = Contact(first_name="John", last_name="Doe", id=1)
        saved_email = ContactMethod(
            method_type=MethodType.EMAIL,
            value="john@example.com",
            contact_id=1,
            is_primary=True,
            id=None,  # No ID assigned
        )

        mock_contact_repo.save.return_value = saved_contact
        mock_contact_repo.find_by_email.return_value = None  # No duplicate email
        mock_contact_repo.add_method.return_value = saved_email

        # Act & Assert
        with pytest.raises(ContactValidationError) as exc_info:
            await contact_service.create_contact(contact, mock_transaction)

        assert exc_info.value.field == "id"
        assert "Method ID is required after save" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_create_contact_with_note_no_id_after_save_raises_error(
        self, contact_service, mock_contact_repo, mock_transaction
    ):
        """Test contact creation with note raises error when note has no ID after save."""
        # Arrange
        contact = Contact(first_name="Jane", last_name="Smith")

        # Add note
        note = ContactNote(
            content="Met at conference",
            contact_id=0,
        )
        if contact.notes is None:
            contact.notes = []
        contact.notes.append(note)

        saved_contact = Contact(first_name="Jane", last_name="Smith", id=1)
        saved_note = ContactNote(
            content="Met at conference",
            contact_id=1,
            id=None,  # No ID assigned
        )

        mock_contact_repo.save.return_value = saved_contact
        mock_contact_repo.add_note.return_value = saved_note

        # Act & Assert
        with pytest.raises(ContactValidationError) as exc_info:
            await contact_service.create_contact(contact, mock_transaction)

        assert exc_info.value.field == "id"
        assert "Note ID is required after save" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_update_contact_with_methods_and_notes_success(
        self, contact_service, mock_contact_repo, mock_transaction
    ):
        """Test successful contact update with attached methods and notes."""
        # Arrange
        current_contact = Contact(first_name="John", last_name="Smith", id=1)
        updated_contact = Contact(first_name="John", last_name="Doe", id=1)

        # Add email method to updated contact
        email_method = ContactMethod(
            method_type=MethodType.EMAIL,
            value="john.doe@example.com",
            contact_id=1,
            is_primary=True,
        )
        if updated_contact.methods is None:
            updated_contact.methods = []
        updated_contact.methods.append(email_method)

        # Add note to updated contact
        note = ContactNote(
            content="Updated contact information",
            contact_id=1,
        )
        if updated_contact.notes is None:
            updated_contact.notes = []
        updated_contact.notes.append(note)

        saved_contact = Contact(first_name="John", last_name="Doe", id=1)
        saved_email = ContactMethod(
            method_type=MethodType.EMAIL,
            value="john.doe@example.com",
            contact_id=1,
            is_primary=True,
            id=2,
        )
        saved_note = ContactNote(
            content="Updated contact information",
            contact_id=1,
            id=3,
        )

        mock_contact_repo.find_by_id.return_value = current_contact
        mock_contact_repo.save.return_value = saved_contact
        mock_contact_repo.find_by_email.return_value = None  # No duplicate email
        mock_contact_repo.add_method.return_value = saved_email
        mock_contact_repo.add_note.return_value = saved_note

        # Act
        result = await contact_service.update_contact(updated_contact, mock_transaction)

        # Assert
        assert result.id == 1
        assert result.first_name == "John"
        assert result.last_name == "Doe"
        assert len(result.methods) == 1
        assert len(result.notes) == 1

        # Verify repository calls
        assert (
            mock_contact_repo.find_by_id.call_count >= 1
        )  # Called for validation and possibly other checks
        mock_contact_repo.save.assert_called_once_with(updated_contact)
        mock_contact_repo.add_method.assert_called_once()
        mock_contact_repo.add_note.assert_called_once()
        mock_contact_repo.find_by_email.assert_called_once_with("john.doe@example.com")

    @pytest.mark.asyncio
    async def test_update_contact_success(
        self, contact_service, mock_contact_repo, mock_transaction
    ):
        """Test successful contact update."""
        # Arrange
        current_contact = Contact(first_name="John", last_name="Smith", id=1)
        updated_contact = Contact(first_name="John", last_name="Doe", id=1)
        saved_contact = Contact(first_name="John", last_name="Doe", id=1)

        mock_contact_repo.find_by_id.return_value = current_contact
        mock_contact_repo.save.return_value = saved_contact

        # Act
        result = await contact_service.update_contact(updated_contact, mock_transaction)

        # Assert
        assert result == saved_contact
        mock_contact_repo.find_by_id.assert_called_once_with(1)
        mock_contact_repo.save.assert_called_once_with(updated_contact)

    @pytest.mark.asyncio
    async def test_update_contact_empty_tag_names_clears_without_tag_service(
        self, contact_service, mock_contact_repo, mock_transaction
    ):
        """An empty tag_names list clears tags and must not require a TagService.

        contact_service is built WITHOUT a TagService, so this would raise if the
        empty-list clear path still went through _resolve_tag_names.
        """
        current_contact = Contact(first_name="John", last_name="Smith", id=1)
        saved_contact = Contact(first_name="John", last_name="Smith", id=1)
        mock_contact_repo.find_by_id.return_value = current_contact
        mock_contact_repo.save.return_value = saved_contact

        updated_contact = Contact(first_name="John", last_name="Smith", id=1, tags=None)
        result = await contact_service.update_contact(
            updated_contact, mock_transaction, tag_names=[]
        )

        assert result == saved_contact
        assert updated_contact.tags == []  # cleared

    @pytest.mark.asyncio
    async def test_update_contact_no_id_raises_error(
        self, contact_service, mock_transaction
    ):
        """Test contact update raises error when no ID."""
        # Arrange
        contact = Contact(first_name="John", id=None)

        # Act & Assert
        with pytest.raises(ContactValidationError) as exc_info:
            await contact_service.update_contact(contact, mock_transaction)

        assert exc_info.value.field == "id"
        assert "Contact ID is required for updates" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_delete_contact_success(
        self, contact_service, mock_contact_repo, mock_transaction
    ):
        """Test successful contact deletion."""
        # Arrange
        contact = Contact(first_name="John", id=1)
        mock_contact_repo.find_by_id.return_value = contact

        # Act
        await contact_service.delete_contact(1, mock_transaction)

        # Assert
        mock_contact_repo.delete.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_assign_tag_to_contact_success(
        self, contact_service, mock_contact_repo, mock_tag_repo, mock_transaction
    ):
        """Test successful tag assignment."""
        # Arrange
        contact = Contact(first_name="John", id=1)
        tag = Tag(name=TagName("work"), id=2)

        mock_contact_repo.find_by_id.return_value = contact
        mock_tag_repo.find_by_id.return_value = tag

        # Act
        await contact_service.assign_tag_to_contact(1, 2, mock_transaction)

        # Assert
        mock_contact_repo.assign_tag.assert_called_once_with(1, 2)

    @pytest.mark.asyncio
    async def test_remove_tag_from_contact_success(
        self, contact_service, mock_contact_repo, mock_tag_repo, mock_transaction
    ):
        """Test successful tag removal."""
        # Arrange
        contact = Contact(first_name="John", id=1)
        tag = Tag(name=TagName("work"), id=2)

        mock_contact_repo.find_by_id.return_value = contact
        mock_tag_repo.find_by_id.return_value = tag

        # Act
        await contact_service.remove_tag_from_contact(1, 2, mock_transaction)

        # Assert
        mock_contact_repo.remove_tag.assert_called_once_with(1, 2)

    @pytest.mark.asyncio
    async def test_add_contact_method_success(
        self, contact_service, mock_contact_repo, mock_transaction
    ):
        """Test successful contact method addition."""
        # Arrange
        contact = Contact(first_name="John", id=1)
        method = ContactMethod(
            method_type=MethodType.EMAIL, value="test@example.com", contact_id=1
        )
        saved_method = ContactMethod(
            method_type=MethodType.EMAIL, value="test@example.com", contact_id=1, id=2
        )

        mock_contact_repo.find_by_id.return_value = contact
        mock_contact_repo.find_by_email.return_value = None  # No duplicate email
        mock_contact_repo.add_method.return_value = saved_method

        # Act
        result = await contact_service.add_contact_method(1, method, mock_transaction)

        # Assert
        assert result == saved_method
        mock_contact_repo.add_method.assert_called_once_with(1, method)

    @pytest.mark.asyncio
    async def test_add_contact_address_success(
        self, contact_service, mock_contact_repo, mock_transaction
    ):
        """Test successful contact address addition."""
        # Arrange
        contact = Contact(first_name="John", id=1)
        address = ContactAddress(
            street_line_1="123 Main St", country_code="AU", contact_id=1
        )
        saved_address = ContactAddress(
            street_line_1="123 Main St", country_code="AU", contact_id=1, id=2
        )

        mock_contact_repo.find_by_id.return_value = contact
        mock_contact_repo.add_address.return_value = saved_address

        # Act
        result = await contact_service.add_contact_address(1, address, mock_transaction)

        # Assert
        assert result == saved_address
        mock_contact_repo.add_address.assert_called_once_with(1, address)

    @pytest.mark.asyncio
    async def test_add_contact_note_success(
        self, contact_service, mock_contact_repo, mock_transaction
    ):
        """Test successful contact note addition."""
        # Arrange
        contact = Contact(first_name="John", id=1)
        note = ContactNote(content="This is a test note", contact_id=1)
        saved_note = ContactNote(content="This is a test note", contact_id=1, id=2)

        mock_contact_repo.find_by_id.return_value = contact
        mock_contact_repo.add_note.return_value = saved_note

        # Act
        result = await contact_service.add_contact_note(1, note, mock_transaction)

        # Assert
        assert result == saved_note
        mock_contact_repo.add_note.assert_called_once_with(1, note)

    @pytest.mark.asyncio
    async def test_get_contact_by_id(self, contact_service, mock_contact_repo):
        """Test getting contact by ID."""
        # Arrange
        contact = Contact(first_name="John", id=1)
        mock_contact_repo.find_by_id.return_value = contact

        # Act
        result = await contact_service.get_contact_by_id(1)

        # Assert
        assert result == contact
        mock_contact_repo.find_by_id.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_get_contact_by_email(self, contact_service, mock_contact_repo):
        """Test getting contact by email."""
        # Arrange
        contact = Contact(first_name="John", id=1)
        mock_contact_repo.find_by_email.return_value = contact

        # Act
        result = await contact_service.get_contact_by_email("test@example.com")

        # Assert
        assert result == contact
        mock_contact_repo.find_by_email.assert_called_once_with("test@example.com")

    @pytest.mark.asyncio
    async def test_search_contacts(self, contact_service, mock_contact_repo):
        """Test searching contacts."""
        # Arrange
        contacts = [Contact(first_name="John", id=1)]
        mock_contact_repo.search.return_value = contacts

        # Act
        result = await contact_service.search_contacts("John", limit=10)

        # Assert
        assert result == contacts
        mock_contact_repo.search.assert_called_once_with("John", 10)

    @pytest.mark.asyncio
    async def test_get_all_contacts(self, contact_service, mock_contact_repo):
        """Test getting all contacts."""
        # Arrange
        contacts = [Contact(first_name="John", id=1)]
        mock_contact_repo.get_all.return_value = contacts

        # Act
        result = await contact_service.get_all_contacts(limit=50, offset=0)

        # Assert
        assert result == contacts
        mock_contact_repo.get_all.assert_called_once_with(50, 0)

    @pytest.mark.asyncio
    async def test_get_contacts_by_tag(self, contact_service, mock_contact_repo):
        """Test getting contacts by tag."""
        # Arrange
        contacts = [Contact(first_name="John", id=1)]
        mock_contact_repo.get_contacts_by_tag.return_value = contacts

        # Act
        result = await contact_service.get_contacts_by_tag(1)

        # Assert
        assert result == contacts
        mock_contact_repo.get_contacts_by_tag.assert_called_once_with(1)

    # Descendant-aware filtering tests (ITER2.6-002 Phase 1)

    @pytest.mark.asyncio
    async def test_get_contacts_paginated_with_parent_tag_expands_descendants(
        self, contact_service, mock_contact_repo, mock_tag_repo
    ):
        """Test that filtering by a parent tag expands to include descendant tag IDs."""
        # Arrange: parent tag 1 has children tag 2 and tag 3
        parent_tag_id = 1
        child_tag_1 = Tag(name=TagName("child1"), id=2, parent_id=parent_tag_id)
        child_tag_2 = Tag(name=TagName("child2"), id=3, parent_id=parent_tag_id)

        mock_tag_repo.get_descendants_for_tags.side_effect = lambda tag_ids: (
            [child_tag_1, child_tag_2] if parent_tag_id in tag_ids else []
        )
        mock_contact_repo.get_contacts_by_filters.return_value = []

        # Act
        await contact_service.get_contacts_paginated(
            limit=10, offset=0, tag_ids=[parent_tag_id]
        )

        # Assert: repo should be called with expanded tag_ids including parent + descendants
        call_args = mock_contact_repo.get_contacts_by_filters.call_args
        called_tag_ids = call_args.kwargs.get("tag_ids") or call_args[1].get("tag_ids")
        assert set(called_tag_ids) == {1, 2, 3}

    @pytest.mark.asyncio
    async def test_get_contacts_count_with_parent_tag_expands_descendants(
        self, contact_service, mock_contact_repo, mock_tag_repo
    ):
        """Test that count with parent tag expands to include descendant tag IDs."""
        # Arrange: parent tag 10 has child tag 20
        parent_tag_id = 10
        child_tag = Tag(name=TagName("child"), id=20, parent_id=parent_tag_id)

        mock_tag_repo.get_descendants_for_tags.side_effect = lambda tag_ids: (
            [child_tag] if parent_tag_id in tag_ids else []
        )
        mock_contact_repo.get_contacts_count_by_filters.return_value = 5

        # Act
        result = await contact_service.get_contacts_count(tag_ids=[parent_tag_id])

        # Assert
        assert result == 5
        call_args = mock_contact_repo.get_contacts_count_by_filters.call_args
        called_tag_ids = call_args.kwargs.get("tag_ids") or call_args[1].get("tag_ids")
        assert set(called_tag_ids) == {10, 20}

    @pytest.mark.asyncio
    async def test_get_contacts_paginated_leaf_tag_unchanged(
        self, contact_service, mock_contact_repo, mock_tag_repo
    ):
        """Test that a leaf tag (no children) passes through unchanged."""
        # Arrange: tag 5 has no children
        leaf_tag_id = 5
        mock_tag_repo.get_descendants_for_tags.return_value = []
        mock_contact_repo.get_contacts_by_filters.return_value = []

        # Act
        await contact_service.get_contacts_paginated(
            limit=10, offset=0, tag_ids=[leaf_tag_id]
        )

        # Assert: repo should be called with just the original tag ID
        call_args = mock_contact_repo.get_contacts_by_filters.call_args
        called_tag_ids = call_args.kwargs.get("tag_ids") or call_args[1].get("tag_ids")
        assert called_tag_ids == [leaf_tag_id]

    @pytest.mark.asyncio
    async def test_get_contacts_paginated_mixed_hierarchy_expands_all(
        self, contact_service, mock_contact_repo, mock_tag_repo
    ):
        """Test that multiple tag_ids with mixed hierarchy expand independently."""
        # Arrange: tag 1 has child 2, tag 5 has no children
        parent_tag_id = 1
        child_tag = Tag(name=TagName("child"), id=2, parent_id=parent_tag_id)
        leaf_tag_id = 5

        mock_tag_repo.get_descendants_for_tags.side_effect = lambda tag_ids: (
            [child_tag] if parent_tag_id in tag_ids else []
        )
        mock_contact_repo.get_contacts_by_filters.return_value = []

        # Act
        await contact_service.get_contacts_paginated(
            limit=10, offset=0, tag_ids=[parent_tag_id, leaf_tag_id]
        )

        # Assert: repo called with parent + child + leaf
        call_args = mock_contact_repo.get_contacts_by_filters.call_args
        called_tag_ids = call_args.kwargs.get("tag_ids") or call_args[1].get("tag_ids")
        assert set(called_tag_ids) == {1, 2, 5}

    @pytest.mark.asyncio
    async def test_get_contacts_paginated_no_tag_ids_skips_descendant_resolution(
        self, contact_service, mock_contact_repo, mock_tag_repo
    ):
        """Test that no tag_ids skips descendant resolution entirely."""
        # Arrange
        mock_contact_repo.get_all.return_value = []

        # Act
        await contact_service.get_contacts_paginated(limit=10, offset=0, tag_ids=None)

        # Assert: get_descendants_for_tags should never be called
        mock_tag_repo.get_descendants_for_tags.assert_not_called()
        mock_contact_repo.get_all.assert_called_once()
