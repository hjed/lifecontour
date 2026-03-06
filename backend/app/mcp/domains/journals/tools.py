"""
Journal domain MCP tools.

Provides AI access to journal management functionality through MCP tools.
Each tool is designed to return AI-friendly, contextual information.
"""

import dataclasses
import json
from typing import Annotated, Any
from uuid import UUID

import structlog
from dishka.integrations.starlette import FromDishka, inject
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_request
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_repository import SqlContactRepository
from app.core.journal.adapters.sql.abseiling_data_repository import (
    SqlAbseilingDataRepository,
)
from app.core.journal.adapters.sql.bushwalking_data_repository import (
    SqlBushwalkingDataRepository,
)
from app.core.journal.adapters.sql.calendar_info_repository import (
    SqlCalendarInfoRepository,
)
from app.core.journal.adapters.sql.canyoning_data_repository import (
    SqlCanyoningDataRepository,
)
from app.core.journal.adapters.sql.climbing_data_repository import (
    SqlClimbingDataRepository,
)
from app.core.journal.adapters.sql.fitness_data_repository import (
    SqlFitnessDataRepository,
)
from app.core.journal.adapters.sql.jogging_data_repository import (
    SqlJoggingDataRepository,
)
from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.journal_tag_repository import SqlJournalTagRepository
from app.core.journal.adapters.sql.mood_data_repository import SqlMoodDataRepository
from app.core.journal.adapters.sql.outdoor_activity_data_repository import (
    SqlOutdoorActivityDataRepository,
)
from app.core.journal.adapters.sql.photo_album_data_repository import (
    SqlPhotoAlbumDataRepository,
)
from app.core.journal.adapters.sql.plan_data_repository import SqlPlanDataRepository
from app.core.journal.adapters.sql.travel_data_repository import SqlTravelDataRepository
from app.core.journal.models.abseiling_data import AbseilingData
from app.core.journal.models.bushwalking_data import BushwalkingData
from app.core.journal.models.calendar_info import CalendarInfo
from app.core.journal.models.canyoning_data import CanyoningData
from app.core.journal.models.climbing_data import ClimbingData
from app.core.journal.models.entities import Journal
from app.core.journal.models.exceptions import JournalValidationError
from app.core.journal.models.fitness_data import FitnessData
from app.core.journal.models.jogging_data import JoggingData
from app.core.journal.models.journal_contact_relationship import (
    JournalContactRelationship,
)
from app.core.journal.models.journal_relationship_types import (
    JournalContactRelationshipType,
)
from app.core.journal.models.journal_tag import JournalTag
from app.core.journal.models.journal_types import JournalType
from app.core.journal.models.mood_data import MoodData
from app.core.journal.models.outdoor_activity_data import OutdoorActivityData
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


def _build_fitness_data(fitness_data: Any) -> dict[str, Any]:
    """Build fitness data dictionary."""
    return {
        "heart_rate_avg": fitness_data.heart_rate_avg,
        "heart_rate_max": fitness_data.heart_rate_max,
        "distance": fitness_data.distance,
        "elevation_gain": fitness_data.elevation_gain,
        "elevation_loss": fitness_data.elevation_loss,
        "duration": fitness_data.duration,
        "calories": fitness_data.calories,
        "gpx_track_data": fitness_data.gpx_track_data,
        "strava_activity_id": fitness_data.strava_activity_id,
    }


def _build_outdoor_activity_data(outdoor_activity_data: Any) -> dict[str, Any]:
    """Build outdoor activity data dictionary."""
    return {
        "activity_type": outdoor_activity_data.activity_type,
        "weather_conditions": outdoor_activity_data.weather_conditions,
        "role": outdoor_activity_data.role,
        "in_leadership_role": outdoor_activity_data.in_leadership_role,
        "participant_notes": outdoor_activity_data.participant_notes,
    }


def _build_bushwalking_data(bushwalking_data: Any) -> dict[str, Any]:
    """Build bushwalking data dictionary."""
    return {
        "route_id": str(bushwalking_data.route_id)
        if bushwalking_data.route_id
        else None,
        "track_grading": bushwalking_data.track_grading,
    }


def _build_jogging_data(jogging_data: Any) -> dict[str, Any]:
    """Build jogging data dictionary."""
    return {
        "route_id": str(jogging_data.route_id) if jogging_data.route_id else None,
        "pace": jogging_data.pace,
    }


