"""Repository interfaces for the journal domain."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import date, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from core_shared.models.history import Provenance
    from core_shared.models.journals import EventDateRange
    from core_shared.models.journals.attendee_status import AttendeeStatus
    from core_shared.models.journals.contact_event_role import ContactEventRole
    from core_shared.models.journals.review_item import ReviewItem
    from sqlalchemy.ext.asyncio import AsyncConnection

    from app.core.journal.models.activity_stats import (
        ActivityFilters,
        ActivityJournalRow,
        ActivityMetric,
        ActivityPersonalRecordRow,
        ActivityTotalsRow,
        ActivityTrendRow,
        ActivityTypeTotalsRow,
        RouteUsageRow,
        TrendInterval,
    )
    from app.core.journal.models.agenda import AgendaEntry

from core_shared.models.journals import (
    AbseilingData,
    AbseilPitch,
    ActivityTemplate,
    BushwalkingData,
    Calendar,
    CalendarInfo,
    CanoeingData,
    CanyoningData,
    CavingData,
    ClimbingData,
    CrossCountrySkiingData,
    DivingData,
    DownhillSkiingData,
    FitnessData,
    GearCheckoutFacts,
    GearItem,
    GearMaintenanceData,
    GearUsageData,
    JoggingData,
    Journal,
    JournalContactRelationship,
    JournalContactRelationshipType,
    KayakingData,
    LogbookEntryData,
    MoodData,
    OutdoorActivityData,
    OutdoorActivityDismissal,
    OutdoorActivityFacts,
    OutdoorActivityTypeFacts,
    OutdoorPlanningData,
    OutdoorTrainingData,
    PlanData,
    PlanDocument,
    SnorkellingData,
    TemplateReferenceFacts,
    TravelAccommodation,
    TravelData,
    TravelFlight,
    TravelTransportation,
    UpcomingOutdoorActivity,
)
from core_shared.models.route import Route

from .journal_series import JournalSeries
from .journal_tag import JournalTag


class JournalRepository(ABC):
    """
    Repository interface for journal operations.

    Provides basic CRUD operations and hierarchy queries for journals.
    Implementations handle database-specific logic.
    """

    @abstractmethod
    async def find_by_id(self, journal_id: int) -> Journal | None:
        """
        Find a journal by ID, **without** scoping it to an owner.

        This is for callers that have no acting user: integration workers and
        stream consumers, which process journals on nobody's behalf. Anything
        serving a request *does* have one and must use
        :meth:`find_by_id_for_user`, or it is deciding on ownership after the
        fact — which is how issue #1267 happened.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The Journal if found, None otherwise
        """
        pass

    @abstractmethod
    async def find_by_id_for_user(
        self, journal_id: int, user_id: str
    ) -> Journal | None:
        """
        Find a journal by ID, scoped to the user who owns it.

        Implementations must apply the owner predicate in the query itself, so
        a journal belonging to somebody else is indistinguishable from one that
        does not exist — the caller never holds it and so cannot leak it.

        Args:
            journal_id: The journal ID to look up
            user_id: The acting user; a journal owned by anybody else is absent

        Returns:
            The Journal if it exists and belongs to ``user_id``, None otherwise
        """
        pass

    @abstractmethod
    async def touch(self, journal_id: int) -> None:
        """
        Record that a journal changed, without changing its own columns.

        ``GET`` represents the journal aggregate — its own fields plus its
        types, type-data, tags and contact relationships — and its entity-tag
        comes from ``updated_at``. A write to any of those child rows must
        bump the parent, or a conditional write would be accepted despite a
        concurrent change it was meant to catch.

        Args:
            journal_id: The journal to mark as changed
        """
        pass

    @abstractmethod
    async def lock_and_get_updated_at(self, journal_id: int) -> datetime | None:
        """
        Lock a journal row for update and return its last-write timestamp.

        Backs the optimistic-concurrency check on updates. Comparing an
        entity-tag against an unlocked read leaves a lost-update window under
        READ COMMITTED: two callers can both see the version they expected
        before either of them writes. Taking the row lock here means the second
        caller waits for the first to commit and then sees the new timestamp.

        Args:
            journal_id: The journal to lock

        Returns:
            The journal's ``updated_at``, or None if no such journal exists
        """
        pass

    @abstractmethod
    async def get_types(self, journal_id: int) -> list[str]:
        """
        Get the types of a journal.

        Args:
            journal_id: The journal ID to look up

        Returns:
            A list of type strings for the journal, including 'NOTE' as the base type.
        """
        pass

    @abstractmethod
    async def find_ids_by_filters(
        self,
        user_id: str,
        journal_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        contact_id: str | None = None,
        tag_ids: list[str] | None = None,
        calendar_id: str | None = None,
        parent_id: int | None = None,
        search: str | None = None,
        journal_ids: list[int] | None = None,
    ) -> set[int]:
        """Ids of the user's journals matching the same filters as :meth:`get_all`.

        Unpaginated: for callers that intersect the matching set with another,
        such as a full-text search restricted to candidate ids.
        """
        pass

    @abstractmethod
    async def find_ids_by_integration_source(
        self, user_id: str, integration_source: str
    ) -> set[int]:
        """Ids of the user's journals linked to ``integration_source``."""
        pass

    @abstractmethod
    async def find_overlapping_for_user(
        self,
        user_id: str,
        *,
        exclude_journal_id: int,
        date_range: EventDateRange,
        limit: int,
    ) -> list[Journal]:
        """The user's other journals whose event range overlaps ``date_range``.

        Ranges that only touch at an endpoint overlap. Ordered by event start and
        capped at ``limit``; ``exclude_journal_id`` is never returned.
        """
        pass

    @abstractmethod
    async def find_by_ids_for_user(
        self, user_id: str, journal_ids: list[int]
    ) -> list[Journal]:
        """Find journals by IDs, scoped to a user.

        This is used for batch-loading related journals (e.g., parents) in a tenant-safe way.

        Args:
            user_id: The user ID to scope the lookup to
            journal_ids: Journal IDs to fetch

        Returns:
            List of journals belonging to the user whose IDs match
        """
        pass

    @abstractmethod
    async def find_and_lock_by_ids_for_user(
        self, user_id: str, journal_ids: list[int]
    ) -> list[Journal]:
        """Find journals by IDs, scoped to a user, holding each for the transaction.

        :meth:`find_by_ids_for_user` with a row lock, and it exists for the lock
        rather than for the read. A caller that is about to write rows carrying
        foreign keys to these journals will take ``FOR KEY SHARE`` on each of
        them anyway, when the write runs; taking the same locks **here**, before
        anything else, is what lets that caller choose the order it acquires
        them in.

        That matters because journal merge takes both of its journals
        ``FOR UPDATE`` in ascending id order and only then writes the task rows
        (see
        :meth:`~app.core.tasks.models.repositories.TaskAnchorRepository.repoint_journal_links`).
        ``TaskService.retarget_due_journal`` used to do the reverse — task row
        first, journals afterwards through its writes' foreign keys — and the two
        deadlocked. It now comes here first, with the same ascending order, so
        the two queue instead.

        The mode is ``FOR KEY SHARE``: the weakest that conflicts with the
        merge's ``FOR UPDATE`` and with a journal ``DELETE``, and precisely the
        one the foreign keys would take later, so nothing new is held — only held
        earlier. An ordinary journal ``UPDATE`` is deliberately **not** blocked,
        so editing a journal never waits behind somebody retargeting a task into
        it.

        The ids are locked one statement at a time, low to high, because a row
        lock does not promise to be taken in the order a query returns its rows —
        the same reason ``repoint_journal_links`` locks its pair one statement
        each.

        Callers must already be inside their unit of work: a lock taken outside
        one is released immediately and closes nothing.

        Args:
            user_id: The user ID to scope the lookup to
            journal_ids: Journal IDs to fetch and lock, in any order

        Returns:
            The user's journals among ``journal_ids``, in ascending id order.
            Ownership is enforced by the query, so another user's journal is
            simply absent — and never locked.
        """
        pass

    @abstractmethod
    async def get_by_ids_for_user(
        self,
        user_id: str,
        journal_ids: list[int],
        limit: int = 100,
        offset: int = 0,
    ) -> list[Journal]:
        """Get journals by IDs for a user with ordering + pagination.

        Results are ordered consistently with other journal list endpoints.

        Args:
            user_id: The user ID to scope the lookup to
            journal_ids: Journal IDs to fetch
            limit: Maximum number of journals to return
            offset: Number of journals to skip

        Returns:
            List of journals
        """
        pass

    @abstractmethod
    async def count_by_ids_for_user(self, user_id: str, journal_ids: list[int]) -> int:
        """Count journals by IDs for a user.

        Args:
            user_id: The user ID to scope the count to
            journal_ids: Journal IDs to count

        Returns:
            Count of matching journals
        """
        pass

    @abstractmethod
    async def count_children_for_parents(
        self, user_id: str, parent_ids: list[int]
    ) -> dict[int, int]:
        """Count direct children for each parent journal ID for a user.

        Args:
            user_id: The user ID to scope the count to
            parent_ids: Parent journal IDs to count children for

        Returns:
            Mapping of parent_id -> direct children count
        """
        pass

    @abstractmethod
    async def find_descendants_for_user(
        self,
        user_id: str,
        ancestor_ids: list[int],
        max_depth: int = 5,
    ) -> list[Journal]:
        """Find all descendant journals for the given ancestor journals, scoped to a user.

        This is used to render contact-page hierarchy: when a journal is directly related
        to a contact, we include its descendants even if those descendants have no direct
        relationship to the contact.

        Args:
            user_id: The user ID to scope the lookup to (tenant isolation)
            ancestor_ids: Journal IDs whose descendants should be returned
            max_depth: Maximum recursion depth from the provided ancestors

        Returns:
            List of descendant journals (excluding the ancestors themselves)
        """
        pass

    @abstractmethod
    async def save(self, journal: Journal) -> Journal:
        """
        Save a journal (insert or update).

        Args:
            journal: The journal to save

        Returns:
            The saved journal with updated fields (id, timestamps)
        """
        pass

    @abstractmethod
    async def delete(self, journal_id: int) -> None:
        """
        Delete a journal by ID.

        Args:
            journal_id: The journal ID to delete
        """
        pass

    @abstractmethod
    async def get_children(self, parent_id: int) -> list[Journal]:
        """
        Get child journals of a parent.

        Children are ordered by event_date_range.start, then by order field.

        Args:
            parent_id: The parent journal ID

        Returns:
            List of child journals in order
        """
        pass

    @abstractmethod
    async def get_ancestors(self, journal_id: int) -> list[Journal]:
        """
        Get all ancestor journals of a given journal (from parent to root).

        Used to calculate hierarchy depth and detect cycles.

        Args:
            journal_id: The journal ID to find ancestors for

        Returns:
            List of ancestor journals ordered from immediate parent to root
        """
        pass

    @abstractmethod
    async def get_depth(self, journal_id: int) -> int:
        """
        Get the depth of a journal in the hierarchy.

        Root journals have depth 1.

        Args:
            journal_id: The journal ID

        Returns:
            The depth (1-based)
        """
        pass

    @abstractmethod
    async def get_depth_bulk(self, journal_ids: list[int]) -> dict[int, int]:
        """
        Get the depth of multiple journals in the hierarchy.

        Root journals have depth 1.

        Args:
            journal_ids: List of journal IDs

        Returns:
            Dictionary mapping journal_id to its depth (1-based)
        """
        pass

    @abstractmethod
    async def get_all(
        self,
        user_id: str,
        limit: int = 100,
        offset: int = 0,
        journal_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        contact_id: str | None = None,
        tag_ids: list[str] | None = None,
        calendar_id: str | None = None,
        parent_id: int | None = None,
        search: str | None = None,
        journal_ids: list[int] | None = None,
    ) -> list[Journal]:
        """
        Get all journals for a user with pagination and filtering.

        Args:
            user_id: The user ID to filter by
            limit: Maximum number of journals to return
            offset: Number of journals to skip
            journal_type: Optional journal type to filter by (e.g., "MOOD_RATING", "EVENT")
            start_date: Optional start date filter (ISO format)
            end_date: Optional end date filter (ISO format)
            contact_id: Optional contact ID to filter journals by
            tag_ids: Optional tag IDs to filter journals by (matches any of them)
            calendar_id: Optional calendar ID to filter journals by
            parent_id: Optional parent journal ID to filter by (None for root journals)
            search: Optional search query for full-text search

        Returns:
            List of journals matching the filter criteria
        """
        pass

    @abstractmethod
    async def get_root_journals(
        self, user_id: str, limit: int = 100, offset: int = 0
    ) -> list[Journal]:
        """
        Get root journals (no parent) for a user.

        Args:
            user_id: The user ID to filter by
            limit: Maximum number of journals to return
            offset: Number of journals to skip

        Returns:
            List of root journals
        """
        pass

    @abstractmethod
    async def count_by_user(self, user_id: str) -> int:
        """
        Count total journals for a user.

        Args:
            user_id: The user ID to count journals for

        Returns:
            Total count of journals
        """
        pass

    @abstractmethod
    async def count_all(
        self,
        user_id: str,
        journal_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        contact_id: str | None = None,
        tag_ids: list[str] | None = None,
        calendar_id: str | None = None,
        parent_id: int | None = None,
        search: str | None = None,
        journal_ids: list[int] | None = None,
    ) -> int:
        """
        Count journals for a user with filtering.

        Uses the same filter logic as get_all() but returns only the count.
        This is more efficient than fetching all records when only the count is needed.

        Args:
            user_id: The user ID to filter by
            journal_type: Optional journal type to filter by
            start_date: Optional start date filter (ISO format)
            end_date: Optional end date filter (ISO format)
            contact_id: Optional contact ID to filter journals by
            tag_ids: Optional tag IDs to filter journals by (matches any of them)
            calendar_id: Optional calendar ID to filter journals by
            parent_id: Optional parent journal ID to filter by
            search: Optional search query for full-text search

        Returns:
            Count of journals matching the filter criteria
        """
        pass

    @abstractmethod
    async def get_external_event_links(self, journal_id: int) -> list[dict[str, Any]]:
        """
        Get Google Calendar external event links for a journal.

        Args:
            journal_id: The journal ID

        Returns:
            List of dictionaries containing link details
        """
        pass

    @abstractmethod
    async def get_snipeit_links(
        self, journal_id: int, user_id: str
    ) -> list[dict[str, Any]]:
        """
        Get Snipe-IT external links for a journal.

        Args:
            journal_id: The journal ID
            user_id: The user ID

        Returns:
            List of dictionaries containing link details
        """
        pass

    @abstractmethod
    async def get_immich_album_links(self, journal_id: int) -> list[dict[str, Any]]:
        """
        Get Immich album external links for a journal.

        Args:
            journal_id: The journal ID

        Returns:
            List of dictionaries with 'album_id' and 'shared_link_url' keys
        """
        pass

    @abstractmethod
    async def get_strava_activity_ids(self, journal_id: int) -> list[str]:
        """
        Get every Strava activity id linked to a journal.

        A journal carries more than one after an additive fitness merge, where
        two activities making up a single outing both stay linked.

        Args:
            journal_id: The journal ID

        Returns:
            Strava activity ids, oldest link first, without duplicates
        """
        pass


