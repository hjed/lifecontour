"""Unit tests for contact field update functionality."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core.contacts.models.entities import Contact
from app.core.contacts.models.exceptions import ContactValidationError
from app.core.contacts.services.contact_service import ContactService


class TestContactFieldUpdate:
    """Test contact field update functionality."""

    @pytest.fixture
    def mock_contact_repo(self):
        """Mock contact repository."""
        return AsyncMock()

    @pytest.fixture
    def mock_tag_repo(self):
        """Mock tag repository."""
        return AsyncMock()

    @pytest.fixture
    def mock_history_service(self):
        """Mock contact history service."""
        return AsyncMock()

    @pytest.fixture
    def mock_event_publisher(self):
        """Mock event publisher."""
        return AsyncMock()

    @pytest.fixture
    def mock_validation_service(self):
        """Mock validation service."""
        return AsyncMock()

    @pytest.fixture
    def mock_address_validation_service(self):
        """Mock address validation service."""
        return AsyncMock()

    @pytest.fixture
    def mock_tag_hierarchy_service(self):
        """Mock tag hierarchy service."""
        return AsyncMock()

    @pytest.fixture
    def mock_history_repo(self):
        """Mock history repository."""
        return AsyncMock()

    @pytest.fixture
    def contact_service(
        self,
        mock_contact_repo,
        mock_tag_repo,
        mock_history_repo,
        mock_event_publisher,
        mock_address_validation_service,
        mock_validation_service,
        mock_history_service,
        mock_tag_hierarchy_service,
    ):
        """Create contact service with mocked dependencies."""
        return ContactService(
            contact_repo=mock_contact_repo,
            tag_repo=mock_tag_repo,
            history_repo=mock_history_repo,
            event_publisher=mock_event_publisher,
            address_validation_service=mock_address_validation_service,
            contact_validation_service=mock_validation_service,
            history_service=mock_history_service,
            tag_hierarchy_service=mock_tag_hierarchy_service,
        )

    @pytest.fixture
    def sample_contact(self):
        """Create a sample contact for testing."""
        return Contact(
            id=1,
            first_name="John",
            last_name="Doe",
            middle_name="William",
            nick_name="Johnny",
            is_favourite=False,
        )

    @pytest.mark.asyncio
    async def test_update_first_name(
        self, contact_service, mock_contact_repo, mock_history_service, mock_event_publisher, sample_contact
    ):
        """Test updating first name field."""
        mock_contact_repo.find_by_id.return_value = sample_contact
        mock_transaction = AsyncMock()

        old_value, new_value = await contact_service.update_contact_field(
            contact_id=1,
            field_name="first_name",
            field_value="Jonathan",
            transaction=mock_transaction,
        )

        assert old_value == "John"
        assert new_value == "Jonathan"
        
        # Verify contact was saved with updated value
        mock_contact_repo.save.assert_called_once()
        saved_contact = mock_contact_repo.save.call_args[0][0]
        assert saved_contact.first_name == "Jonathan"
        
        # Verify history was recorded
        mock_history_service.record_contact_change.assert_called_once()
        history_call = mock_history_service.record_contact_change.call_args
        assert history_call[0][0] == 1  # contact_id
        assert history_call[0][1] == {"first_name": ("John", "Jonathan")}
        
        # Verify event was published
        mock_event_publisher.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_is_favourite_with_string_true(
        self, contact_service, mock_contact_repo, sample_contact
    ):
        """Test updating is_favourite field with string 'true'."""
        mock_contact_repo.find_by_id.return_value = sample_contact
        mock_transaction = AsyncMock()

        old_value, new_value = await contact_service.update_contact_field(
            contact_id=1,
            field_name="is_favourite",
            field_value="true",
            transaction=mock_transaction,
        )

        assert old_value == "False"
        assert new_value == "True"
        
        # Verify contact was saved with boolean value
        saved_contact = mock_contact_repo.save.call_args[0][0]
        assert saved_contact.is_favourite is True

    @pytest.mark.asyncio
    async def test_update_is_favourite_with_boolean(
        self, contact_service, mock_contact_repo, sample_contact
    ):
        """Test updating is_favourite field with boolean value."""
        mock_contact_repo.find_by_id.return_value = sample_contact
        mock_transaction = AsyncMock()

        old_value, new_value = await contact_service.update_contact_field(
            contact_id=1,
            field_name="is_favourite",
            field_value=True,
            transaction=mock_transaction,
        )

        assert old_value == "False"
        assert new_value == "True"
        
        saved_contact = mock_contact_repo.save.call_args[0][0]
        assert saved_contact.is_favourite is True

    @pytest.mark.asyncio
    async def test_update_field_no_change(
        self, contact_service, mock_contact_repo, mock_history_service, mock_event_publisher, sample_contact
    ):
        """Test updating field with same value (no change)."""
        mock_contact_repo.find_by_id.return_value = sample_contact
        mock_transaction = AsyncMock()

        old_value, new_value = await contact_service.update_contact_field(
            contact_id=1,
            field_name="first_name",
            field_value="John",  # Same as current value
            transaction=mock_transaction,
        )

        assert old_value == "John"
        assert new_value == "John"
        
        # Verify no save, history, or event operations were performed
        mock_contact_repo.save.assert_not_called()
        mock_history_service.record_contact_change.assert_not_called()
        mock_event_publisher.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_field_with_none_value(
        self, contact_service, mock_contact_repo, sample_contact
    ):
        """Test updating field with None value."""
        mock_contact_repo.find_by_id.return_value = sample_contact
        mock_transaction = AsyncMock()

        old_value, new_value = await contact_service.update_contact_field(
            contact_id=1,
            field_name="middle_name",
            field_value=None,
            transaction=mock_transaction,
        )

        assert old_value == "William"
        assert new_value is None
        
        saved_contact = mock_contact_repo.save.call_args[0][0]
        assert saved_contact.middle_name is None

    @pytest.mark.asyncio
    async def test_update_invalid_field_name(
        self, contact_service, mock_contact_repo, sample_contact
    ):
        """Test updating with invalid field name."""
        mock_contact_repo.find_by_id.return_value = sample_contact
        mock_transaction = AsyncMock()

        with pytest.raises(ContactValidationError, match="Invalid field name 'invalid_field'"):
            await contact_service.update_contact_field(
                contact_id=1,
                field_name="invalid_field",
                field_value="test",
                transaction=mock_transaction,
            )

    @pytest.mark.asyncio
    async def test_update_field_contact_not_found(
        self, contact_service, mock_contact_repo
    ):
        """Test updating field when contact doesn't exist."""
        mock_contact_repo.find_by_id.return_value = None
        mock_transaction = AsyncMock()

        with pytest.raises(Exception):  # Should raise an exception when contact not found
            await contact_service.update_contact_field(
                contact_id=999,
                field_name="first_name",
                field_value="test",
                transaction=mock_transaction,
            )

    @pytest.mark.asyncio
    async def test_update_all_valid_fields(
        self, contact_service, mock_contact_repo, sample_contact
    ):
        """Test that all valid field names are accepted."""
        mock_contact_repo.find_by_id.return_value = sample_contact
        mock_transaction = AsyncMock()

        valid_fields = ["first_name", "last_name", "middle_name", "nick_name", "is_favourite"]
        
        for field_name in valid_fields:
            mock_contact_repo.reset_mock()

            await contact_service.update_contact_field(
                contact_id=1,
                field_name=field_name,
                field_value="test_value" if field_name != "is_favourite" else True,
                transaction=mock_transaction,
            )

            # Verify the field was processed without error
            mock_contact_repo.save.assert_called_once()


