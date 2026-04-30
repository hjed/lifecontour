"""Repository interfaces for the contacts domain."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any, Protocol, Union

from core_shared.models.contacts.entities import (
    Contact,
    ContactAddress,
    ContactMethod,
    ContactNote,
    ContactRelationship,
    ContactSummary,
    ImportantDate,
    Tag,
)
from core_shared.models.contacts.important_date_types import CustomDateType
from core_shared.models.contacts.value_objects import Provenance
from sqlalchemy.ext.asyncio import AsyncConnection


class DomainEventProtocol(Protocol):
    """Protocol for domain events to support structural typing across domains."""

    @property
    def event_id(self) -> str: ...

    @property
    def occurred_at(self) -> Any: ...  # datetime

    @property
    def aggregate_id(self) -> int: ...

    @property
    def event_type(self) -> str: ...

    @property
    def event_data(self) -> dict[str, Any]: ...

    @property
    def transaction(self) -> AsyncConnection | None: ...


class ContactRepository(ABC):
    """Repository interface for contact operations."""

    @abstractmethod
    async def find_by_id(self, contact_id: int) -> Contact | None:
        """Find a contact by ID with all related data."""
        pass

    @abstractmethod
    async def find_names_by_ids(
        self, contact_ids: list[int]
    ) -> dict[int, tuple[str | None, str | None]]:
        """Fetch (first_name, last_name) for multiple contacts in a single query.

        Returns a dict mapping contact_id to (first_name, last_name).
        Only contacts that exist are included in the result.
        """
        pass

    @abstractmethod
    async def find_by_email(self, email: str) -> Contact | None:
        """Find a contact by email address."""
        pass

    @abstractmethod
    async def find_by_external_reference(
        self, external_system: str, external_entity_id: str
    ) -> Contact | None:
        """Find a contact by external reference."""
        pass

    @abstractmethod
    async def search(self, query: str, limit: int = 50) -> list[Contact]:
        """Search contacts by name, email, or notes."""
        pass

    @abstractmethod
    async def get_all(self, limit: int = 100, offset: int = 0) -> list[Contact]:
        """Get all contacts with pagination."""
        pass

    @abstractmethod
    async def get_count(self) -> int:
        """Get total count of contacts."""
        pass

    @abstractmethod
    async def save(self, contact: Contact) -> Contact:
        """Save a contact (insert or update)."""
        pass

    @abstractmethod
    async def touch(self, contact_id: int, transaction: Any = None) -> None:
        """Update the updated_at timestamp of a contact."""
        pass

    @abstractmethod
    async def delete(self, contact_id: int) -> None:
        """Delete a contact and all related data."""
        pass

    @abstractmethod
    async def bulk_delete_all(self, transaction: Any) -> None:
        """
        Bulk delete all contacts and related data for test cleanup.

        WARNING: This will delete ALL contacts. Only use in test environments.
        """
        pass

    @abstractmethod
    async def get_contacts_by_tag(self, tag_id: int) -> list[Contact]:
        """Get all contacts with a specific tag."""
        pass

    @abstractmethod
    async def get_favourite_contacts(
        self, limit: int = 100, offset: int = 0
    ) -> list[Contact]:
        """Get all favourite contacts with pagination."""
        pass

    @abstractmethod
    async def get_favourite_contacts_count(self) -> int:
        """Get total count of favourite contacts."""
        pass

    @abstractmethod
    async def get_contacts_by_filters(
        self,
        is_favourite: bool | None = None,
        tag_ids: list[int] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Contact]:
        """Get contacts filtered by favourite status and/or tags."""
        pass

    @abstractmethod
    async def get_contacts_count_by_filters(
        self,
        is_favourite: bool | None = None,
        tag_ids: list[int] | None = None,
    ) -> int:
        """Get the distinct count of contacts filtered by favourite status and/or tags."""
        pass

    @abstractmethod
    async def add_method(self, contact_id: int, method: ContactMethod) -> ContactMethod:
        """Add a contact method."""
        pass

    @abstractmethod
    async def update_method(self, method: ContactMethod) -> ContactMethod:
        """Update a contact method."""
        pass

    @abstractmethod
    async def find_method_by_id(self, method_id: int) -> ContactMethod | None:
        """Find a contact method by ID."""
        pass

    @abstractmethod
    async def delete_method(self, method_id: int) -> None:
        """Delete a contact method."""
        pass

    @abstractmethod
    async def delete_all_methods(self, contact_id: int) -> None:
        """Delete all contact methods for a contact."""
        pass

    @abstractmethod
    async def add_address(
        self, contact_id: int, address: ContactAddress
    ) -> ContactAddress:
        """Add a contact address."""
        pass

    @abstractmethod
    async def update_address(self, address: ContactAddress) -> ContactAddress:
        """Update a contact address."""
        pass

    @abstractmethod
    async def find_address_by_id(self, address_id: int) -> ContactAddress | None:
        """Find a contact address by ID."""
        pass

    @abstractmethod
    async def delete_address(self, address_id: int) -> None:
        """Delete a contact address."""
        pass

    @abstractmethod
    async def delete_all_addresses(self, contact_id: int) -> None:
        """Delete all contact addresses for a contact."""
        pass

    @abstractmethod
    async def add_note(self, contact_id: int, note: ContactNote) -> ContactNote:
        """Add a contact note."""
        pass

    @abstractmethod
    async def update_note(self, note: ContactNote) -> ContactNote:
        """Update a contact note."""
        pass

    @abstractmethod
    async def delete_note(self, note_id: int) -> None:
        """Delete a contact note."""
        pass

    @abstractmethod
    async def delete_all_notes(self, contact_id: int) -> None:
        """Delete all contact notes for a contact."""
        pass

    @abstractmethod
    async def assign_tag(self, contact_id: int, tag_id: int) -> None:
        """Assign a tag to a contact."""
        pass

    @abstractmethod
    async def remove_tag(self, contact_id: int, tag_id: int) -> None:
        """Remove a tag from a contact."""
        pass

    @abstractmethod
    async def add_important_date(
        self, contact_id: int, date: ImportantDate
    ) -> ImportantDate:
        """Add an important date to a contact."""
        pass

    @abstractmethod
    async def get_important_dates(self, contact_id: int) -> list[ImportantDate]:
        """Get all important dates for a contact."""
        pass

    @abstractmethod
    async def delete_important_date(self, date_id: int) -> None:
        """Delete an important date."""
        pass

    @abstractmethod
    async def delete_all_important_dates(self, contact_id: int) -> None:
        """Delete all important dates for a contact."""
        pass


class TagRepository(ABC):
    """Repository interface for tag operations."""

    @abstractmethod
    async def find_by_id(self, tag_id: int) -> Tag | None:
        """Find a tag by ID."""
        pass

    @abstractmethod
    async def find_by_name(self, name: str) -> Tag | None:
        """Find a tag by name."""
        pass

    @abstractmethod
    async def find_by_names(self, names: list[str]) -> dict[str, Tag]:
        """Find multiple tags by their names, returned as a dict keyed by tag name."""
        pass

    @abstractmethod
    async def get_all(self) -> list[Tag]:
        """Get all tags."""
        pass

    @abstractmethod
    async def get_children(self, parent_id: int) -> list[Tag]:
        """Get child tags of a parent tag."""
        pass

    @abstractmethod
    async def get_descendants_for_tags(self, tag_ids: list[int]) -> list[Tag]:
        """Get all descendant tags (recursive) for a list of tag IDs."""
        pass

    @abstractmethod
    async def get_root_tags(self) -> list[Tag]:
        """Get all root tags (no parent)."""
        pass

    @abstractmethod
    async def save(self, tag: Tag) -> Tag:
        """Save a tag (insert or update)."""
        pass

    @abstractmethod
    async def delete(self, tag_id: int) -> None:
        """Delete a tag."""
        pass


class CustomDateTypeRepository(ABC):
    """Repository interface for custom date type operations."""

    @abstractmethod
    async def create(self, name: str) -> CustomDateType:
        """Create a new custom date type."""
        pass

    @abstractmethod
    async def get_by_id(self, type_id: int) -> CustomDateType | None:
        """Find a custom date type by ID."""
        pass

    @abstractmethod
    async def get_by_name(self, name: str) -> CustomDateType | None:
        """Find a custom date type by name."""
        pass

    @abstractmethod
    async def list_all(self) -> list[CustomDateType]:
        """Get all custom date types."""
        pass

    @abstractmethod
    async def delete(self, type_id: int) -> None:
        """Delete a custom date type."""
        pass


class ContactFieldHistoryEntry:
    """Field-level change history entry model."""

    def __init__(
        self,
        entity_type: str,
        entity_id: int,
        field_name: str,
        old_value: str | None = None,
        new_value: str | None = None,
        changed_by: str | None = None,
        source: Provenance = Provenance.SYSTEM,
        id: int | None = None,
        created_at: str | None = None,
    ):
        self.id = id
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.field_name = field_name
        self.old_value = old_value
        self.new_value = new_value
        self.changed_by = changed_by
        self.source = source
        self.created_at = created_at


class ContactEditEvent:
    """Domain event for contact editing operations."""

    def __init__(
        self,
        event_id: str,
        event_type: str,
        aggregate_id: int,
        event_data: dict[str, Any],
        occurred_at: str | None = None,
        correlation_id: str | None = None,
        id: int | None = None,
    ):
        self.id = id
        self.event_id = event_id
        self.event_type = event_type
        self.aggregate_id = aggregate_id
        self.event_data = event_data
        self.occurred_at = occurred_at
        self.correlation_id = correlation_id


class ContactFieldHistoryRepository(ABC):
    """Repository interface for field-level change history operations."""

    @abstractmethod
    async def get_contact_history(
        self, contact_id: int, limit: int = 50, offset: int = 0
    ) -> list[ContactFieldHistoryEntry]:
        """Get field history for a specific contact with pagination."""
        pass

    @abstractmethod
    async def get_contact_history_count(self, contact_id: int) -> int:
        """Get total count of history entries for a specific contact."""
        pass

    @abstractmethod
    async def get_entity_history(
        self, entity_type: str, entity_id: int
    ) -> list[ContactFieldHistoryEntry]:
        """Get field history for a specific entity."""
        pass

    @abstractmethod
    async def record_change(
        self, entry: ContactFieldHistoryEntry
    ) -> ContactFieldHistoryEntry:
        """Record a field change in history."""
        pass


class ContactEditEventRepository(ABC):
    """Repository interface for contact edit event operations."""

    @abstractmethod
    async def store_event(self, event: ContactEditEvent) -> ContactEditEvent:
        """Store a contact edit event."""
        pass

    @abstractmethod
    async def get_events_for_contact(
        self, contact_id: int, limit: int = 50
    ) -> list[ContactEditEvent]:
        """Get edit events for a specific contact."""
        pass

    @abstractmethod
    async def get_events_by_type(
        self, event_type: str, limit: int = 50
    ) -> list[ContactEditEvent]:
        """Get events by type."""
        pass


class ContactEventPublisher(ABC):
    """Interface for publishing contact domain events."""

    @abstractmethod
    async def publish(self, event: DomainEventProtocol) -> None:
        """Publish a domain event."""
        pass

    @abstractmethod
    async def publish_batch(self, events: Sequence[DomainEventProtocol]) -> None:
        """Publish multiple domain events."""
        pass


class ContactRelationshipRepository(ABC):
    """Repository interface for contact relationship operations."""

    @abstractmethod
    async def create(
        self, relationship: "ContactRelationship"
    ) -> "ContactRelationship":
        """Create a new contact relationship."""
        pass

    @abstractmethod
    async def get_by_id(
        self, relationship_id: int
    ) -> Union["ContactRelationship", None]:
        """Get a relationship by ID."""
        pass

    @abstractmethod
    async def get_relationships_for_contact(
        self, contact_id: int
    ) -> list["ContactRelationship"]:
        """Get all relationships for a specific contact (both from and to)."""
        pass

    @abstractmethod
    async def get_relationships_from_contact(
        self, contact_id: int
    ) -> list["ContactRelationship"]:
        """Get relationships where the contact is the 'from' contact."""
        pass

    @abstractmethod
    async def get_relationships_to_contact(
        self, contact_id: int
    ) -> list["ContactRelationship"]:
        """Get relationships where the contact is the 'to' contact."""
        pass

    @abstractmethod
    async def update(
        self, relationship: "ContactRelationship"
    ) -> "ContactRelationship":
        """Update an existing relationship."""
        pass

    @abstractmethod
    async def delete(self, relationship_id: int) -> None:
        """Delete a relationship by ID."""
        pass

    @abstractmethod
    async def relationship_exists(
        self,
        from_contact_id: int,
        to_contact_id: int | None,
        relationship_type: str,
        *,
        to_user: bool = False,
    ) -> bool:
        """Check if a specific relationship already exists."""
        pass


class ContactSummaryRepository(ABC):
    """Repository interface for contact summary operations."""

    @abstractmethod
    async def find_by_contact_id(self, contact_id: int) -> "ContactSummary | None":
        """Find a summary by contact ID."""
        pass

    @abstractmethod
    async def upsert(self, summary: "ContactSummary") -> "ContactSummary":
        """Create or update a contact summary."""
        pass

    @abstractmethod
    async def update_status(
        self, contact_id: int, status: str
    ) -> "ContactSummary | None":
        """Update the status of a contact summary."""
        pass
