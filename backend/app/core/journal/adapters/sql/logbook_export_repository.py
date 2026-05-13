"""SQL-based repository for logbook export operations."""

import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from core_shared.models.journals import (
    AbseilingData,
    AbseilPitch,
    BushwalkingData,
    CanoeingData,
    CanyoningData,
    CavingData,
    ClimbingData,
    CrossCountrySkiingData,
    DivingData,
    DownhillSkiingData,
    EventDateRange,
    FitnessData,
    GearMaintenanceData,
    JournalValidationError,
    KayakingData,
    LogbookEntryContact,
    LogbookEntryData,
    OutdoorActivityData,
    OutdoorPlanningData,
    OutdoorTrainingData,
    SnorkellingData,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.models.repositories import LogbookExportRepository


class SqlLogbookExportRepository(LogbookExportRepository):
    """SQL implementation of the logbook export repository."""

    def __init__(self, connection: AsyncConnection):
        """Initialize the repository."""
        self.connection = connection

    async def get_logbook_entries(
        self,
        user_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
        activity_types: list[str] | None = None,
    ) -> list[LogbookEntryData]:
        """
        Get all matching journals for the logbook export with their nested type data.

        Returns a flat list of LogbookEntryData that the LogbookDataService
        will assemble into a hierarchical tree.
        """
        # 1. Fetch matching journals and all descendants/ancestors
        # For simplicity and correctness, we will just fetch all journals for the user
        # that match the types/dates, AND their descendants, so we preserve the hierarchy.

        # We need journals that have one of the logbook types:
        logbook_types = [
            "BUSHWALKING",
            "CANYONING",
            "CAVING",
            "CLIMBING",
            "KAYAKING",
            "CANOEING",
            "SNORKELLING",
            "DIVING",
            "CROSS_COUNTRY_SKIING",
            "DOWNHILL_SKIING",
            "ABSEILING_TRIP",
            "OUTDOOR_ACTIVITY",
            "OUTDOOR_TRAINING",
            "OUTDOOR_PLANNING",
            "GEAR_MAINTENANCE",
        ]

        if activity_types:
            # Filter the allowed types by the requested ones if provided
            activity_types_upper = [t.upper() for t in activity_types]
            logbook_types = [t for t in logbook_types if t in activity_types_upper]

        if not logbook_types:
            return []

        # Find the root journals that match the criteria
        query_params: dict[str, Any] = {"user_id": user_id}

        # We need all journals that match, AND all their ancestors and descendants
        # to assemble a complete tree. But wait, if we include ancestors/descendants
        # that don't match the types, should they be in the logbook? Yes, typically
        # to show the hierarchy context (e.g. "Trip to Blue Mountains" (Event) -> "Bushwalking").
        # The spec says: "Journals ordered chronologically by topmost parent journal date, full hierarchy preserved".

        query_params = {"user_id": user_id}

        table_map = {
            "OUTDOOR_ACTIVITY": "journal_outdoor_activity_data",
            "BUSHWALKING": "journal_bushwalking_data",
            "CANYONING": "journal_canyoning_data",
            "CAVING": "journal_caving_data",
            "CLIMBING": "journal_climbing_data",
            "KAYAKING": "journal_kayaking_data",
            "CROSS_COUNTRY_SKIING": "journal_skiing_data",
            "CANOEING": "journal_canoeing_data",
            "SNORKELLING": "journal_snorkelling_data",
            "DIVING": "journal_diving_data",
            "DOWNHILL_SKIING": "journal_downhill_skiing_data",
            "ABSEILING_TRIP": "journal_abseiling_data",
            "OUTDOOR_PLANNING": "journal_outdoor_planning_data",
            "OUTDOOR_TRAINING": "journal_outdoor_training_data",
            "GEAR_MAINTENANCE": "journal_gear_maintenance_data",
            "EVENT": "journal_calendar_info",
        }

        joins = []
        where_conditions = []

        alias_idx = 0
        for t in logbook_types:
            if t in table_map:
                alias = f"t{alias_idx}"
                table = table_map[t]
                joins.append(f"LEFT JOIN {table} {alias} ON j.id = {alias}.journal_id")
                where_conditions.append(f"{alias}.journal_id IS NOT NULL")
                alias_idx += 1

        if not where_conditions:
            return []

        date_filters = ""
        if start_date:
            date_filters += " AND j.event_date_range_end >= :start_date"
            dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            query_params["start_date"] = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        if end_date:
            date_filters += " AND j.event_date_range_start <= :end_date"
            dt_end = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            query_params["end_date"] = (
                dt_end if dt_end.tzinfo else dt_end.replace(tzinfo=UTC)
            )

        cte_sql = f"""
            WITH RECURSIVE
            matching_journals AS (
                SELECT j.id, j.parent_id
                FROM journals j
                {" ".join(joins)}
                WHERE j.user_id = :user_id
                AND ( {" OR ".join(where_conditions)} )
                {date_filters}
            ),
            ancestors AS (
                SELECT id, parent_id FROM matching_journals
                UNION
                SELECT j.id, j.parent_id
                FROM journals j
                JOIN ancestors a ON j.id = a.parent_id
                WHERE j.user_id = :user_id
            ),
            descendants AS (
                SELECT id, parent_id FROM ancestors
                UNION
                SELECT j.id, j.parent_id
                FROM journals j
                JOIN descendants d ON j.parent_id = d.id
                WHERE j.user_id = :user_id
            ),
            final_ids AS (
                SELECT id FROM ancestors
                UNION
                SELECT id FROM descendants
            )
            SELECT j.id, j.title, j.content, j.event_date_range_start, j.event_date_range_end, j.parent_id
            FROM journals j
            JOIN final_ids f ON j.id = f.id
        """

        result = await self.connection.execute(text(cte_sql), query_params)
        final_journal_rows = result.fetchall()

        if not final_journal_rows:
            return []

        final_journal_ids = [row.id for row in final_journal_rows]

        # 2. Fetch all journal types for the final journal ids
        types_sql = """
            SELECT j.id as journal_id,
                CASE WHEN jci.journal_id IS NOT NULL THEN 'EVENT' END as event_type,
                CASE WHEN jmd.journal_id IS NOT NULL THEN 'MOOD_RATING' END as mood_type,
                CASE WHEN jpd.journal_id IS NOT NULL THEN 'PLAN' END as plan_type,
                CASE WHEN jtd.journal_id IS NOT NULL THEN 'TRAVEL' END as travel_type,
                CASE WHEN jpad.journal_id IS NOT NULL THEN 'PHOTO_ALBUM' END as photo_type,
                CASE WHEN jfd.journal_id IS NOT NULL THEN 'FITNESS' END as fitness_type,
                CASE WHEN joad.journal_id IS NOT NULL THEN 'OUTDOOR_ACTIVITY' END as outdoor_activity_type,
                CASE WHEN jbwd.journal_id IS NOT NULL THEN 'BUSHWALKING' END as bushwalking_type,
                CASE WHEN jjd.journal_id IS NOT NULL THEN 'JOGGING' END as jogging_type,
                CASE WHEN jabd.journal_id IS NOT NULL THEN 'ABSEILING_TRIP' END as abseiling_type,
                CASE WHEN jcyd.journal_id IS NOT NULL THEN 'CANYONING' END as canyoning_type,
                CASE WHEN jcld.journal_id IS NOT NULL THEN 'CLIMBING' END as climbing_type,
                CASE WHEN jkyd.journal_id IS NOT NULL THEN 'KAYAKING' END as kayaking_type,
                CASE WHEN jskid.journal_id IS NOT NULL THEN 'CROSS_COUNTRY_SKIING' END as skiing_type,
                CASE WHEN jcvd.journal_id IS NOT NULL THEN 'CAVING' END as caving_type,
                CASE WHEN jcnd.journal_id IS NOT NULL THEN 'CANOEING' END as canoeing_type,
                CASE WHEN jsnkd.journal_id IS NOT NULL THEN 'SNORKELLING' END as snorkelling_type,
                CASE WHEN jdivd.journal_id IS NOT NULL THEN 'DIVING' END as diving_type,
                CASE WHEN jdsd.journal_id IS NOT NULL THEN 'DOWNHILL_SKIING' END as downhill_skiing_type,
                CASE WHEN jopd.journal_id IS NOT NULL THEN 'OUTDOOR_PLANNING' END as outdoor_planning_type,
                CASE WHEN jotd.journal_id IS NOT NULL THEN 'OUTDOOR_TRAINING' END as outdoor_training_type,
                CASE WHEN jgmd.journal_id IS NOT NULL THEN 'GEAR_MAINTENANCE' END as gear_maintenance_type
            FROM journals j
            LEFT JOIN journal_calendar_info jci ON j.id = jci.journal_id
            LEFT JOIN journal_mood_data jmd ON j.id = jmd.journal_id
            LEFT JOIN journal_plan_data jpd ON j.id = jpd.journal_id
            LEFT JOIN journal_travel_data jtd ON j.id = jtd.journal_id
            LEFT JOIN journal_photo_album_data jpad ON j.id = jpad.journal_id
            LEFT JOIN journal_fitness_data jfd ON j.id = jfd.journal_id
            LEFT JOIN journal_outdoor_activity_data joad ON j.id = joad.journal_id
            LEFT JOIN journal_bushwalking_data jbwd ON j.id = jbwd.journal_id
            LEFT JOIN journal_jogging_data jjd ON j.id = jjd.journal_id
            LEFT JOIN journal_abseiling_data jabd ON j.id = jabd.journal_id
            LEFT JOIN journal_canyoning_data jcyd ON j.id = jcyd.journal_id
            LEFT JOIN journal_climbing_data jcld ON j.id = jcld.journal_id
            LEFT JOIN journal_kayaking_data jkyd ON j.id = jkyd.journal_id
            LEFT JOIN journal_skiing_data jskid ON j.id = jskid.journal_id
            LEFT JOIN journal_caving_data jcvd ON j.id = jcvd.journal_id
            LEFT JOIN journal_canoeing_data jcnd ON j.id = jcnd.journal_id
            LEFT JOIN journal_snorkelling_data jsnkd ON j.id = jsnkd.journal_id
            LEFT JOIN journal_diving_data jdivd ON j.id = jdivd.journal_id
            LEFT JOIN journal_downhill_skiing_data jdsd ON j.id = jdsd.journal_id
            LEFT JOIN journal_outdoor_planning_data jopd ON j.id = jopd.journal_id
            LEFT JOIN journal_outdoor_training_data jotd ON j.id = jotd.journal_id
            LEFT JOIN journal_gear_maintenance_data jgmd ON j.id = jgmd.journal_id
            WHERE j.id = ANY(:journal_ids)
        """
        result = await self.connection.execute(
            text(types_sql), {"journal_ids": final_journal_ids}
        )
        types_by_journal = defaultdict(list)
        for row in result.fetchall():
            for i in range(1, len(row)):
                if row[i]:
                    types_by_journal[row.journal_id].append(row[i])

        # Determine if 'NOTE' applies to any
        for jid in final_journal_ids:
            if not types_by_journal[jid]:
                types_by_journal[jid].append("NOTE")

        # 4. Fetch related data for these final journal IDs

        # Contacts
        contacts_sql = """
            SELECT
                r.journal_id, r.contact_id, r.relationship_type as role,
                TRIM(c.first_name || ' ' || COALESCE(c.last_name, '')) as name
            FROM journal_contact_relationships r
            JOIN contacts c ON r.contact_id = c.id
            WHERE r.journal_id = ANY(:journal_ids)
            AND r.relationship_type IN ('PARTICIPANT', 'INVITEE')
        """
        result = await self.connection.execute(
            text(contacts_sql), {"journal_ids": final_journal_ids}
        )
        contacts_by_journal = defaultdict(list)
        for row in result.fetchall():
            contacts_by_journal[row.journal_id].append(
                LogbookEntryContact(
                    contact_id=row.contact_id, name=row.name, role=row.role
                )
            )

        # Abseil Pitches
        pitches_sql = """
            SELECT journal_id, id, pitch_number, height, anchor_location, anchor_type, did_rescue, did_setup
            FROM abseil_pitches
            WHERE journal_id = ANY(:journal_ids)
            ORDER BY pitch_number
        """
        result = await self.connection.execute(
            text(pitches_sql), {"journal_ids": final_journal_ids}
        )
        pitches_by_journal = defaultdict(list)
        for row in result.fetchall():
            try:
                pitches_by_journal[row.journal_id].append(
                    AbseilPitch(
                        id=row.id,
                        journal_id=row.journal_id,
                        pitch_number=row.pitch_number,
                        height=row.height,
                        anchor_location=row.anchor_location,
                        anchor_type=row.anchor_type,
                        did_rescue=row.did_rescue,
                        did_setup=row.did_setup,
                    )
                )
            except ValueError:
                pass

        # Type-specific Data
        # Helper to fetch a 1:1 table mapped by journal_id
        async def fetch_type_data(table_name: str) -> dict[int, Any]:
            sql = f"SELECT * FROM {table_name} WHERE journal_id = ANY(:journal_ids)"
            result = await self.connection.execute(
                text(sql), {"journal_ids": final_journal_ids}
            )
            # Convert rows to dicts
            return {row.journal_id: dict(row._mapping) for row in result.fetchall()}

        outdoor_act_data = await fetch_type_data("journal_outdoor_activity_data")
        fitness_data = await fetch_type_data("journal_fitness_data")
        bushwalking_data = await fetch_type_data("journal_bushwalking_data")
        abseiling_data = await fetch_type_data("journal_abseiling_data")
        canyoning_data = await fetch_type_data("journal_canyoning_data")
        climbing_data = await fetch_type_data("journal_climbing_data")
        kayaking_data = await fetch_type_data("journal_kayaking_data")
        cc_skiing_data = await fetch_type_data("journal_skiing_data")
        caving_data = await fetch_type_data("journal_caving_data")
        canoeing_data = await fetch_type_data("journal_canoeing_data")
        snorkelling_data = await fetch_type_data("journal_snorkelling_data")
        diving_data = await fetch_type_data("journal_diving_data")
        dh_skiing_data = await fetch_type_data("journal_downhill_skiing_data")
        outdoor_plan_data = await fetch_type_data("journal_outdoor_planning_data")
        outdoor_train_data = await fetch_type_data("journal_outdoor_training_data")
        gear_maint_data = await fetch_type_data("journal_gear_maintenance_data")

        # Resolve names for activity templates and gear items
        template_ids = [
            d["template_id"] for d in canyoning_data.values() if d.get("template_id")
        ]
        template_ids += [
            d["template_id"] for d in caving_data.values() if d.get("template_id")
        ]
        template_ids += [
            d["template_id"] for d in climbing_data.values() if d.get("template_id")
        ]
        template_names = {}
        if template_ids:
            sql = "SELECT id, name FROM activity_templates WHERE id = ANY(:ids) AND user_id = :user_id"
            result = await self.connection.execute(
                text(sql), {"ids": template_ids, "user_id": user_id}
            )
            template_names = {row.id: row.name for row in result.fetchall()}

        gear_item_ids = [
            d["gear_item_id"] for d in gear_maint_data.values() if d.get("gear_item_id")
        ]
        gear_item_names = {}
        if gear_item_ids:
            sql = "SELECT id, name FROM gear_items WHERE id = ANY(:ids) AND user_id = :user_id"
            result = await self.connection.execute(
                text(sql), {"ids": gear_item_ids, "user_id": user_id}
            )
            gear_item_names = {row.id: row.name for row in result.fetchall()}

        entries = []
        for row in final_journal_rows:
            # We instantiate domain models where possible but ignore strict validation if data is legacy/invalid.
            # This ensures logbook export succeeds even if old data doesn't meet current validation constraints.

            def create_if_exists(
                domain_cls: Any, data_dict: dict[str, Any] | None, **extra: Any
            ) -> Any:
                if not data_dict:
                    return None

                # Filter to only attributes that exist in the domain class
                # taking care of renaming or removing unneeded db columns (like timestamps)
                kwargs = {
                    k: (
                        json.loads(v)
                        if k == "activity_types" and isinstance(v, str)
                        else v
                    )
                    for k, v in data_dict.items()
                    if hasattr(domain_cls, k) or k in domain_cls.__annotations__
                }
                kwargs.update(extra)
                try:
                    return domain_cls(**kwargs)
                except Exception:
                    # In logbook export we skip invalid data rather than crashing the whole export
                    return None

            # Defensively construct EventDateRange — legacy data may have null dates.
            # If one bound is missing, collapse it to the known bound so duration is 0
            # rather than using a 2099 fallback which skews multi-day logic.
            _FALLBACK_START = datetime(2000, 1, 1, tzinfo=UTC)
            try:
                raw_start = row.event_date_range_start
                raw_end = row.event_date_range_end

                # First parse whatever dates we have
                parsed_start = (
                    raw_start.replace(tzinfo=UTC)
                    if raw_start and raw_start.tzinfo is None
                    else raw_start
                )
                parsed_end = (
                    raw_end.replace(tzinfo=UTC)
                    if raw_end and raw_end.tzinfo is None
                    else raw_end
                )

                # Collapse missing bounds
                start_dt = parsed_start or parsed_end or _FALLBACK_START
                end_dt = parsed_end or start_dt

                event_date_range = EventDateRange(start=start_dt, end=end_dt)
            except (ValueError, AttributeError, JournalValidationError):
                # Skip journals with completely invalid date data
                continue

            entry = LogbookEntryData(
                id=row.id,
                title=row.title,
                content=row.content,
                event_date_range=event_date_range,
                parent_id=row.parent_id,
                journal_types=types_by_journal[row.id],
                contacts=contacts_by_journal[row.id],
                abseil_pitches=pitches_by_journal[row.id],
                outdoor_activity_data=create_if_exists(
                    OutdoorActivityData, outdoor_act_data.get(row.id)
                ),
                fitness_data=create_if_exists(FitnessData, fitness_data.get(row.id)),
                bushwalking_data=create_if_exists(
                    BushwalkingData, bushwalking_data.get(row.id)
                ),
                abseiling_data=create_if_exists(
                    AbseilingData, abseiling_data.get(row.id)
                ),
                canyoning_data=create_if_exists(
                    CanyoningData, canyoning_data.get(row.id)
                ),
                climbing_data=create_if_exists(ClimbingData, climbing_data.get(row.id)),
                kayaking_data=create_if_exists(KayakingData, kayaking_data.get(row.id)),
                cross_country_skiing_data=create_if_exists(
                    CrossCountrySkiingData, cc_skiing_data.get(row.id)
                ),
                caving_data=create_if_exists(CavingData, caving_data.get(row.id)),
                canoeing_data=create_if_exists(CanoeingData, canoeing_data.get(row.id)),
                snorkelling_data=create_if_exists(
                    SnorkellingData, snorkelling_data.get(row.id)
                ),
                diving_data=create_if_exists(DivingData, diving_data.get(row.id)),
                downhill_skiing_data=create_if_exists(
                    DownhillSkiingData, dh_skiing_data.get(row.id)
                ),
                outdoor_planning_data=create_if_exists(
                    OutdoorPlanningData, outdoor_plan_data.get(row.id)
                ),
                outdoor_training_data=create_if_exists(
                    OutdoorTrainingData, outdoor_train_data.get(row.id)
                ),
                gear_maintenance_data=create_if_exists(
                    GearMaintenanceData, gear_maint_data.get(row.id)
                ),
            )

            # Additional logic for names
            canyon = canyoning_data.get(row.id)
            if canyon and canyon.get("template_id"):
                entry.template_name = template_names.get(canyon["template_id"])

            cave = caving_data.get(row.id)
            if cave and cave.get("template_id"):
                entry.template_name = template_names.get(cave["template_id"])

            climb = climbing_data.get(row.id)
            if climb and climb.get("template_id"):
                entry.template_name = template_names.get(climb["template_id"])

            gear = gear_maint_data.get(row.id)
            if gear and gear.get("gear_item_id"):
                entry.gear_item_name = gear_item_names.get(gear["gear_item_id"])

            entries.append(entry)

        return entries