class CalendarRepository(ABC):
    """
    Repository interface for calendar operations.

    Calendars are used to organize journals and optionally sync with Google Calendar.
    """

    @abstractmethod
    async def find_by_id(self, calendar_id: UUID) -> Calendar | None:
        """
        Find a calendar by ID.

        Args:
            calendar_id: The calendar UUID to look up

        Returns:
            The Calendar if found, None otherwise
        """
        pass

    @abstractmethod
    async def find_linked_to_journal(self, journal_id: int) -> list[Calendar]:
        """
        Find every calendar a journal's event lives in.

        An event de-duplicated across calendars is one journal linked to
        several, while it is still *displayed* in exactly one.

        Args:
            journal_id: The journal to look up

        Returns:
            The calendars, display calendar first; empty for a non-event
        """
        pass

    @abstractmethod
    async def save(self, calendar: Calendar) -> Calendar:
        """
        Save a calendar (insert or update).

        Args:
            calendar: The calendar to save

        Returns:
            The saved calendar with updated fields (id, timestamps)
        """
        pass

    @abstractmethod
    async def delete(self, calendar_id: UUID) -> None:
        """
        Delete a calendar by ID.

        Args:
            calendar_id: The calendar UUID to delete
        """
        pass

    @abstractmethod
    async def get_all(self, user_id: str) -> list[Calendar]:
        """
        Get all calendars for a user.

        Args:
            user_id: The user ID to filter by

        Returns:
            List of calendars
        """
        pass

    @abstractmethod
    async def get_synced_calendars(self, user_id: str) -> list[Calendar]:
        """
        Get all calendars synced to Google Calendar for a user.

        Args:
            user_id: The user ID to filter by

        Returns:
            List of synced calendars
        """
        pass