def _build_abseiling_data(abseiling_data: Any) -> dict[str, Any]:
    """Build abseiling data dictionary."""
    return {
        "number_of_abseils": abseiling_data.number_of_abseils,
        "total_length": abseiling_data.total_length,
    }


def _build_canyoning_data(canyoning_data: Any) -> dict[str, Any]:
    """Build canyoning data dictionary."""
    return {
        "route_id": str(canyoning_data.route_id) if canyoning_data.route_id else None,
        "french_grade": canyoning_data.french_grade,
        "water_guage_name": canyoning_data.water_guage_name,
        "water_guage_level": canyoning_data.water_guage_level,
        "is_vertical": canyoning_data.is_vertical,
        "is_night_canyon": canyoning_data.is_night_canyon,
        "is_white_water": canyoning_data.is_white_water,
    }


def _build_climbing_data(climbing_data: Any) -> dict[str, Any]:
    """Build climbing data dictionary."""
    return {
        "route_id": str(climbing_data.route_id) if climbing_data.route_id else None,
        "climbing_type": climbing_data.climbing_type,
        "grade": climbing_data.grade,
        "length": climbing_data.length,
    }


async def _fetch_journal_types_and_data(
    journal_id: int,
    calendar_info_repo: SqlCalendarInfoRepository,
    mood_data_repo: SqlMoodDataRepository,
    plan_data_repo: SqlPlanDataRepository,
    travel_data_repo: SqlTravelDataRepository,
    photo_album_data_repo: SqlPhotoAlbumDataRepository,
    fitness_data_repo: SqlFitnessDataRepository,
    outdoor_activity_data_repo: SqlOutdoorActivityDataRepository,
    bushwalking_data_repo: SqlBushwalkingDataRepository,
    jogging_data_repo: SqlJoggingDataRepository,
    abseiling_data_repo: SqlAbseilingDataRepository,
    canyoning_data_repo: SqlCanyoningDataRepository,
    climbing_data_repo: SqlClimbingDataRepository,
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
        fitness_data_repo: Fitness data repository
        outdoor_activity_data_repo: Outdoor activity data repository
        bushwalking_data_repo: Bushwalking data repository
        jogging_data_repo: Jogging data repository
        abseiling_data_repo: Abseiling data repository
        canyoning_data_repo: Canyoning data repository
        climbing_data_repo: Climbing data repository

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

    fitness_data = await fitness_data_repo.find_by_journal_id(journal_id)
    if fitness_data:
        types.append(JournalType.FITNESS.value)
        type_data[JournalType.FITNESS.value] = _build_fitness_data(fitness_data)

    outdoor_activity_data = await outdoor_activity_data_repo.find_by_journal_id(
        journal_id
    )
    if outdoor_activity_data:
        types.append(JournalType.OUTDOOR_ACTIVITY.value)
        type_data[JournalType.OUTDOOR_ACTIVITY.value] = _build_outdoor_activity_data(
            outdoor_activity_data
        )

    bushwalking_data = await bushwalking_data_repo.find_by_journal_id(journal_id)
    if bushwalking_data:
        types.append(JournalType.BUSHWALKING.value)
        type_data[JournalType.BUSHWALKING.value] = _build_bushwalking_data(
            bushwalking_data
        )

    jogging_data = await jogging_data_repo.find_by_journal_id(journal_id)
    if jogging_data:
        types.append(JournalType.JOGGING.value)
        type_data[JournalType.JOGGING.value] = _build_jogging_data(jogging_data)

    abseiling_data = await abseiling_data_repo.find_by_journal_id(journal_id)
    if abseiling_data:
        types.append(JournalType.ABSEILING_TRIP.value)
        type_data[JournalType.ABSEILING_TRIP.value] = _build_abseiling_data(
            abseiling_data
        )

    canyoning_data = await canyoning_data_repo.find_by_journal_id(journal_id)
    if canyoning_data:
        types.append(JournalType.CANYONING.value)
        type_data[JournalType.CANYONING.value] = _build_canyoning_data(canyoning_data)

    climbing_data = await climbing_data_repo.find_by_journal_id(journal_id)
    if climbing_data:
        types.append(JournalType.CLIMBING.value)
        type_data[JournalType.CLIMBING.value] = _build_climbing_data(climbing_data)

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
    fitness_data_repo: SqlFitnessDataRepository,
    outdoor_activity_data_repo: SqlOutdoorActivityDataRepository,
    bushwalking_data_repo: SqlBushwalkingDataRepository,
    jogging_data_repo: SqlJoggingDataRepository,
    abseiling_data_repo: SqlAbseilingDataRepository,
    canyoning_data_repo: SqlCanyoningDataRepository,
    climbing_data_repo: SqlClimbingDataRepository,
) -> None:
    """
    Create type-specific data row with default values for the given journal type.

    Args:
        journal_type: The type of journal
        journal_id: The ID of the journal
        mood_data_repo: Repository for mood data
        plan_data_repo: Repository for plan data
        travel_data_repo: Repository for travel data
        fitness_data_repo: Repository for fitness data
        outdoor_activity_data_repo: Repository for outdoor activity data
        bushwalking_data_repo: Repository for bushwalking data
        jogging_data_repo: Repository for jogging data
        abseiling_data_repo: Repository for abseiling data
        canyoning_data_repo: Repository for canyoning data
        climbing_data_repo: Repository for climbing data
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
    elif journal_type == JournalType.FITNESS:
        fitness_data = FitnessData(journal_id=journal_id)
        await fitness_data_repo.save(fitness_data)
    elif journal_type == JournalType.OUTDOOR_ACTIVITY:
        outdoor_activity_data = OutdoorActivityData(journal_id=journal_id)
        await outdoor_activity_data_repo.save(outdoor_activity_data)
    elif journal_type == JournalType.BUSHWALKING:
        bushwalking_data = BushwalkingData(journal_id=journal_id)
        await bushwalking_data_repo.save(bushwalking_data)
    elif journal_type == JournalType.JOGGING:
        jogging_data = JoggingData(journal_id=journal_id)
        await jogging_data_repo.save(jogging_data)
    elif journal_type == JournalType.ABSEILING_TRIP:
        abseiling_data = AbseilingData(journal_id=journal_id)
        await abseiling_data_repo.save(abseiling_data)
    elif journal_type == JournalType.CANYONING:
        canyoning_data = CanyoningData(journal_id=journal_id)
        await canyoning_data_repo.save(canyoning_data)
    elif journal_type == JournalType.CLIMBING:
        climbing_data = ClimbingData(journal_id=journal_id)
        await climbing_data_repo.save(climbing_data)
    # EVENT and PHOTO_ALBUM types require additional data (calendar_id, immich_album_id)
    # These will be created when the user provides type_data


async def _update_event_data(
    journal_id: int,
    type_data_dict: dict[str, Any],
    calendar_info_repo: SqlCalendarInfoRepository,
) -> None:
    calendar_id = type_data_dict.get("calendar_id")
    if calendar_id is not None:
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


async def _update_mood_data(
    journal_id: int,
    type_data_dict: dict[str, Any],
    mood_data_repo: SqlMoodDataRepository,
) -> None:
    existing_mood = await mood_data_repo.find_by_journal_id(journal_id)
    if existing_mood:
        if "mood_value" in type_data_dict:
            existing_mood.mood_value = type_data_dict["mood_value"]
        if "mood_label" in type_data_dict:
            existing_mood.mood_label = type_data_dict["mood_label"]
        if "energy_level" in type_data_dict:
            existing_mood.energy_level = type_data_dict["energy_level"]
        await mood_data_repo.save(existing_mood)


async def _update_photo_album_data(
    journal_id: int,
    type_data_dict: dict[str, Any],
    photo_album_data_repo: SqlPhotoAlbumDataRepository,
) -> None:
    immich_album_id = type_data_dict.get("immich_album_id")
    if immich_album_id is not None:
        photo_album_data = PhotoAlbumData(
            journal_id=journal_id,
            immich_album_id=str(immich_album_id),
        )
        await photo_album_data_repo.save(photo_album_data)


async def _update_fitness_data(
    journal_id: int,
    type_data_dict: dict[str, Any],
    fitness_data_repo: SqlFitnessDataRepository,
) -> None:
    existing_fitness = await fitness_data_repo.find_by_journal_id(journal_id)
    if existing_fitness:
        for field in [
            "heart_rate_avg",
            "heart_rate_max",
            "distance",
            "elevation_gain",
            "elevation_loss",
            "duration",
            "calories",
            "gpx_track_data",
            "strava_activity_id",
        ]:
            if field in type_data_dict:
                setattr(existing_fitness, field, type_data_dict[field])
        await fitness_data_repo.save(existing_fitness)


async def _update_outdoor_activity_data(
    journal_id: int,
    type_data_dict: dict[str, Any],
    outdoor_activity_data_repo: SqlOutdoorActivityDataRepository,
) -> None:
    existing_outdoor = await outdoor_activity_data_repo.find_by_journal_id(journal_id)
    if existing_outdoor:
        updates: dict[str, Any] = {}
        for field in [
            "activity_type",
            "weather_conditions",
            "role",
            "in_leadership_role",
            "participant_notes",
        ]:
            if field in type_data_dict:
                updates[field] = type_data_dict[field]
        validated_outdoor = dataclasses.replace(existing_outdoor, **updates)
        await outdoor_activity_data_repo.save(validated_outdoor)


def _parse_route_id(type_data_dict: dict[str, Any], updates: dict[str, Any]) -> None:
    if "route_id" in type_data_dict:
        route_id_val = type_data_dict["route_id"]
        try:
            updates["route_id"] = (
                UUID(route_id_val) if isinstance(route_id_val, str) else route_id_val
            )
        except ValueError as e:
            raise JournalValidationError(
                "route_id", f"Invalid UUID format: {route_id_val}"
            ) from e


async def _update_bushwalking_data(
    journal_id: int,
    type_data_dict: dict[str, Any],
    bushwalking_data_repo: SqlBushwalkingDataRepository,
) -> None:
    existing_bushwalking = await bushwalking_data_repo.find_by_journal_id(journal_id)
    if existing_bushwalking:
        bw_updates: dict[str, Any] = {}
        if "track_grading" in type_data_dict:
            bw_updates["track_grading"] = type_data_dict["track_grading"]
        _parse_route_id(type_data_dict, bw_updates)
        validated_bushwalking = dataclasses.replace(existing_bushwalking, **bw_updates)
        await bushwalking_data_repo.save(validated_bushwalking)


async def _update_jogging_data(
    journal_id: int,
    type_data_dict: dict[str, Any],
    jogging_data_repo: SqlJoggingDataRepository,
) -> None:
    existing_jogging = await jogging_data_repo.find_by_journal_id(journal_id)
    if existing_jogging:
        jog_updates: dict[str, Any] = {}
        if "pace" in type_data_dict:
            jog_updates["pace"] = type_data_dict["pace"]
        _parse_route_id(type_data_dict, jog_updates)
        validated_jogging = dataclasses.replace(existing_jogging, **jog_updates)
        await jogging_data_repo.save(validated_jogging)


async def _update_abseiling_data(
    journal_id: int,
    type_data_dict: dict[str, Any],
    abseiling_data_repo: SqlAbseilingDataRepository,
) -> None:
    existing_abseiling = await abseiling_data_repo.find_by_journal_id(journal_id)
    if existing_abseiling:
        abs_updates: dict[str, Any] = {}
        if "number_of_abseils" in type_data_dict:
            abs_updates["number_of_abseils"] = type_data_dict["number_of_abseils"]
        if "total_length" in type_data_dict:
            abs_updates["total_length"] = type_data_dict["total_length"]
        validated_abseiling = dataclasses.replace(existing_abseiling, **abs_updates)
        await abseiling_data_repo.save(validated_abseiling)


async def _update_canyoning_data(
    journal_id: int,
    type_data_dict: dict[str, Any],
    canyoning_data_repo: SqlCanyoningDataRepository,
) -> None:
    existing_canyoning = await canyoning_data_repo.find_by_journal_id(journal_id)
    if existing_canyoning:
        can_updates: dict[str, Any] = {}
        _parse_route_id(type_data_dict, can_updates)
        for field in [
            "french_grade",
            "water_guage_name",
            "water_guage_level",
            "is_vertical",
            "is_night_canyon",
            "is_white_water",
        ]:
            if field in type_data_dict:
                can_updates[field] = type_data_dict[field]
        validated_canyoning = dataclasses.replace(existing_canyoning, **can_updates)
        await canyoning_data_repo.save(validated_canyoning)


async def _update_climbing_data(
    journal_id: int,
    type_data_dict: dict[str, Any],
    climbing_data_repo: SqlClimbingDataRepository,
) -> None:
    existing_climbing = await climbing_data_repo.find_by_journal_id(journal_id)
    if existing_climbing:
        clb_updates: dict[str, Any] = {}
        _parse_route_id(type_data_dict, clb_updates)
        for field in ["climbing_type", "grade", "length"]:
            if field in type_data_dict:
                clb_updates[field] = type_data_dict[field]
        validated_climbing = dataclasses.replace(existing_climbing, **clb_updates)
        await climbing_data_repo.save(validated_climbing)


async def _update_type_specific_data(
    journal_type: JournalType,
    journal_id: int,
    type_data_dict: dict[str, Any],
    calendar_info_repo: SqlCalendarInfoRepository,
    mood_data_repo: SqlMoodDataRepository,
    photo_album_data_repo: SqlPhotoAlbumDataRepository,
    fitness_data_repo: SqlFitnessDataRepository,
    outdoor_activity_data_repo: SqlOutdoorActivityDataRepository,
    bushwalking_data_repo: SqlBushwalkingDataRepository,
    jogging_data_repo: SqlJoggingDataRepository,
    abseiling_data_repo: SqlAbseilingDataRepository,
    canyoning_data_repo: SqlCanyoningDataRepository,
    climbing_data_repo: SqlClimbingDataRepository,
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
        fitness_data_repo: Repository for fitness data
        outdoor_activity_data_repo: Repository for outdoor activity data
        bushwalking_data_repo: Repository for bushwalking data
        jogging_data_repo: Repository for jogging data
        abseiling_data_repo: Repository for abseiling data
        canyoning_data_repo: Repository for canyoning data
        climbing_data_repo: Repository for climbing data
    """
    if not type_data_dict:
        return

    if journal_type == JournalType.EVENT:
        await _update_event_data(journal_id, type_data_dict, calendar_info_repo)
    elif journal_type == JournalType.MOOD_RATING:
        await _update_mood_data(journal_id, type_data_dict, mood_data_repo)
    elif journal_type == JournalType.PHOTO_ALBUM:
        await _update_photo_album_data(
            journal_id, type_data_dict, photo_album_data_repo
        )
    elif journal_type == JournalType.FITNESS:
        await _update_fitness_data(journal_id, type_data_dict, fitness_data_repo)
    elif journal_type == JournalType.OUTDOOR_ACTIVITY:
        await _update_outdoor_activity_data(
            journal_id, type_data_dict, outdoor_activity_data_repo
        )
    elif journal_type == JournalType.BUSHWALKING:
        await _update_bushwalking_data(
            journal_id, type_data_dict, bushwalking_data_repo
        )
    elif journal_type == JournalType.JOGGING:
        await _update_jogging_data(journal_id, type_data_dict, jogging_data_repo)
    elif journal_type == JournalType.ABSEILING_TRIP:
        await _update_abseiling_data(journal_id, type_data_dict, abseiling_data_repo)
    elif journal_type == JournalType.CANYONING:
        await _update_canyoning_data(journal_id, type_data_dict, canyoning_data_repo)
    elif journal_type == JournalType.CLIMBING:
        await _update_climbing_data(journal_id, type_data_dict, climbing_data_repo)


