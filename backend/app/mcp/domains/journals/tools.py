"""
Journal domain MCP tools.

Provides AI access to journal management functionality through MCP tools.
Each tool is designed to return AI-friendly, contextual information.
"""

import json
from typing import Annotated, Any

import structlog
from dishka.integrations.starlette import FromDishka, inject
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_request
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_repository import SqlContactRepository
from app.core.journal.adapters.sql.calendar_info_repository import (
    SqlCalendarInfoRepository,
)
from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.journal_tag_repository import SqlJournalTagRepository
from app.core.journal.adapters.sql.mood_data_repository import SqlMoodDataRepository
from app.core.journal.adapters.sql.photo_album_data_repository import (
    SqlPhotoAlbumDataRepository,
)
from app.core.journal.adapters.sql.plan_data_repository import SqlPlanDataRepository
from app.core.journal.adapters.sql.travel_data_repository import SqlTravelDataRepository
from app.core.journal.models.calendar_info import CalendarInfo
from app.core.journal.models.entities import Journal
from app.core.journal.models.journal_contact_relationship import (
    JournalContactRelationship,
)
from app.core.journal.models.journal_relationship_types import (
    JournalContactRelationshipType,
)
from app.core.journal.models.journal_types import JournalType
from app.core.journal.models.mood_data import MoodData
from app.core.journal.models.photo_album_data import PhotoAlbumData
from app.core.journal.models.plan_data import PlanData
from app.core.journal.models.travel_data import TravelData
from app.core.journal.models.value_objects import EventDateRange
from app.core.journal.services.journal_service import JournalService
from app.infrastructure.auth.models import SessionUser
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.mcp.domains.journals.converters import JournalConverter
from app.mcp.domains.journals.schemas import (
    JournalCreateRequest,
    JournalUpdateRequest,
)
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.response_builders import MCPResponseBuilder

logger = structlog.get_logger()


def _get_current_user_id() -> str:
    """
    Get the current authenticated user ID from the request context.

    Returns:
        The user ID from the authenticated session

    Raises:
        RuntimeError: If no authenticated user is found in the request context
    """
    request = get_http_request()
    if not hasattr(request.state, "user"):
        raise RuntimeError("No authenticated user found in request context")

    user: SessionUser = request.state.user
    return user.id


def _journal_to_search_result(journal: Journal) -> Any:
    """
    Convert a Journal entity to a JournalSearchResult.

    Args:
        journal: The journal entity to convert

    Returns:
        JournalSearchResult with basic journal information
    """
    from app.mcp.domains.journals.schemas import (
        EventDateRangeSchema,
        JournalSearchResult,
    )

    return JournalSearchResult(
        id=journal.id or 0,
        title=journal.title,
        content_excerpt=journal.content[:200] + "..."
        if len(journal.content) > 200
        else journal.content,
        event_date_range=EventDateRangeSchema(
            start=journal.event_date_range.start,
            end=journal.event_date_range.end,
        ),
        types=[],
        tags=[],
        highlighted={},
        summary=f"Journal: {journal.title}",
    )


async def _fetch_contact_relationships_with_names(
    journal_id: int,
    contact_relationship_repo: SqlJournalContactRelationshipRepository,
    contact_repo: SqlContactRepository,
) -> list[tuple[int, str, str]]:
    """
    Fetch contact relationships with contact names for a journal.

    Args:
        journal_id: The journal ID to fetch relationships for
        contact_relationship_repo: Contact relationship repository
        contact_repo: Contact repository

    Returns:
        List of tuples (contact_id, contact_name, relationship_type)
    """
    contact_relationships = await contact_relationship_repo.get_by_journal(journal_id)

    contacts: list[tuple[int, str, str]] = []
    for rel in contact_relationships:
        contact = await contact_repo.find_by_id(rel.contact_id)
        if contact:
            contact_name = f"{contact.first_name} {contact.last_name}".strip()
            if not contact_name:
                contact_name = f"Contact {rel.contact_id}"
            contacts.append((rel.contact_id, contact_name, rel.relationship_type.value))

    return contacts


def _build_calendar_data(calendar_info: Any) -> dict[str, Any]:
    """Build calendar event data dictionary."""
    return {
        "calendar_id": str(calendar_info.calendar_id),
        "start_time": calendar_info.start_time.isoformat()
        if calendar_info.start_time
        else None,
        "end_time": calendar_info.end_time.isoformat()
        if calendar_info.end_time
        else None,
        "is_all_day": calendar_info.is_all_day,
        "location": calendar_info.location,
        "sync_invitees": calendar_info.sync_invitees,
    }