class CalendarInfoRepository(ABC):
    """
    Repository interface for calendar info (EVENT type) operations.

    A journal has the EVENT type if a CalendarInfo row exists for its journal_id.
    """

    @abstractmethod
    async def find_by_journal_id(self, journal_id: int) -> CalendarInfo | None:
        """
        Find calendar info by journal ID.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The CalendarInfo if found (journal has EVENT type), None otherwise
        """
        pass

    @abstractmethod
    async def save(self, calendar_info: CalendarInfo) -> CalendarInfo:
        """
        Save calendar info (insert or update).

        This effectively adds or updates the EVENT type for a journal.

        Args:
            calendar_info: The calendar info to save

        Returns:
            The saved calendar info with updated timestamps
        """
        pass

    @abstractmethod
    async def delete(self, journal_id: int) -> None:
        """
        Delete calendar info by journal ID.

        This effectively removes the EVENT type from a journal.

        Args:
            journal_id: The journal ID to delete calendar info for
        """
        pass

    @abstractmethod
    async def get_by_calendar_id(self, calendar_id: UUID) -> list[CalendarInfo]:
        """
        Get all calendar info entries for a calendar.

        Args:
            calendar_id: The calendar UUID to filter by

        Returns:
            List of calendar info entries
        """
        pass

    @abstractmethod
    async def find_cancelled_journal_ids(self, journal_ids: list[int]) -> set[int]:
        """Which of these journals are cancelled events.

        Batched rather than answered one journal at a time because the callers
        ask about a whole set at once — a task's three journal roles, or every
        task due in one journal — and the tasks read model derives *lapsed* from
        the answer on every read. One ``find_by_journal_id`` per journal there
        would be the N+1 that read model exists to avoid.

        Only ``EventState.CANCELLED`` counts. ``invited`` and ``tentative`` are
        not cancellations: a meeting the user has not yet accepted is still
        going ahead as far as the calendar is concerned.

        A journal with no calendar-info row is simply absent from the result
        rather than an error — cancellation is per-event-type data, so a plain
        note journal is *not cancelled* rather than unknown. Ids that do not
        exist at all are absent for the same reason, and this method performs no
        ownership check: callers reach it with ids they have already scoped.

        Args:
            journal_ids: The journals to ask about; an empty list queries nothing

        Returns:
            The subset of ``journal_ids`` whose event state is cancelled.
        """
        pass


class MoodDataRepository(ABC):
    """
    Repository interface for mood data (MOOD_RATING type) operations.

    A journal has the MOOD_RATING type if a MoodData row exists for its journal_id.
    """

    @abstractmethod
    async def find_by_journal_id(self, journal_id: int) -> MoodData | None:
        """
        Find mood data by journal ID.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The MoodData if found (journal has MOOD_RATING type), None otherwise
        """
        pass

    @abstractmethod
    async def save(self, mood_data: MoodData) -> MoodData:
        """
        Save mood data (insert or update).

        This effectively adds or updates the MOOD_RATING type for a journal.

        Args:
            mood_data: The mood data to save

        Returns:
            The saved mood data with updated timestamps
        """
        pass

    @abstractmethod
    async def delete(self, journal_id: int) -> None:
        """
        Delete mood data by journal ID.

        This effectively removes the MOOD_RATING type from a journal.

        Args:
            journal_id: The journal ID to delete mood data for
        """
        pass


class FitnessDataRepository(ABC):
    """
    Repository interface for fitness data (FITNESS type) operations.

    A journal has the FITNESS type if a FitnessData row exists for its journal_id.
    """

    @abstractmethod
    async def find_by_journal_id(self, journal_id: int) -> FitnessData | None:
        """
        Find fitness data by journal ID.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The FitnessData if found (journal has FITNESS type), None otherwise
        """
        pass

    @abstractmethod
    async def save(self, fitness_data: FitnessData) -> FitnessData:
        """
        Save fitness data (insert or update).

        This effectively adds or updates the FITNESS type for a journal.

        Args:
            fitness_data: The fitness data to save

        Returns:
            The saved fitness data with updated timestamps
        """
        pass

    @abstractmethod
    async def delete(self, journal_id: int) -> None:
        """
        Delete fitness data by journal ID.

        This effectively removes the FITNESS type from a journal.

        Args:
            journal_id: The journal ID to delete fitness data for
        """
        pass


class GearUsageDataRepository(ABC):
    """
    Repository interface for gear usage data (GEAR_USAGE type) operations.

    A journal has the GEAR_USAGE type if a GearUsageData entry exists for its
    journal_id, whether or not the entry holds any gear items.
    """

    @abstractmethod
    async def find_by_journal_id(self, journal_id: int) -> GearUsageData | None:
        """
        Find gear usage data by journal ID.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The GearUsageData entry with its items in order if found (journal
            has GEAR_USAGE type), None otherwise
        """
        pass

    @abstractmethod
    async def save(self, gear_usage_data: GearUsageData) -> GearUsageData:
        """
        Save gear usage data (insert or update) with exactly its items.

        This effectively adds or updates the GEAR_USAGE type for a journal. Items
        the entry no longer lists are removed; the others keep ``created_at``.

        Args:
            gear_usage_data: The gear usage data to save

        Returns:
            The saved gear usage data with updated timestamps
        """
        pass

    @abstractmethod
    async def delete(self, journal_id: int) -> None:
        """
        Delete gear usage data by journal ID.

        This effectively removes the GEAR_USAGE type from a journal.

        Args:
            journal_id: The journal ID to delete gear usage data for
        """
        pass


class PlanDataRepository(ABC):
    """
    Repository interface for plan data (PLAN type) operations.

    A journal has the PLAN type if a PlanData row exists for its journal_id.
    Plan documents are managed separately but loaded with plan data.
    """

    @abstractmethod
    async def find_by_journal_id(self, journal_id: int) -> PlanData | None:
        """
        Find plan data by journal ID, including associated documents.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The PlanData with documents if found (journal has PLAN type), None otherwise
        """
        pass

    @abstractmethod
    async def save(self, plan_data: PlanData) -> PlanData:
        """
        Save plan data (insert or update).

        This effectively adds or updates the PLAN type for a journal.
        Documents are saved separately.

        Args:
            plan_data: The plan data to save

        Returns:
            The saved plan data with updated timestamps
        """
        pass

    @abstractmethod
    async def delete(self, journal_id: int) -> None:
        """
        Delete plan data by journal ID.

        This effectively removes the PLAN type from a journal.
        Associated documents are cascade deleted.

        Args:
            journal_id: The journal ID to delete plan data for
        """
        pass

    @abstractmethod
    async def save_document(self, document: PlanDocument) -> PlanDocument:
        """
        Save a plan document (insert or update).

        Args:
            document: The plan document to save

        Returns:
            The saved plan document with updated timestamps
        """
        pass

    @abstractmethod
    async def delete_document(self, document_id: UUID) -> None:
        """
        Delete a plan document by ID.

        Args:
            document_id: The document UUID to delete
        """
        pass

    @abstractmethod
    async def get_documents(self, journal_id: int) -> list[PlanDocument]:
        """
        Get all documents for a plan, ordered by order field.

        Args:
            journal_id: The journal ID to get documents for

        Returns:
            List of plan documents in order
        """
        pass


class TravelDataRepository(ABC):
    """
    Repository interface for travel data (TRAVEL type) operations.

    A journal has the TRAVEL type if a TravelData row exists for its journal_id.
    Travel components (flights, accommodations, transportation) are managed separately
    but loaded with travel data.
    """

    @abstractmethod
    async def find_by_journal_id(self, journal_id: int) -> TravelData | None:
        """
        Find travel data by journal ID, including all associated components.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The TravelData with all components if found (journal has TRAVEL type), None otherwise
        """
        pass

    @abstractmethod
    async def save(self, travel_data: TravelData) -> TravelData:
        """
        Save travel data (insert or update).

        This effectively adds or updates the TRAVEL type for a journal.
        Components are saved separately.

        Args:
            travel_data: The travel data to save

        Returns:
            The saved travel data with updated timestamps
        """
        pass

    @abstractmethod
    async def delete(self, journal_id: int) -> None:
        """
        Delete travel data by journal ID.

        This effectively removes the TRAVEL type from a journal.
        Associated components are cascade deleted.

        Args:
            journal_id: The journal ID to delete travel data for
        """
        pass

    @abstractmethod
    async def save_flight(self, flight: TravelFlight) -> TravelFlight:
        """
        Save a travel flight (insert or update).

        Args:
            flight: The travel flight to save

        Returns:
            The saved travel flight with updated timestamps
        """
        pass

    @abstractmethod
    async def delete_flight(self, flight_id: UUID) -> None:
        """
        Delete a travel flight by ID.

        Args:
            flight_id: The flight UUID to delete
        """
        pass

    @abstractmethod
    async def save_accommodation(
        self, accommodation: TravelAccommodation
    ) -> TravelAccommodation:
        """
        Save a travel accommodation (insert or update).

        Args:
            accommodation: The travel accommodation to save

        Returns:
            The saved travel accommodation with updated timestamps
        """
        pass

    @abstractmethod
    async def delete_accommodation(self, accommodation_id: UUID) -> None:
        """
        Delete a travel accommodation by ID.

        Args:
            accommodation_id: The accommodation UUID to delete
        """
        pass

    @abstractmethod
    async def save_transportation(
        self, transportation: TravelTransportation
    ) -> TravelTransportation:
        """
        Save a travel transportation (insert or update).

        Args:
            transportation: The travel transportation to save

        Returns:
            The saved travel transportation with updated timestamps
        """
        pass

    @abstractmethod
    async def delete_transportation(self, transportation_id: UUID) -> None:
        """
        Delete a travel transportation by ID.

        Args:
            transportation_id: The transportation UUID to delete
        """
        pass


