"""Tests for main ContactService."""

from unittest.mock import AsyncMock

import pytest

from app.core.contacts.models.entities import (
    Contact,
    ContactAddress,
    ContactMethod,
    ContactNote,
    MethodType,
    Tag,
)
from app.core.contacts.models.exceptions import ContactValidationError
from app.core.contacts.models.value_objects import TagName
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
        return ContactService(
            contact_repo=mock_contact_repo,
            tag_repo=mock_tag_repo,
            history_repo=mock_history_repo,
            event_publisher=mock_event_publisher,
        )

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