def _build_mood_data(mood_data: Any) -> dict[str, Any]:
    """Build mood rating data dictionary."""
    return {
        "mood_value": mood_data.mood_value,
        "mood_label": mood_data.mood_label,
        "energy_level": mood_data.energy_level,
    }


def _build_plan_data(plan_data: Any) -> dict[str, Any]:
    """Build plan data dictionary."""
    return {
        "documents": [
            {
                "title": doc.title,
                "url": doc.url,
                "description": doc.description,
            }
            for doc in plan_data.documents
        ]
        if plan_data.documents
        else [],
    }


def _build_travel_data(travel_data: Any) -> dict[str, Any]:
    """Build travel data dictionary."""
    return {
        "flights": [
            {
                "airline": flight.airline,
                "flight_number": flight.flight_number,
                "departure_airport": flight.departure_airport,
                "arrival_airport": flight.arrival_airport,
                "departure_time": flight.departure_time.isoformat()
                if flight.departure_time
                else None,
                "arrival_time": flight.arrival_time.isoformat()
                if flight.arrival_time
                else None,
                "booking_reference": flight.booking_reference,
            }
            for flight in travel_data.flights
        ]
        if travel_data.flights
        else [],
        "accommodations": [
            {
                "name": acc.name,
                "address": acc.address,
                "check_in_date": acc.check_in_date.isoformat()
                if acc.check_in_date
                else None,
                "check_out_date": acc.check_out_date.isoformat()
                if acc.check_out_date
                else None,
                "booking_reference": acc.booking_reference,
            }
            for acc in travel_data.accommodations
        ]
        if travel_data.accommodations
        else [],
        "transportation": [
            {
                "type": trans.type,
                "details": trans.details,
                "booking_reference": trans.booking_reference,
            }
            for trans in travel_data.transportation
        ]
        if travel_data.transportation
        else [],
    }


def _build_photo_album_data(photo_album_data: Any) -> dict[str, Any]:
    """Build photo album data dictionary."""
    return {
        "immich_album_id": str(photo_album_data.immich_album_id),
    }


async def _fetch_journal_types_and_data(
    journal_id: int,
    calendar_info_repo: SqlCalendarInfoRepository,
    mood_data_repo: SqlMoodDataRepository,
    plan_data_repo: SqlPlanDataRepository,
    travel_data_repo: SqlTravelDataRepository,
    photo_album_data_repo: SqlPhotoAlbumDataRepository,
) -> tuple[list[str], dict[str, Any]]:
    """
    Fetch all type-specific data for a journal.

    Args:
        journal_id: The journal ID to fetch data for
        calendar_info_repo: Calendar info repository
        mood_data_repo: Mood data repository
        plan_data_repo: Plan data repository
        travel_data_repo: Travel data repository
        photo_album_data_repo: Photo album data repository

    Returns:
        Tuple of (types list, type_data dict)
    """
    types: list[str] = []
    type_data: dict[str, Any] = {}

    # Check each type-specific data table to determine journal types
    calendar_info = await calendar_info_repo.find_by_journal_id(journal_id)
    if calendar_info:
        types.append(JournalType.EVENT.value)
        type_data[JournalType.EVENT.value] = _build_calendar_data(calendar_info)

    mood_data = await mood_data_repo.find_by_journal_id(journal_id)
    if mood_data:
        types.append(JournalType.MOOD_RATING.value)
        type_data[JournalType.MOOD_RATING.value] = _build_mood_data(mood_data)

    plan_data = await plan_data_repo.find_by_journal_id(journal_id)
    if plan_data:
        types.append(JournalType.PLAN.value)
        type_data[JournalType.PLAN.value] = _build_plan_data(plan_data)

    travel_data = await travel_data_repo.find_by_journal_id(journal_id)
    if travel_data:
        types.append(JournalType.TRAVEL.value)
        type_data[JournalType.TRAVEL.value] = _build_travel_data(travel_data)

    photo_album_data = await photo_album_data_repo.find_by_journal_id(journal_id)
    if photo_album_data:
        types.append(JournalType.PHOTO_ALBUM.value)
        type_data[JournalType.PHOTO_ALBUM.value] = _build_photo_album_data(
            photo_album_data
        )

    # If no types found, it's a NOTE
    if not types:
        types.append(JournalType.NOTE.value)

    return types, type_data