class JournalTagRepository(ABC):
    """
    Repository interface for journal tag operations.

    Tags are hierarchical (parent-child relationships) and can be assigned to journals.
    """

    @abstractmethod
    async def find_by_id(self, tag_id: UUID) -> JournalTag | None:
        """
        Find a tag by ID.

        Args:
            tag_id: The tag UUID to look up

        Returns:
            The JournalTag if found, None otherwise
        """
        pass

    @abstractmethod
    async def find_by_name(self, name: str) -> JournalTag | None:
        """
        Find a tag by name.

        Args:
            name: The tag name to look up

        Returns:
            The JournalTag if found, None otherwise
        """
        pass

    @abstractmethod
    async def save(self, tag: JournalTag) -> JournalTag:
        """
        Save a tag (insert or update).

        Args:
            tag: The tag to save

        Returns:
            The saved tag with updated fields (id, timestamps)
        """
        pass

    @abstractmethod
    async def delete(self, tag_id: UUID) -> None:
        """
        Delete a tag by ID.

        Args:
            tag_id: The tag UUID to delete
        """
        pass

    @abstractmethod
    async def merge_into(self, source_id: UUID, target_id: UUID) -> None:
        """
        Fold the source tag into the target tag and delete the source.

        Every journal assigned the source tag ends up assigned the target tag
        (journals already holding both keep a single assignment), and any child
        tags of the source are re-parented to the target.

        Callers are responsible for validating that both tags exist and that
        the target is not a descendant of the source.

        Args:
            source_id: The tag being merged away and deleted
            target_id: The surviving tag

        Raises:
            ValueError: ``source_id`` and ``target_id`` are the same tag.
                Merging a tag into itself would delete all of its assignments
                and then the tag, so it is rejected rather than performed.
        """
        pass

    @abstractmethod
    async def get_journal_ids_for_tag(self, tag_id: UUID) -> list[int]:
        """
        List the journals currently assigned this tag.

        The inverse of :meth:`get_tags_for_journal`. Tag-scoped writes publish
        journal-scoped history events, so they need to know which journals a
        change reaches — and for destructive writes they must ask *before* the
        assignments cascade away.

        Args:
            tag_id: The tag whose journals to list

        Returns:
            The ids of every journal carrying the tag, ascending. Empty when the
            tag is unassigned or does not exist.
        """
        pass

    @abstractmethod
    async def get_all(self) -> list[JournalTag]:
        """
        Get all tags.

        Returns:
            List of all tags
        """
        pass

    @abstractmethod
    async def get_descendants_for_tags(self, tag_ids: list[UUID]) -> list[JournalTag]:
        """
        Get all descendant tags (recursively) for a list of tag UUIDs.

        Backs hierarchical tag filtering: a journal tagged only with a child
        tag is returned when filtering by any of its ancestors.

        Args:
            tag_ids: The tag UUIDs to expand

        Returns:
            Descendant tags, excluding the requested tags themselves
        """
        pass

    @abstractmethod
    async def get_children(self, parent_id: UUID) -> list[JournalTag]:
        """
        Get child tags of a parent tag.

        Args:
            parent_id: The parent tag UUID

        Returns:
            List of child tags
        """
        pass

    @abstractmethod
    async def get_root_tags(self) -> list[JournalTag]:
        """
        Get all root tags (no parent).

        Returns:
            List of root tags
        """
        pass

    @abstractmethod
    async def get_tags_for_journal(self, journal_id: int) -> list[JournalTag]:
        """
        Get all tags assigned to a journal.

        Args:
            journal_id: The journal ID to get tags for

        Returns:
            List of tags assigned to the journal
        """
        pass

    @abstractmethod
    async def assign_tag(self, journal_id: int, tag_id: UUID) -> bool:
        """
        Assign a tag to a journal.

        Assignment is idempotent, so the return value is how the caller learns
        whether anything actually changed — the service publishes a history event
        only when it did.

        Args:
            journal_id: The journal ID
            tag_id: The tag UUID to assign

        Returns:
            True if a new assignment was created, False if it already existed.
        """
        pass

    @abstractmethod
    async def remove_tag(self, journal_id: int, tag_id: UUID) -> bool:
        """
        Remove a tag from a journal.

        Args:
            journal_id: The journal ID
            tag_id: The tag UUID to remove

        Returns:
            True if an assignment was deleted, False if there was none.
        """
        pass


class JournalSeriesRepository(ABC):
    """
    Repository interface for journal series operations.

    A series groups related journals. Series are either auto-created from a
    recurring calendar event (keyed by calendar_id + recurring_event_id) or
    created manually. All queries are scoped to the owning user.
    """

    @abstractmethod
    async def find_by_id(self, series_id: UUID, user_id: str) -> JournalSeries | None:
        """Find a series by ID, scoped to the owning user."""
        pass

    @abstractmethod
    async def find_all(self, user_id: str) -> list[JournalSeries]:
        """Get all series for a user, ordered by name."""
        pass

    @abstractmethod
    async def save(self, series: JournalSeries) -> JournalSeries:
        """Save a series (insert when id is None, update otherwise)."""
        pass

    @abstractmethod
    async def delete(self, series_id: UUID, user_id: str) -> None:
        """Delete a series; memberships cascade, member journals are untouched."""
        pass

    @abstractmethod
    async def get_or_create_by_recurrence(
        self,
        user_id: str,
        calendar_id: UUID,
        recurring_event_id: str,
        name: str,
        split_recurring_event_id: str | None = None,
    ) -> JournalSeries:
        """Get or atomically create the series for a recurring calendar event.

        Keyed by (calendar_id, recurring_event_id); ``name`` is only used when
        the series doesn't exist yet — an existing series is never renamed.
        A recurrence whose series was merged into another resolves, through
        its alias, to the series that absorbed it.

        ``split_recurring_event_id`` is the instance's own recurring id when
        the source folded it into ``recurring_event_id`` (a split recurrence).
        An alias on it wins: the user merged that split somewhere and its
        instances follow. It never creates a series of its own.
        """
        pass

    @abstractmethod
    async def lock_for_merge(
        self, series_ids: Sequence[UUID], user_id: str
    ) -> set[UUID]:
        """Lock the user's series rows a merge reads and writes, until commit.

        Taken before a series merge reads either series, so two merges that
        share a series run one after the other and the second sees what the
        first committed. Returns the ids actually held (the user's own).
        """
        pass

    @abstractmethod
    async def alias_recurrences(
        self, absorbed: JournalSeries, into_series_id: UUID
    ) -> None:
        """Point ``absorbed``'s recurrences at ``into_series_id`` before a merge.

        Covers ``absorbed``'s own recurrence key (if it was auto-created) and
        every alias it already holds from earlier merges, so later syncs of any
        of them resolve to the absorbing series. Every one of those keys is
        held until the transaction ends, so call it before moving
        ``absorbed``'s members and deleting it.
        """
        pass

    @abstractmethod
    async def move_members(self, from_series_id: UUID, to_series_id: UUID) -> None:
        """Move every member of one series into another (shared members dedupe)."""
        pass

    @abstractmethod
    async def add_member(self, series_id: UUID, journal_id: int) -> None:
        """Add a journal to a series (no-op if already a member)."""
        pass

    @abstractmethod
    async def remove_member(self, series_id: UUID, journal_id: int) -> None:
        """Remove a journal from a series (no-op if not a member)."""
        pass

    @abstractmethod
    async def get_member_journal_ids(self, series_id: UUID) -> list[int]:
        """Get the journal IDs belonging to a series."""
        pass

    @abstractmethod
    async def get_series_for_journal(
        self, journal_id: int, user_id: str
    ) -> list[JournalSeries]:
        """Get all series a journal belongs to, scoped to the owning user."""
        pass

    @abstractmethod
    async def get_series_names_for_journal_ids(
        self, journal_ids: list[int], user_id: str
    ) -> dict[int, list[str]]:
        """Bulk-fetch series names per journal (journals without series omitted)."""
        pass


