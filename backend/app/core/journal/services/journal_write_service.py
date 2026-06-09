"""Composite write service for journals.

Owns the multi-write orchestration that a single journal create/update request
performs (the journal row, its types, the per-type data rows, contact
relationships and the type-data updates). Each public method is decorated with
:func:`app.infrastructure.unit_of_work.transactional` so the *whole* composite
operation commits as ONE unit of work before the HTTP response is sent
(issue #945).

Because ``@transactional`` / ``unit_of_work`` are re-entrant, the underlying
service write methods (``JournalService``, ``JournalContactService``) may also
be decorated: when called from inside a composite method they join the outer
unit of work and only the outermost commit fires, so a mid-request failure
rolls the entire journal write back atomically.

Per-item batch operations (contact-relationship bulk processing) use
:func:`app.infrastructure.unit_of_work.savepoint` so one bad item rolls back
just its SAVEPOINT and the loop continues.
"""

from typing import Any

import structlog
from core_shared.models.history import Provenance
from core_shared.models.journals import (
    Journal,
    JournalContactRelationship,
    JournalContactRelationshipType,
    JournalType,
    JournalValidationError,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.album_sync_read_repository import (
    AlbumSyncReadRepository,
)
from app.core.journal.models.repositories import (
    AbseilingDataRepository,
    AbseilPitchRepository,
    BushwalkingDataRepository,
    CalendarInfoRepository,
    CanoeingDataRepository,
    CanyoningDataRepository,
    CavingDataRepository,
    ClimbingDataRepository,
    CrossCountrySkiingDataRepository,
    DivingDataRepository,
    DownhillSkiingDataRepository,
    FitnessDataRepository,
    GearMaintenanceDataRepository,
    JoggingDataRepository,
    KayakingDataRepository,
    MoodDataRepository,
    OutdoorActivityDataRepository,
    OutdoorPlanningDataRepository,
    OutdoorTrainingDataRepository,
    PlanDataRepository,
    SnorkellingDataRepository,
    TravelDataRepository,
)
from app.core.journal.services import journal_type_data_helpers as helpers
from app.core.journal.services.journal_contact_service import JournalContactService
from app.core.journal.services.journal_service import JournalService
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.infrastructure.unit_of_work import savepoint, transactional

logger = structlog.get_logger()


class JournalWriteService:
    """Service orchestrating composite journal writes as a single unit of work."""

    def __init__(
        self,
        journal_service: JournalService,
        journal_contact_service: JournalContactService,
        calendar_info_repo: CalendarInfoRepository,
        photo_album_data_repo: AlbumSyncReadRepository,
        mood_data_repo: MoodDataRepository,
        plan_data_repo: PlanDataRepository,
        travel_data_repo: TravelDataRepository,
        fitness_data_repo: FitnessDataRepository,
        outdoor_activity_data_repo: OutdoorActivityDataRepository,
        bushwalking_data_repo: BushwalkingDataRepository,
        jogging_data_repo: JoggingDataRepository,
        abseiling_data_repo: AbseilingDataRepository,
        abseil_pitch_repo: AbseilPitchRepository,
        canyoning_data_repo: CanyoningDataRepository,
        caving_data_repo: CavingDataRepository,
        canoeing_data_repo: CanoeingDataRepository,
        climbing_data_repo: ClimbingDataRepository,
        kayaking_data_repo: KayakingDataRepository,
        skiing_data_repo: CrossCountrySkiingDataRepository,
        snorkelling_data_repo: SnorkellingDataRepository,
        diving_data_repo: DivingDataRepository,
        downhill_skiing_data_repo: DownhillSkiingDataRepository,
        outdoor_planning_data_repo: OutdoorPlanningDataRepository,
        outdoor_training_data_repo: OutdoorTrainingDataRepository,
        gear_maintenance_data_repo: GearMaintenanceDataRepository,
        event_publisher: OutboxEventPublisher,
    ) -> None:
        self.journal_service = journal_service
        self.journal_contact_service = journal_contact_service
        self.calendar_info_repo = calendar_info_repo
        self.photo_album_data_repo = photo_album_data_repo
        self.mood_data_repo = mood_data_repo
        self.plan_data_repo = plan_data_repo
        self.travel_data_repo = travel_data_repo
        self.fitness_data_repo = fitness_data_repo
        self.outdoor_activity_data_repo = outdoor_activity_data_repo
        self.bushwalking_data_repo = bushwalking_data_repo
        self.jogging_data_repo = jogging_data_repo
        self.abseiling_data_repo = abseiling_data_repo
        self.abseil_pitch_repo = abseil_pitch_repo
        self.canyoning_data_repo = canyoning_data_repo
        self.caving_data_repo = caving_data_repo
        self.canoeing_data_repo = canoeing_data_repo
        self.climbing_data_repo = climbing_data_repo
        self.kayaking_data_repo = kayaking_data_repo
        self.skiing_data_repo = skiing_data_repo
        self.snorkelling_data_repo = snorkelling_data_repo
        self.diving_data_repo = diving_data_repo
        self.downhill_skiing_data_repo = downhill_skiing_data_repo
        self.outdoor_planning_data_repo = outdoor_planning_data_repo
        self.outdoor_training_data_repo = outdoor_training_data_repo
        self.gear_maintenance_data_repo = gear_maintenance_data_repo
        self.event_publisher = event_publisher

    # ------------------------------------------------------------------ #
    # Composite write operations                                          #
    # ------------------------------------------------------------------ #

    @transactional
    async def create_journal(
        self,
        journal: Journal,
        types: list[str] | None,
        type_data: dict[str, Any] | None,
        relationships: list[dict[str, Any]] | None,
        transaction: AsyncConnection,
        *,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
    ) -> Journal:
        """Create a journal with its types, type-data and contact relationships.

        The entire operation runs inside a single unit of work, so a failure in
        any step rolls back the whole journal.
        """
        created_journal = await self.journal_service.create_journal(
            journal, transaction, changed_by=changed_by, source=source
        )

        if created_journal.id is None:
            raise JournalValidationError(
                "id", "Journal ID is required after save operation"
            )
        journal_id = created_journal.id

        if types:
            await self._process_journal_types(
                journal_id, types, transaction, changed_by=changed_by, source=source
            )

        if type_data:
            await self._process_journal_type_data(journal_id, type_data, transaction)

        if relationships:
            await self._process_journal_contact_relationships(
                journal_id, relationships, transaction
            )

        return created_journal

    @transactional
    async def update_journal(
        self,
        journal: Journal,
        changed_fields: dict[str, Any],
        transaction: AsyncConnection,
        *,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
    ) -> Journal:
        """Update a journal's core fields as a committed unit of work."""
        return await self.journal_service.update_journal(
            journal,
            changed_fields,
            transaction,
            changed_by=changed_by,
            source=source,
        )

    @transactional
    async def delete_journal(
        self,
        journal_id: int,
        transaction: AsyncConnection,
        *,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
    ) -> None:
        """Delete a journal as a committed unit of work."""
        await self.journal_service.delete_journal(
            journal_id, transaction, changed_by=changed_by, source=source
        )

    @transactional
    async def add_type(
        self,
        journal_id: int,
        journal_type: JournalType,
        type_data: dict[str, Any] | None,
        transaction: AsyncConnection,
        *,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
    ) -> list[JournalType]:
        """Add a type (with dependencies), its default rows, and optional data."""
        added_types = await self.journal_service.add_type_to_journal(
            journal_id,
            journal_type,
            transaction,
            changed_by=changed_by,
            source=source,
        )

        for added_type in added_types:
            await self._create_type_specific_data(added_type, journal_id)

        if type_data:
            wrapped_type_data = {journal_type.value: type_data}
            await self._process_journal_type_data(
                journal_id, wrapped_type_data, transaction
            )

        return added_types

    @transactional
    async def remove_type(
        self,
        journal_id: int,
        journal_type: JournalType,
        transaction: AsyncConnection,
        *,
        changed_by: str = "system",
        source: Provenance = Provenance.SYSTEM,
    ) -> None:
        """Remove a type and delete its type-specific data row."""
        await self.journal_service.remove_type_from_journal(
            journal_id,
            journal_type,
            transaction,
            changed_by=changed_by,
            source=source,
        )
        await self._delete_type_specific_data(journal_type, journal_id)

    @transactional
    async def update_type_data(
        self,
        journal_id: int,
        journal_type: JournalType,
        attrs: dict[str, Any],
        transaction: AsyncConnection,
    ) -> None:
        """Update the type-specific data for a single existing journal type."""
        journal_type_str = journal_type.value

        if journal_type == JournalType.EVENT:
            await helpers.update_event_type_data(
                journal_id, journal_type_str, attrs, self.calendar_info_repo
            )
            # Publish JournalUpdated event so Google Calendar worker can sync
            from app.core.journal.models.events import JournalUpdated

            calendar_sync_event = JournalUpdated(
                journal_id=journal_id,
                changed_fields={"calendar_info": True},
                transaction=transaction,
            )
            await self.event_publisher.publish(calendar_sync_event)
        elif journal_type == JournalType.MOOD_RATING:
            await helpers.update_mood_type_data(
                journal_id, journal_type_str, attrs, self.mood_data_repo
            )
        elif journal_type == JournalType.PHOTO_ALBUM:
            # PHOTO_ALBUM data is managed by Immich album sync and cannot be
            # edited through this API.
            raise JournalValidationError(
                "journal_type",
                "PHOTO_ALBUM data is managed by Immich sync and cannot be edited",
            )
        elif journal_type == JournalType.FITNESS:
            await helpers.update_fitness_type_data(
                journal_id, journal_type_str, attrs, self.fitness_data_repo
            )
        elif journal_type == JournalType.OUTDOOR_ACTIVITY:
            await helpers.update_outdoor_activity_type_data(
                journal_id, journal_type_str, attrs, self.outdoor_activity_data_repo
            )
        elif journal_type == JournalType.BUSHWALKING:
            await helpers.update_bushwalking_type_data(
                journal_id, journal_type_str, attrs, self.bushwalking_data_repo
            )
        elif journal_type == JournalType.JOGGING:
            await helpers.update_jogging_type_data(
                journal_id, journal_type_str, attrs, self.jogging_data_repo
            )
        elif journal_type == JournalType.ABSEILING_TRIP:
            await helpers.update_abseiling_type_data(
                journal_id,
                journal_type_str,
                attrs,
                self.abseiling_data_repo,
                self.abseil_pitch_repo,
            )
        elif journal_type == JournalType.CANYONING:
            await helpers.update_canyoning_type_data(
                journal_id, journal_type_str, attrs, self.canyoning_data_repo
            )
        elif journal_type == JournalType.CAVING:
            await helpers.update_caving_type_data(
                journal_id, journal_type_str, attrs, self.caving_data_repo
            )
        elif journal_type == JournalType.CANOEING:
            await helpers.update_canoeing_type_data(
                journal_id, journal_type_str, attrs, self.canoeing_data_repo
            )
        elif journal_type == JournalType.CLIMBING:
            await helpers.update_climbing_type_data(
                journal_id, journal_type_str, attrs, self.climbing_data_repo
            )
        elif journal_type == JournalType.KAYAKING:
            await helpers.update_kayaking_type_data(
                journal_id, journal_type_str, attrs, self.kayaking_data_repo
            )
        elif journal_type == JournalType.CROSS_COUNTRY_SKIING:
            await helpers.update_cross_country_skiing_type_data(
                journal_id, journal_type_str, attrs, self.skiing_data_repo
            )
        elif journal_type == JournalType.SNORKELLING:
            if not await self.snorkelling_data_repo.find_by_journal_id(journal_id):
                raise JournalValidationError(
                    "journal_type", f"Journal does not have type {journal_type_str}"
                )
        elif journal_type == JournalType.DIVING:
            if not await self.diving_data_repo.find_by_journal_id(journal_id):
                raise JournalValidationError(
                    "journal_type", f"Journal does not have type {journal_type_str}"
                )
        elif journal_type == JournalType.DOWNHILL_SKIING:
            if not await self.downhill_skiing_data_repo.find_by_journal_id(journal_id):
                raise JournalValidationError(
                    "journal_type", f"Journal does not have type {journal_type_str}"
                )
        elif journal_type == JournalType.OUTDOOR_PLANNING:
            await helpers.update_outdoor_planning_type_data(
                journal_id, journal_type_str, attrs, self.outdoor_planning_data_repo
            )
        elif journal_type == JournalType.OUTDOOR_TRAINING:
            await helpers.update_outdoor_training_type_data(
                journal_id, attrs, self.outdoor_training_data_repo
            )
        elif journal_type == JournalType.GEAR_MAINTENANCE:
            await helpers.update_gear_maintenance_type_data(
                journal_id, journal_type_str, attrs, self.gear_maintenance_data_repo
            )
        elif journal_type in (JournalType.PLAN, JournalType.TRAVEL):
            # PLAN and TRAVEL types have complex nested data structures
            # For now, return an error indicating this is not yet supported
            raise JournalValidationError(
                "journal_type",
                f"Updating {journal_type_str} type data is not yet supported. "
                "Please use the full journal update endpoint instead.",
            )
        else:
            # NOTE type has no type-specific data
            raise JournalValidationError(
                "journal_type",
                f"Type {journal_type_str} has no type-specific data to update",
            )

    @transactional
    async def add_contact_to_journal(
        self,
        relationship: JournalContactRelationship,
        transaction: AsyncConnection,
    ) -> JournalContactRelationship:
        """Add a single contact relationship to a journal."""
        return await self.journal_contact_service.add_contact_to_journal(
            relationship, transaction=transaction
        )

    @transactional
    async def remove_contact_from_journal(
        self,
        journal_id: int,
        contact_id: int,
        relationship_type: JournalContactRelationshipType,
        transaction: AsyncConnection,
    ) -> None:
        """Remove a single contact relationship from a journal."""
        await self.journal_contact_service.remove_contact_from_journal(
            journal_id, contact_id, relationship_type, transaction=transaction
        )

    # ------------------------------------------------------------------ #
    # Private orchestration helpers                                       #
    # ------------------------------------------------------------------ #

    async def _process_journal_types(
        self,
        journal_id: int,
        types: list[str],
        transaction: AsyncConnection,
        *,
        changed_by: str,
        source: Provenance,
    ) -> None:
        """Add the requested types (and dependencies) plus their default rows.

        Invalid type strings are skipped, mirroring the original controller.
        """
        for type_str in types:
            try:
                journal_type = helpers.parse_journal_type(type_str)

                # Returns all types added, including auto-resolved dependencies
                added_types = await self.journal_service.add_type_to_journal(
                    journal_id,
                    journal_type,
                    transaction,
                    changed_by=changed_by,
                    source=source,
                )

                # Create type-specific data rows for ALL added types (including
                # dependencies)
                for added_type in added_types:
                    await self._create_type_specific_data(added_type, journal_id)
            except ValueError, KeyError:
                # Invalid type, skip
                pass

    async def _process_journal_type_data(
        self,
        journal_id: int,
        type_data: dict[str, Any],
        transaction: AsyncConnection,
    ) -> None:
        """Process and save type-specific data supplied with a create request.

        ``type_data`` keys are case-insensitive.
        """
        # Normalize type_data keys to lowercase for case-insensitive matching
        normalized_type_data = {k.lower(): v for k, v in type_data.items()}

        # Process EVENT type data
        if "event" in normalized_type_data:
            from datetime import time as dt_time
            from uuid import UUID

            from core_shared.models.journals import CalendarInfo

            event_data = normalized_type_data["event"]

            try:

                def _parse_time_str(time_str: str) -> dt_time:
                    """Parse HH:MM or HH:MM:SS time strings from HTML time inputs."""
                    parts = time_str.split(":")
                    if len(parts) == 2:  # noqa: PLR2004
                        hours, minutes = map(int, parts)
                        seconds = 0
                    elif len(parts) == 3:  # noqa: PLR2004
                        hours, minutes, seconds = map(int, parts)
                    else:
                        raise ValueError(f"Invalid time format: {time_str!r}")
                    return dt_time(hours, minutes, seconds)

                # Convert string times to time objects if provided
                start_time = None
                if event_data.get("start_time"):
                    start_time = _parse_time_str(event_data["start_time"])

                end_time = None
                if event_data.get("end_time"):
                    end_time = _parse_time_str(event_data["end_time"])

                calendar_info = CalendarInfo(
                    journal_id=journal_id,
                    calendar_id=UUID(event_data["calendar_id"]),
                    description=event_data.get("description"),
                    start_time=start_time,
                    end_time=end_time,
                    is_all_day=event_data.get("is_all_day", False),
                    location=event_data.get("location"),
                    timezone=event_data.get("timezone"),
                    sync_invitees=event_data.get("sync_invitees", False),
                    private_description=event_data.get("private_description", False),
                )
                await self.calendar_info_repo.save(calendar_info)

                # Publish JournalUpdated event so Google Calendar worker can sync
                from app.core.journal.models.events import JournalUpdated

                calendar_sync_event = JournalUpdated(
                    journal_id=journal_id,
                    changed_fields={"calendar_info": True},
                    transaction=transaction,
                )
                await self.event_publisher.publish(calendar_sync_event)
            except (ValueError, KeyError) as exc:
                from fastapi import HTTPException

                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid EVENT type_data: {exc}",
                ) from exc

        # PHOTO_ALBUM type data is integration-managed (Immich album sync) and is
        # not writable through this API. Fail fast rather than silently dropping
        # the payload so callers don't believe a write succeeded.
        if "photo_album" in normalized_type_data:
            raise JournalValidationError(
                "photo_album",
                "PHOTO_ALBUM data is managed by Immich sync and cannot be set",
            )

        # Process PLAN type data
        if "plan" in normalized_type_data:
            import uuid

            from core_shared.models.journals import PlanData, PlanDocument

            plan_payload = normalized_type_data["plan"]
            plan_data = await self.plan_data_repo.find_by_journal_id(journal_id)
            if not plan_data:
                plan_data = PlanData(journal_id=journal_id)

            if "documents" in plan_payload:
                documents: list[PlanDocument] = []
                for doc in plan_payload["documents"]:
                    doc_id = uuid.uuid4()
                    # Coerce null/blank title to "Untitled"
                    title_raw = doc.get("title")
                    if not title_raw or (
                        isinstance(title_raw, str) and not title_raw.strip()
                    ):
                        title = "Untitled"
                    else:
                        title = title_raw
                    # Coerce null order to sequential index
                    order_raw = doc.get("order")
                    order = order_raw if isinstance(order_raw, int) else len(documents)
                    documents.append(
                        PlanDocument(
                            id=doc_id,
                            journal_id=journal_id,
                            url=doc["url"],
                            title=title,
                            description=doc.get("description"),
                            order=order,
                        )
                    )
                plan_data.documents = documents

            # Persist PlanData itself
            await self.plan_data_repo.save(plan_data)

            # Persist each PlanDocument explicitly (save() does not cascade documents)
            for document in plan_data.documents:
                await self.plan_data_repo.save_document(document)

        # Process TRAVEL type data
        if "travel" in normalized_type_data:
            from core_shared.models.journals import TravelData

            # Payload for travel currently empty in UI, but create data if valid
            travel_data = await self.travel_data_repo.find_by_journal_id(journal_id)
            if not travel_data:
                travel_data = TravelData(journal_id=journal_id)
            await self.travel_data_repo.save(travel_data)

        # Process MOOD_RATING type data
        if "mood_rating" in normalized_type_data:
            from core_shared.models.journals import MoodData

            mood_payload = normalized_type_data["mood_rating"]
            mood_data = await self.mood_data_repo.find_by_journal_id(journal_id)
            if mood_data is None:
                mood_data = MoodData(journal_id=journal_id)

            mood_value_raw = mood_payload.get("mood_value")
            energy_level_raw = mood_payload.get("energy_level")

            if mood_value_raw is not None:
                try:
                    mood_data.mood_value = int(mood_value_raw)
                except (TypeError, ValueError) as exc:
                    from fastapi import HTTPException

                    raise HTTPException(
                        status_code=400,
                        detail="mood_value must be an integer",
                    ) from exc
            if energy_level_raw is not None:
                try:
                    mood_data.energy_level = int(energy_level_raw)
                except (TypeError, ValueError) as exc:
                    from fastapi import HTTPException

                    raise HTTPException(
                        status_code=400,
                        detail="energy_level must be an integer",
                    ) from exc
            mood_data.mood_label = (
                mood_payload.get("mood_label") or mood_data.mood_label
            )

            await self.mood_data_repo.save(mood_data)

        # Process FITNESS type data
        if "fitness" in normalized_type_data:
            from core_shared.models.journals import FitnessData

            fitness_payload = normalized_type_data["fitness"]
            fitness_data = await self.fitness_data_repo.find_by_journal_id(journal_id)
            if fitness_data is None:
                fitness_data = FitnessData(journal_id=journal_id)

            numeric_fields = (
                "distance",
                "duration",
                "heart_rate_avg",
                "heart_rate_max",
                "elevation_gain",
                "elevation_loss",
                "calories",
            )
            for field in numeric_fields:
                if field in fitness_payload:
                    value = fitness_payload[field]
                    if value is None:
                        setattr(fitness_data, field, None)
                    else:
                        try:
                            setattr(fitness_data, field, int(value))
                        except (TypeError, ValueError) as exc:
                            from fastapi import HTTPException

                            raise HTTPException(
                                status_code=400,
                                detail=f"{field} must be an integer",
                            ) from exc

            if "strava_activity_id" in fitness_payload:
                fitness_data.strava_activity_id = fitness_payload["strava_activity_id"]

            await self.fitness_data_repo.save(fitness_data)

        # Process OUTDOOR_ACTIVITY type data
        if "outdoor_activity" in normalized_type_data:
            from core_shared.models.journals import OutdoorActivityData

            outdoor_payload = normalized_type_data["outdoor_activity"]
            outdoor_data = await self.outdoor_activity_data_repo.find_by_journal_id(
                journal_id
            )
            if outdoor_data is None:
                outdoor_data = OutdoorActivityData(journal_id=journal_id)

            if "weather_conditions" in outdoor_payload:
                outdoor_data.weather_conditions = outdoor_payload["weather_conditions"]
            if "role" in outdoor_payload:
                outdoor_data.role = outdoor_payload["role"]
            if "in_leadership_role" in outdoor_payload:
                outdoor_data.in_leadership_role = outdoor_payload["in_leadership_role"]
            if "participant_notes" in outdoor_payload:
                outdoor_data.participant_notes = outdoor_payload["participant_notes"]

            await self.outdoor_activity_data_repo.save(outdoor_data)

        # Process BUSHWALKING type data
        if "bushwalking" in normalized_type_data:
            from core_shared.models.journals import BushwalkingData

            bushwalking_payload = normalized_type_data["bushwalking"]
            bushwalking_data = await self.bushwalking_data_repo.find_by_journal_id(
                journal_id
            )
            if bushwalking_data is None:
                bushwalking_data = BushwalkingData(journal_id=journal_id)

            if "track_grading" in bushwalking_payload:
                bushwalking_data.track_grading = bushwalking_payload["track_grading"]

            await self.bushwalking_data_repo.save(bushwalking_data)

        # Process JOGGING type data
        if "jogging" in normalized_type_data:
            from core_shared.models.journals import JoggingData

            jogging_payload = normalized_type_data["jogging"]
            jogging_data = await self.jogging_data_repo.find_by_journal_id(journal_id)
            if jogging_data is None:
                jogging_data = JoggingData(journal_id=journal_id)

            if "pace" in jogging_payload:
                pace_raw = jogging_payload["pace"]
                if pace_raw is None:
                    jogging_data.pace = None
                else:
                    try:
                        jogging_data.pace = int(pace_raw)
                    except (TypeError, ValueError) as exc:
                        from fastapi import HTTPException

                        raise HTTPException(
                            status_code=400,
                            detail="pace must be an integer (seconds per km)",
                        ) from exc

            await self.jogging_data_repo.save(jogging_data)

        # Process ABSEILING_TRIP type data
        if "abseiling_trip" in normalized_type_data:
            await helpers.update_abseiling_type_data(
                journal_id,
                "ABSEILING_TRIP",
                normalized_type_data["abseiling_trip"],
                self.abseiling_data_repo,
                self.abseil_pitch_repo,
            )

        # Process CANYONING type data
        if "canyoning" in normalized_type_data:
            await helpers.update_canyoning_type_data(
                journal_id,
                "CANYONING",
                normalized_type_data["canyoning"],
                self.canyoning_data_repo,
            )

        # Process CAVING type data
        if "caving" in normalized_type_data:
            await helpers.update_caving_type_data(
                journal_id,
                "CAVING",
                normalized_type_data["caving"],
                self.caving_data_repo,
            )

        # Process CANOEING type data
        if "canoeing" in normalized_type_data:
            await helpers.update_canoeing_type_data(
                journal_id,
                "CANOEING",
                normalized_type_data["canoeing"],
                self.canoeing_data_repo,
            )

        # Process CLIMBING type data
        if "climbing" in normalized_type_data:
            await helpers.update_climbing_type_data(
                journal_id,
                "CLIMBING",
                normalized_type_data["climbing"],
                self.climbing_data_repo,
            )

        # Process KAYAKING type data
        if "kayaking" in normalized_type_data:
            await helpers.update_kayaking_type_data(
                journal_id,
                "KAYAKING",
                normalized_type_data["kayaking"],
                self.kayaking_data_repo,
            )

        # Process CROSS_COUNTRY_SKIING type data
        if "cross_country_skiing" in normalized_type_data:
            await helpers.update_cross_country_skiing_type_data(
                journal_id,
                "CROSS_COUNTRY_SKIING",
                normalized_type_data["cross_country_skiing"],
                self.skiing_data_repo,
            )

        # Process OUTDOOR_PLANNING type data
        if "outdoor_planning" in normalized_type_data:
            await helpers.update_outdoor_planning_type_data(
                journal_id,
                "OUTDOOR_PLANNING",
                normalized_type_data["outdoor_planning"],
                self.outdoor_planning_data_repo,
            )

        # Process OUTDOOR_TRAINING type data
        if "outdoor_training" in normalized_type_data:
            await helpers.update_outdoor_training_type_data(
                journal_id,
                normalized_type_data["outdoor_training"],
                self.outdoor_training_data_repo,
            )

        # Process GEAR_MAINTENANCE type data
        if "gear_maintenance" in normalized_type_data:
            await helpers.update_gear_maintenance_type_data(
                journal_id,
                "GEAR_MAINTENANCE",
                normalized_type_data["gear_maintenance"],
                self.gear_maintenance_data_repo,
            )

    async def _process_journal_contact_relationships(
        self,
        journal_id: int,
        contacts_data: list[dict[str, Any]],
        transaction: AsyncConnection,
    ) -> None:
        """Create contact relationships for a journal, skipping invalid items.

        Each relationship is wrapped in a SAVEPOINT so a missing contact or a
        unique-constraint violation rolls back only that item, not the whole
        composite write.
        """
        for contact_data in contacts_data:
            try:
                # Extract contact_id and relationship_type from attributes
                # contact_data is a dict from JSON, not a Pydantic model
                if "attributes" in contact_data:
                    attrs = contact_data["attributes"]
                    contact_id = int(attrs["contact_id"])
                    relationship_type = JournalContactRelationshipType[
                        attrs["relationship_type"]
                    ]

                    # Parse status and role if present
                    from core_shared.models.journals.attendee_status import (
                        AttendeeStatus,
                    )
                    from core_shared.models.journals.contact_event_role import (
                        ContactEventRole,
                    )

                    status, role = None, None
                    status_raw = attrs.get("status")
                    if isinstance(status_raw, str):
                        try:
                            status = AttendeeStatus[status_raw.upper()]
                        except KeyError:
                            logger.warning(
                                "Invalid AttendeeStatus",
                                status=status_raw,
                                journal_id=journal_id,
                                contact_id=contact_id,
                            )

                    role_raw = attrs.get("role")
                    if isinstance(role_raw, str):
                        try:
                            role = ContactEventRole[role_raw.upper()]
                        except KeyError:
                            logger.warning(
                                "Invalid ContactEventRole",
                                role=role_raw,
                                journal_id=journal_id,
                                contact_id=contact_id,
                            )

                    # Create the relationship using a SAVEPOINT to prevent
                    # aborting the unit of work if a contact is missing or a
                    # unique constraint is violated.
                    relationship = JournalContactRelationship(
                        journal_id=journal_id,
                        contact_id=contact_id,
                        relationship_type=relationship_type,
                        status=status,
                        role=role,
                    )
                    try:
                        async with savepoint(transaction):
                            await self.journal_contact_service.add_contact_to_journal(
                                relationship, transaction=transaction
                            )
                    except IntegrityError:
                        # Log error and ignore; the savepoint handles the rollback
                        logger.warning(
                            "Invalid journal contact relationship ignored",
                            journal_id=journal_id,
                            contact_id=contact_id,
                        )

            except ValueError, KeyError, AttributeError, TypeError:
                # Invalid contact relationship payload, skip
                pass

    async def _create_type_specific_data(
        self, journal_type: JournalType, journal_id: int
    ) -> None:
        """Create the default type-specific data row for a journal type."""
        await helpers.create_type_specific_data(
            journal_type,
            journal_id,
            self.mood_data_repo,
            self.plan_data_repo,
            self.travel_data_repo,
            self.fitness_data_repo,
            self.outdoor_activity_data_repo,
            self.bushwalking_data_repo,
            self.jogging_data_repo,
            self.abseiling_data_repo,
            self.abseil_pitch_repo,
            self.canyoning_data_repo,
            self.caving_data_repo,
            self.canoeing_data_repo,
            self.climbing_data_repo,
            self.kayaking_data_repo,
            self.skiing_data_repo,
            self.snorkelling_data_repo,
            self.diving_data_repo,
            self.downhill_skiing_data_repo,
            self.outdoor_planning_data_repo,
            self.outdoor_training_data_repo,
            self.gear_maintenance_data_repo,
        )

    async def _delete_type_specific_data(
        self, journal_type: JournalType, journal_id: int
    ) -> None:
        """Delete the type-specific data row for a journal type."""
        await helpers.delete_type_specific_data(
            journal_type,
            journal_id,
            self.mood_data_repo,
            self.plan_data_repo,
            self.travel_data_repo,
            self.photo_album_data_repo,
            self.fitness_data_repo,
            self.outdoor_activity_data_repo,
            self.bushwalking_data_repo,
            self.jogging_data_repo,
            self.abseiling_data_repo,
            self.abseil_pitch_repo,
            self.canyoning_data_repo,
            self.caving_data_repo,
            self.canoeing_data_repo,
            self.climbing_data_repo,
            self.kayaking_data_repo,
            self.skiing_data_repo,
            self.snorkelling_data_repo,
            self.diving_data_repo,
            self.downhill_skiing_data_repo,
            self.outdoor_planning_data_repo,
            self.outdoor_training_data_repo,
            self.gear_maintenance_data_repo,
        )
