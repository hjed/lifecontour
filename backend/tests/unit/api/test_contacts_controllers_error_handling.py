"""
Unit tests for contacts controller error handling.

Tests that domain exceptions are properly handled and not caught by generic exception handlers.
"""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.contacts.controllers import (
    create_contact,
    delete_contact,
    remove_tag_from_contact,
    update_contact,
)
from app.api.contacts.schemas import (
    ContactAttributes,
    ContactDataRequest,
    ContactRequest,
)
from app.core.contacts.models.entities import Contact
from app.core.contacts.models.exceptions import (
    ContactNotFoundError,
    ContactValidationError,
    DuplicateEmailError,
    PrimaryMethodConflictError,
    TagNotFoundError,
)


@pytest.mark.asyncio
class TestCreateContactErrorHandling:
    """Test create_contact endpoint error handling."""

    async def test_create_contact_duplicate_email_bubbles_up(self):
        """Test that DuplicateEmailError bubbles up instead of being caught as generic exception."""
        # Arrange
        mock_service = AsyncMock()
        mock_service.create_contact_api.side_effect = DuplicateEmailError("test@example.com", 123)

        request = ContactRequest(
            data=ContactDataRequest(
                attributes=ContactAttributes(first_name="John", last_name="Doe")
            )
        )

        # Act & Assert - The exception should bubble up, not be caught
        with pytest.raises(DuplicateEmailError):
            await create_contact(mock_service, request)

    async def test_create_contact_validation_error_bubbles_up(self):
        """Test that ContactValidationError bubbles up instead of being caught as generic exception."""
        # Arrange
        mock_service = AsyncMock()
        mock_service.create_contact_api.side_effect = ContactValidationError("first_name", "First name is required")

        request = ContactRequest(
            data=ContactDataRequest(
                attributes=ContactAttributes(first_name="", last_name="Doe")
            )
        )

        # Act & Assert - The exception should bubble up, not be caught
        with pytest.raises(ContactValidationError):
            await create_contact(mock_service, request)

    async def test_create_contact_primary_method_conflict_bubbles_up(self):
        """Test that PrimaryMethodConflictError bubbles up instead of being caught as generic exception."""
        # Arrange
        mock_service = AsyncMock()
        mock_service.create_contact_api.side_effect = PrimaryMethodConflictError(123, "email")

        request = ContactRequest(
            data=ContactDataRequest(
                attributes=ContactAttributes(first_name="John", last_name="Doe")
            )
        )

        # Act & Assert - The exception should bubble up, not be caught
        with pytest.raises(PrimaryMethodConflictError):
            await create_contact(mock_service, request)

    async def test_create_contact_http_exception_is_reraised(self):
        """Test that HTTPException is properly re-raised."""
        # Arrange
        mock_service = AsyncMock()
        mock_service.create_contact_api.side_effect = HTTPException(status_code=400, detail="Bad request")

        request = ContactRequest(
            data=ContactDataRequest(
                attributes=ContactAttributes(first_name="John", last_name="Doe")
            )
        )

        # Act & Assert
        with pytest.raises(HTTPException) as exc_info:
            await create_contact(mock_service, request)

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Bad request"

    async def test_create_contact_generic_exception_becomes_500(self):
        """Test that truly generic exceptions become 500 errors."""
        # Arrange
        mock_service = AsyncMock()
        mock_service.create_contact_api.side_effect = ValueError("Unexpected error")

        request = ContactRequest(
            data=ContactDataRequest(
                attributes=ContactAttributes(first_name="John", last_name="Doe")
            )
        )

        # Act & Assert
        with pytest.raises(HTTPException) as exc_info:
            await create_contact(mock_service, request)

        assert exc_info.value.status_code == 500
        assert "Internal server error" in exc_info.value.detail


@pytest.mark.asyncio
class TestUpdateContactErrorHandling:
    """Test update_contact endpoint error handling."""

    async def test_update_contact_contact_not_found_bubbles_up(self):
        """Test that ContactNotFoundError from service bubbles up."""
        # Arrange
        mock_service = AsyncMock()
        mock_service.get_contact_by_id.return_value = Contact(id=1, first_name="John", last_name="Doe")
        mock_service.update_contact_with_existing_api.side_effect = ContactNotFoundError(999)

        request = ContactRequest(
            data=ContactDataRequest(
                attributes=ContactAttributes(first_name="Jane", last_name="Doe")
            )
        )

        # Act & Assert - The exception should bubble up, not be caught
        with pytest.raises(ContactNotFoundError):
            await update_contact(mock_service, request, 999)


@pytest.mark.asyncio
class TestDeleteContactErrorHandling:
    """Test delete_contact endpoint error handling."""

    async def test_delete_contact_not_found_bubbles_up(self):
        """Test that ContactNotFoundError bubbles up from delete service."""
        # Arrange
        mock_service = AsyncMock()
        mock_service.delete_contact_api.side_effect = ContactNotFoundError(999)

        # Act & Assert - The exception should bubble up, not be caught
        with pytest.raises(ContactNotFoundError):
            await delete_contact(mock_service, 999)


@pytest.mark.asyncio
class TestRemoveTagErrorHandling:
    """Test remove_tag_from_contact endpoint error handling."""

    async def test_remove_tag_contact_not_found_bubbles_up(self):
        """Test that ContactNotFoundError bubbles up from remove tag service."""
        # Arrange
        mock_service = AsyncMock()
        mock_service.remove_tag_from_contact_api.side_effect = ContactNotFoundError(999)

        # Act & Assert - The exception should bubble up, not be caught
        with pytest.raises(ContactNotFoundError):
            await remove_tag_from_contact(mock_service, 999, 1)

    async def test_remove_tag_tag_not_found_bubbles_up(self):
        """Test that TagNotFoundError bubbles up from remove tag service."""
        # Arrange
        mock_service = AsyncMock()
        mock_service.remove_tag_from_contact_api.side_effect = TagNotFoundError(999)

        # Act & Assert - The exception should bubble up, not be caught
        with pytest.raises(TagNotFoundError):
            await remove_tag_from_contact(mock_service, 1, 999)