class JournalContactRelationshipRepository(ABC):
    """
    Repository interface for journal-contact relationship operations.

    Manages relationships between journals and contacts with different relationship types.
    """

    @abstractmethod
    async def create(
        self, relationship: JournalContactRelationship
    ) -> JournalContactRelationship:
        """
        Create a new journal-contact relationship.

        Args:
            relationship: The relationship to create

        Returns:
            The created relationship with created_at timestamp
        """
        pass

    @abstractmethod
    async def delete(
        self,
        journal_id: int,
        contact_id: int,
        relationship_type: JournalContactRelationshipType,
    ) -> None:
        """
        Delete a specific journal-contact relationship.

        Args:
            journal_id: The journal ID
            contact_id: The contact ID
            relationship_type: The relationship type to delete
        """
        pass

    @abstractmethod
    async def get_by_journal(self, journal_id: int) -> list[JournalContactRelationship]:
        """
        Get all relationships for a journal.

        Args:
            journal_id: The journal ID to filter by

        Returns:
            List of relationships for the journal
        """
        pass

    @abstractmethod
    async def get_by_contact(self, contact_id: int) -> list[JournalContactRelationship]:
        """
        Get all relationships for a contact.

        Args:
            contact_id: The contact ID to filter by

        Returns:
            List of relationships for the contact
        """
        pass

    @abstractmethod
    async def get_by_journal_and_type(
        self, journal_id: int, relationship_type: JournalContactRelationshipType
    ) -> list[JournalContactRelationship]:
        """
        Get all relationships of a specific type for a journal.

        Args:
            journal_id: The journal ID to filter by
            relationship_type: The relationship type to filter by

        Returns:
            List of relationships matching the criteria
        """
        pass

    @abstractmethod
    async def update_status(
        self,
        journal_id: int,
        contact_id: int,
        relationship_type: JournalContactRelationshipType,
        status: AttendeeStatus,
        expected_current_status: AttendeeStatus | None = None,
    ) -> JournalContactRelationship | None:
        """
        Update the attendee status of a journal-contact relationship.

        Args:
            journal_id: The journal ID
            contact_id: The contact ID
            relationship_type: The relationship type
            status: The new attendee status
            expected_current_status: If provided, only update if the current status matches this.

        Returns:
            The updated relationship, or None if not found
        """
        pass

    @abstractmethod
    async def update_attributes(
        self,
        journal_id: int,
        contact_id: int,
        relationship_type: JournalContactRelationshipType,
        status: AttendeeStatus | None = None,
        role: ContactEventRole | None = None,
        update_status: bool = False,
        update_role: bool = False,
    ) -> JournalContactRelationship | None:
        """
        Update the attributes (status, role) of a journal-contact relationship.

        Args:
            journal_id: The journal ID
            contact_id: The contact ID
            relationship_type: The relationship type
            status: The new attendee status (optional)
            role: The new contact event role (optional)
            update_status: Whether to update the status field (even if None)
            update_role: Whether to update the role field (even if None)

        Returns:
            The updated relationship, or None if not found
        """
        pass

    @abstractmethod
    async def find_attending_for_past_events(
        self,
        cutoff_time: datetime,
        batch_size: int = 100,
    ) -> list[JournalContactRelationship]:
        """
        Find relationships with ATTENDING status on past events.

        Returns relationships where status is ATTENDING and the journal's
        event_date_range end is before the cutoff_time.

        Args:
            cutoff_time: Events ending before this time are considered past.
            batch_size: Maximum number of relationships to return.

        Returns:
            List of eligible relationships for transition.
        """
        pass

    @abstractmethod
    async def repoint_contact(
        self, source_id: int, survivor_id: int, transaction: AsyncConnection
    ) -> None:
        """
        Re-point the source contact's journal links onto the survivor.

        Moves every ``journal_contact_relationships`` row from the source contact
        to the survivor, deduping on the ``(journal_id, contact_id,
        relationship_type)`` composite primary key.

        Args:
            source_id: The contact being absorbed.
            survivor_id: The contact that survives the merge.
            transaction: The connection running the merge unit of work.
        """
        pass


class RouteRepository(ABC):
    """
    Repository interface for route operations.

    Routes are GPX tracks or mapped paths owned by a specific journal.
    """

    @abstractmethod
    async def find_by_id(self, route_id: UUID) -> Route | None:
        """
        Find a route by ID.

        Args:
            route_id: The route UUID to look up

        Returns:
            The Route if found, None otherwise
        """
        pass

    @abstractmethod
    async def find_by_id_for_update(self, route_id: UUID) -> Route | None:
        """
        Find a route by ID and lock its row until the transaction ends.

        For read-modify-write: a concurrent caller locking the same route waits,
        so it merges its change into the row this caller saved.

        Args:
            route_id: The route UUID to look up

        Returns:
            The Route if found, None otherwise
        """
        pass

    @abstractmethod
    async def save(self, route: Route) -> Route:
        """
        Save a route (insert or update).

        Args:
            route: The route to save

        Returns:
            The saved route with updated fields (id, timestamps)
        """
        pass

    @abstractmethod
    async def delete(self, route_id: UUID) -> None:
        """
        Delete a route by ID.

        Args:
            route_id: The route UUID to delete
        """
        pass

    @abstractmethod
    async def find_by_journal_id(self, journal_id: int) -> list[Route]:
        """
        Get all routes associated with a specific journal.

        Args:
            journal_id: The journal ID to filter by

        Returns:
            List of routes for the journal
        """
        pass

    @abstractmethod
    async def find_by_journal_id_paginated(
        self,
        journal_id: int,
        name_filter: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Route], int]:
        """
        Get routes for a journal with filtering and pagination.

        Args:
            journal_id: The journal ID
            name_filter: Optional name filter
            limit: Maximum number of routes to return
            offset: Number of routes to skip

        Returns:
            Tuple of (list of routes, total count matching filter)
        """
        pass

    @abstractmethod
    async def find_usage_history(
        self, user_id: str, route_id: UUID
    ) -> list[RouteUsageRow]:
        """The user's journals a route was used on, newest first.

        A route on another user's journal, or one that does not exist, has no
        usage.
        """
        pass


class OutdoorActivityDataRepository(ABC):
    """
    Repository interface for outdoor activity data (OUTDOOR_ACTIVITY type) operations.

    A journal has the OUTDOOR_ACTIVITY type if an OutdoorActivityData row exists
    for its journal_id.
    """

    @abstractmethod
    async def find_by_journal_id(self, journal_id: int) -> OutdoorActivityData | None:
        """
        Find outdoor activity data by journal ID.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The OutdoorActivityData if found, None otherwise
        """
        pass

    @abstractmethod
    async def save(self, data: OutdoorActivityData) -> OutdoorActivityData:
        """
        Save outdoor activity data (insert or update).

        This effectively adds or updates the OUTDOOR_ACTIVITY type for a journal.

        Args:
            data: The outdoor activity data to save

        Returns:
            The saved data with updated timestamps
        """
        pass

    @abstractmethod
    async def delete(self, journal_id: int) -> None:
        """
        Delete outdoor activity data by journal ID.

        This effectively removes the OUTDOOR_ACTIVITY type from a journal.

        Args:
            journal_id: The journal ID to delete outdoor activity data for
        """
        pass


class BushwalkingDataRepository(ABC):
    """
    Repository interface for bushwalking data (BUSHWALKING type) operations.

    A journal has the BUSHWALKING type if a BushwalkingData row exists for its journal_id.
    """

    @abstractmethod
    async def find_by_journal_id(self, journal_id: int) -> BushwalkingData | None:
        """
        Find bushwalking data by journal ID.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The BushwalkingData if found, None otherwise
        """
        pass

    @abstractmethod
    async def save(self, data: BushwalkingData) -> BushwalkingData:
        """
        Save bushwalking data (insert or update).

        This effectively adds or updates the BUSHWALKING type for a journal.

        Args:
            data: The bushwalking data to save

        Returns:
            The saved data with updated timestamps
        """
        pass

    @abstractmethod
    async def delete(self, journal_id: int) -> None:
        """
        Delete bushwalking data by journal ID.

        This effectively removes the BUSHWALKING type from a journal.

        Args:
            journal_id: The journal ID to delete bushwalking data for
        """
        pass


class JoggingDataRepository(ABC):
    """
    Repository interface for jogging data (JOGGING type) operations.

    A journal has the JOGGING type if a JoggingData row exists for its journal_id.
    """

    @abstractmethod
    async def find_by_journal_id(self, journal_id: int) -> JoggingData | None:
        """
        Find jogging data by journal ID.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The JoggingData if found, None otherwise
        """
        pass

    @abstractmethod
    async def save(self, data: JoggingData) -> JoggingData:
        """
        Save jogging data (insert or update).

        This effectively adds or updates the JOGGING type for a journal.

        Args:
            data: The jogging data to save

        Returns:
            The saved data with updated timestamps
        """
        pass

    @abstractmethod
    async def delete(self, journal_id: int) -> None:
        """
        Delete jogging data by journal ID.

        This effectively removes the JOGGING type from a journal.

        Args:
            journal_id: The journal ID to delete jogging data for
        """
        pass


class AbseilingDataRepository(ABC):
    """
    Repository interface for abseiling data (ABSEILING_TRIP type) operations.

    A journal has the ABSEILING_TRIP type if an AbseilingData row exists for its journal_id.
    """

    @abstractmethod
    async def find_by_journal_id(self, journal_id: int) -> AbseilingData | None:
        """
        Find abseiling data by journal ID.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The AbseilingData if found, None otherwise
        """
        pass

    @abstractmethod
    async def save(self, data: AbseilingData) -> AbseilingData:
        """
        Save abseiling data (insert or update).

        This effectively adds or updates the ABSEILING_TRIP type for a journal.

        Args:
            data: The abseiling data to save

        Returns:
            The saved data with updated timestamps
        """
        pass

    @abstractmethod
    async def delete(self, journal_id: int) -> None:
        """
        Delete abseiling data by journal ID.

        This effectively removes the ABSEILING_TRIP type from a journal.

        Args:
            journal_id: The journal ID to delete abseiling data for
        """
        pass


