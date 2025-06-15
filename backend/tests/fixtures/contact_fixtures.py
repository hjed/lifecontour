"""
Shared contact fixtures and factory functions for testing.

This module provides reusable contact setup patterns to reduce duplication
across test files. It includes both factory functions for customization
and pytest fixtures for common use cases.

Usage Examples:
    # Factory functions (customizable)
    contact = create_basic_contact(first_name="Jane", last_name="Smith")
    contact = create_contact_with_methods(email="jane@example.com")

    # Pytest fixtures (standard patterns)
    def test_something(basic_contact, contact_with_methods):
        # Use the pre-configured contacts
        pass
"""

from __future__ import annotations

import pytest

from app.core.contacts.models.entities import (
    Contact,
    ContactAddress,
    ContactMethod,
    ContactNote,
    MethodType,
    Tag,
)
from app.core.contacts.models.value_objects import TagName

# Factory Functions for Customizable Contact Creation


def create_basic_contact(
    first_name: str = "John",
    last_name: str | None = "Doe",
    middle_name: str | None = None,
    nick_name: str | None = None,
    contact_id: int | None = None,
) -> Contact:
    """Create a basic contact with minimal required fields.

    Args:
        first_name: Contact's first name (default: "John")
        last_name: Contact's last name (default: "Doe")
        middle_name: Contact's middle name (optional)
        nick_name: Contact's nickname (optional)
        contact_id: Contact's ID (optional, useful for tests that need specific IDs)

    Returns:
        Contact entity with basic information
    """
    return Contact(
        id=contact_id,
        first_name=first_name,
        last_name=last_name,
        middle_name=middle_name,
        nick_name=nick_name,
    )


def create_contact_with_email(
    first_name: str = "John",
    last_name: str | None = "Doe",
    email: str = "john.doe@example.com",
    contact_id: int | None = None,
    method_id: int | None = None,
) -> Contact:
    """Create a contact with an email method.

    Args:
        first_name: Contact's first name (default: "John")
        last_name: Contact's last name (default: "Doe")
        email: Email address (default: "john.doe@example.com")
        contact_id: Contact's ID (optional)
        method_id: Email method's ID (optional)

    Returns:
        Contact entity with email method attached
    """
    contact = create_basic_contact(first_name, last_name, contact_id=contact_id)

    email_method = ContactMethod(
        id=method_id,
        contact_id=contact_id or 0,
        method_type=MethodType.EMAIL,
        value=email,
        is_primary=True,
    )
    contact.methods = [email_method]

    return contact


def create_contact_with_phone(
    first_name: str = "John",
    last_name: str | None = "Doe",
    phone: str = "+1-555-0123",
    contact_id: int | None = None,
    method_id: int | None = None,
) -> Contact:
    """Create a contact with a phone method.

    Args:
        first_name: Contact's first name (default: "John")
        last_name: Contact's last name (default: "Doe")
        phone: Phone number (default: "+1-555-0123")
        contact_id: Contact's ID (optional)
        method_id: Phone method's ID (optional)

    Returns:
        Contact entity with phone method attached
    """
    contact = create_basic_contact(first_name, last_name, contact_id=contact_id)

    phone_method = ContactMethod(
        id=method_id,
        contact_id=contact_id or 0,
        method_type=MethodType.PHONE,
        value=phone,
        is_primary=True,
    )
    contact.methods = [phone_method]

    return contact


def create_contact_with_methods(
    first_name: str = "John",
    last_name: str | None = "Doe",
    email: str = "john.doe@example.com",
    phone: str = "+1-555-0123",
    contact_id: int | None = None,
    email_method_id: int | None = None,
    phone_method_id: int | None = None,
) -> Contact:
    """Create a contact with both email and phone methods.

    Args:
        first_name: Contact's first name (default: "John")
        last_name: Contact's last name (default: "Doe")
        email: Email address (default: "john.doe@example.com")
        phone: Phone number (default: "+1-555-0123")
        contact_id: Contact's ID (optional)
        email_method_id: Email method's ID (optional)
        phone_method_id: Phone method's ID (optional)

    Returns:
        Contact entity with email and phone methods attached
    """
    contact = create_basic_contact(first_name, last_name, contact_id=contact_id)

    email_method = ContactMethod(
        id=email_method_id,
        contact_id=contact_id or 0,
        method_type=MethodType.EMAIL,
        value=email,
        is_primary=True,
    )

    phone_method = ContactMethod(
        id=phone_method_id,
        contact_id=contact_id or 0,
        method_type=MethodType.PHONE,
        value=phone,
        is_primary=True,
    )

    contact.methods = [email_method, phone_method]
    return contact


def create_contact_with_tags(
    first_name: str = "John",
    last_name: str | None = "Doe",
    tags: list[str] | None = None,
    contact_id: int | None = None,
) -> Contact:
    """Create a contact with tags.

    Args:
        first_name: Contact's first name (default: "John")
        last_name: Contact's last name (default: "Doe")
        tags: List of tag names (default: ["friend", "work"])
        contact_id: Contact's ID (optional)

    Returns:
        Contact entity with tags attached
    """
    if tags is None:
        tags = ["friend", "work"]

    contact = create_basic_contact(first_name, last_name, contact_id=contact_id)

    contact.tags = [
        Tag(id=i + 1, name=TagName(tag_name)) for i, tag_name in enumerate(tags)
    ]

    return contact


