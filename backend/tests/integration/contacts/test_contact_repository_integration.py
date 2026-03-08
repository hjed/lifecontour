"""Integration tests for ContactRepository with real database."""

import pytest
from core_shared.models.contacts.entities import (
    Contact,
    ContactAddress,
    ContactMethod,
    ContactNote,
    MethodType,
)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql import SqlContactRepository
from app.core.contacts.models.exceptions import (
    DuplicateEmailError,
)


@pytest.mark.integration
class TestContactRepositoryIntegration:
    """Integration tests for ContactRepository with real database."""

    @pytest.fixture
    def contact_repo(self, clean_database: AsyncConnection):
        """Create ContactRepository instance with real database connection."""
        return SqlContactRepository(clean_database)

    @pytest.mark.asyncio
    async def test_save_new_contact(self, contact_repo):
        """Test saving a new contact to database."""
        # Arrange
        contact = Contact(first_name="John", last_name="Doe", middle_name="William")

        # Act
        saved_contact = await contact_repo.save(contact)

        # Assert
        assert saved_contact.id is not None
        assert saved_contact.first_name == "John"
        assert saved_contact.last_name == "Doe"
        assert saved_contact.middle_name == "William"
        assert saved_contact.created_at is not None
        assert saved_contact.updated_at is not None

    @pytest.mark.asyncio
    async def test_save_update_existing_contact(self, contact_repo):
        """Test updating an existing contact in database."""
        # Arrange - Create contact
        contact = Contact(first_name="John", last_name="Smith")
        saved_contact = await contact_repo.save(contact)

        # Update contact
        saved_contact.last_name = "Doe"
        saved_contact.nick_name = "Johnny"

        # Act
        updated_contact = await contact_repo.save(saved_contact)

        # Assert
        assert updated_contact.id == saved_contact.id
        assert updated_contact.first_name == "John"
        assert updated_contact.last_name == "Doe"
        assert updated_contact.nick_name == "Johnny"
        assert updated_contact.updated_at is not None

        # Verify the contact was actually updated in the database
        found_contact = await contact_repo.find_by_id(saved_contact.id)
        assert found_contact.last_name == "Doe"
        assert found_contact.nick_name == "Johnny"

    @pytest.mark.asyncio
    async def test_find_by_id_existing(self, contact_repo):
        """Test finding contact by ID when it exists."""
        # Arrange
        contact = Contact(first_name="Jane", last_name="Smith")
        saved_contact = await contact_repo.save(contact)

        # Act
        found_contact = await contact_repo.find_by_id(saved_contact.id)

        # Assert
        assert found_contact is not None
        assert found_contact.id == saved_contact.id
        assert found_contact.first_name == "Jane"
        assert found_contact.last_name == "Smith"

    @pytest.mark.asyncio
    async def test_find_by_id_not_existing(self, contact_repo):
        """Test finding contact by ID when it doesn't exist."""
        # Act
        found_contact = await contact_repo.find_by_id(999)

        # Assert
        assert found_contact is None

    @pytest.mark.asyncio
    async def test_find_by_email_existing(self, contact_repo):
        """Test finding contact by email when it exists."""
        # Arrange
        contact = Contact(first_name="John", last_name="Doe")
        saved_contact = await contact_repo.save(contact)

        # Add email method
        email_method = ContactMethod(
            method_type=MethodType.EMAIL,
            value="john.doe@example.com",
            contact_id=saved_contact.id,
            is_primary=True,
        )
        await contact_repo.add_method(saved_contact.id, email_method)

        # Act
        found_contact = await contact_repo.find_by_email("john.doe@example.com")

        # Assert
        assert found_contact is not None
        assert found_contact.id == saved_contact.id
        assert found_contact.first_name == "John"

    @pytest.mark.asyncio
    async def test_find_by_email_not_existing(self, contact_repo):
        """Test finding contact by email when it doesn't exist."""
        # Act
        found_contact = await contact_repo.find_by_email("nonexistent@example.com")

        # Assert
        assert found_contact is None

    @pytest.mark.asyncio
    async def test_add_method_success(self, contact_repo):
        """Test adding a contact method."""
        # Arrange
        contact = Contact(first_name="John", last_name="Doe")
        saved_contact = await contact_repo.save(contact)

        method = ContactMethod(
            method_type=MethodType.EMAIL,
            value="john@example.com",
            contact_id=saved_contact.id,
            is_primary=True,
            label="Work",
        )

        # Act
        saved_method = await contact_repo.add_method(saved_contact.id, method)

        # Assert
        assert saved_method.id is not None
        assert saved_method.method_type == MethodType.EMAIL
        assert saved_method.value == "john@example.com"
        assert saved_method.is_primary is True
        assert saved_method.label == "Work"

    @pytest.mark.asyncio
    async def test_add_method_duplicate_email_raises_error(self, contact_repo):
        """Test adding duplicate email raises error."""
        # Arrange - Create first contact with email
        contact1 = Contact(first_name="John", last_name="Doe")
        saved_contact1 = await contact_repo.save(contact1)

        method1 = ContactMethod(
            method_type=MethodType.EMAIL,
            value="duplicate@example.com",
            contact_id=saved_contact1.id,
            is_primary=True,
        )
        await contact_repo.add_method(saved_contact1.id, method1)

        # Create second contact
        contact2 = Contact(first_name="Jane", last_name="Smith")
        saved_contact2 = await contact_repo.save(contact2)

        method2 = ContactMethod(
            method_type=MethodType.EMAIL,
            value="duplicate@example.com",
            contact_id=saved_contact2.id,
            is_primary=True,
        )

        # Act & Assert
        with pytest.raises(DuplicateEmailError):
            await contact_repo.add_method(saved_contact2.id, method2)

    @pytest.mark.asyncio
    async def test_add_method_case_insensitive_duplicate_email_raises_error(
        self, contact_repo
    ):
        """Test adding a case-equivalent duplicate email raises error."""
        contact1 = Contact(first_name="John", last_name="Doe")
        saved_contact1 = await contact_repo.save(contact1)

        method1 = ContactMethod(
            method_type=MethodType.EMAIL,
            value="duplicate@example.com",
            contact_id=saved_contact1.id,
            is_primary=True,
        )
        await contact_repo.add_method(saved_contact1.id, method1)

        contact2 = Contact(first_name="Jane", last_name="Smith")
        saved_contact2 = await contact_repo.save(contact2)

        method2 = ContactMethod(
            method_type=MethodType.EMAIL,
            value="DUPLICATE@example.com",
            contact_id=saved_contact2.id,
            is_primary=True,
        )

        with pytest.raises(DuplicateEmailError):
            await contact_repo.add_method(saved_contact2.id, method2)

    @pytest.mark.asyncio
    async def test_normalized_email_unique_index_rejects_whitespace_and_case_variants(
        self, clean_database: AsyncConnection
    ):
        """Test DB uniqueness uses trimmed/lowercased email semantics."""
        first_contact_row = (
            await clean_database.execute(
                text(
                    """
                    INSERT INTO contacts (first_name, last_name)
                    VALUES (:first_name, :last_name)
                    RETURNING id
                    """
                ),
                {"first_name": "John", "last_name": "Doe"},
            )
        ).fetchone()
        assert first_contact_row is not None

        second_contact_row = (
            await clean_database.execute(
                text(
                    """
                    INSERT INTO contacts (first_name, last_name)
                    VALUES (:first_name, :last_name)
                    RETURNING id
                    """
                ),
                {"first_name": "Jane", "last_name": "Smith"},
            )
        ).fetchone()
        assert second_contact_row is not None

        await clean_database.execute(
            text(
                """
                INSERT INTO contact_methods (contact_id, method_type, value, is_primary)
                VALUES (:contact_id, 'email', :value, true)
                """
            ),
            {"contact_id": first_contact_row.id, "value": "  duplicate@example.com  "},
        )

        with pytest.raises(IntegrityError):
            await clean_database.execute(
                text(
                    """
                    INSERT INTO contact_methods (contact_id, method_type, value, is_primary)
                    VALUES (:contact_id, 'email', :value, true)
                    """
                ),
                {"contact_id": second_contact_row.id, "value": "DUPLICATE@example.com"},
            )

    @pytest.mark.asyncio
    async def test_add_address_success(self, contact_repo):
        """Test adding a contact address."""
        # Arrange
        contact = Contact(first_name="John", last_name="Doe")
        saved_contact = await contact_repo.save(contact)

        address = ContactAddress(
            street_line_1="123 Main St",
            street_line_2="Apt 4B",
            locality="New York",
            region="NY",
            postal_code="10001",
            country_code="US",
            contact_id=saved_contact.id,
            is_primary=True,
            label="Home",
        )

        # Act
        saved_address = await contact_repo.add_address(saved_contact.id, address)

        # Assert
        assert saved_address.id is not None
        assert saved_address.street_line_1 == "123 Main St"
        assert saved_address.street_line_2 == "Apt 4B"
        assert saved_address.locality == "New York"
        assert saved_address.region == "NY"
        assert saved_address.postal_code == "10001"
        assert saved_address.country_code == "US"
        assert saved_address.is_primary is True
        assert saved_address.label == "Home"

    @pytest.mark.asyncio
    async def test_add_note_success(self, contact_repo):
        """Test adding a contact note."""
        # Arrange
        contact = Contact(first_name="John", last_name="Doe")
        saved_contact = await contact_repo.save(contact)

        note = ContactNote(
            content="This is a test note about the contact", contact_id=saved_contact.id
        )

        # Act
        saved_note = await contact_repo.add_note(saved_contact.id, note)

        # Assert
        assert saved_note.id is not None
        assert saved_note.content == "This is a test note about the contact"
        assert saved_note.contact_id == saved_contact.id
        assert saved_note.created_at is not None

    @pytest.mark.asyncio
    async def test_delete_contact(self, contact_repo):
        """Test deleting a contact."""
        # Arrange
        contact = Contact(first_name="John", last_name="Doe")
        saved_contact = await contact_repo.save(contact)

        # Act
        await contact_repo.delete(saved_contact.id)

        # Assert - Contact should no longer exist
        found_contact = await contact_repo.find_by_id(saved_contact.id)
        assert found_contact is None

    @pytest.mark.asyncio
    async def test_search_contacts(self, contact_repo):
        """Test searching contacts by text."""
        # Arrange - Create multiple contacts
        contact1 = Contact(first_name="John", last_name="Doe")
        contact2 = Contact(first_name="Jane", last_name="Smith")
        contact3 = Contact(first_name="Bob", last_name="Johnson")

        await contact_repo.save(contact1)
        await contact_repo.save(contact2)
        await contact_repo.save(contact3)

        # Act
        results = await contact_repo.search("John")

        # Assert
        assert len(results) >= 1
        found_names = [f"{c.first_name} {c.last_name}" for c in results]
        assert any("John" in name for name in found_names)

    @pytest.mark.asyncio
    async def test_get_all_contacts(self, contact_repo):
        """Test getting all contacts."""
        # Arrange - Create multiple contacts
        contact1 = Contact(first_name="John", last_name="Doe")
        contact2 = Contact(first_name="Jane", last_name="Smith")

        await contact_repo.save(contact1)
        await contact_repo.save(contact2)

        # Act
        all_contacts = await contact_repo.get_all()

        # Assert
        assert len(all_contacts) >= 2
        names = [f"{c.first_name} {c.last_name}" for c in all_contacts]
        assert "John Doe" in names
        assert "Jane Smith" in names

    @pytest.mark.asyncio
    async def test_save_contact_with_favourite(self, contact_repo):
        """Test saving a contact with favourite flag."""
        # Arrange
        contact = Contact(first_name="Favourite", last_name="User", is_favourite=True)

        # Act
        saved_contact = await contact_repo.save(contact)

        # Assert
        assert saved_contact.id is not None
        assert saved_contact.is_favourite is True

        # Verify retrieval
        retrieved = await contact_repo.find_by_id(saved_contact.id)
        assert retrieved is not None
        assert retrieved.is_favourite is True

    @pytest.mark.asyncio
    async def test_get_favourite_contacts(self, contact_repo):
        """Test getting favourite contacts."""
        # Arrange - Create contacts with different favourite status
        contact1 = Contact(first_name="Fav1", last_name="User", is_favourite=True)
        contact2 = Contact(first_name="Fav2", last_name="User", is_favourite=True)
        contact3 = Contact(first_name="Regular", last_name="User", is_favourite=False)

        await contact_repo.save(contact1)
        await contact_repo.save(contact2)
        await contact_repo.save(contact3)

        # Act
        favourites = await contact_repo.get_favourite_contacts()

        # Assert
        assert len(favourites) >= 2  # At least the two we just created
        favourite_names = [c.first_name for c in favourites]
        assert "Fav1" in favourite_names
        assert "Fav2" in favourite_names
        assert "Regular" not in favourite_names

    @pytest.mark.asyncio
    async def test_get_favourite_contacts_count(self, contact_repo):
        """Test getting count of favourite contacts."""
        # Arrange - Create contacts with different favourite status
        contact1 = Contact(first_name="FavCount1", last_name="User", is_favourite=True)
        contact2 = Contact(first_name="FavCount2", last_name="User", is_favourite=True)
        contact3 = Contact(
            first_name="RegularCount", last_name="User", is_favourite=False
        )

        await contact_repo.save(contact1)
        await contact_repo.save(contact2)
        await contact_repo.save(contact3)

        # Act
        count = await contact_repo.get_favourite_contacts_count()

        # Assert
        assert count >= 2  # At least the two we just created

    @pytest.mark.asyncio
    async def test_get_contacts_by_filters_favourite_only(self, contact_repo):
        """Test filtering contacts by favourite status."""
        # Arrange - Create contacts with different favourite status
        contact1 = Contact(first_name="FilterFav1", last_name="User", is_favourite=True)
        contact2 = Contact(first_name="FilterFav2", last_name="User", is_favourite=True)
        contact3 = Contact(first_name="FilterReg", last_name="User", is_favourite=False)

        await contact_repo.save(contact1)
        await contact_repo.save(contact2)
        await contact_repo.save(contact3)

        # Act
        filtered = await contact_repo.get_contacts_by_filters(is_favourite=True)

        # Assert
        assert len(filtered) >= 2  # At least the two we just created
        filtered_names = [c.first_name for c in filtered]
        assert "FilterFav1" in filtered_names
        assert "FilterFav2" in filtered_names
        assert "FilterReg" not in filtered_names
