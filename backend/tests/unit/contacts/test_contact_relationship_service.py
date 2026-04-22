"""Tests for ContactRelationshipService."""

from unittest.mock import AsyncMock

import pytest
from core_shared.models.contacts.entities import (
    Contact,
    ContactRelationship,
    RelationshipType,
)
from core_shared.models.contacts.exceptions import ContactValidationError

from app.core.contacts.models.exceptions import (
    ContactNotFoundError,
)
from app.core.contacts.services.contact_relationship_service import (
    ContactRelationshipService,
)


class TestContactRelationshipService:
    """Test ContactRelationshipService."""

    @pytest.fixture
    def mock_contact_repo(self):
        """Create mock contact repository."""
        return AsyncMock()

    @pytest.fixture
    def mock_relationship_repo(self):
        """Create mock relationship repository."""
        return AsyncMock()

    @pytest.fixture
    def mock_transaction(self):
        """Create mock transaction."""
        return AsyncMock()

    @pytest.fixture
    def mock_event_publisher(self):
        """Create mock event publisher."""
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_contact_repo, mock_relationship_repo, mock_event_publisher):
        """Create ContactRelationshipService instance."""
        return ContactRelationshipService(
            mock_contact_repo, mock_relationship_repo, mock_event_publisher
        )

    @pytest.fixture
    def sample_contact_1(self):
        """Create sample contact 1."""
        return Contact(
            id=1,
            first_name="John",
            last_name="Doe",
        )

    @pytest.fixture
    def sample_contact_2(self):
        """Create sample contact 2."""
        return Contact(
            id=2,
            first_name="Jane",
            last_name="Smith",
        )

    @pytest.fixture
    def sample_relationship(self):
        """Create sample relationship."""
        return ContactRelationship(
            id=1,
            from_contact_id=1,
            to_contact_id=2,
            relationship_type=RelationshipType.FRIEND,
        )

    @pytest.mark.asyncio
    async def test_create_relationship_success(
        self,
        service,
        mock_contact_repo,
        mock_relationship_repo,
        mock_transaction,
        mock_event_publisher,
        sample_contact_1,
        sample_contact_2,
    ):
        """Test successful relationship creation."""
        # Setup mocks
        mock_contact_repo.find_by_id.side_effect = [sample_contact_1, sample_contact_2]
        mock_relationship_repo.create.return_value = ContactRelationship(
            id=1,
            from_contact_id=1,
            to_contact_id=2,
            relationship_type=RelationshipType.FRIEND,
        )

        # Create relationship
        relationship = await service.create_relationship(
            from_contact_id=1,
            to_contact_id=2,
            relationship_type=RelationshipType.FRIEND,
        )

        # Verify
        assert relationship.from_contact_id == 1
        assert relationship.to_contact_id == 2
        assert relationship.relationship_type == RelationshipType.FRIEND
        mock_contact_repo.find_by_id.assert_any_call(1)
        mock_contact_repo.find_by_id.assert_any_call(2)
        mock_relationship_repo.create.assert_called_once()
        mock_event_publisher.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_relationship_from_contact_not_found(
        self,
        service,
        mock_contact_repo,
        mock_relationship_repo,
        mock_transaction,
    ):
        """Test relationship creation when from_contact doesn't exist."""
        mock_contact_repo.find_by_id.return_value = None

        with pytest.raises(ContactNotFoundError):
            await service.create_relationship(
                from_contact_id=999,
                to_contact_id=2,
                relationship_type=RelationshipType.FRIEND,
            )

        mock_relationship_repo.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_relationship_to_contact_not_found(
        self,
        service,
        mock_contact_repo,
        mock_relationship_repo,
        mock_transaction,
        sample_contact_1,
    ):
        """Test relationship creation when to_contact doesn't exist."""
        mock_contact_repo.find_by_id.side_effect = [sample_contact_1, None]

        with pytest.raises(ContactNotFoundError):
            await service.create_relationship(
                from_contact_id=1,
                to_contact_id=999,
                relationship_type=RelationshipType.FRIEND,
            )

        mock_relationship_repo.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_relationship_self_relationship(
        self,
        service,
        mock_contact_repo,
        mock_relationship_repo,
        mock_transaction,
        sample_contact_1,
    ):
        """Test that self-relationships are prevented."""
        # from-contact exists, but self-reference should still be rejected
        mock_contact_repo.find_by_id.return_value = sample_contact_1

        with pytest.raises(ContactValidationError) as exc_info:
            await service.create_relationship(
                from_contact_id=1,
                to_contact_id=1,
                relationship_type=RelationshipType.FRIEND,
            )

        assert "cannot have a relationship with itself" in str(exc_info.value)
        # from-contact is validated first, then self-reference is caught
        mock_contact_repo.find_by_id.assert_called_once_with(1)
        mock_relationship_repo.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_bidirectional_relationship(
        self,
        service,
        mock_contact_repo,
        mock_relationship_repo,
        mock_transaction,
        mock_event_publisher,
        sample_contact_1,
        sample_contact_2,
    ):
        """Test bidirectional relationship creation."""
        # Setup mocks
        mock_contact_repo.find_by_id.side_effect = [sample_contact_1, sample_contact_2]
        mock_relationship_repo.create.side_effect = [
            ContactRelationship(
                id=1,
                from_contact_id=1,
                to_contact_id=2,
                relationship_type=RelationshipType.PARTNER,
            ),
            ContactRelationship(
                id=2,
                from_contact_id=2,
                to_contact_id=1,
                relationship_type=RelationshipType.PARTNER,
            ),
        ]

        # Create bidirectional relationship
        relationships = await service.create_relationship(
            from_contact_id=1,
            to_contact_id=2,
            relationship_type=RelationshipType.PARTNER,
            create_bidirectional=True,
        )

        # Verify both relationships created
        assert len(relationships) == 2
        assert relationships[0].from_contact_id == 1
        assert relationships[0].to_contact_id == 2
        assert relationships[1].from_contact_id == 2
        assert relationships[1].to_contact_id == 1
        assert mock_relationship_repo.create.call_count == 2
        assert mock_event_publisher.publish.call_count == 2

    @pytest.mark.asyncio
    async def test_get_relationships_for_contact(
        self,
        service,
        mock_relationship_repo,
        sample_relationship,
    ):
        """Test getting relationships for a contact."""
        mock_relationship_repo.get_relationships_for_contact.return_value = [
            sample_relationship
        ]

        relationships = await service.get_relationships_for_contact(1)

        assert len(relationships) == 1
        assert relationships[0] == sample_relationship
        mock_relationship_repo.get_relationships_for_contact.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_update_relationship_success(
        self,
        service,
        mock_relationship_repo,
        mock_transaction,
        mock_event_publisher,
        sample_relationship,
    ):
        """Test successful relationship update."""
        updated_relationship = ContactRelationship(
            id=1,
            from_contact_id=1,
            to_contact_id=2,
            relationship_type=RelationshipType.COLLEAGUE,
        )
        mock_relationship_repo.get_by_id.return_value = sample_relationship
        mock_relationship_repo.update.return_value = updated_relationship

        result = await service.update_relationship(
            relationship_id=1,
            relationship_type=RelationshipType.COLLEAGUE,
        )

        assert result.relationship_type == RelationshipType.COLLEAGUE
        mock_relationship_repo.get_by_id.assert_called_once_with(1)
        mock_relationship_repo.update.assert_called_once()
        mock_event_publisher.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_relationship_not_found(
        self,
        service,
        mock_relationship_repo,
        mock_transaction,
    ):
        """Test updating non-existent relationship."""
        mock_relationship_repo.get_by_id.return_value = None

        with pytest.raises(ContactValidationError) as exc_info:
            await service.update_relationship(
                relationship_id=999,
                relationship_type=RelationshipType.COLLEAGUE,
            )

        assert "Relationship with ID 999 not found" in str(exc_info.value)
        mock_relationship_repo.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_relationship_success(
        self,
        service,
        mock_relationship_repo,
        mock_transaction,
        mock_event_publisher,
        sample_relationship,
    ):
        """Test successful relationship deletion."""
        mock_relationship_repo.get_by_id.return_value = sample_relationship

        await service.delete_relationship(
            relationship_id=1,
        )

        mock_relationship_repo.get_by_id.assert_called_once_with(1)
        mock_relationship_repo.delete.assert_called_once_with(1)
        mock_event_publisher.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_relationship_not_found(
        self,
        service,
        mock_relationship_repo,
        mock_transaction,
    ):
        """Test deleting non-existent relationship."""
        mock_relationship_repo.get_by_id.return_value = None

        with pytest.raises(ContactValidationError) as exc_info:
            await service.delete_relationship(
                relationship_id=999,
            )

        assert "Relationship with ID 999 not found" in str(exc_info.value)
        mock_relationship_repo.delete.assert_not_called()