def create_contact_with_notes(
    first_name: str = "John",
    last_name: str | None = "Doe",
    notes: list[str] | None = None,
    contact_id: int | None = None,
) -> Contact:
    """Create a contact with notes.

    Args:
        first_name: Contact's first name (default: "John")
        last_name: Contact's last name (default: "Doe")
        notes: List of note contents (default: ["Test contact note"])
        contact_id: Contact's ID (optional)

    Returns:
        Contact entity with notes attached
    """
    if notes is None:
        notes = ["Test contact note"]

    contact = create_basic_contact(first_name, last_name, contact_id=contact_id)

    contact.notes = [
        ContactNote(
            id=i + 1,
            contact_id=contact_id or 0,
            content=note_content,
        )
        for i, note_content in enumerate(notes)
    ]

    return contact


def create_contact_with_address(
    first_name: str = "John",
    last_name: str | None = "Doe",
    street: str = "123 Main St",
    locality: str = "Sydney",
    country_code: str = "AU",
    contact_id: int | None = None,
    address_id: int | None = None,
) -> Contact:
    """Create a contact with an address.

    Args:
        first_name: Contact's first name (default: "John")
        last_name: Contact's last name (default: "Doe")
        street: Street address (default: "123 Main St")
        locality: City/locality (default: "Sydney")
        country_code: Country code (default: "AU")
        contact_id: Contact's ID (optional)
        address_id: Address ID (optional)

    Returns:
        Contact entity with address attached
    """
    contact = create_basic_contact(first_name, last_name, contact_id=contact_id)

    address = ContactAddress(
        id=address_id,
        contact_id=contact_id or 0,
        street_line_1=street,
        locality=locality,
        country_code=country_code,
        is_primary=True,
    )
    contact.addresses = [address]

    return contact


def create_full_contact(
    first_name: str = "John",
    last_name: str | None = "Doe",
    middle_name: str | None = "William",
    nick_name: str | None = "Johnny",
    email: str = "john.doe@example.com",
    phone: str = "+1-555-0123",
    tags: list[str] | None = None,
    notes: list[str] | None = None,
    contact_id: int | None = None,
) -> Contact:
    """Create a contact with all related entities (methods, tags, notes, address).

    Args:
        first_name: Contact's first name (default: "John")
        last_name: Contact's last name (default: "Doe")
        middle_name: Contact's middle name (default: "William")
        nick_name: Contact's nickname (default: "Johnny")
        email: Email address (default: "john.doe@example.com")
        phone: Phone number (default: "+1-555-0123")
        tags: List of tag names (default: ["friend", "work"])
        notes: List of note contents (default: ["Great colleague and friend"])
        contact_id: Contact's ID (optional)

    Returns:
        Contact entity with all related entities attached
    """
    if tags is None:
        tags = ["friend", "work"]
    if notes is None:
        notes = ["Great colleague and friend"]

    contact = Contact(
        id=contact_id,
        first_name=first_name,
        last_name=last_name,
        middle_name=middle_name,
        nick_name=nick_name,
    )

    # Add methods
    email_method = ContactMethod(
        id=1,
        contact_id=contact_id or 0,
        method_type=MethodType.EMAIL,
        value=email,
        is_primary=True,
    )

    phone_method = ContactMethod(
        id=2,
        contact_id=contact_id or 0,
        method_type=MethodType.PHONE,
        value=phone,
        is_primary=True,
    )

    contact.methods = [email_method, phone_method]

    # Add tags
    contact.tags = [
        Tag(id=i + 1, name=TagName(tag_name)) for i, tag_name in enumerate(tags)
    ]

    # Add notes
    contact.notes = [
        ContactNote(
            id=i + 1,
            contact_id=contact_id or 0,
            content=note_content,
        )
        for i, note_content in enumerate(notes)
    ]

    # Add address
    address = ContactAddress(
        id=1,
        contact_id=contact_id or 0,
        street_line_1="123 Main St",
        locality="Sydney",
        country_code="AU",
        is_primary=True,
    )
    contact.addresses = [address]

    return contact


# Pytest Fixtures for Common Use Cases


@pytest.fixture
def basic_contact() -> Contact:
    """Fixture providing a basic contact (John Doe)."""
    return create_basic_contact()


@pytest.fixture
def contact_with_email() -> Contact:
    """Fixture providing a contact with email method."""
    return create_contact_with_email()


@pytest.fixture
def contact_with_phone() -> Contact:
    """Fixture providing a contact with phone method."""
    return create_contact_with_phone()


@pytest.fixture
def contact_with_methods() -> Contact:
    """Fixture providing a contact with email and phone methods."""
    return create_contact_with_methods()


@pytest.fixture
def contact_with_tags() -> Contact:
    """Fixture providing a contact with tags."""
    return create_contact_with_tags()


@pytest.fixture
def contact_with_notes() -> Contact:
    """Fixture providing a contact with notes."""
    return create_contact_with_notes()


@pytest.fixture
def full_contact() -> Contact:
    """Fixture providing a contact with all related entities."""
    return create_full_contact()


# Specialized fixtures for specific test scenarios


@pytest.fixture
def sample_contact() -> Contact:
    """Legacy fixture name for backward compatibility.

    This matches the existing sample_contact fixture pattern
    found in multiple test files.
    """
    return create_full_contact(contact_id=123)


@pytest.fixture
def sample_contact_entity() -> Contact:
    """Legacy fixture name for backward compatibility.

    This matches the existing sample_contact_entity fixture pattern
    found in integration test files.
    """
    return create_full_contact(contact_id=123)
