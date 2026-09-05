"""Repository interfaces for the contacts domain."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol

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
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.importance import ContactImportance
from app.core.contacts.models.upcoming_dates import ContactImportantDate
from app.core.history.models import FieldHistoryEntry, FieldHistoryRepository


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
    async def contact_exists(self, contact_id: int) -> bool:
        """Return whether a contact with the given ID exists.

        A lightweight existence check that does not hydrate the aggregate.
        """
        pass

    @abstractmethod
    async def find_names_by_ids(
        self, contact_ids: list[int]
    ) -> dict[int, tuple[str | None, str | None, str | None]]:
        """Fetch (first_name, last_name, photo_url) for multiple contacts in a single query.

        Returns a dict mapping contact_id to (first_name, last_name, photo_url).
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
    async def get_external_references(self, contact_id: int) -> list[dict[str, str]]:
        """Get all external references for a contact.

        Returns a list of dicts containing 'external_system', 'external_entity_id', and 'external_entity_type'.
        """
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
    async def lock(self, contact_id: int) -> None:
        """Take a contact's row lock before writing any of its child rows.

        Every child-write path ends by touching the contact, and a conditional
        write takes the contact's lock *first* (see
        :meth:`lock_and_get_updated_at`). Without this the two orders invert —
        one holds the parent and wants the child, the other the reverse — and
        PostgreSQL breaks the cycle by aborting one with a deadlock, which
        nothing retries. Locking the parent up front makes every writer take
        the locks in the same order, so they queue instead.
        """
        pass

    @abstractmethod
    async def lock_and_get_updated_at(self, contact_id: int) -> datetime | None:
        """Lock a contact row for update and return its last-write timestamp.

        Backs the optimistic-concurrency check on updates. Comparing an
        entity-tag against an unlocked read leaves a lost-update window under
        READ COMMITTED: two callers can both see the version they expected
        before either of them writes. Taking the row lock here means the second
        caller waits for the first to commit and then sees the new timestamp.

        Returns:
            The contact's ``updated_at``, or None if no such contact exists.
        """
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

    @abstractmethod
    async def repoint_methods(
        self, source_id: int, survivor_id: int, transaction: AsyncConnection
    ) -> None:
        """Re-point the source contact's methods onto the survivor.

        Exact duplicates (same ``method_type`` + ``value``) collapse — this also
        resolves the global email-uniqueness collision, since the survivor is the
        only other contact that could hold the same email. Where the survivor
        already has a primary method of a given type, the source's competing
        primaries are demoted so the one-primary-per-type invariant holds.
        """
        pass

    @abstractmethod
    async def repoint_addresses(
        self, source_id: int, survivor_id: int, transaction: AsyncConnection
    ) -> None:
        """Re-point the source contact's addresses onto the survivor.

        Exact-duplicate addresses collapse. Where the survivor already has a
        primary address, the source's competing primaries are demoted so the
        one-primary-address-per-contact invariant holds.
        """
        pass

    @abstractmethod
    async def repoint_notes(
        self, source_id: int, survivor_id: int, transaction: AsyncConnection
    ) -> None:
        """Re-point the source contact's notes onto the survivor, collapsing
        notes whose content already exists on the survivor."""
        pass

    @abstractmethod
    async def repoint_important_dates(
        self, source_id: int, survivor_id: int, transaction: AsyncConnection
    ) -> None:
        """Re-point the source contact's important dates onto the survivor.

        Exact-duplicate dates collapse. If the survivor already has a birthday,
        the source's birthday is dropped (survivor wins) so the re-point cannot
        violate ``uq_contact_birthday``.
        """
        pass

    @abstractmethod
    async def repoint_tags(
        self, source_id: int, survivor_id: int, transaction: AsyncConnection
    ) -> None:
        """Re-point the source contact's tags onto the survivor, deduping on the
        ``contact_tags`` composite primary key (union of both contacts' tags)."""
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


# Field history is now an entity-agnostic, shared concept. ``ContactFieldHistoryEntry``
# is kept as a compatibility alias over the shared ``FieldHistoryEntry`` so existing
# contact imports continue to work unchanged.
ContactFieldHistoryEntry = FieldHistoryEntry


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


class ContactFieldHistoryRepository(FieldHistoryRepository):
    """Repository interface for contact field-level change history.

    Extends the shared, entity-agnostic ``FieldHistoryRepository`` with the
    contact-rooted read helpers used by the contact history service and API.
    """

    @abstractmethod
    async def get_contact_history(
        self,
        contact_id: int,
        limit: int = 50,
        offset: int = 0,
        *,
        reader_user_id: str | None = None,
    ) -> list[FieldHistoryEntry]:
        """Get field history for a specific contact with pagination.

        ``reader_user_id`` scopes the one kind of row on this aggregate that has
        an owner: a linked task's. Contacts themselves have none, so without it
        a shared contact would hand one user another user's commitments. It
        defaults to ``None``, which matches no row — forgetting it costs those
        entries rather than exposing them.
        """

    @abstractmethod
    async def get_contact_history_count(
        self, contact_id: int, *, reader_user_id: str | None = None
    ) -> int:
        """Get total count of history entries for a specific contact.

        Must be passed the same ``reader_user_id`` as the listing, or the count
        would advertise a page the list will not return.
        """


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
    async def create(self, relationship: ContactRelationship) -> ContactRelationship:
        """Create a new contact relationship."""
        pass

    @abstractmethod
    async def get_by_id(self, relationship_id: int) -> ContactRelationship | None:
        """Get a relationship by ID."""
        pass

    @abstractmethod
    async def get_relationships_for_contact(
        self, contact_id: int
    ) -> list[ContactRelationship]:
        """Get all relationships for a specific contact (both from and to)."""
        pass

    @abstractmethod
    async def get_relationships_from_contact(
        self, contact_id: int
    ) -> list[ContactRelationship]:
        """Get relationships where the contact is the 'from' contact."""
        pass

    @abstractmethod
    async def get_relationships_to_contact(
        self, contact_id: int
    ) -> list[ContactRelationship]:
        """Get relationships where the contact is the 'to' contact."""
        pass

    @abstractmethod
    async def update(self, relationship: ContactRelationship) -> ContactRelationship:
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

    @abstractmethod
    async def repoint_contact(
        self, source_id: int, survivor_id: int, transaction: AsyncConnection
    ) -> None:
        """Re-point the source contact's relationships onto the survivor.

        Moves both directions, drops self-loops between the merged pair, and
        dedupes against the relationship unique indexes.
        """
        pass