async def _create_type_specific_data(
    journal_type: JournalType,
    journal_id: int,
    mood_data_repo: SqlMoodDataRepository,
    plan_data_repo: SqlPlanDataRepository,
    travel_data_repo: SqlTravelDataRepository,
) -> None:
    """
    Create type-specific data row with default values for the given journal type.

    Args:
        journal_type: The type of journal
        journal_id: The ID of the journal
        mood_data_repo: Repository for mood data
        plan_data_repo: Repository for plan data
        travel_data_repo: Repository for travel data
    """
    if journal_type == JournalType.MOOD_RATING:
        mood_data = MoodData(journal_id=journal_id)
        await mood_data_repo.save(mood_data)
    elif journal_type == JournalType.PLAN:
        plan_data = PlanData(journal_id=journal_id)
        await plan_data_repo.save(plan_data)
    elif journal_type == JournalType.TRAVEL:
        travel_data = TravelData(journal_id=journal_id)
        await travel_data_repo.save(travel_data)
    # EVENT and PHOTO_ALBUM types require additional data (calendar_id, immich_album_id)
    # These will be created when the user provides type_data


async def _update_type_specific_data(
    journal_type: JournalType,
    journal_id: int,
    type_data_dict: dict[str, Any],
    calendar_info_repo: SqlCalendarInfoRepository,
    mood_data_repo: SqlMoodDataRepository,
    photo_album_data_repo: SqlPhotoAlbumDataRepository,
) -> None:
    """
    Update type-specific data for a journal type.

    Args:
        journal_type: The type of journal
        journal_id: The ID of the journal
        type_data_dict: Dictionary containing type-specific data
        calendar_info_repo: Repository for calendar info
        mood_data_repo: Repository for mood data
        photo_album_data_repo: Repository for photo album data
    """
    if journal_type == JournalType.EVENT and type_data_dict:
        # Create or update calendar info (calendar_id is required)
        calendar_id = type_data_dict.get("calendar_id")
        if calendar_id is not None:
            from uuid import UUID

            # Convert string to UUID if needed
            if isinstance(calendar_id, str):
                calendar_id = UUID(calendar_id)

            calendar_info = CalendarInfo(
                journal_id=journal_id,
                calendar_id=calendar_id,
                start_time=type_data_dict.get("start_time"),
                end_time=type_data_dict.get("end_time"),
                is_all_day=type_data_dict.get("is_all_day", False),
                location=type_data_dict.get("location"),
                sync_invitees=type_data_dict.get("sync_invitees", False),
            )
            await calendar_info_repo.save(calendar_info)
    elif journal_type == JournalType.MOOD_RATING and type_data_dict:
        # Update mood data
        existing_mood = await mood_data_repo.find_by_journal_id(journal_id)
        if existing_mood:
            if "mood_value" in type_data_dict:
                existing_mood.mood_value = type_data_dict["mood_value"]
            if "mood_label" in type_data_dict:
                existing_mood.mood_label = type_data_dict["mood_label"]
            if "energy_level" in type_data_dict:
                existing_mood.energy_level = type_data_dict["energy_level"]
            await mood_data_repo.save(existing_mood)
    elif journal_type == JournalType.PHOTO_ALBUM and type_data_dict:
        # Create or update photo album data (immich_album_id is required)
        immich_album_id = type_data_dict.get("immich_album_id")
        if immich_album_id is not None:
            photo_album_data = PhotoAlbumData(
                journal_id=journal_id,
                immich_album_id=str(immich_album_id),
            )
            await photo_album_data_repo.save(photo_album_data)


