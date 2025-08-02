"""
Unit tests for Google Contacts transformer.

Tests the GoogleContactTransformer for converting Google People API
responses to internal Contact entities.
"""

import pytest

from app.core.contacts.models.entities import Contact, MethodType
from app.core.integrations.google_contacts.api_models import (
    GoogleAddress,
    GoogleBiography,
    GoogleEmailAddress,
    GoogleFieldMetadata,
    GoogleMembership,
    GoogleName,
    GoogleOrganization,
    GooglePerson,
    GooglePhoneNumber,
)
from app.core.integrations.google_contacts.transformer import GoogleContactTransformer


@pytest.fixture
def transformer():
    """Create GoogleContactTransformer instance."""
    return GoogleContactTransformer()


@pytest.fixture
def sample_google_person():
    """Create a sample GooglePerson for testing."""
    return GooglePerson(
        resourceName="people/c123456789",
        etag="test_etag_123",
        names=[
            GoogleName(
                metadata=GoogleFieldMetadata(primary=True, source_primary=True),
                displayName="John Doe",
                familyName="Doe",
                givenName="John",
                middleName="Michael",
            )
        ],
        emailAddresses=[
            GoogleEmailAddress(
                metadata=GoogleFieldMetadata(primary=True, source_primary=True),
                value="john.doe@example.com",
                type="work",
                formattedType="Work",
            ),
            GoogleEmailAddress(
                metadata=GoogleFieldMetadata(primary=False, source_primary=False),
                value="john.personal@example.com",
                type="home",
                formattedType="Home",
            ),
        ],
        phoneNumbers=[
            GooglePhoneNumber(
                metadata=GoogleFieldMetadata(primary=True, source_primary=True),
                value="+1-555-123-4567",
                canonicalForm="+15551234567",
                type="work",
                formattedType="Work",
            )
        ],
        addresses=[
            GoogleAddress(
                metadata=GoogleFieldMetadata(primary=True, source_primary=True),
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
                metadata=GoogleFieldMetadata(primary=True, source_primary=True),
                value="Software engineer with 10 years of experience.",
                contentType="TEXT_PLAIN",
            )
        ],
        organizations=[
            GoogleOrganization(
                metadata=GoogleFieldMetadata(primary=True, source_primary=True),
                name="Tech Corp",
                title="Senior Developer",
                type="work",
            )
        ],
        memberships=[
            GoogleMembership(
                metadata=GoogleFieldMetadata(primary=True, source_primary=True),
                contactGroupMembership={
                    "contactGroupId": "family",
                    "contactGroupResourceName": "contactGroups/family",
                },
            ),
            GoogleMembership(
                metadata=GoogleFieldMetadata(primary=False, source_primary=False),
                contactGroupMembership={
                    "contactGroupId": "work-colleagues",
                    "contactGroupResourceName": "contactGroups/work-colleagues",
                },
            ),
        ],
    )


class TestGoogleContactTransformer:
    """Test cases for GoogleContactTransformer."""

    def test_transform_person_basic_info(self, transformer, sample_google_person):
        """Test transformation of basic person information."""
        contact = transformer.transform_person(sample_google_person)

        assert isinstance(contact, Contact)
        assert contact.first_name == "John"
        assert contact.last_name == "Doe"
        assert contact.middle_name == "Michael"
        assert contact.nick_name is None
        assert contact.is_favourite is False

    def test_transform_person_basic_structure(self, transformer, sample_google_person):
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

    def test_transform_person_email_addresses(self, transformer, sample_google_person):
        """Test transformation of email addresses."""
        contact = transformer.transform_person(sample_google_person)

        email_methods = [
            cm for cm in contact.methods if cm.method_type == MethodType.EMAIL
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

    def test_transform_person_phone_numbers(self, transformer, sample_google_person):
        """Test transformation of phone numbers."""
        contact = transformer.transform_person(sample_google_person)

        phone_methods = [
            cm for cm in contact.methods if cm.method_type == MethodType.PHONE
        ]
        assert len(phone_methods) == 1

        phone = phone_methods[0]
        assert phone.value == "+15551234567"  # Should use canonical form
        assert phone.label == "Work"  # Should use formatted_type
        assert phone.is_primary is True

    def test_transform_person_addresses(self, transformer, sample_google_person):
        """Test transformation of addresses."""
        contact = transformer.transform_person(sample_google_person)

        assert len(contact.addresses) == 1
        address = contact.addresses[0]
        assert address.street_line_1 == "123 Main St"
        assert address.locality == "Anytown"
        assert address.region == "CA"
        assert address.postal_code == "12345"
        assert address.country_code == "US"
        assert address.is_primary is True

    def test_transform_person_notes(self, transformer, sample_google_person):
        """Test transformation of biographies to notes."""
        contact = transformer.transform_person(sample_google_person)

        assert len(contact.notes) == 1
        note = contact.notes[0]
        assert note.content == "Software engineer with 10 years of experience."

    def test_transform_person_membership_tags(self, transformer, sample_google_person):
        """Test transformation of contact group memberships to tags."""
        contact = transformer.transform_person(sample_google_person)

        assert len(contact.tags) == 2
        tag_names = [tag.name.value for tag in contact.tags]
        assert "family" in tag_names  # Contact group ID becomes tag
        assert "work-colleagues" in tag_names  # Contact group ID becomes tag

    def test_transform_person_empty_names(self, transformer):
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

    def test_transform_person_no_primary_name(self, transformer):
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

    def test_transform_person_empty_email_values(self, transformer):
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
            cm for cm in contact.methods if cm.method_type == MethodType.EMAIL
        ]
        assert len(email_methods) == 1
        assert email_methods[0].value == "valid@example.com"

    def test_transform_person_address_fallback_to_formatted(self, transformer):
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

        assert len(contact.addresses) == 1
        address = contact.addresses[0]
        assert address.street_line_1 == "123 Main St, Anytown, CA 12345"
        assert address.locality == "Anytown"
        assert address.region == "CA"

    def test_transform_person_invalid_membership_names_skipped(self, transformer):
        """Test that invalid membership names are skipped when creating tags."""
        person = GooglePerson(
            resourceName="people/c123456789",
            memberships=[
                GoogleMembership(
                    contactGroupMembership={}  # Empty membership info
                ),
                GoogleMembership(
                    contactGroupMembership={"contactGroupId": "valid-group"}
                ),
                GoogleMembership(
                    contactGroupMembership={
                        "contactGroupId": ""  # Empty group ID
                    }
                ),
            ],
        )

        contact = transformer.transform_person(person)

        # Should only create tags for valid group memberships
        tag_names = [tag.name.value for tag in contact.tags]
        assert "valid-group" in tag_names
        assert len(contact.tags) == 1

    def test_extract_names_with_primary(self, transformer):
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

        first, last, middle, nick = transformer._extract_names(names)

        assert first == "Primary"
        assert last == "Name"
        assert middle == "Middle"
        assert nick is None

    def test_extract_names_no_primary(self, transformer):
        """Test name extraction when no primary name is available."""
        names = [
            GoogleName(
                metadata=GoogleFieldMetadata(primary=False),
                givenName="First",
                familyName="Available",
            ),
        ]

        first, last, middle, nick = transformer._extract_names(names)

        assert first == "First"
        assert last == "Available"
        assert middle is None
        assert nick is None

    def test_extract_names_empty_list(self, transformer):
        """Test name extraction with empty names list."""
        first, last, middle, nick = transformer._extract_names([])

        assert first is None
        assert last is None
        assert middle is None
        assert nick is None
