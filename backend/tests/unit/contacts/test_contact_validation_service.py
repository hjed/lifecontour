"""Tests for ContactValidationService."""

from unittest.mock import AsyncMock

import pytest
from core_shared.models.contacts.entities import Contact, Tag
from core_shared.models.contacts.exceptions import ContactValidationError
from core_shared.models.contacts.value_objects import TagName

from app.core.contacts.models.exceptions import (
    ContactNotFoundError,
    DuplicateEmailError,
    TooManyTagsError,
)
from app.core.contacts.services.contact_validation_service import (
    ContactValidationService,
)


class TestContactValidationService:
    """Test ContactValidationService."""

    @pytest.fixture
    def mock_contact_repo(self):
        """Create mock contact repository."""
        return AsyncMock()

    @pytest.fixture
    def mock_transaction(self):
        """Create mock transaction."""
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_contact_repo):
        """Create ContactValidationService instance."""
        return ContactValidationService(mock_contact_repo)

    @pytest.mark.asyncio
    async def test_validate_email_uniqueness_no_existing_contact(
        self, service, mock_contact_repo, mock_transaction
    ):
        """Test email uniqueness validation when no existing contact."""
        mock_contact_repo.find_by_email.return_value = None

        await service.validate_email_uniqueness("test@example.com", mock_transaction)

        mock_contact_repo.find_by_email.assert_called_once_with("test@example.com")

    @pytest.mark.asyncio
    async def test_validate_email_uniqueness_existing_contact_same_id(
        self, service, mock_contact_repo, mock_transaction
    ):
        """Test email uniqueness validation when existing contact has same ID."""
        existing_contact = Contact(first_name="John", id=1)
        mock_contact_repo.find_by_email.return_value = existing_contact

        await service.validate_email_uniqueness(
            "test@example.com", mock_transaction, exclude_contact_id=1
        )

        mock_contact_repo.find_by_email.assert_called_once_with("test@example.com")

    @pytest.mark.asyncio
    async def test_validate_email_uniqueness_existing_contact_different_id_raises_error(
        self, service, mock_contact_repo, mock_transaction
    ):
        """Test email uniqueness validation raises error when existing contact has different ID."""
        existing_contact = Contact(first_name="John", id=2)
        mock_contact_repo.find_by_email.return_value = existing_contact

        with pytest.raises(DuplicateEmailError):
            await service.validate_email_uniqueness(
                "test@example.com", mock_transaction, exclude_contact_id=1
            )

    @pytest.mark.asyncio
    async def test_validate_email_uniqueness_existing_contact_no_exclude_raises_error(
        self, service, mock_contact_repo, mock_transaction
    ):
        """Test email uniqueness validation raises error when no exclude ID provided."""
        existing_contact = Contact(first_name="John", id=2)
        mock_contact_repo.find_by_email.return_value = existing_contact

        with pytest.raises(DuplicateEmailError):
            await service.validate_email_uniqueness(
                "test@example.com", mock_transaction
            )

    @pytest.mark.asyncio
    async def test_validate_email_uniqueness_existing_contact_no_id_raises_error(
        self, service, mock_contact_repo, mock_transaction
    ):
        """Test email uniqueness validation raises error when existing contact has no ID."""
        existing_contact = Contact(first_name="John", id=None)
        mock_contact_repo.find_by_email.return_value = existing_contact

        with pytest.raises(ContactValidationError) as exc_info:
            await service.validate_email_uniqueness(
                "test@example.com", mock_transaction
            )

        assert exc_info.value.field == "contact_id"
        assert "Existing contact has no ID" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_validate_primary_method_contact_exists(
        self, service, mock_contact_repo, mock_transaction
    ):
        """Test primary method validation when contact exists."""
        contact = Contact(first_name="John", id=1)
        mock_contact_repo.find_by_id.return_value = contact

        await service.validate_primary_method(1, "email", mock_transaction)

        mock_contact_repo.find_by_id.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_validate_primary_method_contact_not_found_raises_error(
        self, service, mock_contact_repo, mock_transaction
    ):
        """Test primary method validation raises error when contact not found."""
        mock_contact_repo.find_by_id.return_value = None

        with pytest.raises(ContactNotFoundError):
            await service.validate_primary_method(1, "email", mock_transaction)

    @pytest.mark.asyncio
    async def test_validate_primary_address_contact_exists(
        self, service, mock_contact_repo, mock_transaction
    ):
        """Test primary address validation when contact exists."""
        contact = Contact(first_name="John", id=1)
        mock_contact_repo.find_by_id.return_value = contact

        await service.validate_primary_address(1, mock_transaction)

        mock_contact_repo.find_by_id.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_validate_primary_address_contact_not_found_raises_error(
        self, service, mock_contact_repo, mock_transaction
    ):
        """Test primary address validation raises error when contact not found."""
        mock_contact_repo.find_by_id.return_value = None

        with pytest.raises(ContactNotFoundError):
            await service.validate_primary_address(1, mock_transaction)

    @pytest.mark.asyncio
    async def test_validate_contact_exists_contact_found(
        self, service, mock_contact_repo, mock_transaction
    ):
        """Test contact exists validation when contact found."""
        contact = Contact(first_name="John", id=1)
        mock_contact_repo.find_by_id.return_value = contact

        await service.validate_contact_exists(1, mock_transaction)

        mock_contact_repo.find_by_id.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_validate_contact_exists_contact_not_found_raises_error(
        self, service, mock_contact_repo, mock_transaction
    ):
        """Test contact exists validation raises error when contact not found."""
        mock_contact_repo.find_by_id.return_value = None

        with pytest.raises(ContactNotFoundError):
            await service.validate_contact_exists(1, mock_transaction)

    @pytest.mark.asyncio
    async def test_validate_contact_tag_limit_under_limit(
        self, service, mock_contact_repo, mock_transaction
    ):
        """Test tag limit validation when under limit."""
        contact = Contact(first_name="John", id=1)
        # Add 24 tags (under limit of 25)
        for i in range(24):
            contact.tags.append(Tag(name=TagName(f"tag{i}"), id=i))

        mock_contact_repo.find_by_id.return_value = contact

        await service.validate_contact_tag_limit(1, mock_transaction)

        mock_contact_repo.find_by_id.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_validate_contact_tag_limit_at_limit_raises_error(
        self, service, mock_contact_repo, mock_transaction
    ):
        """Test tag limit validation raises error when at limit."""
        contact = Contact(first_name="John", id=1)
        # Add 25 tags (at limit)
        for i in range(25):
            contact.tags.append(Tag(name=TagName(f"tag{i}"), id=i))

        mock_contact_repo.find_by_id.return_value = contact

        with pytest.raises(TooManyTagsError):
            await service.validate_contact_tag_limit(1, mock_transaction)

    @pytest.mark.asyncio
    async def test_validate_contact_tag_limit_contact_not_found_raises_error(
        self, service, mock_contact_repo, mock_transaction
    ):
        """Test tag limit validation raises error when contact not found."""
        mock_contact_repo.find_by_id.return_value = None

        with pytest.raises(ContactNotFoundError):
            await service.validate_contact_tag_limit(1, mock_transaction)
