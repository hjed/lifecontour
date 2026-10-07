"""Integration tests for ContactRepository with real database."""

import pytest
from core_shared.models.contacts.entities import (
    Contact,
    ContactAddress,
    ContactMethod,
    ContactNote,
    ImportantDate,
    MethodType,
    Tag,
)
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)
from core_shared.models.contacts.value_objects import TagName
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql import SqlContactRepository, SqlTagRepository
from app.core.contacts.adapters.sql.custom_date_type_repository import (
    SqlCustomDateTypeRepository,
)
from app.core.contacts.models.exceptions import (
    CustomDateTypeNotFoundError,
    DuplicateBirthdayError,
    DuplicateEmailError,
    ImportantDateNotFoundError,
)
from tests.integration.contact_seeding import TEST_USER_ID, seed_contact


@pytest.mark.integration
class TestContactRepositoryIntegration:
    """Integration tests for ContactRepository with real database."""

    @pytest.fixture
    def contact_repo(self, clean_database: AsyncConnection):
        """Create ContactRepository instance with real database connection."""
        return SqlContactRepository(clean_database)

    @pytest.fixture
    def tag_repo(self, clean_database: AsyncConnection):
        """Create TagRepository instance with real database connection."""
        return SqlTagRepository(clean_database)

    @pytest.mark.asyncio
    async def test_save_new_contact(self, contact_repo):
        """Test saving a new contact to database."""
        # Arrange
        contact = Contact(
            user_id=TEST_USER_ID,
            first_name="John",
            last_name="Doe",
            middle_name="William",
        )

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
        contact = Contact(user_id=TEST_USER_ID, first_name="John", last_name="Smith")
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
        contact = Contact(user_id=TEST_USER_ID, first_name="Jane", last_name="Smith")
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
        contact = Contact(user_id=TEST_USER_ID, first_name="John", last_name="Doe")
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
        contact = Contact(user_id=TEST_USER_ID, first_name="John", last_name="Doe")
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
        contact1 = Contact(user_id=TEST_USER_ID, first_name="John", last_name="Doe")
        saved_contact1 = await contact_repo.save(contact1)

        method1 = ContactMethod(
            method_type=MethodType.EMAIL,
            value="duplicate@example.com",
            contact_id=saved_contact1.id,
            is_primary=True,
        )
        await contact_repo.add_method(saved_contact1.id, method1)

        # Create second contact
        contact2 = Contact(user_id=TEST_USER_ID, first_name="Jane", last_name="Smith")
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
        contact1 = Contact(user_id=TEST_USER_ID, first_name="John", last_name="Doe")
        saved_contact1 = await contact_repo.save(contact1)

        method1 = ContactMethod(
            method_type=MethodType.EMAIL,
            value="duplicate@example.com",
            contact_id=saved_contact1.id,
            is_primary=True,
        )
        await contact_repo.add_method(saved_contact1.id, method1)

        contact2 = Contact(user_id=TEST_USER_ID, first_name="Jane", last_name="Smith")
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
        first_contact_id = await seed_contact(
            clean_database, first_name="John", last_name="Doe"
        )
        second_contact_id = await seed_contact(
            clean_database, first_name="Jane", last_name="Smith"
        )

        await clean_database.execute(
            text(
                """
                INSERT INTO contact_methods (contact_id, method_type, value, is_primary)
                VALUES (:contact_id, 'email', :value, true)
                """
            ),
            {"contact_id": first_contact_id, "value": "  duplicate@example.com  "},
        )

        with pytest.raises(IntegrityError):
            await clean_database.execute(
                text(
                    """
                    INSERT INTO contact_methods (contact_id, method_type, value, is_primary)
                    VALUES (:contact_id, 'email', :value, true)
                    """
                ),
                {"contact_id": second_contact_id, "value": "DUPLICATE@example.com"},
            )

    @pytest.mark.asyncio
    async def test_add_address_success(self, contact_repo):
        """Test adding a contact address."""
        # Arrange
        contact = Contact(user_id=TEST_USER_ID, first_name="John", last_name="Doe")
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
    async def test_archived_method_and_address_round_trip(
        self, contact_repo: SqlContactRepository
    ) -> None:
        """is_archived is written on insert and update, and read back."""
        contact = await contact_repo.save(
            Contact(user_id=TEST_USER_ID, first_name="Arch")
        )
        assert contact.id is not None
        method = await contact_repo.add_method(
            contact.id,
            ContactMethod(
                method_type=MethodType.PHONE,
                value="+61 2 1234 5678",
                contact_id=contact.id,
                is_archived=True,
            ),
        )
        address = await contact_repo.add_address(
            contact.id,
            ContactAddress(
                street_line_1="1 Childhood Rd",
                country_code="AU",
                contact_id=contact.id,
                is_archived=True,
            ),
        )

        loaded = await contact_repo.find_by_id(contact.id)
        assert loaded is not None
        assert [m.is_archived for m in loaded.methods or []] == [True]
        assert [a.is_archived for a in loaded.addresses or []] == [True]

        method.is_archived = False
        address.is_archived = False
        await contact_repo.update_method(method)
        await contact_repo.update_address(address)

        assert method.id is not None
        assert address.id is not None
        reloaded_method = await contact_repo.find_method_by_id(method.id)
        reloaded_address = await contact_repo.find_address_by_id(address.id)
        assert reloaded_method is not None
        assert reloaded_method.is_archived is False
        assert reloaded_address is not None
        assert reloaded_address.is_archived is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("table", "columns", "values"),
        [
            (
                "contact_methods",
                "contact_id, method_type, value",
                ":contact_id, 'phone', '+61 2 1234 5678'",
            ),
            (
                "contact_addresses",
                "contact_id, street_line_1, country_code",
                ":contact_id, '1 Main St', 'AU'",
            ),
        ],
    )
    async def test_database_refuses_archived_primary(
        self,
        contact_repo: SqlContactRepository,
        clean_database: AsyncConnection,
        table: str,
        columns: str,
        values: str,
    ) -> None:
        """The CHECK constraint backs the entity invariant."""
        contact = await contact_repo.save(
            Contact(user_id=TEST_USER_ID, first_name="Check")
        )

        with pytest.raises(IntegrityError, match="archived_not_primary"):
            async with clean_database.begin_nested():
                await clean_database.execute(
                    text(
                        f"INSERT INTO {table} ({columns}, is_primary, is_archived) "  # noqa: S608
                        f"VALUES ({values}, true, true)"
                    ),
                    {"contact_id": contact.id},
                )

    @pytest.mark.asyncio
    async def test_find_by_email_matches_archived_email(
        self, contact_repo: SqlContactRepository
    ) -> None:
        """An archived email still identifies its contact."""
        contact = await contact_repo.save(
            Contact(user_id=TEST_USER_ID, first_name="Old")
        )
        assert contact.id is not None
        await contact_repo.add_method(
            contact.id,
            ContactMethod(
                method_type=MethodType.EMAIL,
                value="old.address@example.com",
                contact_id=contact.id,
                is_archived=True,
            ),
        )

        found = await contact_repo.find_by_email("old.address@example.com")

        assert found is not None
        assert found.id == contact.id

    @pytest.mark.asyncio
    async def test_add_note_success(self, contact_repo):
        """Test adding a contact note."""
        # Arrange
        contact = Contact(user_id=TEST_USER_ID, first_name="John", last_name="Doe")
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
        contact = Contact(user_id=TEST_USER_ID, first_name="John", last_name="Doe")
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
        contact1 = Contact(user_id=TEST_USER_ID, first_name="John", last_name="Doe")
        contact2 = Contact(user_id=TEST_USER_ID, first_name="Jane", last_name="Smith")
        contact3 = Contact(user_id=TEST_USER_ID, first_name="Bob", last_name="Johnson")

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
        contact1 = Contact(user_id=TEST_USER_ID, first_name="John", last_name="Doe")
        contact2 = Contact(user_id=TEST_USER_ID, first_name="Jane", last_name="Smith")

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
        contact = Contact(
            user_id=TEST_USER_ID,
            first_name="Favourite",
            last_name="User",
            is_favourite=True,
        )

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
        contact1 = Contact(
            user_id=TEST_USER_ID, first_name="Fav1", last_name="User", is_favourite=True
        )
        contact2 = Contact(
            user_id=TEST_USER_ID, first_name="Fav2", last_name="User", is_favourite=True
        )
        contact3 = Contact(
            user_id=TEST_USER_ID,
            first_name="Regular",
            last_name="User",
            is_favourite=False,
        )

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
        contact1 = Contact(
            user_id=TEST_USER_ID,
            first_name="FavCount1",
            last_name="User",
            is_favourite=True,
        )
        contact2 = Contact(
            user_id=TEST_USER_ID,
            first_name="FavCount2",
            last_name="User",
            is_favourite=True,
        )
        contact3 = Contact(
            user_id=TEST_USER_ID,
            first_name="RegularCount",
            last_name="User",
            is_favourite=False,
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
        contact1 = Contact(
            user_id=TEST_USER_ID,
            first_name="FilterFav1",
            last_name="User",
            is_favourite=True,
        )
        contact2 = Contact(
            user_id=TEST_USER_ID,
            first_name="FilterFav2",
            last_name="User",
            is_favourite=True,
        )
        contact3 = Contact(
            user_id=TEST_USER_ID,
            first_name="FilterReg",
            last_name="User",
            is_favourite=False,
        )

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

    @pytest.mark.asyncio
    async def test_get_contacts_count_by_filters_favourite_only(self, contact_repo):
        """Test counting contacts by favourite status."""
        # Arrange
        await contact_repo.save(
            Contact(
                user_id=TEST_USER_ID,
                first_name="CountFav1",
                last_name="User",
                is_favourite=True,
            )
        )
        await contact_repo.save(
            Contact(
                user_id=TEST_USER_ID,
                first_name="CountFav2",
                last_name="User",
                is_favourite=True,
            )
        )
        await contact_repo.save(
            Contact(
                user_id=TEST_USER_ID,
                first_name="CountReg",
                last_name="User",
                is_favourite=False,
            )
        )

        # Act
        count = await contact_repo.get_contacts_count_by_filters(is_favourite=True)

        # Assert
        assert count == 2

    @pytest.mark.asyncio
    async def test_get_contacts_count_by_filters_counts_tag_matches_distinctly(
        self, contact_repo, tag_repo
    ):
        """Test filtered contact counts stay distinct when one contact matches multiple tags."""
        # Arrange
        contact_with_both_tags = await contact_repo.save(
            Contact(user_id=TEST_USER_ID, first_name="Multi", last_name="Match")
        )
        contact_with_one_tag = await contact_repo.save(
            Contact(user_id=TEST_USER_ID, first_name="Single", last_name="Match")
        )
        await contact_repo.save(
            Contact(user_id=TEST_USER_ID, first_name="Other", last_name="Contact")
        )

        work_tag = await tag_repo.save(Tag(name=TagName("work")))
        client_tag = await tag_repo.save(Tag(name=TagName("client")))

        await contact_repo.assign_tag(contact_with_both_tags.id, work_tag.id)
        await contact_repo.assign_tag(contact_with_both_tags.id, client_tag.id)
        await contact_repo.assign_tag(contact_with_one_tag.id, work_tag.id)

        # Act
        count = await contact_repo.get_contacts_count_by_filters(
            tag_ids=[work_tag.id, client_tag.id]
        )

        # Assert
        assert count == 2


@pytest.mark.integration
class TestContactOwnerPersistence:
    """``contacts.user_id`` is written once, on insert, and read back everywhere."""

    OTHER_OWNER = "other-user-456"

    @pytest.fixture
    def contact_repo(self, clean_database: AsyncConnection) -> SqlContactRepository:
        return SqlContactRepository(clean_database)

    @pytest.mark.asyncio
    async def test_save_persists_the_owner(
        self, contact_repo: SqlContactRepository
    ) -> None:
        saved = await contact_repo.save(Contact(first_name="Ada", user_id=TEST_USER_ID))

        assert saved.id is not None
        found = await contact_repo.find_by_id(saved.id)
        assert found is not None
        assert found.user_id == TEST_USER_ID

    @pytest.mark.asyncio
    async def test_list_reads_carry_the_owner(
        self, contact_repo: SqlContactRepository
    ) -> None:
        await contact_repo.save(
            Contact(first_name="Ada", user_id=TEST_USER_ID, is_favourite=True)
        )

        favourites = await contact_repo.get_favourite_contacts()
        filtered = await contact_repo.get_contacts_by_filters(is_favourite=True)

        assert [c.user_id for c in favourites] == [TEST_USER_ID]
        assert [c.user_id for c in filtered] == [TEST_USER_ID]

    @pytest.mark.asyncio
    async def test_saving_an_existing_contact_never_changes_its_owner(
        self, contact_repo: SqlContactRepository
    ) -> None:
        """A contact's owner is set at creation; an update cannot re-own it."""
        saved = await contact_repo.save(Contact(first_name="Ada", user_id=TEST_USER_ID))
        assert saved.id is not None

        saved.user_id = self.OTHER_OWNER
        saved.last_name = "Lovelace"
        await contact_repo.save(saved)

        found = await contact_repo.find_by_id(saved.id)
        assert found is not None
        assert (found.last_name, found.user_id) == ("Lovelace", TEST_USER_ID)


@pytest.mark.integration
class TestImportantDateRepositoryIntegration:
    """Integration tests for the repository's important-date writes."""

    @pytest.fixture
    def contact_repo(self, clean_database: AsyncConnection) -> SqlContactRepository:
        """Create ContactRepository instance with real database connection."""
        return SqlContactRepository(clean_database)

    @pytest.fixture
    def custom_date_type_repo(
        self, clean_database: AsyncConnection
    ) -> SqlCustomDateTypeRepository:
        """Create CustomDateTypeRepository instance with real database connection."""
        return SqlCustomDateTypeRepository(clean_database)

    @staticmethod
    async def _contact_with_date(
        contact_repo: SqlContactRepository, date: ImportantDate
    ) -> tuple[Contact, ImportantDate]:
        """Persist a contact carrying one important date, returning both."""
        contact = await contact_repo.save(
            Contact(user_id=TEST_USER_ID, first_name="Date", last_name="Owner")
        )
        assert contact.id is not None
        date.contact_id = contact.id
        saved_date = await contact_repo.add_important_date(contact.id, date)
        return contact, saved_date

    @pytest.mark.asyncio
    async def test_update_important_date_rewrites_every_column(
        self, contact_repo: SqlContactRepository
    ) -> None:
        """An update replaces type, precision and all three date components."""
        # Arrange - a year-only work anniversary
        contact, saved_date = await self._contact_with_date(
            contact_repo,
            ImportantDate(
                contact_id=0,
                date_type=ImportantDateType.WORK_ANNIVERSARY,
                precision=DatePrecision.YEAR,
                year=2020,
            ),
        )

        assert contact.id is not None

        # Act - become a full-precision first-met date
        saved_date.date_type = ImportantDateType.FIRST_MET
        saved_date.precision = DatePrecision.FULL
        saved_date.year = 2015
        saved_date.month = 3
        saved_date.day = 9
        returned = await contact_repo.update_important_date(saved_date)

        # Assert - both the returned entity and the stored row
        assert returned.id == saved_date.id
        assert returned.updated_at is not None

        stored = await contact_repo.get_important_dates(contact.id)
        assert len(stored) == 1, "an update must not insert a second row"
        assert stored[0].id == saved_date.id
        assert stored[0].date_type == ImportantDateType.FIRST_MET
        assert stored[0].precision == DatePrecision.FULL
        assert stored[0].year == 2015
        assert stored[0].month == 3
        assert stored[0].day == 9

    @pytest.mark.asyncio
    async def test_update_important_date_clears_components_precision_drops(
        self, contact_repo: SqlContactRepository
    ) -> None:
        """Narrowing precision nulls the components the new precision excludes."""
        # Arrange - a full-precision first-met date
        contact, saved_date = await self._contact_with_date(
            contact_repo,
            ImportantDate(
                contact_id=0,
                date_type=ImportantDateType.FIRST_MET,
                precision=DatePrecision.FULL,
                year=2015,
                month=3,
                day=9,
            ),
        )

        assert contact.id is not None

        # Act - drop to year-only
        saved_date.precision = DatePrecision.YEAR
        saved_date.month = None
        saved_date.day = None
        await contact_repo.update_important_date(saved_date)

        # Assert
        stored = await contact_repo.get_important_dates(contact.id)
        assert stored[0].precision == DatePrecision.YEAR
        assert stored[0].year == 2015
        assert stored[0].month is None
        assert stored[0].day is None

    @pytest.mark.asyncio
    async def test_update_birthday_in_place_does_not_violate_uniqueness(
        self, contact_repo: SqlContactRepository
    ) -> None:
        """Editing the contact's only birthday is not a second birthday.

        ``uq_contact_birthday`` is a partial unique index on ``contact_id``
        where ``date_type = 'birthday'``. An in-place UPDATE of that same row
        leaves one birthday, so it must be allowed - this is the ordinary case
        of a user correcting a birth year.
        """
        # Arrange
        contact, saved_date = await self._contact_with_date(
            contact_repo,
            ImportantDate(
                contact_id=0,
                date_type=ImportantDateType.BIRTHDAY,
                precision=DatePrecision.FULL,
                year=1990,
                month=5,
                day=15,
            ),
        )

        assert contact.id is not None

        # Act
        saved_date.year = 1991
        await contact_repo.update_important_date(saved_date)

        # Assert
        stored = await contact_repo.get_important_dates(contact.id)
        assert len(stored) == 1
        assert stored[0].year == 1991

    @pytest.mark.asyncio
    async def test_update_to_second_birthday_raises_duplicate_birthday(
        self, contact_repo: SqlContactRepository
    ) -> None:
        """Retyping a second date as a birthday hits the partial unique index."""
        # Arrange - a contact with a birthday and a work anniversary
        contact, _birthday = await self._contact_with_date(
            contact_repo,
            ImportantDate(
                contact_id=0,
                date_type=ImportantDateType.BIRTHDAY,
                precision=DatePrecision.DAY_MONTH,
                month=5,
                day=15,
            ),
        )
        assert contact.id is not None
        other = await contact_repo.add_important_date(
            contact.id,
            ImportantDate(
                contact_id=contact.id,
                date_type=ImportantDateType.WORK_ANNIVERSARY,
                precision=DatePrecision.YEAR,
                year=2020,
            ),
        )

        # Act / Assert
        other.date_type = ImportantDateType.BIRTHDAY
        with pytest.raises(DuplicateBirthdayError):
            await contact_repo.update_important_date(other)

    @pytest.mark.asyncio
    async def test_update_important_date_to_custom_type(
        self,
        contact_repo: SqlContactRepository,
        custom_date_type_repo: SqlCustomDateTypeRepository,
    ) -> None:
        """A date can be retyped as custom, and reads back with the type name."""
        # Arrange
        contact, saved_date = await self._contact_with_date(
            contact_repo,
            ImportantDate(
                contact_id=0,
                date_type=ImportantDateType.FIRST_MET,
                precision=DatePrecision.YEAR,
                year=2015,
            ),
        )
        assert contact.id is not None
        custom_type = await custom_date_type_repo.create("Adoption Day")

        # Act
        saved_date.date_type = ImportantDateType.CUSTOM
        saved_date.custom_date_type_id = custom_type.id
        await contact_repo.update_important_date(saved_date)

        # Assert - the name comes from the join, not the written row
        stored = await contact_repo.get_important_dates(contact.id)
        assert stored[0].date_type == ImportantDateType.CUSTOM
        assert stored[0].custom_date_type_id == custom_type.id
        assert stored[0].custom_date_type_name == "Adoption Day"

    @pytest.mark.asyncio
    async def test_update_important_date_unknown_custom_type_raises(
        self, contact_repo: SqlContactRepository
    ) -> None:
        """A custom type id with no row behind it is refused by the FK."""
        # Arrange
        _contact, saved_date = await self._contact_with_date(
            contact_repo,
            ImportantDate(
                contact_id=0,
                date_type=ImportantDateType.FIRST_MET,
                precision=DatePrecision.YEAR,
                year=2015,
            ),
        )

        # Act / Assert
        saved_date.date_type = ImportantDateType.CUSTOM
        saved_date.custom_date_type_id = 999999
        with pytest.raises(CustomDateTypeNotFoundError):
            await contact_repo.update_important_date(saved_date)

    @pytest.mark.asyncio
    async def test_update_important_date_unknown_id_raises_not_found(
        self, contact_repo: SqlContactRepository
    ) -> None:
        """Updating a date that does not exist is reported, not silently ignored."""
        # Arrange
        contact = await contact_repo.save(
            Contact(user_id=TEST_USER_ID, first_name="No", last_name="Date")
        )
        assert contact.id is not None
        missing = ImportantDate(
            id=999999,
            contact_id=contact.id,
            date_type=ImportantDateType.BIRTHDAY,
            precision=DatePrecision.YEAR,
            year=1990,
        )

        # Act / Assert
        with pytest.raises(ImportantDateNotFoundError):
            await contact_repo.update_important_date(missing)