class AbseilPitchRepository(ABC):
    """
    Repository interface for abseil pitch operations.

    Manages individual abseil pitches within an ABSEILING_TRIP journal.
    Pitches are stored in the abseil_pitches table with a FK to journal_abseiling_data.
    """

    @abstractmethod
    async def save(self, pitch: AbseilPitch) -> AbseilPitch:
        """
        Save an abseil pitch (insert or update).

        Uses UPSERT on (journal_id, pitch_number) to handle both creation
        and update in a single operation.

        Args:
            pitch: The abseil pitch to save

        Returns:
            The saved pitch with updated fields (id, timestamps)
        """
        pass

    @abstractmethod
    async def find_by_journal_id(self, journal_id: int) -> list[AbseilPitch]:
        """
        Find all pitches for a journal, ordered by pitch_number.

        Args:
            journal_id: The journal ID to look up

        Returns:
            List of AbseilPitch entities ordered by pitch_number
        """
        pass

    @abstractmethod
    async def delete_by_journal_id(self, journal_id: int) -> None:
        """
        Delete all pitches for a journal.

        Args:
            journal_id: The journal ID to delete pitches for
        """
        pass

    @abstractmethod
    async def delete(self, pitch_id: int) -> None:
        """
        Delete a single pitch by ID.

        Args:
            pitch_id: The pitch ID to delete
        """
        pass


class CanyoningDataRepository(ABC):
    """
    Repository interface for canyoning data (CANYONING type) operations.

    A journal has the CANYONING type if a CanyoningData row exists for its journal_id.
    """

    @abstractmethod
    async def find_by_journal_id(self, journal_id: int) -> CanyoningData | None:
        """
        Find canyoning data by journal ID.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The CanyoningData if found, None otherwise
        """
        pass

    @abstractmethod
    async def save(self, data: CanyoningData) -> CanyoningData:
        """
        Save canyoning data (insert or update).

        This effectively adds or updates the CANYONING type for a journal.

        Args:
            data: The canyoning data to save

        Returns:
            The saved data with updated timestamps
        """
        pass

    @abstractmethod
    async def delete(self, journal_id: int) -> None:
        """
        Delete canyoning data by journal ID.

        This effectively removes the CANYONING type from a journal.

        Args:
            journal_id: The journal ID to delete canyoning data for
        """
        pass


class ClimbingDataRepository(ABC):
    """
    Repository interface for climbing data (CLIMBING type) operations.

    A journal has the CLIMBING type if a ClimbingData row exists for its journal_id.
    """

    @abstractmethod
    async def find_by_journal_id(self, journal_id: int) -> ClimbingData | None:
        """
        Find climbing data by journal ID.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The ClimbingData if found, None otherwise
        """
        pass

    @abstractmethod
    async def save(self, data: ClimbingData) -> ClimbingData:
        """
        Save climbing data (insert or update).

        This effectively adds or updates the CLIMBING type for a journal.

        Args:
            data: The climbing data to save

        Returns:
            The saved data with updated timestamps
        """
        pass

    @abstractmethod
    async def delete(self, journal_id: int) -> None:
        """
        Delete climbing data by journal ID.

        This effectively removes the CLIMBING type from a journal.

        Args:
            journal_id: The journal ID to delete climbing data for
        """
        pass


class KayakingDataRepository(ABC):
    """
    Repository interface for kayaking data (KAYAKING type) operations.

    A journal has the KAYAKING type if a KayakingData row exists for its journal_id.
    """

    @abstractmethod
    async def find_by_journal_id(self, journal_id: int) -> KayakingData | None:
        """
        Find kayaking data by journal ID.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The KayakingData if found, None otherwise
        """
        pass

    @abstractmethod
    async def save(self, data: KayakingData) -> KayakingData:
        """
        Save kayaking data (insert or update).

        This effectively adds or updates the KAYAKING type for a journal.

        Args:
            data: The kayaking data to save

        Returns:
            The saved data with updated timestamps
        """
        pass

    @abstractmethod
    async def delete(self, journal_id: int) -> None:
        """
        Delete kayaking data by journal ID.

        This effectively removes the KAYAKING type from a journal.

        Args:
            journal_id: The journal ID to delete kayaking data for
        """
        pass


class CrossCountrySkiingDataRepository(ABC):
    """
    Repository interface for cross-country skiing data (CROSS_COUNTRY_SKIING type) operations.

    A journal has the CROSS_COUNTRY_SKIING type if a CrossCountrySkiingData row
    exists for its journal_id.
    """

    @abstractmethod
    async def find_by_journal_id(
        self, journal_id: int
    ) -> CrossCountrySkiingData | None:
        """
        Find cross-country skiing data by journal ID.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The CrossCountrySkiingData if found, None otherwise
        """
        pass

    @abstractmethod
    async def save(self, data: CrossCountrySkiingData) -> CrossCountrySkiingData:
        """
        Save cross-country skiing data (insert or update).

        This effectively adds or updates the CROSS_COUNTRY_SKIING type for a journal.

        Args:
            data: The cross-country skiing data to save

        Returns:
            The saved data with updated timestamps
        """
        pass

    @abstractmethod
    async def delete(self, journal_id: int) -> None:
        """
        Delete cross-country skiing data by journal ID.

        This effectively removes the CROSS_COUNTRY_SKIING type from a journal.

        Args:
            journal_id: The journal ID to delete cross-country skiing data for
        """
        pass


class CavingDataRepository(ABC):
    """
    Repository interface for caving data (CAVING type) operations.

    A journal has the CAVING type if a CavingData row exists for its journal_id.
    """

    @abstractmethod
    async def find_by_journal_id(self, journal_id: int) -> CavingData | None:
        """
        Find caving data by journal ID.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The CavingData if found, None otherwise
        """
        pass

    @abstractmethod
    async def save(self, data: CavingData) -> CavingData:
        """
        Save caving data (insert or update).

        This effectively adds or updates the CAVING type for a journal.

        Args:
            data: The caving data to save

        Returns:
            The saved data with updated timestamps
        """
        pass

    @abstractmethod
    async def delete(self, journal_id: int) -> None:
        """
        Delete caving data by journal ID.

        This effectively removes the CAVING type from a journal.

        Args:
            journal_id: The journal ID to delete caving data for
        """
        pass


class CanoeingDataRepository(ABC):
    """
    Repository interface for canoeing data (CANOEING type) operations.

    A journal has the CANOEING type if a CanoeingData row exists for its journal_id.
    """

    @abstractmethod
    async def find_by_journal_id(self, journal_id: int) -> CanoeingData | None:
        """
        Find canoeing data by journal ID.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The CanoeingData if found, None otherwise
        """
        pass

    @abstractmethod
    async def save(self, data: CanoeingData) -> CanoeingData:
        """
        Save canoeing data (insert or update).

        This effectively adds or updates the CANOEING type for a journal.

        Args:
            data: The canoeing data to save

        Returns:
            The saved data with updated timestamps
        """
        pass

    @abstractmethod
    async def delete(self, journal_id: int) -> None:
        """
        Delete canoeing data by journal ID.

        This effectively removes the CANOEING type from a journal.

        Args:
            journal_id: The journal ID to delete canoeing data for
        """
        pass


class ReviewItemRepository(ABC):
    """
    Repository interface for review item operations.

    Review items represent potential matches between journals that need
    user review before merging or dismissing.
    """

    @abstractmethod
    async def create(self, review_item: ReviewItem) -> tuple[ReviewItem, bool]:
        """
        Create a review item.

        Uses ON CONFLICT DO NOTHING for idempotency on the
        (source_journal_id, candidate_journal_id) unique constraint.

        Args:
            review_item: The review item to create

        Returns:
            A tuple of (ReviewItem, bool) where the bool indicates if the item was newly created
            (True) or already existed (False).
        """
        pass

    @abstractmethod
    async def find_by_journal_pair(
        self, journal_id: int, other_journal_id: int, user_id: str
    ) -> ReviewItem | None:
        """
        Find the review item describing a pair of journals, in either order.

        The unique constraint is on the ordered pair, so a caller that has
        no say in which journal is the source cannot use it to tell whether
        the pair is already queued. Producers record the pair in whichever
        order suits them: match detection makes the incoming journal the
        source, while cross-calendar identity sorts by id.

        Args:
            journal_id: One of the two journals
            other_journal_id: The other journal
            user_id: The user who owns both

        Returns:
            The review item for the pair whichever way round it was
            recorded, or None if the pair has never been queued. Items the
            user has already resolved or dismissed are returned too — a
            decision about the pair is still a decision.
        """
        pass

    @abstractmethod
    async def find_pending_by_journal_id(
        self, journal_id: int, user_id: str
    ) -> list[ReviewItem]:
        """
        Find all pending review items where a journal is the source.

        Args:
            journal_id: The source journal ID to look up

        Returns:
            List of pending review items for the journal
        """
        pass

    @abstractmethod
    async def find_pending_by_user(
        self, user_id: str, limit: int = 50, offset: int = 0
    ) -> list[ReviewItem]:
        """
        Find all pending review items for a user, paginated.

        Args:
            user_id: The user ID to look up
            limit: Maximum number of items to return
            offset: Number of items to skip

        Returns:
            List of pending review items ordered by confidence_score DESC
        """
        pass

    @abstractmethod
    async def count_pending_by_user(self, user_id: str) -> int:
        """
        Count pending review items for a user.

        Args:
            user_id: The user ID to count for

        Returns:
            Total number of pending review items
        """
        pass

    @abstractmethod
    async def find_pending_journal_ids_by_user(self, user_id: str) -> set[int]:
        """
        Find journal IDs that have pending review items for a user.

        Returns both source and candidate journal IDs so that list indicators
        can flag any journal involved in a pending review.

        Args:
            user_id: The user ID to look up

        Returns:
            Set of journal IDs with pending review items
        """
        pass

    @abstractmethod
    async def update_status(
        self, review_item_id: int, new_status: str, user_id: str
    ) -> ReviewItem | None:
        """
        Update the status of a review item.

        Args:
            review_item_id: The review item ID to update
            new_status: The new status value (e.g. 'resolved', 'dismissed')
            user_id: The user ID for ownership verification

        Returns:
            The updated ReviewItem, or None if not found
        """
        pass


