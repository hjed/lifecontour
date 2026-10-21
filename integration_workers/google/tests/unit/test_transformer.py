"""
Unit tests for Google Contacts transformer.

Tests the GoogleContactTransformer for converting Google People API
responses to internal Contact entities.
"""

import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, "/core_shared")

from core_shared.models.contacts.entities import Contact, MethodType
from core_shared.models.contacts.sync_scope import ContactSyncField
from core_shared.models.outbox_events import SkippedAddress

from api_models import (
    GoogleAddress,
    GoogleBiography,
    GoogleContactGroupMembership,
    GoogleEmailAddress,
    GoogleFieldMetadata,
    GoogleMembership,
    GoogleName,
    GoogleNickname,
    GoogleOrganization,
    GooglePerson,
    GooglePhoneNumber,
)
from group_translator import GoogleGroupNameTranslator
from transformer import GOOGLE_CONTACT_SYNC_SCOPE, GoogleContactTransformer

TEST_USER_ID = "test-user-google"


@pytest.fixture
def transformer() -> GoogleContactTransformer:
    """Create GoogleContactTransformer instance."""
    return GoogleContactTransformer(user_id=TEST_USER_ID)


def test_transform_person_stamps_the_sync_owner(
    transformer: GoogleContactTransformer, sample_google_person: GooglePerson
) -> None:
    """Every contact the transformer builds belongs to the syncing user."""
    contact = transformer.transform_person(sample_google_person)

    assert contact.user_id == TEST_USER_ID


@pytest.fixture
def sample_google_person() -> GooglePerson:
    """Create a sample GooglePerson for testing."""
    return GooglePerson(
        resourceName="people/c123456789",
        etag="test_etag_123",
        names=[
            GoogleName(
                metadata=GoogleFieldMetadata(primary=True, sourcePrimary=True),
                displayName="John Doe",
                familyName="Doe",
                givenName="John",
                middleName="Michael",
            )
        ],
        emailAddresses=[
            GoogleEmailAddress(
                metadata=GoogleFieldMetadata(primary=True, sourcePrimary=True),
                value="john.doe@example.com",
                type="work",
                formattedType="Work",
            ),
            GoogleEmailAddress(
                metadata=GoogleFieldMetadata(primary=False, sourcePrimary=False),
                value="john.personal@example.com",
                type="home",
                formattedType="Home",
            ),
        ],
        phoneNumbers=[
            GooglePhoneNumber(
                metadata=GoogleFieldMetadata(primary=True, sourcePrimary=True),
                value="+1-555-123-4567",
                canonicalForm="+15551234567",
                type="work",
                formattedType="Work",
            )
        ],
        addresses=[
            GoogleAddress(
                metadata=GoogleFieldMetadata(primary=True, sourcePrimary=True),
                formattedValue="123 Main St, Anytown, CA 12345, USA",
                streetAddress="123 Main St",
                city="Anytown",
                region="CA",
                postalCode="12345",
                country="USA",
                countryCode="US",
                type="home",
            )
        ],
        biographies=[
            GoogleBiography(
                metadata=GoogleFieldMetadata(primary=True, sourcePrimary=True),
                value="Software engineer with 10 years of experience.",
                contentType="TEXT_PLAIN",
            )
        ],
        organizations=[
            GoogleOrganization(
                metadata=GoogleFieldMetadata(primary=True, sourcePrimary=True),
                name="Tech Corp",
                title="Senior Developer",
                type="work",
            )
        ],
        memberships=[
            GoogleMembership(
                metadata=GoogleFieldMetadata(primary=True, sourcePrimary=True),
                contactGroupMembership=GoogleContactGroupMembership(
                    contactGroupId="family",
                    contactGroupResourceName="contactGroups/family",
                ),
            ),
            GoogleMembership(
                metadata=GoogleFieldMetadata(primary=False, sourcePrimary=False),
                contactGroupMembership=GoogleContactGroupMembership(
                    contactGroupId="work-colleagues",
                    contactGroupResourceName="contactGroups/work-colleagues",
                ),
            ),
        ],
    )