class ContactSummaryRepository(ABC):
    """Repository interface for contact summary operations."""

    @abstractmethod
    async def find_by_contact_id(self, contact_id: int) -> ContactSummary | None:
        """Find a summary by contact ID."""
        pass

    @abstractmethod
    async def upsert(self, summary: ContactSummary) -> ContactSummary:
        """Create or update a contact summary."""
        pass

    @abstractmethod
    async def update_status(
        self, contact_id: int, status: str
    ) -> ContactSummary | None:
        """Update the status of a contact summary."""
        pass

    @abstractmethod
    async def mark_refresh_requested(self, contact_id: int) -> None:
        """Record a buffered refresh request for a contact (rolling debounce).

        Sets ``refresh_requested_at`` to now, resetting the debounce timer on
        every call. Creates the summary row if none exists; no-op when the
        summary is disabled.
        """
        pass

    @abstractmethod
    async def clear_refresh_request(self, contact_id: int) -> None:
        """Clear any pending buffered refresh marker for a contact."""
        pass

    @abstractmethod
    async def claim_due_refreshes(
        self, buffer_seconds: int, limit: int
    ) -> list[tuple[int, bool]]:
        """Atomically claim contacts whose buffered refresh is due.

        Clears the marker on rows whose ``refresh_requested_at`` is at least
        ``buffer_seconds`` old — measured on the database clock, the same
        source that stamps the marker — and returns ``(contact_id,
        is_disabled)`` tuples, oldest marker first. Disabled rows are claimed
        too (so stale markers don't accumulate) but callers must not dispatch
        generation for them.
        """
        pass


class ContactImportanceRepository(ABC):
    """Reads how much each of a set of contacts matters to the user.

    Shared deliberately. The signals were computed inside the search indexer
    until ITER18-004 Phase 10, which needed them on the home dashboard as well
    — to order upcoming important dates — and could not depend on MeiliSearch
    being up to get them. One read, two callers, one definition of the window.

    Unlike the dashboard's own ports, the methods here take no ``user_id``:
    ``contacts`` carries no owner column in this schema and every other contacts
    repository is likewise unscoped. See the iteration document for why that was
    not changed here.
    """

    @abstractmethod
    async def for_contacts(
        self, contact_ids: Sequence[int], *, now: datetime | None = None
    ) -> dict[int, ContactImportance]:
        """The importance signals for each of ``contact_ids`` that exists.

        Args:
            contact_ids: The contacts to report on. An empty sequence is
                answered with an empty mapping and no query — the dashboard asks
                this whenever its window holds no dates.
            now: The instant the recency window is measured back from. Defaults
                to the current time; passed explicitly by tests that need the
                window's edge to sit somewhere known.

        Returns:
            A mapping from contact id to its signals. Ids with no ``contacts``
            row are **absent** rather than present with zeros: a contact that
            does not exist has no signals, which is not the same claim as a
            contact nobody has touched.
        """
        pass


class UpcomingImportantDateRepository(ABC):
    """Fetches the important dates that could fall in a window of days.

    The **candidates**, not the answer. A stored row carries loose components —
    a month and a day, sometimes a year — so whether it falls in the next seven
    days is a question about the recurrence rule rather than about a column, and
    that rule lives in ``resolve_occurrence``. What this port asks the database
    is the narrow question it can answer cheaply: which rows carry one of a
    given set of ``(month, day)`` pairs.

    Keeping the split there is what stops a second copy of the recurrence
    appearing in SQL, where no unit test could reach it.

    Like ``ContactImportanceRepository``, this takes no ``user_id``: ``contacts``
    carries no owner column in this schema and every other contacts repository is
    likewise unscoped. When contacts gain an owner, this port and its callers are
    part of the same change.
    """

    @abstractmethod
    async def candidates_for(
        self, month_days: Sequence[tuple[int, int]]
    ) -> list[ContactImportantDate]:
        """Every stored important date carrying one of ``month_days``.

        Args:
            month_days: The ``(month, day)`` pairs to match, as
                ``window_month_days`` builds them. An empty sequence is answered
                with an empty list and no query.

        Returns:
            The rows, each with the contact it belongs to already attached so a
            caller need make no per-row follow-up. Nothing is resolved, ranked
            or filtered beyond the pair match.
        """
        pass