class TestContactMethodFieldUpdate:
    """Test contact method field update functionality."""

    @pytest.fixture
    def mock_contact_repo(self):
        """Mock contact repository."""
        return AsyncMock()

    @pytest.fixture
    def mock_tag_repo(self):
        """Mock tag repository."""
        return AsyncMock()

    @pytest.fixture
    def mock_history_service(self):
        """Mock contact history service."""
        return AsyncMock()

    @pytest.fixture
    def mock_event_publisher(self):
        """Mock event publisher."""
        return AsyncMock()

    @pytest.fixture
    def mock_validation_service(self):
        """Mock validation service."""
        return AsyncMock()

    @pytest.fixture
    def mock_address_validation_service(self):
        """Mock address validation service."""
        return AsyncMock()

    @pytest.fixture
    def mock_tag_hierarchy_service(self):
        """Mock tag hierarchy service."""
        return AsyncMock()

    @pytest.fixture
    def mock_history_repo(self):
        """Mock history repository."""
        return AsyncMock()

    @pytest.fixture
    def contact_service(
        self,
        mock_contact_repo,
        mock_tag_repo,
        mock_history_repo,
        mock_event_publisher,
        mock_address_validation_service,
        mock_validation_service,
        mock_history_service,
        mock_tag_hierarchy_service,
    ):
        """Create contact service with mocked dependencies."""
        return ContactService(
            contact_repo=mock_contact_repo,
            tag_repo=mock_tag_repo,
            history_repo=mock_history_repo,
            event_publisher=mock_event_publisher,
            address_validation_service=mock_address_validation_service,
            contact_validation_service=mock_validation_service,
            history_service=mock_history_service,
            tag_hierarchy_service=mock_tag_hierarchy_service,
        )

    @pytest.fixture
    def sample_contact_with_method(self):
        """Create a sample contact with a method for testing."""
        from app.core.contacts.models.entities import Contact, ContactMethod, MethodType

        method = ContactMethod(
            id=1,
            contact_id=1,
            method_type=MethodType.EMAIL,
            value="john@example.com",
            label="Work",
            is_primary=False,
        )

        contact = Contact(
            id=1,
            first_name="John",
            last_name="Doe",
            methods=[method],
        )
        return contact

    @pytest.mark.asyncio
    async def test_update_method_value(
        self, contact_service, mock_contact_repo, mock_history_service, mock_event_publisher, sample_contact_with_method
    ):
        """Test updating method value field."""
        mock_contact_repo.find_by_id.return_value = sample_contact_with_method
        mock_transaction = AsyncMock()

        old_value, new_value = await contact_service.update_contact_method_field(
            contact_id=1,
            method_id=1,
            field_name="value",
            field_value="newemail@example.com",
            transaction=mock_transaction,
        )

        assert old_value == "john@example.com"
        assert new_value == "newemail@example.com"

        # Verify method was updated
        mock_contact_repo.update_method.assert_called_once()
        updated_method = mock_contact_repo.update_method.call_args[0][0]
        assert updated_method.value == "newemail@example.com"

        # Verify history was recorded
        mock_history_service.record_method_change.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_method_is_primary(
        self, contact_service, mock_contact_repo, sample_contact_with_method
    ):
        """Test updating method is_primary field."""
        mock_contact_repo.find_by_id.return_value = sample_contact_with_method
        mock_transaction = AsyncMock()

        old_value, new_value = await contact_service.update_contact_method_field(
            contact_id=1,
            method_id=1,
            field_name="is_primary",
            field_value="true",
            transaction=mock_transaction,
        )

        assert old_value == "False"
        assert new_value == "True"

        updated_method = mock_contact_repo.update_method.call_args[0][0]
        assert updated_method.is_primary is True

    @pytest.mark.asyncio
    async def test_update_method_invalid_field(
        self, contact_service, mock_contact_repo, sample_contact_with_method
    ):
        """Test updating method with invalid field name."""
        mock_contact_repo.find_by_id.return_value = sample_contact_with_method
        mock_transaction = AsyncMock()

        with pytest.raises(ContactValidationError, match="Invalid method field name 'invalid_field'"):
            await contact_service.update_contact_method_field(
                contact_id=1,
                method_id=1,
                field_name="invalid_field",
                field_value="test",
                transaction=mock_transaction,
            )

    @pytest.mark.asyncio
    async def test_update_method_not_found(
        self, contact_service, mock_contact_repo, sample_contact_with_method
    ):
        """Test updating method that doesn't exist."""
        mock_contact_repo.find_by_id.return_value = sample_contact_with_method
        mock_transaction = AsyncMock()

        with pytest.raises(ContactValidationError, match="Method with ID 999 not found"):
            await contact_service.update_contact_method_field(
                contact_id=1,
                method_id=999,  # Non-existent method ID
                field_name="value",
                field_value="test@example.com",
                transaction=mock_transaction,
            )