class ActivityTemplateRepository(ABC):
    """
    Repository interface for activity template operations.

    Activity templates are user-owned, reusable canyon/cave/climb definitions
    that pre-populate pitch data when selected during journal creation.
    """

    @abstractmethod
    async def save(self, template: ActivityTemplate) -> ActivityTemplate:
        """
        Save an activity template (insert or update).

        When inserting, also persists associated pitches.
        When updating, replaces existing pitches with the template's current pitches.

        Args:
            template: The activity template to save

        Returns:
            The saved template with updated fields (id, timestamps, pitches)
        """
        pass

    @abstractmethod
    async def find_by_id(self, template_id: str) -> ActivityTemplate | None:
        """
        Find an activity template by ID, including its pitches.

        Args:
            template_id: The template UUID string to look up

        Returns:
            The ActivityTemplate with pitches if found, None otherwise
        """
        pass

    @abstractmethod
    async def find_by_user(
        self, user_id: str, template_type: str | None = None
    ) -> list[ActivityTemplate]:
        """
        Find all templates for a user, optionally filtered by type.

        Templates are returned ordered by name ascending.

        Args:
            user_id: The owner user ID
            template_type: Optional type filter (canyoning, caving, climbing)

        Returns:
            List of templates (without pitches for performance)
        """
        pass

    @abstractmethod
    async def search_by_name(
        self, user_id: str, query: str, template_type: str | None = None
    ) -> list[ActivityTemplate]:
        """
        Search templates by name for a user using case-insensitive partial matching.

        Args:
            user_id: The owner user ID
            query: The search query string
            template_type: Optional type filter

        Returns:
            List of matching templates ordered by name (without pitches)
        """
        pass

    @abstractmethod
    async def delete(self, template_id: str) -> None:
        """
        Delete an activity template by ID.

        Associated pitches are cascade-deleted by the database.

        Args:
            template_id: The template UUID string to delete
        """
        pass


class SnorkellingDataRepository(ABC):
    """
    Repository interface for snorkelling data (SNORKELLING type) operations.

    A journal has the SNORKELLING type if a SnorkellingData row exists for its journal_id.
    """

    @abstractmethod
    async def find_by_journal_id(self, journal_id: int) -> SnorkellingData | None:
        """
        Find snorkelling data by journal ID.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The SnorkellingData if found, None otherwise
        """
        pass

    @abstractmethod
    async def save(self, data: SnorkellingData) -> SnorkellingData:
        """
        Save snorkelling data (insert or update).

        This effectively adds or updates the SNORKELLING type for a journal.

        Args:
            data: The snorkelling data to save

        Returns:
            The saved data with updated timestamps
        """
        pass

    @abstractmethod
    async def delete(self, journal_id: int) -> None:
        """
        Delete snorkelling data by journal ID.

        This effectively removes the SNORKELLING type from a journal.

        Args:
            journal_id: The journal ID to delete snorkelling data for
        """
        pass


class DivingDataRepository(ABC):
    """
    Repository interface for diving data (DIVING type) operations.

    A journal has the DIVING type if a DivingData row exists for its journal_id.
    """

    @abstractmethod
    async def find_by_journal_id(self, journal_id: int) -> DivingData | None:
        """
        Find diving data by journal ID.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The DivingData if found, None otherwise
        """
        pass

    @abstractmethod
    async def save(self, data: DivingData) -> DivingData:
        """
        Save diving data (insert or update).

        This effectively adds or updates the DIVING type for a journal.

        Args:
            data: The diving data to save

        Returns:
            The saved data with updated timestamps
        """
        pass

    @abstractmethod
    async def delete(self, journal_id: int) -> None:
        """
        Delete diving data by journal ID.

        This effectively removes the DIVING type from a journal.

        Args:
            journal_id: The journal ID to delete diving data for
        """
        pass


class DownhillSkiingDataRepository(ABC):
    """
    Repository interface for downhill skiing data (DOWNHILL_SKIING type) operations.

    A journal has the DOWNHILL_SKIING type if a DownhillSkiingData row exists for its journal_id.
    """

    @abstractmethod
    async def find_by_journal_id(self, journal_id: int) -> DownhillSkiingData | None:
        """
        Find downhill skiing data by journal ID.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The DownhillSkiingData if found, None otherwise
        """
        pass

    @abstractmethod
    async def save(self, data: DownhillSkiingData) -> DownhillSkiingData:
        """
        Save downhill skiing data (insert or update).

        This effectively adds or updates the DOWNHILL_SKIING type for a journal.

        Args:
            data: The downhill skiing data to save

        Returns:
            The saved data with updated timestamps
        """
        pass

    @abstractmethod
    async def delete(self, journal_id: int) -> None:
        """
        Delete downhill skiing data by journal ID.

        This effectively removes the DOWNHILL_SKIING type from a journal.

        Args:
            journal_id: The journal ID to delete downhill skiing data for
        """
        pass


class GearItemRepository(ABC):
    """
    Repository interface for gear item operations.

    Gear items are user-owned supporting entities that represent
    equipment (e.g. rope, harness, helmet). They are referenced
    from GEAR_MAINTENANCE journal type data.
    """

    @abstractmethod
    async def save(self, gear_item: GearItem) -> GearItem:
        """
        Save a gear item (insert or update).

        Args:
            gear_item: The gear item to save

        Returns:
            The saved gear item with updated fields (id, timestamps)
        """
        pass

    @abstractmethod
    async def find_by_id(self, gear_item_id: str) -> GearItem | None:
        """
        Find a gear item by ID.

        Args:
            gear_item_id: The gear item UUID string to look up

        Returns:
            The GearItem if found, None otherwise
        """
        pass

    @abstractmethod
    async def find_by_user(self, user_id: str) -> list[GearItem]:
        """
        Find all gear items for a user, ordered by name ascending.

        Args:
            user_id: The owner user ID

        Returns:
            List of gear items ordered by name
        """
        pass

    @abstractmethod
    async def search_by_name(self, user_id: str, query: str) -> list[GearItem]:
        """
        Search gear items by name using case-insensitive partial matching.

        Args:
            user_id: The owner user ID
            query: The search query string

        Returns:
            List of matching gear items ordered by name
        """
        pass

    @abstractmethod
    async def delete(self, gear_item_id: str) -> None:
        """
        Delete a gear item by ID.

        Args:
            gear_item_id: The gear item UUID string to delete
        """
        pass

    @abstractmethod
    async def get_snipeit_links(
        self, gear_item_id: str, user_id: str
    ) -> list[dict[str, Any]]:
        """
        Get Snipe-IT external links for a gear item.

        Args:
            gear_item_id: The gear item UUID string
            user_id: The user ID

        Returns:
            List of dictionaries containing link details
        """
        pass


class OutdoorTrainingDataRepository(ABC):
    """
    Repository interface for outdoor training data (OUTDOOR_TRAINING type) operations.

    A journal has the OUTDOOR_TRAINING type if a OutdoorTrainingData row exists for its journal_id.
    """

    @abstractmethod
    async def find_by_journal_id(self, journal_id: int) -> OutdoorTrainingData | None:
        """
        Find outdoor training data by journal ID.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The OutdoorTrainingData if found, None otherwise
        """
        pass

    @abstractmethod
    async def save(self, data: OutdoorTrainingData) -> OutdoorTrainingData:
        """
        Save outdoor training data (insert or update).

        This effectively adds or updates the OUTDOOR_TRAINING type for a journal.

        Args:
            data: The outdoor training data to save

        Returns:
            The saved data with updated timestamps
        """
        pass

    @abstractmethod
    async def delete(self, journal_id: int) -> None:
        """
        Delete outdoor training data by journal ID.

        This effectively removes the OUTDOOR_TRAINING type from a journal.

        Args:
            journal_id: The journal ID to delete outdoor training data for
        """
        pass


class OutdoorPlanningDataRepository(ABC):
    """
    Repository interface for outdoor planning data (OUTDOOR_PLANNING type) operations.

    A journal has the OUTDOOR_PLANNING type if a OutdoorPlanningData row exists for its journal_id.
    """

    @abstractmethod
    async def find_by_journal_id(self, journal_id: int) -> OutdoorPlanningData | None:
        """
        Find outdoor planning data by journal ID.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The OutdoorPlanningData if found, None otherwise
        """
        pass

    @abstractmethod
    async def save(self, data: OutdoorPlanningData) -> OutdoorPlanningData:
        """
        Save outdoor planning data (insert or update).

        This effectively adds or updates the OUTDOOR_PLANNING type for a journal.

        Args:
            data: The outdoor planning data to save

        Returns:
            The saved data with updated timestamps
        """
        pass

    @abstractmethod
    async def delete(self, journal_id: int) -> None:
        """
        Delete outdoor planning data by journal ID.

        This effectively removes the OUTDOOR_PLANNING type from a journal.

        Args:
            journal_id: The journal ID to delete outdoor planning data for
        """
        pass


