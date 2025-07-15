"""Repository interfaces for the contacts domain."""

from abc import ABC, abstractmethod
from typing import Any

from .entities import Contact, ContactAddress, ContactMethod, ContactNote, Tag
from .events import DomainEvent


class ContactRepository(ABC):
    """Repository interface for contact operations."""

    @abstractmethod
    async def find_by_id(self, contact_id: int) -> Contact | None:
        """Find a contact by ID with all related data."""
        pass

    @abstractmethod
    async def find_by_email(self, email: str) -> Contact | None:
        """Find a contact by email address."""
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
    async def delete(self, contact_id: int) -> None:
        """Delete a contact and all related data."""
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
    async def add_method(self, contact_id: int, method: ContactMethod) -> ContactMethod:
        """Add a contact method."""
        pass

    @abstractmethod
    async def update_method(self, method: ContactMethod) -> ContactMethod:
        """Update a contact method."""
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
    async def get_all(self) -> list[Tag]:
        """Get all tags."""
        pass

    @abstractmethod
    async def get_children(self, parent_id: int) -> list[Tag]:
        """Get child tags of a parent tag."""
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
        self, contact_id: int, limit: int = 50
    ) -> list[ContactFieldHistoryEntry]:
        """Get field history for a specific contact."""
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
    async def publish(self, event: DomainEvent) -> None:
        """Publish a domain event."""
        pass

    @abstractmethod
    async def publish_batch(self, events: list[DomainEvent]) -> None:
        """Publish multiple domain events."""
        pass