class TestGoogleContactTransformer:
    """Test cases for GoogleContactTransformer."""

    def test_transform_person_basic_info(
        self, transformer: GoogleContactTransformer, sample_google_person: GooglePerson
    ) -> None:
        """Test transformation of basic person information."""
        contact = transformer.transform_person(sample_google_person)

        assert isinstance(contact, Contact)
        assert contact.first_name == "John"
        assert contact.last_name == "Doe"
        assert contact.middle_name == "Michael"
        assert contact.nick_name is None
        assert contact.is_favourite is False

    def test_transform_person_basic_structure(
        self, transformer: GoogleContactTransformer, sample_google_person: GooglePerson
    ) -> None:
        """Test that contact has the expected structure."""
        contact = transformer.transform_person(sample_google_person)

        # Check that all collections are initialized
        assert hasattr(contact, "methods")
        assert hasattr(contact, "addresses")
        assert hasattr(contact, "notes")
        assert hasattr(contact, "tags")
        assert isinstance(contact.methods, list)
        assert isinstance(contact.addresses, list)
        assert isinstance(contact.notes, list)
        assert isinstance(contact.tags, list)

    def test_transform_person_email_addresses(
        self, transformer: GoogleContactTransformer, sample_google_person: GooglePerson
    ) -> None:
        """Test transformation of email addresses."""
        contact = transformer.transform_person(sample_google_person)

        email_methods = [
            cm
            for cm in contact.methods
            if cm.method_type == MethodType.EMAIL  # type: ignore[union-attr]
        ]
        assert len(email_methods) == 2

        # Check primary email
        primary_email = next(cm for cm in email_methods if cm.is_primary)
        assert primary_email.value == "john.doe@example.com"
        assert primary_email.label == "Work"  # Should use formatted_type

        # Check secondary email
        secondary_email = next(cm for cm in email_methods if not cm.is_primary)
        assert secondary_email.value == "john.personal@example.com"
        assert secondary_email.label == "Home"  # Should use formatted_type

    def test_transform_person_phone_numbers(
        self, transformer: GoogleContactTransformer, sample_google_person: GooglePerson
    ) -> None:
        """Test transformation of phone numbers."""
        contact = transformer.transform_person(sample_google_person)

        phone_methods = [
            cm
            for cm in contact.methods
            if cm.method_type == MethodType.PHONE  # type: ignore[union-attr]
        ]
        assert len(phone_methods) == 1

        phone = phone_methods[0]
        assert phone.value == "+15551234567"  # Should use canonical form
        assert phone.label == "Work"  # Should use formatted_type
        assert phone.is_primary is True

    def test_transform_person_addresses(
        self, transformer: GoogleContactTransformer, sample_google_person: GooglePerson
    ) -> None:
        """Test transformation of addresses."""
        contact = transformer.transform_person(sample_google_person)

        assert len(contact.addresses) == 1  # type: ignore[arg-type]
        address = contact.addresses[0]  # type: ignore[index]
        assert address.street_line_1 == "123 Main St"
        assert address.locality == "Anytown"
        assert address.region == "CA"
        assert address.postal_code == "12345"
        assert address.country_code == "US"
        assert address.is_primary is True

    def test_transform_person_notes(
        self, transformer: GoogleContactTransformer, sample_google_person: GooglePerson
    ) -> None:
        """Test transformation of biographies to notes."""
        contact = transformer.transform_person(sample_google_person)

        assert len(contact.notes) == 1  # type: ignore[arg-type]
        note = contact.notes[0]  # type: ignore[index]
        assert note.content == "Software engineer with 10 years of experience."

    def test_transform_person_membership_tags(
        self, transformer: GoogleContactTransformer, sample_google_person: GooglePerson
    ) -> None:
        """Test transformation of contact group memberships to tags."""
        contact = transformer.transform_person(sample_google_person)

        assert len(contact.tags) == 2  # type: ignore[arg-type]
        tag_names = [tag.name.value for tag in contact.tags]  # type: ignore[union-attr]
        assert "family" in tag_names  # Contact group ID becomes tag
        assert "work-colleagues" in tag_names  # Contact group ID becomes tag

    def test_transform_person_empty_names(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Test transformation when person has no names."""
        person = GooglePerson(
            resourceName="people/c123456789",
            names=[],
        )

        contact = transformer.transform_person(person)

        assert contact.first_name == "Unknown"  # Fallback when no names provided
        assert contact.last_name is None
        assert contact.middle_name is None
        assert contact.nick_name is None

    def test_transform_person_no_primary_name(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Test transformation when no name is marked as primary."""
        person = GooglePerson(
            resourceName="people/c123456789",
            names=[
                GoogleName(
                    metadata=GoogleFieldMetadata(primary=False),
                    givenName="John",
                    familyName="Doe",
                ),
                GoogleName(
                    metadata=GoogleFieldMetadata(primary=False),
                    givenName="Johnny",
                    familyName="Smith",
                ),
            ],
        )

        contact = transformer.transform_person(person)

        # Should use first name when no primary is found
        assert contact.first_name == "John"
        assert contact.last_name == "Doe"

    def test_transform_person_empty_email_values(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Test transformation handles empty email values gracefully."""
        person = GooglePerson(
            resourceName="people/c123456789",
            emailAddresses=[
                GoogleEmailAddress(value=""),  # Empty value
                GoogleEmailAddress(value="valid@example.com"),
            ],
        )

        contact = transformer.transform_person(person)

        # Should only include valid email
        email_methods = [
            cm
            for cm in contact.methods
            if cm.method_type == MethodType.EMAIL  # type: ignore[union-attr]
        ]
        assert len(email_methods) == 1
        assert email_methods[0].value == "valid@example.com"

    def test_transform_person_invalid_email_values_skipped(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Test transformation skips malformed email values instead of failing."""
        person = GooglePerson(
            resourceName="people/c123456789",
            emailAddresses=[
                GoogleEmailAddress(value="not-an-email"),
                GoogleEmailAddress(value="valid@example.com"),
            ],
        )

        contact = transformer.transform_person(person)

        email_methods = [
            cm
            for cm in contact.methods
            if cm.method_type == MethodType.EMAIL  # type: ignore[union-attr]
        ]
        assert len(email_methods) == 1
        assert email_methods[0].value == "valid@example.com"

    def test_transform_person_invalid_phone_values_skipped(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Test transformation skips phone values that cannot pass validation."""
        person = GooglePerson(
            resourceName="people/c123456789",
            phoneNumbers=[
                GooglePhoneNumber(value="main office"),
                GooglePhoneNumber(value="+61 400 123 456"),
            ],
        )

        contact = transformer.transform_person(person)

        phone_methods = [
            cm
            for cm in contact.methods
            if cm.method_type == MethodType.PHONE  # type: ignore[union-attr]
        ]
        assert len(phone_methods) == 1
        assert phone_methods[0].value == "+61 400 123 456"

    def test_transform_person_address_fallback_to_formatted(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Test address transformation falls back to formatted value when street address is missing."""
        person = GooglePerson(
            resourceName="people/c123456789",
            addresses=[
                GoogleAddress(
                    formattedValue="123 Main St, Anytown, CA 12345",
                    streetAddress=None,  # No street address
                    city="Anytown",
                    region="CA",
                    countryCode="US",  # Required for address creation
                )
            ],
        )

        contact = transformer.transform_person(person)

        assert len(contact.addresses) == 1  # type: ignore[arg-type]
        address = contact.addresses[0]  # type: ignore[index]
        assert address.street_line_1 == "123 Main St, Anytown, CA 12345"
        assert address.locality == "Anytown"
        assert address.region == "CA"

    def test_transform_person_invalid_addresses_skipped(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Test transformation skips invalid addresses instead of failing."""
        person = GooglePerson(
            resourceName="people/c123456789",
            addresses=[
                GoogleAddress(
                    streetAddress="1 Broken Street",
                    countryCode="AUS",
                ),
                GoogleAddress(
                    streetAddress="123 Main St",
                    countryCode="AU",
                ),
            ],
        )

        contact = transformer.transform_person(person)

        assert len(contact.addresses) == 1  # type: ignore[arg-type]
        assert contact.addresses[0].street_line_1 == "123 Main St"  # type: ignore[index]
        assert contact.addresses[0].country_code == "AU"  # type: ignore[index]

    def test_transform_addresses_with_none_metadata_not_primary(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Test address transformation treats None metadata as non-primary."""
        address = SimpleNamespace(
            metadata=None,
            street_address="123 Main St",
            country_code="AU",
            extended_address=None,
            city="Sydney",
            region="NSW",
            postal_code="2000",
        )

        contact_addresses = transformer._transform_addresses([address])

        assert len(contact_addresses) == 1
        assert contact_addresses[0].is_primary is False

    def test_transform_person_blank_biographies_skipped(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Test transformation skips blank biographies instead of failing."""
        person = GooglePerson(
            resourceName="people/c123456789",
            biographies=[
                GoogleBiography(value="   "),
                GoogleBiography(value="Valid note"),
            ],
        )

        contact = transformer.transform_person(person)

        assert len(contact.notes) == 1  # type: ignore[arg-type]
        assert contact.notes[0].content == "Valid note"  # type: ignore[index]

    def test_transform_person_invalid_membership_names_skipped(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Test that invalid membership names are skipped when creating tags."""
        person = GooglePerson(
            resourceName="people/c123456789",
            memberships=[
                GoogleMembership(
                    contactGroupMembership=None  # No membership info
                ),
                GoogleMembership(
                    contactGroupMembership=GoogleContactGroupMembership(
                        contactGroupId="valid-group"
                    )
                ),
                GoogleMembership(
                    contactGroupMembership=GoogleContactGroupMembership(
                        contactGroupId=""  # Empty group ID
                    )
                ),
            ],
        )

        contact = transformer.transform_person(person)

        # Should only create tags for valid group memberships
        tag_names = [tag.name.value for tag in contact.tags]  # type: ignore[union-attr]
        assert "valid-group" in tag_names
        assert len(contact.tags) == 1  # type: ignore[arg-type]

    def test_extract_names_with_primary(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Test name extraction when primary name is available."""
        names = [
            GoogleName(
                metadata=GoogleFieldMetadata(primary=False),
                givenName="Secondary",
                familyName="Name",
            ),
            GoogleName(
                metadata=GoogleFieldMetadata(primary=True),
                givenName="Primary",
                familyName="Name",
                middleName="Middle",
            ),
        ]

        first, last, middle = transformer._extract_names(names)

        assert first == "Primary"
        assert last == "Name"
        assert middle == "Middle"

    def test_extract_names_no_primary(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Test name extraction when no primary name is available."""
        names = [
            GoogleName(
                metadata=GoogleFieldMetadata(primary=False),
                givenName="First",
                familyName="Available",
            ),
        ]

        first, last, middle = transformer._extract_names(names)

        assert first == "First"
        assert last == "Available"
        assert middle is None

    def test_extract_names_empty_list(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Test name extraction with empty names list."""
        first, last, middle = transformer._extract_names([])

        assert first is None
        assert last is None
        assert middle is None

    def test_transform_person_starred_is_favourite(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Test that the 'starred' group makes the contact a favourite and doesn't create a tag."""
        person = GooglePerson(
            resourceName="people/c123",
            names=[GoogleName(givenName="Star", familyName="Person")],
            memberships=[
                GoogleMembership(
                    contactGroupMembership=GoogleContactGroupMembership(
                        contactGroupId="starred",
                        contactGroupResourceName="contactGroups/starred",
                    )
                ),
                GoogleMembership(
                    contactGroupMembership=GoogleContactGroupMembership(
                        contactGroupId="family",
                        contactGroupResourceName="contactGroups/family",
                    )
                ),
            ],
        )

        contact = transformer.transform_person(person)

        assert contact.is_favourite is True
        # "starred" should not become a tag
        tag_names = [tag.name.value for tag in contact.tags]  # type: ignore[union-attr]
        assert "family" in tag_names
        assert "starred" not in tag_names
        assert len(contact.tags) == 1  # type: ignore[arg-type]

    def test_transform_person_ignores_reserved_groups(self) -> None:
        """Test that reserved groups (like myContacts) are ignored and not converted to tags."""
        from group_translator import GoogleGroupNameTranslator

        translator = GoogleGroupNameTranslator(
            reserved_group_ids=["myContacts"], group_mapping={}
        )
        transformer = GoogleContactTransformer(
            user_id=TEST_USER_ID, translator=translator
        )

        person = GooglePerson(
            resourceName="people/c123",
            names=[GoogleName(givenName="Reserved", familyName="Person")],
            memberships=[
                GoogleMembership(
                    contactGroupMembership=GoogleContactGroupMembership(
                        contactGroupId="myContacts",
                        contactGroupResourceName="contactGroups/myContacts",
                    )
                ),
                GoogleMembership(
                    contactGroupMembership=GoogleContactGroupMembership(
                        contactGroupId="friends",
                        contactGroupResourceName="contactGroups/friends",
                    )
                ),
            ],
        )

        contact = transformer.transform_person(person)

        tag_names = [tag.name.value for tag in contact.tags]  # type: ignore[union-attr]
        assert "friends" in tag_names
        assert "myContacts" not in tag_names
        assert len(contact.tags) == 1  # type: ignore[arg-type]


class TestOrganizationTransformation:
    """Tests for organization transformation to company and job_title fields."""

    def test_transform_person_with_current_organization(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Test transformation of current organization to company and job_title."""
        person = GooglePerson(
            resourceName="people/c123456789",
            names=[
                GoogleName(
                    metadata=GoogleFieldMetadata(primary=True),
                    givenName="John",
                    familyName="Doe",
                )
            ],
            organizations=[
                GoogleOrganization(
                    metadata=GoogleFieldMetadata(primary=True),
                    name="Tech Corp",
                    title="Senior Software Engineer",
                    current=True,
                )
            ],
        )

        contact = transformer.transform_person(person)

        assert contact.company == "Tech Corp"
        assert contact.job_title == "Senior Software Engineer"

    def test_transform_person_with_multiple_organizations_uses_current(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Test that current organization is preferred over others."""
        person = GooglePerson(
            resourceName="people/c123456789",
            names=[
                GoogleName(
                    metadata=GoogleFieldMetadata(primary=True),
                    givenName="John",
                    familyName="Doe",
                )
            ],
            organizations=[
                GoogleOrganization(
                    metadata=GoogleFieldMetadata(primary=False),
                    name="Old Company",
                    title="Junior Developer",
                    current=False,
                ),
                GoogleOrganization(
                    metadata=GoogleFieldMetadata(primary=True),
                    name="Current Company",
                    title="Senior Developer",
                    current=True,
                ),
                GoogleOrganization(
                    metadata=GoogleFieldMetadata(primary=False),
                    name="Another Old Company",
                    title="Intern",
                    current=False,
                ),
            ],
        )

        contact = transformer.transform_person(person)

        assert contact.company == "Current Company"
        assert contact.job_title == "Senior Developer"

    def test_transform_person_with_no_current_organization_uses_first(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Test that first organization is used when none are marked current."""
        person = GooglePerson(
            resourceName="people/c123456789",
            names=[
                GoogleName(
                    metadata=GoogleFieldMetadata(primary=True),
                    givenName="John",
                    familyName="Doe",
                )
            ],
            organizations=[
                GoogleOrganization(
                    metadata=GoogleFieldMetadata(primary=True),
                    name="First Company",
                    title="Developer",
                    current=None,  # Not specified
                ),
                GoogleOrganization(
                    metadata=GoogleFieldMetadata(primary=False),
                    name="Second Company",
                    title="Manager",
                    current=None,
                ),
            ],
        )

        contact = transformer.transform_person(person)

        assert contact.company == "First Company"
        assert contact.job_title == "Developer"

    def test_transform_person_with_organization_name_only(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Test transformation when organization has only name (no title)."""
        person = GooglePerson(
            resourceName="people/c123456789",
            names=[
                GoogleName(
                    metadata=GoogleFieldMetadata(primary=True),
                    givenName="John",
                    familyName="Doe",
                )
            ],
            organizations=[
                GoogleOrganization(
                    metadata=GoogleFieldMetadata(primary=True),
                    name="Tech Corp",
                    title=None,
                    current=True,
                )
            ],
        )

        contact = transformer.transform_person(person)

        assert contact.company == "Tech Corp"
        assert contact.job_title is None

    def test_transform_person_with_organization_title_only(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Test transformation when organization has only title (no company name)."""
        person = GooglePerson(
            resourceName="people/c123456789",
            names=[
                GoogleName(
                    metadata=GoogleFieldMetadata(primary=True),
                    givenName="John",
                    familyName="Doe",
                )
            ],
            organizations=[
                GoogleOrganization(
                    metadata=GoogleFieldMetadata(primary=True),
                    name=None,
                    title="Freelance Developer",
                    current=True,
                )
            ],
        )

        contact = transformer.transform_person(person)

        assert contact.company is None
        assert contact.job_title == "Freelance Developer"

    def test_transform_person_with_no_organizations(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Test transformation when person has no organizations."""
        person = GooglePerson(
            resourceName="people/c123456789",
            names=[
                GoogleName(
                    metadata=GoogleFieldMetadata(primary=True),
                    givenName="John",
                    familyName="Doe",
                )
            ],
            organizations=[],
        )

        contact = transformer.transform_person(person)

        assert contact.company is None
        assert contact.job_title is None

    def test_transform_person_with_empty_organization_fields(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Test transformation when organization has empty string fields."""
        person = GooglePerson(
            resourceName="people/c123456789",
            names=[
                GoogleName(
                    metadata=GoogleFieldMetadata(primary=True),
                    givenName="John",
                    familyName="Doe",
                )
            ],
            organizations=[
                GoogleOrganization(
                    metadata=GoogleFieldMetadata(primary=True),
                    name="",  # Empty string
                    title="",  # Empty string
                    current=True,
                )
            ],
        )

        contact = transformer.transform_person(person)

        # Empty strings should be treated as None
        assert contact.company is None
        assert contact.job_title is None


class TestInboundHierarchySplitting:
    """Test hierarchy-aware tag splitting in the transformer."""

    def test_flat_group_produces_single_tag(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Test that a flat group name produces a single tag without parent_name."""
        person = GooglePerson(
            resourceName="people/c123",
            names=[GoogleName(givenName="Test", familyName="Person")],
            memberships=[
                GoogleMembership(
                    contactGroupMembership=GoogleContactGroupMembership(
                        contactGroupId="work",
                        contactGroupResourceName="contactGroups/work",
                    )
                ),
            ],
        )

        contact = transformer.transform_person(person)

        assert len(contact.tags) == 1  # type: ignore[arg-type]
        assert contact.tags[0].name.value == "work"  # type: ignore[index]
        assert contact.tags[0].parent_id is None  # type: ignore[index]

    def test_hierarchical_group_produces_parent_and_child(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Test 'Family/Extended' produces two tags with parent→child relationship."""
        translator = GoogleGroupNameTranslator(
            reserved_group_ids=[],
            group_mapping={"contactGroups/abc123": "Family/Extended"},
        )
        transformer_with_groups = GoogleContactTransformer(
            user_id=TEST_USER_ID, translator=translator
        )

        person = GooglePerson(
            resourceName="people/c123",
            names=[GoogleName(givenName="Test", familyName="Person")],
            memberships=[
                GoogleMembership(
                    contactGroupMembership=GoogleContactGroupMembership(
                        contactGroupId="abc123",
                        contactGroupResourceName="contactGroups/abc123",
                    )
                ),
            ],
        )

        contact = transformer_with_groups.transform_person(person)

        # Should produce 2 tags: "Family" (root) and "Extended" (child)
        assert len(contact.tags) == 2  # type: ignore[arg-type]
        tag_names = [tag.name.value for tag in contact.tags]  # type: ignore[union-attr]
        assert "Family" in tag_names
        assert "Extended" in tag_names

    def test_three_level_hierarchy_produces_chain(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Test 'A/B/C' produces three tags in parent chain."""
        translator = GoogleGroupNameTranslator(
            reserved_group_ids=[],
            group_mapping={"contactGroups/deep": "A/B/C"},
        )
        transformer_with_groups = GoogleContactTransformer(
            user_id=TEST_USER_ID, translator=translator
        )

        person = GooglePerson(
            resourceName="people/c123",
            names=[GoogleName(givenName="Test", familyName="Person")],
            memberships=[
                GoogleMembership(
                    contactGroupMembership=GoogleContactGroupMembership(
                        contactGroupId="deep",
                        contactGroupResourceName="contactGroups/deep",
                    )
                ),
            ],
        )

        contact = transformer_with_groups.transform_person(person)

        tag_names = [tag.name.value for tag in contact.tags]  # type: ignore[union-attr]
        assert "A" in tag_names
        assert "B" in tag_names
        assert "C" in tag_names
        assert len(contact.tags) == 3  # type: ignore[arg-type]

    def test_sanitize_tag_name_replaces_slash(
        self, transformer: GoogleContactTransformer
    ) -> None:
        """Test that _sanitize_tag_name replaces / with -."""
        result = transformer._sanitize_tag_name("Family/Extended")
        assert result == "Family-Extended"

    def test_reserved_group_with_slash_still_filtered(
        self,
    ) -> None:
        """Test that reserved groups containing / are still filtered out."""
        translator = GoogleGroupNameTranslator(
            reserved_group_ids=["myContacts/special"],
            group_mapping={},
        )
        transformer_with_reserved = GoogleContactTransformer(
            user_id=TEST_USER_ID, translator=translator
        )

        person = GooglePerson(
            resourceName="people/c123",
            names=[GoogleName(givenName="Test", familyName="Person")],
            memberships=[
                GoogleMembership(
                    contactGroupMembership=GoogleContactGroupMembership(
                        contactGroupId="myContacts/special",
                        contactGroupResourceName="contactGroups/myContacts-special",
                    )
                ),
            ],
        )

        contact = transformer_with_reserved.transform_person(person)

        assert len(contact.tags) == 0  # type: ignore[arg-type]

    def test_case_variant_group_names_dedupe_to_single_tag(self) -> None:
        """Groups whose names differ only in case produce one tag.

        Tag identity is case-insensitive in the backend, so case-variant
        Google groups (e.g. "Scouts" and "scouts") must collapse to a single
        tag instead of resolving to the same DB tag twice downstream.
        """
        translator = GoogleGroupNameTranslator(
            reserved_group_ids=[],
            group_mapping={
                "contactGroups/upper": "Scouts",
                "contactGroups/lower": "scouts",
            },
        )
        transformer_with_groups = GoogleContactTransformer(
            user_id=TEST_USER_ID, translator=translator
        )

        person = GooglePerson(
            resourceName="people/c123",
            names=[GoogleName(givenName="Test", familyName="Person")],
            memberships=[
                GoogleMembership(
                    contactGroupMembership=GoogleContactGroupMembership(
                        contactGroupId="upper",
                        contactGroupResourceName="contactGroups/upper",
                    )
                ),
                GoogleMembership(
                    contactGroupMembership=GoogleContactGroupMembership(
                        contactGroupId="lower",
                        contactGroupResourceName="contactGroups/lower",
                    )
                ),
            ],
        )

        contact = transformer_with_groups.transform_person(person)

        assert len(contact.tags) == 1  # type: ignore[arg-type]
        assert contact.tags[0].name.value == "Scouts"  # type: ignore[index]


class TestNicknameTransformation:
    """Google nicknames are imported: the app pushes them, so Google holds them."""

    def test_primary_nickname_is_imported(
        self, transformer: GoogleContactTransformer
    ) -> None:
        person = GooglePerson(
            resourceName="people/n1",
            names=[GoogleName(givenName="Robert")],
            nicknames=[
                GoogleNickname(value="Robbie"),
                GoogleNickname(metadata=GoogleFieldMetadata(primary=True), value="Bob"),
            ],
        )

        contact = transformer.transform_person(person)

        assert contact.nick_name == "Bob"

    def test_first_nickname_is_imported_without_a_primary(
        self, transformer: GoogleContactTransformer
    ) -> None:
        person = GooglePerson(
            resourceName="people/n2",
            names=[GoogleName(givenName="Robert")],
            nicknames=[GoogleNickname(value="  "), GoogleNickname(value="Bob")],
        )

        contact = transformer.transform_person(person)

        assert contact.nick_name == "Bob"

    def test_no_nickname_in_google_imports_none(
        self, transformer: GoogleContactTransformer
    ) -> None:
        person = GooglePerson(
            resourceName="people/n3", names=[GoogleName(givenName="Robert")]
        )

        contact = transformer.transform_person(person)

        assert contact.nick_name is None

    def test_google_sync_owns_the_nickname(self) -> None:
        """Owned, so a nickname removed in Google is cleared locally too."""
        assert ContactSyncField.NICK_NAME in GOOGLE_CONTACT_SYNC_SCOPE.fields


class TestAddressRegions:
    """Regions follow the backend's rules; an unplaceable one is skipped (#1820)."""

    @staticmethod
    def _person(*addresses: GoogleAddress) -> GooglePerson:
        return GooglePerson(resourceName="people/c1", addresses=list(addresses))

    def test_a_typed_region_is_imported_as_its_code(
        self, transformer: GoogleContactTransformer
    ) -> None:
        person = self._person(
            GoogleAddress(
                streetAddress="1 George St", region="new south wales", countryCode="AU"
            )
        )

        contact = transformer.transform_person(person)

        assert [a.region for a in contact.addresses or []] == ["NSW"]

    def test_an_address_whose_region_is_unrecognised_is_skipped_and_reported(
        self, transformer: GoogleContactTransformer
    ) -> None:
        london = GoogleAddress(
            streetAddress="10 Downing St",
            city="London",
            region="London",
            postalCode="SW1A 2AA",
            countryCode="AU",
        )
        person = self._person(
            london, GoogleAddress(streetAddress="1 George St", countryCode="AU")
        )

        contact = transformer.transform_person(person)

        assert [a.street_line_1 for a in contact.addresses or []] == ["1 George St"]
        assert transformer.skipped_addresses(person) == [
            SkippedAddress(
                street_line_1="10 Downing St",
                locality="London",
                region="London",
                postal_code="SW1A 2AA",
                country_code="AU",
                reason="unrecognised_region",
            )
        ]

    def test_nothing_is_reported_when_every_region_is_placed(
        self, transformer: GoogleContactTransformer
    ) -> None:
        person = self._person(
            GoogleAddress(streetAddress="1 George St", region="NSW", countryCode="AU"),
            GoogleAddress(streetAddress="1 High St", region="Kent", countryCode="GB"),
        )

        assert transformer.skipped_addresses(person) == []

    def test_a_region_is_judged_in_the_inferred_country(self) -> None:
        """A countryless "London" given AU is reported for review, not imported."""
        person = GooglePerson(
            resourceName="people/c1",
            addresses=[GoogleAddress(streetAddress="10 Downing St", region="London")],
        )
        transformer = GoogleContactTransformer(
            user_id=TEST_USER_ID, default_country="AU"
        )

        contact = transformer.transform_person(person)

        assert contact.addresses is None
        assert transformer.skipped_addresses(person) == [
            SkippedAddress(
                street_line_1="10 Downing St",
                region="London",
                country_code="AU",
                reason="unrecognised_region",
            )
        ]


class TestAddressCountryFallback:
    """An address with no country takes one from the phones, then the default.

    See ``address_country.resolve_address_country`` for the order (#1820).
    """

    @staticmethod
    def _person(
        *addresses: GoogleAddress, phones: tuple[str, ...] = ()
    ) -> GooglePerson:
        return GooglePerson(
            resourceName="people/c1",
            addresses=list(addresses),
            phoneNumbers=[GooglePhoneNumber(value=phone) for phone in phones],
        )

    def test_takes_the_country_of_the_contacts_phone(self) -> None:
        person = self._person(
            GoogleAddress(streetAddress="1 Queen St", city="Auckland"),
            phones=("+6421234567",),
        )

        contact = GoogleContactTransformer(
            user_id=TEST_USER_ID, default_country="AU"
        ).transform_person(person)

        assert [a.country_code for a in contact.addresses or []] == ["NZ"]

    def test_takes_the_users_default_country_without_a_phone(self) -> None:
        person = self._person(GoogleAddress(streetAddress="1 Queen St"))

        contact = GoogleContactTransformer(
            user_id=TEST_USER_ID, default_country="AU"
        ).transform_person(person)

        assert [a.country_code for a in contact.addresses or []] == ["AU"]

    def test_skips_the_address_with_neither(
        self, transformer: GoogleContactTransformer
    ) -> None:
        person = self._person(GoogleAddress(streetAddress="1 Queen St"))

        contact = transformer.transform_person(person)

        assert contact.addresses is None

    def test_an_explicit_country_code_wins(self) -> None:
        person = self._person(
            GoogleAddress(streetAddress="1 Queen St", countryCode="GB"),
            phones=("+6421234567",),
        )

        contact = GoogleContactTransformer(
            user_id=TEST_USER_ID, default_country="AU"
        ).transform_person(person)

        assert [a.country_code for a in contact.addresses or []] == ["GB"]

    def test_drops_an_inferred_twin_of_an_address_with_a_country(self) -> None:
        """A push before #1820 left the local copy beside Google's countryless one."""
        person = self._person(
            GoogleAddress(streetAddress="1 Queen St", city="Auckland"),
            GoogleAddress(
                streetAddress="1 Queen St", city="Auckland", countryCode="NZ"
            ),
            GoogleAddress(streetAddress="9 Other Rd"),
            phones=("+6421234567",),
        )

        contact = GoogleContactTransformer(user_id=TEST_USER_ID).transform_person(
            person
        )

        assert [(a.street_line_1, a.country_code) for a in contact.addresses or []] == [
            ("1 Queen St", "NZ"),
            ("9 Other Rd", "NZ"),
        ]

    @pytest.mark.parametrize(
        "explicit",
        [
            GoogleAddress(
                streetAddress="1 Queen St",
                extendedAddress="Flat 2",
                city="Auckland",
                countryCode="NZ",
            ),
            GoogleAddress(
                streetAddress="1 Queen St",
                city="Auckland",
                region="X",
                countryCode="NZ",
            ),
            GoogleAddress(
                streetAddress="1 Queen St", city="Auckland", countryCode="GB"
            ),
        ],
        ids=["other-flat", "other-region", "other-country"],
    )
    def test_keeps_an_inferred_address_that_differs_from_one_with_a_country(
        self, explicit: GoogleAddress
    ) -> None:
        person = self._person(
            GoogleAddress(streetAddress="1 Queen St", city="Auckland"),
            explicit,
            phones=("+6421234567",),
        )

        contact = GoogleContactTransformer(user_id=TEST_USER_ID).transform_person(
            person
        )

        assert len(contact.addresses or []) == 2

    def test_the_surviving_twin_keeps_a_primary_choice(self) -> None:
        """The countryless copy was the primary one: its twin takes the flag."""
        person = self._person(
            GoogleAddress.model_validate(
                {"streetAddress": "1 Queen St", "metadata": {"primary": True}}
            ),
            GoogleAddress(streetAddress="1 Queen St", countryCode="NZ"),
            phones=("+6421234567",),
        )

        contact = GoogleContactTransformer(user_id=TEST_USER_ID).transform_person(
            person
        )

        assert [(a.country_code, a.is_primary) for a in contact.addresses or []] == [
            ("NZ", True)
        ]


class TestAddressFallbackCountry:
    """The fallback a pull records: only one it gave an address (#1820)."""

    def test_is_the_country_a_countryless_address_was_given(self) -> None:
        person = TestAddressCountryFallback._person(
            GoogleAddress(streetAddress="1 Queen St"), phones=("+6421234567",)
        )

        assert (
            GoogleContactTransformer(user_id=TEST_USER_ID).address_fallback_country(
                person
            )
            == "NZ"
        )

    @pytest.mark.parametrize(
        "addresses",
        [
            (),
            (GoogleAddress(streetAddress="1 Queen St", countryCode="NZ"),),
            (GoogleAddress(city="Auckland"),),
        ],
        ids=["no-addresses", "every-address-has-a-country", "no-street"],
    )
    def test_is_none_when_no_address_took_it(
        self, addresses: tuple[GoogleAddress, ...]
    ) -> None:
        """So an address added in Google later is not owned before it is pulled."""
        person = TestAddressCountryFallback._person(*addresses, phones=("+6421234567",))

        assert (
            GoogleContactTransformer(
                user_id=TEST_USER_ID, default_country="AU"
            ).address_fallback_country(person)
            is None
        )
