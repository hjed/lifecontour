"""Unit tests for contact field update functionality."""

from unittest.mock import AsyncMock

import pytest
from core_shared.models.contacts.exceptions import ContactValidationError

from app.core.contacts.models.exceptions import ContactNotFoundError
from app.core.contacts.services.contact_service import ContactService

# Import shared fixtures and factory functions
from tests.fixtures.contact_fixtures import (
    create_basic_contact,
    create_contact_with_methods,
)
from tests.integration.contact_seeding import TEST_USER_ID


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
        """Create a sample contact for basic field testing."""
        return create_basic_contact(
            contact_id=1,
            first_name="John",
            last_name="Doe",
            middle_name="William",
            nick_name="Johnny",
        )

    @pytest.mark.asyncio
    async def test_update_first_name(
        self,
        contact_service,
        mock_contact_repo,
        mock_history_service,
        mock_event_publisher,
        sample_contact,
    ):
        """Test updating first name field."""
        mock_contact_repo.find_by_id.return_value = sample_contact
        mock_transaction = AsyncMock()

        old_value, new_value = await contact_service.update_contact_field(
            contact_id=1,
            field_name="first_name",
            field_value="Jonathan",
            transaction=mock_transaction,
            user_id=TEST_USER_ID,
        )

        assert old_value == "John"
        assert new_value == "Jonathan"

        # Verify contact was saved with updated value
        mock_contact_repo.save.assert_called_once()
        saved_contact = mock_contact_repo.save.call_args[0][0]
        assert saved_contact.first_name == "Jonathan"

        # History is now derived from the published ContactUpdated event
        # (ITER12-003 Phase 2); the dual-write no longer runs.
        mock_history_service.record_contact_change.assert_not_called()
        mock_event_publisher.publish.assert_called_once()
        published = mock_event_publisher.publish.call_args[0][0]
        assert published.event_type == "ContactUpdated"
        assert published.event_data["contact_id"] == 1
        assert published.event_data["changed_fields"] == {
            "first_name": ("John", "Jonathan")
        }

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
            user_id=TEST_USER_ID,
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
            user_id=TEST_USER_ID,
        )

        assert old_value == "False"
        assert new_value == "True"

        saved_contact = mock_contact_repo.save.call_args[0][0]
        assert saved_contact.is_favourite is True

    @pytest.mark.asyncio
    async def test_update_field_no_change(
        self,
        contact_service,
        mock_contact_repo,
        mock_history_service,
        mock_event_publisher,
        sample_contact,
    ):
        """Test updating field with same value (no change)."""
        mock_contact_repo.find_by_id.return_value = sample_contact
        mock_transaction = AsyncMock()

        old_value, new_value = await contact_service.update_contact_field(
            contact_id=1,
            field_name="first_name",
            field_value="John",  # Same as current value
            transaction=mock_transaction,
            user_id=TEST_USER_ID,
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
            user_id=TEST_USER_ID,
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

        with pytest.raises(
            ContactValidationError, match="Invalid field name 'invalid_field'"
        ):
            await contact_service.update_contact_field(
                contact_id=1,
                field_name="invalid_field",
                field_value="test",
                transaction=mock_transaction,
                user_id=TEST_USER_ID,
            )

    @pytest.mark.asyncio
    async def test_update_field_contact_not_found(
        self, contact_service, mock_contact_repo
    ):
        """Test updating field when contact doesn't exist."""
        mock_contact_repo.find_by_id.return_value = None
        mock_transaction = AsyncMock()

        with pytest.raises(ContactNotFoundError):
            await contact_service.update_contact_field(
                contact_id=999,
                field_name="first_name",
                field_value="test",
                transaction=mock_transaction,
                user_id=TEST_USER_ID,
            )

    @pytest.mark.asyncio
    async def test_update_all_valid_fields(
        self, contact_service, mock_contact_repo, sample_contact
    ):
        """Test that all valid field names are accepted."""
        mock_contact_repo.find_by_id.return_value = sample_contact
        mock_transaction = AsyncMock()

        valid_fields = [
            "first_name",
            "last_name",
            "middle_name",
            "nick_name",
            "is_favourite",
        ]

        for field_name in valid_fields:
            mock_contact_repo.reset_mock()

            await contact_service.update_contact_field(
                contact_id=1,
                field_name=field_name,
                field_value="test_value" if field_name != "is_favourite" else True,
                transaction=mock_transaction,
                user_id=TEST_USER_ID,
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
        """Create a contact with a method that has ID=1 for testing."""
        return create_contact_with_methods(
            contact_id=1,
            email_method_id=1,
            phone_method_id=2,
        )

    @pytest.mark.asyncio
    async def test_update_method_value(
        self,
        contact_service,
        mock_contact_repo,
        mock_history_service,
        mock_event_publisher,
        sample_contact_with_method,
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
            user_id=TEST_USER_ID,
        )

        assert old_value == "john.doe@example.com"
        assert new_value == "newemail@example.com"

        # Verify method was updated
        mock_contact_repo.update_method.assert_called_once()
        updated_method = mock_contact_repo.update_method.call_args[0][0]
        assert updated_method.value == "newemail@example.com"

        # History is now derived from the published ContactUpdated event with the
        # per-sub-entity key (ITER12-003 Phase 2); the dual-write no longer runs.
        mock_history_service.record_method_change.assert_not_called()
        published = mock_event_publisher.publish.call_args[0][0]
        assert published.event_type == "ContactUpdated"
        assert published.event_data["changed_fields"] == {
            "method_1_value": ("john.doe@example.com", "newemail@example.com")
        }

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
            field_value="false",
            transaction=mock_transaction,
            user_id=TEST_USER_ID,
        )

        assert old_value == "True"
        assert new_value == "False"

        updated_method = mock_contact_repo.update_method.call_args[0][0]
        assert updated_method.is_primary is False

    @pytest.mark.asyncio
    async def test_update_method_invalid_field(
        self, contact_service, mock_contact_repo, sample_contact_with_method
    ):
        """Test updating method with invalid field name."""
        mock_contact_repo.find_by_id.return_value = sample_contact_with_method
        mock_transaction = AsyncMock()

        with pytest.raises(
            ContactValidationError, match="Invalid method field name 'invalid_field'"
        ):
            await contact_service.update_contact_method_field(
                contact_id=1,
                method_id=1,
                field_name="invalid_field",
                field_value="test",
                transaction=mock_transaction,
                user_id=TEST_USER_ID,
            )

    @pytest.mark.asyncio
    async def test_update_method_not_found(
        self, contact_service, mock_contact_repo, sample_contact_with_method
    ):
        """Test updating method that doesn't exist."""
        mock_contact_repo.find_by_id.return_value = sample_contact_with_method
        mock_transaction = AsyncMock()

        with pytest.raises(
            ContactValidationError, match="Method with ID 999 not found"
        ):
            await contact_service.update_contact_method_field(
                contact_id=1,
                method_id=999,  # Non-existent method ID
                field_name="value",
                field_value="test@example.com",
                transaction=mock_transaction,
                user_id=TEST_USER_ID,
            )