async def _persist_contact_relationships(
    journal_id: int,
    contact_relationships: list[dict[str, Any]],
    contact_relationship_repo: SqlJournalContactRelationshipRepository,
) -> None:
    """
    Create contact relationships for a journal.

    Args:
        journal_id: The ID of the journal
        contact_relationships: List of relationship dictionaries with contact_id and relationship_type
        contact_relationship_repo: Repository for contact relationships
    """
    for rel_dict in contact_relationships:
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


async def _persist_tags(
    journal_id: int,
    tags: list[str],
    tag_repo: SqlJournalTagRepository,
) -> None:
    """
    Find or create tags and assign them to a journal.

    Args:
        journal_id: The ID of the journal
        tags: List of tag names
        tag_repo: Repository for tags
    """
    from uuid import uuid4

    for tag_name in tags:
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


async def _fetch_enrichment_data(
    journal_id: int,
    calendar_info_repo: SqlCalendarInfoRepository,
    mood_data_repo: SqlMoodDataRepository,
    plan_data_repo: SqlPlanDataRepository,
    travel_data_repo: SqlTravelDataRepository,
    photo_album_data_repo: SqlPhotoAlbumDataRepository,
    fitness_data_repo: SqlFitnessDataRepository,
    outdoor_activity_data_repo: SqlOutdoorActivityDataRepository,
    bushwalking_data_repo: SqlBushwalkingDataRepository,
    jogging_data_repo: SqlJoggingDataRepository,
    abseiling_data_repo: SqlAbseilingDataRepository,
    canyoning_data_repo: SqlCanyoningDataRepository,
    climbing_data_repo: SqlClimbingDataRepository,
    contact_relationship_repo: SqlJournalContactRelationshipRepository,
    contact_repo: SqlContactRepository,
    tag_repo: SqlJournalTagRepository,
) -> tuple[list[str], dict[str, Any], list[tuple[int, str, str]], list[JournalTag]]:
    """
    Fetch all enrichment data for a journal (types, type_data, contacts, tags).

    Args:
        journal_id: The ID of the journal
        calendar_info_repo: Repository for calendar info
        mood_data_repo: Repository for mood data
        plan_data_repo: Repository for plan data
        travel_data_repo: Repository for travel data
        photo_album_data_repo: Repository for photo album data
        fitness_data_repo: Repository for fitness data
        outdoor_activity_data_repo: Repository for outdoor activity data
        bushwalking_data_repo: Repository for bushwalking data
        jogging_data_repo: Repository for jogging data
        abseiling_data_repo: Repository for abseiling data
        canyoning_data_repo: Repository for canyoning data
        climbing_data_repo: Repository for climbing data
        contact_relationship_repo: Repository for contact relationships
        contact_repo: Repository for contacts
        tag_repo: Repository for tags

    Returns:
        Tuple of (types, type_data, contacts, tags)
    """
    types, type_data = await _fetch_journal_types_and_data(
        journal_id,
        calendar_info_repo,
        mood_data_repo,
        plan_data_repo,
        travel_data_repo,
        photo_album_data_repo,
        fitness_data_repo,
        outdoor_activity_data_repo,
        bushwalking_data_repo,
        jogging_data_repo,
        abseiling_data_repo,
        canyoning_data_repo,
        climbing_data_repo,
    )

    contacts = await _fetch_contact_relationships_with_names(
        journal_id, contact_relationship_repo, contact_repo
    )

    tags = await tag_repo.get_tags_for_journal(journal_id)

    return types, type_data, contacts, tags


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
        fitness_data_repo: FromDishka[SqlFitnessDataRepository],
        outdoor_activity_data_repo: FromDishka[SqlOutdoorActivityDataRepository],
        bushwalking_data_repo: FromDishka[SqlBushwalkingDataRepository],
        jogging_data_repo: FromDishka[SqlJoggingDataRepository],
        abseiling_data_repo: FromDishka[SqlAbseilingDataRepository],
        canyoning_data_repo: FromDishka[SqlCanyoningDataRepository],
        climbing_data_repo: FromDishka[SqlClimbingDataRepository],
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

                    # Capture the return value: includes all types added (requested +
                    # auto-resolved dependencies like FITNESS for OUTDOOR_ACTIVITY).
                    added_types = await journal_service.add_type_to_journal(
                        journal_id, journal_type, db_connection
                    )

                    # Create type-specific data rows for ALL added types (including
                    # dependency types like FITNESS). Mirrors REST controller behaviour.
                    for added_type in added_types:
                        await _create_type_specific_data(
                            added_type,
                            journal_id,
                            mood_data_repo,
                            plan_data_repo,
                            travel_data_repo,
                            fitness_data_repo,
                            outdoor_activity_data_repo,
                            bushwalking_data_repo,
                            jogging_data_repo,
                            abseiling_data_repo,
                            canyoning_data_repo,
                            climbing_data_repo,
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
                            fitness_data_repo,
                            outdoor_activity_data_repo,
                            bushwalking_data_repo,
                            jogging_data_repo,
                            abseiling_data_repo,
                            canyoning_data_repo,
                            climbing_data_repo,
                        )
                except (ValueError, KeyError):
                    # Invalid type, skip
                    pass

        # Add contact relationships if provided
        if request.contact_relationships:
            await _persist_contact_relationships(
                journal_id, request.contact_relationships, contact_relationship_repo
            )

        # Add tags if provided
        if request.tags:
            await _persist_tags(journal_id, request.tags, tag_repo)

        # Fetch all enrichment data
        types, type_data, contacts, tags = await _fetch_enrichment_data(
            journal_id,
            calendar_info_repo,
            mood_data_repo,
            plan_data_repo,
            travel_data_repo,
            photo_album_data_repo,
            fitness_data_repo,
            outdoor_activity_data_repo,
            bushwalking_data_repo,
            jogging_data_repo,
            abseiling_data_repo,
            canyoning_data_repo,
            climbing_data_repo,
            contact_relationship_repo,
            contact_repo,
            tag_repo,
        )

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
        fitness_data_repo: FromDishka[SqlFitnessDataRepository],
        outdoor_activity_data_repo: FromDishka[SqlOutdoorActivityDataRepository],
        bushwalking_data_repo: FromDishka[SqlBushwalkingDataRepository],
        jogging_data_repo: FromDishka[SqlJoggingDataRepository],
        abseiling_data_repo: FromDishka[SqlAbseilingDataRepository],
        canyoning_data_repo: FromDishka[SqlCanyoningDataRepository],
        climbing_data_repo: FromDishka[SqlClimbingDataRepository],
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
                fitness_data_repo,
                outdoor_activity_data_repo,
                bushwalking_data_repo,
                jogging_data_repo,
                abseiling_data_repo,
                canyoning_data_repo,
                climbing_data_repo,
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
                        # Capture the return value: includes all types added (requested +
                        # auto-resolved dependencies like FITNESS for OUTDOOR_ACTIVITY).
                        added_types = await journal_service.add_type_to_journal(
                            journal_id, journal_type, db_connection
                        )

                        # Create type-specific data rows for ALL added types (including
                        # dependency types like FITNESS). Mirrors REST controller behaviour.
                        for added_type in added_types:
                            await _create_type_specific_data(
                                added_type,
                                journal_id,
                                mood_data_repo,
                                plan_data_repo,
                                travel_data_repo,
                                fitness_data_repo,
                                outdoor_activity_data_repo,
                                bushwalking_data_repo,
                                jogging_data_repo,
                                abseiling_data_repo,
                                canyoning_data_repo,
                                climbing_data_repo,
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
                            fitness_data_repo,
                            outdoor_activity_data_repo,
                            bushwalking_data_repo,
                            jogging_data_repo,
                            abseiling_data_repo,
                            canyoning_data_repo,
                            climbing_data_repo,
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
                        fitness_data_repo,
                        outdoor_activity_data_repo,
                        bushwalking_data_repo,
                        jogging_data_repo,
                        abseiling_data_repo,
                        canyoning_data_repo,
                        climbing_data_repo,
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
            await _persist_contact_relationships(
                journal_id, request.contact_relationships, contact_relationship_repo
            )

        # Update tags if provided (replace all tags)
        if request.tags is not None:
            # Remove all existing tags
            existing_tags = await tag_repo.get_tags_for_journal(journal_id)
            for existing_tag in existing_tags:
                if existing_tag.id is not None:
                    await tag_repo.remove_tag(journal_id, existing_tag.id)

            # Add new tags
            await _persist_tags(journal_id, request.tags, tag_repo)

        # Fetch all enrichment data
        types, type_data, contacts, tags = await _fetch_enrichment_data(
            journal_id,
            calendar_info_repo,
            mood_data_repo,
            plan_data_repo,
            travel_data_repo,
            photo_album_data_repo,
            fitness_data_repo,
            outdoor_activity_data_repo,
            bushwalking_data_repo,
            jogging_data_repo,
            abseiling_data_repo,
            canyoning_data_repo,
            climbing_data_repo,
            contact_relationship_repo,
            contact_repo,
            tag_repo,
        )

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
        fitness_data_repo = SqlFitnessDataRepository(db_connection)
        outdoor_activity_data_repo = SqlOutdoorActivityDataRepository(db_connection)
        bushwalking_data_repo = SqlBushwalkingDataRepository(db_connection)
        jogging_data_repo = SqlJoggingDataRepository(db_connection)
        abseiling_data_repo = SqlAbseilingDataRepository(db_connection)
        canyoning_data_repo = SqlCanyoningDataRepository(db_connection)
        climbing_data_repo = SqlClimbingDataRepository(db_connection)
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
            fitness_data_repo,
            outdoor_activity_data_repo,
            bushwalking_data_repo,
            jogging_data_repo,
            abseiling_data_repo,
            canyoning_data_repo,
            climbing_data_repo,
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

    @mcp.tool
    @mcp_unified_error_handler("list_calendars", "journal")
    @inject
    async def list_calendars(
        db_connection: FromDishka[AsyncConnection],
    ) -> str:
        """
        List all calendars available for EVENT journals.
        """
        from app.core.journal.adapters.sql.calendar_repository import (
            SqlCalendarRepository,
        )

        user_id = _get_current_user_id()
        calendar_repo = SqlCalendarRepository(db_connection)

        calendars = await calendar_repo.get_all(user_id=user_id)

        from pydantic import BaseModel

        class CalendarListItem(BaseModel):
            id: str
            name: str
            description: str | None
            color: str | None

        class CalendarListResponse(BaseModel):
            calendars: list[CalendarListItem]

        response = CalendarListResponse(
            calendars=[
                CalendarListItem(
                    id=str(c.id),
                    name=c.name,
                    description=c.description,
                    color=c.color,
                )
                for c in calendars
            ]
        )

        return MCPResponseBuilder.success_response(response)

    @mcp.tool
    @mcp_unified_error_handler("create_calendar", "journal")
    @inject
    async def create_calendar(
        db_connection: FromDishka[AsyncConnection],
        name: Annotated[str, Field(description="Calendar name")],
        description: Annotated[
            str | None, Field(description="Calendar description", default=None)
        ] = None,
        color: Annotated[
            str | None, Field(description="Calendar color hex code", default=None)
        ] = None,
    ) -> str:
        """
        Create a new calendar to be used with EVENT journals.
        """
        from app.core.journal.adapters.sql.calendar_repository import (
            SqlCalendarRepository,
        )
        from app.core.journal.models.calendar import Calendar

        user_id = _get_current_user_id()
        calendar_repo = SqlCalendarRepository(db_connection)

        new_calendar = Calendar(
            user_id=user_id,
            name=name,
            description=description,
            color=color or "#3B82F6",
            is_synced_to_google=False,
            google_calendar_id=None,
        )

        saved_calendar = await calendar_repo.save(new_calendar)

        from pydantic import BaseModel

        class CalendarResponse(BaseModel):
            id: str
            name: str
            summary: str

        return MCPResponseBuilder.success_response(
            CalendarResponse(
                id=str(saved_calendar.id),
                name=saved_calendar.name,
                summary=f"Created calendar '{saved_calendar.name}'",
            )
        )

    @mcp.tool
    @mcp_unified_error_handler("update_calendar", "journal")
    @inject
    async def update_calendar(
        db_connection: FromDishka[AsyncConnection],
        calendar_id: Annotated[str, Field(description="Calendar UUID")],
        name: Annotated[
            str | None, Field(description="Calendar name", default=None)
        ] = None,
        description: Annotated[
            str | None, Field(description="Calendar description", default=None)
        ] = None,
        color: Annotated[
            str | None, Field(description="Calendar color hex code", default=None)
        ] = None,
    ) -> str:
        """
        Update an existing calendar.
        """
        import uuid

        from app.core.journal.adapters.sql.calendar_repository import (
            SqlCalendarRepository,
        )

        user_id = _get_current_user_id()
        calendar_repo = SqlCalendarRepository(db_connection)

        calendar = await calendar_repo.find_by_id(uuid.UUID(calendar_id))
        if not calendar or calendar.user_id != user_id:
            return MCPResponseBuilder.not_found_error_response("Calendar", calendar_id)

        if name is not None:
            calendar.name = name
        if description is not None:
            calendar.description = description
        if color is not None:
            calendar.color = color

        saved_calendar = await calendar_repo.save(calendar)

        from pydantic import BaseModel

        class CalendarResponse(BaseModel):
            id: str
            name: str
            summary: str

        return MCPResponseBuilder.success_response(
            CalendarResponse(
                id=str(saved_calendar.id),
                name=saved_calendar.name,
                summary=f"Updated calendar '{saved_calendar.name}'",
            )
        )

    @mcp.tool
    @mcp_unified_error_handler("delete_calendar", "journal")
    @inject
    async def delete_calendar(
        db_connection: FromDishka[AsyncConnection],
        calendar_id: Annotated[str, Field(description="Calendar UUID")],
    ) -> str:
        """
        Delete a calendar. Will fail if the calendar is in use.
        """
        import uuid

        from app.core.journal.adapters.sql.calendar_repository import (
            SqlCalendarRepository,
        )

        user_id = _get_current_user_id()
        calendar_repo = SqlCalendarRepository(db_connection)

        calendar = await calendar_repo.find_by_id(uuid.UUID(calendar_id))
        if not calendar or calendar.user_id != user_id:
            return MCPResponseBuilder.not_found_error_response("Calendar", calendar_id)

        from sqlalchemy import text

        check_query = text(
            """
            SELECT COUNT(*) as count
            FROM journal_calendar_info
            WHERE calendar_id = :calendar_id
            """
        )
        result = await db_connection.execute(check_query, {"calendar_id": calendar.id})
        row = result.fetchone()
        usage_count: int = row[0] if row else 0

        if usage_count > 0:
            return MCPResponseBuilder.error_response(
                f"Calendar is in use by {usage_count} journal(s)",
                "CONFLICT",
            )

        if calendar.id is not None:
            await calendar_repo.delete(calendar.id)

        from pydantic import BaseModel

        class DeleteCalendarResponse(BaseModel):
            summary: str

        return MCPResponseBuilder.success_response(
            DeleteCalendarResponse(summary=f"Deleted calendar '{calendar.name}'")
        )