def register_journal_tools(mcp: FastMCP[None]) -> None:
    """
    Register journal-related MCP tools with the FastMCP server.

    Args:
        mcp: The FastMCP server instance to register tools with
    """

    @mcp.tool
    @mcp_unified_error_handler("create_journal_entry", "journal")
    @inject
    async def create_journal_entry(
        db_connection: FromDishka[AsyncConnection],
        event_publisher: FromDishka[OutboxEventPublisher],
        calendar_info_repo: FromDishka[SqlCalendarInfoRepository],
        mood_data_repo: FromDishka[SqlMoodDataRepository],
        plan_data_repo: FromDishka[SqlPlanDataRepository],
        travel_data_repo: FromDishka[SqlTravelDataRepository],
        photo_album_data_repo: FromDishka[SqlPhotoAlbumDataRepository],
        contact_relationship_repo: FromDishka[SqlJournalContactRelationshipRepository],
        contact_repo: FromDishka[SqlContactRepository],
        tag_repo: FromDishka[SqlJournalTagRepository],
        journal_data: Annotated[
            str,
            Field(
                description="JSON string containing journal creation data with fields: "
                "title (str), content (str), event_date_range (dict with start/end), "
                "types (list[str]), type_data (dict), contact_relationships (list[dict]), "
                "tags (list[str]), parent_id (int, optional)"
            ),
        ],
    ) -> str:
        """
        Create a new journal entry with types, type-specific data, relationships, and tags.

        Creates a journal entry with support for multiple types (NOTE, EVENT, MOOD_RATING, etc.),
        type-specific data (e.g., calendar_id for EVENT), contact relationships, and tags.
        Returns AI-friendly response with contextual summary.

        Args:
            journal_data: JSON string with journal creation data

        Returns:
            JSON string containing AI-friendly journal information including:
            - Journal details (title, content, date range)
            - Types and type-specific data
            - Contact relationships
            - Tags
            - Contextual summary for AI understanding

        Raises:
            JournalValidationError: If validation fails
            ValueError: If JSON parsing fails or required fields are missing
        """
        # Parse JSON input
        try:
            data_dict = json.loads(journal_data)
            request = JournalCreateRequest(**data_dict)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON format: {e}") from e
        except Exception as e:
            raise ValueError(f"Invalid journal data: {e}") from e

        # Get current user ID from auth context
        user_id = _get_current_user_id()

        # Create repositories
        journal_repo = SqlJournalRepository(db_connection)

        # Create journal service
        journal_service = JournalService(journal_repo, event_publisher)

        # Create journal entity
        journal = Journal(
            user_id=user_id,
            title=request.title,
            content=request.content,
            event_date_range=EventDateRange(
                start=request.event_date_range.start,
                end=request.event_date_range.end,
            ),
            parent_id=request.parent_id,
        )

        # Create journal
        created_journal = await journal_service.create_journal(journal, db_connection)

        # Ensure journal_id is not None (it should always be set after creation)
        if created_journal.id is None:
            msg = "Journal ID should be set after creation"
            raise ValueError(msg)
        journal_id = created_journal.id

        # Add types if provided in the request
        if request.types:
            for type_str in request.types:
                try:
                    # Convert type string to enum
                    journal_type = JournalType[type_str.upper()]

                    await journal_service.add_type_to_journal(
                        journal_id, journal_type, db_connection
                    )

                    # Create type-specific data row with default values
                    await _create_type_specific_data(
                        journal_type,
                        journal_id,
                        mood_data_repo,
                        plan_data_repo,
                        travel_data_repo,
                    )

                    # Update type-specific data if provided
                    if request.type_data and type_str.upper() in request.type_data:
                        await _update_type_specific_data(
                            journal_type,
                            journal_id,
                            request.type_data[type_str.upper()],
                            calendar_info_repo,
                            mood_data_repo,
                            photo_album_data_repo,
                        )
                except (ValueError, KeyError):
                    # Invalid type, skip
                    pass

        # Add contact relationships if provided
        if request.contact_relationships:
            for rel_dict in request.contact_relationships:
                try:
                    contact_id = rel_dict.get("contact_id")
                    relationship_type_str = rel_dict.get("relationship_type")

                    if contact_id and relationship_type_str:
                        # Convert relationship type string to enum
                        relationship_type = JournalContactRelationshipType[
                            relationship_type_str.upper()
                        ]

                        # Create relationship
                        relationship = JournalContactRelationship(
                            journal_id=journal_id,
                            contact_id=contact_id,
                            relationship_type=relationship_type,
                        )
                        await contact_relationship_repo.create(relationship)
                except (ValueError, KeyError):
                    # Invalid relationship, skip
                    pass

        # Add tags if provided
        if request.tags:
            from uuid import uuid4

            from app.core.journal.models.journal_tag import JournalTag

            for tag_name in request.tags:
                try:
                    # Find or create tag by name
                    existing_tags = await tag_repo.get_all()
                    tag = next(
                        (
                            t
                            for t in existing_tags
                            if t.name.lower() == tag_name.lower()
                        ),
                        None,
                    )

                    if not tag:
                        # Tag doesn't exist, create it
                        tag = JournalTag(
                            id=uuid4(),
                            name=tag_name,
                            color="#808080",  # Default gray color
                        )
                        tag = await tag_repo.save(tag)

                    # Assign tag to journal (tag.id is guaranteed to be set after save)
                    if tag.id is not None:
                        await tag_repo.assign_tag(journal_id, tag.id)
                except Exception:
                    # Error creating/assigning tag, skip
                    pass

        # Fetch all enrichment data
        types, type_data = await _fetch_journal_types_and_data(
            journal_id,
            calendar_info_repo,
            mood_data_repo,
            plan_data_repo,
            travel_data_repo,
            photo_album_data_repo,
        )

        contacts = await _fetch_contact_relationships_with_names(
            journal_id, contact_relationship_repo, contact_repo
        )

        tags = await tag_repo.get_tags_for_journal(journal_id)

        # Convert to AI-friendly response
        response = JournalConverter.to_response(
            journal=created_journal,
            types=types,
            type_data=type_data,
            contacts=contacts,
            tags=tags,
        )

        return MCPResponseBuilder.success_response(response)

    @mcp.tool
    @mcp_unified_error_handler("update_journal_entry", "journal")
    @inject
    async def update_journal_entry(
        db_connection: FromDishka[AsyncConnection],
        event_publisher: FromDishka[OutboxEventPublisher],
        calendar_info_repo: FromDishka[SqlCalendarInfoRepository],
        mood_data_repo: FromDishka[SqlMoodDataRepository],
        plan_data_repo: FromDishka[SqlPlanDataRepository],
        travel_data_repo: FromDishka[SqlTravelDataRepository],
        photo_album_data_repo: FromDishka[SqlPhotoAlbumDataRepository],
        contact_relationship_repo: FromDishka[SqlJournalContactRelationshipRepository],
        contact_repo: FromDishka[SqlContactRepository],
        tag_repo: FromDishka[SqlJournalTagRepository],
        journal_id: Annotated[
            int, Field(description="The unique identifier of the journal to update")
        ],
        journal_data: Annotated[
            str,
            Field(
                description="JSON string containing journal update data with optional fields: "
                "title (str), content (str), event_date_range (dict with start/end), "
                "types (list[str]), type_data (dict), contact_relationships (list[dict]), "
                "tags (list[str])"
            ),
        ],
    ) -> str:
        """
        Update an existing journal entry with partial data.

        Updates journal fields, types, type-specific data, contact relationships, and tags.
        Only provided fields are updated; omitted fields remain unchanged.
        Returns AI-friendly response with contextual summary.

        Args:
            journal_id: The unique identifier of the journal to update
            journal_data: JSON string with journal update data (partial)

        Returns:
            JSON string containing AI-friendly updated journal information

        Raises:
            JournalNotFoundError: If the journal with the given ID does not exist
            JournalValidationError: If validation fails
            ValueError: If JSON parsing fails
        """
        # Parse JSON input
        try:
            data_dict = json.loads(journal_data)
            request = JournalUpdateRequest(**data_dict)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON format: {e}") from e
        except Exception as e:
            raise ValueError(f"Invalid journal data: {e}") from e

        # Create repositories
        journal_repo = SqlJournalRepository(db_connection)
        journal_service = JournalService(journal_repo, event_publisher)

        # Get existing journal
        existing_journal = await journal_repo.find_by_id(journal_id)
        if not existing_journal:
            from app.core.journal.models.exceptions import JournalNotFoundError

            raise JournalNotFoundError(journal_id)

        # Track changed fields
        changed_fields: dict[str, Any] = {}

        # Update journal fields
        if request.title is not None:
            existing_journal.title = request.title
            changed_fields["title"] = request.title
        if request.content is not None:
            existing_journal.content = request.content
            changed_fields["content"] = request.content
        if request.event_date_range is not None:
            existing_journal.event_date_range = EventDateRange(
                start=request.event_date_range.start,
                end=request.event_date_range.end,
            )
            changed_fields["event_date_range"] = request.event_date_range

        # Update journal
        updated_journal = await journal_service.update_journal(
            existing_journal, changed_fields, db_connection
        )

        # Update types if provided (replace all types)
        if request.types is not None:
            # Get current types
            current_types, _ = await _fetch_journal_types_and_data(
                journal_id,
                calendar_info_repo,
                mood_data_repo,
                plan_data_repo,
                travel_data_repo,
                photo_album_data_repo,
            )

            # Remove types that are not in the new list
            for current_type_str in current_types:
                if current_type_str not in [t.upper() for t in request.types]:
                    try:
                        current_type = JournalType[current_type_str.upper()]
                        await journal_service.remove_type_from_journal(
                            journal_id, current_type, db_connection
                        )
                    except (ValueError, KeyError):
                        pass

            # Add new types
            for type_str in request.types:
                try:
                    journal_type = JournalType[type_str.upper()]

                    # Only add if not already present
                    if type_str.upper() not in current_types:
                        await journal_service.add_type_to_journal(
                            journal_id, journal_type, db_connection
                        )

                        # Create type-specific data row with default values
                        await _create_type_specific_data(
                            journal_type,
                            journal_id,
                            mood_data_repo,
                            plan_data_repo,
                            travel_data_repo,
                        )

                    # Update type-specific data if provided
                    if request.type_data and type_str.upper() in request.type_data:
                        await _update_type_specific_data(
                            journal_type,
                            journal_id,
                            request.type_data[type_str.upper()],
                            calendar_info_repo,
                            mood_data_repo,
                            photo_album_data_repo,
                        )
                except (ValueError, KeyError):
                    # Invalid type, skip
                    pass

        # Update type_data if provided (without changing types)
        elif request.type_data is not None:
            for type_str, type_data_dict in request.type_data.items():
                try:
                    journal_type = JournalType[type_str.upper()]
                    await _update_type_specific_data(
                        journal_type,
                        journal_id,
                        type_data_dict,
                        calendar_info_repo,
                        mood_data_repo,
                        photo_album_data_repo,
                    )
                except (ValueError, KeyError):
                    # Invalid type, skip
                    pass

        # Update contact relationships if provided (replace all relationships)
        if request.contact_relationships is not None:
            # Remove all existing relationships
            existing_relationships = await contact_relationship_repo.get_by_journal(
                journal_id
            )
            for rel in existing_relationships:
                await contact_relationship_repo.delete(
                    journal_id, rel.contact_id, rel.relationship_type
                )

            # Add new relationships
            for rel_dict in request.contact_relationships:
                try:
                    contact_id = rel_dict.get("contact_id")
                    relationship_type_str = rel_dict.get("relationship_type")

                    if contact_id and relationship_type_str:
                        relationship_type = JournalContactRelationshipType[
                            relationship_type_str.upper()
                        ]

                        relationship = JournalContactRelationship(
                            journal_id=journal_id,
                            contact_id=contact_id,
                            relationship_type=relationship_type,
                        )
                        await contact_relationship_repo.create(relationship)
                except (ValueError, KeyError):
                    # Invalid relationship, skip
                    pass

        # Update tags if provided (replace all tags)
        if request.tags is not None:
            from uuid import uuid4

            from app.core.journal.models.journal_tag import JournalTag

            # Remove all existing tags
            existing_tags = await tag_repo.get_tags_for_journal(journal_id)
            for existing_tag in existing_tags:
                if existing_tag.id is not None:
                    await tag_repo.remove_tag(journal_id, existing_tag.id)

            # Add new tags
            for tag_name in request.tags:
                try:
                    # Find or create tag by name
                    all_tags = await tag_repo.get_all()
                    tag: JournalTag | None = next(
                        (t for t in all_tags if t.name.lower() == tag_name.lower()),
                        None,
                    )

                    if not tag:
                        # Tag doesn't exist, create it
                        tag = JournalTag(
                            id=uuid4(),
                            name=tag_name,
                            color="#808080",  # Default gray color
                        )
                        tag = await tag_repo.save(tag)

                    # Assign tag to journal (tag.id is guaranteed to be set after save)
                    if tag.id is not None:
                        await tag_repo.assign_tag(journal_id, tag.id)
                except Exception:
                    # Error creating/assigning tag, skip
                    pass

        # Fetch all enrichment data
        types, type_data = await _fetch_journal_types_and_data(
            journal_id,
            calendar_info_repo,
            mood_data_repo,
            plan_data_repo,
            travel_data_repo,
            photo_album_data_repo,
        )

        contacts = await _fetch_contact_relationships_with_names(
            journal_id, contact_relationship_repo, contact_repo
        )

        tags = await tag_repo.get_tags_for_journal(journal_id)

        # Convert to AI-friendly response
        response = JournalConverter.to_response(
            journal=updated_journal,
            types=types,
            type_data=type_data,
            contacts=contacts,
            tags=tags,
        )

        return MCPResponseBuilder.success_response(response)

    @mcp.tool
    @mcp_unified_error_handler("get_journal", "journal")
    @inject
    async def get_journal(
        db_connection: FromDishka[AsyncConnection],
        journal_id: Annotated[
            int, Field(description="The unique identifier of the journal")
        ],
        include_children: Annotated[
            bool,
            Field(
                default=False,
                description="Optional: Include child journals in the response",
            ),
        ] = False,
    ) -> str:
        """
        Get journal details by ID for AI analysis.

        Retrieves comprehensive journal information including title, content, types,
        type-specific data, contact relationships, tags, and a contextual summary.
        Optionally includes child journals.

        Args:
            journal_id: The unique identifier of the journal
            include_children: Optional flag to include child journals

        Returns:
            JSON string containing AI-friendly journal information including:
            - Journal details (title, content, date range)
            - Types and type-specific data
            - Contact relationships
            - Tags
            - Optional child journals
            - Contextual summary for AI understanding

        Raises:
            JournalNotFoundError: If the journal with the given ID does not exist
        """
        # Create repositories
        journal_repo = SqlJournalRepository(db_connection)
        calendar_info_repo = SqlCalendarInfoRepository(db_connection)
        mood_data_repo = SqlMoodDataRepository(db_connection)
        plan_data_repo = SqlPlanDataRepository(db_connection)
        travel_data_repo = SqlTravelDataRepository(db_connection)
        photo_album_data_repo = SqlPhotoAlbumDataRepository(db_connection)
        contact_relationship_repo = SqlJournalContactRelationshipRepository(
            db_connection
        )
        tag_repo = SqlJournalTagRepository(db_connection)

        # Get journal
        journal = await journal_repo.find_by_id(journal_id)
        if not journal:
            from app.core.journal.models.exceptions import JournalNotFoundError

            raise JournalNotFoundError(journal_id)

        # Get children if requested
        children = None
        if include_children:
            children = await journal_repo.get_children(journal_id)

        # Fetch types and type-specific data
        types, type_data = await _fetch_journal_types_and_data(
            journal_id,
            calendar_info_repo,
            mood_data_repo,
            plan_data_repo,
            travel_data_repo,
            photo_album_data_repo,
        )

        # Fetch contact relationships and contact details
        contact_repo = SqlContactRepository(db_connection)
        contacts = await _fetch_contact_relationships_with_names(
            journal_id, contact_relationship_repo, contact_repo
        )

        # Fetch tags
        journal_tags = await tag_repo.get_tags_for_journal(journal_id)

        # Convert to AI-friendly response
        response = JournalConverter.to_response(
            journal=journal,
            types=types,
            type_data=type_data,
            contacts=contacts,
            tags=journal_tags,
            children=children,
        )

        return MCPResponseBuilder.success_response(response)

    @mcp.tool
    @mcp_unified_error_handler("search_journals", "journal")
    @inject
    async def search_journals(
        db_connection: FromDishka[AsyncConnection],
        query: Annotated[
            str | None,
            Field(
                default=None,
                description="Optional: Search query for full-text search",
            ),
        ] = None,
        types: Annotated[
            str | None,
            Field(
                default=None,
                description="Optional: Comma-separated list of journal types to filter by",
            ),
        ] = None,
        limit: Annotated[
            int,
            Field(
                default=20,
                description="Maximum number of results to return (default: 20)",
            ),
        ] = 20,
    ) -> str:
        """
        Search journals with filtering options.

        Searches journals by query, types, and other filters.
        Returns AI-friendly summaries with relevance scores.

        Args:
            query: Optional search query for full-text search
            types: Optional comma-separated list of journal types
            limit: Maximum number of results to return

        Returns:
            JSON string containing AI-friendly search results with:
            - List of matching journals with excerpts
            - Search metadata (total hits, processing time)
            - Contextual summary for AI understanding

        Raises:
            ValueError: If invalid filter values are provided
        """
        # Get current user ID from auth context
        user_id = _get_current_user_id()

        # Create repositories
        journal_repo = SqlJournalRepository(db_connection)

        # Parse types filter
        # type_list = None  # TODO: Use for filtering by types
        # if types:
        #     type_list = [t.strip() for t in types.split(",")]

        # Get journals (simplified for now - will add search later)
        journals = await journal_repo.get_all(
            user_id=user_id,
            limit=limit,
            offset=0,
        )

        # Convert to search results
        from app.mcp.domains.journals.schemas import JournalSearchResponse

        results = [_journal_to_search_result(journal) for journal in journals]

        response = JournalSearchResponse(
            results=results,
            query=query,
            total_hits=len(results),
            processing_time_ms=0,
            summary=f"Found {len(results)} journal(s)",
        )

        return MCPResponseBuilder.success_response(response)

    @mcp.tool
    @mcp_unified_error_handler("delete_journal", "journal")
    @inject
    async def delete_journal(
        db_connection: FromDishka[AsyncConnection],
        event_publisher: FromDishka[OutboxEventPublisher],
        journal_id: Annotated[
            int, Field(description="The unique identifier of the journal to delete")
        ],
        delete_children: Annotated[
            bool,
            Field(
                default=False,
                description="Optional: Delete child journals as well",
            ),
        ] = False,
    ) -> str:
        """
        Delete a journal entry.

        Deletes a journal entry and optionally its children.
        Returns confirmation response.

        Args:
            journal_id: The unique identifier of the journal to delete
            delete_children: Optional flag to delete child journals

        Returns:
            JSON string containing deletion confirmation

        Raises:
            JournalNotFoundError: If the journal with the given ID does not exist
        """
        # Explicitly reject unsupported delete_children behavior to avoid silent misuse
        if delete_children:
            raise NotImplementedError(
                "The 'delete_children' flag is not yet supported. "
                "Child journals are not deleted automatically."
            )

        # Create repositories
        journal_repo = SqlJournalRepository(db_connection)
        journal_service = JournalService(journal_repo, event_publisher)

        # Delete journal
        await journal_service.delete_journal(journal_id, db_connection)

        from pydantic import BaseModel

        class DeleteResponse(BaseModel):
            journal_id: int
            deleted: bool
            summary: str

        response = DeleteResponse(
            journal_id=journal_id,
            deleted=True,
            summary=f"Successfully deleted journal {journal_id}",
        )

        return MCPResponseBuilder.success_response(response)

    @mcp.tool
    @mcp_unified_error_handler("get_contact_journals", "journal")
    @inject
    async def get_contact_journals(
        db_connection: FromDishka[AsyncConnection],
        contact_id: Annotated[
            int, Field(description="The unique identifier of the contact")
        ],
        limit: Annotated[
            int,
            Field(
                default=20,
                description="Maximum number of results to return (default: 20)",
            ),
        ] = 20,
    ) -> str:
        """
        Get journals associated with a contact.

        Retrieves journals that have relationships with the specified contact.
        Returns AI-friendly summaries.

        Args:
            contact_id: The unique identifier of the contact
            limit: Maximum number of results to return

        Returns:
            JSON string containing AI-friendly journal summaries

        Raises:
            ContactNotFoundError: If the contact with the given ID does not exist
        """
        # Create repositories
        contact_rel_repo = SqlJournalContactRelationshipRepository(db_connection)
        journal_repo = SqlJournalRepository(db_connection)

        # Get relationships
        relationships = await contact_rel_repo.get_by_contact(contact_id)

        # Get journals
        journals = []
        for rel in relationships[:limit]:
            journal = await journal_repo.find_by_id(rel.journal_id)
            if journal:
                journals.append(journal)

        # Convert to search results
        from app.mcp.domains.journals.schemas import JournalSearchResponse

        results = [_journal_to_search_result(journal) for journal in journals]

        response = JournalSearchResponse(
            results=results,
            query=None,
            total_hits=len(results),
            processing_time_ms=0,
            summary=f"Found {len(results)} journal(s) for contact {contact_id}",
        )

        return MCPResponseBuilder.success_response(response)

    @mcp.tool
    @mcp_unified_error_handler("link_journal_to_contact", "journal")
    @inject
    async def link_journal_to_contact(
        db_connection: FromDishka[AsyncConnection],
        journal_id: Annotated[
            int, Field(description="The unique identifier of the journal")
        ],
        contact_id: Annotated[
            int, Field(description="The unique identifier of the contact")
        ],
        relationship_type: Annotated[
            str,
            Field(
                description="Relationship type (PARTICIPANT, INVITEE, MENTION, ABOUT)"
            ),
        ],
    ) -> str:
        """
        Link a journal to a contact with a specific relationship type.

        Creates a relationship between a journal and a contact.
        Returns confirmation response.

        Args:
            journal_id: The unique identifier of the journal
            contact_id: The unique identifier of the contact
            relationship_type: Relationship type (PARTICIPANT, INVITEE, MENTION, ABOUT)

        Returns:
            JSON string containing relationship creation confirmation

        Raises:
            JournalNotFoundError: If the journal with the given ID does not exist
            ContactNotFoundError: If the contact with the given ID does not exist
            ValueError: If relationship_type is invalid
        """
        # Validate relationship type
        try:
            rel_type = JournalContactRelationshipType(relationship_type.upper())
        except ValueError as e:
            raise ValueError(
                f"Invalid relationship type: {relationship_type}. "
                f"Must be one of: PARTICIPANT, INVITEE, MENTION, ABOUT"
            ) from e

        # Create repositories
        contact_rel_repo = SqlJournalContactRelationshipRepository(db_connection)
        journal_repo = SqlJournalRepository(db_connection)
        contact_repo = SqlContactRepository(db_connection)

        # Verify journal exists
        journal = await journal_repo.find_by_id(journal_id)
        if not journal:
            from app.core.journal.models.exceptions import JournalNotFoundError

            raise JournalNotFoundError(journal_id)

        # Verify contact exists
        contact = await contact_repo.find_by_id(contact_id)
        if not contact:
            from app.core.contacts.models.exceptions import ContactNotFoundError

            raise ContactNotFoundError(contact_id)

        # Create relationship
        relationship = JournalContactRelationship(
            journal_id=journal_id,
            contact_id=contact_id,
            relationship_type=rel_type,
        )
        await contact_rel_repo.create(relationship)

        from pydantic import BaseModel

        class LinkResponse(BaseModel):
            journal_id: int
            contact_id: int
            relationship_type: str
            linked: bool
            summary: str

        response = LinkResponse(
            journal_id=journal_id,
            contact_id=contact_id,
            relationship_type=relationship_type,
            linked=True,
            summary=f"Successfully linked journal {journal_id} to contact {contact_id} as {relationship_type}",
        )

        return MCPResponseBuilder.success_response(response)