class GearMaintenanceDataRepository(ABC):
    """
    Repository interface for gear maintenance data (GEAR_MAINTENANCE type) operations.

    A journal has the GEAR_MAINTENANCE type if a GearMaintenanceData row exists for its journal_id.
    """

    @abstractmethod
    async def find_by_journal_id(self, journal_id: int) -> GearMaintenanceData | None:
        """
        Find gear maintenance data by journal ID.

        Args:
            journal_id: The journal ID to look up

        Returns:
            The GearMaintenanceData if found, None otherwise
        """
        pass

    @abstractmethod
    async def save(self, data: GearMaintenanceData) -> GearMaintenanceData:
        """
        Save gear maintenance data (insert or update).

        This effectively adds or updates the GEAR_MAINTENANCE type for a journal.

        Args:
            data: The gear maintenance data to save

        Returns:
            The saved data with updated timestamps
        """
        pass

    @abstractmethod
    async def delete(self, journal_id: int) -> None:
        """
        Delete gear maintenance data by journal ID.

        This effectively removes the GEAR_MAINTENANCE type from a journal.

        Args:
            journal_id: The journal ID to delete gear maintenance data for
        """
        pass


class LogbookExportRepository(ABC):
    """Repository for fetching bulk data for the logbook export."""

    @abstractmethod
    async def get_logbook_entries(
        self,
        user_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
        activity_types: list[str] | None = None,
    ) -> list[LogbookEntryData]:
        """
        Get all matching journals for the logbook export with their nested type data.

        Returns a flat list of `LogbookEntryData` objects that the
        LogbookDataService will assemble into a hierarchical tree.
        """
        pass


class OutdoorActivityDismissalRepository(ABC):
    """Repository interface for outdoor-activity review dismissals.

    A dismissal is journal-scoped and reversible, and is stored separately from
    the merge ``journal_review_items`` queue. A row's presence means the journal
    has been dismissed from the incomplete-activities review for that user.
    """

    @abstractmethod
    async def dismiss(
        self, journal_id: int, user_id: str, provenance: Provenance
    ) -> OutdoorActivityDismissal:
        """Dismiss a journal for a user (idempotent upsert).

        Re-dismissing an already-dismissed journal keeps a single row and
        refreshes its provenance/``updated_at`` rather than raising.
        """
        pass

    @abstractmethod
    async def undismiss(self, journal_id: int, user_id: str) -> bool:
        """Un-dismiss a journal for a user (idempotent delete).

        Returns ``True`` if a dismissal was removed, ``False`` if the journal was
        not dismissed (a harmless no-op).
        """
        pass

    @abstractmethod
    async def list_dismissed_journal_ids(self, user_id: str) -> set[int]:
        """Return the set of journal ids the user has dismissed."""
        pass


class IncompleteOutdoorActivityRepository(ABC):
    """Read repository for the incomplete outdoor activities projection.

    Returns per-journal :class:`OutdoorActivityFacts` for a user's outdoor
    journals (those with a ``journal_outdoor_activity_data`` row). Rule
    evaluation deliberately lives in ``evaluate_incompleteness`` (core_shared),
    not in SQL, so the rules stay pure and unit-testable.
    """

    @abstractmethod
    async def list_outdoor_activity_facts(
        self, user_id: str
    ) -> list[OutdoorActivityFacts]:
        """Fetch the facts for every outdoor journal owned by ``user_id``."""
        pass


class ActivityStatsRepository(ABC):
    """Read repository for a user's activity journals and their aggregates.

    An activity journal is one with fitness data; its effective activity type
    and metrics are described in ``app.core.journal.models.activity_stats``.
    Every read covers only ``filters.user_id``'s journals.
    """

    @abstractmethod
    async def list_activity_journals(
        self,
        filters: ActivityFilters,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ActivityJournalRow]:
        """Matching activity journals, newest event first."""
        pass

    @abstractmethod
    async def count_activity_journals(self, filters: ActivityFilters) -> int:
        """How many activity journals match, ignoring any paging."""
        pass

    @abstractmethod
    async def get_totals(self, filters: ActivityFilters) -> ActivityTotalsRow:
        """Metric totals across every matching journal (zeros when none match)."""
        pass

    @abstractmethod
    async def list_type_totals(
        self, filters: ActivityFilters
    ) -> list[ActivityTypeTotalsRow]:
        """Metric totals per effective activity type, ordered by type."""
        pass

    @abstractmethod
    async def find_personal_record(
        self, filters: ActivityFilters, metric: ActivityMetric
    ) -> ActivityPersonalRecordRow | None:
        """The matching journal with the highest ``metric``, if any match.

        Ties go to the most recent event.
        """
        pass

    @abstractmethod
    async def list_trend_buckets(
        self, filters: ActivityFilters, interval: TrendInterval
    ) -> list[ActivityTrendRow]:
        """Metric totals per UTC ``interval`` bucket of event start, oldest first."""
        pass


class OutdoorDashboardRepository(ABC):
    """Read repository for the outdoor logbook dashboard projections.

    The upcoming/totals queries are windowed over
    ``journals.event_date_range_start/end`` with an overlap predicate (a
    multi-day trip already underway still matches). The gear/template queries
    return per-row facts. Window arithmetic, ordering, capping, the
    checked-out determination and all grouping live in
    ``OutdoorDashboardService`` (via the core_shared pure rules) so they stay
    pure and unit-testable.
    """

    @abstractmethod
    async def list_upcoming_journals(
        self, user_id: str, *, window_start: datetime, window_end: datetime
    ) -> list[UpcomingOutdoorActivity]:
        """Outdoor and OUTDOOR_PLANNING journals overlapping the window."""
        pass

    @abstractmethod
    async def list_outdoor_type_facts(
        self, user_id: str, *, window_start: datetime, window_end: datetime
    ) -> list[OutdoorActivityTypeFacts]:
        """Per-journal subtype facts for outdoor journals in the window."""
        pass

    @abstractmethod
    async def list_gear_checkout_facts(
        self, user_id: str, *, ending_after: datetime
    ) -> list[GearCheckoutFacts]:
        """Gear-usage rows whose resolved check-in falls after ``ending_after``.

        Dates come back resolved (buffer overrides falling back to the
        journal's event range); rows whose window has already ended are
        excluded as a cheap bound — ``is_currently_checked_out`` remains the
        single source of the full determination.
        """
        pass

    @abstractmethod
    async def list_template_references(
        self, user_id: str
    ) -> list[TemplateReferenceFacts]:
        """One row per abseiling-derived journal referencing a template.

        Each row carries the referencing journal's event range so the service
        can apply the recent-templates window without a second query.
        """
        pass


class AgendaRepository(ABC):
    """Reads the event journals an agenda window covers.

    Here rather than in the dashboard domain, beside ``OutdoorDashboardRepository``
    and for the same reason: every table it reads is a journal table and every
    row it returns is a journal. The dashboard was its first caller, which is not
    the same as being its owner — the daily summary is the second, and a
    journal-domain caller reaching into the dashboard for a read over journal
    tables had the dependency backwards.
    """

    @abstractmethod
    async def list_entries_in_window(
        self, user_id: str, *, window: EventDateRange, anchor: date
    ) -> list[AgendaEntry]:
        """The user's event journals on the day ``window`` and ``anchor`` describe.

        **Two parameters for one day, because timed and all-day events are asked
        about differently.** A timed event happens at instants, so it is matched
        by **overlap** against ``window``: one that began before the day and ends
        after it is inside it in the only sense the agenda cares about — it is
        happening. That is the outdoor dashboard's semantics.

        An all-day event happens on a *date* and has no meaningful instants, so
        it is matched against ``anchor`` by date. Matching it by instant reads
        the wrong day: a date-only event synced from Google is stored at midnight
        UTC, which for a user west of UTC falls in the previous local day's
        window. See the adapter for how the stored bounds are resolved back to
        the date they were written as.

        Only journals with calendar info are returned — a journal has the EVENT
        type exactly when a ``journal_calendar_info`` row exists for it, so a
        journal without one is a note about the day rather than something
        scheduled on it. Cancelled events are returned **flagged**, not filtered:
        the specification requires them to be shown clearly marked, and a surface
        cannot mark an entry it was never sent.

        The order of the result is not part of the contract — ordering is
        ``order_agenda_entries``' job, and it belongs to the caller rather than
        to the query.

        Scoped on ``user_id``, which every implementation must honour: nothing on
        an agenda is shared between users, and a read port with no owner
        parameter is the shape that eventually leaks one user's day to another.

        Args:
            user_id: The acting user. Implementations must scope on it.
            window: The instants the day covers, from ``local_day_window`` —
                the span timed events are matched against.
            anchor: The day itself, in the user's timezone — the date all-day
                events are matched against.

        Returns:
            The matching entries with their tags and participants already
            attached, in no guaranteed order.
        """
        pass
